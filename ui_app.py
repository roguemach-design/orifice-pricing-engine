"""Compatibility entrypoint for the pre-multipage customer UI service."""

import streamlit as st


st.set_page_config(page_title="O-Plates", layout="wide")
st.switch_page("pages/1_Quote.py")
