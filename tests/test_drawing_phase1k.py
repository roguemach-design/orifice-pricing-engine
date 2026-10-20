"""Owner-test cart handoff and access gates, without live payment calls."""

from pathlib import Path
from unittest.mock import patch

import auth
from drawing_intake.assisted_quote import (
    availability_from_active_config,
    confirm_configuration,
    set_customer_value,
)
from drawing_intake.cart_gate import verified_assisted_cart_inputs
from drawing_intake.classification import DrawingDocumentClass
from drawing_intake.owner_access import verified_owner_access
from pricing_engine import QuoteInputs
from streamlit.testing.v1 import AppTest

from test_drawing_phase1i import _jwt, _payload, _session

ROOT = Path(__file__).resolve().parents[1]
ACTIVE = {
    "materials": ["304"],
    "thicknesses_by_material": {"304": [0.125, 0.25]},
    "lead_times_days": [14, 21],
    "default_lead_time_days": 14,
    "tolerance_options_in": [0.001, 0.002, 0.005],
    "max_paddle_dia_in": 48.0,
    "max_bore_dia_in": 19.0,
    "max_handle_label_chars": 40,
}


class Response:
    def __init__(self, body, status_code=200):
        self.body = body
        self.status_code = status_code

    def json(self):
        return self.body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise ValueError(self.status_code)


def priced(payload):
    return {
        "normalized_configuration": QuoteInputs(**payload).model_dump(),
        "validation": {"valid": True, "errors": []},
        "currency": "USD",
        "configuration_id": "verified-quote",
        "pricing_config_version": "current-test-version",
        "unit_price": 125.0,
        "total_price": 125.0,
        "area_sq_in": 10.0,
        "estimated_total_weight_lb": 5.0,
        "estimated_package_in": {"length": 10, "width": 10, "height": 2},
    }


def available():
    return availability_from_active_config(ACTIVE)


def complete_session(payload):
    return confirm_configuration(_session(payload), availability=available())


def test_assisted_cart_uses_exact_confirmed_and_verified_canonical_inputs():
    payload = _payload()
    session = complete_session(payload)
    assert (
        verified_assisted_cart_inputs(
            session, payload, priced(payload), availability=available()
        )
        == QuoteInputs(**payload).model_dump()
    )
    changed = {**payload, "paddle_dia": 10.25}
    for altered in (
        changed,
        {**priced(payload), "normalized_configuration": changed},
    ):
        import pytest

        with pytest.raises(ValueError):
            if "normalized_configuration" in altered:
                verified_assisted_cart_inputs(
                    session, payload, altered, availability=available()
                )
            else:
                verified_assisted_cart_inputs(
                    session, altered, priced(payload), availability=available()
                )


def test_assisted_cart_rejects_missing_quote_unconfirmed_and_unsafe_documents():
    import pytest

    payload = _payload()
    session = complete_session(payload)
    for missing in ("validation", "configuration_id", "pricing_config_version"):
        incomplete_quote = priced(payload)
        incomplete_quote.pop(missing)
        with pytest.raises(ValueError):
            verified_assisted_cart_inputs(
                session, payload, incomplete_quote, availability=available()
            )
    with pytest.raises(ValueError):
        verified_assisted_cart_inputs(
            _session(payload), payload, priced(payload), availability=available()
        )
    for kind, count, selected, required in (
        (DrawingDocumentClass.REFERENCE_VENDOR_DATASHEET, 0, None, False),
        (DrawingDocumentClass.MULTI_PLATE_DRAWING, 8, None, True),
    ):
        unsafe = _session(
            payload,
            kind=kind,
            count=count,
            selected=selected,
            selection_required=required,
        )
        with pytest.raises(ValueError):
            verified_assisted_cart_inputs(
                unsafe, payload, priced(payload), availability=available()
            )


def test_customer_correction_and_later_edit_require_new_confirmation_and_price():
    import pytest

    original = _payload(od=10.0, bore=3.75, thickness=0.25)
    session = complete_session(original)
    corrected = {**original, "paddle_dia": 10.25}
    session = set_customer_value(session, "paddle_dia", 10.25)
    with pytest.raises(ValueError):
        verified_assisted_cart_inputs(
            session, corrected, priced(original), availability=available()
        )
    session = confirm_configuration(session, availability=available())
    assert (
        verified_assisted_cart_inputs(
            session, corrected, priced(corrected), availability=available()
        )["paddle_dia"]
        == 10.25
    )
    changed_again = {**corrected, "bore_dia": 3.875}
    session = set_customer_value(session, "bore_dia", 3.875)
    with pytest.raises(ValueError):
        verified_assisted_cart_inputs(
            session, changed_again, priced(corrected), availability=available()
        )


def test_owner_access_fails_closed_and_uses_existing_verified_api_gate():
    with patch("requests.get") as get:
        assert not verified_owner_access(
            "http://test", enabled=False, user_id_hint="internal", headers={}
        )
        assert not verified_owner_access(
            "http://test", enabled=True, user_id_hint=None, headers={}
        )
        get.assert_not_called()
        get.return_value = Response(
            {"enabled": True, "authorized": True, "user_id": "other"}
        )
        assert not verified_owner_access(
            "http://test", enabled=True, user_id_hint="internal", headers={}
        )
        get.return_value = Response(
            {"enabled": True, "authorized": True, "user_id": "internal"}
        )
        assert verified_owner_access(
            "http://test", enabled=True, user_id_hint="internal", headers={}
        )


def _quote_app(monkeypatch, *, checkout_enabled, confirmed=True, authorized=True):
    monkeypatch.setenv("API_KEY", "test-ui-key")
    monkeypatch.setenv("API_BASE", "http://test")
    monkeypatch.setenv("OPLATES_DRAWING_ASSISTED_ENABLED", "true")
    monkeypatch.setenv("OPLATES_OWNER_ACCEPTANCE_MODE", "true")
    monkeypatch.setenv(
        "OPLATES_OWNER_TEST_CHECKOUT_ENABLED", str(checkout_enabled).lower()
    )
    monkeypatch.setattr(auth, "API_BASE", "http://test")
    payload = _payload()
    session = _session(payload)
    if confirmed:
        session = confirm_configuration(session, availability=available())
    calls = []

    def fake_get(url, **kwargs):
        return Response(
            ACTIVE
            if url.endswith("/config/active")
            else {"enabled": True, "authorized": authorized, "user_id": "internal-user"}
        )

    def fake_post(url, **kwargs):
        calls.append((url, kwargs["json"]))
        if url.endswith("/checkout/create"):
            return Response(
                {
                    "checkout_url": "https://checkout.stripe.test/test-session",
                    "session_id": "cs_test_phase1k",
                }
            )
        return Response(priced(kwargs["json"]))

    with (
        patch("requests.get", fake_get),
        patch("requests.post", fake_post),
        patch("streamlit.switch_page"),
    ):
        app = AppTest.from_file(str(ROOT / "pages" / "1_Quote.py"), default_timeout=20)
        app.session_state["auth"] = {
            "access_token": _jwt(),
            "refresh_token": None,
            "user": None,
            "email": "internal@example.com",
        }
        for field, value in payload.items():
            app.session_state[f"quote_field_{field}"] = value
        app.session_state["phase1g_form_origins"] = {
            field: "customer" for field in payload
        }
        app.session_state["phase1g_form_snapshot"] = payload.copy()
        app.session_state["phase1g_assisted_session"] = session
        app.session_state["phase1g_customer_confirmation"] = confirmed
        app.run()
        assert not app.exception
        yield app, payload, calls


def test_owner_test_checkout_is_disabled_by_default_and_for_unapproved_users(
    monkeypatch,
):
    for enabled, authorized in ((False, True), (True, False)):
        for app, payload, calls in _quote_app(
            monkeypatch, checkout_enabled=enabled, authorized=authorized
        ):
            assert next(
                b for b in app.button if b.label == "Add another plate"
            ).disabled
            assert next(
                b for b in app.button if b.label == "Continue to secure checkout"
            ).disabled
            assert not any(url.endswith("/checkout/create") for url, _ in calls)


def test_confirmed_owner_can_add_verified_quote_to_normal_cart(monkeypatch):
    for app, payload, calls in _quote_app(monkeypatch, checkout_enabled=True):
        button = next(b for b in app.button if b.label == "Add another plate")
        assert not button.disabled
        button.click().run()
        assert not app.exception
        assert len(app.session_state.cart) == 1
        line = app.session_state.cart[0]
        assert line["inputs"] == QuoteInputs(**payload).model_dump()
        assert line["assisted_quote"] is True
        assert line["configuration_id"] == "verified-quote"
        assert not any(url.endswith("/checkout/create") for url, _ in calls)
        payload["paddle_dia"] = 12.0
        assert line["inputs"]["paddle_dia"] == 5.0


def test_confirmed_owner_direct_checkout_sends_only_existing_canonical_inputs(
    monkeypatch,
):
    for app, payload, calls in _quote_app(monkeypatch, checkout_enabled=True):
        button = next(b for b in app.button if b.label == "Continue to secure checkout")
        assert not button.disabled
        button.click().run()
        assert not app.exception
        sent = [body for url, body in calls if url.endswith("/checkout/create")]
        assert len(sent) == 1
        assert sent[0]["inputs"] == QuoteInputs(**payload).model_dump()
        assert sent[0]["configuration_id"] == "verified-quote"
        assert sent[0]["pricing_config_version"] == "current-test-version"
        assert not any("drawing" in key for key in sent[0])


def test_pricing_relevant_edit_disables_checkout_and_hides_old_price(monkeypatch):
    for app, payload, calls in _quote_app(monkeypatch, checkout_enabled=True):
        next(
            field
            for field in app.number_input
            if field.label == "Plate outside diameter (in.)"
        ).set_value(5.25).run()
        assert not app.exception
        assert not app.session_state["phase1g_customer_confirmation"]
        assert next(b for b in app.button if b.label == "Add another plate").disabled
        assert next(
            b for b in app.button if b.label == "Continue to secure checkout"
        ).disabled
        assert not any(metric.label == "Unit price" for metric in app.metric)
        assert not any(url.endswith("/checkout/create") for url, _ in calls)


def test_next_plate_resets_editor_but_preserves_independent_cart_snapshot(monkeypatch):
    for app, payload, calls in _quote_app(monkeypatch, checkout_enabled=True):
        cart_snapshot = {
            "line_id": "previous",
            "inputs": QuoteInputs(**payload).model_dump(),
            "assisted_quote": True,
        }
        app.session_state["cart"] = [cart_snapshot]
        app.session_state["phase1k_new_plate_requested"] = True
        app.run()
        assert not app.exception
        assert app.session_state.get("phase1g_assisted_session") is None
        assert app.session_state["quote_field_paddle_dia"] == 3.0
        assert app.session_state.cart == [cart_snapshot]


def test_unconfirmed_quote_cannot_add_or_start_checkout(monkeypatch):
    for app, payload, calls in _quote_app(
        monkeypatch, checkout_enabled=True, confirmed=False
    ):
        assert next(b for b in app.button if b.label == "Add another plate").disabled
        assert next(
            b for b in app.button if b.label == "Continue to secure checkout"
        ).disabled
        assert not calls


def test_owner_cart_freezes_confirmed_line_and_reprices_each_snapshot(monkeypatch):
    monkeypatch.setenv("API_KEY", "test-ui-key")
    monkeypatch.setenv("API_BASE", "http://test")
    monkeypatch.setenv("OPLATES_OWNER_ACCEPTANCE_MODE", "true")
    monkeypatch.setenv("OPLATES_OWNER_TEST_CHECKOUT_ENABLED", "true")
    monkeypatch.setattr(auth, "API_BASE", "http://test")
    first = QuoteInputs(**_payload()).model_dump()
    corrected = QuoteInputs(
        **_payload(od=10.25, bore=3.75, thickness=0.25)
    ).model_dump()
    cart = [
        {"line_id": "first", "inputs": first.copy(), "assisted_quote": True},
        {"line_id": "corrected", "inputs": corrected.copy(), "assisted_quote": True},
    ]
    calls = []

    def fake_get(url, **kwargs):
        return Response(
            {"enabled": True, "authorized": True, "user_id": "internal-user"}
        )

    def fake_post(url, **kwargs):
        calls.append((url, kwargs["json"]))
        if url.endswith("/quote"):
            return Response(priced(kwargs["json"]))
        return Response(
            {
                "checkout_url": "https://checkout.stripe.test/test-session",
                "session_id": "cs_test_phase1k",
            }
        )

    with (
        patch("requests.get", fake_get),
        patch("requests.post", fake_post),
        patch("streamlit.switch_page"),
    ):
        app = AppTest.from_file(str(ROOT / "pages" / "3_Quote_Cart.py"))
        app.session_state["auth"] = {
            "access_token": _jwt(),
            "refresh_token": None,
            "user": None,
            "email": "internal@example.com",
        }
        app.session_state["cart"] = cart
        app.run()
        assert not app.exception
        assert len([c for c in calls if c[0].endswith("/quote")]) == 2
        assert all(field.disabled for field in app.number_input if field.label == "Qty")
        assert (
            next(b for b in app.button if b.label == "💳 Checkout All Items").disabled
            is False
        )
        next(b for b in app.button if b.label == "💳 Checkout All Items").click().run()
        assert not app.exception
        checkout_calls = [c for c in calls if c[0].endswith("/checkout/cart/create")]
        assert len(checkout_calls) == 1
        sent = checkout_calls[0][1]
        assert sent["items"] == [first, corrected]
        assert sent["pricing_config_version"] == "current-test-version"
        assert not any("drawing" in key or "confirmation" in key for key in sent)
        assert app.session_state.cart[0]["inputs"] == first
        assert app.session_state.cart[1]["inputs"] == corrected
        next(b for b in app.button if b.label == "➕ Add another plate").click().run()
        assert app.session_state["phase1k_new_plate_requested"] is True


def test_owner_cart_checkout_remains_disabled_without_switch_or_access(monkeypatch):
    monkeypatch.setenv("API_KEY", "test-ui-key")
    monkeypatch.setenv("API_BASE", "http://test")
    monkeypatch.setenv("OPLATES_OWNER_ACCEPTANCE_MODE", "true")
    monkeypatch.setattr(auth, "API_BASE", "http://test")
    calls = []

    for enabled, authorized in ((False, True), (True, False)):
        monkeypatch.setenv("OPLATES_OWNER_TEST_CHECKOUT_ENABLED", str(enabled).lower())
        with (
            patch(
                "requests.get",
                return_value=Response(
                    {
                        "enabled": True,
                        "authorized": authorized,
                        "user_id": "internal-user",
                    }
                ),
            ),
            patch(
                "requests.post",
                side_effect=lambda url, **kw: (
                    calls.append(url) or Response(priced(kw["json"]))
                ),
            ),
        ):
            app = AppTest.from_file(str(ROOT / "pages" / "3_Quote_Cart.py"))
            app.session_state["auth"] = {
                "access_token": _jwt(),
                "refresh_token": None,
                "user": None,
                "email": "internal@example.com",
            }
            app.session_state["cart"] = [
                {"line_id": "one", "inputs": _payload(), "assisted_quote": True}
            ]
            app.run()
            assert not app.exception
            assert next(
                b for b in app.button if b.label == "💳 Checkout All Items"
            ).disabled
            assert not any(url.endswith("/checkout/cart/create") for url in calls)


def test_fresh_quote_session_recovers_corrected_checkout_snapshot(monkeypatch):
    import drawing_intake.checkout_recovery as recovery

    monkeypatch.setenv("API_KEY", "test-ui-key")
    monkeypatch.setenv("API_BASE", "http://test")
    monkeypatch.setenv("OPLATES_DRAWING_ASSISTED_ENABLED", "true")
    monkeypatch.setenv("OPLATES_OWNER_ACCEPTANCE_MODE", "true")
    monkeypatch.setenv("OPLATES_OWNER_TEST_CHECKOUT_ENABLED", "false")
    monkeypatch.setattr(auth, "API_BASE", "http://test")
    payload = _payload()
    payload.update(
        paddle_dia=10.25,
        bore_dia=3.75,
        thickness=0.25,
        handle_width=2.0,
        handle_length_from_bore=14.0,
        quantity=3,
    )
    calls = []
    with (
        patch.object(
            recovery,
            "fetch_checkout_recovery",
            return_value={
                "kind": "direct",
                "items": [payload],
                "contexts": [
                    {
                        "document_class": "single_plate_drawing",
                        "selected_candidate_id": "selected-detail",
                        "candidate_count": 1,
                        "selection_required": False,
                    }
                ],
            },
        ) as fetch,
        patch(
            "requests.get",
            lambda url, **kwargs: Response(
                ACTIVE
                if url.endswith("/config/active")
                else {"enabled": True, "authorized": True, "user_id": "internal-user"}
            ),
        ),
        patch(
            "requests.post",
            lambda url, **kwargs: calls.append(url) or Response(priced(kwargs["json"])),
        ),
        patch("streamlit.switch_page"),
    ):
        app = AppTest.from_file(str(ROOT / "pages" / "1_Quote.py"), default_timeout=20)
        app.session_state["auth"] = {
            "access_token": _jwt(),
            "refresh_token": None,
            "user": None,
            "email": "internal@example.com",
        }
        app.query_params["checkout"] = "cancelled"
        app.query_params["resume"] = "a" * 64
        app.run()
        assert not app.exception
        for field, value in payload.items():
            assert app.session_state[f"quote_field_{field}"] == value
        assert app.session_state["phase1g_customer_confirmation"] is False
        assert not calls
        app.checkbox(key="phase1g_customer_confirmation").check().run()
        assert not app.exception
        assert calls == ["http://test/quote"]
        assert app.session_state["quote_field_paddle_dia"] == 10.25
        calls.clear()
        app.number_input(key="quote_field_paddle_dia").set_value(10.5).run()
        assert not app.exception
        assert app.session_state["quote_field_paddle_dia"] == 10.5
        assert fetch.call_count == 1
        assert not calls
        assert app.session_state["phase1g_customer_confirmation"] is False
        app.checkbox(key="phase1g_customer_confirmation").check().run()
        assert not app.exception
        assert calls == ["http://test/quote"]


def test_fresh_cart_session_recovers_independent_lines_and_editor(monkeypatch):
    import drawing_intake.checkout_recovery as recovery

    monkeypatch.setenv("API_KEY", "test-ui-key")
    monkeypatch.setenv("API_BASE", "http://test")
    monkeypatch.setenv("OPLATES_OWNER_ACCEPTANCE_MODE", "true")
    monkeypatch.setenv("OPLATES_OWNER_TEST_CHECKOUT_ENABLED", "true")
    monkeypatch.setattr(auth, "API_BASE", "http://test")
    first = _payload()
    second = dict(
        first, paddle_dia=10.25, bore_dia=3.75, quantity=3, handle_length_from_bore=14.0
    )
    calls = []
    with (
        patch.object(
            recovery,
            "fetch_checkout_recovery",
            return_value={"kind": "cart", "items": [first, second]},
        ) as fetch,
        patch(
            "requests.get",
            lambda url, **kwargs: Response(
                {"enabled": True, "authorized": True, "user_id": "internal-user"}
            ),
        ),
        patch(
            "requests.post",
            lambda url, **kwargs: calls.append((url, kwargs["json"]))
            or Response(priced(kwargs["json"])),
        ),
        patch("streamlit.switch_page"),
    ):
        app = AppTest.from_file(
            str(ROOT / "pages" / "3_Quote_Cart.py"), default_timeout=20
        )
        app.session_state["auth"] = {
            "access_token": _jwt(),
            "refresh_token": None,
            "user": None,
            "email": "internal@example.com",
        }
        app.query_params["checkout"] = "cancelled"
        app.query_params["resume"] = "a" * 64
        app.run()
        assert not app.exception
        assert [line["inputs"] for line in app.session_state["cart"]] == [first, second]
        assert len({line["line_id"] for line in app.session_state["cart"]}) == 2
        assert app.session_state["quote_field_paddle_dia"] == 10.25
        assert app.session_state["phase1g_customer_confirmation"] is False
        assert next(
            b for b in app.button if b.label == "💳 Checkout All Items"
        ).disabled
        assert all(url.endswith("/quote") for url, body in calls)
        app.run()
        assert not app.exception
        assert fetch.call_count == 1
        assert [line["inputs"] for line in app.session_state["cart"]] == [first, second]
