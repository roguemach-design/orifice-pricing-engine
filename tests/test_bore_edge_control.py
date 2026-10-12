"""Bore-edge presentation keeps required canonical booleans."""

import xml.etree.ElementTree as ET
from pathlib import Path

from streamlit.testing.v1 import AppTest

from bore_edge_control import bore_edge_svg


def test_bore_edge_selector_preserves_unresolved_and_boolean_state():
    def render():
        from bore_edge_control import bore_edge_choice
        import streamlit as st

        value = bore_edge_choice(key="quote_field_chamfer")
        if value is True:
            st.number_input("Chamfer Width (in.)", value=None)

    app = AppTest.from_function(render).run()
    assert not app.exception
    assert app.button_group(key="quote_field_chamfer").value is None
    assert not app.number_input
    app.button_group(key="quote_field_chamfer").set_value(True).run()
    assert not app.exception
    assert app.session_state["quote_field_chamfer"] is True
    assert len(app.number_input) == 1
    assert app.number_input[0].value is None
    app.button_group(key="quote_field_chamfer").set_value(False).run()
    assert not app.exception
    assert app.session_state["quote_field_chamfer"] is False
    assert not app.number_input


def test_bore_edge_illustrations_are_scalable_and_have_no_dimensional_claims():
    for chamfered in (False, True):
        svg = bore_edge_svg(chamfered)
        root = ET.fromstring(svg)
        assert root.attrib["viewBox"] == "0 0 300 180"
        assert "width" not in root.attrib
        assert "height" not in root.attrib
        assert root.find("{http://www.w3.org/2000/svg}title") is not None
        assert "45" not in "".join(root.itertext())
        assert "DEPTH" not in svg
    assert bore_edge_svg(False) != bore_edge_svg(True)
