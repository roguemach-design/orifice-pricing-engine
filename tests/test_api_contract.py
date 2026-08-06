import math

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

import api_app


def valid_payload(**overrides):
    payload = {
        "quantity": 2,
        "material": "304",
        "thickness": 0.125,
        "handle_width": 1.5,
        "handle_length_from_bore": 9.0,
        "paddle_dia": 3.0,
        "bore_dia": 1.0,
        "bore_tolerance": 0.005,
        "chamfer": True,
        "chamfer_width": 0.062,
        "handle_label": "UPSTREAM 1.000 BORE",
        "ships_in_days": 14,
    }
    payload.update(overrides)
    return payload


def test_quote_contract_contains_authority_metadata(monkeypatch):
    def fake_calculation(inputs):
        return {
            "unit_price": 100.25,
            "total_price": 200.50,
            "quantity": inputs.quantity,
            "shipping": {"ups_ground_cents": 1500},
            "pricing_config_version": "2026-08-06T12:00:00+00:00",
        }

    monkeypatch.setattr(api_app, "_calculate_quote_with_db_knobs", fake_calculation)
    client = TestClient(api_app.app)
    response = client.post("/quote", json=valid_payload())

    assert response.status_code == 200
    body = response.json()
    assert body["validation"] == {"valid": True, "errors": []}
    assert body["currency"] == "USD"
    assert body["configuration_schema_version"] == "1.0"
    assert body["pricing_config_version"] == "2026-08-06T12:00:00+00:00"
    assert body["revalidate_at_checkout"] is True
    assert body["normalized_configuration"]["quantity"] == 2
    assert body["total_price"] == body["unit_price"] * 2
    assert body["configuration_id"]


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
def test_quote_request_rejects_non_finite_numbers(value):
    with pytest.raises(ValidationError):
        api_app.QuoteRequest(**valid_payload(bore_dia=value))


@pytest.mark.parametrize(
    "label",
    ["<script>alert(1)</script>", "A" * 81, "MARK\nSECOND LINE"],
)
def test_quote_request_rejects_unsafe_handle_marking(label):
    with pytest.raises(ValidationError):
        api_app.QuoteRequest(**valid_payload(handle_label=label))


def test_active_config_disables_unavailable_lead_time():
    active = api_app._default_knobs_config()
    active["lead_time_enabled"] = {"7": False, "14": True, "21": True}

    with api_app._CFG_LOCK:
        api_app._restore_cfg_baseline()
        api_app._apply_cfg_from_db_config(active)
        try:
            assert 7 not in api_app.cfg.LEAD_TIME_MULTIPLIER
            assert sorted(api_app.cfg.LEAD_TIME_MULTIPLIER) == [14, 21]
        finally:
            api_app._restore_cfg_baseline()
