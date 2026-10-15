"""Owner API factory. Mount with EXISTING admin auth; no public/customer generation."""

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.routing import APIRoute
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field
from frozen_plate.repository import WorkflowError


class Association(BaseModel):
    model_config = ConfigDict(extra="forbid")
    order_id: str = Field(min_length=1, max_length=100)
    line_id: str = Field(min_length=1, max_length=100)
    plate_id: str = Field(min_length=1, max_length=100)
    revision_id: str = Field(min_length=1, max_length=100)
    spec_sha256: str = Field(pattern="^[0-9a-f]{64}$")
    source_sha256: str = Field(pattern="^[0-9a-f]{64}$")


class GenerateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    parent: Association
    family: str = Field(pattern="^(HAAS|PACKAGING)$")
    reviewed_record: dict | None = None


class BoundedRoute(APIRoute):
    def get_route_handler(self):
        original = super().get_route_handler()

        async def bounded(request: Request):
            if request.method == "POST":
                data = bytearray()
                async for chunk in request.stream():
                    data.extend(chunk)
                    if len(data) > 65536:
                        raise HTTPException(413, "Manufacturing request too large")
                request._body = bytes(data)
            return await original(request)

        return bounded


def router(admin_auth, get_service, *, server_actor):
    r = APIRouter(
        prefix="/admin/manufacturing",
        dependencies=[Depends(admin_auth)],
        route_class=BoundedRoute,
    )

    def run(action):
        try:
            return action()
        except (WorkflowError, ValueError, KeyError, TypeError):
            raise HTTPException(
                409,
                "Manufacturing artifact unavailable, incompatible or verification failed",
            ) from None

    @r.post("/bundles")
    def create(body: GenerateRequest):
        return run(
            lambda: get_service().create(
                body.family,
                body.parent.model_dump(),
                actor=server_actor,
                reviewed_record=body.reviewed_record,
            )
        )

    @r.post("/bundles/query")
    def query(body: Association):
        return run(lambda: get_service().list(body.model_dump()))

    @r.get("/bundles/{bundle_id}")
    def metadata(bundle_id: str):
        return run(lambda: get_service().metadata(bundle_id))

    @r.get("/bundles/{bundle_id}/files/{name}")
    def download(bundle_id: str, name: str):
        filename, hash_, data = run(lambda: get_service().download(bundle_id, name))
        media = (
            "application/dxf" if name.endswith(".dxf") else "application/octet-stream"
        )
        return Response(
            data,
            media_type=media,
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "X-Artifact-SHA256": hash_,
                "X-Artifact-Verified": "true",
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
            },
        )

    return r
