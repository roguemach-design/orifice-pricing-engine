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

    assert "OD &#8960; 3.000 in." in svg
    assert "BORE &#8960; 1.000" in svg
    assert "HANDLE 1.500 in." in svg
    assert "C/L TO END 9.000 in." in svg
    assert "t = 0.125 in." in svg
    assert "&#177; 0.005 in." in svg
    assert "UPSTREAM" in svg
    assert "YES &#8212; WIDTH NOT ENTERED" in svg
    assert "Configuration preview" in svg
    assert "Not an approved manufacturing drawing" in svg
    assert "CONFIGURATION DRAWING &#183; NTS" in svg
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
    assert f"{paddle_dia:.3f} in." in svg
    assert f"{bore_dia:.3f}" in svg
    assert f"HANDLE {handle_width:.3f} in." in svg
    assert f"{handle_length:.3f} in." in svg
    assert "Carbon Steel" in svg
    assert "0.500 in." in svg


def test_material_thickness_and_chamfer_update_title_block_with_customer_width():
    common = dict(
        paddle_dia=6,
        bore_dia=2,
        handle_width=1.5,
        handle_length_from_bore=10,
    )

    stainless = render_plate_svg(material="304", thickness=0.125, chamfer=False, **common)
    carbon = render_plate_svg(
        material="Carbon Steel",
        thickness=0.5,
        chamfer=True,
        chamfer_width=0.062,
        **common,
    )

    assert stainless != carbon
    assert "304" in stainless
    assert "0.125 in." in stainless
    assert "Carbon Steel" in carbon
    assert "0.500 in." in carbon
    assert "CHAMFER" in carbon
    assert "YES &#8212; 0.062 in." in carbon
