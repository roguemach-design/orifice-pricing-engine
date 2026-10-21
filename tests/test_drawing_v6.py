"""Measure serialized output and preserve exact manufacturing artifacts."""

from dataclasses import asdict, replace
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from xml.etree import ElementTree as ET
import json
import math
import re
import pdfplumber
from pypdf import PdfReader
import pytest
from drawing_presentation import WEB, PRINT, build_presentation, build_views
from drawing_standards import BREAK_FROM_JUNCTION, BREAK_GAP_POINTS, dimension, inch
from manufacturing_drawing import DrawingMetadata, render_pdf
from plate_geometry import PlateSpec, build_plate_geometry
from scripts.review_drawing_v6 import svg_for
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


def feature(root, key):
    return root.findall(f".//*[@data-feature='{key}']", NS)


def sampled_path(path):
    """Independent cubic evaluation in the serialized output coordinate space."""
    points = []
    current = None
    for command in path:
        op, *p = command
        if op in ("m", "l"):
            current = p[0]
            points.append(current)
        elif op == "c":
            a, b, c, d = current, *p
            for n in range(101):
                t = n / 100
                points.append(
                    tuple(
                        (1 - t) ** 3 * a[i]
                        + 3 * (1 - t) ** 2 * t * b[i]
                        + 3 * (1 - t) * t * t * c[i]
                        + t**3 * d[i]
                        for i in (0, 1)
                    )
                )
            current = d
    return points


def svg_path(value):
    result = []
    for match in re.finditer(r"([MLCZ])([^MLCZ]*)", value):
        op, raw = match.groups()
        nums = list(map(float, raw.split()))
        result.append((op.lower(), *zip(nums[::2], nums[1::2])))
    return result


@pytest.mark.parametrize("case", CASES)
@pytest.mark.parametrize("chamfer", [False, True])
@pytest.mark.parametrize("material", ["304", "316", "Carbon Steel"])
def test_serialized_geometry_and_section_parity(case, chamfer, material):
    od, bore, width, length, hole = case
    spec = PlateSpec(
        od,
        bore,
        width,
        length,
        material,
        0.125,
        bore_tolerance=0.005,
        chamfer=chamfer,
        chamfer_width=0.02 if chamfer else None,
        marking="FE-101" if chamfer else None,
        **(
            dict(
                handle_hole_enabled=True,
                handle_hole_diameter=hole[0],
                handle_hole_center_from_handle_end=hole[1],
            )
            if hole
            else {}
        ),
    )
    g = build_plate_geometry(spec)
    view = build_presentation(g, WEB)
    printed = build_presentation(g, PRINT)
    assert view.denominator == printed.denominator
    root = ET.fromstring(svg_for(spec))
    data = render_pdf(g)
    scale = 72 / int(root.attrib["data-scale"].split(":")[1])
    sp = sampled_path(svg_path(feature(root, "plate-outline")[0].attrib["d"]))
    sx = min(x for x, y in sp)
    ex = max(x for x, y in sp)
    svg_od = ex - sx
    bc = feature(root, "bore")[0]
    svg_bore = 2 * float(bc.attrib["r"])
    # Profile sides are read from the serialized canonical path (no label proxy).
    xs = [x for x, y in sp if y < -view.ordinate(g.join_x) - 0.1]
    svg_width = max(xs) - min(xs)
    for actual, nominal in ((svg_od, od), (svg_bore, bore), (svg_width, width)):
        assert actual == pytest.approx(nominal * scale, rel=0.005)
    assert svg_od / svg_bore == pytest.approx(od / bore, rel=0.005)
    with pdfplumber.open(BytesIO(data)) as pdf:
        page = pdf.pages[0]
        assert (page.width, page.height) == (612, 792)
        heavy = [c for c in page.curves if c["linewidth"] == 1.25]
        paddle = sampled_path(heavy[0]["path"])
        pdf_od = max(x for x, y in paddle) - min(x for x, y in paddle)
        assert pdf_od == pytest.approx(svg_od, rel=0.005)
        circles = [
            c
            for c in page.curves
            if len(c["pts"]) == 5 and abs(c["width"] - c["height"]) < 1e-5
        ]

        def circle(node):
            x = float(node.attrib["cx"]) - view.cx + printed.cx
            y = -float(node.attrib["cy"]) - view.cy + printed.cy
            return next(
                c
                for c in circles
                if abs((c["x0"] + c["x1"]) / 2 - x) < 0.001
                and abs((c["y0"] + c["y1"]) / 2 - y) < 0.001
                and abs(c["width"] / 2 - float(node.attrib["r"])) < 0.001
            )

        assert circle(bc)["width"] == pytest.approx(svg_bore, rel=0.005)

        # Match every section face, wall, slope and hatch segment between serializers.
        def has_line(node):
            coords = tuple(float(node.attrib[k]) for k in ("x1", "y1", "x2", "y2"))
            x1, y1, x2, y2 = coords
            x1, x2 = (x - view.section_x + printed.section_x for x in (x1, x2))
            y1, y2 = (-y - view.cy + printed.cy for y in (y1, y2))
            return any(
                all(
                    abs(a - b) < 0.001
                    for a, b in zip(
                        (l["x0"], l["y0"], l["x1"], l["y1"]),
                        (min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2)),
                    )
                )
                and abs(l["linewidth"] - float(node.attrib["stroke-width"]) / WEB.line * PRINT.line) < 1e-9
                for l in page.lines
            )

        for key in (
            "section-face",
            "section-end",
            "bore-wall",
            "chamfer-slope",
            "chamfer-bore-line",
            "hole-wall",
            "section-hatch",
        ):
            assert all(has_line(n) for n in feature(root, key)), key
        assert len(feature(root, "section-face")) == (4 if view.broken else 2)
        assert len(feature(root, "bore-wall")) == 2
        if chamfer:
            cc = feature(root, "chamfer-circle")[0]
            assert float(cc.attrib["r"]) * 2 == pytest.approx(
                (bore + 0.04) * scale, rel=0.005
            )
            assert cc.attrib["stroke-dasharray"] == "4 2"
            assert circle(cc)["dash"][0] == [4, 2]
            line = feature(root, "chamfer-bore-line")[0]
            assert float(line.attrib["x1"]) == pytest.approx(
                view.section_x + (0.125 - 0.02) * scale, abs=0.001
            )
            assert len(feature(root, "chamfer-slope")) == 2
        else:
            assert not feature(root, "chamfer-circle")
        for line in feature(root, "section-hatch"):
            y1, y2 = sorted((-float(line.attrib["y1"]), -float(line.attrib["y2"])))
            assert (
                y2 <= view.cy - bore * scale / 2 + 0.001
                or y1 >= view.cy + bore * scale / 2 - 0.001
            )
            if hole:
                hc = view.ordinate(length - hole[1])
                hr = hole[0] * scale / 2
                assert y2 <= hc - hr + 0.001 or y1 >= hc + hr - 0.001
            if view.broken:
                assert y2 <= view.break_ys[0] + 0.001 or y1 >= view.break_ys[1] - 0.001
        if hole:
            hc = feature(root, "handle-hole")[0]
            assert circle(hc)["width"] == pytest.approx(hole[0] * scale, rel=0.005)
            assert view.tip_y + float(hc.attrib["cy"]) == pytest.approx(
                hole[1] * scale, rel=0.005
            )
            if view.broken:
                assert (
                    -float(hc.attrib["cy"]) - float(hc.attrib["r"]) > view.break_ys[1]
                )
        if view.broken:
            assert view.break_start == pytest.approx(g.join_x + BREAK_FROM_JUNCTION)
            assert view.break_ys[1] - view.break_ys[0] == pytest.approx(
                BREAK_GAP_POINTS
            )
            assert view.tip_y - view.break_ys[1] == pytest.approx(view.kept_tip * scale)
        # Every PDF text matrix is horizontal; SVG has no transforms on text.
        assert all(
            abs(c["matrix"][1]) < 1e-12 and abs(c["matrix"][2]) < 1e-12
            for c in page.chars
        )
        assert all("transform" not in t.attrib for t in root.findall(".//s:text", NS))
    text = PdfReader(BytesIO(data)).pages[0].extract_text()
    for value in (
        "Ø" + inch(od),
        "Ø" + inch(bore),
        dimension(width, "width"),
        dimension(length, "length"),
        "±.005",
    ):
        assert value in text
    for forbidden in (
        "HOLD",
        "NTS",
        "prototype",
        "DATUM",
        "POSITION",
        "FLATNESS",
        "+/-",
    ):
        assert forbidden.lower() not in text.lower()
    assert not re.search(r"(?<!\d)0\.\d", text)
    assert spec == g.spec


def test_break_only_when_needed_and_length_does_not_drive_scale():
    base = PlateSpec(3, 1, 1.5, 2, "304", 0.125, chamfer=False)
    short = build_presentation(build_plate_geometry(base))
    long = build_presentation(
        build_plate_geometry(replace(base, centerline_to_handle_end=30))
    )
    assert not short.broken and long.broken
    assert short.denominator == long.denominator == 1


def test_non_drawing_outputs_match_unchanged_production_baseline():
    expected = json.loads(
        (
            Path(__file__).parents[1] / "review/drawing-v6/exact-output-baseline.json"
        ).read_text()
    )
    assert len(expected) == 51
    assert hashes() == expected


def test_input_records_and_existing_pdf_are_immutable(tmp_path):
    source = Path(__file__).parent / "fixtures/legacy-v3e.pdf"
    old = tmp_path / "captured.pdf"
    old.write_bytes(source.read_bytes())
    before = sha256(old.read_bytes()).hexdigest()
    s = PlateSpec(3, 1, 1.5, 9, "304", 0.125, chamfer=True, chamfer_width=0.04)
    m = DrawingMetadata(order_identifier="01234567-89ab-cdef-0123-456789abcdef")
    spec_before, meta_before = asdict(s), asdict(m)
    data = render_pdf(build_plate_geometry(s), m)
    assert asdict(s) == spec_before and asdict(m) == meta_before
    assert sha256(old.read_bytes()).hexdigest() == before
    r = PdfReader(BytesIO(data))
    assert m.order_identifier not in r.pages[0].extract_text()
    assert json.loads(r.metadata.subject)["order"] == m.order_identifier
