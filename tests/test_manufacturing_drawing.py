from dataclasses import replace
from hashlib import sha256
import pytest
from reportlab.pdfgen.canvas import Canvas
from plate_geometry import PlateSpec, build_plate_geometry, GEOMETRY_VERSION
from manufacturing_files import pdf_bytes, dxf_bytes, preview_svg
from manufacturing_drawing import DrawingMetadata, section_profile, GENERATOR_VERSION


@pytest.fixture
def geometry():
    return build_plate_geometry(
        PlateSpec(5, 1.548, 2, 10.5, "304 stainless steel", 0.125)
    )


def test_drawing_fields_and_holds(geometry, monkeypatch):
    labels = []

    def record(self, x, y, value, *args, **kwargs):
        labels.append(value)

    monkeypatch.setattr(Canvas, "drawString", record)
    monkeypatch.setattr(Canvas, "drawCentredString", record)
    pdf_bytes(geometry)
    text = "\n".join(labels)
    for expected in (
        "Ø1.548",
        "Ø5.000",
        "2.000",
        "10.500 C/L TO HANDLE END",
        "4X R 0.03125",
        "304 STAINLESS STEEL",
        "0.125 THK.",
        "NO. REQ'D.",
        "BORE TOLERANCE: NOT SPECIFIED - HOLD",
        "CHAMFER: NOT SPECIFIED - HOLD",
        "MARKING: HOLD",
        "BORE FINISH: HOLD",
        "UNLESS OTHERWISE SPECIFIED:",
        "THROUGH HANDLE / BORE",
        "CHAMFER: NOT SPECIFIED - HOLD",
        "P3E",
        GEOMETRY_VERSION,
        GENERATOR_VERSION,
        "PROTOTYPE - NOT RELEASED FOR MANUFACTURE",
        "DO NOT SCALE DRAWING",
        "PROTOTYPE - NOT RELEASED FOR MANUFACTURE",
    ):
        assert expected in text
    for forbidden in (
        "1.423",
        "ANDRITZ",
        "706928890",
        "ISO 2768",
        "ISO 13920",
        "BIG RIVER",
    ):
        assert forbidden not in text.upper()


def test_section_matches_finished_dimensions_without_invented_chamfer(geometry):
    p = section_profile(geometry, DrawingMetadata())
    assert not p["chamfer_drawn"]
    assert p["thickness"] == 0.125
    assert p["finished_bore_diameter"] == 1.548
    assert p["polygons"][0] == ((0, 0.774), (0.125, 0.774), (0.125, 10.5), (0, 10.5))


@pytest.mark.parametrize("side", ["upstream", "downstream"])
def test_explicit_future_chamfer_convention(geometry, side):
    g = build_plate_geometry(
        replace(
            geometry.spec,
            chamfer=True,
            chamfer_width=0.02,
            chamfer_angle_degrees=45,
            chamfer_side=side,
        )
    )
    assert not section_profile(g, DrawingMetadata())["chamfer_drawn"]
    metadata = DrawingMetadata(
        flow_orientation="left-to-right",
        chamfer_width_definition="radial-angle-from-face",
    )
    profile = section_profile(g, metadata)
    assert profile["chamfer_drawn"]
    upper = profile["polygons"][0]
    assert len(upper) == 5
    assert max(y for x, y in upper) == 10.5
    point = upper[2] if side == "downstream" else upper[0]
    assert point == pytest.approx(
        (0.125 if side == "downstream" else 0, 0.794), rel=0, abs=1e-12
    )


def test_oversize_chamfer_rejected(geometry):
    g = build_plate_geometry(
        replace(
            geometry.spec,
            chamfer=True,
            chamfer_width=0.2,
            chamfer_angle_degrees=45,
            chamfer_side="downstream",
        )
    )
    with pytest.raises(ValueError, match="does not fit"):
        pdf_bytes(
            g,
            DrawingMetadata(
                flow_orientation="left-to-right",
                chamfer_width_definition="radial-angle-from-face",
            ),
        )


def test_traceability_with_optional_order_fields(geometry, monkeypatch):
    labels = []
    monkeypatch.setattr(
        Canvas, "drawString", lambda self, x, y, value, *a, **k: labels.append(value)
    )
    metadata = DrawingMetadata(
        order_identifier="TEST-ORDER",
        order_line_revision="L2-R1",
        customer_tag="TAG-1",
        line_service="TEST SERVICE",
    )
    first = pdf_bytes(geometry, metadata)
    second = pdf_bytes(geometry, metadata)
    assert first == second
    text = "\n".join(labels)
    for field in ("TEST-ORDER", "L2-R1", "TAG-1", "TEST SERVICE"):
        assert field in text


@pytest.mark.parametrize(
    "values",
    [
        {"flow_orientation": "unknown"},
        {"chamfer_width_definition": "unknown"},
        {"revision": "\n"},
    ],
)
def test_invalid_drawing_metadata_rejected(values):
    with pytest.raises(ValueError):
        DrawingMetadata(**values)


@pytest.mark.parametrize("length", [2.7, 10.5, 30])
def test_letter_layout_and_determinism_for_handle_proportions(geometry, length):
    g = build_plate_geometry(replace(geometry.spec, centerline_to_handle_end=length))
    first = pdf_bytes(g)
    assert first == pdf_bytes(g)
    assert b"/MediaBox [ 0 0 612 792 ]" in first
