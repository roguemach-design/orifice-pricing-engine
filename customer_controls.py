"""Visible finite choices without changing canonical configurator values."""

import streamlit as st


def choice_buttons(label, options, *, key, placeholder=None, **kwargs):
    options = list(options)
    if st.session_state.get(key) not in options:
        st.session_state[key] = None
    value = st.segmented_control(
        label,
        options,
        key=key,
        required=True,
        wrap=True,
        selection_mode="single",
        **kwargs,
    )
    if value is None and placeholder:
        st.caption(placeholder)
    return value
