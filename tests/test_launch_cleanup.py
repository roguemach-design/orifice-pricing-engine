import ast
import io
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo
from typing import Any, Dict, List
import os

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pypdf import PdfReader

import api_app as api
from customer_safety import customer_product_details, service_message
from test_checkout_workflow import quote_inputs

ROOT = Path(__file__).resolve().parents[1]


def test_customer_errors_never_echo_provider_exception(monkeypatch):
    monkeypatch.setattr(api, "API_KEY", "synthetic-quote")
    api._RATE_LIMITER.clear()
    secret = "postgresql://private:synthetic-secret@private-host/db"

    def fail(*args, **kwargs):
        raise RuntimeError(secret)

    monkeypatch.setattr(api, "_calculate_quote_with_db_knobs", fail)
    c = TestClient(api.app, raise_server_exceptions=False)
    r = c.post("/quote", headers={"x-api-key": "synthetic-quote"}, json=quote_inputs())
    assert r.status_code == 500
    assert secret not in r.text and "RuntimeError" not in r.text
    assert r.json() == {"detail": "Service temporarily unavailable. Please try again."}
    assert "private-host" not in service_message(500, pricing=True)


def test_public_server_configuration_error_is_generic(monkeypatch):
    monkeypatch.setattr(api, "engine", None)
    monkeypatch.setattr(api, "SessionLocal", None)
    c = TestClient(api.app, raise_server_exceptions=False)
    r = c.get("/config/active")
    assert r.status_code == 500
    assert "DATABASE_URL" not in r.text
    for path in ["/docs", "/redoc", "/openapi.json"]:
        assert c.get(path).status_code == 404
    assert c.get("/debug/whoami").status_code in (401, 403)


def test_order_details_exclude_operational_metadata():
    payload = dict(
        material="304",
        quantity=2,
        handle_length_from_bore=10.5,
        artifact_sha256="secret-hash",
        internal_note="not-public",
        stripe_session_id="not-public",
        selected_part_context={"internal": "no"},
    )
    assert customer_product_details(payload) == {
        "Material": "304",
        "Quantity": 2,
        "Handle length from bore center (in.)": 10.5,
    }


@pytest.mark.parametrize("quantity,lead", [(1, 14), (2, 21)])
def test_cart_quote_pdf_preserves_ui_values(quantity, lead):
    # Exercise the actual PDF function without executing authenticated page IO.
    tree = ast.parse((ROOT / "pages/3_Quote_Cart.py").read_text())
    names = {"_make_pdf_quote", "_usd"}
    functions = [
        n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names
    ]
    ns = dict(
        io=io,
        os=os,
        datetime=datetime,
        timedelta=timedelta,
        Dict=Dict,
        Any=Any,
        List=List,
        st=SimpleNamespace(session_state=SimpleNamespace()),
        cart_pricing_config_version="version-current",
        new_quote_meta=lambda: dict(quote_id="Q-SYNTHETIC", created_at=datetime(2026,10,19,tzinfo=ZoneInfo("America/New_York"))),
        document_from_cart=__import__('quote_document').document_from_cart,
        render_quote_pdf=__import__('quote_document').render_quote_pdf,
    )
    exec(
        compile(ast.Module(body=functions, type_ignores=[]), "actual-cart-pdf", "exec"),
        ns,
    )
    inputs = {**quote_inputs(), "quantity": quantity, "ships_in_days": lead}
    # UI and PDF consume the same verified price response; no independent price formula.
    lines = [
        dict(inputs=inputs, unit_price=140.39, line_total=round(140.39 * quantity, 2))
    ]
    pdf = ns["_make_pdf_quote"](lines, customer={})
    text = "\n".join(p.extract_text() for p in PdfReader(io.BytesIO(pdf)).pages)
    assert "$140.39" in text and f"${140.39*quantity:,.2f}" in text
    assert f"{lead} calendar days (est.)" in text and "Quoted subtotal" in text
    assert (
        "Calculated at checkout, if applicable" in text
        and "Selected at checkout" in text
    )
    assert "Oct 19, 2026" in text and "Nov 18, 2026" in text
    normalized = " ".join(text.split())
    for specification in (
        "Material 304 Stainless Steel",
        "Thickness 0.125 in",
        "Plate outside diameter 3.000 in",
        "Bore diameter 1.000 in",
        "Bore tolerance ± 0.005 in",
        "Handle width 1.500 in",
        "Handle length from bore center 9.000 in",
        "Chamfer 0.062 in",
        "Handle marking “UPSTREAM”",
        f"TOTAL QUANTITY {quantity} plate" + ("s" if quantity > 1 else ""),
    ):
        assert specification in normalized
    assert "Rogue Machine LLC" in text and "400 Public Rd" in text
    assert "Yorkville, OH 43971" in text
    assert "Q-SYNTHETIC" in text
    assert all(term not in text.lower() for term in ["staging", "sandbox", "debug"])


def test_footer_runs_even_when_page_stops():
    from streamlit.testing.v1 import AppTest

    app = AppTest.from_string('''
from types import SimpleNamespace
import streamlit as st
import customer_navigation as nav
def stopped_page():
    st.write("Page before stop")
    st.stop()
    st.write("Unreachable")
original_page, original_navigation = st.Page, st.navigation
try:
    st.Page = lambda *a, **k: None
    st.navigation = lambda *a, **k: SimpleNamespace(url_path="My_Orders", run=stopped_page)
    nav.run_customer_app()
finally:
    st.Page, st.navigation = original_page, original_navigation
''').run()
    assert not app.exception
    values = [item.value for item in app.markdown]
    assert values[0] == "Page before stop"
    assert "<footer" in values[1] and "Privacy Policy" in values[1]
    assert "Unreachable" not in values
