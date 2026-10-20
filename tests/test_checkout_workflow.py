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


@pytest.mark.parametrize("cart", [False, True])
def test_complete_chamfer_survives_checkout_and_builds_finished_section(
    monkeypatch, checkout_client, database, cart
):
    from frozen_plate.order_adapter import specification_from_order
    from section_geometry import build_section_geometry

    install_idempotent_stripe(monkeypatch)
    monkeypatch.setattr(api_app, "_decode_supabase_user_id_from_bearer", lambda _: "owner-test")
    values = quote_inputs(
        chamfer_width=0.02, chamfer_angle_degrees=45,
        chamfer_side="downstream", flow_orientation="left-to-right",
        chamfer_width_definition="radial-angle-from-face",
    )
    body = {"items": [values]} if cart else {"inputs": values}
    path = "/checkout/cart/create" if cart else "/checkout/create"
    response = checkout_client.post(path, json=body, headers={"Authorization": "Bearer test"})
    assert response.status_code == 200
    with database() as db:
        order = db.query(api_app.Order).one()
        snapshot = {"id": order.id, "customer_id": order.customer_id, "quote_payload": order.quote_payload}
        spec, _ = specification_from_order(snapshot, line_index=0, part_identifier="STAGING TEST")
    section = build_section_geometry(spec)
    assert section.status == "CONFIGURED"
    assert section.angle_degrees == 45
    assert section.chamfer_radial_width == 0.02
    assert section.face == "right"


def test_width_only_checkout_preserves_incomplete_chamfer_hold(monkeypatch, checkout_client, database):
    from frozen_plate.order_adapter import specification_from_order
    from section_geometry import build_section_geometry

    install_idempotent_stripe(monkeypatch)
    monkeypatch.setattr(api_app, "_decode_supabase_user_id_from_bearer", lambda _: "owner-test")
    response = checkout_client.post("/checkout/create", json=checkout_body(), headers={"Authorization": "Bearer test"})
    assert response.status_code == 200
    with database() as db:
        order = db.query(api_app.Order).one()
        spec, _ = specification_from_order(
            {"id": order.id, "customer_id": order.customer_id, "quote_payload": order.quote_payload},
            line_index=0, part_identifier="STAGING HOLD",
        )
    assert "HOLD" in build_section_geometry(spec).status


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

    first = checkout_client.post(
        "/checkout/create", json=checkout_body(), headers=headers
    )
    duplicate = checkout_client.post(
        "/checkout/create", json=checkout_body(), headers=headers
    )

    assert first.status_code == 200
    assert duplicate.status_code == 200
    assert first.json() == duplicate.json()
    assert calls[0]["idempotency_key"] == checkout_body()["idempotency_key"]
    assert calls[0]["success_url"].endswith("/Success?session_id={CHECKOUT_SESSION_ID}")
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


def test_checkout_rate_limit_allows_requests_below_limit_then_enforces(
    monkeypatch, checkout_client
):
    install_idempotent_stripe(monkeypatch)
    monkeypatch.setattr(api_app, "CHECKOUT_RATE_LIMIT_REQUESTS", 2)
    api_app._RATE_LIMITER.clear()
    headers = {"x-api-key": "test-ui-key"}

    try:
        first = checkout_client.post(
            "/checkout/create", json=checkout_body(), headers=headers
        )
        second = checkout_client.post(
            "/checkout/create", json=checkout_body(), headers=headers
        )
        limited = checkout_client.post(
            "/checkout/create", json=checkout_body(), headers=headers
        )

        assert first.status_code == 200
        assert second.status_code == 200
        assert limited.status_code == 429
        assert limited.headers["retry-after"]
    finally:
        api_app._RATE_LIMITER.clear()


def test_signed_jwt_is_authoritative_over_valid_ui_key(
    monkeypatch, checkout_client, database
):
    from datetime import datetime, timedelta, timezone

    from cryptography.hazmat.primitives.asymmetric import rsa

    calls = install_idempotent_stripe(monkeypatch)
    monkeypatch.setattr(api_app, "_RATE_LIMITER", api_app._InMemoryRateLimiter())
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    monkeypatch.setattr(
        api_app,
        "_jwk_client",
        SimpleNamespace(
            get_signing_key_from_jwt=lambda token: SimpleNamespace(
                key=private_key.public_key()
            )
        ),
    )
    issuer = "https://auth.example.test/v1"
    monkeypatch.setattr(api_app, "SUPABASE_JWT_ISSUER", issuer)
    monkeypatch.setattr(api_app, "SUPABASE_JWT_AUD", "authenticated")
    now = datetime.now(timezone.utc)
    claims = {"sub": "signed-customer", "iss": issuer, "aud": "authenticated"}
    expired = api_app.jwt.encode(
        {**claims, "exp": now - timedelta(hours=1)}, private_key, algorithm="RS256"
    )
    valid = api_app.jwt.encode(
        {**claims, "exp": now + timedelta(hours=1)}, private_key, algorithm="RS256"
    )

    rejected = checkout_client.post(
        "/checkout/create",
        json=checkout_body(),
        headers={"Authorization": f"Bearer {expired}", "x-api-key": "test-ui-key"},
    )
    assert rejected.status_code == 401
    assert calls == []
    with database() as db:
        assert db.query(api_app.Order).count() == 0

    accepted = checkout_client.post(
        "/checkout/create",
        json=checkout_body(),
        headers={"Authorization": f"Bearer {valid}", "x-api-key": "test-ui-key"},
    )
    assert accepted.status_code == 200
    assert calls[0]["metadata"]["customer_id"] == "signed-customer"
    with database() as db:
        assert db.query(api_app.Order).one().customer_id == "signed-customer"


def test_checkout_rate_limit_isolates_customer_principals(monkeypatch, checkout_client):
    install_idempotent_stripe(monkeypatch)
    monkeypatch.setattr(api_app, "_RATE_LIMITER", api_app._InMemoryRateLimiter())
    monkeypatch.setattr(api_app, "CHECKOUT_RATE_LIMIT_REQUESTS", 2)
    monkeypatch.setattr(
        api_app,
        "_decode_supabase_user_id_from_bearer",
        lambda authorization: {
            "Bearer customer-a": "customer-a",
            "Bearer customer-b": "customer-b",
        }.get(authorization),
    )
    headers_a = {"Authorization": "Bearer customer-a", "x-api-key": "test-ui-key"}
    headers_b = {"Authorization": "Bearer customer-b", "x-api-key": "test-ui-key"}
    body_a = checkout_body()
    body_b = checkout_body(idempotency_key="00000000-0000-4000-8000-000000000002")

    def request(body, headers):
        return checkout_client.post("/checkout/create", json=body, headers=headers)

    assert request(body_a, headers_a).status_code == 200
    assert request(body_a, headers_a).status_code == 200
    limited_a = request(body_a, headers_a)
    assert limited_a.status_code == 429
    assert limited_a.headers["retry-after"]
    assert request(body_b, headers_b).status_code == 200
    assert request(body_b, headers_b).status_code == 200
    assert request(body_b, headers_b).status_code == 429
    assert request(body_a, headers_a).status_code == 429


def test_checkout_rejects_stale_pricing_before_stripe(monkeypatch, checkout_client):
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
        lambda authorization: (
            "verified-user" if authorization == "Bearer valid" else None
        ),
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
    assert calls[0]["cancel_url"].endswith("/Quote_Cart?checkout=cancelled")

    db = database()
    try:
        orders = db.query(api_app.Order).all()
        assert len(orders) == 1
        assert orders[0].customer_id == "verified-user"
        assert len(orders[0].quote_payload["cart_items"]) == 2
    finally:
        db.close()


def test_confirmed_drawing_items_use_existing_test_checkout_and_order_path(
    monkeypatch, checkout_client, database
):
    from drawing_intake.assisted_quote import (
        AssistedQuoteSession,
        CanonicalFieldValue,
        ConfigurationValueOrigin,
        availability_from_active_config,
        confirm_configuration,
    )
    from drawing_intake.cart_gate import verified_assisted_cart_inputs
    from drawing_intake.classification import DrawingDocumentClass
    from pricing_engine import QuoteInputs

    availability = availability_from_active_config(
        {
            "materials": ["304"],
            "thicknesses_by_material": {"304": [0.125, 0.25]},
            "lead_times_days": [14, 21],
            "tolerance_options_in": [0.001, 0.002, 0.005],
            "max_paddle_dia_in": 48.0,
            "max_bore_dia_in": 19.0,
            "max_handle_label_chars": 40,
        }
    )
    first = quote_inputs(
        paddle_dia=5.0,
        bore_dia=1.548,
        handle_width=2.0,
        handle_length_from_bore=10.5,
        chamfer=False,
        chamfer_width=None,
        handle_label="No label",
    )
    corrected = quote_inputs(
        paddle_dia=10.25,
        bore_dia=3.75,
        thickness=0.25,
        handle_width=2.0,
        handle_length_from_bore=10.5,
        chamfer=False,
        chamfer_width=None,
        handle_label="No label",
    )

    def confirmed_line(payload, part):
        session = AssistedQuoteSession(
            source_document="synthetic-fixture.pdf",
            source_sha256="1" * 64,
            document_class=DrawingDocumentClass.SINGLE_PLATE_DRAWING,
            candidate_count=1,
            selected_candidate_id=part,
            selection_required=False,
            configuration={
                name: CanonicalFieldValue(
                    value=value, origin=ConfigurationValueOrigin.CUSTOMER
                )
                for name, value in payload.items()
                if value is not None
            },
        )
        session = confirm_configuration(session, availability=availability)
        quote = {
            "normalized_configuration": QuoteInputs(**payload).model_dump(),
            "validation": {"valid": True},
            "currency": "USD",
            "configuration_id": part,
            "pricing_config_version": "version-current",
            "unit_price": 125.0,
            "total_price": 125.0,
        }
        return verified_assisted_cart_inputs(
            session, payload, quote, availability=availability
        )

    items = [confirmed_line(first, "plate-1"), confirmed_line(corrected, "plate-2")]
    calls = install_idempotent_stripe(monkeypatch)
    monkeypatch.setattr(
        api_app,
        "_decode_supabase_user_id_from_bearer",
        lambda authorization: (
            "verified-owner" if authorization == "Bearer valid" else None
        ),
    )
    request = {
        "items": items,
        "pricing_config_version": "version-current",
        "idempotency_key": "00000000-0000-4000-8000-000000000111",
    }
    headers = {"Authorization": "Bearer valid"}
    first_checkout = checkout_client.post(
        "/checkout/cart/create", json=request, headers=headers
    )
    replay_checkout = checkout_client.post(
        "/checkout/cart/create", json=request, headers=headers
    )
    assert first_checkout.status_code == 200
    assert replay_checkout.json() == first_checkout.json()
    assert calls[0]["line_items"][0]["price_data"]["unit_amount"] == 25000
    assert calls[0]["idempotency_key"] == request["idempotency_key"]
    assert not any("drawing" in key for key in calls[0]["metadata"])

    session = completed_session(
        first_checkout.json()["session_id"], customer_id="verified-owner"
    )
    session.update(amount_subtotal=25000, amount_shipping=3000, amount_total=28000)
    install_completed_webhook(monkeypatch, session)
    monkeypatch.setattr(api_app, "_send_email", lambda *args, **kwargs: None)
    webhook = checkout_client.post(
        "/stripe/webhook", content=b"{}", headers={"stripe-signature": "valid"}
    )
    replay = checkout_client.post(
        "/stripe/webhook", content=b"{}", headers={"stripe-signature": "valid"}
    )
    assert webhook.json()["status"] == "completed"
    assert replay.json()["status"] == "already_completed"
    orders = checkout_client.get("/me/orders", headers=headers)
    assert orders.status_code == 200
    assert len(orders.json()) == 1
    detail = checkout_client.get(
        f"/me/orders/{orders.json()[0]['id']}", headers=headers
    )
    assert detail.status_code == 200
    assert detail.json()["quote_payload"] == {"cart_items": items}
    assert detail.json()["quote_payload"]["cart_items"][1]["paddle_dia"] == 10.25
    assert detail.json()["amount_total_usd"] == 280.0
    db = database()
    try:
        assert db.query(api_app.Order).count() == 1
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

    failed = checkout_client.post(
        "/checkout/create", json=checkout_body(), headers=headers
    )
    retried = checkout_client.post(
        "/checkout/create", json=checkout_body(), headers=headers
    )

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


def test_signed_replay_repairs_only_missing_shipping_service(monkeypatch, checkout_client, database):
    install_idempotent_stripe(monkeypatch)
    result = checkout_client.post('/checkout/create', json=checkout_body(), headers={'x-api-key': 'test-ui-key'})
    session = completed_session(result.json()['session_id'])
    install_completed_webhook(monkeypatch, session)
    emails = []
    monkeypatch.setattr(api_app, '_send_email', lambda **kwargs: emails.append(kwargs))

    def retrieve(session_id, **kwargs):
        assert kwargs['expand'] == ['shipping_cost.shipping_rate']
        return session

    monkeypatch.setattr(api_app.stripe.checkout.Session, 'retrieve', retrieve)
    headers = {'stripe-signature': 'valid'}
    assert checkout_client.post('/stripe/webhook', content=b'{}', headers=headers).json()['status'] == 'completed'
    with database() as db:
        order = db.query(api_app.Order).one()
        before = (order.id, order.order_number, order.paid_at, order.stripe_payment_intent, order.amount_total_cents, order.quote_payload)
        order.shipping_service = None
        db.commit()
    for _ in range(2):
        assert checkout_client.post('/stripe/webhook', content=b'{}', headers=headers).json()['status'] == 'already_completed'
    with database() as db:
        order = db.query(api_app.Order).one()
        assert order.shipping_service == 'ups_ground'
        assert (order.id, order.order_number, order.paid_at, order.stripe_payment_intent, order.amount_total_cents, order.quote_payload) == before
    assert len(emails) == 1


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

    class StripeEventObject(StripeSessionObject):
        pass

    monkeypatch.setattr(api_app, "WEBHOOK_SECRET", "whsec_test")
    monkeypatch.setattr(
        api_app.stripe.Webhook,
        "construct_event",
        lambda payload, signature, secret: StripeEventObject(
            {
                "id": "evt_test_stripe_object",
                "type": "checkout.session.completed",
                "data": {"object": StripeSessionObject({"id": session_id})},
            }
        ),
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


@pytest.mark.parametrize("environment,mode,expected", [
    ("staging", "capture", "capture"),
    ("staging", "send", None),
    ("production", "capture", None),
])
def test_success_capture_notice_is_server_scoped(monkeypatch, database, checkout_client,
                                                environment, mode, expected):
    monkeypatch.setattr(api_app, "APP_ENV", environment)
    monkeypatch.setenv("FROZEN_PLATE_EMAIL_MODE", mode)
    with database() as db:
        db.add(api_app.Order(id="notice-order", stripe_session_id="cs_notice", status="completed"))
        db.commit()
    response = checkout_client.get("/orders/by-session/cs_notice")
    assert response.status_code == 200
    assert response.json().get("email_delivery_mode") == expected


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


@pytest.fixture(params=["preview", "staging"])
def recovery_client(checkout_client, monkeypatch, request):
    monkeypatch.setattr(api_app, "APP_ENV", request.param)
    monkeypatch.setenv("OPLATES_DRAWING_ASSISTED_ENABLED", "true")
    monkeypatch.setenv("OPLATES_DRAWING_ASSISTED_ALLOWED_USER_IDS", "owner")
    monkeypatch.setattr(
        api_app,
        "_decode_supabase_user_id_from_bearer",
        lambda token: {"Bearer owner": "owner", "Bearer other": "other"}.get(token),
    )
    yield checkout_client


def recovery_reference(calls):
    from urllib.parse import urlparse, parse_qs

    return parse_qs(urlparse(calls[-1]["cancel_url"]).query)["resume"][0]


@pytest.mark.parametrize(
    "values",
    [
        quote_inputs(
            paddle_dia=5.0,
            bore_dia=1.548,
            handle_width=2.0,
            handle_length_from_bore=10.5,
        ),
        quote_inputs(
            paddle_dia=10.25,
            bore_dia=3.75,
            thickness=0.25,
            quantity=3,
            handle_width=2.0,
            handle_length_from_bore=14.0,
        ),
    ],
)
def test_checkout_recovery_exact_customer_inputs(
    recovery_client, database, monkeypatch, values
):
    calls = install_idempotent_stripe(monkeypatch)
    body = checkout_body(inputs=values)
    headers = {"Authorization": "Bearer owner"}
    assert (
        recovery_client.post("/checkout/create", json=body, headers=headers).status_code
        == 200
    )
    reference = recovery_reference(calls)
    result = recovery_client.get(f"/checkout/recovery/{reference}", headers=headers)
    assert result.status_code == 200, result.text
    assert result.json() == {
        "kind": "direct",
        "items": [values],
        "contexts": [None],
        "requires_confirmation": True,
    }
    assert (
        recovery_client.post("/checkout/create", json=body, headers=headers).status_code
        == 200
    )
    assert calls[0]["cancel_url"] == calls[1]["cancel_url"]
    with database() as db:
        assert db.query(api_app.Order).count() == 1
        order = db.query(api_app.Order).one()
        assert order.status == "pending" and order.paid_at is None


def test_checkout_recovery_isolation_expiration_and_paid(
    recovery_client, database, monkeypatch
):
    from datetime import datetime, timezone, timedelta

    calls = install_idempotent_stripe(monkeypatch)
    assert (
        recovery_client.post(
            "/checkout/create",
            json=checkout_body(),
            headers={"Authorization": "Bearer owner"},
        ).status_code
        == 200
    )
    path = f"/checkout/recovery/{recovery_reference(calls)}"
    assert recovery_client.get(path).status_code == 401
    assert (
        recovery_client.get(path, headers={"Authorization": "Bearer other"}).status_code
        == 403
    )
    assert (
        recovery_client.get(
            "/checkout/recovery/" + "f" * 64, headers={"Authorization": "Bearer owner"}
        ).status_code
        == 404
    )
    assert (
        recovery_client.get(
            "/checkout/recovery/tampered", headers={"Authorization": "Bearer owner"}
        ).status_code
        == 404
    )
    with database() as db:
        order = db.query(api_app.Order).one()
        order.created_at = datetime.now(timezone.utc) - timedelta(hours=25)
        db.commit()
    assert (
        recovery_client.get(path, headers={"Authorization": "Bearer owner"}).status_code
        == 404
    )
    with database() as db:
        order = db.query(api_app.Order).one()
        order.created_at = datetime.now(timezone.utc)
        order.status = "completed"
        order.paid_at = datetime.now(timezone.utc)
        db.commit()
    assert (
        recovery_client.get(path, headers={"Authorization": "Bearer owner"}).status_code
        == 404
    )


def test_checkout_recovery_two_independent_cart_lines(
    recovery_client, database, monkeypatch
):
    calls = install_idempotent_stripe(monkeypatch)
    items = [
        quote_inputs(paddle_dia=5.0, bore_dia=1.548),
        quote_inputs(paddle_dia=10.25, bore_dia=3.75, quantity=3),
    ]
    body = {
        "items": items,
        "pricing_config_version": "version-current",
        "idempotency_key": "cart-recovery-unique-attempt",
    }
    headers = {"Authorization": "Bearer owner"}
    response = recovery_client.post("/checkout/cart/create", json=body, headers=headers)
    assert response.status_code == 200, response.text
    result = recovery_client.get(
        f"/checkout/recovery/{recovery_reference(calls)}", headers=headers
    )
    assert result.status_code == 200, result.text
    assert result.json()["items"] == items
    assert result.json()["kind"] == "cart"
    assert (
        recovery_client.post(
            "/checkout/cart/create", json=body, headers=headers
        ).status_code
        == 200
    )
    with database() as db:
        assert db.query(api_app.Order).count() == 1


def test_recovered_session_requires_fresh_confirmation():
    from drawing_intake.checkout_recovery import recovered_quote_session
    from drawing_intake.assisted_quote import review_assisted_quote

    session = recovered_quote_session(quote_inputs(paddle_dia=5.0, bore_dia=1.548))
    assert session.confirmation_fingerprint is None
    assert not review_assisted_quote(session).confirmation_current
    assert all(field.origin == "customer" for field in session.configuration.values())


@pytest.mark.parametrize(
    "document_class,count",
    [
        ("single_plate_drawing", 1),
        ("multi_plate_drawing", 8),
        ("table_driven_plate_schedule", 13),
    ],
)
def test_selected_part_checkout_cancel_reconfirm_reprice(
    recovery_client, database, monkeypatch, document_class, count
):
    from drawing_intake.checkout_context import attest_context, selected_part_context
    from drawing_intake.checkout_recovery import recovered_quote_session
    from drawing_intake.assisted_quote import confirm_configuration
    from drawing_intake.pricing_gate import confirmed_drawing_quote_inputs
    from test_drawing_phase1k import available

    calls = install_idempotent_stripe(monkeypatch)
    inputs = quote_inputs(
        paddle_dia=10.25,
        bore_dia=3.75,
        thickness=0.25,
        handle_width=2,
        handle_length_from_bore=14,
    )
    context = {
        "document_class": document_class,
        "candidate_count": count,
        "selected_candidate_id": "explicit-selected-part",
        "selection_required": False,
    }
    # Exercise the initial confirmation/pricing gate as well as recovery.
    initial = recovered_quote_session(inputs, context)
    with pytest.raises(ValueError):
        confirmed_drawing_quote_inputs(initial, inputs, availability=available())
    initial = confirm_configuration(initial, availability=available())
    initial_payload = confirmed_drawing_quote_inputs(
        initial, inputs, availability=available()
    )
    first_price = recovery_client.post(
        "/quote", json=initial_payload, headers={"x-api-key": "test-ui-key"}
    )
    assert first_price.status_code == 200
    body = checkout_body(
        inputs=initial_payload,
        recovery_context=attest_context(
            selected_part_context(initial), initial_payload, "owner", "test-ui-key"
        ),
    )
    headers = {"Authorization": "Bearer owner"}
    assert (
        recovery_client.post("/checkout/create", json=body, headers=headers).status_code
        == 200
    )
    snapshot = recovery_client.get(
        "/checkout/recovery/" + recovery_reference(calls), headers=headers
    ).json()
    assert snapshot["contexts"] == [context]
    session = recovered_quote_session(snapshot["items"][0], snapshot["contexts"][0])
    with pytest.raises(ValueError):
        confirmed_drawing_quote_inputs(session, inputs, availability=available())
    session = confirm_configuration(session, availability=available())
    payload = confirmed_drawing_quote_inputs(session, inputs, availability=available())
    assert payload["paddle_dia"] == 10.25
    assert payload == api_app.QuoteInputs(**inputs).model_dump()
    price = recovery_client.post(
        "/quote", json=payload, headers={"x-api-key": "test-ui-key"}
    )
    assert price.status_code == 200
    assert price.json()["total_price"] == 125.0
    assert price.json()["total_price"] == first_price.json()["total_price"]


@pytest.mark.parametrize(
    "tamper", ["signature", "inputs", "customer", "reference", "unselected"]
)
def test_selected_part_attestation_cannot_be_forged(
    recovery_client, monkeypatch, tamper
):
    from drawing_intake.checkout_context import attest_context

    calls = install_idempotent_stripe(monkeypatch)
    inputs = quote_inputs()
    context = {
        "document_class": "multi_plate_drawing",
        "candidate_count": 8,
        "selected_candidate_id": "selected-part",
        "selection_required": False,
    }
    envelope = attest_context(
        context, inputs, "other" if tamper == "customer" else "owner", "test-ui-key"
    )
    if tamper == "signature":
        envelope["signature"] = "0" * 64
    if tamper == "inputs":
        inputs["paddle_dia"] = 5
    if tamper == "reference":
        envelope["context"]["document_class"] = "reference_vendor_datasheet"
    if tamper == "unselected":
        envelope["context"]["selection_required"] = True
    result = recovery_client.post(
        "/checkout/create",
        json=checkout_body(inputs=inputs, recovery_context=envelope),
        headers={"Authorization": "Bearer owner"},
    )
    assert result.status_code == 400
    assert not calls


@pytest.mark.parametrize("cart", [False, True])
def test_unified_completed_order_captures_exact_independent_lines(
    monkeypatch, recovery_client, database, tmp_path, cart
):
    from hashlib import sha256
    from email.parser import BytesParser
    from email import policy
    from frozen_plate.repository import Repository
    from frozen_plate import api as frozen_api

    class CaptureRepository(Repository):
        def create_delivery(self, *args, **kwargs):
            delivery = super().create_delivery(*args, **kwargs)
            captured.append(delivery)
            return delivery

    captured = []
    repo = CaptureRepository(tmp_path, "unit-signing-key" * 6)
    monkeypatch.setattr(frozen_api, "repository", lambda: repo)
    monkeypatch.setattr(api_app, "APP_ENV", "staging")
    monkeypatch.setenv("FROZEN_PLATE_DATABASE_URL", "unit-test-binding")
    monkeypatch.setenv("FROZEN_PLATE_EMAIL_MODE", "capture")
    monkeypatch.setattr(api_app, "SENDGRID_API_KEY", "unit-test-do-not-send")
    monkeypatch.setattr(api_app, "SendGridAPIClient", lambda *a, **k: pytest.fail("Customer email attempted"))
    install_idempotent_stripe(monkeypatch)
    values = quote_inputs(chamfer=False, chamfer_width=None, paddle_dia=5.0,
                          bore_dia=1.548, handle_width=2.0, handle_length_from_bore=10.5)
    other = {**values, "paddle_dia": 10.25, "bore_dia": 3.75, "quantity": 2}
    body = checkout_body(inputs=values)
    if cart:
        body = {"items": [values, other], "pricing_config_version": "version-current",
                "idempotency_key": body["idempotency_key"]}
    response = recovery_client.post("/checkout/cart/create" if cart else "/checkout/create",
                                    json=body, headers={"Authorization": "Bearer owner"})
    assert response.status_code == 200, response.text
    install_completed_webhook(monkeypatch, completed_session(response.json()["session_id"], customer_id="owner"))
    for expected in ("completed", "already_completed"):
        result = recovery_client.post("/stripe/webhook", content=b"{}", headers={"stripe-signature": "valid"})
        assert result.status_code == 200, result.text
        assert result.json()["status"] == expected
    assert len(captured) == (2 if cart else 1)
    with database() as db:
        order = db.query(api_app.Order).one()
        assert order.status == "completed" and order.shipping_service == "ups_ground"
        assert "_checkout_recovery" in order.quote_payload
    for delivery, source in zip(captured, [values, other] if cart else [values]):
        context = delivery["context"]
        token = delivery["token"]
        filename, pdf = repo.customer_pdf(token, customer_id="owner")
        mime = BytesParser(policy=policy.default).parsebytes(delivery["mime"])
        attached = list(mime.iter_attachments())
        assert len(attached) == 1 and attached[0].get_payload(decode=True) == pdf
        with repo.connect() as db:
            binding = db.execute("SELECT revision_id,pdf_sha256 FROM frozen_plate_tokens WHERE fingerprint=?",
                                 (sha256(token.encode()).hexdigest(),)).fetchone()
        assert sha256(pdf).hexdigest() == binding["pdf_sha256"]
        import json
        spec = json.loads(repo.revision(binding["revision_id"])["spec_json"])
        assert spec["finished_od"] == source["paddle_dia"]
        assert spec["finished_bore_diameter"] == source["bore_dia"]
        assert spec["quantity"] == source["quantity"]


def test_production_checkout_rejects_test_key_before_creating_session(monkeypatch, checkout_client):
    monkeypatch.setattr(api_app, "APP_ENV", "production")
    calls = install_idempotent_stripe(monkeypatch)
    response = checkout_client.post("/checkout/create", json=checkout_body(), headers={"x-api-key": "test-ui-key"})
    assert response.status_code == 500
    assert response.json()["detail"] == "Production checkout requires Stripe live mode."
    assert not calls


def test_live_key_alone_cannot_open_unverified_production_checkout(monkeypatch, checkout_client):
    monkeypatch.setattr(api_app, "APP_ENV", "production")
    monkeypatch.setattr(api_app.stripe, "api_key", "rk_live_synthetic")
    monkeypatch.delenv("FROZEN_PLATE_LIVE_CHECKOUT_READY", raising=False)
    calls = install_idempotent_stripe(monkeypatch)
    response = checkout_client.post("/checkout/create", json=checkout_body(), headers={"x-api-key": "test-ui-key"})
    assert response.status_code == 503
    assert not calls


def test_production_webhook_rejects_test_event_before_order_mutation(monkeypatch, checkout_client, database):
    monkeypatch.setattr(api_app, "APP_ENV", "production")
    install_completed_webhook(monkeypatch, completed_session())
    result = checkout_client.post("/stripe/webhook", content=b"{}", headers={"stripe-signature": "valid"})
    assert result.status_code == 400
    with database() as db:
        assert db.query(api_app.Order).count() == 0


def test_production_completion_uses_server_snapshot_and_suppresses_generic_email(monkeypatch, checkout_client, database, tmp_path):
    from frozen_plate import api as frozen_api, delivery
    from frozen_plate.repository import Repository
    from frozen_plate.runtime import PRODUCTION_API
    monkeypatch.setattr(api_app, "APP_ENV", "production")
    monkeypatch.setenv("FROZEN_PLATE_ENABLED", "true")
    monkeypatch.setenv("FROZEN_PLATE_DATABASE_URL", "synthetic-binding")
    monkeypatch.setattr(api_app, "_send_email", lambda *a, **k: pytest.fail("generic email duplicated exact drawing"))
    repo = Repository(tmp_path, "synthetic-signing-key" * 6)
    repo.delivery_origin = PRODUCTION_API
    repo.part_prefix = "PRD-"
    captures = []
    original = repo.create_delivery
    def capture(revision_id):
        result = original(revision_id, base_url=PRODUCTION_API)
        captures.append(result)
        return result
    repo.create_delivery = capture
    monkeypatch.setattr(frozen_api, "repository", lambda: repo)
    sent = []
    monkeypatch.setattr(delivery, "deliver_completed_order", lambda r, snapshot, states: sent.append((snapshot, states)))
    with database() as db:
        order = api_app.Order(id="production-order", stripe_session_id="cs_live_synthetic", status="pending",
            customer_id="owner", quote_payload=quote_inputs(chamfer=False, chamfer_width=None))
        db.add(order)
        db.commit()
    session = completed_session("cs_live_synthetic", "owner")
    session["livemode"] = True
    event = {"id": "evt_live_synthetic", "type": "checkout.session.completed", "livemode": True,
             "data": {"object": session}}
    monkeypatch.setattr(api_app, "WEBHOOK_SECRET", "synthetic-webhook-secret")
    monkeypatch.setattr(api_app.stripe.Webhook, "construct_event", lambda *args: event)
    monkeypatch.setattr(api_app.stripe.checkout.Session, "retrieve", lambda *a, **k: session)
    for _ in range(2):
        result = checkout_client.post("/stripe/webhook", content=b"{}", headers={"stripe-signature": "valid"})
        assert result.status_code == 200, result.text
    assert len(captures) == 1
    assert len(sent) == 2  # delivery's immutable claim provides per-revision idempotency
    assert sent[0][0]["customer_id"] == "owner"
    assert sent[0][0]["customer_email"] == "buyer@example.com"
    assert sent[0][1][0]["state"] == "FROZEN"
    assert sent[0][1] == sent[1][1]
    assert "OP-PRD-" in captures[0]["context"]["drawing"]
