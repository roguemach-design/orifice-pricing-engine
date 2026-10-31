"""Required native lead-time choices survive a transient remount, not invalidation."""

import pytest
from streamlit.testing.v1 import AppTest


@pytest.mark.parametrize("current, committed, options, expected", [
    (None, 14, [14, 21], 14),
    (None, 21, [14, 21], 21),
    (21, 14, [14, 21], 21),
    (None, None, [14, 21], None),
    (None, 7, [14, 21], None),
    (7, 14, [14, 21], None),
])
def test_required_lead_time_recovers_only_an_available_committed_choice(
    current, committed, options, expected
):
    def render(current, committed, options):
        import streamlit as st
        from customer_controls import lead_time_choices

        st.session_state["quote_field_ships_in_days"] = current
        value = lead_time_choices("Lead time", options, key="quote_field_ships_in_days",
                                  committed_value=committed)
        st.session_state["observed_lead_time"] = value

    app = AppTest.from_function(render, args=(current, committed, options)).run()
    assert not app.exception
    assert app.session_state["observed_lead_time"] == expected
    assert app.button_group(key="quote_field_ships_in_days").value == expected


def test_remount_reasserts_the_selected_lead_time_on_the_browser_wire():
    def render():
        import streamlit as st
        from customer_controls import lead_time_choices

        if "quote_field_ships_in_days" not in st.session_state:
            st.session_state["quote_field_ships_in_days"] = 21
        lead_time_choices("Lead time", [14, 21], key="quote_field_ships_in_days",
                          committed_value=21)

    app = AppTest.from_function(render).run()
    app.run()
    control = app.button_group(key="quote_field_ships_in_days")
    assert not app.exception and control.value == 21
    assert control.proto.set_value
    assert list(control.proto.raw_values) == ["21 calendar days"]
