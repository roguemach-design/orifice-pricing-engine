"""Loopback-only demonstration of authenticated one-action POST approval.

Customer sessions are provisioned by the local fixture, never by visiting a
bearer link. Production must inject its verified Supabase customer principal.
Internal routes use the existing application's constant-time x-api-key pattern,
with a separate prototype-only key; api_app is deliberately never imported.
"""

from hashlib import sha256
from html import escape
import secrets
from urllib.parse import parse_qs

from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.responses import HTMLResponse, Response, RedirectResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware
from itsdangerous import URLSafeTimedSerializer, BadSignature
from pydantic import BaseModel, ConfigDict
from .repository import WorkflowError, ROUTES
from .presentation import email_html, success_html, message_html, page

ORIGIN = "http://127.0.0.1:8765"


class LocalSessions:
    def __init__(self, key):
        if len(key) < 32:
            raise ValueError("separate random session key required")
        self.signer = URLSafeTimedSerializer(
            key,
            salt="frozen-plate-local-session-v1",
            signer_kwargs={"digest_method": sha256},
        )

    def issue(self, customer_id):
        # Local harness only; intentionally no HTTP login or auto-login endpoint.
        csrf = secrets.token_urlsafe(32)
        return self.signer.dumps({"customer_id": customer_id, "csrf": csrf}), csrf

    def read(self, request):
        try:
            return self.signer.loads(
                request.cookies.get("fp_local_session", ""), max_age=3600
            )
        except BadSignature as exc:
            raise HTTPException(401, "Customer session required") from exc


class SourceSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    route: str


def create_app(repository, *, session_key, admin_key):
    if len(admin_key) < 32:
        raise ValueError("dedicated prototype admin key required")
    app = FastAPI(
        title="Frozen Plate — LOCAL PROTOTYPE",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "testserver"])
    sessions = LocalSessions(session_key)
    app.state.local_sessions = sessions

    @app.middleware("http")
    async def security_headers(request, call_next):
        response = await call_next(request)
        response.headers.update(
            {
                "Cache-Control": "no-store",
                "Referrer-Policy": "no-referrer",
                "X-Content-Type-Options": "nosniff",
                "X-Frame-Options": "DENY",
                "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'",
            }
        )
        return response

    @app.exception_handler(WorkflowError)
    async def safe_error(request, exc):
        return HTMLResponse(
            message_html("superseded" if str(exc) == "superseded" else "invalid"),
            status_code=409,
        )

    def customer(request: Request):
        return sessions.read(request)

    def internal(request: Request):
        provided = request.headers.get("x-api-key", "")
        if not provided or not secrets.compare_digest(
            provided.encode(), admin_key.encode()
        ):
            raise HTTPException(401, "Unauthorized")
        return "prototype-internal-admin"

    def result_html(result):
        if result["state"] == "approved":
            return success_html(
                result["context"],
                result["approval"]["approved_at"],
                result["historical"],
            )
        return message_html(result["state"])

    @app.get("/approve/{token}", response_class=HTMLResponse)
    @app.head("/approve/{token}", response_class=HTMLResponse)
    def status(token: str, session=Depends(customer)):
        return result_html(repository.inspect_token(token, session["customer_id"]))

    @app.get("/local-email/{token}", response_class=HTMLResponse)
    def preview(token: str, session=Depends(customer)):
        result = repository.inspect_token(token, session["customer_id"])
        if result["state"] != "pending":
            return result_html(result)
        return email_html(
            result["context"],
            "/approve/" + token,
            csrf=session["csrf"],
            pdf_url="/attachment/" + token,
        )

    @app.post("/approve/{token}")
    async def approve(token: str, request: Request, session=Depends(customer)):
        if request.headers.get("origin") != ORIGIN or request.headers.get(
            "sec-fetch-site"
        ) not in (None, "same-origin"):
            raise HTTPException(403, "Invalid request origin")
        if (
            request.headers.get("content-type", "").split(";")[0]
            != "application/x-www-form-urlencoded"
        ):
            raise HTTPException(415, "Expected approval form")
        body = await request.body()
        if len(body) > 2048:
            raise HTTPException(413, "Approval request too large")
        fields = parse_qs(body.decode("utf-8", errors="replace"))
        values = fields.get("csrf", [])
        if len(values) != 1 or not secrets.compare_digest(
            values[0].encode(), session["csrf"].encode()
        ):
            raise HTTPException(403, "Invalid approval request")
        repository.approve(token, session["customer_id"])
        return RedirectResponse("/approve/" + token, status_code=303)

    @app.get("/attachment/{token}")
    def attachment(token: str, session=Depends(customer)):
        filename, data = repository.customer_pdf(token, session["customer_id"])
        return Response(
            data,
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    @app.get("/internal/revisions/{revision_id}/source", response_class=HTMLResponse)
    def source_control(revision_id: str, actor=Depends(internal)):
        revision = repository.revision(revision_id)
        artifact = revision["artifacts"]["dxf"]
        # Internal API-backed control; authenticated tooling submits the JSON POST.
        return page(
            '<p class="eyebrow">INTERNAL · LOCAL PROTOTYPE</p><h1>SOURCE ROUGH BLANK</h1>'
            + f'<p>{escape(artifact["filename"])}</p><p>Exact revision DXF SHA-256:<br><code>{artifact["sha256"]}</code></p>'
            + f'<form action="/internal/revisions/{escape(revision_id)}/source" method="post"><select name="route" aria-label="Rough blank source">'
            + "".join(f"<option>{r}</option>" for r in ROUTES)
            + '</select><p><button type="submit">RECORD LOCAL SOURCE SELECTION</button></p></form>'
            + "<p>Use the authenticated source-selection API to record a local option. No quote, vendor submission or machine action is enabled.</p>"
        )

    @app.post("/internal/revisions/{revision_id}/source")
    async def select_source(
        revision_id: str, request: Request, actor=Depends(internal)
    ):
        if (
            request.headers.get("content-type", "").split(";")[0]
            == "application/x-www-form-urlencoded"
        ):
            if request.headers.get("origin") != ORIGIN:
                raise HTTPException(403, "Invalid request origin")
            fields = parse_qs((await request.body()).decode("utf-8", errors="replace"))
            if set(fields) != {"route"} or len(fields["route"]) != 1:
                raise HTTPException(422, "One route required")
            route = fields["route"][0]
        else:
            from pydantic import ValidationError

            try:
                route = SourceSelection.model_validate(await request.json()).route
            except (ValidationError, ValueError):
                raise HTTPException(422, "One route required")
        return repository.select_source(revision_id, route, actor=actor)

    return app
