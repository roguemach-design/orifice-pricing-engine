"""Visible finite choices without changing canonical configurator values."""

import streamlit as st
from material_labels import MATERIAL_COPY


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


# Display-only finishes are keyed by the unchanged canonical material values.
MATERIAL_FINISH = {
    "304": "linear-gradient(115deg,#8e9ba5 0%,#d9e0e5 32%,#a9b5be 57%,#e0e5e9 78%,#919fa9 100%)",
    "316": "linear-gradient(115deg,#768b99 0%,#bfcdd5 30%,#8fa4b1 57%,#c9d5dd 78%,#748996 100%)",
    "Carbon Steel": "linear-gradient(115deg,#303840 0%,#525c65 32%,#3b454e 57%,#626c75 78%,#303940 100%)",
}


def material_cards(options, *, key):
    """Native accessible selection; display copy never changes canonical values."""

    options = list(options)

    def card_label(value):
        name, description = MATERIAL_COPY.get(value, (value, ""))
        return f"**{name}**\n\n{description}"

    finish_css = "\n".join(
        f'.st-key-material_cards [data-testid="stButtonGroup"] button:nth-of-type({index})::before '
        + '{background-image:repeating-linear-gradient(100deg,rgba(255,255,255,.08) 0px,'
        + 'rgba(255,255,255,.08) 1px,transparent 1px,transparent 3px),'
        + MATERIAL_FINISH[value] + ';}'
        for index, value in enumerate(options, 1) if value in MATERIAL_FINISH
    )

    st.markdown(
        """<style>
      .st-key-material_cards [data-testid="stElementContainer"]:has([data-testid="stButtonGroup"]) {width:100%!important}
      .st-key-material_cards [data-testid="stButtonGroup"],
      .st-key-material_cards [data-testid="stButtonGroup"] > div {width:100%;max-width:none;flex-wrap:wrap;gap:.75rem}
      .st-key-material_cards [data-testid="stButtonGroup"] button {
        position:relative;flex:1 1 155px;min-width:0;max-width:100%;height:auto;min-height:150px;
        display:flex;flex-direction:column;align-items:stretch;justify-content:flex-start;
        padding:.75rem;text-align:left;border:2px solid #343e49;border-radius:8px;
        background:#111820;color:#dbe1e7;font-family:inherit;
      }
      .st-key-material_cards [data-testid="stButtonGroup"] button::before {
        content:"";display:block;width:100%;height:64px;flex-shrink:0;
        border-radius:4px;margin-bottom:.75rem;background-color:#48535e;
      }
      .st-key-material_cards button [data-testid="stMarkdownContainer"] {width:100%;text-align:left}
      .st-key-material_cards button p {white-space:normal;font-size:.875rem!important;font-weight:400;
        line-height:1.4!important;margin:0 0 .35rem!important;color:#dbe1e7}
      .st-key-material_cards button strong {font-size:1rem!important;font-weight:600;line-height:1.35;color:#fff}
      .st-key-material_cards button[aria-pressed="true"],
      .st-key-material_cards button[aria-checked="true"] {
        border:2px solid #e99527;box-shadow:inset 0 0 0 1px #e99527;background-color:#24201a;
      }
      .st-key-material_cards button:focus-visible {outline:3px solid #e99527;outline-offset:3px}
      .st-key-account_utility {align-items:center;gap:.5rem}
      .st-key-account_utility [data-testid="stButton"] button {height:auto;min-height:32px;padding:.2rem .5rem;font-size:.85rem}
      .st-key-drawing_upload [data-testid="stButton"] button {height:auto;min-height:44px;font-size:.9rem;padding:.5rem .75rem}
      .st-key-drawing_upload [data-testid="stFileUploaderDropzone"] {padding:.5rem}
    """ + finish_css + "</style>",
        unsafe_allow_html=True,
    )
    with st.container(key="material_cards"):
        return choice_buttons("Material", options, key=key, format_func=card_label)
