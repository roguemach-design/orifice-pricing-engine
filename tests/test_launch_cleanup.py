import ast
import io
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
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
        SUPPLIER_LOGOS=[],
        QUOTE_VALID_DAYS=30,
        SUPPLIER=dict(
            name="Rogue Machine LLC",
            addr1="736 Stone and Shannon Rd",
            city_state_zip="Wheeling WV 26003",
            country="United States",
            phone="+1 304-639-0595",
        ),
        _ensure_quote_meta=lambda: dict(
            quote_id="Q-SYNTHETIC",
            created_at=datetime(2026, 10, 19, tzinfo=timezone.utc),
        ),
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
    assert f"ships={lead}d" in text and "Subtotal:" in text
    assert (
        "Prices shown exclude tax" in text
        and "Shipping is selected at checkout" in text
    )
    assert "Valid until: 2026-11-18" in text
    assert all(term not in text.lower() for term in ["staging", "sandbox", "debug"])


def test_footer_runs_even_when_page_stops(monkeypatch):
    import customer_navigation as nav

    class StopPage(BaseException):
        pass

    def stop():
        raise StopPage()

    monkeypatch.setattr(nav.st, "set_page_config", lambda **k: None)
    monkeypatch.setattr(nav.st, "Page", lambda *a, **k: None)
    monkeypatch.setattr(
        nav.st,
        "navigation",
        lambda *a, **k: SimpleNamespace(url_path="My_Orders", run=stop),
    )
    calls = []
    monkeypatch.setattr(nav, "render_customer_footer", lambda: calls.append("footer"))
    with pytest.raises(StopPage):
        nav.run_customer_app()
    assert calls == ["footer"]
