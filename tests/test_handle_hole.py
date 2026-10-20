"""Optional manufacturing cut: geometry, artifacts, authority and compatibility."""

from dataclasses import replace
from hashlib import sha256
from io import BytesIO, StringIO
import json
import math
from pathlib import Path

import ezdxf
from pypdf import PdfReader
import pytest

from plate_geometry import (
    PlateSpec,
    build_plate_geometry,
    canonical_specification,
    rough_bore_diameter,
    validate_handle_hole,
)
from prototype_manufacturing import sample_spec
from manufacturing_files import dxf_bytes, pdf_bytes, preview_svg, generate_package
from manufacturing_drawing import DrawingMetadata
from plate_preview import render_plate_svg
from frozen_plate.repository import Repository, canonical, digest
from frozen_plate.validation import validate_package
from drawing_intake.handle_hole import propose_handle_hole
from drawing_intake.models import SourceEvidence, MeasurementUnit, DrawingFields
from drawing_intake.providers import NativeTextExtractionProvider
from drawing_intake.documents import normalize_document
from pricing_engine import QuoteInputs, calculate_quote


def spec(**changes):
    values = dict(
        handle_width=1.0,
        bore_tolerance=0.005,
        chamfer=False,
        handle_hole_enabled=True,
        handle_hole_diameter=0.375,
        handle_hole_center_from_handle_end=0.75,
    )
    return replace(sample_spec(), **{**values, **changes})


@pytest.mark.parametrize(
    "field,value,message",
    [
        ("handle_hole_diameter", 0.9001, "90%"),
        ("handle_hole_diameter", 0, "greater than zero"),
        ("handle_hole_diameter", -1, "greater than zero"),
        ("handle_hole_diameter", None, "required"),
        ("handle_hole_diameter", float("nan"), "finite"),
        ("handle_hole_diameter", float("inf"), "finite"),
        ("handle_hole_diameter", True, "finite"),
        ("handle_hole_center_from_handle_end", 0, "greater than zero"),
        ("handle_hole_center_from_handle_end", -1, "greater than zero"),
        ("handle_hole_center_from_handle_end", None, "required"),
        ("handle_hole_center_from_handle_end", 0.1875, "inside the handle end"),
        ("handle_hole_center_from_handle_end", 0.18, "inside the handle end"),
        ("handle_hole_center_from_handle_end", 8, "neck transition"),
    ],
)
def test_invalid_dimensions(field, value, message):
    with pytest.raises(ValueError, match=message):
        spec(**{field: value})


@pytest.mark.parametrize(
    "width,diameter,distance",
    [
        (1, 0.375, 0.75),
        (1, 0.9, 0.75),
        (2, 0.375, 0.75),
        (2, 1.8, 1.25),
    ],
)
def test_valid_and_exact_90_percent(width, diameter, distance):
    s = spec(
        handle_width=width,
        handle_hole_diameter=diameter,
        handle_hole_center_from_handle_end=distance,
    )
    assert build_plate_geometry(s).spec == s


def test_neck_tangent_boundary_from_actual_geometry():
    base = replace(sample_spec(), finished_od=5, handle_width=2)
    g = build_plate_geometry(base)
    radius = 0.125
    distance = base.centerline_to_handle_end - max(g.join_x, g.radius) - radius
    with pytest.raises(ValueError, match="neck"):
        replace(
            base,
            handle_hole_enabled=True,
            handle_hole_diameter=radius * 2,
            handle_hole_center_from_handle_end=distance,
        )
    replace(
        base,
        handle_hole_enabled=True,
        handle_hole_diameter=radius * 2,
        handle_hole_center_from_handle_end=distance - 0.00001,
    )


def test_disabled_rejects_stray_dimensions():
    with pytest.raises(ValueError, match="require"):
        replace(sample_spec(), handle_hole_diameter=0.375)


def test_legacy_spec_and_outer_profile_unchanged():
    legacy = canonical_specification(sample_spec())
    assert not any(k.startswith("handle_hole") for k in legacy)
    assert PlateSpec(**legacy) == sample_spec()
    off = replace(
        spec(),
        handle_hole_enabled=False,
        handle_hole_diameter=None,
        handle_hole_center_from_handle_end=None,
    )
    assert build_plate_geometry(off).segments == build_plate_geometry(spec()).segments


def test_finished_dxf_circle_and_main_bore_allowance_determinism():
    g = build_plate_geometry(spec())
    raw = dxf_bytes(g)
    assert raw == dxf_bytes(g)
    doc = ezdxf.read(StringIO(raw.decode()))
    assert not doc.audit().errors
    model = doc.modelspace()
    assert len(model) == 3
    hole = model.query('CIRCLE[layer=="CUT_HANDLE_HOLE"]')[0]
    bore = model.query('CIRCLE[layer=="CUT_BORE"]')[0]
    assert hole.dxf.radius * 2 == 0.375
    assert tuple(hole.dxf.center) == (9.75, 0, 0)
    assert bore.dxf.radius * 2 == 1.423
    assert rough_bore_diameter(g.spec) == 1.548 - 0.125
    assert next(iter(model)).closed


def test_pdf_svg_enabled_disabled_and_determinism():
    on = build_plate_geometry(spec())
    off = build_plate_geometry(
        replace(
            spec(),
            handle_hole_enabled=False,
            handle_hole_diameter=None,
            handle_hole_center_from_handle_end=None,
        )
    )
    pdf = pdf_bytes(on)
    assert pdf == pdf_bytes(on)
    text = PdfReader(BytesIO(pdf)).pages[0].extract_text()
    assert "HANDLE HOLE Ø0.3750" in text
    assert "0.7500 HANDLE END TO HOLE C/L" in text
    assert (
        "HANDLE HOLE" not in PdfReader(BytesIO(pdf_bytes(off))).pages[0].extract_text()
    )
    assert 'id="handle-hole"' in preview_svg(on)
    assert 'cx="9.75"' in preview_svg(on)
    assert 'r="0.1875"' in preview_svg(on)
    assert "handle-hole" not in preview_svg(off)


@pytest.mark.parametrize("enabled", [False, True])
def test_configurator_svg(enabled):
    kwargs = dict(
        paddle_dia=5,
        bore_dia=1.548,
        handle_width=1,
        handle_length_from_bore=10.5,
        thickness=0.125,
        material="304",
    )
    if enabled:
        kwargs.update(
            handle_hole_enabled=True,
            handle_hole_diameter=0.375,
            handle_hole_center_from_handle_end=0.75,
        )
    svg = render_plate_svg(**kwargs)
    assert ('id="handle-hole"' in svg) == enabled
    if enabled:
        assert "HANDLE HOLE &#8960; 0.3750" in svg
        assert "HANDLE END TO HOLE C/L 0.7500" in svg


@pytest.mark.parametrize(
    "change",
    [
        dict(handle_hole_diameter=0.4),
        dict(handle_hole_center_from_handle_end=0.8),
        dict(
            handle_hole_enabled=False,
            handle_hole_diameter=None,
            handle_hole_center_from_handle_end=None,
        ),
    ],
)
def test_hash_changes(change):
    assert digest(canonical(canonical_specification(spec()))) != digest(
        canonical(canonical_specification(spec(**change)))
    )


def test_revision_immutability_and_artifact_verification(tmp_path):
    repo = Repository(tmp_path / "private", "dedicated-handle-hole-key-" + "a" * 32)
    plate = repo.create_plate(
        order_id="OP-HOLE",
        line_id="L1",
        configuration_id="hole",
        customer_id="customer",
        actor="test",
    )
    off = replace(
        spec(),
        handle_hole_enabled=False,
        handle_hole_diameter=None,
        handle_hole_center_from_handle_end=None,
    )

    def freeze(s, current):
        return repo.create_revision(
            plate,
            s,
            expected_current=current,
            reason="optional hole",
            actor="test",
            source_snapshot={},
        )

    r1 = freeze(off, None)
    immutable = repo.revision(r1["id"])
    r2 = freeze(spec(), r1["id"])
    assert r2["number"] == 2
    assert r2["spec_sha256"] != r1["spec_sha256"]
    assert repo.revision(r1["id"]) == immutable
    assert not any(k.startswith("handle_hole") for k in json.loads(r1["spec_json"]))
    assert json.loads(r2["spec_json"])["handle_hole_diameter"] == 0.375
    assert r2["artifacts"]["dxf"]["sha256"] != r1["artifacts"]["dxf"]["sha256"]


def test_package_verifier_rejects_undersized_handle_hole(tmp_path):
    from manufacturing_context import DrawingState

    metadata = DrawingMetadata(state=DrawingState.CUSTOMER_CONFIRMATION)
    g = build_plate_geometry(spec())
    outputs = generate_package(g, tmp_path, include_svg=False, metadata=metadata)
    validate_package(g, metadata, outputs)
    doc = ezdxf.read(StringIO(outputs["dxf"].decode()))
    doc.modelspace().query('CIRCLE[layer=="CUT_HANDLE_HOLE"]')[0].dxf.radius -= 0.0625
    stream = StringIO()
    doc.write(stream)
    with pytest.raises(ValueError, match="Handle hole"):
        validate_package(g, metadata, {**outputs, "dxf": stream.getvalue().encode()})


def observation(text):
    return text, SourceEvidence(page_number=1, raw_text=text, extraction_method="test")


def test_analyzer_contract_evidence_and_distinct_bore():
    from reportlab.pdfgen import canvas

    buffer = BytesIO()
    c = canvas.Canvas(buffer, invariant=1)
    for y, text in [
        (700, "UNITS: IN"),
        (680, "BORE DIAMETER: 1.5480"),
        (660, "HANDLE HOLE Ø0.3750"),
        (640, "0.7500 FROM HANDLE END TO HOLE CENTER"),
    ]:
        c.drawString(50, y, text)
    c.save()
    result = NativeTextExtractionProvider().extract_drawing(
        normalize_document(buffer.getvalue(), "hole.pdf")
    )
    assert result.fields.bore_diameter.value == 1.548
    assert result.fields.handle_hole_enabled.value is True
    assert result.fields.handle_hole_diameter.value == 0.375
    assert result.fields.handle_hole_center_from_handle_end.value == 0.75
    assert result.fields.handle_hole_diameter.evidence
    assert result.fields.handle_hole_diameter.confidence == 0.9
    assert set(DrawingFields.model_fields) >= {
        "handle_hole_enabled",
        "handle_hole_diameter",
        "handle_hole_center_from_handle_end",
    }


@pytest.mark.parametrize(
    "diameter,distance", [(".3750", ".7500"), ("3/8", "3/4"), ("9.525", "19.05")]
)
def test_analyzer_generalized_dimensions(diameter, distance):
    fields = propose_handle_hole(
        [
            observation(f"HANDLE HOLE DIAMETER {diameter}"),
            observation(f"HANDLE END TO HOLE C/L {distance}"),
        ],
        MeasurementUnit.INCH,
    )
    from drawing_intake.value_normalization import parse_number

    assert fields["handle_hole_diameter"].value == parse_number(diameter)
    assert fields["handle_hole_center_from_handle_end"].value == parse_number(distance)


def test_analyzer_abstains_on_unlabeled_and_conflicting_callouts():
    fields = propose_handle_hole(
        [observation("Ø0.3750"), observation("0.7500")], MeasurementUnit.INCH
    )
    assert fields["handle_hole_enabled"].value is None
    conflict = propose_handle_hole(
        [observation("HANDLE HOLE Ø0.3750"), observation("HANDLE HOLE Ø0.5000")],
        MeasurementUnit.INCH,
    )
    assert conflict["handle_hole_diameter"].status == "ambiguous"
    assert conflict["handle_hole_diameter"].value is None


def payload(**changes):
    data = dict(
        quantity=1,
        material="304",
        thickness=0.125,
        handle_width=1,
        handle_length_from_bore=10.5,
        paddle_dia=5,
        bore_dia=1.548,
        bore_tolerance=0.005,
        chamfer=False,
        ships_in_days=14,
    )
    return {**data, **changes}


def test_neutral_pricing_and_configuration_passthrough():
    from api_app import QuoteRequest

    off = payload()
    on = payload(
        handle_hole_enabled=True,
        handle_hole_diameter=0.375,
        handle_hole_center_from_handle_end=0.75,
    )
    assert calculate_quote(QuoteInputs(**off)) == calculate_quote(QuoteInputs(**on))
    normalized = QuoteRequest(**on).model_dump()
    assert PlateSpec.from_configuration(normalized).handle_hole_diameter == 0.375
    assert not any(
        k.startswith("handle_hole") for k in QuoteRequest(**off).model_dump()
    )
    with pytest.raises(ValueError):
        QuoteRequest(**payload(handle_hole_enabled=True))


def test_assisted_confirmation_invalidated_and_missing_fields_hold():
    from drawing_intake.assisted_quote import (
        build_manual_quote_session,
        set_customer_value,
        review_assisted_quote,
        confirm_configuration,
        build_pricing_handoff_preview,
    )

    session = build_manual_quote_session()
    for name, value in payload().items():
        session = set_customer_value(session, name, value)
    confirmed = confirm_configuration(session)
    enabled = set_customer_value(confirmed, "handle_hole_enabled", True)
    review = review_assisted_quote(enabled)
    assert set(review.missing_required_fields) >= {
        "handle_hole_diameter",
        "handle_hole_center_from_handle_end",
    }
    assert not review.confirmation_current
    with pytest.raises(ValueError):
        build_pricing_handoff_preview(enabled)
    enabled = set_customer_value(enabled, "handle_hole_diameter", 0.375)
    enabled = set_customer_value(enabled, "handle_hole_center_from_handle_end", 0.75)
    handoff = build_pricing_handoff_preview(confirm_configuration(enabled))
    assert handoff.quote_request["handle_hole_diameter"] == 0.375


def test_configurator_checkbox_missing_input_fractions_and_off(monkeypatch):
    from test_drawing_phase1k import _quote_app

    for app, _, calls in _quote_app(monkeypatch, checkout_enabled=True):
        toggle = next(c for c in app.checkbox if c.label == "Handle Hole")
        toggle.check().run()
        assert not app.exception
        assert any("Drawing HOLD" in e.value for e in app.error)
        assert not app.session_state["phase1g_customer_confirmation"]
        diameter = next(
            t for t in app.text_input if t.label == "Handle Hole Diameter (in.)"
        )
        distance = next(
            t for t in app.text_input if t.label == "Handle End to Hole Center (in.)"
        )
        diameter.set_value("3/8")
        distance.set_value("3/4")
        app.run()
        assert not app.exception
        assert app.session_state["quote_field_handle_hole_diameter"] == 0.375
        assert (
            app.session_state["quote_field_handle_hole_center_from_handle_end"] == 0.75
        )
        assert not any("Drawing HOLD" in e.value for e in app.error)
        next(c for c in app.checkbox if c.label == "Handle Hole").uncheck().run()
        assert not app.exception
        snapshot = app.session_state["phase1g_form_snapshot"]
        assert snapshot["handle_hole_enabled"] is False
        assert snapshot["handle_hole_diameter"] is None


def test_longitudinal_section_shows_through_hole_without_changing_chamfer():
    from section_geometry import build_section_geometry

    section = build_section_geometry(spec())
    assert len(section.polygons) == 3
    ys = {y for p in section.polygons for _, y in p}
    assert 9.5625 in ys and 9.9375 in ys
    assert section.status == "NONE"


def test_cropped_drawing_secondary_hole_becomes_reviewable_configuration():
    from types import SimpleNamespace
    from test_drawing_cropped_detail import detail
    from drawing_intake.deterministic import interpret_precomputed_region
    from drawing_intake.validation import validate_extraction
    from drawing_intake.confirmation_contract import (
        build_customer_confirmation_contract,
    )
    from drawing_intake.assisted_quote import (
        build_assisted_quote_session,
        review_assisted_quote,
    )

    doc, region, ocr, rendered = detail()
    results, extraction = interpret_precomputed_region(
        doc, region, ocr, rendered=rendered
    )
    assert extraction.fields.bore_diameter.value == 1.25
    assert extraction.fields.tag_hole_diameter.value == 0.375
    assert extraction.fields.handle_hole_diameter.value == 0.375
    assert extraction.fields.handle_hole_center_from_handle_end.value == 0.75
    assert extraction.fields.handle_hole_enabled.value is True
    contract = build_customer_confirmation_contract(
        SimpleNamespace(
            field_results=results,
            extraction=extraction,
            validation=validate_extraction(extraction),
        ),
        document_class="single_plate_drawing",
        candidate_count=1,
        selected_candidate_id=region.region_id,
    )
    session = build_assisted_quote_session(contract)
    assert session.configuration["handle_hole_diameter"].value == 0.375
    assert session.configuration["handle_hole_center_from_handle_end"].value == 0.75
    assert session.configuration["handle_hole_enabled"].value is True
    assert not review_assisted_quote(session).confirmation_current
    hole_proposals = [
        p for p in contract.proposals if p.extraction_field.startswith("handle_hole")
    ]
    assert all(
        p.confirmation_required and p.source_bbox and p.confidence
        for p in hole_proposals
    )


def test_explicit_metric_hole_units_override_global_inches():
    from drawing_intake.handle_hole import propose_handle_hole

    fields = propose_handle_hole([observation("Ø9.525 MM HANDLE HOLE")], "in")
    assert fields["handle_hole_diameter"].normalized_unit == "mm"


def test_feature_off_matches_accepted_golden_bytes():
    baseline = Path(__file__).resolve().parents[1] / "review" / "handle-hole"
    expected = json.loads((baseline / "no-hole-compatibility-hashes.json").read_text())
    from manufacturing_context import DrawingState
    from plate_geometry import manufacturing_record

    off = replace(
        sample_spec(),
        handle_width=1,
        part_identifier="HANDLE-HOLE-REVIEW",
        bore_tolerance=0.005,
        chamfer=False,
    )
    g = build_plate_geometry(off)
    metadata = DrawingMetadata(state=DrawingState.CUSTOMER_CONFIRMATION)
    assert sha256(pdf_bytes(g, metadata)).hexdigest() == expected["pdf_sha256"]
    assert sha256(dxf_bytes(g)).hexdigest() == expected["dxf_sha256"]
    assert sha256(preview_svg(g).encode()).hexdigest() == expected["svg_sha256"]
    svg = render_plate_svg(
        paddle_dia=5,
        bore_dia=1.548,
        handle_width=1,
        handle_length_from_bore=10.5,
        thickness=0.125,
        material=off.material,
        bore_tolerance=0.005,
    )
    assert sha256(svg.encode()).hexdigest() == expected["configurator_svg_sha256"]
    assert (
        digest(canonical(canonical_specification(off)))
        == expected["canonical_spec_sha256"]
    )


def test_restoring_legacy_editor_clears_previous_plate_hole():
    from drawing_intake.checkout_recovery import restore_quote_editor
    state = {
        "quote_field_handle_hole_enabled": True,
        "quote_field_handle_hole_diameter": .375,
        "quote_field_handle_hole_diameter_text": "3/8",
        "quote_field_handle_hole_center_from_handle_end_text": "3/4",
    }
    restore_quote_editor(state, payload())
    assert state["quote_field_handle_hole_enabled"] is False
    assert state["quote_field_handle_hole_diameter"] is None
    assert state["quote_field_handle_hole_diameter_text"] == ""
    assert state["quote_field_handle_hole_center_from_handle_end_text"] == ""
