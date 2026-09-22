import io
import shutil

import pytest
from reportlab.lib.pagesizes import landscape, letter
from reportlab.pdfgen import canvas

from drawing_intake.deterministic import (
    DeterministicRegionRecognizer,
    EvidenceClassification,
    interpret_precomputed_region,
)
from drawing_intake.documents import normalize_document
from drawing_intake.engineering_text import (
    ToleranceKind,
    normalize_engineering_text,
    parse_chamfer_notation,
    parse_material,
    parse_measurement,
    parse_tolerance,
)
from drawing_intake.models import FieldStatus, MeasurementUnit
from drawing_intake.ocr import (
    LocalOcrResult,
    OcrTokenObservation,
    TesseractLocalOcrEngine,
)
from drawing_intake.pipeline import DrawingIntakePipeline
from drawing_intake.providers import NativeTextExtractionProvider
from drawing_intake.regions import derive_candidate_regions
from drawing_intake.rendering import render_region_png
from drawing_intake.spatial import nearest_same_region_token
from drawing_intake.structure import assess_document_structure
from drawing_intake.validation import validate_extraction
from drawing_intake.value_normalization import to_inches


def drawing_pdf(*, centers=((300, 300),), text=True) -> bytes:
    output = io.BytesIO()
    pdf = canvas.Canvas(output, pagesize=landscape(letter))
    for center_x, center_y in centers:
        for radius in (45, 30, 15):
            pdf.circle(center_x, center_y, radius)
        if text:
            pdf.setFont("Helvetica", 12)
            rows = (
                (85, "1.500 IN BORE +/- .005 IN"),
                (65, "5.000 IN DIA"),
                (45, ".250 IN THK"),
                (-70, "MATERIAL: 304 SS"),
                (-90, "QTY: 2"),
            )
            for offset, value in rows:
                pdf.drawString(center_x - 100, center_y + offset, value)
    pdf.showPage()
    pdf.save()
    return output.getvalue()


def single_region_document(*, center=(300, 300)):
    document = normalize_document(
        drawing_pdf(centers=(center,), text=False), "test.pdf"
    )
    structure = assess_document_structure(document)
    region = derive_candidate_regions(
        document, structure, source_group_id="synthetic-test"
    )[0]
    return document, region


def token(region, raw, x, y, *, engine_pass="psm6", line="1", region_id=None):
    source_x = region.source_bbox[0] + x
    source_y = region.source_bbox[1] + y
    return OcrTokenObservation(
        token_id=f"{region_id or region.region_id}:{engine_pass}:{line}:{x}:{raw}",
        region_id=region_id or region.region_id,
        page_number=region.page_number,
        raw_text=raw,
        engine_confidence=90.0,
        pixel_bbox=(int(x * 4), int(y * 4), int((x + 10) * 4), int((y + 5) * 4)),
        source_bbox=(source_x, source_y, source_x + 10, source_y + 5),
        engine="synthetic-local-ocr",
        engine_pass=engine_pass,
        line_key=f"{engine_pass}:{line}",
    )


def field_tokens(region, *, bore='1.500"', od='5.000"', material="304 SS"):
    output = []
    for engine_pass in ("psm6", "psm11"):
        output.extend(
            [
                token(region, bore, 10, 10, engine_pass=engine_pass, line="bore"),
                token(region, "BORE", 22, 10, engine_pass=engine_pass, line="bore"),
                token(region, "±", 34, 10, engine_pass=engine_pass, line="bore"),
                token(region, '.005"', 40, 10, engine_pass=engine_pass, line="bore"),
                token(region, od, 10, 30, engine_pass=engine_pass, line="od"),
                token(region, "DIA", 22, 30, engine_pass=engine_pass, line="od"),
                token(region, '.250"', 10, 50, engine_pass=engine_pass, line="thk"),
                token(region, "THK", 22, 50, engine_pass=engine_pass, line="thk"),
                token(region, material, 10, 70, engine_pass=engine_pass, line="mat"),
                token(region, "QTY", 10, 90, engine_pass=engine_pass, line="qty"),
                token(region, "2", 22, 90, engine_pass=engine_pass, line="qty"),
            ]
        )
    return output


def ocr_result(region, tokens):
    return LocalOcrResult(
        engine="synthetic-local-ocr",
        engine_version="test",
        region_id=region.region_id,
        dpi=300,
        page_segmentation_modes=[6, 11],
        tokens=tokens,
        ocr_seconds=0.0,
    )


def test_engineering_measurement_grammar_handles_decimals_fractions_metric_and_diameter():
    assert parse_measurement(".250 THK").value == pytest.approx(0.25)
    assert parse_measurement("1/4 IN").value == pytest.approx(0.25)
    assert parse_measurement('1 9/16"').value == pytest.approx(1.5625)
    diameter = parse_measurement("Ø1.564")
    assert diameter.value == pytest.approx(1.564)
    metric = parse_measurement("25.4 MM")
    assert metric.unit == MeasurementUnit.MILLIMETER
    assert to_inches(metric.value, metric.unit) == pytest.approx(1.0)


def test_tolerance_grammar_handles_symmetric_bilateral_unilateral_and_limits():
    symmetric = parse_tolerance("BORE ± .005 IN")
    assert symmetric.kind == ToleranceKind.SYMMETRIC
    assert symmetric.plus == symmetric.minus == pytest.approx(0.005)

    bilateral = parse_tolerance("+.002 / -.000")
    assert bilateral.kind == ToleranceKind.BILATERAL
    assert bilateral.plus == pytest.approx(0.002)
    assert bilateral.minus == pytest.approx(0.0)

    unilateral = parse_tolerance("+.003")
    assert unilateral.kind == ToleranceKind.UNILATERAL
    assert unilateral.plus == pytest.approx(0.003)
    assert unilateral.minus is None

    limits = parse_tolerance("1.502 / 1.500")
    assert limits.kind == ToleranceKind.LIMITS
    assert limits.upper_limit == pytest.approx(1.502)
    assert limits.lower_limit == pytest.approx(1.5)


def test_material_chamfer_and_ocr_confusion_normalization_are_contextual():
    assert parse_material("304 STAINLESS STEEL") == "304"
    assert parse_material("SS 316") == "316"
    assert parse_material("CARBON STEEL") == "Carbon Steel"
    assert parse_material("HASTELLOY C276") == "HASTELLOY C276"

    repaired = normalize_engineering_text('O.OO5"', numeric_context=True)
    assert repaired.normalized_text == '0.005"'
    assert (
        "ocr_alphanumeric_to_numeric_in_numeric_context" in repaired.normalization_rules
    )
    assert (
        normalize_engineering_text("O-RING", numeric_context=False).normalized_text
        == "O-RING"
    )

    chamfer = parse_chamfer_notation(".060 X 45°", default_unit=MeasurementUnit.INCH)
    assert chamfer.width_or_depth == pytest.approx(0.06)
    assert chamfer.angle_degrees == pytest.approx(45.0)


def test_spatial_lookup_requires_same_region_and_supports_adjacent_tokens():
    _, region = single_region_document()
    label = token(region, "BORE", 20, 20)
    local_value = token(region, '1.500"', 8, 20)
    other_value = token(region, '9.999"', 19, 20, region_id="other-region")

    nearest = nearest_same_region_token(
        label,
        [local_value, other_value],
        maximum_distance=30,
        require_same_line=True,
    )
    assert nearest.token_id == local_value.token_id


def test_deterministic_field_rules_produce_verified_values_and_provenance():
    document, region = single_region_document()
    fields, extraction = interpret_precomputed_region(
        document, region, ocr_result(region, field_tokens(region))
    )

    assert fields["bore_diameter"].value == pytest.approx(1.5)
    assert fields["bore_diameter"].evidence_classification == "verified"
    assert fields["outside_diameter"].value == pytest.approx(5.0)
    assert fields["outside_diameter"].evidence_classification == "verified"
    assert fields["thickness"].value == pytest.approx(0.25)
    assert fields["material"].value == "304"
    assert fields["bore_tolerance_plus"].value == pytest.approx(0.005)
    assert fields["bore_tolerance_minus"].value == pytest.approx(0.005)
    assert extraction.fields.bore_diameter.evidence[0].bbox is not None
    assert extraction.provider_data_handling.external_service is False


def test_cross_region_values_cannot_bind_to_selected_region():
    document, region = single_region_document()
    selected_label = token(region, "BORE", 20, 20)
    foreign_value = token(
        region, '1.500"', 8, 20, region_id="different-selected-region"
    )
    fields, _ = interpret_precomputed_region(
        document, region, ocr_result(region, [selected_label, foreign_value])
    )

    assert fields["bore_diameter"].status == FieldStatus.NOT_DETECTED
    assert fields["bore_diameter"].value is None


def test_equally_supported_critical_candidates_abstain_as_ambiguous():
    document, region = single_region_document()
    tokens = []
    for engine_pass in ("psm6", "psm11"):
        tokens.extend(
            [
                token(region, '1.500"', 10, 10, engine_pass=engine_pass, line="a"),
                token(region, "BORE", 22, 10, engine_pass=engine_pass, line="a"),
                token(region, '1.600"', 10, 40, engine_pass=engine_pass, line="b"),
                token(region, "BORE", 22, 40, engine_pass=engine_pass, line="b"),
            ]
        )
    fields, _ = interpret_precomputed_region(
        document, region, ocr_result(region, tokens)
    )

    assert fields["bore_diameter"].status == FieldStatus.AMBIGUOUS
    assert fields["bore_diameter"].value is None
    assert fields["bore_diameter"].evidence_classification == "ambiguous"


def test_bore_od_relationship_and_unsupported_domain_values_stay_separate():
    document, region = single_region_document()
    fields, extraction = interpret_precomputed_region(
        document,
        region,
        ocr_result(
            region,
            field_tokens(
                region, bore='61.000"', od='60.000"', material="HASTELLOY C276"
            ),
        ),
    )
    validation = validate_extraction(extraction)

    assert fields["outside_diameter"].value == pytest.approx(60.0)
    assert fields["material"].value == "HASTELLOY C276"
    assert fields["outside_diameter"].evidence_classification == "requires_confirmation"
    assert {issue.code for issue in validation.issues} >= {
        "outside_diameter_out_of_envelope",
        "bore_diameter_out_of_envelope",
        "bore_not_smaller_than_od",
        "unsupported_material",
    }
    assert validation.canonical_candidate.paddle_dia is None
    assert validation.extraction.fields.material.value == "HASTELLOY C276"


def test_missing_values_are_not_invented():
    document, region = single_region_document()
    fields, extraction = interpret_precomputed_region(
        document, region, ocr_result(region, [])
    )

    assert fields["bore_diameter"].status == FieldStatus.NOT_DETECTED
    assert extraction.fields.bore_diameter.value is None
    assert fields["bore_diameter"].abstention_reason


def test_derived_regions_are_neighbor_based_and_coordinate_independent():
    left_document, left_region = single_region_document(center=(200, 300))
    right_document, right_region = single_region_document(center=(550, 300))

    assert left_region.classification == "derived_real_region"
    assert left_region.source_bbox != right_region.source_bbox
    for document, region, expected_x in (
        (left_document, left_region, 200),
        (right_document, right_region, 550),
    ):
        assert region.source_bbox[0] < expected_x < region.source_bbox[2]
        assert region.page_number == 1
        assert region.source_filename == document.filename


def test_multi_part_whole_page_remains_blocked_and_cannot_select_one_candidate():
    data = drawing_pdf(centers=((200, 300), (550, 300)))
    result = DrawingIntakePipeline(NativeTextExtractionProvider()).process(
        data, "multi.pdf"
    )

    assert result.structure.status == "multiple_candidates"
    assert result.structure.candidate_region_count == 2
    assert result.validation.canonical_candidate.paddle_dia is None
    assert result.validation.canonical_candidate.source_fields == {}
    assert "unsupported_multi_part_sheet" in {
        issue.code for issue in result.validation.issues
    }


def test_region_rendering_scale_and_coordinate_transform_are_traceable():
    document, region = single_region_document()
    at_300 = render_region_png(document, region, dpi=300)
    at_600 = render_region_png(document, region, dpi=600)

    assert at_600.width == pytest.approx(at_300.width * 2, abs=2)
    assert at_600.height == pytest.approx(at_300.height * 2, abs=2)
    assert at_300.transform.pdf_bbox == region.source_bbox
    mapped = at_300.transform.pixel_bbox_to_pdf((0, 0, at_300.width, at_300.height))
    assert mapped == pytest.approx(region.source_bbox)
    assert at_300.png_bytes.startswith(b"\x89PNG")


@pytest.mark.skipif(shutil.which("tesseract") is None, reason="Tesseract not installed")
def test_local_tesseract_returns_word_boxes_mapped_to_original_pdf_region():
    document = normalize_document(drawing_pdf(), "ocr-local.pdf")
    region = derive_candidate_regions(
        document,
        assess_document_structure(document),
        source_group_id="synthetic-local-ocr",
    )[0]
    rendered = render_region_png(document, region, dpi=300)
    result = TesseractLocalOcrEngine(page_segmentation_modes=(11,)).recognize(rendered)

    assert result.engine == "tesseract_tsv_local"
    assert any("BORE" in item.raw_text.upper() for item in result.tokens)
    assert all(item.region_id == region.region_id for item in result.tokens)
    assert all(
        region.source_bbox[0] <= item.source_bbox[0] <= region.source_bbox[2]
        and region.source_bbox[1] <= item.source_bbox[1] <= region.source_bbox[3]
        for item in result.tokens
    )


@pytest.mark.parametrize("center", [(220, 300), (520, 300)])
@pytest.mark.skipif(shutil.which("tesseract") is None, reason="Tesseract not installed")
def test_local_end_to_end_region_recognition_has_no_fixed_coordinate_dependency(center):
    document = normalize_document(
        drawing_pdf(centers=(center,)), f"shifted-{center[0]}.pdf"
    )
    region = derive_candidate_regions(
        document,
        assess_document_structure(document),
        source_group_id="shifted-synthetic",
    )[0]
    result = DeterministicRegionRecognizer().recognize(document, region)

    assert result.field_results["bore_diameter"].value == pytest.approx(1.5)
    assert result.field_results["outside_diameter"].value == pytest.approx(5.0)
    assert result.field_results["material"].value == "304"
    assert result.field_results["quantity"].value == 2
    assert result.validation.extraction == result.extraction
    assert result.validation.canonical_candidate.paddle_dia == pytest.approx(5.0)
    assert result.field_results["global_units"].value == "in"
    assert result.field_results["bore_tolerance_plus"].value == pytest.approx(0.005)
    assert result.field_results["bore_tolerance_minus"].value == pytest.approx(0.005)
