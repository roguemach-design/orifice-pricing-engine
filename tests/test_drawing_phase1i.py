"""Owner-test pricing convergence without another pricing implementation."""

import base64
import json
from pathlib import Path
from unittest.mock import patch

import pytest
import requests
from fastapi.testclient import TestClient
from streamlit.testing.v1 import AppTest

import api_app
import auth
from drawing_intake.assisted_quote import (
    AssistedQuoteSession,
    CanonicalFieldValue,
    ConfigurationValueOrigin,
    availability_from_active_config,
    confirm_configuration,
    review_assisted_quote,
    set_customer_value,
)
from drawing_intake.classification import DrawingDocumentClass
from drawing_intake.pricing_gate import confirmed_drawing_quote_inputs
from pricing_engine import QuoteInputs, calculate_quote


@pytest.fixture
def availability():
    return availability_from_active_config(
        {
            "materials": ["304"],
            "thicknesses_by_material": {"304": [0.125, 0.25]},
            "lead_times_days": [14, 21],
            "tolerance_options_in": [0.001, 0.002, 0.005],
            "max_paddle_dia_in": 48.0,
            "max_bore_dia_in": 19.0,
            "max_handle_label_chars": 40,
        }
    )


def _payload(od=5.0, bore=1.548, thickness=0.125):
    return {
        "quantity": 1,
        "material": "304",
        "thickness": thickness,
        "handle_width": 2.0,
        "handle_length_from_bore": 10.5,
        "paddle_dia": od,
        "bore_dia": bore,
        "bore_tolerance": 0.005,
        "chamfer": True,
        "chamfer_width": 0.0625,
        "handle_label": "No label",
        "ships_in_days": 14,
    }


def _session(
    payload,
    *,
    fields=None,
    kind=DrawingDocumentClass.SINGLE_PLATE_DRAWING,
    count=1,
    selected="plate-1",
    selection_required=False,
):
    fields = fields if fields is not None else payload.keys()
    return AssistedQuoteSession(
        source_document="synthetic-owner-test.pdf",
        source_sha256="1" * 64,
        document_class=kind,
        candidate_count=count,
        selected_candidate_id=selected,
        selection_required=selection_required,
        configuration={
            name: CanonicalFieldValue(
                value=payload[name], origin=ConfigurationValueOrigin.DRAWING
            )
            for name in fields
            if payload[name] is not None
        },
    )


def _complete(session, payload):
    for name, value in payload.items():
        if name not in session.configuration and value is not None:
            session = set_customer_value(session, name, value)
    return session


def _api_quote(monkeypatch, payload):
    monkeypatch.setattr(api_app, "API_KEY", "test-quote-key")
    monkeypatch.setattr(
        api_app,
        "_calculate_quote_with_db_knobs",
        lambda inputs: {**calculate_quote(inputs), "pricing_config_version": "test"},
    )
    response = TestClient(api_app.app).post(
        "/quote", json=payload, headers={"x-api-key": "test-quote-key"}
    )
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.parametrize(
    "payload,recognized",
    [
        (
            _payload(),
            {
                "paddle_dia",
                "bore_dia",
                "thickness",
                "material",
                "quantity",
                "bore_tolerance",
                "handle_width",
                "handle_length_from_bore",
            },
        ),
        (
            _payload(od=10.0, bore=3.75, thickness=0.25),
            {"paddle_dia", "bore_dia", "thickness", "material", "bore_tolerance"},
        ),
    ],
    ids=["SYN-W1-01", "SYN-W1-06-partial"],
)
def test_manual_and_confirmed_drawing_use_identical_api_payload_and_price(
    monkeypatch, availability, payload, recognized
):
    session = _session(payload, fields=recognized)
    with pytest.raises(ValueError, match="confirmed"):
        confirmed_drawing_quote_inputs(session, payload, availability=availability)
    session = confirm_configuration(
        _complete(session, payload), availability=availability
    )
    drawing_payload = confirmed_drawing_quote_inputs(
        session, payload, availability=availability
    )
    manual_payload = QuoteInputs(**payload).model_dump()
    assert drawing_payload == manual_payload
    assert set(drawing_payload) == set(QuoteInputs.model_fields)
    assert not any("source" in name or "confidence" in name for name in drawing_payload)
    manual_result = _api_quote(monkeypatch, manual_payload)
    drawing_result = _api_quote(monkeypatch, drawing_payload)
    assert (
        manual_result["normalized_configuration"]
        == drawing_result["normalized_configuration"]
    )
    # A quote reference and timestamp are unique per request; all substantive
    # pricing, validation, shipping, and normalized input fields must agree.
    request_specific = {"configuration_id", "calculated_at"}
    assert {
        key: value
        for key, value in manual_result.items()
        if key not in request_specific
    } == {
        key: value
        for key, value in drawing_result.items()
        if key not in request_specific
    }


def test_customer_correction_is_authoritative_and_reconfirmation_reprices(
    monkeypatch, availability
):
    original = _payload(od=10.0, bore=3.75, thickness=0.25)
    session = _session(
        original,
        fields={"paddle_dia", "bore_dia", "thickness", "material", "bore_tolerance"},
    )
    session = confirm_configuration(
        _complete(session, original), availability=availability
    )
    old = _api_quote(
        monkeypatch,
        confirmed_drawing_quote_inputs(session, original, availability=availability),
    )
    corrected = {**original, "paddle_dia": 10.25}
    session = set_customer_value(session, "paddle_dia", 10.25)
    assert not review_assisted_quote(
        session, availability=availability
    ).confirmation_current
    with pytest.raises(ValueError, match="confirmed"):
        confirmed_drawing_quote_inputs(session, corrected, availability=availability)
    session = confirm_configuration(session, availability=availability)
    priced_payload = confirmed_drawing_quote_inputs(
        session, corrected, availability=availability
    )
    assert priced_payload["paddle_dia"] == 10.25
    assert priced_payload["handle_length_from_bore"] == 10.5
    new = _api_quote(monkeypatch, priced_payload)
    assert new["normalized_configuration"]["paddle_dia"] == 10.25
    assert new["total_price"] != old["total_price"]
    with pytest.raises(ValueError, match="differs"):
        confirmed_drawing_quote_inputs(session, original, availability=availability)


@pytest.mark.parametrize(
    "field,value",
    [
        ("quantity", 2),
        ("material", "316"),
        ("thickness", 0.25),
        ("paddle_dia", 5.25),
        ("bore_dia", 1.6),
        ("bore_tolerance", 0.002),
        ("handle_width", 1.5),
        ("handle_length_from_bore", 11.0),
        ("chamfer", False),
        ("chamfer_width", 0.125),
        ("handle_label", "UPSTREAM"),
        ("ships_in_days", 21),
    ],
)
def test_every_pricing_relevant_edit_invalidates_confirmation(
    availability, field, value
):
    payload = _payload()
    session = confirm_configuration(_session(payload), availability=availability)
    changed = set_customer_value(session, field, value)
    assert not review_assisted_quote(
        changed, availability=availability
    ).confirmation_current
    with pytest.raises(ValueError):
        confirmed_drawing_quote_inputs(
            changed, {**payload, field: value}, availability=availability
        )


def test_incomplete_invalid_and_unsupported_tolerance_cannot_price(availability):
    payload = _payload(od=10.0, bore=3.75, thickness=0.25)
    partial = _session(
        payload, fields={"paddle_dia", "bore_dia", "thickness", "material"}
    )
    with pytest.raises(ValueError):
        confirm_configuration(partial, availability=availability)
    with pytest.raises(ValueError):
        confirmed_drawing_quote_inputs(partial, payload, availability=availability)
    for name in ("quantity", "ships_in_days", "bore_tolerance"):
        missing = _complete(partial, payload)
        missing = set_customer_value(missing, name, None)
        assert (
            name
            in review_assisted_quote(
                missing, availability=availability
            ).missing_required_fields
        )
        with pytest.raises(ValueError):
            confirmed_drawing_quote_inputs(missing, payload, availability=availability)
    invalid = _complete(partial, payload)
    invalid = set_customer_value(invalid, "bore_dia", 11.0)
    assert (
        "bore_dia"
        in review_assisted_quote(invalid, availability=availability).invalid_fields
    )
    with pytest.raises(ValueError):
        confirm_configuration(invalid, availability=availability)
    for field, value in (
        ("material", "Unsupported Alloy"),
        ("thickness", 0.375),
        ("ships_in_days", 7),
    ):
        invalid = set_customer_value(_complete(partial, payload), field, value)
        assert (
            field
            in review_assisted_quote(invalid, availability=availability).invalid_fields
        )
        with pytest.raises(ValueError):
            confirmed_drawing_quote_inputs(invalid, payload, availability=availability)


def test_reference_and_unselected_multi_plate_never_price(availability):
    payload = _payload()
    reference = _session(
        payload,
        kind=DrawingDocumentClass.REFERENCE_VENDOR_DATASHEET,
        count=0,
        selected=None,
    )
    with pytest.raises(ValueError, match="quote-specific"):
        confirmed_drawing_quote_inputs(reference, payload, availability=availability)
    multi = _session(
        payload,
        kind=DrawingDocumentClass.MULTI_PLATE_DRAWING,
        count=8,
        selected=None,
        selection_required=True,
    )
    with pytest.raises(ValueError, match="quote-specific"):
        confirmed_drawing_quote_inputs(multi, payload, availability=availability)
    selected = multi.model_copy(
        update={"selected_candidate_id": "region-3", "selection_required": False}
    )
    selected = confirm_configuration(selected, availability=availability)
    assert (
        confirmed_drawing_quote_inputs(selected, payload, availability=availability)
        == payload
    )


class _Response:
    status_code = 200

    def __init__(self, body, status_code=200):
        self.body = body
        self.status_code = status_code

    def json(self):
        return self.body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(str(self.status_code))


def _jwt():
    def encode(body):
        return base64.urlsafe_b64encode(json.dumps(body).encode()).decode().rstrip("=")

    return f"{encode({'alg': 'RS256'})}.{encode({'sub': 'internal-user', 'exp': 4102444800})}.signature"


@pytest.mark.parametrize("failure", ["timeout", "validation", "unavailable"])
def test_pricing_api_failure_preserves_confirmed_form_and_hides_price(
    monkeypatch, availability, failure
):
    payload = _payload()
    session = confirm_configuration(_session(payload), availability=availability)
    monkeypatch.setenv("API_BASE", "http://test")
    monkeypatch.setenv("OPLATES_DRAWING_ASSISTED_ENABLED", "true")
    monkeypatch.setenv("OPLATES_OWNER_ACCEPTANCE_MODE", "true")
    monkeypatch.setattr(auth, "API_BASE", "http://test")
    active = {
        "materials": ["304"],
        "thicknesses_by_material": {"304": [0.125, 0.25]},
        "lead_times_days": [14, 21],
        "default_lead_time_days": 14,
        "tolerance_options_in": [0.001, 0.002, 0.005],
        "max_paddle_dia_in": 48.0,
        "max_bore_dia_in": 19.0,
        "max_handle_label_chars": 40,
    }
    seen = []

    def fake_get(url, **kwargs):
        return _Response(
            active
            if url.endswith("/config/active")
            else {"enabled": True, "authorized": True, "user_id": "internal-user"}
        )

    def fake_post(url, **kwargs):
        seen.append(kwargs["json"])
        if failure == "timeout":
            raise requests.Timeout()
        return _Response(
            {"detail": "The pricing service rejected the configuration."},
            status_code=422 if failure == "validation" else 503,
        )

    with patch("requests.get", fake_get), patch("requests.post", fake_post):
        app = AppTest.from_file(
            str(Path(__file__).resolve().parents[1] / "pages" / "1_Quote.py"),
            default_timeout=20,
        )
        app.session_state["auth"] = {
            "access_token": _jwt(),
            "refresh_token": None,
            "user": None,
            "email": "internal@example.com",
        }
        for field, value in payload.items():
            app.session_state[f"quote_field_{field}"] = value
        app.session_state["phase1g_form_origins"] = {
            name: "customer" for name in payload
        }
        app.session_state["phase1g_form_snapshot"] = payload.copy()
        app.session_state["phase1g_assisted_session"] = session
        app.session_state["phase1g_customer_confirmation"] = True
        app.run()

    assert not app.exception
    assert seen == [payload]
    assert app.session_state["quote_field_paddle_dia"] == 5.0
    assert app.session_state["phase1g_customer_confirmation"] is True
    assert not any(item.label == "Unit price" for item in app.metric)
    assert next(
        button for button in app.button if button.label == "Continue to secure checkout"
    ).disabled
    assert any(
        "temporarily unavailable" in item.value or "rejected" in item.value
        for item in app.error
    )


@pytest.mark.parametrize("owner_mode,authorized", [(True, False), (False, True)])
def test_owner_scope_blocks_stale_assisted_session_pricing(
    monkeypatch, availability, owner_mode, authorized
):
    payload = _payload()
    session = confirm_configuration(_session(payload), availability=availability)
    monkeypatch.setenv("API_BASE", "http://test")
    monkeypatch.setenv("OPLATES_DRAWING_ASSISTED_ENABLED", "true")
    monkeypatch.setenv("OPLATES_OWNER_ACCEPTANCE_MODE", str(owner_mode).lower())
    monkeypatch.setattr(auth, "API_BASE", "http://test")
    active = {
        "materials": ["304"],
        "thicknesses_by_material": {"304": [0.125, 0.25]},
        "lead_times_days": [14, 21],
        "default_lead_time_days": 14,
        "tolerance_options_in": [0.001, 0.002, 0.005],
        "max_paddle_dia_in": 48.0,
        "max_bore_dia_in": 19.0,
        "max_handle_label_chars": 40,
    }
    with patch(
        "requests.get",
        side_effect=lambda url, **kw: _Response(
            active
            if url.endswith("/config/active")
            else {"enabled": True, "authorized": authorized, "user_id": "internal-user"}
        ),
    ), patch("requests.post") as post:
        app = AppTest.from_file(
            str(Path(__file__).resolve().parents[1] / "pages" / "1_Quote.py"),
            default_timeout=20,
        )
        app.session_state["auth"] = {
            "access_token": _jwt(),
            "refresh_token": None,
            "user": None,
            "email": "internal@example.com",
        }
        for field, value in payload.items():
            app.session_state[f"quote_field_{field}"] = value
        app.session_state["phase1g_form_origins"] = {
            name: "customer" for name in payload
        }
        app.session_state["phase1g_form_snapshot"] = payload.copy()
        app.session_state["phase1g_assisted_session"] = session
        app.session_state["phase1g_customer_confirmation"] = True
        app.run()
        post.assert_not_called()
    assert not app.exception
    assert not any(item.label == "Unit price" for item in app.metric)
