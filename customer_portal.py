"""Compatibility entrypoint for the retired standalone customer portal."""

import streamlit as st


st.set_page_config(page_title="O-Plates My Orders", layout="wide")
st.switch_page("pages/2_My_Orders.py")
