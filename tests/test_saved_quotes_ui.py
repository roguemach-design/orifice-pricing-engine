"""Exercise the shipped account/cart pages through Streamlit's real app runner."""

from types import SimpleNamespace
import copy
import requests
import streamlit as st
import auth
from ui_harness import customer_page_test
from test_drawing_phase1g import _jwt
from test_landing_convergence import CONFIG, response
from test_checkout_workflow import quote_inputs


def setup(monkeypatch, shared=False, expired=False):
    st.cache_data.clear()
    monkeypatch.setenv("API_BASE", "http://offline-fixture")
    monkeypatch.setattr(auth, "API_BASE", "http://offline-fixture")
    monkeypatch.setenv("SAVED_QUOTES_ENABLED", "true")
    monkeypatch.setattr(auth, "_cookie_set", lambda data: None)
    calls = []
    inputs = quote_inputs(chamfer=False)
    line = {"inputs": inputs, "unit_price": 125.0, "total_price": 125.0}
    row = {
        "quote_id": "Q-SYNTHETIC1",
        "root_quote_id": "Q-SYNTHETIC1",
        "supersedes_quote_id": None,
        "created_at": "2026-10-22T12:00:00+00:00",
        "valid_through": "2026-11-21T12:00:00+00:00",
        "status": "expired" if expired else "open",
        "subtotal": "125",
        "shared_with_you": shared,
        "snapshot": {"lines": [line], "customer": {}, "pricing_ref": "current"},
    }

    def get(url, **kw):
        calls.append(("GET", url, kw))
        if url.endswith("/me/quotes"):
            return response([row])
        if url.endswith("/pdf"):
            return SimpleNamespace(status_code=200, content=b"%PDF synthetic")
        if url.endswith("/shares"):
            return response([])
        if url.endswith("/config/active"):
            return response({**CONFIG, "lead_times_days": [14, 21]})
        if url.endswith("/checkout/availability"):
            return response({"available": True, "mode": "test"})
        return response(row)

    def post(url, **kw):
        calls.append(("POST", url, copy.deepcopy(kw)))
        if url.endswith("/revalidate"):
            return response(
                {
                    "lines": [line],
                    "quoted_lines": [line],
                    "pricing_ref": "current",
                    "changed": True,
                    "review_id": "review-synthetic",
                    "quoted_subtotal": "125",
                    "current_subtotal": "125",
                }
            )
        if url.endswith("/shares"):
            return response({"share_id": "share-synthetic", "email_status": "captured"})
        if url.endswith("/revisions"):
            return response({"quote_id": "Q-SYNTHETIC1-R2"})
        if url.endswith("/quote"):
            return response(
                {
                    "unit_price": 125,
                    "total_price": 125,
                    "pricing_config_version": "current",
                }
            )
        return response({"accepted": True, "quote_id": "Q-SYNTHETIC1"})

    monkeypatch.setattr(requests, "get", get)
    monkeypatch.setattr(requests, "post", post)
    app = customer_page_test("pages/7_My_Quotes.py")
    app.session_state["auth"] = {
        "access_token": _jwt("buyer" if shared else "owner"),
        "refresh_token": None,
        "user": None,
        "email": "purchasing@example.test" if shared else "engineer@example.test",
    }
    app.session_state["saved_quote_intent"] = "Q-SYNTHETIC1"
    return app, calls, inputs


def test_account_share_review_and_existing_cart_handoff(monkeypatch):
    app, calls, inputs = setup(monkeypatch)
    app.run()
    assert not app.exception
    app.text_input[1].set_value("purchasing@example.test")
    next(b for b in app.button if b.label == "Send purchasing invitation").click().run()
    assert not app.exception
    assert any(
        url.endswith("/shares") and data["json"]["email"] == "purchasing@example.test"
        for method, url, data in calls
        if method == "POST"
    )
    next(b for b in app.button if b.label == "Review current pricing").click().run()
    assert not app.exception
    assert next(b for b in app.button if b.label == "Continue in Quote Cart").disabled
    next(
        c for c in app.checkbox if c.label == "I've reviewed the changes"
    ).check().run()
    next(b for b in app.button if b.label == "Continue in Quote Cart").click().run()
    assert not app.exception
    assert app.session_state["cart"][0]["inputs"] == inputs
    assert app.session_state["saved_quote_cart"]["quote_id"] == "Q-SYNTHETIC1"
    assert app.session_state["saved_quote_cart"]["acknowledged"] is True
    assert not any(url.endswith("/checkout/cart/create") for method, url, data in calls)


def test_invited_buyer_has_no_owner_share_controls(monkeypatch):
    app, calls, inputs = setup(monkeypatch, shared=True)
    app.run()
    assert not app.exception
    assert "Share with Purchasing" not in [e.label for e in app.expander]
    assert "Review current pricing" in [b.label for b in app.button]


def test_expired_quote_offers_update_pricing_and_no_checkout(monkeypatch):
    app, calls, inputs = setup(monkeypatch, expired=True)
    app.run()
    assert not app.exception
    labels = [b.label for b in app.button]
    assert "Update Pricing" in labels and "Review current pricing" not in labels


def test_find_number_survives_signed_out_state(monkeypatch):
    app, calls, inputs = setup(monkeypatch)
    app.session_state["auth"] = {
        "access_token": None,
        "refresh_token": None,
        "user": None,
        "email": "",
    }
    app.run()
    assert not app.exception
    field = next(t for t in app.text_input if t.label == "Find a Quote by number")
    field.set_value("Q-PRESERVE01")
    next(b for b in app.button if b.label == "Find a Quote").click().run()
    assert app.session_state["saved_quote_intent"] == "Q-PRESERVE01"
    assert not any(url.endswith("/me/quotes") for method, url, data in calls)
