import io

import pytest
from PIL import Image, ImageDraw

from drawing_intake.classification import (
    DocumentClassificationResult,
    DrawingDocumentClass,
)
from drawing_intake.corpus_audit import score_field_result
from drawing_intake.deterministic import EvidenceClassification, FieldRecognitionResult
from drawing_intake.document_recognition import (
    DeterministicDocumentRecognitionResult,
    DocumentRecognitionTimings,
)
from drawing_intake.documents import normalize_document
from drawing_intake.models import (
    DocumentReference,
    DocumentStatus,
    DocumentStructureAssessment,
    DrawingExtractionResult,
    DrawingFields,
    FieldStatus,
    MeasurementUnit,
    NumericField,
    ProviderDataHandling,
    StringField,
    UnitField,
)
from drawing_intake.raster_structure import detect_raster_plate_structure
from drawing_intake.reconciliation_workflow import (
    ReconciliationEntryStatus,
    ReconciliationReviewStatus,
    assess_reconciliation_entry,
    build_reconciliation_review,
)
from drawing_intake.regions import DerivedDrawingRegion
from drawing_intake.rendering import render_region_png
from drawing_intake.validation import validate_extraction


def _drawing_image(centers):
    image = Image.new("L", (900, 440), 255)
    draw = ImageDraw.Draw(image)
    for center_x, center_y in centers:
        draw.line((center_x - 100, center_y, center_x + 100, center_y), fill=0, width=2)
        draw.line((center_x, center_y - 100, center_x, center_y + 100), fill=0, width=2)
        draw.ellipse(
            (center_x - 68, center_y - 68, center_x + 68, center_y + 68),
            outline=0,
            width=3,
        )
        draw.ellipse(
            (center_x - 34, center_y - 34, center_x + 34, center_y + 34),
            outline=0,
            width=3,
        )
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def _full_page_render(data):
    document = normalize_document(data, "shifted-raster.png")
    page = document.pages[0]
    region = DerivedDrawingRegion(
        region_id="full-page",
        source_group_id="synthetic-phase1d",
        source_filename=document.filename,
        page_number=1,
        source_bbox=(0, 0, page.width, page.height),
        candidate_bbox=(0, 0, page.width, page.height),
        coordinate_unit=page.coordinate_unit,
        derivation_method="synthetic_full_page",
    )
    return document, region, render_region_png(document, region, dpi=96)


@pytest.mark.parametrize(
    "centers", [((220, 210), (650, 210)), ((180, 190), (570, 240))]
)
def test_raster_profile_detection_is_coordinate_independent_and_multi_part_safe(
    centers,
):
    _, _, rendered = _full_page_render(_drawing_image(centers))

    structure = detect_raster_plate_structure(rendered)

    assert structure.status == DocumentStatus.MULTIPLE_CANDIDATES
    assert structure.candidate_region_count == 2
    detected_centers = [
        ((item.bbox[0] + item.bbox[2]) / 2, (item.bbox[1] + item.bbox[3]) / 2)
        for item in structure.candidate_regions
    ]
    assert sorted(detected_centers) == pytest.approx(sorted(centers), abs=4)
    assert all(
        item.detection_method == "raster_centerline_plus_two_concentric_perimeters_v1"
        for item in structure.candidate_regions
    )


def test_raster_resampling_preserves_original_pixel_coordinate_mapping():
    document, region, at_96 = _full_page_render(_drawing_image(((300, 210),)))
    at_192 = render_region_png(document, region, dpi=192)

    assert at_192.width == at_96.width * 2
    assert at_192.height == at_96.height * 2
    assert at_192.transform.pixel_bbox_to_pdf(
        (0, 0, at_192.width, at_192.height)
    ) == pytest.approx(region.source_bbox)


def _document_result(document_class, *, quote_specific, candidate_count):
    status = (
        DocumentStatus.MULTIPLE_CANDIDATES
        if candidate_count and candidate_count > 1
        else DocumentStatus.UNKNOWN
    )
    return DeterministicDocumentRecognitionResult(
        structure=DocumentStructureAssessment(
            status=status,
            candidate_region_count=candidate_count,
        ),
        classification=DocumentClassificationResult(
            document_class=document_class,
            quote_specific=quote_specific,
            candidate_count=candidate_count,
            reason="synthetic",
        ),
        page_rotation_degrees=0,
        ocr_token_count=0,
        timings=DocumentRecognitionTimings(
            classification_seconds=0,
            rendering_and_ocr_seconds=0,
            table_interpretation_seconds=0,
            total_seconds=0,
        ),
    )


def test_reference_document_and_multi_candidate_document_cannot_enter_reconciliation():
    reference = _document_result(
        DrawingDocumentClass.REFERENCE_VENDOR_DATASHEET,
        quote_specific=False,
        candidate_count=None,
    )
    multi = _document_result(
        DrawingDocumentClass.MULTI_PLATE_DRAWING,
        quote_specific=True,
        candidate_count=2,
    )

    reference_gate = assess_reconciliation_entry(reference)
    multi_gate = assess_reconciliation_entry(multi)

    assert reference_gate.status == ReconciliationEntryStatus.NOT_QUOTE_SPECIFIC
    assert multi_gate.status == ReconciliationEntryStatus.SELECTION_REQUIRED
    assert reference_gate.canonical_candidate_created is False
    assert multi_gate.automatic_candidate_selection_permitted is False


def _number(value, *, status=FieldStatus.DETECTED):
    return NumericField(
        value=value,
        normalized_unit=MeasurementUnit.INCH,
        status=status,
    )


def _validation(*, bore=2.0, bore_status=FieldStatus.DETECTED, od=8.0):
    extraction = DrawingExtractionResult(
        document=DocumentReference(
            filename="selected.png",
            media_type="image/png",
            sha256="0" * 64,
            page_count=1,
        ),
        provider_name="deterministic-test",
        provider_data_handling=ProviderDataHandling(
            external_service=False,
            retention="none",
            sends_document_content=False,
        ),
        fields=DrawingFields(
            outside_diameter=_number(od),
            bore_diameter=_number(bore, status=bore_status),
            thickness=_number(0.125),
            material=StringField(value="304", status=FieldStatus.DETECTED),
            global_units=UnitField(
                value="in",
                normalized_unit=MeasurementUnit.INCH,
                status=FieldStatus.DETECTED,
            ),
            bore_tolerance_plus=_number(0.005),
            bore_tolerance_minus=_number(0.005),
        ),
    )
    return validate_extraction(extraction)


def _config(**updates):
    values = {
        "quantity": 1,
        "material": "304",
        "thickness": 0.125,
        "paddle_dia": 8.0,
        "bore_dia": 2.0,
        "bore_tolerance": 0.005,
        "chamfer": False,
    }
    values.update(updates)
    return values


def _strong_evidence():
    return {
        name: "strong"
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


def test_selected_candidate_reconciliation_matches_without_mutation_or_pricing():
    config = _config()
    before = dict(config)

    review = build_reconciliation_review(
        _validation(),
        config,
        selected_candidate_id="p1-r1-c1",
        evidence_by_field=_strong_evidence(),
    )

    assert review.status == ReconciliationReviewStatus.MATCH
    assert review.critical_mismatches == []
    assert review.critical_unknowns == []
    assert review.automatic_overwrite_permitted is False
    assert review.pricing_invoked is False
    assert config == before


def test_reconciliation_surfaces_mismatch_and_confirmation_only_observation():
    mismatch = build_reconciliation_review(
        _validation(),
        _config(bore_dia=2.5),
        selected_candidate_id="selected",
        evidence_by_field=_strong_evidence(),
    )
    confirmation_evidence = _strong_evidence()
    confirmation_evidence["bore_diameter"] = "requires_confirmation"
    confirmation = build_reconciliation_review(
        _validation(bore_status=FieldStatus.LOW_CONFIDENCE),
        _config(),
        selected_candidate_id="selected",
        evidence_by_field=confirmation_evidence,
    )

    assert mismatch.status == ReconciliationReviewStatus.REQUIRES_RESOLUTION
    assert mismatch.critical_mismatches == ["bore_diameter"]
    assert confirmation.status == ReconciliationReviewStatus.REQUIRES_RESOLUTION
    assert confirmation.confirmation_required == ["bore_diameter"]


def test_unsupported_critical_value_blocks_reconciliation_without_substitution():
    review = build_reconciliation_review(
        _validation(od=60.0),
        _config(paddle_dia=48.0),
        selected_candidate_id="selected",
        evidence_by_field=_strong_evidence(),
    )

    assert review.status == ReconciliationReviewStatus.BLOCKED
    assert review.critical_unsupported == ["outside_diameter"]
    comparison = next(
        item
        for item in review.comparison.comparisons
        if item.extraction_field == "outside_diameter"
    )
    assert comparison.drawing_value == 60.0
    assert comparison.customer_value == 48.0


def test_corpus_safety_metric_counts_only_wrong_authoritative_critical_values():
    wrong_strong = score_field_result(
        "bore_diameter",
        1.5,
        FieldRecognitionResult(
            field_name="bore_diameter",
            value=2.0,
            status=FieldStatus.DETECTED,
            evidence_classification=EvidenceClassification.STRONG,
        ),
    )
    wrong_confirmation = score_field_result(
        "bore_diameter",
        1.5,
        FieldRecognitionResult(
            field_name="bore_diameter",
            value=2.0,
            status=FieldStatus.LOW_CONFIDENCE,
            evidence_classification=EvidenceClassification.REQUIRES_CONFIRMATION,
        ),
    )
    wrong_secondary = score_field_result(
        "quantity",
        2,
        FieldRecognitionResult(
            field_name="quantity",
            value=3,
            status=FieldStatus.DETECTED,
            evidence_classification=EvidenceClassification.STRONG,
        ),
    )

    assert wrong_strong.wrong_authoritative is True
    assert wrong_confirmation.wrong_authoritative is False
    assert wrong_secondary.wrong_authoritative is False
