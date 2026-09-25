import base64
import io
import json
import time
from pathlib import Path
from unittest.mock import patch

import pytest
import requests
from fastapi.testclient import TestClient
from PIL import Image
from reportlab.pdfgen import canvas

import api_app
import auth
import drawing_intake.configurator_integration as integration
from drawing_intake.assisted_intake import (
    AssistedCandidateKind,
    AssistedCandidateOption,
    AssistedDocumentReview,
    ProcessedAssistedUpload,
    inspect_assisted_upload,
)
from drawing_intake.assisted_quote import (
    AssistedQuoteStatus,
    ConfigurationValueOrigin,
    availability_from_active_config,
    build_assisted_quote_session,
    confirm_configuration,
    review_assisted_quote,
    set_customer_value,
)
from drawing_intake.classification import DrawingDocumentClass
from drawing_intake.confirmation_contract import (
    ConfirmationFieldProposal,
    ConfirmationWorkflowStatus,
    CustomerConfirmationContract,
)
from drawing_intake.deterministic import EvidenceClassification
from drawing_intake.documents import normalize_document
from drawing_intake.models import (
    CoordinateUnit,
    FieldStatus,
    MeasurementUnit,
)
from drawing_intake.configurator_integration import (
    DrawingProcessingTimeoutError,
    DrawingUploadLimits,
    DrawingUploadValidationError,
    FormValueOrigin,
    accept_pricing_boundary_without_invocation,
    feature_flag_enabled,
    integrate_selected_session,
    internal_user_is_allowed,
    parse_allowed_user_ids,
    synchronize_session_from_form,
    validate_drawing_upload,
)

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def active_config():
    return {
        "material_enabled": {"304": True, "316": True, "Carbon Steel": True},
        "thickness_enabled_by_material": {
            "304": {"0.125": True, "0.25": True},
            "316": {"0.125": True},
            "Carbon Steel": {"0.125": True},
        },
        "lead_time_enabled": {"14": True, "21": True},
        "default_lead_time_days": 14,
        "materials": ["304", "316", "Carbon Steel"],
        "thicknesses_by_material": {
            "304": [0.125, 0.25],
            "316": [0.125],
            "Carbon Steel": [0.125],
        },
        "lead_times_days": [14, 21],
        "tolerance_options_in": [0.001, 0.002, 0.005],
        "max_paddle_dia_in": 48.0,
        "max_bore_dia_in": 19.0,
        "max_handle_label_chars": 40,
        "configuration_schema_version": "1.0",
    }


@pytest.fixture
def availability(active_config):
    return availability_from_active_config(active_config)


def _proposal(
    extraction_field,
    canonical_field,
    value,
    *,
    unit=None,
    status=FieldStatus.DETECTED,
    unsupported=False,
    raw=None,
):
    return ConfirmationFieldProposal(
        extraction_field=extraction_field,
        canonical_field=canonical_field,
        proposed_value=value,
        normalized_unit=unit,
        raw_text=raw or (str(value) if value is not None else None),
        source_document="internal-test.pdf",
        source_sha256="1" * 64,
        source_page=1,
        source_bbox=(10.0, 20.0, 30.0, 40.0),
        source_coordinate_unit=CoordinateUnit.PDF_POINT,
        evidence_status=(
            EvidenceClassification.AMBIGUOUS
            if status == FieldStatus.AMBIGUOUS
            else EvidenceClassification.REQUIRES_CONFIRMATION
        ),
        validation_status=status,
        confirmation_required=value is not None,
        unsupported=unsupported,
    )


def _contract(*proposals, selected="plate-1", source_sha="1" * 64):
    return CustomerConfirmationContract(
        source_document="internal-test.pdf",
        source_sha256=source_sha,
        document_class=DrawingDocumentClass.SINGLE_PLATE_DRAWING,
        candidate_count=1,
        selected_candidate_id=selected,
        selection_required=False,
        proposals=list(proposals),
        status=ConfirmationWorkflowStatus.REQUIRES_CONFIRMATION,
    )


def _standard_session(availability, *, od=8.0, bore=2.0, source_sha="1" * 64):
    contract = _contract(
        _proposal("outside_diameter", "paddle_dia", od, unit=MeasurementUnit.INCH),
        _proposal("bore_diameter", "bore_dia", bore, unit=MeasurementUnit.INCH),
        _proposal("thickness", "thickness", 0.125, unit=MeasurementUnit.INCH),
        _proposal("material", "material", "304"),
        _proposal("quantity", "quantity", 1, unit=MeasurementUnit.COUNT),
        _proposal(
            "bore_tolerance_plus",
            "bore_tolerance",
            0.005,
            unit=MeasurementUnit.INCH,
        ),
        _proposal(
            "bore_tolerance_minus",
            "bore_tolerance",
            0.005,
            unit=MeasurementUnit.INCH,
        ),
        _proposal("chamfer_present", "chamfer", False),
        source_sha=source_sha,
    )
    return build_assisted_quote_session(contract, availability=availability)


def _complete(session, availability):
    values = {
        "quantity": 1,
        "material": "304",
        "thickness": 0.125,
        "handle_width": 1.5,
        "handle_length_from_bore": 9.0,
        "paddle_dia": 8.0,
        "bore_dia": 2.0,
        "bore_tolerance": 0.005,
        "chamfer": False,
        "ships_in_days": 14,
        "handle_label": "No label",
    }
    for field, value in values.items():
        if field not in session.configuration:
            session = set_customer_value(session, field, value)
    assert not review_assisted_quote(
        session, availability=availability
    ).missing_required_fields
    return session


def _manual_defaults():
    return {
        "quantity": 1,
        "material": "304",
        "thickness": 0.125,
        "handle_width": 1.5,
        "handle_length_from_bore": 9.0,
        "paddle_dia": 3.0,
        "bore_dia": 1.0,
        "bore_tolerance": 0.005,
        "chamfer": False,
        "ships_in_days": 14,
        "handle_label": "",
        "chamfer_width": None,
    }


def _png(width=120, height=80):
    output = io.BytesIO()
    Image.new("RGB", (width, height), "white").save(output, format="PNG")
    return output.getvalue()


def _pdf(page_count=1):
    output = io.BytesIO()
    drawing = canvas.Canvas(output, pagesize=(612, 792))
    for page in range(page_count):
        drawing.drawString(72, 720, f"Synthetic O-Plate regression page {page + 1}")
        drawing.showPage()
    drawing.save()
    return output.getvalue()


def _jwt(subject="internal-user"):
    def encode(value):
        return base64.urlsafe_b64encode(json.dumps(value).encode()).decode().rstrip("=")

    return f"{encode({'alg': 'RS256'})}.{encode({'sub': subject, 'exp': 4102444800})}.signature"


class _Response:
    def __init__(self, data, status_code=200):
        self._data = data
        self.status_code = status_code

    def json(self):
        return self._data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(str(self.status_code))


def test_feature_is_disabled_by_default_and_allowlist_fails_closed():
    assert not feature_flag_enabled(None)
    assert not feature_flag_enabled("false")
    assert feature_flag_enabled("TRUE")
    assert parse_allowed_user_ids("") == frozenset()
    assert not internal_user_is_allowed(
        enabled=True, user_id="u1", allowed_user_ids=frozenset()
    )
    assert internal_user_is_allowed(
        enabled=True,
        user_id="u1",
        allowed_user_ids=parse_allowed_user_ids("u1, u2"),
    )


def test_api_internal_access_is_disabled_with_404(monkeypatch):
    monkeypatch.delenv("OPLATES_DRAWING_ASSISTED_ENABLED", raising=False)
    response = TestClient(api_app.app).get("/internal/drawing-intake/access")
    assert response.status_code == 404


@pytest.mark.parametrize(
    ("decoded_user", "allowed", "expected"),
    [
        (None, "internal-user", 401),
        ("ordinary-user", "internal-user", 403),
        ("internal-user", "", 403),
    ],
)
def test_api_internal_access_enforces_verified_identity_and_allowlist(
    monkeypatch, decoded_user, allowed, expected
):
    monkeypatch.setenv("OPLATES_DRAWING_ASSISTED_ENABLED", "true")
    monkeypatch.setenv("OPLATES_DRAWING_ASSISTED_ALLOWED_USER_IDS", allowed)
    monkeypatch.setattr(
        api_app, "_decode_supabase_user_id_from_bearer", lambda value: decoded_user
    )
    api_app._RATE_LIMITER.clear()

    response = TestClient(api_app.app).get(
        "/internal/drawing-intake/access",
        headers={"authorization": "Bearer test"},
    )
    assert response.status_code == expected


def test_api_internal_access_accepts_only_allowlisted_verified_user(monkeypatch):
    monkeypatch.setenv("OPLATES_DRAWING_ASSISTED_ENABLED", "true")
    monkeypatch.setenv("OPLATES_DRAWING_ASSISTED_ALLOWED_USER_IDS", "internal-user")
    monkeypatch.setattr(
        api_app,
        "_decode_supabase_user_id_from_bearer",
        lambda value: "internal-user",
    )
    api_app._RATE_LIMITER.clear()

    response = TestClient(api_app.app).get(
        "/internal/drawing-intake/access",
        headers={"authorization": "Bearer test"},
    )
    assert response.status_code == 200
    assert response.json() == {
        "enabled": True,
        "authorized": True,
        "user_id": "internal-user",
    }


def test_upload_validation_accepts_real_content_and_sanitizes_filename():
    validated = validate_drawing_upload(_png(), "C:\\fakepath\\plate.png", "image/png")
    assert validated.filename == "plate.png"
    assert validated.media_type == "image/png"
    assert validated.page_count == 1
    assert len(validated.sha256) == 64


@pytest.mark.parametrize(
    ("data", "filename", "media_type"),
    [
        (b"not a drawing", "plate.pdf", "application/pdf"),
        (_png(), "plate.pdf", "application/pdf"),
        (_png(), "plate.png", "application/pdf"),
        (_png(), "plate.svg", "image/png"),
    ],
)
def test_upload_validation_rejects_type_mismatch(data, filename, media_type):
    with pytest.raises(DrawingUploadValidationError):
        validate_drawing_upload(data, filename, media_type)


def test_upload_validation_enforces_size_page_and_pixel_limits():
    with pytest.raises(DrawingUploadValidationError, match="limited"):
        validate_drawing_upload(
            b"\x89PNG\r\n\x1a\n" + b"x" * 2048,
            "plate.png",
            "image/png",
            limits=DrawingUploadLimits(max_file_bytes=1024),
        )
    with pytest.raises(DrawingUploadValidationError, match="pages"):
        validate_drawing_upload(
            _pdf(3),
            "plate.pdf",
            "application/pdf",
            limits=DrawingUploadLimits(max_pdf_pages=2),
        )
    with pytest.raises(DrawingUploadValidationError, match="dimensions"):
        validate_drawing_upload(
            _png(2000, 10),
            "plate.png",
            "image/png",
            limits=DrawingUploadLimits(max_image_dimension_px=1000),
        )


def _sleeping_worker(connection, operation, arguments):
    time.sleep(5)


def test_processing_timeout_terminates_bounded_worker(monkeypatch):
    monkeypatch.setattr(integration, "_processing_worker", _sleeping_worker)
    started = time.monotonic()
    with pytest.raises(DrawingProcessingTimeoutError):
        integration._run_with_timeout("inspect", tuple(), timeout_seconds=1)
    assert time.monotonic() - started < 4


def test_local_recognition_adapter_keeps_upload_in_memory():
    source = ROOT / "drawing_corpus" / "synthetic" / "clean_digital.pdf"
    validated = validate_drawing_upload(
        source.read_bytes(), source.name, "application/pdf"
    )
    processed = integration.inspect_validated_upload(validated, timeout_seconds=30)

    assert processed.document.sha256 == validated.sha256
    assert not processed.review.external_service_used
    assert not processed.review.persistent_storage_used


def test_active_config_schema_is_real_and_fails_on_missing_options(active_config):
    product = availability_from_active_config(active_config)
    assert product.materials == active_config["materials"]
    assert product.thicknesses_by_material["304"] == [0.125, 0.25]
    assert product.lead_times_days == [14, 21]

    invalid = dict(active_config)
    invalid["tolerance_options_in"] = []
    with pytest.raises(ValueError, match="tolerance"):
        availability_from_active_config(invalid)


def test_active_config_controls_drawing_mapping_not_local_defaults(active_config):
    restricted = dict(active_config)
    restricted["materials"] = ["316"]
    restricted["thicknesses_by_material"] = {"316": [0.125]}
    product = availability_from_active_config(restricted)
    session = _standard_session(product)
    assert "material" not in session.configuration
    assert session.configuration["thickness"].value == 0.125


def test_existing_customer_values_survive_upload_and_conflicts_are_visible(
    availability,
):
    drawing = _standard_session(availability, od=8.0)
    values = _manual_defaults()
    values["paddle_dia"] = 8.25
    origins = {field: FormValueOrigin.DEFAULT for field in values}
    origins["paddle_dia"] = FormValueOrigin.CUSTOMER

    merged = integrate_selected_session(
        drawing,
        current_values=values,
        current_origins=origins,
        availability=availability,
    )

    assert merged.values["paddle_dia"] == 8.25
    assert merged.origins["paddle_dia"] == FormValueOrigin.CUSTOMER
    assert (
        merged.session.configuration["paddle_dia"].origin
        == ConfigurationValueOrigin.CUSTOMER
    )
    assert merged.conflicts[0].drawing_value == 8.0
    assert merged.conflicts[0].customer_value == 8.25


def test_unreadable_fields_clear_defaults_and_dynamic_checklist_updates(availability):
    drawing = _standard_session(availability)
    merged = integrate_selected_session(
        drawing,
        current_values=_manual_defaults(),
        current_origins={
            field: FormValueOrigin.DEFAULT for field in _manual_defaults()
        },
        availability=availability,
    )
    review = review_assisted_quote(merged.session, availability=availability)
    assert set(review.missing_required_fields) == {
        "handle_width",
        "handle_length_from_bore",
        "ships_in_days",
    }

    updated = set_customer_value(merged.session, "handle_width", 1.5)
    assert (
        "handle_width"
        not in review_assisted_quote(
            updated, availability=availability
        ).missing_required_fields
    )
    cleared = set_customer_value(updated, "handle_width", None)
    assert (
        "handle_width"
        in review_assisted_quote(
            cleared, availability=availability
        ).missing_required_fields
    )


def test_dynamic_checklist_tracks_conditional_chamfer_width(availability):
    session = _complete(_standard_session(availability), availability)
    assert (
        "chamfer_width"
        not in review_assisted_quote(
            session, availability=availability
        ).missing_required_fields
    )

    enabled = set_customer_value(session, "chamfer", True)
    assert (
        "chamfer_width"
        in review_assisted_quote(
            enabled, availability=availability
        ).missing_required_fields
    )

    completed = set_customer_value(enabled, "chamfer_width", 0.062)
    assert (
        "chamfer_width"
        not in review_assisted_quote(
            completed, availability=availability
        ).missing_required_fields
    )


def test_customer_correction_survives_reanalysis_and_new_source(availability):
    original = _standard_session(availability, bore=2.0)
    merged = integrate_selected_session(
        original,
        current_values=_manual_defaults(),
        current_origins={
            field: FormValueOrigin.DEFAULT for field in _manual_defaults()
        },
        availability=availability,
    )
    corrected_values = dict(merged.values)
    corrected_values["bore_dia"] = 2.125
    synchronized = synchronize_session_from_form(
        merged.session,
        previous_values=merged.values,
        current_values=corrected_values,
        current_origins=merged.origins,
    )

    rerun = _standard_session(availability, bore=2.25, source_sha="2" * 64)
    reapplied = integrate_selected_session(
        rerun,
        current_values=synchronized.values,
        current_origins=synchronized.origins,
        availability=availability,
    )
    assert reapplied.values["bore_dia"] == 2.125
    assert reapplied.conflicts[0].drawing_value == 2.25


def test_confirmation_follows_current_form_and_invalidates_on_edit(availability):
    session = confirm_configuration(
        _complete(_standard_session(availability), availability),
        availability=availability,
    )
    before = review_assisted_quote(session, availability=availability)
    assert before.status == AssistedQuoteStatus.READY_FOR_PRICING

    values = before.configuration
    changed = dict(values)
    changed["material"] = "316"
    result = synchronize_session_from_form(
        session,
        previous_values=values,
        current_values=changed,
        current_origins={field: FormValueOrigin.CUSTOMER for field in values},
    )
    after = review_assisted_quote(result.session, availability=availability)
    assert not after.confirmation_current
    assert after.status == AssistedQuoteStatus.NEEDS_CONFIRMATION


def test_unsupported_observation_is_not_substituted(availability):
    contract = _contract(
        _proposal(
            "material",
            "material",
            "Hastelloy C276",
            unsupported=True,
            status=FieldStatus.UNSUPPORTED,
        )
    )
    session = build_assisted_quote_session(contract, availability=availability)
    merged = integrate_selected_session(
        session,
        current_values=_manual_defaults(),
        current_origins={
            field: FormValueOrigin.DEFAULT for field in _manual_defaults()
        },
        availability=availability,
    )
    assert merged.values["material"] is None
    assert (
        "material"
        in review_assisted_quote(
            merged.session, availability=availability
        ).unsupported_fields
    )


def test_manual_and_assisted_pricing_boundary_are_exactly_equal(availability):
    confirmed = confirm_configuration(
        _complete(_standard_session(availability), availability),
        availability=availability,
    )
    manual_payload = review_assisted_quote(
        confirmed, availability=availability
    ).configuration
    accepted = accept_pricing_boundary_without_invocation(
        confirmed, manual_payload, availability=availability
    )
    assert accepted.structures_equal
    assert accepted.manual_quote_request == accepted.assisted_quote_request
    assert not accepted.pricing_invoked
    assert not accepted.checkout_invoked
    assert not accepted.order_created


def test_real_page_keeps_manual_pricing_and_existing_svg_when_feature_disabled(
    monkeypatch, active_config
):
    from streamlit.testing.v1 import AppTest

    monkeypatch.setenv("API_BASE", "http://test")
    monkeypatch.delenv("OPLATES_DRAWING_ASSISTED_ENABLED", raising=False)
    monkeypatch.setattr(auth, "API_BASE", "http://test")
    quote_calls = []

    def fake_get(url, **kwargs):
        assert url.endswith("/config/active")
        return _Response(active_config)

    def fake_post(url, **kwargs):
        quote_calls.append((url, kwargs["json"]))
        return _Response(
            {
                "unit_price": 100.0,
                "total_price": 100.0,
                "area_sq_in": 10.0,
                "estimated_total_weight_lb": 5.0,
                "estimated_package_in": {"length": 10, "width": 10, "height": 2},
                "configuration_id": "manual-test",
                "pricing_config_version": "test",
            }
        )

    with patch("requests.get", fake_get), patch("requests.post", fake_post):
        app = AppTest.from_file(
            str(ROOT / "pages" / "1_Quote.py"), default_timeout=20
        ).run()

    assert not app.exception
    assert not app.get("file_uploader")
    assert quote_calls
    assert quote_calls[0][1]["paddle_dia"] == 3.0
    assert quote_calls[0][1]["bore_dia"] == 1.0
    assert "render_plate_svg" in (ROOT / "pages" / "1_Quote.py").read_text()


def test_manual_chamfer_waits_for_width_before_requesting_price(
    monkeypatch, active_config
):
    from streamlit.testing.v1 import AppTest

    monkeypatch.setenv("API_BASE", "http://test")
    monkeypatch.delenv("OPLATES_DRAWING_ASSISTED_ENABLED", raising=False)
    monkeypatch.setattr(auth, "API_BASE", "http://test")
    quote_calls = []

    def fake_get(url, **kwargs):
        assert url.endswith("/config/active")
        return _Response(active_config)

    def fake_post(url, **kwargs):
        quote_calls.append(kwargs["json"])
        return _Response(
            {
                "unit_price": 100.0,
                "total_price": 100.0,
                "area_sq_in": 10.0,
                "estimated_total_weight_lb": 5.0,
                "estimated_package_in": {"length": 10, "width": 10, "height": 2},
                "configuration_id": "manual-chamfer",
            }
        )

    with patch("requests.get", fake_get), patch("requests.post", fake_post):
        app = AppTest.from_file(str(ROOT / "pages" / "1_Quote.py"), default_timeout=20)
        app.run()
        initial_count = len(quote_calls)
        next(field for field in app.checkbox if field.label == "Chamfer").set_value(
            True
        ).run()
        assert not app.exception
        assert not app.error
        assert len(quote_calls) == initial_count
        assert any("Complete the required fields" in item.value for item in app.info)
        assert (
            next(
                field
                for field in app.number_input
                if field.label == "Chamfer Width (in.)"
            ).value
            is None
        )

        next(
            field for field in app.number_input if field.label == "Chamfer Width (in.)"
        ).set_value(0.0625).run()
        assert not app.exception
        assert not app.error
        assert len(quote_calls) == initial_count + 1
        assert quote_calls[-1]["chamfer"] is True
        assert quote_calls[-1]["chamfer_width"] == 0.0625


def test_internal_entry_point_requires_server_verified_access(
    monkeypatch, active_config
):
    from streamlit.testing.v1 import AppTest

    monkeypatch.setenv("API_BASE", "http://test")
    monkeypatch.setenv("OPLATES_DRAWING_ASSISTED_ENABLED", "true")
    monkeypatch.setattr(auth, "API_BASE", "http://test")

    def fake_get(url, **kwargs):
        if url.endswith("/config/active"):
            return _Response(active_config)
        return _Response({"detail": "Forbidden"}, status_code=403)

    with patch("requests.get", fake_get), patch(
        "requests.post",
        lambda *args, **kwargs: _Response(
            {
                "unit_price": 100.0,
                "total_price": 100.0,
                "configuration_id": "manual",
            }
        ),
    ):
        app = AppTest.from_file(str(ROOT / "pages" / "1_Quote.py"), default_timeout=20)
        app.session_state["auth"] = {
            "access_token": _jwt("ordinary-user"),
            "refresh_token": None,
            "user": None,
            "email": "ordinary@example.com",
        }
        app.run()

    assert not app.exception
    assert not app.get("file_uploader")


def test_invalid_upload_preserves_existing_manual_configuration(
    monkeypatch, active_config
):
    from streamlit.testing.v1 import AppTest

    monkeypatch.setenv("API_BASE", "http://test")
    monkeypatch.setenv("OPLATES_DRAWING_ASSISTED_ENABLED", "true")
    monkeypatch.setattr(auth, "API_BASE", "http://test")
    quote_calls = []

    def fake_get(url, **kwargs):
        if url.endswith("/config/active"):
            return _Response(active_config)
        return _Response(
            {"enabled": True, "authorized": True, "user_id": "internal-user"}
        )

    def fake_post(url, **kwargs):
        quote_calls.append(kwargs["json"])
        return _Response(
            {
                "unit_price": 100.0,
                "total_price": 100.0,
                "area_sq_in": 10.0,
                "estimated_total_weight_lb": 5.0,
                "estimated_package_in": {"length": 10, "width": 10, "height": 2},
                "configuration_id": "manual-preserved",
                "pricing_config_version": "test",
            }
        )

    with patch("requests.get", fake_get), patch("requests.post", fake_post):
        app = AppTest.from_file(str(ROOT / "pages" / "1_Quote.py"), default_timeout=20)
        app.session_state["auth"] = {
            "access_token": _jwt("internal-user"),
            "refresh_token": None,
            "user": None,
            "email": "internal@example.com",
        }
        app.run()
        app.get("file_uploader")[0].set_value(
            ("broken.pdf", b"not a pdf", "application/pdf")
        ).run()
        next(
            button for button in app.button if button.label == "Analyze drawing"
        ).click().run()

    assert not app.exception
    assert any("supported drawing" in item.value.lower() for item in app.error)
    assert (
        next(
            field
            for field in app.number_input
            if field.label == "Plate outside diameter (in.)"
        ).value
        == 3.0
    )
    assert (
        next(
            field for field in app.number_input if field.label == "Bore diameter (in.)"
        ).value
        == 1.0
    )
    assert quote_calls


def test_internal_real_form_upload_populate_complete_confirm_without_pricing(
    monkeypatch, active_config, availability
):
    from streamlit.testing.v1 import AppTest

    monkeypatch.setenv("API_BASE", "http://test")
    monkeypatch.setenv("OPLATES_DRAWING_ASSISTED_ENABLED", "true")
    monkeypatch.setattr(auth, "API_BASE", "http://test")
    quote_calls = []

    source_bytes = _pdf()
    base_processed = inspect_assisted_upload(
        source_bytes, "internal-test.pdf", media_type="application/pdf"
    )
    candidate = AssistedCandidateOption(
        candidate_id="plate-1",
        kind=AssistedCandidateKind.DETAIL_REGION,
        label="Plate detail plate-1",
        page_number=1,
        source_bbox=(0.0, 0.0, 612.0, 792.0),
    )
    processed = ProcessedAssistedUpload(
        document=base_processed.document,
        recognition=base_processed.recognition,
        review=AssistedDocumentReview(
            filename="internal-test.pdf",
            sha256=base_processed.document.sha256,
            document_class=DrawingDocumentClass.SINGLE_PLATE_DRAWING,
            quote_specific=True,
            reason="one synthetic test plate",
            candidates=[candidate],
            selection_required=False,
            processing_seconds=0.01,
        ),
        regions={},
        schedule_rows={},
    )
    recognized = _standard_session(availability)

    def fake_get(url, **kwargs):
        if url.endswith("/config/active"):
            return _Response(active_config)
        return _Response(
            {"enabled": True, "authorized": True, "user_id": "internal-user"}
        )

    def fake_post(url, **kwargs):
        quote_calls.append(kwargs["json"])
        return _Response(
            {
                "unit_price": 100.0,
                "total_price": 100.0,
                "area_sq_in": 10.0,
                "estimated_total_weight_lb": 5.0,
                "estimated_package_in": {"length": 10, "width": 10, "height": 2},
                "configuration_id": "manual-before-drawing",
                "pricing_config_version": "test",
            }
        )

    with (
        patch("requests.get", fake_get),
        patch("requests.post", fake_post),
        patch(
            "drawing_intake.configurator_integration.inspect_validated_upload",
            return_value=processed,
        ),
        patch(
            "drawing_intake.configurator_integration.recognize_selected_candidate",
            return_value=recognized,
        ),
    ):
        app = AppTest.from_file(str(ROOT / "pages" / "1_Quote.py"), default_timeout=30)
        app.session_state["auth"] = {
            "access_token": _jwt("internal-user"),
            "refresh_token": None,
            "user": None,
            "email": "internal@example.com",
        }
        app.run()
        assert not app.exception
        app.get("file_uploader")[0].set_value(
            ("internal-test.pdf", source_bytes, "application/pdf")
        ).run()
        next(
            button for button in app.button if button.label == "Analyze drawing"
        ).click().run()
        assert not app.exception
        assert not any(
            button.label == "Apply identified values" for button in app.button
        )

        assert (
            next(
                field
                for field in app.number_input
                if field.label == "Plate outside diameter (in.)"
            ).value
            == 8.0
        )
        assert (
            next(
                field
                for field in app.number_input
                if field.label == "Bore diameter (in.)"
            ).value
            == 2.0
        )
        assert any("Handle width" in item.value for item in app.info)
        assert any(
            "fields outlined in red" in item.value
            and "Handle width" in item.value
            and "Lead time" in item.value
            for item in app.error
        )
        highlight = "\n".join(item.value for item in app.markdown)
        assert ".st-key-quote_field_handle_width" in highlight
        assert ".st-key-quote_field_handle_length_from_bore" in highlight
        assert ".st-key-quote_field_ships_in_days" in highlight
        assert ".st-key-quote_field_paddle_dia" not in highlight
        assert ".st-key-quote_field_handle_label" not in highlight

        next(field for field in app.selectbox if field.label == "Chamfer").set_value(
            True
        ).run()
        assert not app.exception
        assert any(
            ".st-key-quote_field_chamfer_width" in item.value for item in app.markdown
        )
        next(field for field in app.selectbox if field.label == "Chamfer").set_value(
            False
        ).run()
        assert not app.exception
        assert not any(
            ".st-key-quote_field_chamfer_width" in item.value for item in app.markdown
        )

        next(
            field for field in app.number_input if field.label == "Bore diameter (in.)"
        ).set_value(9.0).run()
        assert any(
            ".st-key-quote_field_bore_dia" in item.value for item in app.markdown
        )
        assert any(
            "Bore diameter" in item.value and "fields outlined in red" in item.value
            for item in app.error
        )
        next(
            field for field in app.number_input if field.label == "Bore diameter (in.)"
        ).set_value(2.0).run()
        assert not any(
            ".st-key-quote_field_bore_dia" in item.value for item in app.markdown
        )
        price_calls_after_apply = len(quote_calls)

        next(
            field for field in app.number_input if field.label == "Handle width (in.)"
        ).set_value(1.5)
        next(
            field
            for field in app.number_input
            if field.label == "Handle length from bore center (in.)"
        ).set_value(9.0)
        next(field for field in app.selectbox if field.label == "Lead time").set_value(
            14
        )
        app.run()
        assert not app.exception
        assert not any("fields outlined in red" in item.value for item in app.error)
        assert not any(
            ".st-key-quote_field_handle_width" in item.value for item in app.markdown
        )

        confirmation = next(
            field
            for field in app.checkbox
            if field.label.startswith("I have reviewed the dimensions")
        )
        assert not confirmation.disabled
        confirmation.set_value(True).run()
        assert not app.exception
        success_messages = [item.value for item in app.success]
        final_session = app.session_state["phase1g_assisted_session"]
        final_review = review_assisted_quote(final_session, availability=availability)
        assert any(
            "Configuration confirmed and ready" in item for item in success_messages
        ), {
            "messages": success_messages,
            "confirmation_widget": app.session_state.get(
                "phase1g_customer_confirmation"
            ),
            "fingerprint": final_session.confirmation_fingerprint,
            "review": final_review.model_dump(),
        }
        assert len(quote_calls) == price_calls_after_apply
        assert (
            app.session_state["phase1g_assisted_session"].selected_candidate_id
            == "plate-1"
        )
        next(
            button
            for button in app.button
            if button.label == "Reset quote and return to manual entry"
        ).click().run()
        assert not app.exception
        assert (
            next(
                field
                for field in app.number_input
                if field.label == "Plate outside diameter (in.)"
            ).value
            == 3.0
        )
        assert (
            next(
                field
                for field in app.number_input
                if field.label == "Bore diameter (in.)"
            ).value
            == 1.0
        )
        assert len(quote_calls) > price_calls_after_apply

        next(
            field
            for field in app.number_input
            if field.label == "Plate outside diameter (in.)"
        ).set_value(8.25).run()
        app.get("file_uploader")[0].set_value(
            ("internal-test.pdf", source_bytes, "application/pdf")
        ).run()
        next(
            button for button in app.button if button.label == "Analyze drawing"
        ).click().run()
        assert not app.exception
        assert (
            next(
                field
                for field in app.number_input
                if field.label == "Plate outside diameter (in.)"
            ).value
            == 8.25
        )
        next(
            button for button in app.button if button.label == "Apply identified values"
        ).click().run()
        assert not app.exception
        assert (
            next(
                field
                for field in app.number_input
                if field.label == "Plate outside diameter (in.)"
            ).value
            == 8.25
        )
        assert (
            next(
                field
                for field in app.number_input
                if field.label == "Bore diameter (in.)"
            ).value
            == 2.0
        )


def test_source_contract_has_no_upload_api_or_drawing_pricing_path():
    api_source = (ROOT / "api_app.py").read_text()
    quote_source = (ROOT / "pages" / "1_Quote.py").read_text()
    pricing_source = (ROOT / "pricing_engine.py").read_text()

    assert '@app.post("/internal/drawing-intake' not in api_source
    assert '@app.get("/internal/drawing-intake/access")' in api_source
    assert "calculate_quote" not in quote_source
    assert "accept_pricing_boundary_without_invocation" in quote_source
    assert "drawing" not in pricing_source.lower()
    assert 'st.subheader("Configuration Drawing")' in quote_source
    assert 'st.checkbox("Chamfer", value=False)' in quote_source


def test_candidate_metadata_remains_explicit_and_source_scoped(active_config):
    document = normalize_document(_png(), "two-plate.png", "image/png")
    review = AssistedDocumentReview(
        filename=document.filename,
        sha256=document.sha256,
        document_class=DrawingDocumentClass.MULTI_PLATE_DRAWING,
        quote_specific=True,
        reason="two independent plate regions",
        candidates=[
            AssistedCandidateOption(
                candidate_id="plate-a",
                kind=AssistedCandidateKind.DETAIL_REGION,
                label="Plate A",
                page_number=1,
                source_bbox=(0, 0, 50, 80),
            ),
            AssistedCandidateOption(
                candidate_id="plate-b",
                kind=AssistedCandidateKind.DETAIL_REGION,
                label="Plate B",
                page_number=1,
                source_bbox=(60, 0, 120, 80),
            ),
        ],
        selection_required=True,
        processing_seconds=0.01,
    )
    assert review.selection_required
    assert review.candidates[0].source_bbox[2] < review.candidates[1].source_bbox[0]
    assert review.sha256 == document.sha256
