"""Presentation changes cannot change canonical manufacturing facts."""

from dataclasses import replace
from hashlib import sha256
from math import atan2, degrees
from pathlib import Path
import pytest
from reportlab.pdfgen.canvas import Canvas
import manufacturing_drawing as drawing
from drawing_presentation import build_presentation, DEFAULT_LAYOUT
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
    # Move the paper zone, never distort individual features.
    changed = build_presentation(g, replace(DEFAULT_LAYOUT, left=64, right=624))
    second = drawing.render_pdf(g, presentation=changed)
    assert first != second
    assert labels == original_labels
    for value in (
        "Ø1.548",
        "10.50",
        "2.00",
        ".125",
        ".040 RAD",
        "AXIAL DEPTH .0400 / LAND .0850",
        "45°",
    ):
        assert value in labels
    assert before == (manufacturing_record(g), dxf_bytes(g), preview_svg(g))


@pytest.mark.parametrize("length", [2.7, 10.5, 30])
def test_right_facing_and_explicit_break_only_affect_display(length):
    g = build_plate_geometry(replace(sample_spec(), centerline_to_handle_end=length))
    v = build_presentation(g)
    assert v.point((length, 0)) == pytest.approx((v.tip_x, v.cy), abs=1e-12, rel=0)
    assert v.point((-g.radius, 0)) == (v.layout.left, v.cy)
    assert g.spec.centerline_to_handle_end == length
    assert max(p[0] for seg in g.segments for p in (seg.start, seg.end)) == length
    assert v.tip_x - v.cx == pytest.approx((length - v.removed_length) * v.scale)
    if length == 2.7:
        assert not v.broken
    if length == 30:
        assert v.broken and v.removed_length > 0


@pytest.mark.parametrize("flow", ["left-to-right", "right-to-left"])
@pytest.mark.parametrize("side", ["upstream", "downstream"])
@pytest.mark.parametrize("angle", [30, 45, 60])
def test_detail_angle_side_and_flow_survive_relocation(flow, side, angle, monkeypatch):
    g = example(flow_orientation=flow, chamfer_side=side, chamfer_angle_degrees=angle)
    sec = build_section_geometry(g.spec)
    polys = []
    original_polygon = drawing.hatched_polygon

    def capture_polygon(c, points):
        polys.append(points)
        original_polygon(c, points)

    arrows = []
    original_arrow = drawing.arrow

    def capture_arrow(c, x, y, dx, dy):
        arrows.append((x, y, dx, dy))
        original_arrow(c, x, y, dx, dy)

    monkeypatch.setattr(drawing, "hatched_polygon", capture_polygon)
    monkeypatch.setattr(drawing, "arrow", capture_arrow)
    drawing.render_pdf(g)
    assert len(polys) == 1  # Detail B remains; main view is now an unsectioned edge.
    upper = polys[0]
    slope = (upper[1], upper[2]) if sec.face == "right" else (upper[0], upper[1])
    dx, dy = (abs(slope[1][i] - slope[0][i]) for i in (0, 1))
    assert degrees(atan2(dx, dy)) == pytest.approx(angle, abs=1e-11, rel=0)
    assert sec.face == (
        "left" if (side == "upstream") == (flow == "left-to-right") else "right"
    )
    assert (
        max(x for x, y in upper) - min(x for x, y in upper)
        > g.spec.thickness * build_presentation(g).scale
    )
    flow_arrows = [a for a in arrows if a[1] == 230]
    assert len(flow_arrows) == 1
    assert flow_arrows[0][2] == (1 if flow == "right-to-left" else -1)


@pytest.mark.parametrize("enabled", [False, True])
def test_no_fake_bevel_when_none_or_incomplete(enabled, monkeypatch):
    g = build_plate_geometry(replace(sample_spec(), chamfer=enabled))
    sec = build_section_geometry(g.spec)
    assert not sec.chamfer_drawn
    assert sec.status == ("INCOMPLETE - HOLD" if enabled else "NONE")
    for polygon in sec.polygons:
        assert len(polygon) == 4
        assert len({x for x, y in polygon}) == 2
        assert len({y for x, y in polygon}) == 2
    monkeypatch.setattr(
        drawing, "draw_chamfer_detail", lambda *a: pytest.fail("invented bevel")
    )
    drawing.render_pdf(g)


def test_locked_golden_pdf_visual_fixture():
    g = build_plate_geometry(replace(sample_spec(), part_identifier="PROTOTYPE-001"))
    data = drawing.render_pdf(g)
    expected = (
        (Path(__file__).parent / "fixtures/true-scale-manufacturing-print.sha256")
        .read_text()
        .strip()
    )
    assert (
        sha256(data).hexdigest() == expected
    ), "Review raster visually before explicit fixture refresh"
    assert data == drawing.render_pdf(g)
