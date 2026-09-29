from dataclasses import replace
from math import atan2, degrees
import pytest
from plate_geometry import PlateSpec, build_plate_geometry
from section_geometry import build_section_geometry
from manufacturing_files import pdf_bytes, generate_package
from reportlab.pdfgen.canvas import Canvas


@pytest.fixture
def spec():
    return PlateSpec(
        5,
        1.548,
        2,
        10.5,
        "304",
        0.125,
        chamfer=True,
        chamfer_width=0.04,
        chamfer_angle_degrees=45,
        chamfer_side="downstream",
        flow_orientation="left-to-right",
        chamfer_width_definition="radial-angle-from-face",
    )


@pytest.mark.parametrize(
    "thickness,angle", [(0.125, 45), (0.25, 45), (0.125, 30), (0.5, 60)]
)
def test_numeric_chamfer_section(spec, thickness, angle):
    s = replace(spec, thickness=thickness, chamfer_angle_degrees=angle)
    sec = build_section_geometry(s)
    p = sec.polygons[0]
    assert sec == build_section_geometry(s)
    assert sec.status == "CONFIGURED"
    assert max(x for x, y in p) == thickness
    assert min(y for x, y in p) == pytest.approx(0.774, rel=0, abs=1e-12)
    dx = p[2][0] - p[1][0]
    dy = p[2][1] - p[1][1]
    assert degrees(atan2(dx, dy)) == pytest.approx(angle, rel=0, abs=1e-12)
    assert dy == pytest.approx(0.04, rel=0, abs=1e-12)
    assert sec.chamfer_axial_depth == pytest.approx(dx, rel=0, abs=1e-12)
    assert sec.straight_land == pytest.approx(thickness - dx, rel=0, abs=1e-12)
    assert sec.straight_land > 0
    # Both filled polygons are simple, positive-area closed regions (implicit closing edge).
    for poly in sec.polygons:
        assert len(set(poly)) == len(poly)
        edges = list(zip(poly, poly[1:] + poly[:1]))
        area = sum(a[0] * b[1] - b[0] * a[1] for a, b in edges) / 2
        assert area > 0

        def cross(a, b, c):
            return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])

        for i, (a, b) in enumerate(edges):
            for j, (c, d) in enumerate(edges):
                if j <= i + 1 or (i == 0 and j == len(edges) - 1):
                    continue
                assert not (
                    cross(a, b, c) * cross(a, b, d) < 0
                    and cross(c, d, a) * cross(c, d, b) < 0
                )


@pytest.mark.parametrize(
    "field",
    [
        "chamfer_width",
        "chamfer_angle_degrees",
        "chamfer_side",
        "flow_orientation",
        "chamfer_width_definition",
    ],
)
def test_each_missing_parameter_is_hold(spec, field, monkeypatch):
    s = replace(spec, **{field: None})
    sec = build_section_geometry(s)
    assert sec.status == "INCOMPLETE - HOLD"
    assert field in sec.missing
    assert not sec.chamfer_drawn
    assert all(len(p) == 4 for p in sec.polygons)
    labels = []
    monkeypatch.setattr(
        Canvas, "drawString", lambda self, x, y, t, *a, **k: labels.append(t)
    )
    pdf_bytes(build_plate_geometry(s))
    assert any("CHAMFER: INCOMPLETE - HOLD" in t for t in labels)


def test_none_is_distinct_from_incomplete(spec, monkeypatch):
    s = replace(
        spec,
        chamfer=False,
        chamfer_width=None,
        chamfer_angle_degrees=None,
        chamfer_side=None,
    )
    section = build_section_geometry(s)
    assert section.status == "NONE" and not section.chamfer_drawn
    assert all(len(p) == 4 for p in section.polygons)
    labels = []
    monkeypatch.setattr(
        Canvas, "drawString", lambda self, x, y, t, *a, **k: labels.append(t)
    )
    pdf_bytes(build_plate_geometry(s))
    assert any("CHAMFER: NONE" in t for t in labels)


def test_opposite_side_and_flow_mirror(spec):
    right = build_section_geometry(spec)
    left = build_section_geometry(replace(spec, chamfer_side="upstream"))
    reversed_flow = build_section_geometry(
        replace(spec, flow_orientation="right-to-left")
    )
    assert left.polygons == reversed_flow.polygons
    for a, b in zip(right.polygons, left.polygons):
        mirrored = sorted((spec.thickness - x, y) for x, y in a)
        assert len(mirrored) == len(b)
        for p, q in zip(mirrored, sorted(b)):
            assert p == pytest.approx(q, rel=0, abs=1e-12)


@pytest.mark.parametrize(
    "updates",
    [{"chamfer_width": 0.125}, {"chamfer_width": 2}, {"chamfer_angle_degrees": 89.9}],
)
def test_invalid_fit_rejected_before_writing(spec, updates, tmp_path):
    with pytest.raises(ValueError, match="fit"):
        generate_package(
            build_plate_geometry(replace(spec, **updates)), tmp_path / "bad"
        )
    assert not (tmp_path / "bad").exists()


def test_axial_depth_convention(spec):
    sec = build_section_geometry(
        replace(
            spec,
            chamfer_width=0.04,
            chamfer_angle_degrees=30,
            chamfer_width_definition="axial-depth-angle-from-face",
        )
    )
    assert sec.chamfer_axial_depth == 0.04
    assert sec.chamfer_radial_width == pytest.approx(
        0.0692820323027551, rel=0, abs=1e-12
    )


def test_adapter_preserves_complete_customer_chamfer(spec):
    d = dict(
        paddle_dia=5,
        bore_dia=1.548,
        handle_width=2,
        handle_length_from_bore=10.5,
        material="304",
        thickness=0.125,
        chamfer=True,
        chamfer_width=0.04,
        chamfer_angle_degrees=30,
        chamfer_side="upstream",
        flow_orientation="right-to-left",
        chamfer_width_definition="radial-angle-from-face",
    )
    s = PlateSpec.from_configuration(d)
    assert s.chamfer_angle_degrees == 30 and s.chamfer_side == "upstream"
    assert build_section_geometry(s).status == "CONFIGURED"
