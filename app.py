# app.py
import streamlit as st
from auth import render_auth_sidebar, is_logged_in

st.set_page_config(page_title="O-Plates", layout="wide")

# Shared auth/login in the sidebar for ALL pages
render_auth_sidebar(show_debug=False)

# --------------------------------------------------
# Stripe return handling
# If Stripe sends us back with ?session_id=..., route
# to the Quote page where the success UI lives.
# --------------------------------------------------
session_id = st.query_params.get("session_id")

if isinstance(session_id, list):
    session_id = session_id[0] if session_id else None

if session_id:
    # Prevent redirect loop by clearing the param after switch
    st.query_params.clear()
    st.switch_page("pages/1_Quote.py")

# --------------------------------------------------
# Landing page content
# --------------------------------------------------
st.title("O-Plates")
st.caption("Configure → Quote → Order → Reorder")

st.divider()

col1, col2 = st.columns(2, gap="large")

with col1:
    st.subheader("Build a Plate")
    st.write(
        "If you’re purchasing **one configured plate**, you can start a quote and checkout fast."
    )
    st.info("Use the left navigation → **Quote**")

with col2:
    st.subheader("My Orders")
    st.write(
        "If you need to buy **multiple configured plates**, log in and use the Quote Cart."
    )
    st.info("Use the left navigation → **My Orders**")

st.divider()

if is_logged_in():
    st.success(
        "You’re logged in — orders placed from the Quote page will be saved to your account."
    )
else:
    st.warning(
        "You’re not logged in. Log in from the sidebar to save orders to your account."
    )
