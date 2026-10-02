import io
from dataclasses import replace

import pytest
from PIL import Image, ImageDraw

from drawing_intake.classification import (
    DrawingDocumentClass,
    classify_drawing_document,
)
from drawing_intake.deterministic import (
    EvidenceClassification,
    FieldRecognitionResult,
    _NumericCandidate,
    _resolve_marking,
    _resolve_numeric_field,
    _resolve_quantity,
    _resolve_tolerance,
)
from drawing_intake.documents import normalize_document
from drawing_intake.engineering_text import (
    ToleranceKind,
    parse_measurement,
    parse_quantity,
    parse_tolerance,
)
from drawing_intake.models import (
    CoordinateUnit,
    DocumentStatus,
    DocumentStructureAssessment,
    MeasurementUnit,
    SourceEvidence,
)
from drawing_intake.ocr import (
    LocalOcrResult,
    OcrTokenObservation,
    recover_plus_minus_glyphs,
)
from drawing_intake.regions import DerivedDrawingRegion
from drawing_intake.rendering import (
    RegionCoordinateTransform,
    RenderedRegion,
    rotate_rendered_region,
)
from drawing_intake.spatial import SpatialTextLine
from drawing_intake.table_schedule import parse_plate_schedule


def _rendered_image(image: Image.Image, *, region_id="synthetic") -> RenderedRegion:
    output = io.BytesIO()
    image.save(output, format="PNG")
    data = output.getvalue()
    region = DerivedDrawingRegion(
        region_id=region_id,
        source_group_id="synthetic-phase1c",
        source_filename="synthetic.png",
        page_number=1,
        source_bbox=(0, 0, image.width, image.height),
        candidate_bbox=(0, 0, image.width, image.height),
    )
    return RenderedRegion(
        region=region,
        dpi=150,
        width=image.width,
        height=image.height,
        transform=RegionCoordinateTransform(
            pdf_bbox=region.source_bbox,
            pixel_width=image.width,
            pixel_height=image.height,
            points_per_pixel_x=1,
            points_per_pixel_y=1,
        ),
        png_size_bytes=len(data),
        uncompressed_grayscale_bytes=image.width * image.height,
        render_seconds=0,
        png_bytes=data,
    )


def _ocr_token(region_id, raw, x, y, *, line="1"):
    return OcrTokenObservation(
        token_id=f"{region_id}:{line}:{x}:{raw}",
        region_id=region_id,
        page_number=1,
        raw_text=raw,
        engine_confidence=90,
        pixel_bbox=(x, y, x + max(8, len(raw) * 7), y + 12),
        source_bbox=(x, y, x + max(8, len(raw) * 7), y + 12),
        engine="synthetic-local-ocr",
        engine_pass="psm11",
        line_key=f"psm11:{line}",
    )


def test_compact_fraction_and_quantity_reconstruction_are_context_bound():
    repaired = parse_measurement('Y%4" THK', thickness_context=True)
    assert repaired.value == pytest.approx(0.25)
    assert "ocr_compact_fraction_slash_repair_in_thickness_context" in (
        repaired.normalization_rules
    )
    unscoped = parse_measurement('Y%4"', thickness_context=False)
    assert unscoped.value == pytest.approx(4)
    assert "ocr_compact_fraction_slash_repair_in_thickness_context" not in (
        unscoped.normalization_rules
    )
    assert parse_quantity("NO. REQ'D, ONE") == 1
    assert parse_quantity("NO. REQ 3") == 3


def test_owner_print_ocr_repairs_remain_context_bound_and_reviewable():
    outside = parse_measurement('3,625"')
    assert outside.value == pytest.approx(3.625)
    assert "ocr_decimal_comma_in_quoted_inch_dimension" in outside.normalization_rules
    assert "ocr_decimal_comma_in_quoted_inch_dimension" not in (
        parse_measurement("3,625").normalization_rules
    )

    thickness = parse_measurement("__¥4°__", thickness_context=True)
    assert thickness.value == pytest.approx(0.25)
    assert thickness.explicit_unit
    assert "ocr_compact_fraction_degree_as_inch_mark_in_thickness_context" in (
        thickness.normalization_rules
    )
    assert "ocr_compact_fraction_degree_as_inch_mark_in_thickness_context" not in (
        parse_measurement("__¥4°__").normalization_rules
    )
    assert parse_quantity("NO, REQ. TWO") == 2


def test_clipped_targeted_od_observation_does_not_override_base_reading():
    candidates = [
        _NumericCandidate(
            value=3.625,
            unit=MeasurementUnit.INCH,
            raw_text='3,625" DIA.',
            source=SourceEvidence(
                page_number=1, bbox=(100, 100, 160, 120), extraction_method="synthetic"
            ),
            token_ids=(pass_name,),
            engine_pass=pass_name,
            normalization_rules=("ocr_decimal_comma_in_quoted_inch_dimension",),
        )
        for pass_name in ("psm6", "psm11")
    ] + [
        _NumericCandidate(
            value=625.0,
            unit=MeasurementUnit.INCH,
            raw_text='625" DIA.',
            source=SourceEvidence(
                page_number=1, bbox=(106, 100, 160, 120), extraction_method="synthetic"
            ),
            token_ids=(pass_name,),
            engine_pass=f"target.outside.raw.{pass_name}",
            normalization_rules=("targeted_callout_ocr",),
        )
        for pass_name in ("psm6", "psm11")
    ]
    result = _resolve_numeric_field("outside_diameter", candidates)
    assert result.value == pytest.approx(3.625)
    assert result.evidence_classification == "requires_confirmation"
    assert result.status == "low_confidence"

    conflicting = candidates[:2] + [
        replace(candidate, raw_text='999" DIA.', value=999.0)
        for candidate in candidates[2:]
    ]
    assert _resolve_numeric_field("outside_diameter", conflicting).status == "ambiguous"


def test_quantity_and_generic_stamping_instruction_are_kept_separate():
    def line(raw):
        token = _ocr_token("synthetic", raw, 10, 10)
        return SpatialTextLine(
            region_id="synthetic",
            page_number=1,
            engine_pass="psm11",
            line_key=token.line_key,
            raw_text=raw,
            normalized_text=raw,
            source_coordinate_unit=CoordinateUnit.PDF_POINT,
            bbox=token.source_bbox,
            token_ids=[token.token_id],
            tokens=[token],
        )

    assert _resolve_quantity([line("NO, REQ. TWO")]).value == 2
    marking = _resolve_marking([line('STAMP WITH 1/4" LETTERS')])
    assert marking.status == "ambiguous"
    assert marking.value is None
    assert marking.raw_text == 'STAMP WITH 1/4" LETTERS'


def test_incomplete_tolerance_remains_unilateral_and_does_not_invent_symmetry():
    parsed = parse_tolerance("BORE +0.005")
    assert parsed.kind == ToleranceKind.UNILATERAL
    assert parsed.plus == pytest.approx(0.005)
    assert parsed.minus is None
    assert parse_tolerance("BORE £0.005") is None


def test_targeted_variants_cannot_promote_single_base_observation_to_strong():
    source = SourceEvidence(page_number=1, extraction_method="synthetic")
    candidates = [
        _NumericCandidate(
            value=1.5,
            unit=MeasurementUnit.INCH,
            raw_text="1.500 BORE",
            source=source,
            token_ids=("base",),
            engine_pass="psm6",
            normalization_rules=(),
        ),
        _NumericCandidate(
            value=1.5,
            unit=MeasurementUnit.INCH,
            raw_text="1.500 BORE",
            source=source,
            token_ids=("target-raw",),
            engine_pass="target.bore.raw.psm6",
            normalization_rules=("targeted_callout_ocr",),
        ),
        _NumericCandidate(
            value=1.5,
            unit=MeasurementUnit.INCH,
            raw_text="1.500 BORE",
            source=source,
            token_ids=("target-otsu",),
            engine_pass="target.bore.otsu.psm11",
            normalization_rules=(
                "targeted_callout_ocr",
                "otsu_threshold_preprocessing",
            ),
        ),
    ]
    result = _resolve_numeric_field("bore_diameter", candidates, geometry_support=True)
    assert result.evidence_classification == "requires_confirmation"
    assert result.status == "low_confidence"


def test_tolerance_sides_resolve_independently_when_symmetry_is_uncertain():
    symmetric_token = _ocr_token("region", "BORE ±0.005", 10, 10, line="sym")
    unilateral_token = _ocr_token("region", "BORE +0.005", 10, 30, line="uni")
    lines = [
        SpatialTextLine(
            region_id="region",
            page_number=1,
            engine_pass=token.engine_pass,
            line_key=token.line_key,
            raw_text=token.raw_text,
            normalized_text=token.raw_text,
            source_coordinate_unit=CoordinateUnit.PDF_POINT,
            bbox=token.source_bbox,
            token_ids=[token.token_id],
            tokens=[token],
        )
        for token in (symmetric_token, unilateral_token)
    ]
    bore = FieldRecognitionResult(
        field_name="bore_diameter",
        value=1.5,
        status="detected",
        evidence_classification=EvidenceClassification.STRONG,
    )
    plus, minus = _resolve_tolerance(lines, bore)
    assert plus.value == pytest.approx(0.005)
    assert plus.evidence_classification == "requires_confirmation"
    assert minus.value is None
    assert minus.status == "ambiguous"
    assert minus.abstention_reason == "tolerance_side_incompletely_observed"


@pytest.mark.parametrize("second_bar,expected", [(True, "±0.005"), (False, None)])
def test_plus_minus_recovery_requires_two_separated_horizontal_bands(
    second_bar, expected
):
    image = Image.new("L", (140, 50), 255)
    draw = ImageDraw.Draw(image)
    draw.line((15, 8, 15, 26), fill=0, width=2)
    draw.line((8, 15, 22, 15), fill=0, width=2)
    if second_bar:
        draw.line((8, 24, 22, 24), fill=0, width=2)
    rendered = _rendered_image(image)
    sign = _ocr_token("synthetic", "+0.005", 7, 7, line="tol")
    sign = sign.model_copy(update={"pixel_bbox": (7, 7, 50, 30)})
    bore = _ocr_token("synthetic", "BORE", 65, 10, line="tol")
    result = LocalOcrResult(
        engine="synthetic",
        engine_version="test",
        region_id="synthetic",
        dpi=150,
        page_segmentation_modes=[11],
        tokens=[sign, bore],
        ocr_seconds=0,
    )
    recovered = recover_plus_minus_glyphs(result, rendered).tokens[0]
    assert recovered.normalized_text == expected
    if expected:
        assert "two_horizontal_bands_plus_minus_glyph" in (
            recovered.normalization_rules
        )


def test_rotated_page_observations_map_back_to_original_source_coordinates():
    rendered = _rendered_image(Image.new("L", (100, 50), 255))
    rotated = rotate_rendered_region(rendered, 90)
    assert (rotated.width, rotated.height) == (50, 100)
    assert rotated.transform.pixel_bbox_to_pdf((0, 0, 50, 100)) == pytest.approx(
        rendered.region.source_bbox
    )
    corner = rotated.transform.pixel_bbox_to_pdf((0, 0, 10, 10))
    assert corner == pytest.approx((90, 0, 100, 10))


def _synthetic_table(offset_x: int):
    width, height = 760 + offset_x, 240
    image = Image.new("L", (width, height), 255)
    draw = ImageDraw.Draw(image)
    verticals = [offset_x + value for value in (20, 120, 190, 280, 360, 450, 550)]
    horizontals = [60, 100, 140, 180]
    for y in horizontals:
        draw.line((verticals[0], y, verticals[-1], y), fill=0, width=2)
    for x in verticals:
        draw.line((x, horizontals[0], x, horizontals[-1]), fill=0, width=2)
    rendered = _rendered_image(image, region_id=f"table-{offset_x}")
    tokens = []

    def add(raw, x, y, line):
        tokens.append(_ocr_token(rendered.region.region_id, raw, x, y, line=line))

    add("ORIFICE", verticals[2] + 5, 35, "section")
    add("PLATE", verticals[2] + 75, 35, "section")
    add("DIM", verticals[2] + 120, 35, "section")
    add("DESIGN", verticals[-1] + 8, 35, "section")
    for raw, column in (("TAG", 0), ("QTY", 1), ("O.D.", 2), ("THK", 3), ("BORE", 4)):
        add(raw, verticals[column] + 8, 74, "header")
    add("ORIFICE", 20 + offset_x, 205, "material")
    add("PLATE", 95 + offset_x, 205, "material")
    add("S.S.-316", 160 + offset_x, 205, "material")
    add("ALL", 300 + offset_x, 205, "units")
    add("DIMENSIONS", 335 + offset_x, 205, "units")
    add("IN", 430 + offset_x, 205, "units")
    add("M.M.", 450 + offset_x, 205, "units")
    rows = (
        ("P-1", "2", "406.4", "6", "162.08", "±0.08"),
        ("P-2", "1", "276.1", "6", "115.75", "+0.06/-0.00"),
    )
    for index, values in enumerate(rows):
        y = 112 + index * 40
        for column, value in enumerate(values):
            add(value, verticals[column] + 8, y, f"row{index}")
    result = LocalOcrResult(
        engine="synthetic",
        engine_version="test",
        region_id=rendered.region.region_id,
        dpi=150,
        page_segmentation_modes=[11],
        tokens=tokens,
        ocr_seconds=0,
    )
    return rendered, result


@pytest.mark.parametrize("offset_x", [0, 137])
def test_generic_table_binding_handles_shifted_coordinates_and_never_selects_row(
    offset_x,
):
    rendered, ocr = _synthetic_table(offset_x)
    schedule = parse_plate_schedule(rendered, ocr)
    assert len(schedule.candidates) == 2
    assert schedule.candidates[0].outside_diameter.value == pytest.approx(406.4)
    assert schedule.candidates[0].thickness.value == pytest.approx(6)
    assert schedule.candidates[0].bore_diameter.value == pytest.approx(162.08)
    assert schedule.candidates[0].bore_tolerance_minus.value == pytest.approx(0.08)
    assert schedule.candidates[1].bore_tolerance_plus.value == pytest.approx(0.06)
    assert schedule.candidates[1].bore_tolerance_minus.value == pytest.approx(0)
    assert schedule.candidates[0].material.value == "316"
    assert schedule.candidates[0].global_units.value == "mm"
    assert all(
        getattr(schedule.candidates[0], field).status != "detected"
        for field in (
            "outside_diameter",
            "thickness",
            "bore_diameter",
            "bore_tolerance_plus",
            "bore_tolerance_minus",
            "material",
            "global_units",
        )
    )
    assert schedule.quote_candidate_created is False


@pytest.mark.parametrize("filename", ["reference-a.jpg", "renamed-without-vendor.jpg"])
def test_reference_document_classification_has_no_vendor_or_filename_dependency(
    filename,
):
    image = Image.new("L", (100, 100), 255)
    output = io.BytesIO()
    image.save(output, format="JPEG")
    document = normalize_document(output.getvalue(), filename)
    structure = DocumentStructureAssessment(status=DocumentStatus.UNKNOWN)
    result = classify_drawing_document(
        document,
        structure,
        observed_text=(
            "CAT NO A100 PADDLE ORIFICE PLATE UNIVERSAL TYPE ORIFICE PLATE "
            "d = ORIFICE BORE DIAMETER E = ORIFICE PLATE THICKNESS SIZE SELECTION"
        ),
        detected_table_rows=8,
    )
    assert result.document_class == DrawingDocumentClass.REFERENCE_VENDOR_DATASHEET
    assert result.quote_specific is False
