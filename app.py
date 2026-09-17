# app.py
import streamlit as st

st.set_page_config(page_title="O-Plates", layout="wide")

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

# The marketing site and any legacy root links should enter the configurator
# directly. Account and quote-cart capabilities remain available from there.
st.switch_page("pages/1_Quote.py")
