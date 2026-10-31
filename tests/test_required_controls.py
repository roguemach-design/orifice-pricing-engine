"""Required choices have one canonical value and an explicit browser selection."""

import pytest
from streamlit.testing.v1 import AppTest


@pytest.mark.parametrize("selected", [False, True])
def test_required_boolean_reasserts_unchanged_selection_on_browser_wire(selected):
    def render(selected):
        import streamlit as st
        from customer_controls import choice_buttons

        if "initialized" not in st.session_state:
            st.session_state["initialized"] = True
            st.session_state["bore"] = selected
        choice_buttons("Bore edge", [False, True], key="bore")

    app = AppTest.from_function(render, args=(selected,)).run()
    app.run()
    control = app.button_group(key="bore")
    assert not app.exception and control.value is selected
    assert control.proto.set_value
    assert list(control.proto.raw_values) == [str(selected)]


@pytest.mark.parametrize("current, committed, options, expected", [
    (None, False, [False, True], False),
    (None, True, [False, True], True),
    (None, None, [False, True], None),
    (False, True, [False, True], False),
    (True, False, [False, True], True),
    ("invalid", True, [False, True], None),
    (None, True, [False], None),
    (None, False, [True], None),
    (True, True, [False], None),
])
def test_required_choice_recovery_respects_none_current_edits_and_availability(
    current, committed, options, expected
):
    def render(current, committed, options):
        import streamlit as st
        from customer_controls import choice_buttons

        st.session_state["bore"] = current
        result = choice_buttons("Bore edge", options, key="bore", committed_value=committed)
        st.session_state["observed"] = result

    app = AppTest.from_function(render, args=(current, committed, options)).run()
    control = app.button_group(key="bore")
    assert not app.exception and app.session_state["observed"] is expected
    assert control.value is expected and control.proto.set_value
    assert list(control.proto.raw_values) == ([] if expected is None else [str(expected)])


def test_bore_edge_conditional_remount_and_explicit_unresolved_reset():
    def render():
        import streamlit as st
        from bore_edge_control import bore_edge_choice

        if "canonical" not in st.session_state:
            st.session_state["canonical"] = False
        if st.button("Reset required selection"):
            st.session_state["canonical"] = None
            st.session_state["bore"] = None
        hidden = st.checkbox("Hide control")
        if not hidden:
            value = bore_edge_choice(key="bore", committed_value=st.session_state["canonical"])
            st.session_state["canonical"] = value
            if value is True:
                st.number_input("Chamfer width", value=0.04)

    app = AppTest.from_function(render).run()
    app.button_group(key="bore").set_value(True).run()
    assert app.session_state["canonical"] is True and len(app.number_input) == 1
    app.button_group(key="bore").set_value(False).run()
    assert app.session_state["canonical"] is False and not app.number_input
    app.checkbox[0].check().run()
    app.checkbox[0].uncheck().run()
    assert app.button_group(key="bore").value is False
    app.button[0].click().run()
    assert not app.exception and app.session_state["canonical"] is None
    assert app.button_group(key="bore").value is None
