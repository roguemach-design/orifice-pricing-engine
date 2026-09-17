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

    assert "OD ⌀ 3.000 in." in svg
    assert "Bore ⌀ 1.000" in svg
    assert "Handle 1.500 in." in svg
    assert "From bore center 9.000 in." in svg
    assert "not an approval or manufacturing drawing" in svg
    assert 'role="img"' in svg


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
