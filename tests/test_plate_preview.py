from xml.etree import ElementTree

import pytest

from plate_preview import render_plate_svg


def test_svg_contains_current_dimensions_and_disclaimer():
    svg = render_plate_svg(
        paddle_dia=3.0,
        bore_dia=1.0,
        handle_width=1.5,
        handle_length_from_bore=9.0,
        thickness=0.125,
        material="304",
    )

    assert "OD &#8960; 3.000 in." in svg
    assert "Bore &#8960; 1.000" in svg
    assert "1.500 in. handle" in svg
    assert "Center to handle end 9.000 in." in svg
    assert "not an approval or manufacturing drawing" in svg
    assert 'role="img"' in svg
    assert "LIVE PREVIEW" in svg
    ElementTree.fromstring(svg)


def test_svg_escapes_material_text():
    svg = render_plate_svg(
        paddle_dia=3,
        bore_dia=1,
        handle_width=1,
        handle_length_from_bore=5,
        thickness=0.25,
        material="<script>alert(1)</script>",
    )

    assert "<script>" not in svg
    assert "&lt;script&gt;" in svg


@pytest.mark.parametrize(
    ("paddle_dia", "bore_dia", "handle_width", "handle_length"),
    [
        (1.0, 0.125, 0.125, 0.75),
        (3.0, 1.0, 1.5, 9.0),
        (48.0, 19.0, 1.5, 25.0),
    ],
)
def test_svg_is_valid_and_contains_boundary_configuration(
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
    assert f"{paddle_dia:.3f} in." in svg
    assert f"{bore_dia:.3f}" in svg
    assert f"{handle_width:.3f} in. handle" in svg
    assert f"{handle_length:.3f} in." in svg
    assert "Carbon Steel" in svg
    assert "0.500 in. nominal thickness" in svg


def test_material_changes_visual_finish():
    common = dict(
        paddle_dia=6,
        bore_dia=2,
        handle_width=1.5,
        handle_length_from_bore=10,
        thickness=0.25,
    )

    stainless = render_plate_svg(material="304", **common)
    carbon = render_plate_svg(material="Carbon Steel", **common)

    assert stainless != carbon
    assert '#d8dee5' in carbon
    assert '#f8fafc' in stainless
