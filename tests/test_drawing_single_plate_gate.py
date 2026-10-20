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
from drawing_intake.assisted_quote import (
    build_assisted_quote_session,
    review_assisted_quote,
    set_customer_value,
)
from drawing_intake.classification import (
    DrawingDocumentClass,
    classify_drawing_document,
)
from drawing_intake.confirmation_contract import (
    ConfirmationFieldProposal,
    ConfirmationWorkflowStatus,
    CustomerConfirmationContract,
)
from drawing_intake.deterministic import (
    EvidenceClassification,
    _adjacent_numeric_candidates,
    _labeled_note_candidates,
    _resolve_marking,
    _specification_row_candidates,
)
from drawing_intake.documents import normalize_document
from drawing_intake.document_recognition import _labeled_document_identifier
from drawing_intake.models import DocumentStatus, FieldStatus
from drawing_intake.ocr import LocalOcrResult, OcrTokenObservation
from drawing_intake.raster_structure import detect_raster_plate_structure
from drawing_intake.regions import DerivedDrawingRegion, derive_candidate_regions
from drawing_intake.rendering import render_region_png
from drawing_intake.spatial import build_spatial_lines


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


def _one_plate_with_side_view_and_ruled_specifications(center_x):
    image = Image.open(io.BytesIO(_raster_plate(center_x))).convert("L")
    draw = ImageDraw.Draw(image)
    # A section view and ruled specification table must not supply competing
    # round-plate candidates. Shift all three regions together in the test.
    side_x = center_x + 250
    draw.rectangle((side_x, 275, side_x + 16, 525), outline=0, width=3)
    left = center_x + 320
    right = left + 280
    draw.rectangle((left, 90, right, 555), outline=0, width=3)
    draw.line((left + 140, 90, left + 140, 555), fill=0, width=3)
    for y in range(120, 555, 35):
        draw.line((left, y, right, y), fill=0, width=3)
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
            "PADDLE ORIFICE PLATE OUTSIDE DIAMETER BORE DIAMETER PLATE THICKNESS "
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
        ("PADDLE ORIFICE PLATE OUTSIDE DIAMETER BORE DIAMETER", False),
        (
            "PADDLE ORIFICE PLATE OUTSIDE DIAMETER BORE DIAMETER PLATE THICKNESS MATERIAL "
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


def test_single_plate_eligibility_does_not_require_quote_field_completeness():
    document, structure = _structure(_raster_plate(600))
    accepted = classify_drawing_document(
        document,
        structure,
        observed_text=(
            "PADDLE ORIFICE PLATE OUTSIDE DIAMETER 10.000 BORE DIAMETER "
            "3.750 PLATE THICKNESS .250 MATERIAL 304 STAINLESS STEEL"
        ),
        labeled_document_identifier=True,
    )
    assert accepted.document_class == DrawingDocumentClass.SINGLE_PLATE_DRAWING
    assert accepted.quote_specific
    assert accepted.candidate_count == 1
    assert not any("quantity" in rule for rule in accepted.evidence_rules)

    proposals = [
        ConfirmationFieldProposal(
            extraction_field=source,
            canonical_field=target,
            proposed_value=value,
            raw_text=str(value),
            source_document="generated-test.png",
            source_sha256="1" * 64,
            source_page=1,
            evidence_status=EvidenceClassification.REQUIRES_CONFIRMATION,
            validation_status=FieldStatus.DETECTED,
            confirmation_required=True,
            unsupported=False,
        )
        for source, target, value in (
            ("outside_diameter", "paddle_dia", 10.0),
            ("bore_diameter", "bore_dia", 3.75),
            ("thickness", "thickness", 0.25),
            ("material", "material", "304"),
        )
    ]
    contract = CustomerConfirmationContract(
        source_document="generated-test.png",
        source_sha256="1" * 64,
        document_class=accepted.document_class,
        candidate_count=1,
        selected_candidate_id="plate-1",
        selection_required=False,
        proposals=proposals,
        status=ConfirmationWorkflowStatus.REQUIRES_CONFIRMATION,
    )
    session = build_assisted_quote_session(contract)
    assert len(session.configuration) == 4
    missing = review_assisted_quote(session).missing_required_fields
    assert {"handle_width", "handle_length_from_bore", "quantity"} <= set(missing)
    for field, value in (
        ("handle_width", 1.25),
        ("handle_length_from_bore", 15.0),
        ("quantity", 1),
    ):
        session = set_customer_value(session, field, value)
    missing_after = review_assisted_quote(session).missing_required_fields
    assert not {"handle_width", "handle_length_from_bore", "quantity"} & set(
        missing_after
    )
    assert session.configuration["handle_length_from_bore"].value == 15.0


def test_identifier_binds_to_neighboring_table_cell_and_strips_label_colon():
    def observed(tokens):
        return LocalOcrResult(
            engine="tesseract",
            engine_version="test",
            region_id="selected",
            dpi=150,
            page_segmentation_modes=[11],
            tokens=tokens,
            ocr_seconds=0.0,
        )

    assert _labeled_document_identifier(
        observed(
            [
                _token("TEST ID:", 100, 100, line="label"),
                _token("ZX-2041", 270, 100, line="value"),
            ]
        )
    )
    assert _labeled_document_identifier(
        observed(
            [
                _token("DWG NO.: ZX-2041", 100, 100, line="label"),
            ]
        )
    )
    assert _labeled_document_identifier(
        observed(
            [
                _token("TEST ID:", 100, 100, line="label"),
                _token("ZX-2041", 120, 128, line="value"),
            ]
        )
    )
    assert not _labeled_document_identifier(
        observed(
            [
                _token("TEST ID:", 100, 100, line="label"),
                _token("5000", 300, 128, line="unrelated_next_row"),
            ]
        )
    )
    assert not _labeled_document_identifier(
        observed(
            [
                _token("TEST ID:", 100, 100, line="label"),
            ]
        )
    )


@pytest.mark.parametrize("center_x", [210, 270])
def test_front_and_side_views_with_specification_table_still_have_one_plate(
    center_x,
):
    document, structure = _structure(
        _one_plate_with_side_view_and_ruled_specifications(center_x)
    )
    assert structure.status == DocumentStatus.SINGLE_CANDIDATE
    assert structure.candidate_region_count == 1
    bbox = structure.candidate_regions[0].bbox
    assert (bbox[0] + bbox[2]) / 2 == pytest.approx(center_x, abs=5)
    classification = classify_drawing_document(
        document,
        structure,
        observed_text=(
            "PADDLE ORIFICE PLATE SPECIFICATIONS OUTSIDE DIAMETER "
            "BORE DIAMETER MATERIAL DRAWING NO ZX-2041"
        ),
        labeled_document_identifier=True,
    )
    assert classification.document_class == DrawingDocumentClass.SINGLE_PLATE_DRAWING
    assert classification.candidate_count == 1
    assert classification.quote_specific


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


@pytest.mark.parametrize("offset", [0, 180])
def test_explicit_note_dimensions_skip_note_numbers_and_preserve_units(offset):
    tokens = [
        _token("4.", 10 + offset, 20 + offset, line="number"),
        _token("BORE", 42 + offset, 20 + offset, line="number"),
        _token(
            "BORE DIAMETER: @3.750 IN. +0.005 IN.",
            10 + offset,
            60 + offset,
            line="bore-note",
        ),
        _token(
            "OUTSIDE DIAMETER: @10.000 IN.",
            10 + offset,
            100 + offset,
            line="od-note",
        ),
        _token(
            "PLATE THICKNESS: 0.250 IN.",
            10 + offset,
            140 + offset,
            line="thickness-note",
        ),
        _token(
            "BORE DIAMETER TOLERANCE: +0.005 IN.",
            10 + offset,
            180 + offset,
            line="tolerance-note",
        ),
        _token("OUTSIDE DIAMETER: 12.000", 10 + offset, 220 + offset, line="no-unit"),
    ]
    assert not _adjacent_numeric_candidates(tokens, labels={"BORE"})
    no_period = [
        _token("4", 10 + offset, 20 + offset, line="number"),
        *tokens[1:],
    ]
    assert not _adjacent_numeric_candidates(no_period, labels={"BORE"})
    notes = _labeled_note_candidates(tokens)
    assert {
        name: [candidate.value for candidate in matches]
        for name, matches in notes.items()
    } == {
        "bore_diameter": [3.75],
        "outside_diameter": [10.0],
        "thickness": [0.25],
    }
    assert all(
        candidate.unit == "in" for matches in notes.values() for candidate in matches
    )


def test_marking_literal_requires_explicit_binding_and_abstains_on_merges():
    merged = build_spatial_lines(
        [
            _token(
                'oro (STAMP 1/4" HIGH LETTERS) DRAWING NO.: ZX-2041',
                100,
                100,
                line="merged",
            ),
        ]
    )
    assert _resolve_marking(merged).value is None
    assert _resolve_marking(merged).status == FieldStatus.AMBIGUOUS

    table = build_spatial_lines(
        [
            _token("MARKING TEXT", 300, 200, line="label"),
            _token("UPSTREAM", 540, 200, line="value"),
            _token('(STAMP 1/4" HIGH LETTERS)', 300, 250, line="instruction"),
        ]
    )
    result = _resolve_marking(table)
    assert result.value == "UPSTREAM"
    assert result.status == FieldStatus.LOW_CONFIDENCE
    assert result.raw_text == "UPSTREAM"
    assert result.evidence[0].source.bbox is not None

    quoted = build_spatial_lines(
        [
            _token(
                'MARK HANDLE WITH "UPSTREAM" USING 1/4" LETTERS',
                200,
                300,
                line="quoted",
            ),
        ]
    )
    assert _resolve_marking(quoted).value == "UPSTREAM"

    conflicting = build_spatial_lines(
        [
            _token("MARKING TEXT: UPSTREAM", 200, 300, line="first"),
            _token("MARKING TEXT: DOWNSTREAM", 200, 350, line="second"),
        ]
    )
    result = _resolve_marking(conflicting)
    assert result.status == FieldStatus.AMBIGUOUS
    assert result.value is None
    assert result.candidate_values == ["DOWNSTREAM", "UPSTREAM"]

    mislabeled = build_spatial_lines(
        [
            _token("MARKING TEXT: UPSTREAM DRAWING NO", 200, 400, line="contaminated"),
        ]
    )
    assert _resolve_marking(mislabeled).value is None


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


@pytest.mark.parametrize(
    ("fixture_env", "expected"),
    [
        (
            "DRAWING_OWNER_SYNTHETIC_RICH",
            {
                "paddle_dia": 5.0,
                "bore_dia": 1.548,
                "thickness": 0.125,
                "handle_width": 2.0,
                "handle_length_from_bore": 10.5,
                "material": "304",
                "quantity": 1,
                "bore_tolerance": 0.005,
            },
        ),
        (
            "DRAWING_OWNER_SYNTHETIC_ALTERNATE",
            {
                "paddle_dia": 13.25,
                "bore_dia": 6.875,
                "thickness": 0.375,
                "handle_width": 1.25,
                "material": "Carbon Steel",
                "quantity": 3,
                "handle_label": "UPSTREAM",
            },
        ),
    ],
)
def test_private_owner_prints_remain_single_plate_without_committing_images(
    fixture_env,
    expected,
):
    if fixture_env not in os.environ:
        pytest.skip("owner-supplied synthetic print is not in this test environment")
    path = Path(os.environ[fixture_env])
    upload = inspect_assisted_upload(path.read_bytes(), path.name)
    assert upload.review.document_class == DrawingDocumentClass.SINGLE_PLATE_DRAWING
    assert upload.recognition.structure.candidate_region_count == 1
    assert len(upload.review.candidates) == 1
    session = select_assisted_candidate(
        upload, upload.review.candidates[0].candidate_id
    )
    assert {name: session.configuration[name].value for name in expected} == expected
    assert "chamfer" not in session.configuration
    assert "chamfer_width" not in session.configuration
    assert "ships_in_days" not in session.configuration


@pytest.mark.skipif(
    "DRAWING_OWNER_SYNTHETIC_PARTIAL" not in os.environ,
    reason="partial owner-supplied synthetic print is not in this test environment",
)
def test_private_partial_print_can_proceed_to_manual_completion():
    path = Path(os.environ["DRAWING_OWNER_SYNTHETIC_PARTIAL"])
    upload = inspect_assisted_upload(path.read_bytes(), path.name)
    assert upload.review.document_class == DrawingDocumentClass.SINGLE_PLATE_DRAWING
    assert len(upload.review.candidates) == 1
    session = select_assisted_candidate(
        upload, upload.review.candidates[0].candidate_id
    )
    assert {
        name: session.configuration[name].value
        for name in (
            "paddle_dia",
            "bore_dia",
            "thickness",
            "material",
        )
    } == {
        "paddle_dia": 10.0,
        "bore_dia": 3.75,
        "thickness": 0.25,
        "material": "304",
    }
    assert session.configuration["bore_tolerance"].value == 0.005
    assert {"handle_width", "handle_length_from_bore", "quantity"} <= set(
        review_assisted_quote(session).missing_required_fields
    )
    assert all(
        field not in session.configuration
        for field in (
            "handle_width",
            "handle_length_from_bore",
            "quantity",
            "chamfer",
            "chamfer_width",
            "ships_in_days",
        )
    )
