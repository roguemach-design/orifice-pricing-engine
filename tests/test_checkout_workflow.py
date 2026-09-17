from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import api_app


def quote_inputs(**overrides):
    values = {
        "quantity": 1,
        "material": "304",
        "thickness": 0.125,
        "handle_width": 1.5,
        "handle_length_from_bore": 9.0,
        "paddle_dia": 3.0,
        "bore_dia": 1.0,
        "bore_tolerance": 0.005,
        "chamfer": True,
        "chamfer_width": 0.062,
        "handle_label": "UPSTREAM",
        "ships_in_days": 14,
    }
    values.update(overrides)
    return values


def checkout_body(**overrides):
    body = {
        "inputs": quote_inputs(),
        "configuration_id": "configuration-test",
        "pricing_config_version": "version-current",
        "idempotency_key": "00000000-0000-4000-8000-000000000001",
    }
    body.update(overrides)
    return body


def authoritative_result(inputs):
    return {
        "unit_price": 125.0,
        "total_price": 125.0 * inputs.quantity,
        "total_price_cents": 12500 * inputs.quantity,
        "pricing_config_version": "version-current",
        "shipping": {
            "ups_ground_cents": 1500,
            "ups_2day_cents": 3000,
            "ups_nextday_cents": 5000,
        },
    }


@pytest.fixture
def database(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    api_app.Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(api_app, "SessionLocal", factory)
    yield factory
    api_app.Base.metadata.drop_all(bind=engine)
    engine.dispose()


@pytest.fixture
def checkout_client(monkeypatch, database):
    monkeypatch.setattr(api_app, "API_KEY", "test-ui-key")
    monkeypatch.setattr(api_app, "APP_ENV", "test")
    monkeypatch.setattr(api_app, "APP_BASE_URL", "https://quote.staging.example.test")
    monkeypatch.setattr(api_app.stripe, "api_key", "sk_test_unit")
    monkeypatch.setattr(
        api_app,
        "_calculate_quote_with_db_knobs",
        authoritative_result,
    )
    return TestClient(api_app.app)


def install_idempotent_stripe(monkeypatch):
    calls = []
    sessions = {}

    def create(**kwargs):
        calls.append(kwargs)
        key = kwargs.get("idempotency_key") or f"call-{len(calls)}"
        if key not in sessions:
            sessions[key] = SimpleNamespace(
                id=f"cs_test_{len(sessions) + 1}",
                url=f"https://checkout.stripe.test/{len(sessions) + 1}",
            )
        return sessions[key]

    monkeypatch.setattr(api_app.stripe.checkout.Session, "create", create)
    return calls


def completed_session(session_id="cs_test_1", customer_id=""):
    return {
        "id": session_id,
        "payment_status": "paid",
        "payment_intent": "pi_test_1",
        "amount_total": 14000,
        "amount_subtotal": 12500,
        "shipping_cost": {
            "amount_total": 1500,
            "shipping_rate": {
                "metadata": {"service": "ups_ground"},
                "display_name": "UPS Ground",
            },
        },
        "customer_details": {
            "email": "buyer@example.com",
            "name": "Test Buyer",
            "address": {
                "line1": "1 Test Way",
                "city": "Wheeling",
                "state": "WV",
                "postal_code": "26003",
                "country": "US",
            },
        },
        "shipping_details": {},
        "metadata": {"customer_id": customer_id},
    }


def install_completed_webhook(monkeypatch, session):
    event = {
        "id": "evt_test_completed_1",
        "type": "checkout.session.completed",
        "data": {"object": {"id": session["id"]}},
    }
    monkeypatch.setattr(api_app, "WEBHOOK_SECRET", "whsec_test")
    monkeypatch.setattr(
        api_app.stripe.Webhook,
        "construct_event",
        lambda payload, signature, secret: event,
    )
    monkeypatch.setattr(
        api_app.stripe.checkout.Session,
        "retrieve",
        lambda *args, **kwargs: session,
    )


def test_guest_checkout_reprices_persists_pending_and_is_idempotent(
    monkeypatch, checkout_client, database
):
    calls = install_idempotent_stripe(monkeypatch)
    headers = {"x-api-key": "test-ui-key"}

    first = checkout_client.post("/checkout/create", json=checkout_body(), headers=headers)
    duplicate = checkout_client.post("/checkout/create", json=checkout_body(), headers=headers)

    assert first.status_code == 200
    assert duplicate.status_code == 200
    assert first.json() == duplicate.json()
    assert calls[0]["idempotency_key"] == checkout_body()["idempotency_key"]
    assert calls[0]["success_url"].endswith(
        "/Success?session_id={CHECKOUT_SESSION_ID}"
    )
    assert calls[0]["cancel_url"].endswith("/Quote?checkout=cancelled")
    assert calls[0]["line_items"][0]["price_data"]["unit_amount"] == 12500

    db = database()
    try:
        orders = db.query(api_app.Order).all()
        assert len(orders) == 1
        assert orders[0].status == "pending"
        assert orders[0].customer_id is None
        assert orders[0].quote_payload["chamfer_width"] == 0.062
    finally:
        db.close()


def test_checkout_rejects_stale_pricing_before_stripe(
    monkeypatch, checkout_client
):
    calls = install_idempotent_stripe(monkeypatch)
    response = checkout_client.post(
        "/checkout/create",
        json=checkout_body(pricing_config_version="version-stale"),
        headers={"x-api-key": "test-ui-key"},
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "pricing_changed"
    assert calls == []


def test_customer_identity_cannot_be_supplied_in_checkout_body(
    checkout_client,
):
    response = checkout_client.post(
        "/checkout/create",
        json=checkout_body(customer_id="attacker-controlled"),
        headers={"x-api-key": "test-ui-key"},
    )

    assert response.status_code == 422


def test_verified_bearer_identity_wins_when_ui_key_is_also_present(
    monkeypatch, checkout_client, database
):
    install_idempotent_stripe(monkeypatch)
    monkeypatch.setattr(
        api_app,
        "_decode_supabase_user_id_from_bearer",
        lambda authorization: "verified-user" if authorization == "Bearer valid" else None,
    )

    response = checkout_client.post(
        "/checkout/create",
        json=checkout_body(),
        headers={"Authorization": "Bearer valid", "x-api-key": "test-ui-key"},
    )

    assert response.status_code == 200
    db = database()
    try:
        order = db.query(api_app.Order).one()
        assert order.customer_id == "verified-user"
    finally:
        db.close()


def test_invalid_bearer_cannot_downgrade_to_guest_with_valid_ui_key(
    monkeypatch, checkout_client
):
    calls = install_idempotent_stripe(monkeypatch)
    monkeypatch.setattr(
        api_app,
        "_decode_supabase_user_id_from_bearer",
        lambda authorization: None,
    )

    response = checkout_client.post(
        "/checkout/create",
        json=checkout_body(),
        headers={"Authorization": "Bearer invalid", "x-api-key": "test-ui-key"},
    )

    assert response.status_code == 401
    assert calls == []


def test_authenticated_cart_checkout_uses_verified_user_and_idempotency(
    monkeypatch, checkout_client, database
):
    calls = install_idempotent_stripe(monkeypatch)
    monkeypatch.setattr(
        api_app,
        "_decode_supabase_user_id_from_bearer",
        lambda authorization: (
            "verified-user" if authorization == "Bearer verified-token" else None
        ),
    )
    body = {
        "items": [quote_inputs(), quote_inputs(quantity=2)],
        "pricing_config_version": "version-current",
        "idempotency_key": "00000000-0000-4000-8000-000000000099",
    }
    headers = {"Authorization": "Bearer verified-token"}

    first = checkout_client.post(
        "/checkout/cart/create",
        json=body,
        headers=headers,
    )
    duplicate = checkout_client.post(
        "/checkout/cart/create",
        json=body,
        headers=headers,
    )

    assert first.status_code == 200
    assert duplicate.json() == first.json()
    assert calls[0]["idempotency_key"] == body["idempotency_key"]
    assert calls[0]["metadata"]["customer_id"] == "verified-user"
    assert calls[0]["metadata"]["pricing_config_version"] == "version-current"
    assert calls[0]["cancel_url"].endswith(
        "/Quote_Cart?checkout=cancelled"
    )

    db = database()
    try:
        orders = db.query(api_app.Order).all()
        assert len(orders) == 1
        assert orders[0].customer_id == "verified-user"
        assert len(orders[0].quote_payload["cart_items"]) == 2
    finally:
        db.close()


def test_cart_checkout_rejects_stale_pricing_before_stripe(
    monkeypatch, checkout_client
):
    calls = install_idempotent_stripe(monkeypatch)
    monkeypatch.setattr(
        api_app,
        "_decode_supabase_user_id_from_bearer",
        lambda authorization: "verified-user",
    )

    response = checkout_client.post(
        "/checkout/cart/create",
        json={
            "items": [quote_inputs()],
            "pricing_config_version": "version-stale",
            "idempotency_key": "00000000-0000-4000-8000-000000000098",
        },
        headers={"Authorization": "Bearer verified-token"},
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "pricing_changed"
    assert calls == []


def test_staging_rejects_live_stripe_key(monkeypatch, checkout_client):
    monkeypatch.setattr(api_app.stripe, "api_key", "sk_live_forbidden")
    response = checkout_client.post(
        "/checkout/create",
        json=checkout_body(),
        headers={"x-api-key": "test-ui-key"},
    )

    assert response.status_code == 500
    assert response.json()["detail"] == "Staging checkout requires Stripe test mode."


def test_checkout_fails_closed_when_app_environment_is_not_explicit(
    monkeypatch, checkout_client
):
    monkeypatch.setattr(api_app, "APP_ENV", "unset")

    response = checkout_client.post(
        "/checkout/create",
        json=checkout_body(),
        headers={"x-api-key": "test-ui-key"},
    )

    assert response.status_code == 500
    assert response.json()["detail"] == (
        "Checkout environment is not configured (set APP_ENV)."
    )


def test_checkout_fails_closed_when_return_url_is_not_explicit(
    monkeypatch, checkout_client
):
    monkeypatch.setattr(api_app, "APP_BASE_URL", "")

    response = checkout_client.post(
        "/checkout/create",
        json=checkout_body(),
        headers={"x-api-key": "test-ui-key"},
    )

    assert response.status_code == 500
    assert response.json()["detail"] == (
        "Checkout return URL is not configured (set APP_BASE_URL to an HTTPS URL)."
    )


def test_checkout_database_failure_returns_retryable_error(
    monkeypatch, checkout_client
):
    install_idempotent_stripe(monkeypatch)

    class FailingSession:
        def query(self, *args, **kwargs):
            raise RuntimeError("database unavailable")

        def rollback(self):
            pass

        def close(self):
            pass

    monkeypatch.setattr(api_app, "SessionLocal", lambda: FailingSession())
    response = checkout_client.post(
        "/checkout/create",
        json=checkout_body(),
        headers={"x-api-key": "test-ui-key"},
    )

    assert response.status_code == 503
    assert response.json()["detail"] == (
        "Checkout could not be initialized. Please try again."
    )


def test_checkout_retry_reuses_stripe_session_after_transient_database_failure(
    monkeypatch, checkout_client, database
):
    calls = install_idempotent_stripe(monkeypatch)

    class FailingSession:
        def query(self, *args, **kwargs):
            raise RuntimeError("database unavailable")

        def rollback(self):
            pass

        def close(self):
            pass

    attempts = {"count": 0}

    def flaky_session_factory():
        attempts["count"] += 1
        if attempts["count"] == 1:
            return FailingSession()
        return database()

    monkeypatch.setattr(api_app, "SessionLocal", flaky_session_factory)
    headers = {"x-api-key": "test-ui-key"}

    failed = checkout_client.post("/checkout/create", json=checkout_body(), headers=headers)
    retried = checkout_client.post("/checkout/create", json=checkout_body(), headers=headers)

    assert failed.status_code == 503
    assert retried.status_code == 200
    assert len(calls) == 2
    assert calls[0]["idempotency_key"] == calls[1]["idempotency_key"]
    assert retried.json()["session_id"] == "cs_test_1"

    db = database()
    try:
        assert db.query(api_app.Order).count() == 1
    finally:
        db.close()


def test_completed_webhook_updates_once_and_replay_does_not_duplicate(
    monkeypatch, checkout_client, database
):
    calls = install_idempotent_stripe(monkeypatch)
    checkout_response = checkout_client.post(
        "/checkout/create",
        json=checkout_body(),
        headers={"x-api-key": "test-ui-key"},
    )
    assert checkout_response.status_code == 200
    assert calls

    session = completed_session(checkout_response.json()["session_id"])
    install_completed_webhook(monkeypatch, session)
    sent_emails = []
    monkeypatch.setattr(
        api_app,
        "_send_email",
        lambda to_email, subject, html: sent_emails.append(to_email),
    )

    first = checkout_client.post(
        "/stripe/webhook",
        content=b"{}",
        headers={"stripe-signature": "valid"},
    )
    replay = checkout_client.post(
        "/stripe/webhook",
        content=b"{}",
        headers={"stripe-signature": "valid"},
    )

    assert first.status_code == 200
    assert first.json()["status"] == "completed"
    assert replay.status_code == 200
    assert replay.json()["status"] == "already_completed"
    assert sent_emails == ["buyer@example.com"]

    db = database()
    try:
        orders = db.query(api_app.Order).all()
        assert len(orders) == 1
        order = orders[0]
        assert order.status == "completed"
        assert order.order_number == 1
        assert order.stripe_payment_intent == "pi_test_1"
        assert order.last_stripe_event_id == "evt_test_completed_1"
        assert order.paid_at is not None
    finally:
        db.close()


def test_completed_webhook_accepts_stripe_session_objects(
    monkeypatch, checkout_client, database
):
    install_idempotent_stripe(monkeypatch)
    checkout_response = checkout_client.post(
        "/checkout/create",
        json=checkout_body(),
        headers={"x-api-key": "test-ui-key"},
    )
    session_id = checkout_response.json()["session_id"]

    class StripeSessionObject:
        def __init__(self, values):
            self.values = values

        def to_dict_recursive(self):
            return self.values

    monkeypatch.setattr(api_app, "WEBHOOK_SECRET", "whsec_test")
    monkeypatch.setattr(
        api_app.stripe.Webhook,
        "construct_event",
        lambda payload, signature, secret: {
            "id": "evt_test_stripe_object",
            "type": "checkout.session.completed",
            "data": {"object": StripeSessionObject({"id": session_id})},
        },
    )
    monkeypatch.setattr(
        api_app.stripe.checkout.Session,
        "retrieve",
        lambda *args, **kwargs: StripeSessionObject(completed_session(session_id)),
    )
    monkeypatch.setattr(api_app, "_send_email", lambda *args, **kwargs: None)

    response = checkout_client.post(
        "/stripe/webhook",
        content=b"{}",
        headers={"stripe-signature": "valid"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "completed"

    db = database()
    try:
        order = db.query(api_app.Order).one()
        assert order.status == "completed"
        assert order.last_stripe_event_id == "evt_test_stripe_object"
    finally:
        db.close()


def test_invalid_webhook_signature_is_rejected(monkeypatch, checkout_client):
    monkeypatch.setattr(api_app, "WEBHOOK_SECRET", "whsec_test")

    def invalid_signature(*args, **kwargs):
        raise ValueError("bad signature")

    monkeypatch.setattr(
        api_app.stripe.Webhook,
        "construct_event",
        invalid_signature,
    )
    response = checkout_client.post(
        "/stripe/webhook",
        content=b"{}",
        headers={"stripe-signature": "invalid"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid Stripe signature"


def test_delayed_webhook_leaves_visible_pending_then_completes(
    monkeypatch, checkout_client
):
    install_idempotent_stripe(monkeypatch)
    checkout_response = checkout_client.post(
        "/checkout/create",
        json=checkout_body(),
        headers={"x-api-key": "test-ui-key"},
    )
    session_id = checkout_response.json()["session_id"]

    pending = checkout_client.get(f"/orders/by-session/{session_id}")
    assert pending.status_code == 200
    assert pending.json()["status"] == "pending"

    install_completed_webhook(monkeypatch, completed_session(session_id))
    completed = checkout_client.post(
        "/stripe/webhook",
        content=b"{}",
        headers={"stripe-signature": "valid"},
    )
    retrieved = checkout_client.get(f"/orders/by-session/{session_id}")

    assert completed.status_code == 200
    assert retrieved.json()["status"] == "completed"
    assert retrieved.json()["order_number_display"] == "OP-0001"


def test_guest_session_confirmation_redacts_customer_pii(database, checkout_client):
    db = database()
    try:
        db.add(
            api_app.Order(
                id="guest-order",
                stripe_session_id="cs_guest_private",
                status="completed",
                order_number=12,
                customer_email="guest@example.com",
                shipping_name="Guest Buyer",
                shipping_address={"line1": "1 Private Way"},
                amount_total_cents=14000,
            )
        )
        db.commit()
    finally:
        db.close()

    response = checkout_client.get("/orders/by-session/cs_guest_private")

    assert response.status_code == 200
    assert response.json()["order_number_display"] == "OP-0012"
    assert response.json()["amount_total_usd"] == 140.0
    assert "customer_email" not in response.json()
    assert "shipping_name" not in response.json()
    assert "shipping_address" not in response.json()


def test_authenticated_owner_session_confirmation_includes_customer_pii(
    monkeypatch, database, checkout_client
):
    db = database()
    try:
        db.add(
            api_app.Order(
                id="owned-order",
                stripe_session_id="cs_owned_private",
                customer_id="owner-user",
                status="completed",
                order_number=13,
                customer_email="owner@example.com",
                shipping_name="Owner Buyer",
                shipping_address={"line1": "2 Private Way"},
                amount_total_cents=15000,
            )
        )
        db.commit()
    finally:
        db.close()
    monkeypatch.setattr(
        api_app,
        "_decode_supabase_user_id_from_bearer",
        lambda authorization: "owner-user" if authorization == "Bearer owner" else None,
    )

    response = checkout_client.get(
        "/orders/by-session/cs_owned_private",
        headers={"Authorization": "Bearer owner"},
    )

    assert response.status_code == 200
    assert response.json()["customer_email"] == "owner@example.com"
    assert response.json()["shipping_name"] == "Owner Buyer"
    assert response.json()["shipping_address"] == {"line1": "2 Private Way"}


def test_webhook_database_failure_returns_retryable_status(
    monkeypatch, checkout_client, database
):
    db = database()
    try:
        db.add(
            api_app.Order(
                id="order-pending",
                stripe_session_id="cs_test_db_failure",
                status="pending",
                quote_payload=quote_inputs(),
            )
        )
        db.commit()
    finally:
        db.close()

    install_completed_webhook(
        monkeypatch,
        completed_session("cs_test_db_failure"),
    )

    class FailingSession:
        def query(self, *args, **kwargs):
            raise RuntimeError("database unavailable")

        def rollback(self):
            pass

        def close(self):
            pass

    monkeypatch.setattr(api_app, "SessionLocal", lambda: FailingSession())
    response = checkout_client.post(
        "/stripe/webhook",
        content=b"{}",
        headers={"stripe-signature": "valid"},
    )

    assert response.status_code == 503
    assert response.json()["detail"] == (
        "Order completion is temporarily unavailable; Stripe will retry."
    )
