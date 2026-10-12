"""Illustrative bore-edge selection; no dimensions or manufacturing geometry."""

import base64

import streamlit as st

from customer_controls import choice_buttons


def bore_edge_svg(chamfered: bool) -> str:
    upper = (
        "223,18 257,18 257,60 237,80 223,80"
        if chamfered
        else "223,18 257,18 257,80 223,80"
    )
    lower = (
        "223,120 237,120 257,140 257,162 223,162"
        if chamfered
        else "223,120 257,120 257,162 223,162"
    )
    edge = (
        "M223 80 H237 L257 60 M223 120 H237 L257 140"
        if chamfered
        else "M223 80 H257 V120 H223 Z"
    )
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 300 180" role="img">
      <title>{"Chamfered bore" if chamfered else "Square bore edge"} illustration</title>
      <defs>
        <linearGradient id="metal"><stop stop-color="#737d86"/><stop offset=".5" stop-color="#c0c7cc"/><stop offset="1" stop-color="#65717c"/></linearGradient>
        <pattern id="hatch" width="7" height="7" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><rect width="7" height="7" fill="#7f8b97"/><path d="M0 0V7" stroke="#d9e0e5" stroke-width="2"/></pattern>
      </defs>
      <path d="M80 48V18 Q80 12 86 12H100Q106 12 106 18V48 A60 60 0 1 1 80 48Z" fill="url(#metal)" stroke="#e6edf3" stroke-width="2"/>
      <circle cx="93" cy="105" r="24" fill="#111c28" stroke="#e6edf3" stroke-width="2"/>
      <circle cx="93" cy="24" r="5" fill="#111c28" stroke="#e6edf3"/>
      <path d="M22 105H164 M93 10V175" stroke="#e6edf3" stroke-dasharray="7 5" opacity=".55"/>
      <polygon points="{upper}" fill="url(#hatch)" stroke="#e6edf3" stroke-width="2"/>
      <polygon points="{lower}" fill="url(#hatch)" stroke="#e6edf3" stroke-width="2"/>
      <path d="{edge}" fill="none" stroke="#36adff" stroke-width="3"/>
      <path d="M204 100H275" stroke="#e6edf3" stroke-dasharray="7 5" opacity=".55"/>
    </svg>"""


def bore_edge_choice(*, key):
    """Keep the canonical required boolean selection and existing state key."""

    def label(value):
        name = "Chamfered Bore" if value else "No Chamfer"
        description = (
            "Add a chamfer to the bore edge." if value else "Square bore edge."
        )
        encoded = base64.b64encode(bore_edge_svg(value).encode()).decode()
        return f"![{name} illustration](data:image/svg+xml;base64,{encoded})\n\n**{name}**\n\n{description}"

    st.markdown(
        """<style>
      .st-key-bore_edge_choice [data-testid="stButtonGroup"] > div {width:100%;flex-wrap:wrap;gap:.5rem}
      .st-key-bore_edge_choice [data-testid="stButtonGroup"] button {
        flex:1 1 180px;min-width:0;max-width:100%;height:auto;padding:.65rem;
        text-align:left;border-radius:8px;background-color:#111c28;color:#edf3f8;
      }
      .st-key-bore_edge_choice button img {width:100%;height:auto!important;max-height:160px!important;max-width:100%;object-fit:contain;display:block}
      .st-key-bore_edge_choice button p {white-space:normal;line-height:1.35;font-size:.8rem;margin:.25rem 0}
      .st-key-bore_edge_choice button strong {font-size:.95rem}
      .st-key-bore_edge_choice button[aria-pressed="true"] {border:2px solid #36adff;box-shadow:inset 0 0 0 1px #36adff}
      .st-key-bore_edge_choice button:focus-visible {outline:3px solid #e99527;outline-offset:3px}
      @media(max-width:600px){.st-key-bore_edge_choice [data-testid="stButtonGroup"] button{flex-basis:100%}}
    </style>""",
        unsafe_allow_html=True,
    )
    with st.container(key="bore_edge_choice"):
        st.markdown("**Bore Edge Type**")
        return choice_buttons(
            "Chamfer",
            [False, True],
            key=key,
            format_func=label,
            label_visibility="collapsed",
        )
