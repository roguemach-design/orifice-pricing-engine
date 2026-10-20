"""Synthetic, coordinate-shifted handle callouts; no customer print is tracked."""

import io

import pytest
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

from drawing_intake.assisted_quote import (
    build_assisted_quote_session,
    local_form_availability,
)
from drawing_intake.classification import DrawingDocumentClass
from drawing_intake.confirmation_contract import build_customer_confirmation_contract
from drawing_intake.deterministic import interpret_precomputed_region
from drawing_intake.documents import normalize_document
from drawing_intake.engineering_text import parse_measurement
from drawing_intake.models import FieldStatus
from drawing_intake.ocr import LocalOcrResult, OcrTokenObservation
from drawing_intake.regions import derive_candidate_regions
from drawing_intake.rendering import render_region_png
from drawing_intake.structure import assess_document_structure
from drawing_intake.validation import validate_extraction


def _detail(center_x=240, *, width_lines=True, center_witness=True):
    output = io.BytesIO()
    page = canvas.Canvas(output, pagesize=letter)
    cy, radius = 270, 70
    for r in (radius, 48, 37):
        page.circle(center_x, cy, r)
    tip_y = cy + radius * 1.3
    for side in (center_x - 25, center_x + 25):
        page.line(side, cy + radius * 0.98, side, tip_y)
    page.line(center_x - 25, tip_y, center_x + 25, tip_y)
    # Upper and lower witnesses of the vertical bore-center-to-tip dimension.
    dimension_x = center_x + 125
    page.line(center_x, tip_y, dimension_x + 15, tip_y)
    if center_witness:
        page.line(center_x - 90, cy, dimension_x + 15, cy)
    page.line(dimension_x, cy, dimension_x, tip_y)
    if width_lines:
        dim_y = tip_y + 16
        for side in (center_x - 25, center_x + 25):
            page.line(side, dim_y + 8, side, cy + radius * 0.98)
        page.line(center_x - 25, dim_y, center_x - 15, dim_y)
        page.line(center_x + 15, dim_y, center_x + 25, dim_y)
    page.showPage()
    page.save()
    doc = normalize_document(output.getvalue(), "synthetic-handle.pdf")
    region = derive_candidate_regions(
        doc, assess_document_structure(doc), source_group_id="synthetic"
    )[0]
    return doc, region


def _token(region, text, bbox, *, mode="psm6", other_region=False):
    return OcrTokenObservation(
        token_id=f"{mode}:{text}:{bbox[0]}",
        region_id="other-region" if other_region else region.region_id,
        page_number=region.page_number,
        raw_text=text,
        pixel_bbox=tuple(int(v * 4) for v in bbox),
        source_bbox=bbox,
        engine="synthetic-local-ocr",
        engine_pass=mode,
        line_key=f"{mode}:line",
    )


def _observations(region, center_x, *, width='1 1/2"', length="8.500"):
    # Source coordinates are top-left PDF points. Only the layout moves.
    return [
        _token(region, '4.000"', (center_x - 180, 480, center_x - 145, 495)),
        _token(
            region, '4.000"', (center_x - 180, 480, center_x - 145, 495), mode="psm11"
        ),
        _token(region, width, (center_x - 15, 387, center_x + 15, 410)),
        _token(
            region,
            length,
            (center_x + 99, 452, center_x + 116, 484),
            mode="target.handle.rot270.psm11",
        ),
    ]


def _interpret(doc, region, tokens):
    ocr = LocalOcrResult(
        engine="synthetic-local-ocr",
        engine_version="test",
        region_id=region.region_id,
        dpi=300,
        page_segmentation_modes=[6, 11],
        tokens=tokens,
        ocr_seconds=0,
    )
    return interpret_precomputed_region(
        doc, region, ocr, rendered=render_region_png(doc, region)
    )


@pytest.mark.parametrize("raw,value", [('1½"', 1.5), ('1 9/16"', 1.5625), ('¾"', 0.75)])
def test_exact_fraction_glyphs_are_normalized_without_ocr_guessing(raw, value):
    assert parse_measurement(raw).value == pytest.approx(value)


@pytest.mark.parametrize("center_x", [225, 475])
def test_unlabeled_handle_dimensions_bind_to_printed_center_and_tip(center_x):
    doc, region = _detail(center_x)
    fields, extraction = _interpret(doc, region, _observations(region, center_x))
    assert fields["handle_width"].value == pytest.approx(1.5)
    assert fields["handle_length_from_bore"].value == pytest.approx(8.5)
    assert fields["handle_length_from_bore"].evidence[0].rule_id == (
        "bore_center_to_tip_dimension_lines"
    )
    assert extraction.fields.handle_length_from_bore.evidence[0].bbox == pytest.approx(
        (center_x + 99, 452, center_x + 116, 484)
    )
    assert fields["handle_length_from_bore"].evidence_classification == (
        "requires_confirmation"
    )


def test_corrupted_fraction_and_missing_dimension_lines_abstain():
    doc, region = _detail(width_lines=False, center_witness=False)
    fields, _ = _interpret(doc, region, _observations(region, 240, width='1%"'))
    assert fields["handle_width"].value is None
    assert fields["handle_length_from_bore"].value is None

    complete, selected = _detail()
    fields, _ = _interpret(
        complete, selected, _observations(selected, 240, width='1%"')
    )
    assert fields["handle_width"].value is None


def test_explicit_handle_labels_work_without_a_topology_match():
    doc, region = _detail(width_lines=False, center_witness=False)
    width = [
        _token(region, text, bbox).model_copy(update={"line_key": "psm6:handle-width"})
        for text, bbox in (
            ("HANDLE", (190, 390, 220, 408)),
            ("WIDTH", (222, 390, 254, 408)),
            ('1½"', (256, 390, 276, 408)),
        )
    ]
    length = [
        _token(region, text, bbox).model_copy(update={"line_key": "psm6:handle-length"})
        for text, bbox in (
            ("HANDLE", (130, 460, 160, 478)),
            ("LENGTH", (162, 460, 200, 478)),
            ("FROM", (202, 460, 232, 478)),
            ("BORE", (234, 460, 262, 478)),
            ("CENTER", (264, 460, 301, 478)),
            ('8.500"', (303, 460, 341, 478)),
        )
    ]
    fields, _ = _interpret(doc, region, [*width, *length])
    assert fields["handle_width"].value == pytest.approx(1.5)
    assert fields["handle_length_from_bore"].value == pytest.approx(8.5)


def test_competing_readings_and_cross_region_tokens_cannot_be_selected():
    doc, region = _detail()
    observations = _observations(region, 240)
    observations.append(
        _token(
            region,
            "9.000",
            (339, 452, 356, 484),
            mode="target.handle.rot270.psm6",
        )
    )
    fields, _ = _interpret(doc, region, observations)
    assert fields["handle_length_from_bore"].status == FieldStatus.AMBIGUOUS
    assert fields["handle_length_from_bore"].value is None

    foreign = _observations(region, 240)[-1].model_copy(
        update={"region_id": "other-region"}
    )
    fields, _ = _interpret(doc, region, [*_observations(region, 240)[:-1], foreign])
    assert fields["handle_length_from_bore"].value is None


def test_chamfer_is_evidence_only_and_lead_time_remains_manual():
    doc, region = _detail()
    fields, extraction = _interpret(doc, region, _observations(region, 240))
    extraction.fields.chamfer_present = extraction.fields.chamfer_present.model_copy(
        update={
            "value": True,
            "status": FieldStatus.DETECTED,
            "raw_text": "0.0625 X 45°",
        }
    )
    extraction.fields.chamfer_width = extraction.fields.chamfer_width.model_copy(
        update={
            "value": 0.0625,
            "normalized_unit": "in",
            "status": FieldStatus.DETECTED,
        }
    )
    validation = validate_extraction(extraction)
    assert validation.canonical_candidate.chamfer is None
    assert validation.canonical_candidate.chamfer_width is None
    assert "chamfer" in validation.canonical_candidate.missing_required_fields
    assert "ships_in_days" in validation.canonical_candidate.missing_required_fields

    from types import SimpleNamespace

    recognition = SimpleNamespace(
        field_results=fields,
        region=region,
        validation=validation,
        extraction=extraction,
    )

    contract = build_customer_confirmation_contract(
        recognition,
        document_class=DrawingDocumentClass.SINGLE_PLATE_DRAWING,
        candidate_count=1,
        selected_candidate_id=region.region_id,
    )
    session = build_assisted_quote_session(
        contract, availability=local_form_availability()
    )
    chamfer_proposal = next(
        proposal
        for proposal in contract.proposals
        if proposal.extraction_field == "chamfer_present"
    )
    assert chamfer_proposal.canonical_field is None
    assert not chamfer_proposal.confirmation_required
    assert session.configuration["handle_length_from_bore"].value == 8.5
    assert "chamfer" not in session.configuration
    assert "chamfer_width" not in session.configuration
    assert "ships_in_days" not in session.configuration

    unsupported_validation = validation.model_copy(
        update={"field_outcomes": {"chamfer_width": FieldStatus.UNSUPPORTED}}
    )
    alternate = SimpleNamespace(
        field_results=fields,
        region=region,
        validation=unsupported_validation,
        extraction=extraction,
    )
    unsupported_contract = build_customer_confirmation_contract(
        alternate,
        document_class=DrawingDocumentClass.SINGLE_PLATE_DRAWING,
        candidate_count=1,
        selected_candidate_id=region.region_id,
    )
    assert unsupported_contract.status != "blocked"
