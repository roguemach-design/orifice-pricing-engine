"""NTS is a PDF-only mapping; dimensions remain facts from the exact spec."""

from dataclasses import replace
from hashlib import sha256
from math import atan2, degrees
from pathlib import Path
import pytest
from reportlab.pdfgen.canvas import Canvas
import manufacturing_drawing as drawing
from manufacturing_files import dxf_bytes, preview_svg
from plate_geometry import build_plate_geometry, manufacturing_record
from prototype_manufacturing import sample_spec
from section_geometry import build_section_geometry


def example(**updates):
    values = dict(
        chamfer=True,
        chamfer_width=0.04,
        chamfer_angle_degrees=45,
        chamfer_side="downstream",
        flow_orientation="left-to-right",
        chamfer_width_definition="radial-angle-from-face",
    )
    values.update(updates)
    return build_plate_geometry(replace(sample_spec(), **values))


def test_presentation_is_independent_and_labels_stay_exact(monkeypatch):
    g = example()
    before = (manufacturing_record(g), dxf_bytes(g), preview_svg(g))
    labels = []
    for method in ("drawString", "drawCentredString"):
        monkeypatch.setattr(
            Canvas, method, lambda self, x, y, t, *a, **k: labels.append(t)
        )
    first = drawing.render_pdf(g)
    original_labels = labels[:]
    labels.clear()
    changed = replace(
        drawing.GOLDEN_PRESENTATION,
        paddle_radius=100,
        handle_tip=620,
        bore_radius=57,
        section_thickness=26,
    )
    second = drawing.render_pdf(g, presentation=changed)
    assert first != second
    assert labels == original_labels
    for value in (
        "Ø1.548",
        "10.500 C/L TO HANDLE END",
        "2.000",
        "t = 0.125",
        "0.040 RAD",
        "AXIAL DEPTH 0.0400 / LAND 0.0850",
        "45°",
    ):
        assert value in labels
    assert before == (manufacturing_record(g), dxf_bytes(g), preview_svg(g))


@pytest.mark.parametrize("length", [2.7, 10.5, 30])
def test_upward_rotation_and_shortened_handle_only_affect_display(length):
    g = build_plate_geometry(replace(sample_spec(), centerline_to_handle_end=length))
    v = drawing.GOLDEN_PRESENTATION
    assert v.point(g, (length, 0)) == pytest.approx(
        (v.cx, v.handle_tip), abs=1e-12, rel=0
    )
    assert v.point(g, (-g.radius, 0)) == (v.cx, v.cy - v.paddle_radius)
    assert g.spec.centerline_to_handle_end == length
    assert max(p[0] for seg in g.segments for p in (seg.start, seg.end)) == length
    if length == 10.5:
        assert v.handle_tip - v.cy < length * v.scale(g) / 2


@pytest.mark.parametrize("flow", ["left-to-right", "right-to-left"])
@pytest.mark.parametrize("side", ["upstream", "downstream"])
@pytest.mark.parametrize("angle", [30, 45, 60])
def test_section_angle_side_and_flow_survive_nts(flow, side, angle, monkeypatch):
    g = example(flow_orientation=flow, chamfer_side=side, chamfer_angle_degrees=angle)
    sec = build_section_geometry(g.spec)
    v = drawing.GOLDEN_PRESENTATION
    polys = drawing.section_presentation(g, sec)
    upper = polys[0]
    slope = (upper[1], upper[2]) if sec.face == "right" else (upper[0], upper[1])
    dx, dy = (abs(slope[1][i] - slope[0][i]) for i in (0, 1))
    assert degrees(atan2(dx, dy)) == pytest.approx(angle, abs=1e-11, rel=0)
    assert sec.face == (
        "left" if (side == "upstream") == (flow == "left-to-right") else "right"
    )
    width = max(x for x, y in upper) - min(x for x, y in upper)
    assert width > g.spec.thickness * v.scale(g)
    arrows = []
    original = drawing.arrow

    def capture(c, x, y, dx, dy):
        arrows.append((x, y, dx, dy))
        original(c, x, y, dx, dy)

    monkeypatch.setattr(drawing, "arrow", capture)
    drawing.render_pdf(g)
    flow_arrows = [a for a in arrows if a[1] == v.cy + 25]
    assert len(flow_arrows) == 1
    # Arrow helper's vector points back into the shaft, opposite flow.
    assert flow_arrows[0][2] == (1 if flow == "right-to-left" else -1)


@pytest.mark.parametrize("enabled", [False, True])
def test_no_fake_bevel_when_none_or_incomplete(enabled):
    g = build_plate_geometry(replace(sample_spec(), chamfer=enabled))
    sec = build_section_geometry(g.spec)
    polygons = drawing.section_presentation(g, sec)
    assert not sec.chamfer_drawn
    assert sec.status == ("INCOMPLETE - HOLD" if enabled else "NONE")
    for polygon in polygons:
        assert len(polygon) == 4
        assert len({x for x, y in polygon}) == 2
        assert len({y for x, y in polygon}) == 2


def test_locked_golden_pdf_visual_fixture():
    g = build_plate_geometry(replace(sample_spec(), part_identifier="PROTOTYPE-001"))
    data = drawing.render_pdf(g)
    expected = (
        (Path(__file__).parent / "fixtures/phase3e-manufacturing-print.sha256")
        .read_text()
        .strip()
    )
    assert (
        sha256(data).hexdigest() == expected
    ), "Review raster visually before explicit fixture refresh"
    assert data == drawing.render_pdf(g)
