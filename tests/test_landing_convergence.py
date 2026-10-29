from ui_harness import customer_page_test

"""Customer selections preserve accepted request values and artifact fingerprints."""

import json
import ast
from pathlib import Path
from types import SimpleNamespace

import pytest
import requests
import streamlit as st
from streamlit.testing.v1 import AppTest

from frozen_plate.repository import canonical, digest
from manufacturing_files import pdf_bytes, dxf_bytes
from plate_geometry import PlateSpec, build_plate_geometry, canonical_specification
from plate_preview import render_plate_svg
from pricing_engine import QuoteInputs, calculate_quote

ROOT = Path(__file__).resolve().parents[1]
CASES = [
    dict(
        material="304",
        thickness=0.125,
        bore_tolerance=0.005,
        ships_in_days=21,
        chamfer=False,
        hole=False,
    ),
    dict(
        material="316",
        thickness=0.25,
        bore_tolerance=0.002,
        ships_in_days=14,
        chamfer=False,
        hole=True,
    ),
    dict(
        material="Carbon Steel",
        thickness=0.375,
        bore_tolerance=0.001,
        ships_in_days=21,
        chamfer=True,
        hole=True,
    ),
]
CONFIG = dict(
    materials=["304", "316", "Carbon Steel"],
    thicknesses_by_material={
        m: [0.125, 0.25, 0.375, 0.5] for m in ["304", "316", "Carbon Steel"]
    },
    lead_times_days=[14, 21],
    default_lead_time_days=14,
    tolerance_options_in=[0.001, 0.002, 0.005],
    max_paddle_dia_in=48,
    max_bore_dia_in=19,
    max_handle_label_chars=40,
)


def response(data):
    return SimpleNamespace(
        status_code=200, raise_for_status=lambda: None, json=lambda: data
    )


def select(app, key, value):
    for kind in ("button_group", "selectbox", "checkbox"):
        widgets = getattr(app, kind)
        for item in widgets:
            if item.key == key or (
                key == "quote_field_chamfer" and item.label == "Chamfer"
            ):
                item.set_value(value)
                return
    raise AssertionError(f"Missing choice: {key}")


def exercise(app, case):
    app.run()
    select(app, "quote_field_material", case["material"])
    app.run()
    for field in ("thickness", "bore_tolerance", "ships_in_days", "chamfer"):
        select(app, "quote_field_" + field, case[field])
    select(app, "quote_field_handle_hole_enabled", case["hole"])
    app.run()
    for field, value in dict(
        paddle_dia=5.0, bore_dia=1.548, handle_width=2.0, handle_length_from_bore=10.5
    ).items():
        app.number_input(key="quote_field_" + field).set_value(value)
    if case["hole"]:
        app.text_input(key="quote_field_handle_hole_diameter_text").set_value("3/8")
        app.text_input(
            key="quote_field_handle_hole_center_from_handle_end_text"
        ).set_value("3/4")
    if case["chamfer"]:
        app.number_input(key="quote_field_chamfer_width").set_value(0.02)
    app.run()
    assert not app.exception


def fingerprints(payload):
    spec = PlateSpec.from_configuration(payload, part_identifier="CONVERGENCE-TEST")
    geometry = build_plate_geometry(spec)
    svg = render_plate_svg(
        **{
            k: payload[k]
            for k in (
                "paddle_dia",
                "bore_dia",
                "handle_width",
                "handle_length_from_bore",
                "thickness",
                "material",
                "bore_tolerance",
                "handle_label",
                "chamfer",
                "chamfer_width",
            )
        },
        **{k: v for k, v in payload.items() if k.startswith("handle_hole")},
    )
    return dict(
        payload=payload,
        price=calculate_quote(QuoteInputs(**payload)),
        spec_sha256=digest(canonical(canonical_specification(spec)).encode()),
        pdf_sha256=digest(pdf_bytes(geometry)),
        dxf_sha256=digest(dxf_bytes(geometry)),
        svg_sha256=digest(svg.encode()),
    )


@pytest.mark.parametrize("index", range(3))
def test_choices_match_accepted_baseline(monkeypatch, index):
    st.cache_data.clear()
    monkeypatch.setenv("API_BASE", "http://offline-fixture")
    monkeypatch.setenv("OPLATES_OWNER_ACCEPTANCE_MODE", "true")
    monkeypatch.delenv("OPLATES_DRAWING_ASSISTED_ENABLED", raising=False)
    monkeypatch.setattr(requests, "get", lambda *a, **k: response(CONFIG))
    calls = []

    def post(*a, **k):
        calls.append(k["json"])
        return response(
            dict(unit_price=100.0, total_price=100.0, configuration_id="offline")
        )

    monkeypatch.setattr(requests, "post", post)
    app = customer_page_test("pages/1_Quote.py", default_timeout=20)
    exercise(app, CASES[index])
    golden = json.loads((ROOT / "tests/fixtures/convergence-baseline.json").read_text())
    actual=fingerprints(calls[-1])
    presentation=json.loads((ROOT / "tests/fixtures/v7-1-convergence-hashes.json").read_text())
    for key,value in actual.items():
        assert value == (presentation[index][key] if key in ("pdf_sha256","svg_sha256") else golden["cases"][index][key])


def test_dynamic_availability_keeps_unresolved_choices(monkeypatch):
    st.cache_data.clear()
    monkeypatch.setenv("API_BASE", "http://offline-fixture")
    monkeypatch.delenv("OPLATES_DRAWING_ASSISTED_ENABLED", raising=False)
    config = {
        **CONFIG,
        "thicknesses_by_material": {
            "304": [0.125, 0.25],
            "316": [0.125],
            "Carbon Steel": [0.375],
        },
    }
    monkeypatch.setattr(requests, "get", lambda *a, **k: response(config))
    calls = []
    monkeypatch.setattr(
        requests,
        "post",
        lambda *a, **k: (
            calls.append(k["json"]) or response(dict(unit_price=1.0, total_price=1.0))
        ),
    )
    app = customer_page_test("pages/1_Quote.py").run()
    app.button_group(key="quote_field_thickness").set_value(0.25).run()
    app.button_group(key="quote_field_material").set_value("316").run()
    assert app.button_group(key="quote_field_thickness").value == 0.125
    assert calls[-1]["thickness"] == 0.125
    # Analyzer/recovery may intentionally leave a field unresolved before first render.
    unresolved = customer_page_test("pages/1_Quote.py")
    unresolved.session_state["phase1g_form_origins"] = {}
    unresolved.session_state["quote_field_bore_tolerance"] = None
    before = len(calls)
    unresolved.run()
    assert unresolved.button_group(key="quote_field_bore_tolerance").value is None
    assert len(calls) == before


def test_navigation_retains_hidden_compatible_routes():
    source = (ROOT / "customer_navigation.py").read_text()
    routes = {}
    for call in ast.walk(ast.parse(source)):
        if (
            isinstance(call, ast.Call)
            and isinstance(call.func, ast.Attribute)
            and call.func.attr == "Page"
        ):
            keywords = {
                item.arg: ast.literal_eval(item.value) for item in call.keywords
            }
            if "url_path" in keywords:
                routes[keywords["url_path"]] = keywords.get("visibility", "visible")
    for route in ("Success", "Drawing_Approval", "Internal_Sourcing"):
        assert routes[route] == "hidden"
    for route in ("Quote", "My_Orders", "Quote_Cart"):
        assert routes[route] == "visible"
    html = (ROOT / "o-plates landing/index.html").read_text()
    assert 'id="configurator"' in html and 'id="plate-configurator"' in html
    assert html.count('href="#configurator"') == 3
    assert 'name="robots" content="noindex' not in html


@pytest.mark.parametrize(
    "path",
    ["pages/2_My_Orders.py", "pages/3_Quote_Cart.py", "pages/6_Internal_Sourcing.py"],
)
def test_customer_entrypoint_retains_routes_and_guest_gates(monkeypatch, path):
    import auth

    st.cache_data.clear()
    monkeypatch.setenv("API_BASE", "http://offline-fixture")
    monkeypatch.delenv("OPLATES_DRAWING_ASSISTED_ENABLED", raising=False)
    monkeypatch.setattr(auth, "API_BASE", "http://offline-fixture")
    monkeypatch.setattr(auth, "render_auth_sidebar", lambda **kwargs: None)
    monkeypatch.setattr(requests, "get", lambda *a, **k: response(CONFIG))
    monkeypatch.setattr(
        requests,
        "post",
        lambda *a, **k: response(dict(unit_price=1.0, total_price=1.0)),
    )
    app = AppTest.from_file(str(ROOT / "app.py")).run()
    assert not app.exception
    app.switch_page(path).run()
    assert not app.exception
    if path.endswith("My_Orders.py"):
        assert any("log in" in item.value.lower() for item in [*app.info, *app.warning])
    if path.endswith("Internal_Sourcing.py"):
        # An unbound environment fails closed before requesting credentials/data.
        assert not app.text_input
        assert not app.get("dataframe")


def test_cold_direct_embedded_quote_initializes_customer_shell(monkeypatch):
    st.cache_data.clear()
    monkeypatch.setenv("API_BASE", "http://offline-fixture")
    monkeypatch.delenv("OPLATES_DRAWING_ASSISTED_ENABLED", raising=False)
    monkeypatch.setattr(requests, "get", lambda *a, **k: response(CONFIG))
    monkeypatch.setattr(
        requests,
        "post",
        lambda *a, **k: response(dict(unit_price=1.0, total_price=1.0)),
    )
    app = customer_page_test("pages/1_Quote.py")
    app.query_params["integrated"] = "1"
    app.run()
    assert not app.exception
    assert app.session_state["integrated_landing"] is True
    assert not app.title  # The landing section already provides the one heading.
    assert app.button(key="starter_sign_in").label == "Sign in"
    assert app.button(key="starter_sign_in").proto.type == "secondary"
    assert not app.sidebar.text_input
    page_links = app.get("page_link")
    assert [x.proto.label for x in page_links] == [
        "Configure your plate",
        "My Orders",
        "Quote Cart",
    ]
    assert (
        "showSidebarNavigation=false" in (ROOT / ".streamlit/config.toml").read_text()
    )


def test_signed_in_account_is_compact_and_logout_still_clears_session(monkeypatch):
    import auth
    st.cache_data.clear()
    monkeypatch.setenv("API_BASE", "http://offline-fixture")
    monkeypatch.delenv("OPLATES_DRAWING_ASSISTED_ENABLED", raising=False)
    monkeypatch.setattr(requests, "get", lambda *a, **k: response(CONFIG))
    monkeypatch.setattr(requests, "post", lambda *a, **k: response(dict(unit_price=1.0, total_price=1.0)))
    monkeypatch.setattr(auth, "_restore_auth_from_cookie_if_needed", lambda: None)
    monkeypatch.setattr(auth, "_refresh_session_if_needed", lambda: None)
    monkeypatch.setattr(auth, "_cookie_clear", lambda: None)
    app = customer_page_test("pages/1_Quote.py")
    app.session_state["auth"] = dict(access_token=__import__("test_checkout_identity_gate")._jwt("fixture"), refresh_token=None, user=None, email="customer@example.test")
    app.run()
    assert not app.exception
    assert any(x.value == "Signed in as: customer@example.test" for x in app.caption)
    assert not any("Logged in as" in x.value for x in app.success)
    assert not any(x.label == "Account" for x in app.expander)
    assert app.title[0].value == "Configure your plate"
    app.button(key="account_log_out").click().run()
    assert not app.exception
    assert app.session_state["auth"]["access_token"] is None
    assert app.button(key="starter_sign_in").label == "Sign in"
    assert app.button(key="starter_sign_in").proto.type == "secondary"


def test_material_cards_keep_required_unresolved_selection():
    def render():
        from customer_controls import material_cards
        material_cards(["304", "316", "Carbon Steel"], key="material")
    app = AppTest.from_function(render).run()
    assert not app.exception
    assert app.button_group(key="material").value is None
    assert app.button_group(key="material").options == [
        "**304 SS**\n\nGeneral-purpose stainless.",
        "**316 SS**\n\nAdded corrosion resistance.",
        "**Carbon Steel**\n\nCost-effective steel.",
    ]
    for value in ("304", "316", "Carbon Steel"):
        app.button_group(key="material").set_value(value).run()
        assert not app.exception
        assert app.session_state["material"] == value
