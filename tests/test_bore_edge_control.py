"""Bore-edge presentation keeps required canonical booleans."""

import hashlib
from pathlib import Path

from streamlit.testing.v1 import AppTest

from bore_edge_control import BORE_EDGE_IMAGE


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


def test_bore_edge_graphic_is_exact_uploaded_image():
    assert hashlib.sha256(BORE_EDGE_IMAGE.read_bytes()).hexdigest() == "c752ddc2c2952c8dd2bd50ac9897c28e5b8e442d8ac5194d94a1d455ceecb322"
