"""Separate admin service. Never mounted by api_app.py or customer apps."""

from dataclasses import asdict
from io import BytesIO
from pathlib import Path
import secrets
from zipfile import ZIP_STORED, ZipFile, ZipInfo

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from .contract import MachineProfile, ReviewedRecord, construct, loads
from .generator import generate

MAX_BODY = 32768


def archive(files):
    output = BytesIO()
    with ZipFile(output, "w", compression=ZIP_STORED) as bundle:
        for name, contents in sorted(files.items()):
            info = ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = 0o100600 << 16
            bundle.writestr(info, contents.encode("ascii"))
    return output.getvalue()


def create_app(*, admin_key, profile):
    if not isinstance(admin_key, str) or len(admin_key) < 32 or not admin_key.isascii():
        raise ValueError(
            "dedicated HAAS_ADMIN_KEY of at least 32 ASCII characters required"
        )
    # Validate and copy trusted server-owned profile at app construction.
    trusted = construct(MachineProfile, asdict(profile))
    app = FastAPI(
        title="O-Plates internal Haas review",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    basic = HTTPBasic(auto_error=False)

    def admin(credentials: HTTPBasicCredentials | None = Depends(basic)):
        valid = (
            credentials is not None
            and secrets.compare_digest(credentials.username.encode(), b"admin")
            and secrets.compare_digest(
                credentials.password.encode(), admin_key.encode()
            )
        )
        if not valid:
            raise HTTPException(
                401,
                "Admin authentication required",
                headers={"WWW-Authenticate": "Basic"},
            )

    @app.middleware("http")
    async def private_response(request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    @app.get("/", response_class=HTMLResponse, dependencies=[Depends(admin)])
    def home():
        return Path(__file__).with_name("admin.html").read_text(encoding="utf-8")

    @app.get("/profile", dependencies=[Depends(admin)])
    def machine_profile():
        return {"profile": asdict(trusted), "holds": trusted.holds}

    @app.post("/generate", dependencies=[Depends(admin)])
    async def bundle(request: Request):
        data = bytearray()
        async for chunk in request.stream():
            data.extend(chunk)
            if len(data) > MAX_BODY:
                raise HTTPException(413, "Reviewed record exceeds size limit")
        try:
            record = construct(ReviewedRecord, loads(data.decode("utf-8")))
            files = generate(record, trusted)
        except (ValueError, UnicodeError) as exc:
            raise HTTPException(422, str(exc)) from exc
        return Response(
            archive(files),
            media_type="application/zip",
            headers={
                "Content-Disposition": 'attachment; filename="haas-review.zip"',
            },
        )

    return app
