"""Measure serialized SVG/PDF paths independently of the presentation mapping."""

from dataclasses import replace
from io import BytesIO
from pathlib import Path
import json
import math
import re
from xml.etree import ElementTree as ET
import pdfplumber
from pypdf import PdfReader
import pytest
from drawing_presentation import (
    build_presentation,
    BREAK_FROM_JUNCTION,
    BREAK_GAP_POINTS,
)
from drawing_standards import inch
from manufacturing_drawing import render_pdf, DrawingMetadata
from plate_geometry import PlateSpec, build_plate_geometry
from plate_preview import render_plate_svg
from scripts.drawing_isolation_hashes import hashes

NS = {"s": "http://www.w3.org/2000/svg"}
CASES = [
    (1, 0.2, 0.25, 1, None),
    (3, 0.15, 1.5, 9, None),
    (3, 2.85, 1.5, 9, None),
    (3, 1, 1.5, 2, None),
    (3, 1, 1.5, 30, None),
    (6, 2, 1.5, 14, None),
    (16, 5, 1.25, 20, None),
    (48, 19, 1.5, 25, None),
    (3, 1, 1.5, 9, (0.5, 0.75)),
    (3, 1, 1.5, 30, (0.5, 3.5)),
    (5, 1.548, 4.8, 6, None),
]


def svg_for(s):
    return render_plate_svg(
        paddle_dia=s.finished_od,
        bore_dia=s.finished_bore_diameter,
        handle_width=s.handle_width,
        handle_length_from_bore=s.centerline_to_handle_end,
        thickness=s.thickness,
        material=s.material,
        bore_tolerance=s.bore_tolerance,
        chamfer=s.chamfer,
        chamfer_width=s.chamfer_width,
        handle_hole_enabled=s.handle_hole_enabled,
        handle_hole_diameter=s.handle_hole_diameter,
        handle_hole_center_from_handle_end=s.handle_hole_center_from_handle_end,
    )


def extrema(curve):
    # pdfplumber's curve bbox uses endpoints only. Evaluate cubic extrema as well.
    values = []
    current = None
    for command in curve["path"]:
        op, *points = command
        if op in ("m", "l"):
            current = points[0]
            values.append(current)
        elif op == "c":
            p0, p1, p2, p3 = current, *points
            candidates = {0.0, 1.0}
            for axis in (0, 1):
                a = -p0[axis] + 3 * p1[axis] - 3 * p2[axis] + p3[axis]
                b = 2 * (p0[axis] - 2 * p1[axis] + p2[axis])
                c = p1[axis] - p0[axis]
                if abs(a) < 1e-12:
                    if abs(b) > 1e-12:
                        candidates.add(-c / b)
                elif b * b - 4 * a * c >= 0:
                    d = math.sqrt(b * b - 4 * a * c)
                    candidates.update(((-b + d) / (2 * a), (-b - d) / (2 * a)))
            for t in candidates:
                if 0 <= t <= 1:
                    values.append(
                        tuple(
                            (1 - t) ** 3 * p0[i]
                            + 3 * (1 - t) ** 2 * t * p1[i]
                            + 3 * (1 - t) * t * t * p2[i]
                            + t**3 * p3[i]
                            for i in (0, 1)
                        )
                    )
            current = p3
    return (
        min(p[0] for p in values),
        min(p[1] for p in values),
        max(p[0] for p in values),
        max(p[1] for p in values),
    )


@pytest.mark.parametrize("case", CASES)
@pytest.mark.parametrize("chamfer", [False, True])
def test_serialized_svg_pdf_ratio_scale_and_true_dimensions(case, chamfer):
    od, bore, width, length, hole = case
    s = PlateSpec(
        od,
        bore,
        width,
        length,
        "304",
        0.125,
        bore_tolerance=0.005,
        chamfer=chamfer,
        **(
            dict(
                chamfer_width=0.02,
                chamfer_angle_degrees=45,
                chamfer_side="downstream",
                flow_orientation="left-to-right",
                chamfer_width_definition="radial-angle-from-face",
            )
            if chamfer
            else {}
        ),
        **(
            dict(
                handle_hole_enabled=True,
                handle_hole_diameter=hole[0],
                handle_hole_center_from_handle_end=hole[1],
            )
            if hole
            else {}
        )
    )
    g = build_plate_geometry(s)
    v = build_presentation(g)
    svg = svg_for(s)
    root = ET.fromstring(svg)
    scale = 72 / int(root.attrib["data-scale"].split(":")[1])
    outline = root.find(".//s:path[@id='plate-outline']", NS).attrib["d"]
    arcs = re.findall(r"A ([\d.]+),([\d.]+) 0 ([01]) ([01]) ([\d.]+),([\d.]+)", outline)
    svg_od = 2 * max(float(a[0]) for a in arcs)
    sb = root.find(".//s:circle[@id='bore']", NS)
    svg_bore = 2 * float(sb.attrib["r"])
    sw = root.find(".//s:line[@class='handle-width']", NS)
    svg_width = abs(float(sw.attrib["y2"]) - float(sw.attrib["y1"]))
    for actual, nominal in ((svg_od, od), (svg_bore, bore), (svg_width, width)):
        assert actual == pytest.approx(nominal * scale, rel=0.005)
    assert svg_od / svg_bore == pytest.approx(od / bore, rel=0.005)
    assert svg_od / svg_width == pytest.approx(od / width, rel=0.005)
    data = render_pdf(g)
    with pdfplumber.open(BytesIO(data)) as pdf:
        page = pdf.pages[0]
        assert (page.width, page.height) == (792, 612)
        # The first heavy curve is the canonical OD arc. Measure its extrema.
        heavy = [c for c in page.curves if c["linewidth"] == pytest.approx(1.15)]
        paddle = extrema(heavy[0])
        pdf_od = paddle[3] - paddle[1]
        circles = [
            c
            for c in heavy
            if len(c["pts"]) == 5 and abs(c["width"] - c["height"]) < 1e-5
        ]
        bc = next(
            c
            for c in circles
            if (c["x0"] + c["x1"]) / 2
            == pytest.approx(float(sb.attrib["cx"]), abs=0.001)
            and (c["y0"] + c["y1"]) / 2
            == pytest.approx(float(sb.attrib["cy"]), abs=0.001)
        )
        pdf_bore = bc["width"]
        sides = [
            l
            for l in page.lines
            if l["linewidth"] == pytest.approx(1.15) and l["height"] == 0
        ]
        pdf_width = max(l["y0"] for l in sides) - min(l["y0"] for l in sides)
        assert pdf_od / pdf_bore == pytest.approx(od / bore, rel=0.005)
        assert pdf_od / pdf_width == pytest.approx(od / width, rel=0.005)
        assert pdf_od == pytest.approx(od * scale, rel=0.005)
        for actual, expected in (
            (pdf_od, svg_od),
            (pdf_bore, svg_bore),
            (pdf_width, svg_width),
        ):
            assert actual == pytest.approx(expected, rel=0.005)
        edge = next(r for r in page.rects if r["x0"] == v.layout.edge_x)
        assert edge["height"] == pytest.approx(od * scale, rel=0.005)
        assert edge["width"] == pytest.approx(s.thickness * scale, rel=0.005)
        assert edge["y0"] + edge["height"] / 2 == pytest.approx(v.cy)
        text = PdfReader(BytesIO(data)).pages[0].extract_text()
        for value in (inch(od), inch(bore), inch(width, 2), inch(length, 2), "±.005"):
            assert value in text
        for forbidden in ("HOLD", "prototype", "NTS", "+/-"):
            assert forbidden.lower() not in text.lower()
            assert forbidden.lower() not in "".join(root.itertext()).lower()
        assert not re.search(r"(?<!\d)0\.\d", text)
        if hole:
            hc = root.find(".//s:circle[@id='handle-hole']", NS)
            hx = float(hc.attrib["cx"])
            pc = next(
                c
                for c in circles
                if (c["x0"] + c["x1"]) / 2 == pytest.approx(hx, abs=0.001)
            )
            assert pc["width"] == pytest.approx(hole[0] * scale, rel=0.005)
            # Tip is actual heavy vertical outline, not an annotation endpoint.
            end = max(
                l["x0"]
                for l in page.lines
                if l["linewidth"] == pytest.approx(1.15) and l["width"] == 0
            )
            assert end - hx == pytest.approx(hole[1] * scale, rel=0.005)
            location = root.find(".//s:line[@class='hole-location']", NS)
            assert float(location.attrib["x2"]) - float(
                location.attrib["x1"]
            ) == pytest.approx(hole[1] * scale, rel=0.005)
            if v.broken:
                assert hx - hole[0] * scale / 2 > v.break_xs[1]
                assert float(location.attrib["x1"]) > v.break_xs[1]
        if v.broken:
            # Kept side runs to the tangent before the true tip radius.
            kept = (
                max(l["width"] for l in sides if l["x0"] >= v.break_xs[1] - 0.001)
                + g.corner_radius * scale
            )
            assert kept == pytest.approx(v.kept_tip * scale, rel=0.005)
            dimension = root.find(".//s:line[@class='handle-length']", NS)
            assert (
                float(dimension.attrib["x1"])
                < v.break_xs[0]
                < v.break_xs[1]
                < float(dimension.attrib["x2"])
            )
            assert any(
                l["x0"] == pytest.approx(v.cx, abs=0.001)
                and l["x1"] == pytest.approx(v.tip_x, abs=0.001)
                and l["y0"] == pytest.approx(v.cy + g.radius * scale + 24, abs=0.001)
                for l in page.lines
            )
    breaks = root.findall(".//s:polyline[@class='long-break']", NS)
    assert len(breaks) == (2 if v.broken else 0)
    if v.broken:
        assert v.break_start == pytest.approx(g.join_x + BREAK_FROM_JUNCTION)
        assert v.removed_length > 0
        assert v.break_xs[1] - v.break_xs[0] == pytest.approx(BREAK_GAP_POINTS)
        assert (length + g.radius) * scale > v.layout.right - v.layout.left
        for line in root.findall(".//s:line[@class='centerline']", NS):
            if line.attrib["y1"] == line.attrib["y2"]:
                assert (
                    float(line.attrib["x2"]) < v.break_xs[0]
                    or float(line.attrib["x1"]) > v.break_xs[1]
                )
    else:
        assert v.tip_x - v.cx == pytest.approx(length * scale)


def test_scale_depends_on_od_and_kept_features_not_long_handle():
    for od, width in ((3, 1.5), (6, 1.5), (16, 1.25), (48, 1.5)):
        views = [
            build_presentation(
                build_plate_geometry(PlateSpec(od, od / 3, width, L, "304", 0.125))
            )
            for L in (od + 10, od + 100)
        ]
        assert views[0].denominator == views[1].denominator
    assert (
        build_presentation(
            build_plate_geometry(PlateSpec(6, 2, 1.5, 14, "304", 0.125))
        ).denominator
        == 2
    )
    assert (
        build_presentation(
            build_plate_geometry(PlateSpec(48, 19, 1.5, 25, "304", 0.125))
        ).denominator
        == 16
    )


def test_uuid_shortened_only_in_visible_drawing():
    s = PlateSpec(3, 1, 1.5, 9, "304", 0.125, part_identifier="PRD-a04088158d8767b4-1")
    uid = "12345678-abcd-4321-abcd-123456789012"
    data = render_pdf(build_plate_geometry(s), DrawingMetadata(order_identifier=uid))
    with pdfplumber.open(BytesIO(data)) as pdf:
        text = pdf.pages[0].extract_text()
        assert uid not in text and "a04088158d8767b4" not in text
        assert "OP-PRD-A0408815-1" in text and "12345678" in text
        assert uid in pdf.metadata["Subject"]


def test_exact_geometry_consumers_match_before_change_byte_baseline():
    baseline = (
        Path(__file__).resolve().parents[1]
        / "review/drawing-true-scale/exact-output-baseline.json"
    )
    assert hashes() == json.loads(baseline.read_text())
