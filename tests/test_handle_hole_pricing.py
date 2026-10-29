"""OP-IMP-001: a fixed per-plate base operation, with existing pricing authority."""
import hashlib
import itertools
import json
from pathlib import Path

import pytest
import requests
import streamlit as st

import tuning_knobs as cfg
from pricing_calibration import MODEL_VERSION
from pricing_engine import QuoteInputs, calculate_quote
from test_checkout_workflow import install_idempotent_stripe
from test_pricing_configuration import client
from test_shipping_mass import OP19


def inputs(enabled=True, **changes):
    values = {**OP19, **changes, "handle_hole_enabled": enabled}
    if not enabled:
        values["handle_hole_diameter"] = values["handle_hole_center_from_handle_end"] = None
    return values


@pytest.mark.parametrize("days,multiplier", [(7,2.3),(14,1.6),(21,1.0)])
@pytest.mark.parametrize("qty,discount", [(1,1),(5,.97),(10,.95),(25,.92)])
def test_fixed_base_per_plate_before_lead_and_quantity(monkeypatch, days, multiplier, qty, discount):
    monkeypatch.setattr(cfg, "LEAD_TIME_MULTIPLIER", {7:2.3,14:1.6,21:1})
    off = calculate_quote(QuoteInputs(**inputs(False, quantity=qty, ships_in_days=days)))
    on = calculate_quote(QuoteInputs(**inputs(quantity=qty, ships_in_days=days)))
    assert off["manufacturing_cost_components"]["handle_hole"] == 0
    assert on["manufacturing_cost_components"]["handle_hole"] == 15.06
    assert on["manufacturing_subtotal_unrounded"]-off["manufacturing_subtotal_unrounded"] == pytest.approx(15.06)
    assert on["lead_time_multiplier"] == multiplier
    assert on["qty_discount_multiplier"] == discount
    expected_unit = round((off["manufacturing_subtotal_unrounded"]+15.06)*multiplier*discount,2)
    assert on["unit_price"] == expected_unit
    assert on["total_price"] == round(expected_unit*qty,2)
    assert sum(on["manufacturing_cost_components"].values()) == pytest.approx(on["manufacturing_subtotal_unrounded"])
    assert calculate_quote(QuoteInputs(**inputs(False, quantity=qty, ships_in_days=days))) == off


@pytest.mark.parametrize("diameter", [.25,.375,.625])
def test_charge_is_not_a_diameter_rate(diameter):
    q = calculate_quote(QuoteInputs(**inputs(handle_hole_diameter=diameter)))
    assert q["manufacturing_cost_components"]["handle_hole"] == 15.06
    assert q["unit_price"] == 709.45
    assert q["linear_inches"] == 49.6225
    assert q["laser_cost"] == 40.99


def regression_inputs():
    for material, thickness, diameter, qty, days, enabled in itertools.product(
        ("304","316","Carbon Steel"), (.125,.25,.375,.5), (.25,.375,.625),
        (1,5,10,25), (7,14,21), (False,True),
    ):
        yield inputs(enabled, material=material, thickness=thickness,
                     handle_hole_diameter=diameter, quantity=qty, ships_in_days=days)


def unaffected_digest(calculate=calculate_quote):
    results=[]
    for values in regression_inputs():
        q=calculate(QuoteInputs(**values))
        # Only these outputs are approved to change. Every other cost component,
        # multiplier, dimension, weight and shipping estimate must match exactly.
        for key in ("pricing_model_version","manufacturing_subtotal_unrounded",
                    "subtotal_pre_multiplier","unit_price_pre_qty_discount","unit_price","total_price"):
            q.pop(key)
        q["manufacturing_cost_components"].pop("handle_hole",None)
        results.append(q)
    return hashlib.sha256(json.dumps(results,sort_keys=True,allow_nan=False).encode()).hexdigest()


def test_all_other_costs_and_shipping_match_shipping_release_exactly(monkeypatch):
    monkeypatch.setattr(cfg, "LEAD_TIME_MULTIPLIER", {7:2.3,14:1.6,21:1})
    expected=json.loads((Path(__file__).parent/"fixtures/handle-hole-regression-baseline.json").read_text())
    assert len(list(regression_inputs())) == expected["cases"] == 864
    assert unaffected_digest() == expected["unaffected_sha256"]


@pytest.mark.parametrize("cart", [False,True])
def test_quote_checkout_prices_and_shipping_match_and_old_versions_cannot_pay(client, monkeypatch, cart):
    import api_app as api
    c,factory=client
    monkeypatch.setattr(api,"APP_ENV","test")
    monkeypatch.setattr(api,"APP_BASE_URL","https://synthetic.example.test")
    monkeypatch.setattr(api.stripe,"api_key","sk_test_synthetic")
    monkeypatch.setattr(api,"_decode_supabase_user_id_from_bearer",lambda _:"synthetic-owner")
    calls=install_idempotent_stripe(monkeypatch)
    items=[inputs(),inputs(False,quantity=5),inputs(quantity=10,material="316")] if cart else [inputs()]
    quotes=[c.post("/quote",headers={"x-api-key":"synthetic-quote"},json=x).json() for x in items]
    assert quotes[0]["unit_price"] == 709.45
    version=quotes[0]["pricing_config_version"]
    assert version.endswith(":"+MODEL_VERSION)
    body={"items":items} if cart else {"inputs":items[0]}
    body["pricing_config_version"]=version.removesuffix(MODEL_VERSION)+"diameter-allowances-2026-10-v2"
    path="/checkout/cart/create" if cart else "/checkout/create"
    headers={"authorization":"Bearer synthetic"}
    rejected=c.post(path,headers=headers,json=body)
    assert rejected.status_code == 409 and calls == []
    with factory() as db: assert db.query(api.Order).count() == 0
    body["pricing_config_version"]=version
    accepted=c.post(path,headers=headers,json=body)
    assert accepted.status_code == 200,accepted.text
    # Existing checkout represents the authoritative extended amount as one
    # Stripe line; retain that workflow rather than changing Stripe line shape.
    assert sum(line["price_data"]["unit_amount"]*line["quantity"] for line in calls[0]["line_items"]) == sum(round(q["total_price"]*100) for q in quotes)
    assert [r["shipping_rate_data"]["fixed_amount"]["amount"] for r in calls[0]["shipping_options"]] == [
        sum(q["shipping"][key] for q in quotes) for key in ("ups_ground_cents","ups_2day_cents","ups_nextday_cents")]
    with factory() as db: assert db.query(api.Order).count() == 1


def test_configurator_toggle_immediately_reprices_and_turning_off_restores_price(monkeypatch):
    from ui_harness import customer_page_test
    from test_landing_convergence import CONFIG,response
    st.cache_data.clear()
    monkeypatch.setenv("API_BASE","http://offline-handle-hole")
    monkeypatch.setenv("OPLATES_OWNER_ACCEPTANCE_MODE","true")
    monkeypatch.delenv("OPLATES_DRAWING_ASSISTED_ENABLED",raising=False)
    monkeypatch.setattr(requests,"get",lambda *a,**k:response(CONFIG))
    calls=[]
    def quote(url,**kw):
        assert url.endswith("/quote")
        result=calculate_quote(QuoteInputs(**kw["json"]))
        calls.append((kw["json"],result))
        return response({**result,"configuration_id":"synthetic-handle-hole","pricing_config_version":MODEL_VERSION})
    monkeypatch.setattr(requests,"post",quote)
    app=customer_page_test("pages/1_Quote.py",default_timeout=20).run()
    assert not app.exception
    before=calls[-1][1]
    app.button_group(key="quote_field_handle_hole_enabled").set_value(True).run()
    assert not app.exception
    payload,after=calls[-1]
    assert payload["handle_hole_enabled"] is True and payload["handle_hole_diameter"] == .375
    assert after["manufacturing_cost_components"]["handle_hole"] == 15.06
    assert after["manufacturing_subtotal_unrounded"]-before["manufacturing_subtotal_unrounded"] == pytest.approx(15.06)
    assert any(m.value == f"${after['unit_price']:,.2f}" for m in app.metric)
    app.button_group(key="quote_field_handle_hole_enabled").set_value(False).run()
    assert not app.exception
    assert calls[-1][1] == before


def test_quote_cart_shows_authoritative_mixed_hole_line_totals(monkeypatch):
    import auth
    from ui_harness import customer_page_test
    from test_drawing_phase1k import _jwt,Response
    monkeypatch.setenv("API_KEY","synthetic-quote")
    monkeypatch.setenv("API_BASE","http://offline-handle-hole")
    monkeypatch.setattr(auth,"API_BASE","http://offline-handle-hole")
    monkeypatch.setattr(requests,"get",lambda *a,**k:Response({"available":False,"mode":None}))
    calls=[]
    def quote(url,**kw):
        assert url.endswith("/quote")
        result=calculate_quote(QuoteInputs(**kw["json"]))
        calls.append(result)
        return Response({**result,"pricing_config_version":MODEL_VERSION,"configuration_id":"synthetic-handle-hole"})
    monkeypatch.setattr(requests,"post",quote)
    app=customer_page_test("pages/3_Quote_Cart.py",default_timeout=20)
    app.session_state["auth"]={"access_token":_jwt(),"refresh_token":None,"user":None,"email":"synthetic@example.test"}
    app.session_state["cart"]=[{"line_id":"on","inputs":inputs()}, {"line_id":"off","inputs":inputs(False,quantity=5)}]
    app.run()
    assert not app.exception
    assert len(calls) == 2
    subtotal=sum(q["total_price"] for q in calls)
    assert next(m for m in app.metric if m.label=="Cart Subtotal").value == f"${subtotal:,.2f}"
    assert [q["manufacturing_cost_components"]["handle_hole"] for q in calls] == [15.06,0]
