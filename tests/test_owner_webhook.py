import asyncio
import hashlib
import hmac
import json
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from owner_webhook.app import MAX_BODY_BYTES, UPSTREAM_URL, create_app
import owner_webhook.app as relay

# Synthetic local test credential only; never used in deployed configuration.
SECRET = "whsec_synthetic_local_fixture"


def signed_payload(**changes):
    data = {
        "id": "evt_synthetic",
        "type": "checkout.session.completed",
        "livemode": False,
        "data": {"object": {"id": "cs_test_synthetic"}},
    }
    data.update(changes)
    body = json.dumps(data, indent=2).encode()
    timestamp = str(int(time.time()))
    digest = hmac.new(
        SECRET.encode(), timestamp.encode() + b"." + body, hashlib.sha256
    ).hexdigest()
    return body, {
        "content-type": "application/json",
        "stripe-signature": f"t={timestamp},v1={digest}",
    }


def test_exact_bytes_signature_fixed_destination_and_no_sensitive_response(caplog):
    seen = []

    def forward(request):
        seen.append(request)
        return httpx.Response(
            200, json={"private": "not public"}, headers={"x-private": "hidden"}
        )

    body, headers = signed_payload()
    with TestClient(
        create_app(SECRET, transport=httpx.MockTransport(forward))
    ) as client:
        result = client.post(
            "/stripe/webhook?url=https://evil.invalid", content=body, headers=headers
        )
        assert result.status_code == 200
        assert result.content == b""
        assert "x-private" not in result.headers
        assert client.get("/health").json() == {"ok": True}
        assert client.get("/docs").status_code == 404
        assert client.get("/quote").status_code == 404
        assert client.get("/stripe/webhook").status_code == 405
    assert str(seen[0].url) == UPSTREAM_URL
    assert seen[0].content == body
    assert seen[0].headers["stripe-signature"] == headers["stripe-signature"]
    assert SECRET not in caplog.text
    assert "cs_test_synthetic" not in caplog.text


@pytest.mark.parametrize(
    "case,expected",
    [
        ("invalid", 400),
        ("missing", 400),
        ("stale", 400),
        ("live", 400),
        ("oversized", 413),
        ("stream_oversized", 413),
        ("encoded", 415),
        ("media", 415),
    ],
)
def test_rejections_never_forward(case, expected):
    def forbidden(request):
        pytest.fail("Rejected webhook reached private API")

    body, headers = signed_payload(livemode=case == "live")
    if case == "invalid":
        body += b" "
    elif case == "missing":
        headers.pop("stripe-signature")
    elif case == "stale":
        headers["stripe-signature"] = "t=1,v1=invalid"
    elif case in {"oversized", "stream_oversized"}:
        body = b"x" * (MAX_BODY_BYTES + 1)
    elif case == "encoded":
        headers["content-encoding"] = "gzip"
    elif case == "media":
        headers["content-type"] = "text/plain"
    with TestClient(
        create_app(SECRET, transport=httpx.MockTransport(forbidden))
    ) as client:
        content = iter([body[:100], body[100:]]) if case == "stream_oversized" else body
        assert (
            client.post("/stripe/webhook", content=content, headers=headers).status_code
            == expected
        )


@pytest.mark.parametrize("status", [400, 500, 503, 302])
def test_upstream_status_and_no_redirect_following(status):
    body, headers = signed_payload()
    with TestClient(
        create_app(
            SECRET,
            transport=httpx.MockTransport(
                lambda r: httpx.Response(
                    status, headers={"location": "https://evil.invalid"}
                )
            ),
        )
    ) as client:
        assert client.post(
            "/stripe/webhook", content=body, headers=headers
        ).status_code == (502 if status == 302 else status)


def test_upstream_timeout_is_retryable_and_preserves_capacity():
    def timeout(request):
        raise httpx.ReadTimeout("synthetic", request=request)

    body, headers = signed_payload()
    with TestClient(
        create_app(SECRET, transport=httpx.MockTransport(timeout))
    ) as client:
        for _ in range(6):
            assert (
                client.post(
                    "/stripe/webhook", content=body, headers=headers
                ).status_code
                == 502
            )


def test_replay_is_forwarded_for_existing_api_idempotency():
    calls = []
    body, headers = signed_payload()

    def forward(request):
        calls.append(request.content)
        return httpx.Response(200)

    with TestClient(
        create_app(SECRET, transport=httpx.MockTransport(forward))
    ) as client:
        for _ in range(2):
            assert (
                client.post(
                    "/stripe/webhook", content=body, headers=headers
                ).status_code
                == 200
            )
    assert calls == [body, body]


def test_unneeded_event_acknowledged_without_forwarding():
    body, headers = signed_payload(type="payment_intent.created")
    with TestClient(
        create_app(
            SECRET,
            transport=httpx.MockTransport(lambda r: pytest.fail("Unexpected forward")),
        )
    ) as client:
        assert (
            client.post("/stripe/webhook", content=body, headers=headers).json()[
                "status"
            ]
            == "ignored"
        )


def test_missing_secret_fails_startup(monkeypatch):
    monkeypatch.delenv("STRIPE_WEBHOOK_SECRET", raising=False)
    with pytest.raises(RuntimeError, match="signing secret"):
        with TestClient(create_app()):
            pass


def test_overall_forward_deadline(monkeypatch):
    monkeypatch.setattr(relay, "FORWARD_TIMEOUT_SECONDS", 0.01)

    async def slow(request):
        await asyncio.sleep(0.1)
        return httpx.Response(200)

    body, headers = signed_payload()
    with TestClient(create_app(SECRET, transport=httpx.MockTransport(slow))) as client:
        assert (
            client.post("/stripe/webhook", content=body, headers=headers).status_code
            == 502
        )


def test_body_read_deadline_and_concurrent_capacity(monkeypatch):
    monkeypatch.setattr(relay, "READ_TIMEOUT_SECONDS", 0.01)

    async def exercise():
        started = asyncio.Event()
        release = asyncio.Event()

        async def forward(request):
            started.set()
            await release.wait()
            return httpx.Response(200)

        app = create_app(SECRET, transport=httpx.MockTransport(forward))
        body, headers = signed_payload()

        async def slow_body():
            yield body[:10]
            await asyncio.sleep(0.1)
            yield body[10:]

        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://relay.test"
            ) as client:
                response = await client.post(
                    "/stripe/webhook", content=slow_body(), headers=headers
                )
                assert response.status_code == 408
                requests = [
                    asyncio.create_task(
                        client.post("/stripe/webhook", content=body, headers=headers)
                    )
                    for _ in range(relay.MAX_IN_FLIGHT)
                ]
                await started.wait()
                assert (
                    await client.post("/stripe/webhook", content=body, headers=headers)
                ).status_code == 503
                release.set()
                assert all(
                    r.status_code == 200 for r in await asyncio.gather(*requests)
                )
                assert (
                    await client.post("/stripe/webhook", content=body, headers=headers)
                ).status_code == 200

    asyncio.run(exercise())
