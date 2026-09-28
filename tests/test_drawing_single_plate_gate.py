"""Synthetic, layout-independent safety checks for raster single-part drawings."""

import io
import os
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from drawing_intake.assisted_intake import (
    inspect_assisted_upload,
    select_assisted_candidate,
)
from drawing_intake.classification import (
    DrawingDocumentClass,
    classify_drawing_document,
)
from drawing_intake.deterministic import (
    _adjacent_numeric_candidates,
    _specification_row_candidates,
)
from drawing_intake.documents import normalize_document
from drawing_intake.models import DocumentStatus
from drawing_intake.ocr import OcrTokenObservation
from drawing_intake.raster_structure import detect_raster_plate_structure
from drawing_intake.regions import DerivedDrawingRegion, derive_candidate_regions
from drawing_intake.rendering import render_region_png


def _raster_plate(center_x):
    image = Image.new("L", (1000, 750), 255)
    draw = ImageDraw.Draw(image)
    for center in (center_x,) if isinstance(center_x, int) else center_x:
        for radius in (55, 125):
            draw.ellipse(
                (center - radius, 400 - radius, center + radius, 400 + radius),
                outline=0,
                width=3,
            )
        for x in range(center - 125, center + 125, 16):
            draw.line((x, 400, x + 5, 400), fill=0)
        for y in range(275, 525, 16):
            draw.line((center, y, center, y + 5), fill=0)
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def _structure(data):
    document = normalize_document(data, "shifted-layout.png")
    page = document.pages[0]
    full = DerivedDrawingRegion(
        region_id="full",
        source_group_id="synthetic",
        source_filename=document.filename,
        page_number=1,
        source_bbox=(0, 0, page.width, page.height),
        candidate_bbox=(0, 0, page.width, page.height),
        coordinate_unit=page.coordinate_unit,
    )
    return document, detect_raster_plate_structure(
        render_region_png(document, full, dpi=96)
    )


@pytest.mark.parametrize("center_x", [300, 600])
def test_dashed_centerline_profile_is_detected_without_fixed_coordinates(center_x):
    document, structure = _structure(_raster_plate(center_x))
    assert structure.status == DocumentStatus.SINGLE_CANDIDATE
    assert structure.candidate_region_count == 1
    assert structure.candidate_regions[0].detection_method.endswith(
        "perimeters_without_centerline_v1"
    )
    bbox = structure.candidate_regions[0].bbox
    assert (bbox[0] + bbox[2]) / 2 == pytest.approx(center_x, abs=5)

    accepted = classify_drawing_document(
        document,
        structure,
        observed_text=(
            "OUTSIDE DIAMETER BORE DIAMETER PLATE THICKNESS "
            "MATERIAL QUANTITY DRAWING NO 12345"
        ),
        labeled_document_identifier=True,
    )
    assert accepted.document_class == DrawingDocumentClass.SINGLE_PLATE_DRAWING
    assert accepted.quote_specific
    region = derive_candidate_regions(document, structure, source_group_id="synthetic")[
        0
    ]
    assert region.source_bbox == (
        0,
        0,
        document.pages[0].width,
        document.pages[0].height,
    )

    for text, identifier in (
        ("OUTSIDE DIAMETER BORE DIAMETER MATERIAL QUANTITY", True),
        (
            "OUTSIDE DIAMETER BORE DIAMETER PLATE THICKNESS MATERIAL "
            "QUANTITY CATALOG SIZE SELECTION",
            True,
        ),
        (
            "OUTSIDE DIAMETER BORE DIAMETER PLATE THICKNESS MATERIAL QUANTITY",
            False,
        ),
    ):
        rejected = classify_drawing_document(
            document,
            structure,
            observed_text=text,
            labeled_document_identifier=identifier,
        )
        assert not rejected.quote_specific


def _token(raw, x, y, *, line, region="selected", pass_name="psm11"):
    return OcrTokenObservation(
        token_id=f"{region}:{pass_name}:{line}:{x}:{raw}",
        region_id=region,
        page_number=1,
        raw_text=raw,
        pixel_bbox=(x, y, x + len(raw) * 8, y + 18),
        source_bbox=(x, y, x + len(raw) * 8, y + 18),
        source_coordinate_unit="pixel",
        engine="tesseract",
        engine_pass=pass_name,
        line_key=line,
    )


@pytest.mark.parametrize("offset", [0, 160])
def test_key_value_table_bindings_follow_rows_and_regions(offset):
    tokens = []
    for index, (label, value) in enumerate(
        (
            ("OUTSIDE DIAMETER", "8.500 in"),
            ("BORE DIAMETER", "4.443 in"),
            ("HANDLE WIDTH", "1.500 in"),
            ("HANDLE LENGTH", "14.000 in"),
            ("PLATE THICKNESS", "0.250 in"),
        )
    ):
        y = 80 + offset + index * 35
        tokens.extend(
            [
                _token(label, 450 - offset, y, line=f"label-{index}"),
                _token(value, 740 - offset, y, line=f"value-{index}"),
            ]
        )
        if label == "HANDLE LENGTH":
            tokens.append(
                _token(
                    "(FROM BORE CENTER TO HANDLE TIP)",
                    450 - offset,
                    y + 20,
                    line="length-qualifier",
                )
            )
    tokens.append(
        _token(
            "99.000 in", 680 - offset, 115 + offset, line="other-value", region="other"
        )
    )
    rows = _specification_row_candidates(tokens)
    assert {key: values[0].value for key, values in rows.items()} == {
        "outside_diameter": 8.5,
        "bore_diameter": 4.443,
        "handle_width": 1.5,
        "handle_length_from_bore": 14.0,
        "thickness": 0.25,
    }
    assert all(
        candidate.source.bbox for values in rows.values() for candidate in values
    )
    assert "other" not in rows["bore_diameter"][0].source.raw_text
    unqualified = [token for token in tokens if token.line_key != "length-qualifier"]
    assert "handle_length_from_bore" not in _specification_row_candidates(unqualified)


def test_bore_center_handle_callout_cannot_become_bore_diameter():
    tokens = [
        _token("14.000", 10, 20, line="handle"),
        _token("BORE", 85, 20, line="handle"),
        _token("CENTER", 130, 20, line="handle"),
    ]
    assert not _adjacent_numeric_candidates(tokens, labels={"BORE"})


def test_two_broken_centerline_profiles_remain_separate_candidates():
    document, structure = _structure(_raster_plate((270, 730)))
    assert structure.status == DocumentStatus.MULTIPLE_CANDIDATES
    assert structure.candidate_region_count == 2
    classification = classify_drawing_document(document, structure)
    assert classification.document_class == DrawingDocumentClass.MULTI_PLATE_DRAWING
    assert classification.candidate_count == 2
    regions = derive_candidate_regions(document, structure, source_group_id="synthetic")
    assert len(regions) == 2
    assert regions[0].source_bbox[2] <= regions[1].source_bbox[0]


@pytest.mark.skipif(
    not os.environ.get("DRAWING_SINGLE_PLATE_REGRESSION"),
    reason="private uploaded print supplied only in the local test environment",
)
def test_private_single_plate_regression_is_never_committed():
    path = Path(os.environ["DRAWING_SINGLE_PLATE_REGRESSION"])
    upload = inspect_assisted_upload(path.read_bytes(), path.name)
    assert upload.review.document_class == DrawingDocumentClass.SINGLE_PLATE_DRAWING
    assert len(upload.review.candidates) == 1
    session = select_assisted_candidate(
        upload, upload.review.candidates[0].candidate_id
    )
    expected = {
        "paddle_dia": 8.5,
        "bore_dia": 4.443,
        "thickness": 0.25,
        "handle_width": 1.5,
        "handle_length_from_bore": 14.0,
        "material": "316",
        "quantity": 2,
    }
    assert {name: session.configuration[name].value for name in expected} == expected
    assert "chamfer" not in session.configuration
    assert "chamfer_width" not in session.configuration
    assert "ships_in_days" not in session.configuration
