import io
from pathlib import Path

import pytest
from PIL import Image

from drawing_intake.assisted_intake import (
    AssistedCandidateKind,
    AssistedCandidateOption,
    AssistedDocumentReview,
    ProcessedAssistedUpload,
    select_assisted_candidate,
)

from drawing_intake.assisted_quote import (
    AssistedQuoteStatus,
    CanonicalFormAvailability,
    ConfigurationValueOrigin,
    FieldAttentionKind,
    build_assisted_quote_session,
    build_manual_quote_session,
    build_pricing_handoff_preview,
    canonical_required_fields,
    confirm_configuration,
    reject_drawing_proposal,
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
from drawing_intake.models import (
    CandidateRegionHint,
    CoordinateUnit,
    DocumentStatus,
    DocumentStructureAssessment,
    FieldStatus,
    MeasurementUnit,
    SourceEvidence,
)
from drawing_intake.documents import normalize_document
from drawing_intake.regions import derive_candidate_regions
from drawing_intake.table_schedule import (
    TableFieldObservation,
    TablePlateCandidate,
)
from pricing_engine import QuoteInputs

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def availability():
    return CanonicalFormAvailability(
        materials=["304", "316", "Carbon Steel"],
        thicknesses_by_material={
            "304": [0.125, 0.25],
            "316": [0.125, 0.25],
            "Carbon Steel": [0.125],
        },
        tolerance_options_in=[0.001, 0.002, 0.005],
        lead_times_days=[14, 21],
        max_paddle_dia_in=48.0,
        max_bore_dia_in=19.0,
        max_handle_label_chars=40,
    )


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
        source_document="selected.pdf",
        source_sha256="1" * 64,
        source_page=1,
        source_bbox=(10, 20, 30, 40),
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


def _contract(*proposals, candidate_count=1, selected="plate-1", document_class=None):
    return CustomerConfirmationContract(
        source_document="selected.pdf",
        source_sha256="1" * 64,
        document_class=document_class or DrawingDocumentClass.SINGLE_PLATE_DRAWING,
        candidate_count=candidate_count,
        selected_candidate_id=selected,
        selection_required=candidate_count != 1 or selected is None,
        proposals=list(proposals),
        status=ConfirmationWorkflowStatus.REQUIRES_CONFIRMATION,
    )


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
        "ships_in_days": 21,
    }
    for field, value in values.items():
        if field not in session.configuration:
            session = set_customer_value(session, field, value)
    return session


def _standard_contract():
    return _contract(
        _proposal("outside_diameter", "paddle_dia", 8.0, unit=MeasurementUnit.INCH),
        _proposal("bore_diameter", "bore_dia", 2.0, unit=MeasurementUnit.INCH),
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
    )


def test_drawing_values_map_to_actual_quote_inputs_and_metric_normalizes(availability):
    contract = _contract(
        _proposal(
            "outside_diameter",
            "paddle_dia",
            203.2,
            unit=MeasurementUnit.MILLIMETER,
        ),
        _proposal(
            "bore_diameter",
            "bore_dia",
            50.8,
            unit=MeasurementUnit.MILLIMETER,
        ),
    )

    session = build_assisted_quote_session(contract, availability=availability)

    assert session.configuration["paddle_dia"].value == pytest.approx(8.0)
    assert session.configuration["bore_dia"].value == pytest.approx(2.0)
    assert set(canonical_required_fields()) == {
        name for name, field in QuoteInputs.model_fields.items() if field.is_required()
    }


def test_missing_fields_update_when_customer_enters_and_clears_value(availability):
    session = build_assisted_quote_session(
        _standard_contract(), availability=availability
    )
    before = review_assisted_quote(session, availability=availability)
    assert "handle_width" in before.missing_required_fields

    entered = set_customer_value(session, "handle_width", 1.5)
    after_enter = review_assisted_quote(entered, availability=availability)
    assert "handle_width" not in after_enter.missing_required_fields

    cleared = set_customer_value(entered, "handle_width", None)
    after_clear = review_assisted_quote(cleared, availability=availability)
    assert "handle_width" in after_clear.missing_required_fields


def test_unreadable_bore_stays_blank_until_customer_supplies_it(availability):
    contract = _contract(
        _proposal(
            "bore_diameter",
            "bore_dia",
            None,
            unit=MeasurementUnit.INCH,
            status=FieldStatus.AMBIGUOUS,
        )
    )
    session = build_assisted_quote_session(contract, availability=availability)
    assert "bore_dia" not in session.configuration
    assert (
        "bore_dia"
        in review_assisted_quote(
            session, availability=availability
        ).missing_required_fields
    )

    entered = set_customer_value(session, "bore_dia", 2.0)
    assert entered.configuration["bore_dia"].origin == ConfigurationValueOrigin.CUSTOMER
    assert (
        "bore_dia"
        not in review_assisted_quote(
            entered, availability=availability
        ).missing_required_fields
    )


def test_customer_correction_wins_and_original_provenance_remains(availability):
    session = build_assisted_quote_session(
        _standard_contract(), availability=availability
    )
    corrected = set_customer_value(session, "paddle_dia", 8.25)

    assert corrected.configuration["paddle_dia"].value == 8.25
    assert (
        corrected.configuration["paddle_dia"].origin
        == ConfigurationValueOrigin.CUSTOMER
    )
    proposal = next(
        item
        for item in corrected.proposals
        if item.extraction_field == "outside_diameter"
    )
    assert proposal.proposed_value == 8.0
    assert proposal.source_bbox == (10, 20, 30, 40)


def test_rejected_proposal_clears_only_drawing_value(availability):
    session = build_assisted_quote_session(
        _standard_contract(), availability=availability
    )
    rejected = reject_drawing_proposal(session, "outside_diameter")
    assert "paddle_dia" not in rejected.configuration
    assert "outside_diameter" in rejected.rejected_extraction_fields

    corrected = set_customer_value(session, "paddle_dia", 8.25)
    corrected_rejected = reject_drawing_proposal(corrected, "outside_diameter")
    assert corrected_rejected.configuration["paddle_dia"].value == 8.25


def test_asymmetric_or_incomplete_tolerance_is_not_silently_mapped(availability):
    asymmetric = _contract(
        _proposal(
            "bore_tolerance_plus",
            "bore_tolerance",
            0.002,
            unit=MeasurementUnit.INCH,
        ),
        _proposal(
            "bore_tolerance_minus",
            "bore_tolerance",
            0.0,
            unit=MeasurementUnit.INCH,
        ),
    )
    incomplete = _contract(
        _proposal(
            "bore_tolerance_plus",
            "bore_tolerance",
            0.005,
            unit=MeasurementUnit.INCH,
        ),
        _proposal(
            "bore_tolerance_minus",
            "bore_tolerance",
            None,
            unit=MeasurementUnit.INCH,
            status=FieldStatus.AMBIGUOUS,
        ),
    )

    assert (
        "bore_tolerance"
        not in build_assisted_quote_session(
            asymmetric, availability=availability
        ).configuration
    )
    assert (
        "bore_tolerance"
        not in build_assisted_quote_session(
            incomplete, availability=availability
        ).configuration
    )


def test_chamfer_dependency_is_dynamic(availability):
    session = _complete(build_manual_quote_session(), availability)
    without_chamfer = review_assisted_quote(session, availability=availability)
    assert "chamfer_width" not in without_chamfer.missing_required_fields

    enabled = set_customer_value(session, "chamfer", True)
    enabled_review = review_assisted_quote(enabled, availability=availability)
    assert "chamfer_width" in enabled_review.missing_required_fields

    with_width = set_customer_value(enabled, "chamfer_width", 0.062)
    assert (
        "chamfer_width"
        not in review_assisted_quote(
            with_width, availability=availability
        ).missing_required_fields
    )

    disabled = set_customer_value(with_width, "chamfer", False)
    assert (
        "chamfer_width"
        not in review_assisted_quote(
            disabled, availability=availability
        ).missing_required_fields
    )


def test_invalid_bore_relationship_blocks_confirmation(availability):
    session = _complete(build_manual_quote_session(), availability)
    session = set_customer_value(session, "bore_dia", 9.0)
    review = review_assisted_quote(session, availability=availability)

    assert "bore_dia" in review.invalid_fields
    with pytest.raises(ValueError, match="complete and valid"):
        confirm_configuration(session, availability=availability)


def test_api_incompatible_handle_marking_is_flagged_before_handoff(availability):
    session = _complete(build_manual_quote_session(), availability)
    session = set_customer_value(session, "handle_label", "BAD @ MARK")
    review = review_assisted_quote(session, availability=availability)
    assert "handle_label" in review.invalid_fields


def test_unsupported_drawing_value_is_preserved_but_customer_can_choose_supported(
    availability,
):
    unsupported = _proposal(
        "thickness",
        "thickness",
        6.0,
        unit=MeasurementUnit.MILLIMETER,
        status=FieldStatus.UNSUPPORTED,
        unsupported=True,
        raw="6 mm",
    )
    session = build_assisted_quote_session(
        _contract(unsupported), availability=availability
    )
    assert "thickness" not in session.configuration
    assert session.proposals[0].proposed_value == 6.0

    selected = set_customer_value(session, "thickness", 0.125)
    review = review_assisted_quote(selected, availability=availability)
    assert "thickness" in review.unsupported_fields
    assert any(
        item.kind == FieldAttentionKind.UNSUPPORTED and "6 mm" in item.message
        for item in review.attention
    )


def test_confirmation_required_and_any_later_change_invalidates_it(availability):
    session = _complete(
        build_assisted_quote_session(_standard_contract(), availability=availability),
        availability,
    )
    assert (
        review_assisted_quote(session, availability=availability).status
        == AssistedQuoteStatus.NEEDS_CONFIRMATION
    )

    confirmed = confirm_configuration(session, availability=availability)
    assert (
        review_assisted_quote(confirmed, availability=availability).status
        == AssistedQuoteStatus.READY_FOR_PRICING
    )

    changed = set_customer_value(confirmed, "bore_dia", 2.25)
    assert changed.confirmation_fingerprint is None
    assert (
        review_assisted_quote(changed, availability=availability).status
        == AssistedQuoteStatus.NEEDS_CONFIRMATION
    )


def test_handoff_uses_exact_quoteinputs_schema_without_pricing_or_checkout(
    availability,
):
    session = _complete(build_manual_quote_session(), availability)
    confirmed = confirm_configuration(session, availability=availability)
    handoff = build_pricing_handoff_preview(confirmed, availability=availability)

    assert set(handoff.quote_request) == set(QuoteInputs.model_fields)
    assert handoff.destination.startswith("QuoteRequest -> QuoteInputs")
    assert handoff.pricing_invoked is False
    assert handoff.checkout_invoked is False
    assert handoff.order_created is False


def test_multi_candidate_contract_cannot_confirm_until_explicit_selection(availability):
    session = build_assisted_quote_session(
        _contract(*_standard_contract().proposals, candidate_count=2, selected=None),
        availability=availability,
    )
    complete = _complete(session, availability)
    assert (
        review_assisted_quote(complete, availability=availability).status
        == AssistedQuoteStatus.SELECTION_REQUIRED
    )
    with pytest.raises(ValueError, match="must be selected"):
        confirm_configuration(complete, availability=availability)


def test_two_candidate_sessions_cannot_cross_populate(availability):
    first = build_assisted_quote_session(
        _contract(
            _proposal("outside_diameter", "paddle_dia", 8.0, unit=MeasurementUnit.INCH),
            selected="plate-a",
        ),
        availability=availability,
    )
    second = build_assisted_quote_session(
        _contract(
            _proposal(
                "outside_diameter", "paddle_dia", 12.0, unit=MeasurementUnit.INCH
            ),
            selected="plate-b",
        ),
        availability=availability,
    )

    assert first.selected_candidate_id == "plate-a"
    assert first.configuration["paddle_dia"].value == 8.0
    assert second.selected_candidate_id == "plate-b"
    assert second.configuration["paddle_dia"].value == 12.0


def test_reference_document_enters_manual_path_without_random_candidate(availability):
    session = build_manual_quote_session(
        source_document="reference.jpg",
        source_sha256="2" * 64,
        document_class=DrawingDocumentClass.REFERENCE_VENDOR_DATASHEET,
    )
    review = review_assisted_quote(session, availability=availability)

    assert session.selected_candidate_id is None
    assert session.configuration == {}
    assert review.status == AssistedQuoteStatus.MANUAL_CONFIGURATION


def _table_observation(value, *, unit=None, raw=None):
    return TableFieldObservation(
        value=value,
        normalized_unit=unit,
        raw_text=raw or str(value),
        status=FieldStatus.LOW_CONFIDENCE,
        evidence=SourceEvidence(
            page_number=1,
            raw_text=raw or str(value),
            bbox=(10, 20, 30, 40),
            coordinate_unit=CoordinateUnit.PDF_POINT,
            extraction_method="synthetic_table",
        ),
    )


def _schedule_row(index, *, tag, od, bore):
    return TablePlateCandidate(
        row_index=index,
        tag=_table_observation(tag),
        quantity=_table_observation(1, unit=MeasurementUnit.COUNT),
        outside_diameter=_table_observation(od, unit=MeasurementUnit.MILLIMETER),
        thickness=_table_observation(6.0, unit=MeasurementUnit.MILLIMETER, raw="6 mm"),
        bore_diameter=_table_observation(bore, unit=MeasurementUnit.MILLIMETER),
        bore_tolerance_plus=_table_observation(
            0.08, unit=MeasurementUnit.MILLIMETER, raw="±0.08"
        ),
        bore_tolerance_minus=_table_observation(
            0.08, unit=MeasurementUnit.MILLIMETER, raw="±0.08"
        ),
        material=_table_observation("316", raw="S.S.-316"),
        global_units=_table_observation("mm", unit=MeasurementUnit.MILLIMETER),
    )


def _schedule_upload():
    image = Image.new("L", (100, 100), 255)
    output = io.BytesIO()
    image.save(output, format="PNG")
    document = normalize_document(output.getvalue(), "schedule.png", "image/png")
    first = _schedule_row(1, tag="FIT-01 103", od=406.4, bore=162.08)
    second = _schedule_row(2, tag="FIT-01 203", od=276.1, bore=115.75)
    options = [
        AssistedCandidateOption(
            candidate_id="schedule-row-1",
            kind=AssistedCandidateKind.SCHEDULE_ROW,
            label="FIT-01 103",
            page_number=1,
            row_index=1,
        ),
        AssistedCandidateOption(
            candidate_id="schedule-row-2",
            kind=AssistedCandidateKind.SCHEDULE_ROW,
            label="FIT-01 203",
            page_number=1,
            row_index=2,
        ),
    ]
    return ProcessedAssistedUpload(
        document=document,
        recognition=None,
        review=AssistedDocumentReview(
            filename=document.filename,
            sha256=document.sha256,
            document_class=DrawingDocumentClass.TABLE_DRIVEN_PLATE_SCHEDULE,
            quote_specific=True,
            reason="synthetic table",
            candidates=options,
            selection_required=True,
            processing_seconds=0,
        ),
        regions={},
        schedule_rows={"schedule-row-1": first, "schedule-row-2": second},
    )


def test_table_row_selection_is_explicit_and_isolated():
    upload = _schedule_upload()
    first = select_assisted_candidate(upload, "schedule-row-1")
    second = select_assisted_candidate(upload, "schedule-row-2")

    assert first.selected_candidate_id == "schedule-row-1"
    assert second.selected_candidate_id == "schedule-row-2"
    assert first.candidate_count == 2
    assert first.selection_required is False
    assert first.configuration["paddle_dia"].value == pytest.approx(16.0)
    assert second.configuration["paddle_dia"].value == pytest.approx(10.87007874)
    assert (
        first.configuration["bore_dia"].value != second.configuration["bore_dia"].value
    )


def test_schedule_support_audit_retains_unsupported_thickness_and_tolerance():
    session = select_assisted_candidate(_schedule_upload(), "schedule-row-1")
    review = review_assisted_quote(session)

    assert "thickness" not in session.configuration
    assert "bore_tolerance" not in session.configuration
    assert "thickness" in review.unsupported_fields
    assert "bore_tolerance" in review.unsupported_fields
    thickness = next(
        item for item in session.proposals if item.extraction_field == "thickness"
    )
    assert thickness.proposed_value == 6.0
    assert thickness.raw_text == "6 mm"


def test_raster_candidate_derivation_preserves_pixel_coordinate_system():
    image = Image.new("L", (300, 200), 255)
    output = io.BytesIO()
    image.save(output, format="PNG")
    document = normalize_document(output.getvalue(), "raster.png", "image/png")
    structure = DocumentStructureAssessment(
        status=DocumentStatus.SINGLE_CANDIDATE,
        candidate_region_count=1,
        candidate_regions=[
            CandidateRegionHint(
                page_number=1,
                bbox=(100, 50, 200, 150),
                coordinate_unit=CoordinateUnit.PIXEL,
                detection_method="synthetic",
            )
        ],
    )

    region = derive_candidate_regions(document, structure, source_group_id="synthetic")[
        0
    ]
    assert region.coordinate_unit == CoordinateUnit.PIXEL


def test_internal_prototype_is_gated_and_contains_no_pricing_checkout_calls():
    source = (ROOT / "internal_drawing_quote_app.py").read_text()
    assert 'os.environ.get("OPLATES_INTERNAL_DRAWING_PROTOTYPE") != "1"' in source
    assert "request_authoritative_price" not in source
    assert "calculate_quote" not in source
    assert "start_checkout" not in source
    assert '"Reject this drawing proposal"' in source
    assert "requests.post" not in source
    assert "stripe" not in source.lower()
    assert "openai" not in source.lower()
    assert "anthropic" not in source.lower()


def test_internal_streamlit_prototype_renders_when_locally_enabled(monkeypatch):
    from streamlit.testing.v1 import AppTest

    monkeypatch.setenv("OPLATES_INTERNAL_DRAWING_PROTOTYPE", "1")
    app = AppTest.from_file(
        str(ROOT / "internal_drawing_quote_app.py"), default_timeout=20
    ).run()

    assert not app.exception
    assert app.title[0].value == "Drawing-Assisted Quote — Internal Prototype"
    assert len(app.get("file_uploader")) == 1
    assert next(
        button for button in app.button if button.label == "Analyze drawing"
    ).disabled


def test_drawing_integration_preserves_authoritative_pricing_entrypoint():
    quote_source = (ROOT / "pages" / "1_Quote.py").read_text()
    pricing_source = (ROOT / "pricing_engine.py").read_text()

    # Phase 1G intentionally integrates drawing assistance into the real page.
    # Preserve the original safety intent: pricing remains API-authoritative.
    assert "calculate_quote" not in quote_source
    assert "accept_pricing_boundary_without_invocation" in quote_source
    assert "drawing_intake" not in pricing_source
    assert 'requests.post(\n            f"{API_BASE}/quote"' in quote_source
