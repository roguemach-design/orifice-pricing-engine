"""Authenticated staging integration; no email delivery or vendor submission."""

from functools import lru_cache
from hashlib import sha256
import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response, HTMLResponse
from pydantic import BaseModel, ConfigDict, Field

from .order_adapter import specification_from_order
from .repository import WorkflowError, canonical
from .presentation import success_html, page
from .staging import StagingRepository
from .orders import freeze_line, complete_order
from html import escape
from urllib.parse import quote


class FreezeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    line_index: int = Field(ge=0)
    part_identifier: str = Field(pattern=r"^[A-Za-z0-9_-]{1,40}$")
    expected_current: str | None = None
    reason: str = Field(min_length=1, max_length=500)


class TokenRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: str = Field(min_length=1, max_length=2048)


class RouteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    route: str


@lru_cache(maxsize=1)
def repository():
    return StagingRepository()


def router(customer_auth, admin_auth, load_order):
    routes = APIRouter()

    def _records(repo, table, revision_id):
        with repo.connect() as db:
            return [
                dict(r)
                for r in db.execute(
                    f"SELECT * FROM {table} WHERE revision_id=?", (revision_id,)
                )
            ]

    def run(action):
        try:
            return action()
        except (WorkflowError, ValueError, KeyError):
            raise HTTPException(
                409, "Frozen Plate request unavailable or no longer current"
            ) from None

    @routes.post(
        "/admin/frozen-plates/orders/{order_id}", dependencies=[Depends(admin_auth)]
    )
    def freeze(order_id: str, body: FreezeRequest):
        return run(
            lambda: freeze_line(
                repository(),
                load_order(order_id),
                body.line_index,
                body.part_identifier,
                expected_current=body.expected_current,
                reason=body.reason,
                revision=True,
            )
        )

    @routes.post(
        "/admin/frozen-plates/orders/{order_id}/complete",
        dependencies=[Depends(admin_auth)],
    )
    def retry_completed(order_id: str):
        return run(lambda: complete_order(repository(), load_order(order_id)))

    @routes.api_route("/approve/{token}", methods=["GET", "HEAD"])
    def landing(token: str):
        # No token resolution or mutation on passive requests. No automatic approval POST.
        if len(token) > 2048:
            raise HTTPException(400, "Invalid link")
        url = (
            "https://oplates-customer-ui-staging.onrender.com/Drawing_Approval?token="
            + quote(token, safe="")
        )
        return HTMLResponse(
            page(
                '<h1>Review your attached drawing</h1><p>Sign in to review the exact PDF and deliberately approve it.</p><a class="button" href="'
                + escape(url, quote=True)
                + '">SIGN IN &amp; REVIEW DRAWING</a>'
            ),
            headers={
                "Cache-Control": "no-store",
                "Referrer-Policy": "no-referrer",
                "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; frame-ancestors 'none'",
            },
        )

    @routes.get("/admin/frozen-plates", dependencies=[Depends(admin_auth)])
    def plates(order_id: str):
        with repository().connect() as db:
            return [
                dict(r)
                for r in db.execute(
                    "SELECT * FROM frozen_plates WHERE order_id=? ORDER BY line_id",
                    (order_id,),
                )
            ]

    @routes.get(
        "/admin/frozen-plates/deliveries/{delivery_id}/capture",
        dependencies=[Depends(admin_auth)],
    )
    def capture(delivery_id: str):
        def read():
            repo = repository()
            with repo.connect() as db:
                delivery = repo._one(
                    db,
                    "SELECT * FROM frozen_plate_deliveries WHERE id=?",
                    (delivery_id,),
                )
            content = repo.storage.get("confirmation/" + delivery["id"] + ".eml")
            if sha256(content).hexdigest() != delivery["mime_sha256"]:
                raise WorkflowError("capture integrity failure")
            return content

        return Response(
            run(read),
            media_type="message/rfc822",
            headers={"Cache-Control": "no-store"},
        )

    @routes.get("/me/orders/{order_id}/frozen-plates")
    def customer_plates(order_id: str, customer_id=Depends(customer_auth)):
        repo = repository()
        with repo.connect() as db:
            return [
                dict(r)
                for r in db.execute(
                    "SELECT id,line_id,current_revision,lifecycle FROM frozen_plates WHERE order_id=? AND customer_id=? ORDER BY line_id",
                    (order_id, customer_id),
                )
            ]

    @routes.post("/me/frozen-plates/{plate_id}/confirmation")
    def confirmation(plate_id: str, customer_id=Depends(customer_auth)):
        repo = repository()
        plate = run(lambda: repo.plate(plate_id))
        if plate["customer_id"] != customer_id:
            raise HTTPException(404, "Not found")
        delivery = run(lambda: repo.create_delivery(plate["current_revision"]))
        return {
            "token": delivery["token"],
            "context": delivery["context"],
            "email_sent": False,
        }

    @routes.post("/me/frozen-plates/inspect")
    def inspect(body: TokenRequest, customer_id=Depends(customer_auth)):
        return run(lambda: repository().inspect_token(body.token, customer_id))

    @routes.post("/me/frozen-plates/pdf")
    def pdf(body: TokenRequest, customer_id=Depends(customer_auth)):
        filename, content = run(
            lambda: repository().customer_pdf(body.token, customer_id)
        )
        return Response(
            content,
            media_type="application/pdf",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "Cache-Control": "no-store",
            },
        )

    @routes.post("/me/frozen-plates/approve")
    def approve(body: TokenRequest, customer_id=Depends(customer_auth)):
        result = run(lambda: repository().approve(body.token, customer_id))
        return {
            "state": result["state"],
            "context": result["context"],
            "success_html": success_html(
                result["context"],
                result["approval"]["approved_at"],
                result["historical"],
            ),
        }

    @routes.get("/admin/frozen-plates/{plate_id}", dependencies=[Depends(admin_auth)])
    def internal(plate_id: str):
        repo = repository()
        plate = run(lambda: repo.plate(plate_id))
        return {
            "plate": plate,
            "revision": (
                repo.revision(plate["current_revision"])
                if plate["current_revision"]
                else None
            ),
            "deliveries": _records(
                repo, "frozen_plate_deliveries", plate["current_revision"]
            ),
            "approvals": _records(
                repo, "frozen_plate_approvals", plate["current_revision"]
            ),
            "sourcing": _records(
                repo, "frozen_plate_sourcing", plate["current_revision"]
            ),
        }

    @routes.post(
        "/admin/frozen-plates/revisions/{revision_id}/source",
        dependencies=[Depends(admin_auth)],
    )
    def source(revision_id: str, body: RouteRequest):
        return run(
            lambda: repository().select_source(
                revision_id, body.route, actor="staging-admin"
            )
        )

    @routes.get(
        "/admin/frozen-plates/revisions/{revision_id}/dxf",
        dependencies=[Depends(admin_auth)],
    )
    def dxf(revision_id: str):
        repo = repository()

        def read():
            with repo.transaction() as db:
                revision, artifacts, contents = repo._verified(db, revision_id)
                plate = repo._one(
                    db,
                    "SELECT * FROM frozen_plates WHERE id=?",
                    (revision["plate_id"],),
                )
                if plate["current_revision"] != revision_id:
                    raise WorkflowError("superseded")
                approval = repo._one(
                    db,
                    "SELECT * FROM frozen_plate_approvals WHERE revision_id=?",
                    (revision_id,),
                )
                if (
                    approval["pdf_sha256"] != artifacts["pdf"]["sha256"]
                    or approval["spec_sha256"] != revision["spec_sha256"]
                ):
                    raise WorkflowError("approval integrity failure")
                return artifacts["dxf"], contents["dxf"]

        artifact, content = run(read)
        return Response(
            content,
            media_type="application/dxf",
            headers={
                "Content-Disposition": f'attachment; filename="{artifact["filename"]}"',
                "X-Artifact-SHA256": artifact["sha256"],
                "Cache-Control": "no-store",
            },
        )

    return routes
