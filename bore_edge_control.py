"""Approved bore-edge selection graphic; never manufacturing geometry."""

import base64
from pathlib import Path
from io import BytesIO

from PIL import Image

import streamlit as st

from customer_controls import choice_buttons

BORE_EDGE_IMAGE = Path(__file__).resolve().parent / "assets" / "bore-edge-type.png"


@st.cache_data
def _graphic_background():
    # Crop only the illustrations; exclude raster labels, borders and state dots.
    with Image.open(BORE_EDGE_IMAGE) as source:
        graphics = []
        for box in ((230, 150, 930, 555), (1080, 150, 1780, 555)):
            output = BytesIO()
            source.crop(box).save(output, format="PNG")
            graphics.append(base64.b64encode(output.getvalue()).decode("ascii"))
    return tuple(graphics)


def bore_edge_choice(*, key):
    """Use two graphic cards as the single required canonical boolean selector."""
    left_graphic, right_graphic = _graphic_background()
    st.markdown(
        """<style>
      .st-key-bore_edge_choice [data-testid="stElementContainer"]:has([data-testid="stButtonGroup"]) {width:100%!important}
      .st-key-bore_edge_choice [data-testid="stButtonGroup"] {width:100%}
      .st-key-bore_edge_choice [data-testid="stButtonGroup"] > div {width:100%;max-width:none;gap:1rem;flex-wrap:nowrap}
      .st-key-bore_edge_choice [data-testid="stButtonGroup"] button {
        position:relative;flex:1 1 0;min-width:0;max-width:100%;height:auto;
        display:flex;flex-direction:column;align-items:stretch;justify-content:flex-start;
        padding:1rem;text-align:left;border:2px solid #343e49;border-radius:10px;
        background:#0d141c;overflow:hidden;
      }
      .st-key-bore_edge_choice [data-testid="stButtonGroup"] button::before {
        content:"";display:block;width:100%;aspect-ratio:700/405;flex-shrink:0;
        background-image:url(data:image/png;base64,""" + left_graphic + """);
        background-size:contain;background-position:center;background-repeat:no-repeat;
      }
      .st-key-bore_edge_choice [data-testid="stButtonGroup"] button:nth-of-type(2)::before {
        background-image:url(data:image/png;base64,""" + right_graphic + """);
      }
      .st-key-bore_edge_choice [data-testid="stButtonGroup"] button {font-family:inherit}
      .st-key-bore_edge_choice button [data-testid="stMarkdownContainer"] {width:100%;text-align:left}
      .st-key-bore_edge_choice [data-testid="stButtonGroup"] button p {
        font-family:inherit!important;white-space:normal;font-size:.875rem!important;
        font-weight:400!important;line-height:1.4!important;margin:0!important;color:#dbe1e7;
      }
      .st-key-bore_edge_choice [data-testid="stButtonGroup"] button p:has(strong) {
        margin:.75rem 0 .35rem!important;
      }
      .st-key-bore_edge_choice [data-testid="stButtonGroup"] button strong {
        font-family:inherit!important;font-size:1rem!important;font-weight:600!important;
        line-height:1.35!important;color:#fff;
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
            format_func=lambda value: (
                "**CHAMFERED BORE**\n\nAdd a chamfer to the bore edge."
                if value else "**NO CHAMFER**\n\nSquare bore edge."
            ),
            label_visibility="collapsed",
        )
