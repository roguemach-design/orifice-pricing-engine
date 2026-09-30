"""Verify TEST webhooks, then forward unchanged bytes to one private API."""

import asyncio
import logging
import os
import time
from contextlib import asynccontextmanager

import httpx
import stripe
from fastapi import FastAPI, HTTPException, Request
from starlette.responses import Response

UPSTREAM_URL = "http://oplates-owner-acceptance-api:10000/stripe/webhook"
MAX_BODY_BYTES = 1024 * 1024
READ_TIMEOUT_SECONDS = 5.0
FORWARD_TIMEOUT_SECONDS = 10.0
MAX_IN_FLIGHT = 4
SUPPORTED_EVENTS = {
    "checkout.session.completed",
    "checkout.session.async_payment_succeeded",
}
logger = logging.getLogger("owner_webhook")


def create_app(signing_secret: str | None = None, *, transport=None) -> FastAPI:
    secret = signing_secret or os.environ.get("STRIPE_WEBHOOK_SECRET", "")

    @asynccontextmanager
    async def lifespan(app):
        if not secret.startswith("whsec_"):
            raise RuntimeError("TEST webhook signing secret must be configured")
        async with httpx.AsyncClient(
            transport=transport,
            timeout=httpx.Timeout(8.0, connect=3.0),
            limits=httpx.Limits(max_connections=MAX_IN_FLIGHT),
            follow_redirects=False,
            trust_env=False,
        ) as client:
            app.state.client = client
            yield

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    slots = asyncio.Semaphore(MAX_IN_FLIGHT)

    @app.get("/health")
    async def health():
        return {"ok": True}

    @app.post("/stripe/webhook")
    async def webhook(request: Request):
        signature = request.headers.get("stripe-signature")
        if not signature or len(signature) > 4096:
            raise HTTPException(400, "Stripe signature required")
        if (
            request.headers.get("content-type", "").split(";")[0].strip().lower()
            != "application/json"
        ):
            raise HTTPException(415, "JSON content required")
        if request.headers.get("content-encoding", "identity").lower() != "identity":
            raise HTTPException(415, "Encoded request bodies are not supported")
        content_length = request.headers.get("content-length")
        if content_length is not None:
            try:
                length = int(content_length)
                if length < 0:
                    raise ValueError
            except ValueError:
                raise HTTPException(400, "Invalid content length") from None
            if length > MAX_BODY_BYTES:
                raise HTTPException(413, "Webhook body too large")
        try:
            await asyncio.wait_for(slots.acquire(), timeout=0.1)
        except TimeoutError:
            raise HTTPException(503, "Webhook capacity exceeded") from None
        started = time.monotonic()
        try:
            body = bytearray()
            try:
                async with asyncio.timeout(READ_TIMEOUT_SECONDS):
                    async for chunk in request.stream():
                        if len(body) + len(chunk) > MAX_BODY_BYTES:
                            raise HTTPException(413, "Webhook body too large")
                        body.extend(chunk)
            except TimeoutError:
                raise HTTPException(408, "Webhook upload timed out") from None
            payload = bytes(body)
            try:
                event = stripe.Webhook.construct_event(payload, signature, secret)
                if not isinstance(event, dict):
                    event = event.to_dict()
            except Exception:
                raise HTTPException(400, "Invalid Stripe webhook") from None
            if event.get("livemode") is not False:
                raise HTTPException(400, "Only TEST events are accepted")
            if event.get("type") not in SUPPORTED_EVENTS:
                return {"ok": True, "status": "ignored"}
            try:
                async with asyncio.timeout(FORWARD_TIMEOUT_SECONDS):
                    async with app.state.client.stream(
                        "POST",
                        UPSTREAM_URL,
                        content=payload,
                        headers={
                            "content-type": "application/json",
                            "stripe-signature": signature,
                        },
                    ) as result:
                        status = result.status_code
                if status not in range(200, 300) and status not in range(400, 600):
                    status = 502
            except (httpx.RequestError, TimeoutError):
                status = 502
            logger.info(
                "webhook_forward status=%d elapsed_ms=%d",
                status,
                int((time.monotonic() - started) * 1000),
            )
            # Never return private API content or headers to the public caller.
            return Response(status_code=status)
        finally:
            slots.release()

    return app


app = create_app()
