"""Safe captured-email review: authentication and a deliberate button are required."""

import os
import streamlit as st
from auth import render_auth_sidebar, require_login, api_post
from frozen_plate.presentation import APPROVAL_COPY, BUTTON
from frozen_plate.runtime import ui_enabled

st.set_page_config(page_title="O-Plates Drawing Approval")
if not ui_enabled():
    st.stop()
render_auth_sidebar(show_debug=False)
require_login("Sign in to review and approve your attached drawing.")
token = st.query_params.get("token", "")
if not token or len(token) > 2048:
    st.error("Open the current drawing link from your confirmation email.")
    st.stop()
response = api_post("/me/frozen-plates/inspect", payload={"token": token})
if response.status_code != 200:
    st.error(
        "This drawing link is unavailable, expired, or belongs to another customer."
    )
    st.stop()
review = response.json()
if review.get("historical"):
    st.warning(
        "A newer revision requires separate review. Open My Orders for the current drawing."
    )
    st.stop()
if review["state"] == "approved":
    st.title("YOUR ORDER IS IN PRODUCTION")
    st.stop()
context = review["context"]
st.title("Review your attached drawing")
st.write(
    f"Drawing {context['drawing']} · {context['revision']} · Quantity {context['quantity']}"
)
pdf = api_post("/me/frozen-plates/pdf", payload={"token": token})
if pdf.status_code != 200:
    st.error("The exact drawing could not be verified.")
    st.stop()
st.download_button(
    "Download drawing PDF",
    pdf.content,
    file_name=context["filename"],
    mime="application/pdf",
)
st.write(APPROVAL_COPY)
if st.button(BUTTON):
    approved = api_post("/me/frozen-plates/approve", payload={"token": token})
    if approved.status_code == 200:
        st.title("YOUR ORDER IS IN PRODUCTION")
    else:
        st.error("Approval was not recorded. Refresh and review the current drawing.")
