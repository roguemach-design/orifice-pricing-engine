"""Approved bore-edge selection graphic; never manufacturing geometry."""

from pathlib import Path

import streamlit as st

from customer_controls import choice_buttons

BORE_EDGE_IMAGE = Path(__file__).resolve().parent / "assets" / "bore-edge-type.png"


def bore_edge_choice(*, key):
    """Keep the required boolean choice and use the original uploaded graphic."""
    st.markdown(
        """<style>
      .st-key-bore_edge_choice [data-testid="stButtonGroup"] > div {width:100%;gap:.5rem}
      .st-key-bore_edge_choice [data-testid="stButtonGroup"] button {flex:1;min-width:0}
      .st-key-bore_edge_choice button[aria-pressed="true"] {border:2px solid #36adff}
      .st-key-bore_edge_choice button:focus-visible {outline:3px solid #e99527;outline-offset:3px}
    </style>""",
        unsafe_allow_html=True,
    )
    with st.container(key="bore_edge_choice"):
        st.image(str(BORE_EDGE_IMAGE), width="stretch")
        return choice_buttons(
            "Chamfer",
            [False, True],
            key=key,
            format_func=lambda value: "YES" if value else "NO",
            label_visibility="collapsed",
        )
