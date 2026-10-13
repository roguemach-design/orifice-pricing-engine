"""Approved bore-edge selection graphic; never manufacturing geometry."""

import base64
from pathlib import Path

import streamlit as st

from customer_controls import choice_buttons

BORE_EDGE_IMAGE = Path(__file__).resolve().parent / "assets" / "bore-edge-type.png"


@st.cache_data
def _graphic_background():
    return base64.b64encode(BORE_EDGE_IMAGE.read_bytes()).decode("ascii")


def bore_edge_choice(*, key):
    """Use two graphic cards as the single required canonical boolean selector."""
    # Show the interiors of the original cards, excluding their baked-in borders.
    # Native button state supplies the border and covers the static selection dot.
    graphic = _graphic_background()
    st.markdown(
        """<style>
      .st-key-bore_edge_choice [data-testid="stElementContainer"]:has([data-testid="stButtonGroup"]) {width:100%!important}
      .st-key-bore_edge_choice [data-testid="stButtonGroup"] {width:100%}
      .st-key-bore_edge_choice [data-testid="stButtonGroup"] > div {width:100%;max-width:none;gap:1rem;flex-wrap:nowrap}
      .st-key-bore_edge_choice [data-testid="stButtonGroup"] button {
        position:relative;flex:1 1 0;min-width:0;max-width:100%;height:auto;
        aspect-ratio:797/552;padding:0;border:2px solid #343e49;border-radius:10px;
        background-image:url(data:image/png;base64,""" + graphic + """);
        background-size:256.9636% 135.5072%;background-repeat:no-repeat;
        background-position:16.7866% 65.8163%;overflow:hidden;
      }
      .st-key-bore_edge_choice [data-testid="stButtonGroup"] button:nth-of-type(2) {background-position:83.4532% 65.8163%}
      .st-key-bore_edge_choice [data-testid="stButtonGroup"] button p {
        position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;
        clip-path:inset(50%);white-space:nowrap;
      }
      .st-key-bore_edge_choice [data-testid="stButtonGroup"] button::after {
        content:"";position:absolute;top:3%;right:3.3%;width:6%;aspect-ratio:1;
        border:2px solid #dbe1e7;border-radius:50%;background:#0d141c;
        box-shadow:0 0 0 5px #0d141c;
      }
      .st-key-bore_edge_choice button[aria-pressed="true"],
      .st-key-bore_edge_choice button[aria-checked="true"] {border:2px solid #009cff}
      .st-key-bore_edge_choice button[aria-pressed="true"]::after,
      .st-key-bore_edge_choice button[aria-checked="true"]::after {
        border-color:#009cff;background:radial-gradient(circle,#fff 0 28%,#009cff 30% 44%,#0d141c 46%);
      }
      .st-key-bore_edge_choice button:focus-visible {outline:3px solid #e99527;outline-offset:3px}
      @media(max-width:600px) {
        .st-key-bore_edge_choice [data-testid="stButtonGroup"] > div {flex-wrap:wrap}
        .st-key-bore_edge_choice [data-testid="stButtonGroup"] button {flex:1 1 100%}
      }
    </style>""",
        unsafe_allow_html=True,
    )
    with st.container(key="bore_edge_choice"):
        st.markdown("**Bore Edge Type :red[*]**")
        st.caption("Select the bore edge finish for your orifice plate.")
        return choice_buttons(
            "Chamfer",
            [False, True],
            key=key,
            format_func=lambda value: "CHAMFERED BORE" if value else "NO CHAMFER",
            label_visibility="collapsed",
        )
