import inspect
import math

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

import api_app


QUOTE_HEADERS = {"x-api-key": "test-quote-key"}


@pytest.fixture(autouse=True)
def configured_quote_api_key(monkeypatch):
    monkeypatch.setattr(api_app, "API_KEY", "test-quote-key")


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
        "chamfer_width": None,
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
    response = client.post("/quote", json=valid_payload(), headers=QUOTE_HEADERS)

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
    ["<script>alert(1)</script>", "MARK\nSECOND LINE"],
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


def test_default_active_config_exposes_owner_manufacturing_limits():
    active = api_app._default_knobs_config()

    assert active["max_paddle_dia_in"] == 48.0
    assert active["max_bore_dia_in"] == 19.0
    assert active["max_handle_label_chars"] == 40
    assert active["lead_time_enabled"] == {"7": False, "14": True, "21": True}
    assert active["default_lead_time_days"] == 14


def test_quote_normalization_does_not_invent_chamfer_width(monkeypatch):
    def fake_calculation(inputs):
        assert inputs.chamfer is True
        assert inputs.chamfer_width is None
        return {
            "unit_price": 100.0,
            "total_price": 200.0,
            "quantity": inputs.quantity,
            "pricing_config_version": "test",
        }

    monkeypatch.setattr(api_app, "_calculate_quote_with_db_knobs", fake_calculation)
    payload = valid_payload(chamfer=True)
    payload.pop("chamfer_width")
    response = TestClient(api_app.app).post(
        "/quote", json=payload, headers=QUOTE_HEADERS
    )

    assert response.status_code == 200
    assert response.json()["normalized_configuration"]["chamfer_width"] is None


def test_quote_preserves_customer_entered_chamfer_width(monkeypatch):
    def fake_calculation(inputs):
        assert inputs.chamfer is True
        assert inputs.chamfer_width == 0.062
        return {
            "unit_price": 100.0,
            "total_price": 200.0,
            "quantity": inputs.quantity,
            "pricing_config_version": "test",
        }

    monkeypatch.setattr(api_app, "_calculate_quote_with_db_knobs", fake_calculation)
    response = TestClient(api_app.app).post(
        "/quote",
        json=valid_payload(chamfer=True, chamfer_width=0.062),
        headers=QUOTE_HEADERS,
    )

    assert response.status_code == 200
    assert response.json()["normalized_configuration"]["chamfer_width"] == 0.062


def test_order_lifecycle_startup_migration_is_additive_and_idempotent():
    source = inspect.getsource(api_app.init_db).upper()

    assert "ADD COLUMN IF NOT EXISTS STATUS" in source
    assert "ADD COLUMN IF NOT EXISTS PAID_AT" in source
    assert "ADD COLUMN IF NOT EXISTS LAST_STRIPE_EVENT_ID" in source
    assert "CREATE INDEX IF NOT EXISTS IX_ORDERS_STATUS" in source
    assert "CREATE UNIQUE INDEX IF NOT EXISTS IX_ORDERS_LAST_STRIPE_EVENT_ID" in source
    assert "DROP TABLE" not in source
    assert "DROP COLUMN" not in source
    assert "ALTER COLUMN" not in source


def test_quote_api_key_fails_closed_when_server_key_is_missing(monkeypatch):
    monkeypatch.setattr(api_app, "API_KEY", "")

    response = TestClient(api_app.app).post("/quote", json=valid_payload())

    assert response.status_code == 401
    assert response.json()["detail"] == "Unauthorized"


def test_quote_api_key_accepts_valid_key_and_rejects_invalid_key(monkeypatch):
    comparisons = []
    real_compare_digest = api_app.secrets.compare_digest

    def observed_compare_digest(provided, expected):
        comparisons.append((provided, expected))
        return real_compare_digest(provided, expected)

    monkeypatch.setattr(api_app.secrets, "compare_digest", observed_compare_digest)

    api_app._require_api_key("test-quote-key")
    with pytest.raises(api_app.HTTPException) as exc_info:
        api_app._require_api_key("wrong-key")

    assert exc_info.value.status_code == 401
    assert comparisons == [
        (b"test-quote-key", b"test-quote-key"),
        (b"wrong-key", b"test-quote-key"),
    ]
