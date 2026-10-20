"""Synthetic, customer-free regressions for cropped industrial details."""

import io
import pytest
from PIL import Image, ImageDraw, ImageFont
from drawing_intake.documents import normalize_document
from drawing_intake.regions import DerivedDrawingRegion
from drawing_intake.rendering import render_region_png
from drawing_intake.ocr import LocalOcrResult, OcrTokenObservation
from drawing_intake.cropped_detail import observations
from drawing_intake.engineering_text import parse_measurement, parse_material
from drawing_intake.deterministic import interpret_precomputed_region
from drawing_intake.classification import classify_drawing_document
from drawing_intake.models import DocumentStructureAssessment, CandidateRegionHint


def detail(*, bore=1.25, bore_text='1-1/4"', thickness='1/4"', od=4.125, tag="SYN-100"):
    im = Image.new("RGB", (950, 400), "white")
    d = ImageDraw.Draw(im)
    font = ImageFont.truetype("DejaVuSans.ttf", 17)
    # Long horizontal handle, short center marks, concentric perimeters.
    d.ellipse((508, 68, 772, 332), outline="black", width=2)
    d.rectangle((125, 168, 516, 232), fill="white")
    d.line((125, 168, 512, 168), fill="black", width=2)
    d.line((125, 232, 512, 232), fill="black", width=2)
    d.line((125, 168, 125, 276), fill="black", width=2)
    rad = bore / 4.125 * 132
    d.ellipse((640 - rad, 200 - rad, 640 + rad, 200 + rad), outline="black", width=2)
    d.ellipse((162, 188, 186, 212), outline="black", width=2)
    d.line((632, 200, 648, 200), fill="black", width=2)
    d.line((640, 192, 640, 278), fill="black", width=2)
    d.line((174, 200, 174, 262), fill="black", width=2)
    d.line((47, 168, 47, 232), fill="black", width=2)
    d.line((37, 168, 125, 168), fill="black", width=2)
    d.line((37, 232, 125, 232), fill="black", width=2)
    d.line((125, 250, 210, 250), fill="black", width=2)
    d.line((125, 275, 345, 275), fill="black", width=2)
    d.line((405, 275, 640, 275), fill="black", width=2)
    toks = []

    def text(raw, x, y, *, diameter=False, engine_pass="psm11"):
        display = raw
        if diameter:
            # Explicit crossed circular glyph. OCR snapshot misreads it as 9.
            d.ellipse((x, y + 1, x + 10, y + 13), outline="black", width=1)
            d.line((x, y + 14, x + 11, y), fill="black", width=1)
            display = raw[1:]
            d.text((x + 13, y - 3), display, font=font, fill="black")
            w = 13 + d.textlength(display, font=font)
        else:
            d.text((x, y - 3), raw, font=font, fill="black")
            w = d.textlength(raw, font=font)
        box = (x, y, x + w, y + 14)
        toks.append((raw, box, engine_pass))
        return box

    a = text("9" + f"{od:.4f}", 440, 28, diameter=True)
    d.line((a[2] + 5, 35, a[2] + 30, 35, 560, 108), fill="black", width=2)
    b = text("9" + f"{bore:.4f}", 415, 98, diameter=True)
    d.line(
        (b[2] + 5, 105, b[2] + 30, 105, 640 - rad * 0.7, 200 - rad * 0.7),
        fill="black",
        width=2,
    )
    a = text("90.3750", 265, 98, diameter=True)
    d.line((a[0] - 20, 105, a[0] - 5, 105), fill="black", width=2)
    d.line((245, 105, 180, 190), fill="black", width=2)
    text("1.0000", 62, 98)
    text("0.7500", 212, 244)
    text("8.0000", 348, 267)
    text("R0.1250", 345, 324)
    text(bore_text + " BORE", 245, 175)
    text("TAG: " + tag, 245, 216)
    text("316 S/S", 320, 145, engine_pass="material.rot270.psm11")
    text("2-600", 280, 145)
    text("3.2500 Letter Length", 190, 345)
    d.text((790, 65), thickness + " 316 SS", font=font, fill="blue")
    f = io.BytesIO()
    im.save(f, format="PNG")
    document = normalize_document(f.getvalue(), "synthetic.png")
    region = DerivedDrawingRegion(
        region_id="synthetic",
        source_group_id="synthetic",
        source_filename="synthetic.png",
        page_number=1,
        source_bbox=(0, 0, 950, 400),
        candidate_bbox=(508, 68, 772, 332),
        coordinate_unit="pixel",
        derivation_method="single_quote_specific_raster_page_v1",
    )
    rendered = render_region_png(document, region, dpi=300)
    tokens = [
        OcrTokenObservation(
            token_id=str(i),
            region_id=region.region_id,
            page_number=1,
            raw_text=raw,
            pixel_bbox=tuple(int(v * 3.125) for v in bbox),
            source_bbox=bbox,
            source_coordinate_unit="pixel",
            engine="synthetic_observation",
            engine_pass=p,
            line_key=str(i),
        )
        for i, (raw, bbox, p) in enumerate(toks)
    ]
    ocr = LocalOcrResult(
        engine="synthetic_observation",
        engine_version="1",
        region_id=region.region_id,
        dpi=300,
        page_segmentation_modes=[11],
        tokens=tokens,
        ocr_seconds=0,
    )
    return document, region, ocr, rendered


@pytest.mark.parametrize(
    "raw,value",
    [
        ('1"', 1),
        ('1-1/4"', 1.25),
        ('2-3/8"', 2.375),
        ("3 1/2 IN", 3.5),
        ('1/8"', 0.125),
        ('1/4"', 0.25),
    ],
)
def test_fraction_measurements(raw, value):
    assert parse_measurement(raw).value == value


@pytest.mark.parametrize(
    "raw,value", [("316 S/S", "316"), ("304 S/S", "304"), ("316 SS", "316")]
)
def test_material_abbreviations(raw, value):
    assert parse_material(raw) == value


@pytest.mark.parametrize(
    "bore,bore_text,thickness",
    [(1, '1"', '1/8"'), (1.25, '1-1/4"', '1/4"'), (1.5, '1-1/2"', '3/8"')],
)
def test_spatial_detail_fields_and_provenance(bore, bore_text, thickness):
    doc, reg, ocr, rendered = detail(
        bore=bore, bore_text=bore_text, thickness=thickness
    )
    fields = observations(reg, ocr, rendered, doc)
    expected = {
        "outside_diameter": 4.125,
        "bore_diameter": bore,
        "handle_width": 1,
        "handle_length_from_bore": 8,
        "tag_hole_diameter": 0.375,
        "tag_hole_position": 0.75,
        "neck_radius": 0.125,
        "material": "316",
        "marking_text": "SYN-100",
    }
    for name, value in expected.items():
        assert fields[name].value == value, (name, fields.get(name))
        assert fields[name].evidence_classification == "requires_confirmation"
        assert fields[name].confidence < 0.9
        assert fields[name].evidence[0].source.source_type.startswith("printed_")
    assert fields["thickness"].value is None
    assert fields["thickness"].evidence[0].source.source_type == "handwritten_note"
    assert "unreadable" in fields["thickness"].abstention_reason
    assert not any(
        v.value in [316, 600, 3.25] for k, v in fields.items() if k not in ["material"]
    )


def test_nominal_mixed_bore_is_not_minus_tolerance():
    doc, reg, ocr, rendered = detail()
    results, extraction = interpret_precomputed_region(doc, reg, ocr, rendered=rendered)
    assert results["bore_diameter"].value == 1.25
    assert results["bore_tolerance_minus"].value is None
    assert results["bore_tolerance_plus"].value is None


def test_conflicting_bore_marking_does_not_choose_one():
    _, reg, ocr, rendered = detail(bore=1.25, bore_text='1"')
    results = observations(reg, ocr, rendered)
    assert results["bore_diameter"].value is None
    assert set(results["bore_diameter"].candidate_values) == {1, 1.25}
    assert results["bore_diameter"].status == "ambiguous"


def test_large_decimal_without_diameter_glyph_not_repaired():
    _, reg, ocr, rendered = detail()
    # Put OCR's 94.1250 text over an ordinary numeral, rather than a diameter.
    image = Image.open(io.BytesIO(rendered.png_bytes))
    draw = ImageDraw.Draw(image)
    first = ocr.tokens[0]
    x0, y0, x1, y1 = first.pixel_bbox
    draw.rectangle((x0, y0, x0 + 42, y1), fill="white")
    draw.text(
        (x0, y0), "9", fill="black", font=ImageFont.truetype("DejaVuSans.ttf", 42)
    )
    f = io.BytesIO()
    image.save(f, format="PNG")
    changed = rendered.model_copy(update={"png_bytes": f.getvalue()})
    assert "outside_diameter" not in observations(reg, ocr, changed)


@pytest.mark.parametrize(
    "text,specific",
    [
        ('TAG: SYN-123 1" BORE', True),
        ('1" BORE', False),
        ('CATALOG TAG: SYN-123 1" BORE', False),
    ],
)
def test_cropped_geometry_requires_specific_context(text, specific):
    doc, reg, _, _ = detail()
    hint = CandidateRegionHint(
        page_number=1,
        bbox=reg.candidate_bbox,
        coordinate_unit="pixel",
        detection_method="raster_cropped_two_concentric_perimeters_v1",
    )
    structure = DocumentStructureAssessment(
        status="single_candidate", candidate_region_count=1, candidate_regions=[hint]
    )
    assert (
        classify_drawing_document(doc, structure, observed_text=text).quote_specific
        is specific
    )


@pytest.mark.parametrize(
    "fraction,expected", [('1/8"', 0.125), ('1/4"', 0.25), ('3/8"', 0.375)]
)
def test_readable_colored_fraction_is_low_confidence_candidate(fraction, expected):
    doc, reg, ocr, rendered = detail(thickness=fraction)
    t = OcrTokenObservation(
        token_id="note",
        region_id=reg.region_id,
        page_number=1,
        raw_text=fraction,
        pixel_bbox=(2468, 203, 2580, 260),
        source_bbox=(790, 65, 825, 82),
        source_coordinate_unit="pixel",
        engine="synthetic_observation",
        engine_pass="psm11",
        line_key="note",
    )
    ocr = ocr.model_copy(update={"tokens": [*ocr.tokens, t]})
    fields = observations(reg, ocr, rendered, doc)
    assert fields["thickness"].value == expected
    assert fields["thickness"].confidence == 0.4
    assert fields["thickness"].status == "low_confidence"
    assert fields["thickness"].evidence[-1].source.source_type == "handwritten_note"


def test_handwritten_printed_thickness_conflict_is_preserved():
    doc, reg, ocr, rendered = detail(thickness='1/8"')
    for raw, box, key in [
        ('1/8"', (790, 65, 825, 82), "note"),
        ("THK", (240, 370, 270, 384), "label"),
        ('.250"', (275, 370, 315, 384), "printed"),
    ]:
        t = OcrTokenObservation(
            token_id=key,
            region_id=reg.region_id,
            page_number=1,
            raw_text=raw,
            pixel_bbox=(0, 0, 100, 20),
            source_bbox=box,
            source_coordinate_unit="pixel",
            engine="synthetic_observation",
            engine_pass="psm11",
            line_key=key,
        )
        ocr = ocr.model_copy(update={"tokens": [*ocr.tokens, t]})
    results, extraction = interpret_precomputed_region(doc, reg, ocr, rendered=rendered)
    assert results["thickness"].value is None
    assert set(results["thickness"].candidate_values) == {0.125, 0.25}
    assert results["thickness"].status == "ambiguous"


def test_dimensions_and_tag_variants_not_looked_up():
    doc, reg, ocr, rendered = detail(
        od=5.5, bore=1.5, bore_text='1-1/2"', tag="TEST-98765"
    )
    fields = observations(reg, ocr, rendered, doc)
    assert fields["outside_diameter"].value == 5.5
    assert fields["bore_diameter"].value == 1.5
    assert fields["marking_text"].value == "TEST-98765"


@pytest.mark.parametrize("bore,bore_text", [(1, '1"'), (1.25, '1-1/4"')])
def test_synthetic_image_through_real_upload_ocr_review(bore, bore_text):
    from drawing_intake.assisted_intake import (
        inspect_assisted_upload,
        select_assisted_candidate,
    )

    doc, *_ = detail(bore=bore, bore_text=bore_text)
    upload = inspect_assisted_upload(doc.source_bytes, "arbitrary-name.png")
    assert len(upload.review.candidates) == 1
    session = select_assisted_candidate(
        upload, upload.review.candidates[0].candidate_id
    )
    fields = {p.extraction_field: p for p in session.proposals}
    assert fields["outside_diameter"].proposed_value == 4.125
    assert fields["bore_diameter"].proposed_value == bore
    assert fields["bore_tolerance_minus"].proposed_value is None
    assert session.confirmation_fingerprint is None
    assert session.order_created is False
    assert fields["thickness"].source_type == "handwritten_note"
    assert fields["thickness"].confidence == 0.4


def test_colored_scan_specks_do_not_reclassify_printed_bore_as_thickness():
    doc, reg, ocr, rendered = detail()
    im = Image.open(io.BytesIO(doc.source_bytes))
    draw = ImageDraw.Draw(im)
    draw.rectangle((100, 20, 103, 23), fill="blue")
    draw.rectangle((920, 370, 923, 373), fill="blue")
    f = io.BytesIO()
    im.save(f, format="PNG")
    doc = normalize_document(f.getvalue(), "noisy-synthetic.png")
    t = OcrTokenObservation(
        token_id="printed-fraction",
        region_id=reg.region_id,
        page_number=1,
        raw_text='1-1/4"',
        pixel_bbox=(0, 0, 100, 20),
        source_bbox=(245, 175, 299, 189),
        source_coordinate_unit="pixel",
        engine="synthetic_observation",
        engine_pass="psm11",
        line_key="printed-fraction",
    )
    ocr = ocr.model_copy(update={"tokens": [*ocr.tokens, t]})
    assert observations(reg, ocr, rendered, doc)["thickness"].value is None
