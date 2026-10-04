import io

import pytest
from PIL import Image, ImageDraw

from drawing_intake.classification import DrawingDocumentClass
from drawing_intake.confirmation_contract import (
    ConfirmationWorkflowStatus,
    CustomerDecision,
    build_customer_confirmation_contract,
    record_customer_decision,
    record_manual_value,
)
from drawing_intake.deterministic import (
    DeterministicRecognitionResult,
    EvidenceClassification,
    FieldRecognitionResult,
    RecognitionEvidence,
    RecognitionTimings,
)
from drawing_intake.geometry import RegionGeometryEvidence
from drawing_intake.models import (
    CoordinateUnit,
    DocumentReference,
    DrawingExtractionResult,
    DrawingFields,
    FieldStatus,
    IntegerField,
    MeasurementUnit,
    NumericField,
    ProviderDataHandling,
    SourceEvidence,
    StringField,
    UnitField,
)
from drawing_intake.ocr import (
    LocalOcrResult,
    OcrTokenObservation,
    recover_plus_minus_glyphs,
)
from drawing_intake.reconciliation_workflow import (
    ReconciliationReviewStatus,
    build_reconciliation_review,
)
from drawing_intake.regions import DerivedDrawingRegion
from drawing_intake.rendering import RegionCoordinateTransform, RenderedRegion
from drawing_intake.schedule_benchmark import ScheduleFieldScore, _aggregate
from drawing_intake.table_schedule import _quantity_from_cell_text
from drawing_intake.validation import validate_extraction


def _rendered_glyph(second_bar: bool) -> tuple[RenderedRegion, LocalOcrResult]:
    image = Image.new("L", (140, 50), 255)
    draw = ImageDraw.Draw(image)
    draw.line((15, 8, 15, 26), fill=0, width=2)
    draw.line((8, 15, 22, 15), fill=0, width=2)
    if second_bar:
        draw.line((8, 24, 22, 24), fill=0, width=2)
    output = io.BytesIO()
    image.save(output, format="PNG")
    region = DerivedDrawingRegion(
        region_id="cell",
        source_group_id="synthetic-phase1e",
        source_filename="cell.png",
        page_number=1,
        source_bbox=(0, 0, image.width, image.height),
        candidate_bbox=(0, 0, image.width, image.height),
        coordinate_unit=CoordinateUnit.PIXEL,
    )
    rendered = RenderedRegion(
        region=region,
        dpi=600,
        width=image.width,
        height=image.height,
        transform=RegionCoordinateTransform(
            pdf_bbox=region.source_bbox,
            pixel_width=image.width,
            pixel_height=image.height,
            points_per_pixel_x=1,
            points_per_pixel_y=1,
        ),
        png_size_bytes=len(output.getvalue()),
        uncompressed_grayscale_bytes=image.width * image.height,
        render_seconds=0,
        png_bytes=output.getvalue(),
    )
    token = OcrTokenObservation(
        token_id="cell:psm6:1",
        region_id="cell",
        page_number=1,
        raw_text="+0.005",
        engine_confidence=90,
        pixel_bbox=(7, 7, 50, 30),
        source_bbox=(7, 7, 50, 30),
        source_coordinate_unit=CoordinateUnit.PIXEL,
        engine="synthetic",
        engine_pass="psm6",
        line_key="psm6:1",
    )
    return rendered, LocalOcrResult(
        engine="synthetic",
        engine_version="test",
        region_id="cell",
        dpi=600,
        page_segmentation_modes=[6],
        tokens=[token],
        ocr_seconds=0,
    )


def test_tolerance_cell_context_recovers_only_visual_two_band_plus_minus():
    rendered, result = _rendered_glyph(second_bar=True)
    without_bound_column = recover_plus_minus_glyphs(result, rendered)
    within_bound_column = recover_plus_minus_glyphs(
        result, rendered, tolerance_context=True
    )
    plain_rendered, plain = _rendered_glyph(second_bar=False)
    plain_in_bound_column = recover_plus_minus_glyphs(
        plain, plain_rendered, tolerance_context=True
    )

    assert without_bound_column.tokens[0].normalized_text is None
    assert within_bound_column.tokens[0].normalized_text == "±0.005"
    assert plain_in_bound_column.tokens[0].normalized_text is None


@pytest.mark.parametrize(
    "raw,expected",
    [("| 1", 1), ("[1 |", 1), ("|1]|", 1), ("12", 12), ("A-103", None)],
)
def test_quantity_cell_border_normalization_is_cell_scoped(raw, expected):
    assert _quantity_from_cell_text(raw) == expected


def _field(value, *, unit=MeasurementUnit.INCH, status=FieldStatus.DETECTED):
    return NumericField(
        value=value,
        normalized_unit=unit,
        raw_text=str(value) if value is not None else None,
        status=status,
        evidence=(
            [
                SourceEvidence(
                    page_number=1,
                    raw_text=str(value),
                    bbox=(10, 20, 30, 40),
                    coordinate_unit=CoordinateUnit.PDF_POINT,
                    extraction_method="synthetic",
                )
            ]
            if value is not None
            else []
        ),
    )


def _extraction(
    *,
    od=8.0,
    bore=2.0,
    bore_status=FieldStatus.DETECTED,
    units=MeasurementUnit.INCH,
    units_status=FieldStatus.DETECTED,
    tol_plus=0.005,
    tol_minus=0.005,
):
    return DrawingExtractionResult(
        document=DocumentReference(
            filename="selected.pdf",
            media_type="application/pdf",
            sha256="1" * 64,
            page_count=1,
        ),
        provider_name="synthetic-phase1e",
        provider_data_handling=ProviderDataHandling(
            external_service=False,
            retention="none",
            sends_document_content=False,
        ),
        fields=DrawingFields(
            outside_diameter=_field(od, unit=units),
            bore_diameter=_field(bore, unit=units, status=bore_status),
            thickness=_field(
                0.125 if units == MeasurementUnit.INCH else 3.175, unit=units
            ),
            material=StringField(value="304", status=FieldStatus.DETECTED),
            quantity=IntegerField(value=1, status=FieldStatus.DETECTED),
            global_units=UnitField(
                value=units.value if units_status == FieldStatus.DETECTED else None,
                normalized_unit=units if units_status == FieldStatus.DETECTED else None,
                status=units_status,
            ),
            bore_tolerance_plus=_field(tol_plus, unit=units),
            bore_tolerance_minus=_field(
                tol_minus,
                unit=units,
                status=(
                    FieldStatus.AMBIGUOUS if tol_minus is None else FieldStatus.DETECTED
                ),
            ),
        ),
    )


def _config(**updates):
    config = {
        "quantity": 1,
        "material": "304",
        "thickness": 0.125,
        "paddle_dia": 8.0,
        "bore_dia": 2.0,
        "bore_tolerance": 0.005,
        "chamfer": False,
    }
    config.update(updates)
    return config


def _evidence():
    return {
        name: EvidenceClassification.STRONG
        for name in (
            "outside_diameter",
            "bore_diameter",
            "thickness",
            "material",
            "global_units",
            "bore_tolerance_plus",
            "bore_tolerance_minus",
        )
    }


def test_reconciliation_missing_field_and_ambiguous_units_require_resolution():
    missing_bore = build_reconciliation_review(
        validate_extraction(
            _extraction(bore=None, bore_status=FieldStatus.NOT_DETECTED)
        ),
        _config(),
        selected_candidate_id="selected",
        evidence_by_field=_evidence(),
    )
    ambiguous_units = build_reconciliation_review(
        validate_extraction(_extraction(units_status=FieldStatus.AMBIGUOUS)),
        _config(),
        selected_candidate_id="selected",
        evidence_by_field=_evidence(),
    )

    assert missing_bore.status == ReconciliationReviewStatus.REQUIRES_RESOLUTION
    assert "bore_diameter" in missing_bore.critical_unknowns
    assert ambiguous_units.status == ReconciliationReviewStatus.REQUIRES_RESOLUTION
    assert "global_units" in ambiguous_units.critical_unknowns
    assert missing_bore.pricing_invoked is False
    assert ambiguous_units.automatic_overwrite_permitted is False


def test_reconciliation_normalizes_metric_values_but_does_not_invent_units():
    metric = _extraction(
        od=203.2,
        bore=50.8,
        units=MeasurementUnit.MILLIMETER,
        tol_plus=0.127,
        tol_minus=0.127,
    )
    review = build_reconciliation_review(
        validate_extraction(metric),
        _config(),
        selected_candidate_id="selected",
        evidence_by_field=_evidence(),
    )

    assert review.status == ReconciliationReviewStatus.MATCH
    assert review.critical_mismatches == []


def test_asymmetric_tolerance_never_maps_to_symmetric_canonical_field():
    extraction = _extraction(tol_plus=0.002, tol_minus=0.0)
    validation = validate_extraction(extraction)
    review = build_reconciliation_review(
        validation,
        _config(bore_tolerance=0.002),
        selected_candidate_id="selected",
        evidence_by_field=_evidence(),
    )

    assert validation.canonical_candidate.bore_tolerance is None
    assert any(
        issue.code == "asymmetric_tolerance_not_canonical"
        for issue in validation.issues
    )
    assert review.status == ReconciliationReviewStatus.BLOCKED
    assert set(review.critical_unsupported) >= {
        "bore_tolerance_plus",
        "bore_tolerance_minus",
    }


def _recognition(*, unsupported_od=False) -> DeterministicRecognitionResult:
    extraction = _extraction(od=60.0 if unsupported_od else 8.0)
    validation = validate_extraction(extraction)
    field_results = {}
    for name in type(extraction.fields).model_fields:
        field = getattr(extraction.fields, name)
        evidence = []
        if field.evidence:
            evidence = [
                RecognitionEvidence(
                    rule_id="synthetic",
                    description="Synthetic field evidence.",
                    source=field.evidence[0],
                )
            ]
        field_results[name] = FieldRecognitionResult(
            field_name=name,
            value=field.value,
            normalized_unit=field.normalized_unit,
            raw_text=field.raw_text,
            status=field.status,
            evidence_classification=(
                EvidenceClassification.STRONG
                if field.value is not None
                else EvidenceClassification.NOT_DETECTED
            ),
            evidence=evidence,
            candidate_values=([field.value] if field.value is not None else []),
        )
    region = DerivedDrawingRegion(
        region_id="selected",
        source_group_id="synthetic-phase1e",
        source_filename="selected.pdf",
        page_number=1,
        source_bbox=(0, 0, 100, 100),
        candidate_bbox=(20, 20, 80, 80),
    )
    return DeterministicRecognitionResult(
        region=region,
        rendered_width=100,
        rendered_height=100,
        rendered_png_size_bytes=0,
        rendered_uncompressed_bytes=10000,
        ocr_token_count=0,
        geometry=RegionGeometryEvidence(
            region_id="selected",
            profile_count=2,
            concentric_profile_count=2,
            has_inner_outer_profiles=True,
        ),
        field_results=field_results,
        extraction=extraction,
        validation=validation,
        timings=RecognitionTimings(
            rendering_seconds=0,
            ocr_seconds=0,
            interpretation_seconds=0,
            total_seconds=0,
        ),
    )


def test_confirmation_contract_preserves_proposal_evidence_and_customer_correction():
    recognition = _recognition()
    contract = build_customer_confirmation_contract(
        recognition,
        document_class=DrawingDocumentClass.SINGLE_PLATE_DRAWING,
        candidate_count=1,
        selected_candidate_id="selected",
    )
    original = next(
        item for item in contract.proposals if item.extraction_field == "bore_diameter"
    )
    corrected = record_customer_decision(
        contract,
        "bore_diameter",
        CustomerDecision.CORRECTED,
        customer_value=2.125,
        reason="Customer checked the print.",
    )
    changed = next(
        item for item in corrected.proposals if item.extraction_field == "bore_diameter"
    )

    assert contract.status == ConfirmationWorkflowStatus.REQUIRES_CONFIRMATION
    assert original.proposed_value == 2.0
    assert original.source_bbox == (10, 20, 30, 40)
    assert changed.proposed_value == 2.0
    assert changed.customer_value == 2.125
    assert changed.customer_decision == CustomerDecision.CORRECTED
    assert contract.proposals != corrected.proposals
    assert corrected.automatic_overwrite_permitted is False
    assert corrected.canonical_configuration_created is False
    assert corrected.pricing_invoked is False


def test_confirmation_contract_blocks_unsupported_and_requires_explicit_selection():
    recognition = _recognition(unsupported_od=True)
    contract = build_customer_confirmation_contract(
        recognition,
        document_class=DrawingDocumentClass.MULTI_PLATE_DRAWING,
        candidate_count=2,
        selected_candidate_id=None,
    )
    od = next(
        item
        for item in contract.proposals
        if item.extraction_field == "outside_diameter"
    )

    assert contract.status == ConfirmationWorkflowStatus.SELECTION_REQUIRED
    assert contract.selection_required is True
    assert od.proposed_value == 60.0
    assert od.unsupported is True
    assert contract.canonical_configuration_created is False


def test_manual_fields_are_recorded_without_constructing_or_pricing_quote_inputs():
    contract = build_customer_confirmation_contract(
        _recognition(),
        document_class=DrawingDocumentClass.SINGLE_PLATE_DRAWING,
        candidate_count=1,
        selected_candidate_id="selected",
    )
    assert {"handle_width", "handle_length_from_bore", "ships_in_days"}.issubset(
        contract.required_manual_fields
    )

    updated = record_manual_value(contract, "handle_width", 1.5)

    assert contract.completed_manual_values == {}
    assert updated.completed_manual_values == {"handle_width": 1.5}
    assert updated.canonical_configuration_created is False
    assert updated.pricing_invoked is False


def test_schedule_benchmark_keeps_provisional_annotations_out_of_verified_totals():
    common = dict(
        row_index=1,
        field_name="bore_diameter",
        expected_value=2.0,
        observed_value=2.0,
        observed_status=FieldStatus.LOW_CONFIDENCE,
        correct=True,
        source_page=1,
        source_bbox=(1, 2, 3, 4),
    )
    aggregate = _aggregate(
        [
            ScheduleFieldScore(verification_status="verified", **common),
            ScheduleFieldScore(
                verification_status="provisional",
                **{**common, "row_index": 2},
            ),
        ]
    )["bore_diameter"]

    assert aggregate.verified_total == 1
    assert aggregate.verified_correct == 1
    assert aggregate.provisional_total == 1
    assert aggregate.provisional_correct == 1
