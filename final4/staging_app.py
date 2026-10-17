"""Isolated synthetic-record staging harness. No production bindings/imports."""

from contextlib import asynccontextmanager
from dataclasses import asdict, replace
import json
import os
from pathlib import Path
import secrets
import tempfile
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from frozen_plate.repository import Repository
from plate_geometry import PlateSpec
from haas_generator.contract import from_dict
from haas_generator.engineering import Parameters
from packaging_generator.generator import Configuration
from .service import DerivedService
from .api import router

ROOT = Path(__file__).resolve().parents[1]


def create_app():
    # Explicit fail-closed startup; unrelated environment keys cannot enable access.
    key = os.environ.get("FINAL4_STAGING_ADMIN_KEY", "")
    if len(key) < 32 or os.environ.get("FINAL4_ENV") != "isolated-synthetic-staging":
        raise ValueError(
            "isolated synthetic staging and dedicated admin credential required"
        )
    if os.environ.get("APP_ENV") == "production":
        raise ValueError("Final 4 harness cannot run in production")
    state = {}

    @asynccontextmanager
    async def lifespan(app):
        # Ephemeral synthetic records only: restarting creates a new test parent, not production data.
        with tempfile.TemporaryDirectory(prefix="final4-synthetic-") as root:
            repo = Repository(Path(root) / "private", secrets.token_urlsafe(48))
            r, p = from_dict(
                json.loads((ROOT / "examples/haas/record.json").read_text()),
                json.loads((ROOT / "examples/haas/profile.json").read_text()),
            )
            s = PlateSpec(
                finished_od=5,
                finished_bore_diameter=r.finished_bore,
                handle_width=2,
                centerline_to_handle_end=10.5,
                material=r.material,
                thickness=r.thickness,
                bore_tolerance=r.bore_tolerance,
                chamfer=False,
                part_identifier=r.part_id,
            )
            plate = repo.create_plate(
                order_id=r.job_id,
                line_id="L1",
                configuration_id="SYNTHETIC",
                customer_id="synthetic-customer",
                actor="staging-harness",
            )
            rev = repo.create_revision(
                plate,
                s,
                expected_current=None,
                reason="synthetic Final 4 acceptance",
                actor="staging-harness",
                source_snapshot={"synthetic": True},
            )
            delivery = repo.create_delivery(rev["id"])
            repo.approve(delivery["token"], "synthetic-customer")
            parent = dict(
                order_id=r.job_id,
                line_id="L1",
                plate_id=plate,
                revision_id=rev["id"],
                spec_sha256=rev["spec_sha256"],
                source_sha256=rev["source_sha256"],
            )
            record = replace(r, top_chamfer_width=0, source_sha256=rev["spec_sha256"])
            service = DerivedService(
                repo,
                machine_profile=p,
                packaging_config=Configuration(
                    **json.loads(
                        (ROOT / "examples/final4/packaging-config.json").read_text()
                    )
                ),
                machining_parameters=Parameters(
                    **json.loads(
                        (ROOT / "examples/final4/machining-parameters.json").read_text()
                    )
                ),
            )
            service.initialize_isolated_sqlite()
            bundles = [
                service.create(
                    f,
                    parent,
                    actor="staging-harness",
                    reviewed_record=asdict(record) if f == "HAAS" else None,
                )
                for f in ("HAAS", "PACKAGING")
            ]
            state.update(
                service=service, parent=parent, record=asdict(record), bundles=bundles
            )
            yield

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

    @app.middleware("http")
    async def bounded_body(request: Request, call_next):
        if request.method == "POST":
            body = bytearray()
            async for chunk in request.stream():
                body.extend(chunk)
                if len(body) > 65536:
                    return JSONResponse(
                        {"detail": "request too large"}, status_code=413
                    )
            request._body = bytes(body)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        return response

    def auth(x_api_key: str | None = Header(default=None)):
        if not x_api_key or not secrets.compare_digest(
            x_api_key.encode(), key.encode()
        ):
            raise HTTPException(401, "Unauthorized")

    @app.get("/health")
    def health():
        return {
            "status": "ok",
            "scope": "isolated-synthetic-staging",
            "manufacturing_release_enabled": False,
        }

    from fastapi import Depends

    @app.get("/admin/manufacturing/synthetic-fixture", dependencies=[Depends(auth)])
    def fixture():
        return {
            "parent": state["parent"],
            "reviewed_record": state["record"],
            "bundles": state["bundles"],
        }

    app.include_router(
        router(auth, lambda: state["service"], server_actor="staging-owner")
    )
    return app
