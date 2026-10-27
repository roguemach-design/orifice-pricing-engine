"""Authentication and activation boundaries for single and multi-plate payment."""
import copy
from types import SimpleNamespace
import pytest
import requests
import streamlit as st
import api_app
import auth
from test_checkout_workflow import database, checkout_client, checkout_body, install_idempotent_stripe, completed_session, install_completed_webhook
from test_owner_sandbox_checkout import sandbox, headers
from test_landing_convergence import CONFIG, response, select
from test_drawing_phase1g import _jwt
from ui_harness import customer_page_test


@pytest.mark.parametrize("cart", [False, True])
@pytest.mark.parametrize("credentials", [{}, {"x-api-key": "test-ui-key"},
    {"Authorization": "Bearer invalid", "x-api-key": "test-ui-key"}])
def test_no_guest_checkout_even_with_ui_key(monkeypatch, checkout_client, database, cart, credentials):
    calls = install_idempotent_stripe(monkeypatch)
    payload = {"items": [checkout_body()["inputs"]]} if cart else checkout_body()
    result = checkout_client.post("/checkout/cart/create" if cart else "/checkout/create",
                                  json=payload, headers=credentials)
    assert result.status_code == 401
    assert not calls
    with database() as db:
        assert db.query(api_app.Order).count() == 0


@pytest.mark.parametrize("acceptance", [None, "true", "false"])
def test_live_environment_readiness_cannot_override_database_test_mode(sandbox, monkeypatch, acceptance):
    monkeypatch.setenv("FROZEN_PLATE_LIVE_CHECKOUT_READY", "true")
    monkeypatch.setenv("OPLATES_STRIPE_TEST_VALIDATION_WINDOW", "false")
    if acceptance is None:
        monkeypatch.delenv("OPLATES_OWNER_ACCEPTANCE_MODE", raising=False)
    else:
        monkeypatch.setenv("OPLATES_OWNER_ACCEPTANCE_MODE", acceptance)
    owner = sandbox.client.get("/checkout/availability", headers=headers(mode=False)).json()
    public = sandbox.client.get("/checkout/availability").json()
    customer = sandbox.client.get("/checkout/availability", headers=headers("customer", mode=False)).json()
    assert owner == {"available": True, "mode": "owner_test"}
    assert public["available"] is False
    assert customer["available"] is False
    assert not sandbox.calls
    # Readiness never replaces authentication on the creation API.
    assert sandbox.client.post("/checkout/create", json=checkout_body(),
                               headers={"x-api-key": "test-ui-key"}).status_code == 401


def test_live_not_ready_preserves_independent_owner_test(sandbox):
    assert sandbox.client.get("/checkout/availability").json()["available"] is False
    assert sandbox.client.get("/checkout/availability", headers=headers()).json() == {
        "available": True, "mode": "owner_test"}
    assert sandbox.client.get("/checkout/availability", headers=headers("customer")).json()["available"] is False
    assert not sandbox.calls


def test_wrong_session_mode_cannot_persist_order(monkeypatch, checkout_client, database):
    monkeypatch.setattr(api_app.stripe.checkout.Session, "create",
                        lambda **kwargs: SimpleNamespace(id="cs_live_wrong", livemode=True, url="https://checkout.stripe.com/c/pay/cs_live_wrong"))
    result = checkout_client.post("/checkout/create", json=checkout_body(),
                                  headers={"Authorization": "Bearer synthetic"})
    assert result.status_code == 502
    with database() as db:
        assert db.query(api_app.Order).count() == 0


def test_anonymous_supabase_identity_is_not_a_customer(monkeypatch):
    monkeypatch.setattr(api_app, "_jwk_client", SimpleNamespace(get_signing_key_from_jwt=lambda t: SimpleNamespace(key="public")))
    monkeypatch.setattr(api_app, "SUPABASE_JWT_ISSUER", "verified-issuer")
    monkeypatch.setattr(api_app.jwt, "get_unverified_header", lambda t: {"alg": "RS256"})
    monkeypatch.setattr(api_app.jwt, "decode", lambda *a, **k: {"sub": "anonymous-id", "is_anonymous": True})
    assert api_app._decode_supabase_user_id_from_bearer("Bearer signed") is None


@pytest.mark.parametrize("integrated", [False, True])
def test_sign_in_at_checkout_preserves_configuration_cart_and_resumes(monkeypatch, integrated):
    st.cache_data.clear()
    monkeypatch.setenv("API_BASE", "http://offline-fixture")
    for key in ("APP_ENV", "OPLATES_OWNER_ACCEPTANCE_MODE", "OPLATES_DRAWING_ASSISTED_ENABLED"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(auth, "_cookie_set", lambda payload: None)
    monkeypatch.setattr(auth, "sb", lambda: SimpleNamespace(auth=SimpleNamespace(
        verify_otp=lambda payload: SimpleNamespace(session=SimpleNamespace(
            access_token=_jwt("signed-customer"), refresh_token=None), user=None))))
    monkeypatch.setattr(requests, "get", lambda url, **k: response({"available": True, "mode": "test"}) if url.endswith("/checkout/availability") else response(CONFIG))
    calls = []
    def post(url, **kwargs):
        calls.append((url, copy.deepcopy(kwargs)))
        if url.endswith("/quote"):
            return response(dict(unit_price=100, total_price=100, configuration_id="synthetic",
                                 pricing_config_version="current"))
        assert url.endswith("/checkout/create")
        return response({"checkout_url": "https://checkout.stripe.com/c/pay/cs_test_synthetic"})
    monkeypatch.setattr(requests, "post", post)
    app = customer_page_test("pages/1_Quote.py")
    app.session_state["integrated_landing"] = integrated
    app.session_state["cart"] = [{"line_id": "existing-cart-line", "inputs": checkout_body()["inputs"]}]
    app.run()
    select(app, "quote_field_material", "316")
    select(app, "quote_field_ships_in_days", 21)
    app.number_input(key="quote_field_paddle_dia").set_value(4).run()
    expected = copy.deepcopy([data["json"] for url, data in calls if url.endswith("/quote")][-1])
    cart = copy.deepcopy(app.session_state["cart"])
    next(b for b in app.button if b.label == "Continue to secure checkout").click().run()
    assert not app.exception
    assert not any(url.endswith("/checkout/create") for url, _ in calls)
    assert app.session_state["pending_checkout_sign_in"]["inputs"] == expected
    # AppTest reruns the full script rather than the native dialog fragment.
    # Model the verified callback's session transition; auth callback tests
    # separately cover OTP verification and the full-app rerun.
    app.session_state["auth"] = {"access_token": _jwt("signed-customer"),
                                 "refresh_token": None, "user": None,
                                 "email": "synthetic@example.test"}
    app.run()
    assert not app.exception
    checkout = [data for url, data in calls if url.endswith("/checkout/create")]
    assert len(checkout) == 1, {"auth": bool(app.session_state["auth"].get("access_token")), "pending": app.session_state.get("pending_checkout_sign_in"), "errors": [e.value for e in app.error], "text": [t.label for t in app.text_input]}
    assert checkout[0]["json"]["inputs"] == expected
    assert checkout[0]["headers"]["Authorization"].startswith("Bearer ")
    assert "x-api-key" not in checkout[0]["headers"]
    assert app.session_state["cart"] == cart
    assert "pending_checkout_sign_in" not in app.session_state
    app.run()
    assert len([url for url, _ in calls if url.endswith("/checkout/create")]) == 1


@pytest.mark.parametrize("customer_id", ["other-customer", ""])
def test_payment_cannot_rebind_authenticated_order(monkeypatch, checkout_client, database, customer_id):
    install_idempotent_stripe(monkeypatch)
    created = checkout_client.post("/checkout/create", json=checkout_body(),
                                   headers={"Authorization": "Bearer synthetic"})
    assert created.status_code == 200
    install_completed_webhook(monkeypatch, completed_session(created.json()["session_id"], customer_id))
    monkeypatch.setattr(api_app, "_send_email", lambda **kwargs: pytest.fail("Email before identity verification"))
    result = checkout_client.post("/stripe/webhook", content=b"{}", headers={"stripe-signature": "valid"})
    assert result.status_code == 400
    with database() as db:
        order = db.query(api_app.Order).one()
        assert order.customer_id == "signed-customer"
        assert order.status == "pending" and order.paid_at is None
