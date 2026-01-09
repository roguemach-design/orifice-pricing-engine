# app.py
import streamlit as st
from auth import render_auth_sidebar, is_logged_in

st.set_page_config(page_title="O-Plates", layout="wide")

# Shared auth/login in the sidebar for ALL pages
render_auth_sidebar(show_debug=False)

st.title("O-Plates")
st.caption("Configure → Quote → Order → Reorder")

st.divider()

col1, col2 = st.columns(2, gap="large")

with col1:
    st.subheader("Build a Plate")
    st.write("Create an instant quote and checkout with shipping options.")
    st.info("Use the left navigation → **Quote**")

with col2:
    st.subheader("My Orders")
    st.write("View past orders tied to your account and reorder (next).")
    st.info("Use the left navigation → **My Orders**")

st.divider()

if is_logged_in():
    st.success("You’re logged in — orders placed from the Quote page will be saved to your account.")
else:
    st.warning("You’re not logged in. Log in from the sidebar to save orders to your account.")
