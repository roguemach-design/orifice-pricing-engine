from math import hypot
from drawing_presentation import build_presentation
from drawing_standards import inch
from plate_geometry import PlateSpec, build_plate_geometry
import re
from xml.etree import ElementTree

import pytest

from plate_preview import render_plate_svg


def test_svg_contains_customer_dimensions_and_drawing_disclaimer():
    svg = render_plate_svg(
        paddle_dia=3.0,
        bore_dia=1.0,
        handle_width=1.5,
        handle_length_from_bore=9.0,
        thickness=0.125,
        material="304",
        bore_tolerance=0.005,
        handle_label="UPSTREAM",
        chamfer=True,
    )

    assert "OD Ø3.000 in." in svg
    assert "BORE Ø1.000" in svg
    assert "HANDLE 1.50" in svg
    assert "C/L TO END 9.00 in." in svg
    assert "t = .125 in." in svg
    assert "±.005 in." in svg
    assert "UPSTREAM" in svg
    assert "YES — WIDTH NOT ENTERED" in svg
    assert "Configuration preview" in svg
    assert "Not an approved manufacturing drawing" in svg
    assert "CONFIGURATION DRAWING · SCALE 1:1" in svg
    assert 'role="img"' in svg
    ElementTree.fromstring(svg)


def test_svg_escapes_customer_controlled_text():
    svg = render_plate_svg(
        paddle_dia=3,
        bore_dia=1,
        handle_width=1,
        handle_length_from_bore=5,
        thickness=0.25,
        material="<script>alert(1)</script>",
        handle_label="A&B <UPSTREAM>",
    )

    assert "<script>" not in svg
    assert "&lt;script&gt;" in svg
    assert "A&amp;B &lt;UPSTREAM&gt;" in svg


@pytest.mark.parametrize(
    ("paddle_dia", "bore_dia", "handle_width", "handle_length"),
    [
        (1.0, 0.125, 0.125, 0.75),
        (3.0, 1.0, 1.5, 9.0),
        (48.0, 19.0, 1.5, 25.0),
    ],
)
def test_svg_is_valid_for_small_default_and_maximum_configurations(
    paddle_dia, bore_dia, handle_width, handle_length
):
    svg = render_plate_svg(
        paddle_dia=paddle_dia,
        bore_dia=bore_dia,
        handle_width=handle_width,
        handle_length_from_bore=handle_length,
        thickness=0.5,
        material="Carbon Steel",
    )

    root = ElementTree.fromstring(svg)
    assert root.tag.endswith("svg")
    assert f"{inch(paddle_dia)} in." in svg
    assert f"{inch(bore_dia)}" in svg
    assert f"HANDLE {inch(handle_width, 2)}" in svg
    assert f"{inch(handle_length, 2)} in." in svg
    assert "Carbon Steel" in svg
    assert ".500 in." in svg


def test_material_thickness_and_chamfer_update_title_block_with_customer_width():
    common = dict(
        paddle_dia=6,
        bore_dia=2,
        handle_width=1.5,
        handle_length_from_bore=10,
    )

    stainless = render_plate_svg(
        material="304", thickness=0.125, chamfer=False, **common
    )
    carbon = render_plate_svg(
        material="Carbon Steel",
        thickness=0.5,
        chamfer=True,
        chamfer_width=0.062,
        **common,
    )

    assert stainless != carbon
    assert "304" in stainless
    assert ".125 in." in stainless
    assert "Carbon Steel" in carbon
    assert ".500 in." in carbon
    assert "CHAMFER" in carbon
    assert "YES — .062 in." in carbon


@pytest.mark.parametrize(
    ("od", "handle_width", "handle_length"),
    [
        (3.0, 1.5, 9.0),
        (5.0, 2.0, 9.0),
        (8.5, 1.5, 14.0),
        (16.0, 1.25, 20.0),
        (1.0, 0.9, 2.0),  # Wide handle on a small plate.
    ],
)
def test_outer_profile_has_one_tangent_symmetric_contour(
    od, handle_width, handle_length
):
    svg = render_plate_svg(
        paddle_dia=od,
        bore_dia=od / 3,
        handle_width=handle_width,
        handle_length_from_bore=handle_length,
        thickness=0.125,
        material="304",
    )
    root = ElementTree.fromstring(svg)
    namespace = {"svg": "http://www.w3.org/2000/svg"}
    outline = root.find(".//svg:path[@id='plate-outline']", namespace)
    assert outline is not None
    assert outline.attrib.get("fill", "none") == "none"
    assert (
        len(root.findall(".//svg:circle", namespace)) == 1
    )  # Bore; centerlines have no dot.
    assert f"OD Ø{inch(od)}" in svg
    assert f"HANDLE {inch(handle_width, 2)}" in svg
    path = outline.attrib["d"]
    g = build_plate_geometry(
        PlateSpec(od, od / 3, handle_width, handle_length, "304", 0.125)
    )
    v = build_presentation(g)
    assert path.count("M ") == (2 if v.broken else 1)
    arcs = re.findall(r"A ([\d.]+),([\d.]+) 0 ([01]) ([01]) ([\d.]+),([\d.]+)", path)
    assert len(arcs) == 5  # OD plus all four exact canonical fillets.
    assert (
        sum(
            float(a[0]) == pytest.approx(g.corner_radius * v.scale, abs=1e-6)
            for a in arcs
        )
        == 4
    )
    paddle = next(a for a in arcs if a[2] == "1")
    assert float(paddle[0]) == float(paddle[1]) == g.radius * v.scale
    px, py = map(float, paddle[-2:])
    assert hypot(px - v.cx, py - v.cy) == pytest.approx(g.radius * v.scale, abs=1e-6)
    # Both neck tangent points are symmetric, on the OD, and on the fillet.
    lower = g.segments[1]
    lx, ly = v.point(lower.center)
    assert hypot(px - lx, py - ly) == pytest.approx(g.corner_radius * v.scale, abs=1e-6)
    assert hypot(lx - v.cx, ly - v.cy) == pytest.approx(
        (g.radius + g.corner_radius) * v.scale, abs=1e-6
    )
    ux, uy = v.point(g.segments[-1].center)
    assert ux == pytest.approx(lx)
    assert uy + ly == pytest.approx(2 * v.cy)
    assert v.tip_x > ux > px > v.cx
    assert all(float(a[0]) == float(a[1]) for a in arcs)
