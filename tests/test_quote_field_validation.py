"""Field feedback must preserve the SVG and prevent stale pricing/purchasing."""

import math

import pytest
import requests
import streamlit as st

from drawing_intake.assisted_quote import availability_from_active_config
from quote_field_validation import field_errors
from test_landing_convergence import CONFIG, response, select
from ui_harness import customer_page_test


@pytest.fixture
def quote_page(monkeypatch):
    st.cache_data.clear()
    monkeypatch.setenv("API_BASE", "http://offline-fixture")
    monkeypatch.delenv("OPLATES_DRAWING_ASSISTED_ENABLED", raising=False)
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.delenv("OPLATES_OWNER_ACCEPTANCE_MODE", raising=False)
    monkeypatch.setattr(requests, "get", lambda *a, **k: response(CONFIG))
    calls = []

    def post(url, **kwargs):
        assert url.endswith("/quote")
        calls.append(kwargs["json"])
        return response(dict(unit_price=100, total_price=100, configuration_id="synthetic"))

    monkeypatch.setattr(requests, "post", post)
    return customer_page_test("pages/1_Quote.py").run(), calls


@pytest.mark.parametrize("field,value,affected", [
    ("paddle_dia", None, {"paddle_dia"}),
    ("quantity", 0, {"quantity"}),
    ("paddle_dia", 49.0, {"paddle_dia"}),
    ("bore_dia", 3.0, {"paddle_dia", "bore_dia"}),
    ("handle_length_from_bore", 1.0, {"paddle_dia", "handle_length_from_bore"}),
    ("handle_width", 3.0, {"paddle_dia", "handle_width"}),
    ("handle_width", 0.03, {"handle_width"}),
    ("bore_dia", 2.999, {"paddle_dia", "bore_dia", "bore_tolerance"}),
])
def test_invalid_edit_preserves_last_drawing_without_quote(quote_page, field, value, affected):
    app, calls = quote_page
    baseline = app.session_state["quote_last_valid_svg"]
    old_value = app.number_input(key="quote_field_" + field).value
    before = len(calls)
    app.number_input(key="quote_field_" + field).set_value(value).run()
    assert not app.exception
    assert len(calls) == before
    assert len(app.metric) == 0
    assert app.session_state["quote_last_valid_svg"] == baseline
    assert any(item.value == baseline for item in app.markdown)
    assert any("Last valid configuration shown" in item.value for item in app.warning)
    for name in affected:
        assert any(f'data-field-error="{name}"' in item.value for item in app.markdown)
    assert next(b for b in app.button if b.label == "Continue to secure checkout").disabled
    assert next(b for b in app.button if b.label == "Add another plate").disabled
    app.number_input(key="quote_field_" + field).set_value(old_value).run()
    assert not app.exception
    assert len(calls) == before + 1
    assert len(app.metric) == 2
    assert not any("data-field-error=" in item.value for item in app.markdown)


def test_conditional_defaults_preserve_edits_and_invalid_text(quote_page):
    app, calls = quote_page
    select(app, "quote_field_chamfer", True)
    select(app, "quote_field_handle_hole_enabled", True)
    app.run()
    assert not app.exception
    assert calls[-1]["chamfer_width"] == 0.062
    assert calls[-1]["handle_hole_diameter"] == 0.375
    assert calls[-1]["handle_hole_center_from_handle_end"] == 0.750
    app.number_input(key="quote_field_chamfer_width").set_value(0.04)
    app.text_input(key="quote_field_handle_hole_diameter_text").set_value("1/2")
    app.text_input(key="quote_field_handle_hole_center_from_handle_end_text").set_value("1.25")
    app.run()
    select(app, "quote_field_chamfer", False)
    select(app, "quote_field_handle_hole_enabled", False)
    app.run()
    assert calls[-1]["chamfer_width"] is None
    assert "handle_hole_diameter" not in calls[-1]
    select(app, "quote_field_chamfer", True)
    select(app, "quote_field_handle_hole_enabled", True)
    app.run()
    assert not app.exception
    assert calls[-1]["chamfer_width"] == 0.04
    assert calls[-1]["handle_hole_diameter"] == 0.5
    assert calls[-1]["handle_hole_center_from_handle_end"] == 1.25
    before = len(calls)
    app.text_input(key="quote_field_handle_hole_diameter_text").set_value("bad").run()
    assert not app.exception
    assert len(calls) == before
    assert any('data-field-error="handle_hole_diameter"' in item.value for item in app.markdown)
    select(app, "quote_field_handle_hole_enabled", False)
    app.run()
    select(app, "quote_field_handle_hole_enabled", True)
    app.run()
    assert app.text_input(key="quote_field_handle_hole_diameter_text").value == "bad"
    assert len(app.metric) == 0
    app.text_input(key="quote_field_handle_hole_diameter_text").set_value("").run()
    assert len(app.metric) == 0
    select(app, "quote_field_handle_hole_enabled", False)
    app.run()
    select(app, "quote_field_handle_hole_enabled", True)
    app.run()
    assert calls[-1]["handle_hole_diameter"] == 0.375
    assert calls[-1]["handle_hole_center_from_handle_end"] == 1.25


@pytest.mark.parametrize("value", [float("nan"), float("inf"), "invalid"])
def test_nonfinite_or_nonnumeric_fields_are_invalid(value):
    values = dict(quantity=1, material="304", thickness=.125, paddle_dia=3., bore_dia=1.,
                  handle_width=1.5, handle_length_from_bore=9., bore_tolerance=.005,
                  ships_in_days=14, chamfer=False, handle_label="")
    values["paddle_dia"] = value
    assert "paddle_dia" in field_errors(values, availability_from_active_config(CONFIG))
