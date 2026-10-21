"""Expedited display follows existing availability without new quote eligibility."""

import pytest
import requests
import streamlit as st

from test_landing_convergence import CONFIG, response
from ui_harness import customer_page_test


@pytest.fixture
def lead_page(monkeypatch):
    st.cache_data.clear()
    monkeypatch.setenv("API_BASE", "http://offline-fixture")
    monkeypatch.delenv("OPLATES_DRAWING_ASSISTED_ENABLED", raising=False)
    monkeypatch.delenv("OPLATES_OWNER_ACCEPTANCE_MODE", raising=False)
    config = {**CONFIG, "lead_time_enabled": {"7": False, "14": True, "21": True}}
    monkeypatch.setattr(requests, "get", lambda *a, **k: response(config))
    calls = []

    def post(url, **kwargs):
        assert url.endswith("/quote")
        calls.append(kwargs["json"])
        return response(dict(unit_price=100, total_price=100, configuration_id="synthetic"))

    monkeypatch.setattr(requests, "post", post)
    return customer_page_test("pages/1_Quote.py").run(), config, calls


def assert_coming_soon(app):
    button = app.button(key="lead_time_coming_soon")
    assert button.label == "Today / 2-Day · Coming Soon"
    assert button.disabled
    options = app.button_group(key="quote_field_ships_in_days").options
    assert "0 calendar days" not in options and "2 calendar days" not in options
    assert not any("Coming Soon" in option for option in options)


def test_off_keeps_ghosted_options_and_standard_selections(lead_page):
    app, config, calls = lead_page
    assert not app.exception
    unavailable = app.button(key="lead_time_7_unavailable")
    assert unavailable.label == "7 Days · Currently Unavailable"
    assert unavailable.disabled
    assert_coming_soon(app)
    assert app.button_group(key="quote_field_ships_in_days").options == [
        "14 calendar days", "21 calendar days",
    ]
    for days in (21, 14):
        app.button_group(key="quote_field_ships_in_days").set_value(days).run()
        assert calls[-1]["ships_in_days"] == days
        assert not app.exception


def test_existing_toggle_enables_seven_and_revokes_stale_selection(lead_page):
    app, config, calls = lead_page
    config["lead_time_enabled"]["7"] = True
    config["lead_times_days"] = [7, 14, 21]
    st.cache_data.clear()
    app.run()
    assert app.button_group(key="quote_field_ships_in_days").options == [
        "7 Days", "14 calendar days", "21 calendar days",
    ]
    assert not any(b.key == "lead_time_7_unavailable" for b in app.button)
    app.button_group(key="quote_field_ships_in_days").set_value(7).run()
    assert calls[-1]["ships_in_days"] == 7
    assert_coming_soon(app)
    before = len(calls)
    config["lead_time_enabled"]["7"] = False
    config["lead_times_days"] = [14, 21]
    st.cache_data.clear()
    app.run()
    assert not app.exception
    assert app.button(key="lead_time_7_unavailable").disabled
    assert app.button_group(key="quote_field_ships_in_days").value is None
    assert len(calls) == before
    assert not app.metric
    assert next(b for b in app.button if b.label == "Continue to secure checkout").disabled
    assert next(b for b in app.button if b.label == "Add another plate").disabled
    app.button_group(key="quote_field_ships_in_days").set_value(14).run()
    assert calls[-1]["ships_in_days"] == 14


@pytest.mark.parametrize("unavailable", [0, 2, 7])
def test_unavailable_lead_cannot_become_quote_or_purchase_value(lead_page, unavailable):
    previous, _, calls = lead_page
    before = len(calls)
    # Seed a restored form before widget creation; AppTest otherwise resends the
    # already-rendered widget's valid value over a direct session-state edit.
    app = customer_page_test("pages/1_Quote.py")
    app.session_state["phase1g_form_origins"] = {}
    for field, value in previous.session_state["phase1g_form_snapshot"].items():
        app.session_state["quote_field_" + field] = value
    app.session_state["quote_field_ships_in_days"] = unavailable
    app.run()
    assert not app.exception
    assert app.button_group(key="quote_field_ships_in_days").value is None
    assert len(calls) == before
    assert not app.metric
    assert next(b for b in app.button if b.label == "Continue to secure checkout").disabled
    assert next(b for b in app.button if b.label == "Add another plate").disabled
    assert_coming_soon(app)
