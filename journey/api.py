"""Origin-checked, bounded telemetry ingestion and protected owner reports."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from functools import partial
import os
import threading
import time
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from pydantic import ValidationError
from .schema import Start, Event
from . import runtime

PRODUCTION_ORIGINS = (
    "https://www.o-plates.com",
    "https://o-plates.com",
    "https://quote.o-plates.com",
)
STAGING_ORIGINS = (
    "https://oplates-landing-page-staging.onrender.com",
    "https://oplates-customer-ui-staging.onrender.com",
)


class Budget:
    def __init__(self):
        self.lock = threading.Lock()
        self.rows = {}

    def check(self, key, limit):
        minute = int(time.monotonic() // 60)
        with self.lock:
            self.rows = {k: v for k, v in self.rows.items() if v[0] == minute}
            stamp, count = self.rows.get(key, (minute, 0))
            if count >= limit:
                raise HTTPException(429, "Telemetry budget reached")
            self.rows[key] = (stamp, count + 1)


budget = Budget()
_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="journey-http")
_slots = asyncio.Semaphore(2)


async def isolated(function, *args):
    try:
        await asyncio.wait_for(_slots.acquire(), timeout=0.02)
    except asyncio.TimeoutError:
        raise HTTPException(429, "Telemetry busy") from None
    try:
        return await asyncio.get_running_loop().run_in_executor(
            _executor, partial(function, *args)
        )
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(503, "Telemetry unavailable") from None
    finally:
        _slots.release()


def origins():
    return (
        PRODUCTION_ORIGINS
        if os.environ.get("APP_ENV") == "production"
        else STAGING_ORIGINS
    )


def install(app, owner_dependency):
    router = APIRouter()

    @app.middleware("http")
    async def journey_boundary(request, call_next):
        if not request.url.path.startswith("/journey/"):
            return await call_next(request)
        origin = request.headers.get("origin")
        if origin not in origins():
            return JSONResponse({"detail": "Origin not accepted"}, status_code=403)
        headers = {
            "Access-Control-Allow-Origin": origin,
            "Vary": "Origin",
            "Cache-Control": "no-store",
            "Access-Control-Allow-Methods": "POST, DELETE, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type, X-Journey-Session",
            "Access-Control-Max-Age": "600",
        }
        if request.method == "OPTIONS":
            return Response(status_code=204, headers=headers)
        if not runtime.enabled():
            return Response(status_code=204, headers=headers)
        try:
            budget.check("global", 300)

            # Stream size is bounded before JSON parsing; no request body logs.
            async def bounded_body():
                body = b""
                async for chunk in request.stream():
                    body += chunk
                    if len(body) > 2048:
                        raise HTTPException(413, "Event too large")
                return body

            try:
                request._body = await asyncio.wait_for(bounded_body(), timeout=3)
            except asyncio.TimeoutError:
                return JSONResponse(
                    {"detail": "Telemetry request timeout"}, 408, headers=headers
                )
        except HTTPException as exc:
            return JSONResponse(
                {"detail": exc.detail}, exc.status_code, headers=headers
            )
        response = await call_next(request)
        for key, value in headers.items():
            response.headers[key] = value
        return response

    def available():
        try:
            store = runtime.get_store()
        except Exception:
            store = None
        if store is None:
            raise HTTPException(503, "Telemetry unavailable")
        return store

    @router.post("/journey/session")
    async def begin(request: Request):
        budget.check("new-sessions", 60)
        try:
            data = Start.model_validate_json(await request.body())
            token = await isolated(lambda: available().start(data.internal))
        except (ValidationError, ValueError):
            raise HTTPException(400, "Invalid telemetry request") from None
        return {"session": token, "expires_in": 86400}

    @router.post("/journey/event")
    async def ingest(request: Request):
        token = request.headers.get("x-journey-session", "")
        # A caller cannot expand the bounded rate map with arbitrary tokens.
        try:
            event = Event.model_validate_json(await request.body())
        except (ValidationError, ValueError):
            raise HTTPException(400, "Invalid telemetry event") from None

        def save():
            store = available()
            try:
                with store.engine.connect() as db:
                    row = store.session(db, token)
                budget.check("session:" + row["id"], 30)
                store.add(token, event)
            except ValueError:
                raise HTTPException(410, "Telemetry session expired") from None

        await isolated(save)
        return Response(status_code=204)

    @router.delete("/journey/session")
    async def revoke(request: Request):
        def remove():
            try:
                available().revoke(request.headers.get("x-journey-session", ""))
            except ValueError:
                pass

        await isolated(remove)
        return Response(status_code=204)

    @router.post("/journey/internal")
    async def mark_internal(request: Request):
        def mark():
            try:
                available().mark_internal(request.headers.get("x-journey-session", ""))
            except ValueError:
                raise HTTPException(400, "Invalid session") from None

        await isolated(mark)
        return Response(status_code=204)

    @router.get("/admin/journey", dependencies=[Depends(owner_dependency)])
    def report(hours: int = 168, internal: bool = False):
        if hours not in (24, 168, 720, 2160):
            raise HTTPException(422, "Unsupported date filter")
        if not runtime.enabled():
            return {
                "enabled": False,
                "message": "Customer journey collection is disabled.",
            }
        result = available().report(hours, internal)
        result.update(enabled=True, coverage=runtime.coverage())
        return JSONResponse(result, headers={"Cache-Control": "no-store"})

    app.include_router(router)
