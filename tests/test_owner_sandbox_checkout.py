"""Production owner sandbox gates, credential isolation and the real digital thread."""
import hashlib
import hmac
import json
import time
from types import SimpleNamespace

import pytest
import api_app
from test_checkout_workflow import (
    database, checkout_client, checkout_body, completed_session,
)


@pytest.fixture
def sandbox(monkeypatch, checkout_client, tmp_path):
    from frozen_plate import api as frozen_api, delivery
    from frozen_plate.repository import Repository
    from frozen_plate.runtime import PRODUCTION_API
    monkeypatch.setattr(api_app, "APP_ENV", "production")
    monkeypatch.setattr(api_app, "APP_BASE_URL", "https://quote.o-plates.com")
    monkeypatch.setattr(api_app.stripe, "api_key", "rk_live_preserved")
    monkeypatch.setattr(api_app, "STRIPE_TEST_SECRET_KEY", "rk_test_separate")
    monkeypatch.setattr(api_app, "WEBHOOK_SECRET", "whsec_live_separate")
    monkeypatch.setattr(api_app, "STRIPE_TEST_WEBHOOK_SECRET", "whsec_test_separate")
    monkeypatch.setattr(api_app, "ADMIN_API_KEY", "admin-synthetic")
    monkeypatch.setattr(api_app, "SENDGRID_API_KEY", "sendgrid-synthetic")
    for name, value in {
        "OPLATES_OWNER_TEST_CHECKOUT_ENABLED": "true",
        "OPLATES_DRAWING_ASSISTED_ENABLED": "true",
        "OPLATES_DRAWING_ASSISTED_ALLOWED_USER_IDS": "owner",
        "FROZEN_PLATE_ENABLED": "true",
        "FROZEN_PLATE_DATABASE_URL": "synthetic-binding",
        "FROZEN_PLATE_EMAIL_MODE": "send",
        "SENDGRID_API_KEY": "sendgrid-synthetic",
        "FROZEN_PLATE_LIVE_CHECKOUT_READY": "false",
    }.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(api_app, "_decode_supabase_user_id_from_bearer",
                        lambda auth: {"Bearer owner": "owner", "Bearer customer": "customer"}.get(auth))
    repo = Repository(tmp_path, "synthetic-signing-key" * 6)
    repo.delivery_origin = PRODUCTION_API
    repo.part_prefix = "PRD-"
    original = repo.create_delivery
    captures = []
    def capture(rid):
        result = original(rid, base_url=PRODUCTION_API)
        captures.append(result)
        return result
    repo.create_delivery = capture
    monkeypatch.setattr(frozen_api, "repository", lambda: repo)
    deliveries = []
    monkeypatch.setattr(delivery, "deliver_completed_order", lambda r, s, states: deliveries.append((s, states)))
    calls = []
    sessions = {}
    def create(**kwargs):
        calls.append(kwargs)
        sid = "cs_test_owner_synthetic"
        session = completed_session(sid, kwargs["metadata"]["customer_id"])
        session["livemode"] = False
        session["metadata"].update(kwargs["metadata"])
        sessions[sid] = session
        return SimpleNamespace(id=sid, livemode=False, url="https://checkout.stripe.test/owner")
    monkeypatch.setattr(api_app.stripe.checkout.Session, "create", create)
    retrieve_calls = []
    def retrieve(sid, **kwargs):
        retrieve_calls.append(kwargs)
        return sessions[sid]
    monkeypatch.setattr(api_app.stripe.checkout.Session, "retrieve", retrieve)
    return SimpleNamespace(client=checkout_client, repo=repo, calls=calls, sessions=sessions,
                           deliveries=deliveries, retrieve_calls=retrieve_calls, captures=captures)


def headers(user="owner", mode=True):
    return {"Authorization": "Bearer " + user, **({"x-oplates-checkout-mode": "owner_test"} if mode else {})}


@pytest.mark.parametrize("cart", [False, True])
@pytest.mark.parametrize("user,flag,status", [(None, True, 403), ("customer", True, 403), ("owner", False, 403)])
def test_checkout_denies_unverified_or_disabled_owner(sandbox, monkeypatch, user, flag, status, cart):
    monkeypatch.setenv("OPLATES_OWNER_TEST_CHECKOUT_ENABLED", str(flag).lower())
    auth = headers(user) if user else {"x-api-key": "test-ui-key", "x-oplates-checkout-mode": "owner_test"}
    body = {"items": [checkout_body()["inputs"]]} if cart else checkout_body()
    result = sandbox.client.post("/checkout/cart/create" if cart else "/checkout/create", json=body, headers=auth)
    assert result.status_code == (401 if user is None else 503 if not flag else status)
    assert not sandbox.calls


@pytest.mark.parametrize("user", ["owner", "customer"])
def test_server_mode_allows_only_owner_without_client_mode_header(sandbox, user):
    result = sandbox.client.post("/checkout/create", json=checkout_body(), headers=headers(user, mode=False))
    assert result.status_code == (200 if user == "owner" else 403)
    assert len(sandbox.calls) == (1 if user == "owner" else 0)


@pytest.mark.parametrize("setting,value", [("STRIPE_TEST_SECRET_KEY", ""), ("STRIPE_TEST_SECRET_KEY", "rk_live_wrong"),
                                          ("STRIPE_TEST_WEBHOOK_SECRET", ""), ("STRIPE_TEST_WEBHOOK_SECRET", "whsec_live_separate")])
def test_sandbox_never_falls_back_to_live(sandbox, monkeypatch, setting, value):
    monkeypatch.setattr(api_app, setting, value)
    result = sandbox.client.post("/checkout/create", json=checkout_body(), headers=headers())
    assert result.status_code == 503
    assert not sandbox.calls
    assert api_app.stripe.api_key == "rk_live_preserved"


@pytest.mark.parametrize("cart", [False, True])
def test_owner_checkout_persists_test_identity(sandbox, database, cart):
    body = checkout_body(inputs={**checkout_body()["inputs"], "chamfer": False, "chamfer_width": None})
    if cart:
        body = {"items": [body["inputs"]], "idempotency_key": body["idempotency_key"]}
    result = sandbox.client.post("/checkout/cart/create" if cart else "/checkout/create", json=body, headers=headers())
    assert result.status_code == 200, result.text
    call = sandbox.calls[0]
    assert call["api_key"] == "rk_test_separate"
    assert call["metadata"]["oplates_payment_mode"] == "owner_test"
    assert call["idempotency_key"].startswith("owner-test:owner:")
    assert call["success_url"].startswith("https://quote.o-plates.com/Success")
    assert api_app.stripe.api_key == "rk_live_preserved"
    with database() as db:
        order = db.query(api_app.Order).one()
        assert api_app._is_owner_test_order(order)
        assert order.status == "pending"
        assert order.quote_payload["_payment"] == {"mode": "owner_test", "owner_id": "owner", "recipient": "owner@example.test"}


def event_payload(session, live=False):
    return json.dumps({"id": "evt_owner_synthetic", "type": "checkout.session.completed", "livemode": live,
                       "data": {"object": session}}).encode()


def sign(payload, secret):
    timestamp = str(int(time.time()))
    signature = hmac.new(secret.encode(), timestamp.encode() + b"." + payload, hashlib.sha256).hexdigest()
    return {"stripe-signature": "t=" + timestamp + ",v1=" + signature, "content-type": "application/json"}


@pytest.mark.parametrize("path,secret,live,status", [
    ("/stripe/test/webhook", "whsec_live_separate", False, 400),
    ("/stripe/webhook", "whsec_test_separate", False, 400),
    ("/stripe/test/webhook", "whsec_test_separate", True, 400),
    ("/stripe/webhook", "whsec_live_separate", False, 400),
])
def test_actual_signature_and_mode_isolation(sandbox, database, path, secret, live, status):
    payload = event_payload(completed_session(), live=live)
    result = sandbox.client.post(path, content=payload, headers=sign(payload, secret))
    assert result.status_code == status
    with database() as db:
        assert db.query(api_app.Order).count() == 0


def test_unsigned_test_event_rejected(sandbox):
    result = sandbox.client.post("/stripe/test/webhook", content=event_payload(completed_session()))
    assert result.status_code == 400


def test_replay_uses_production_frozen_path_and_exact_approval(sandbox, database, monkeypatch):
    body = checkout_body(inputs={**checkout_body()["inputs"], "chamfer": False, "chamfer_width": None})
    result = sandbox.client.post("/checkout/create", json=body, headers=headers())
    assert result.status_code == 200
    sid = result.json()["session_id"]
    payload = event_payload(sandbox.sessions[sid])
    # Closing the new-purchase gate must not strand an already paid test order.
    monkeypatch.setenv("OPLATES_OWNER_TEST_CHECKOUT_ENABLED", "false")
    for state in ("completed", "already_completed"):
        result = sandbox.client.post("/stripe/test/webhook", content=payload, headers=sign(payload, "whsec_test_separate"))
        assert result.status_code == 200, result.text
        assert result.json()["status"] == state
    assert all(call["api_key"] == "rk_test_separate" for call in sandbox.retrieve_calls)
    with database() as db:
        order = db.query(api_app.Order).one()
        assert order.status == "completed" and order.paid_at
        assert api_app._is_owner_test_order(order)
        snapshot = api_app._frozen_plate_order_snapshot(order.id)
    states = sandbox.deliveries[0][1]
    assert states == sandbox.deliveries[1][1] and states[0]["state"] == "FROZEN"
    revision = sandbox.repo.revision(states[0]["revision_id"])
    assert set(revision["artifacts"]) == {"pdf", "dxf", "json"}
    with sandbox.repo.connect() as db:
        deliveries = db.execute("SELECT * FROM frozen_plate_deliveries").fetchall()
        assert len(deliveries) == 1
        assert db.execute("SELECT COUNT(*) FROM frozen_plate_approvals").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM frozen_plate_sourcing").fetchone()[0] == 0
    assert snapshot["quote_payload"]["_payment"]["mode"] == "owner_test"
    capture = sandbox.captures[0]
    _, pdf = sandbox.repo.customer_pdf(capture["token"], customer_id="owner")
    assert hashlib.sha256(pdf).hexdigest() == revision["artifacts"]["pdf"]["sha256"]
    sandbox.repo.approve(capture["token"], customer_id="owner")
    sandbox.repo.approve(capture["token"], customer_id="owner")
    with sandbox.repo.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM frozen_plate_approvals").fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM frozen_plate_sourcing").fetchone()[0] == 0
    response = sandbox.client.get("/admin/orders", headers={"x-api-key": "admin-synthetic"})
    assert response.json()[0]["payment_mode"] == "OWNER TEST"
    assert api_app.stripe.api_key == "rk_live_preserved"


def test_test_webhook_cannot_complete_unmarked_order(sandbox, database):
    sid = "cs_test_owner_synthetic"
    session = completed_session(sid, "owner")
    session.update(livemode=False)
    session["metadata"]["oplates_payment_mode"] = "owner_test"
    session["metadata"]["test_recipient"] = "owner@example.test"
    sandbox.sessions[sid] = session
    with database() as db:
        db.add(api_app.Order(id="unmarked", stripe_session_id=sid, customer_id="owner",
                            status="pending", quote_payload=checkout_body()["inputs"]))
        db.commit()
    payload = event_payload(session)
    result = sandbox.client.post("/stripe/test/webhook", content=payload, headers=sign(payload, "whsec_test_separate"))
    assert result.status_code == 400
    with database() as db:
        assert db.query(api_app.Order).one().status == "pending"


@pytest.mark.parametrize("user,status", [("owner", 200), ("customer", 403), ("unknown", 401)])
def test_owner_ui_capability_is_server_verified(sandbox, user, status):
    result = sandbox.client.get("/internal/owner-test/access", headers=headers(user))
    assert result.status_code == status


@pytest.mark.parametrize("mutation", ["live_session", "wrong_owner", "missing_marker", "retrieval_failure"])
def test_test_completion_rejects_mismatched_stripe_state(sandbox, database, monkeypatch, mutation):
    result = sandbox.client.post("/checkout/create", json=checkout_body(), headers=headers())
    sid = result.json()["session_id"]
    session = sandbox.sessions[sid]
    if mutation == "live_session":
        session["livemode"] = True
    elif mutation == "wrong_owner":
        session["metadata"]["customer_id"] = "customer"
    elif mutation == "missing_marker":
        session["metadata"].pop("oplates_payment_mode")
    else:
        def unavailable(*args, **kwargs):
            raise RuntimeError("Stripe unavailable")
        monkeypatch.setattr(api_app.stripe.checkout.Session, "retrieve", unavailable)
    payload = event_payload(session)
    result = sandbox.client.post("/stripe/test/webhook", content=payload, headers=sign(payload, "whsec_test_separate"))
    assert result.status_code == (503 if mutation == "retrieval_failure" else 400)
    with database() as db:
        assert db.query(api_app.Order).one().status == "pending"
    assert not sandbox.deliveries


def test_production_owner_cancel_recovery_is_private_and_reprices(sandbox, database):
    result = sandbox.client.post("/checkout/create", json=checkout_body(), headers=headers())
    assert result.status_code == 200
    with database() as db:
        reference = db.query(api_app.Order).one().quote_payload["_checkout_recovery"]["reference"]
    response = sandbox.client.get("/checkout/recovery/" + reference, headers=headers())
    assert response.status_code == 200
    assert response.json()["requires_confirmation"] is True
    assert "_payment" not in response.json()["items"][0]
    assert sandbox.client.get("/checkout/recovery/" + reference, headers=headers("customer")).status_code == 403


@pytest.mark.parametrize("cart", [False, True])
def test_validation_window_blocks_live_even_if_live_readiness_is_enabled(sandbox, monkeypatch, cart):
    monkeypatch.setenv("OPLATES_STRIPE_TEST_VALIDATION_WINDOW", "true")
    monkeypatch.setenv("FROZEN_PLATE_LIVE_CHECKOUT_READY", "true")
    body = {"items": [checkout_body()["inputs"]]} if cart else checkout_body()
    result = sandbox.client.post("/checkout/cart/create" if cart else "/checkout/create", json=body, headers=headers(mode=False))
    assert result.status_code == 200
    assert sandbox.calls[0]["api_key"] == "rk_test_separate"
    assert sandbox.calls[0]["metadata"]["oplates_payment_mode"] == "owner_test"
    result = sandbox.client.post("/checkout/cart/create" if cart else "/checkout/create", json=body, headers=headers())
    assert result.status_code == 200, result.text
    assert sandbox.calls[0]["api_key"] == "rk_test_separate"


def test_validation_window_blocks_live_session_factory(sandbox, monkeypatch):
    monkeypatch.setenv("OPLATES_STRIPE_TEST_VALIDATION_WINDOW", "true")
    with pytest.raises(api_app.HTTPException) as exc:
        api_app._create_checkout_session({"metadata": {}}, False, "owner")
    assert exc.value.status_code == 503
    assert not sandbox.calls
