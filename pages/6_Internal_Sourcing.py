"""Retired owner entry point; never forwards credentials or loads owner data."""
import streamlit as st
from owner_portal_transport import clear_owner_session

clear_owner_session(st.session_state)
st.query_params.clear()
st.title("Manufacturing Control has moved")
st.write("Open the dedicated owner application and unlock there to continue.")
st.link_button("Open Manufacturing Control", "https://mfgcontrol.o-plates.com/")
