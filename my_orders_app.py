"""Compatibility entrypoint for the retired standalone order-history app."""

import streamlit as st


st.set_page_config(page_title="O-Plates My Orders", layout="wide")
st.switch_page("pages/2_My_Orders.py")
