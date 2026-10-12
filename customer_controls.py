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


MATERIAL_COPY = {
    "304": (
        "304 Stainless Steel",
        "304 SS",
        "General-purpose stainless for a wide range of services.",
    ),
    "316": (
        "316 Stainless Steel",
        "316 SS",
        "Molybdenum-bearing stainless with added corrosion resistance.",
    ),
    "Carbon Steel": (
        "Carbon Steel",
        "CS",
        "A cost-effective choice where stainless is not required.",
    ),
}


def material_cards(options, *, key):
    """Native accessible selection; display copy never changes canonical values."""

    def card_label(value):
        name, code, description = MATERIAL_COPY.get(value, (value, value, ""))
        return f"**{name}**\n\n`{code}`\n\n{description}"

    st.markdown(
        """<style>
      .st-key-material_cards [data-testid="stButtonGroup"] > div {width:100%;flex-wrap:wrap;gap:0.5rem}
      .st-key-material_cards [data-testid="stButtonGroup"] button {
        flex:1 1 155px;min-width:0;max-width:100%;height:auto;min-height:132px;
        padding:0.75rem;text-align:left;align-items:flex-start;border-radius:8px;
        background:repeating-linear-gradient(105deg,rgba(128,140,150,.08) 0px,
          rgba(128,140,150,.08) 1px,transparent 1px,transparent 4px);
      }
      .st-key-material_cards button p {white-space:normal;font-size:0.8rem;line-height:1.35;margin:0 0 .35rem}
      .st-key-material_cards button strong {font-size:0.95rem}
      .st-key-material_cards button code {font-size:.7rem;border-radius:4px;padding:.1rem .3rem}
      .st-key-material_cards button[aria-pressed="true"] {
        border:2px solid #e99527;box-shadow:inset 0 0 0 1px #e99527;
        background-color:rgba(233,149,39,.12);
      }
      .st-key-account_utility {align-items:center;gap:.5rem}
      .st-key-account_utility [data-testid="stButton"] button {height:auto;min-height:32px;padding:.2rem .5rem;font-size:.85rem}
      .st-key-drawing_upload [data-testid="stButton"] button {height:auto;min-height:44px;font-size:.9rem;padding:.5rem .75rem}
      .st-key-drawing_upload [data-testid="stFileUploaderDropzone"] {padding:.5rem}
    </style>""",
        unsafe_allow_html=True,
    )
    with st.container(key="material_cards"):
        return choice_buttons("Material", options, key=key, format_func=card_label)
