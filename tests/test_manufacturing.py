from dataclasses import replace
from io import StringIO
import json
import math
import os
from pathlib import Path
import subprocess
import sys
from xml.etree import ElementTree

import ezdxf
import pytest

from plate_geometry import PlateSpec, build_plate_geometry, rough_bore_diameter
from manufacturing_files import (
    dxf_bytes,
    drawing_callouts,
    generate_package,
    pdf_bytes,
    preview_svg,
)


@pytest.fixture
def spec():
    return PlateSpec(5.0, 1.548, 2.0, 10.5, "304 stainless steel", 0.125)


def read_dxf(g):
    return ezdxf.read(StringIO(dxf_bytes(g).decode("ascii")))


def test_exported_exact_sample_geometry(spec):
    doc = read_dxf(build_plate_geometry(spec))
    assert doc.units == ezdxf.units.IN
    assert doc.header["$MEASUREMENT"] == 0
    assert not doc.audit().has_errors
    model = doc.modelspace()
    assert len(model) == 2
    outer = model.query('LWPOLYLINE[layer=="CUT_OUTER"]')[0]
    bore = model.query('CIRCLE[layer=="CUT_BORE"]')[0]
    assert outer.closed
    assert tuple(bore.dxf.center) == (0, 0, 0)
    assert bore.dxf.radius * 2 == pytest.approx(1.423, rel=0, abs=1e-12)
    assert (spec.finished_bore_diameter - 2 * bore.dxf.radius) / 2 == pytest.approx(
        0.0625, rel=0, abs=1e-12
    )
    segments = list(outer.virtual_entities())
    assert [e.dxftype() for e in segments] == [
        "ARC",
        "ARC",
        "LINE",
        "ARC",
        "LINE",
        "ARC",
        "LINE",
        "ARC",
    ]
    arc = segments[0]
    assert arc.dxf.radius * 2 == pytest.approx(5.0, rel=0, abs=1e-12)
    assert tuple(arc.dxf.center) == pytest.approx((0, 0, 0), rel=0, abs=1e-12)
    assert (arc.dxf.end_angle - arc.dxf.start_angle) % 360 > 180
    points = list(outer.get_points("xy"))
    assert max(p[0] for p in points) == pytest.approx(10.5, rel=0, abs=1e-12)
    assert points[6][1] - points[3][1] == pytest.approx(2.0, rel=0, abs=1e-12)
    assert points[0][0] ** 2 + points[0][1] ** 2 == pytest.approx(
        2.5**2, rel=0, abs=1e-12
    )
    assert_radiused_contour(outer, spec)
    # Exact arc extrema rather than tessellated CAM approximations.
    assert min(p[0] for p in points) > 0  # major arc supplies the left circular half
    assert arc.dxf.start_angle < 90 < 180 < 270 < arc.dxf.end_angle % 360


@pytest.mark.parametrize(
    "changes",
    [
        {"finished_od": 0},
        {"finished_bore_diameter": 5},
        {"finished_bore_diameter": -1},
        {"handle_width": 5},
        {"handle_width": 0},
        {"centerline_to_handle_end": 2.5},
        {"thickness": 0},
        {"finished_od": math.nan},
        {"finished_bore_diameter": math.inf},
        {"handle_width": -math.inf},
        {"finished_od": True},
        {"quantity": 0},
        {"quantity": 1.5},
        {"bore_tolerance": -0.01},
        {"bore_tolerance": 4},
        {"material": ""},
        {"chamfer": False, "chamfer_width": 0.01},
        {"chamfer": "yes"},
        {"marking": "line\nbreak"},
        {"part_identifier": "x" * 41},
    ],
)
def test_invalid_specs_fail(spec, changes):
    with pytest.raises(ValueError):
        replace(spec, **changes)


@pytest.mark.parametrize("diameter", [0.01, 0.124, 0.125])
def test_invalid_rough_bore_produces_no_files(spec, diameter, tmp_path):
    g = build_plate_geometry(replace(spec, finished_bore_diameter=diameter))
    with pytest.raises(ValueError, match="rough bore"):
        generate_package(g, tmp_path / "invalid")
    assert not (tmp_path / "invalid").exists()


def test_positive_rough_bore_limit(spec):
    assert rough_bore_diameter(
        replace(spec, finished_bore_diameter=0.126)
    ) == pytest.approx(0.001, rel=0, abs=1e-12)


def test_tolerance_cannot_consume_all_stock(spec):
    with pytest.raises(ValueError, match="stock"):
        rough_bore_diameter(replace(spec, bore_tolerance=0.125))


def test_pdf_receives_finished_values_and_discloses_missing_requirements(
    spec, monkeypatch
):
    from reportlab.pdfgen.canvas import Canvas

    texts = []
    original = Canvas.drawString

    def capture(self, x, y, text, *args, **kwargs):
        texts.append(text)
        return original(self, x, y, text, *args, **kwargs)

    monkeypatch.setattr(Canvas, "drawString", capture)
    g = build_plate_geometry(spec)
    assert drawing_callouts(g)["finished_bore_diameter"] == 1.548
    assert pdf_bytes(g).startswith(b"%PDF")
    assert any("Ø1.548" in t for t in texts)
    assert not any("1.423" in t for t in texts)
    assert any("BORE TOLERANCE: NOT SPECIFIED - HOLD" in t for t in texts)


def test_supplied_requirements_reach_drawing(spec, monkeypatch):
    from reportlab.pdfgen.canvas import Canvas

    texts = []
    monkeypatch.setattr(
        Canvas, "drawString", lambda self, x, y, text, *a, **k: texts.append(text)
    )
    pdf_bytes(
        build_plate_geometry(
            replace(
                spec,
                bore_tolerance=0.005,
                chamfer=True,
                chamfer_width=0.02,
                chamfer_angle_degrees=45,
                chamfer_side="downstream",
                marking="UPSTREAM",
                quantity=3,
            )
        )
    )
    assert any("BORE TOLERANCE: +/- 0.005" in t for t in texts)
    assert any("width 0.02; angle 45; side downstream" in t for t in texts)
    assert "UPSTREAM" in texts
    assert any("MARKING:" in t for t in texts)
    assert "NO. REQ'D." in texts
    assert "3" in texts


def test_outputs_repeat_identically_in_process(spec, tmp_path):
    g = build_plate_geometry(spec)
    first = generate_package(g, tmp_path / "a")
    second = generate_package(g, tmp_path / "b")
    assert first == second
    record = json.loads(first["json"])
    assert record["manufacturing"]["rough_bore_diameter"] == 1.423
    assert record["specification"]["finished_bore_diameter"] == 1.548
    assert record["manufacturing"]["rough_bore_diameter_allowance"] == 0.125
    assert record["manufacturing"]["radial_machining_stock"] == 0.0625


def test_outputs_repeat_across_processes(tmp_path):
    root = Path(__file__).resolve().parents[1]
    for name, seed in (("one", "1"), ("two", "2"), ("three", "17")):
        subprocess.run(
            [
                sys.executable,
                str(root / "prototype_manufacturing.py"),
                "--output",
                str(tmp_path / name),
            ],
            check=True,
            cwd=root,
            env={**os.environ, "PYTHONHASHSEED": seed},
            capture_output=True,
        )
    for file in (tmp_path / "one").iterdir():
        assert file.read_bytes() == (tmp_path / "two" / file.name).read_bytes()
        assert file.read_bytes() == (tmp_path / "three" / file.name).read_bytes()


def test_fixed_metadata_option_is_restored(spec):
    prior = ezdxf.options.write_fixed_meta_data_for_testing
    dxf_bytes(build_plate_geometry(spec))
    assert ezdxf.options.write_fixed_meta_data_for_testing == prior


def test_canonical_svg_uses_finished_circle(spec):
    g = build_plate_geometry(spec)
    root = ElementTree.fromstring(preview_svg(g))
    circle = root.find("{http://www.w3.org/2000/svg}circle")
    assert float(circle.attrib["r"]) * 2 == 1.548
    path = root.find("{http://www.w3.org/2000/svg}path").attrib["d"]
    assert "A 2.5 2.5" in path
    assert path.count("A 0.03125 0.03125") == 4
    for segment in g.segments:
        x, y = segment.end
        if segment.kind == "arc":
            assert (
                f"A {segment.radius} {segment.radius} 0 {int(abs(segment.sweep_degrees)>180)} {int(segment.sweep_degrees<0)} {x} {-y}"
                in path
            )
        else:
            assert f"L {x} {-y}" in path


def test_existing_configuration_adapter():
    s = PlateSpec.from_configuration(
        dict(
            paddle_dia=5,
            bore_dia=1.548,
            handle_width=2,
            handle_length_from_bore=10.5,
            material="304",
            thickness=0.125,
            bore_tolerance=0.005,
            chamfer=True,
            chamfer_width=0.02,
            handle_label="ABC",
            quantity=2,
            ships_in_days=14,
        )
    )
    assert s.finished_bore_diameter == 1.548
    assert s.centerline_to_handle_end == 10.5
    assert s.bore_tolerance == 0.005
    assert s.marking == "ABC"


@pytest.mark.parametrize(
    "od,bore,width,length",
    [(1, 0.25, 0.125, 0.75), (3, 1, 1.5, 9), (48, 19, 1.5, 25), (5, 1, 4.99, 10.5)],
)
def test_contour_varies_with_spec(spec, od, bore, width, length):
    s = replace(
        spec,
        finished_od=od,
        finished_bore_diameter=bore,
        handle_width=width,
        centerline_to_handle_end=length,
    )
    doc = read_dxf(build_plate_geometry(s))
    outer = doc.modelspace().query("LWPOLYLINE")[0]
    arc = list(outer.virtual_entities())[0]
    assert arc.dxf.radius == pytest.approx(od / 2, rel=0, abs=1e-12)
    assert tuple(arc.dxf.center) == pytest.approx((0, 0, 0), rel=0, abs=1e-12)
    assert list(outer.get_points("xy"))[4] == pytest.approx(
        (length, -width / 2 + 0.03125), rel=0, abs=1e-12
    )


def assert_radiused_contour(outer, spec):
    """Check exported primitives independently, including directed G1 joins."""
    vertices = list(outer.get_points("xyb"))
    entities = list(outer.virtual_entities())
    assert len(vertices) == len(entities) == 8
    assert len(set(vertices)) == 8
    assert outer.closed
    ends = []
    tangent_pairs = []
    arcs = []
    for entity, vertex in zip(entities, vertices):
        if entity.dxftype() == "ARC":
            arcs.append(entity)
            direction = 1 if vertex[2] > 0 else -1
            start, end = entity.start_point, entity.end_point
            if direction < 0:
                start, end = end, start
            center = entity.dxf.center

            def tangent(point):
                x, y = point.x - center.x, point.y - center.y
                norm = math.hypot(x, y)
                return (-direction * y / norm, direction * x / norm)

            tangents = tangent(start), tangent(end)
        else:
            start, end = entity.dxf.start, entity.dxf.end
            dx, dy = end.x - start.x, end.y - start.y
            length = math.hypot(dx, dy)
            assert length > 0
            tangents = ((dx / length, dy / length),) * 2
        ends.append((start, end))
        tangent_pairs.append(tangents)
    assert len(arcs) == 5
    for arc in arcs[1:]:
        assert arc.dxf.radius == pytest.approx(0.03125, rel=0, abs=1e-12)
    for i, (_, end) in enumerate(ends):
        next_i = (i + 1) % len(ends)
        assert tuple(end) == pytest.approx(tuple(ends[next_i][0]), rel=0, abs=1e-12)
        assert tangent_pairs[i][1] == pytest.approx(
            tangent_pairs[next_i][0], rel=0, abs=1e-12
        )
    R, h, L = spec.finished_od / 2, spec.handle_width / 2, spec.centerline_to_handle_end
    for neck in (arcs[1], arcs[4]):
        x, y, _ = neck.dxf.center
        assert math.hypot(x, y) == pytest.approx(R + 0.03125, rel=0, abs=1e-12)
        assert abs(y) - h == pytest.approx(0.03125, rel=0, abs=1e-12)
    for tip in arcs[2:4]:
        x, y, _ = tip.dxf.center
        assert x + tip.dxf.radius == pytest.approx(L, rel=0, abs=1e-12)
        assert abs(y) + tip.dxf.radius == pytest.approx(h, rel=0, abs=1e-12)


@pytest.mark.parametrize(
    "od,bore,width,length",
    [
        (1, 0.25, 0.125, 0.75),
        (3, 1, 1.5, 9),
        (48, 19, 1.5, 25),
        (5, 1, 4.99, 10.5),
        (0.5, 0.2, 0.07, 0.5),
        (12, 4, 3, 8),
    ],
)
def test_all_radii_tangency_and_connectivity_across_sizes(
    spec, od, bore, width, length
):
    s = replace(
        spec,
        finished_od=od,
        finished_bore_diameter=bore,
        handle_width=width,
        centerline_to_handle_end=length,
    )
    doc = read_dxf(build_plate_geometry(s))
    assert not doc.audit().has_errors
    assert len(doc.modelspace()) == 2
    assert_radiused_contour(doc.modelspace().query("LWPOLYLINE")[0], s)


@pytest.mark.parametrize("width,length", [(0.0625, 10.5), (0.04, 10.5), (0.125, 2.501)])
def test_radius_does_not_fit_fails_explicitly(spec, width, length, tmp_path):
    with pytest.raises(ValueError, match="radius|radii"):
        generate_package(
            build_plate_geometry(
                replace(spec, handle_width=width, centerline_to_handle_end=length)
            ),
            tmp_path / "invalid",
        )
    assert not (tmp_path / "invalid").exists()


def test_record_exposes_versioned_corner_rule(spec, tmp_path):
    data = json.loads(generate_package(build_plate_geometry(spec), tmp_path)["json"])
    assert data["schema_version"] == 4
    assert data["geometry"]["version"] == "straight-handle-r03125-v2-prototype"
    assert (
        data["geometry"]["corner_radius"]
        == data["manufacturing"]["corner_radius"]
        == 0.03125
    )
    assert data["geometry"]["corner_count"] == 4
    assert len(data["geometry"]["segments"]) == 8


def test_pdf_draws_canonical_arcs_and_calls_out_exact_radius(spec, monkeypatch):
    from reportlab.pdfgen.pathobject import PDFPathObject
    from reportlab.pdfgen.canvas import Canvas

    arcs = []
    texts = []
    original = PDFPathObject.arcTo

    def capture(self, *args, **kwargs):
        arcs.append(args)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(PDFPathObject, "arcTo", capture)
    monkeypatch.setattr(
        Canvas, "drawString", lambda self, x, y, text, *a, **k: texts.append(text)
    )
    g = build_plate_geometry(spec)
    pdf_bytes(g)
    expected = []
    for segment in g.segments:
        if segment.kind == "arc":
            x, y = segment.center
            r = segment.radius
            expected.append(
                (
                    x - r,
                    y - r,
                    x + r,
                    y + r,
                    segment.start_degrees,
                    segment.sweep_degrees,
                )
            )
    assert arcs == expected
    assert any("4X R 0.03125" in text for text in texts)
    assert any("P3E" in text for text in texts)
