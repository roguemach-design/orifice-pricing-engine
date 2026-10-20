"""Owner authentication wraps the unchanged candidate customer entrypoint."""
import os
from pathlib import Path

import streamlit as st

from auth import auth_headers, current_user_id_hint, render_auth_sidebar
from drawing_intake.owner_access import verified_owner_access
from review_runtime import REVIEW_SERVICE, AUTH_API
from customer_navigation import render_customer_footer

ROOT = Path(__file__).resolve().parents[1]


def review_root():
    st.switch_page(ROOT / "pages/1_Quote.py")

st.set_page_config(page_title="O-Plates — isolated visual review", layout="wide")
# Register navigation before any stop: direct /Quote navigation must still run
# this entrypoint's authentication gate, never Streamlit's legacy pages mode.
selected = st.navigation([
    st.Page(review_root, default=True, visibility="hidden"),
    st.Page(ROOT / "pages/1_Quote.py", title="Configure your plate", url_path="Quote"),
    st.Page(ROOT / "pages/2_My_Orders.py", title="My Orders", url_path="My_Orders"),
    st.Page(ROOT / "pages/3_Quote_Cart.py", title="Quote Cart", url_path="Quote_Cart"),
    st.Page(ROOT / "pages/4_Success.py", url_path="Success", visibility="hidden"),
], position="hidden")
if (os.environ.get("RENDER_SERVICE_ID") != REVIEW_SERVICE
        or os.environ.get("V71_REVIEW_AUTH_API_BASE") != AUTH_API
        or os.environ.get("API_BASE") != "http://127.0.0.1:8505"
        or os.environ.get("OPLATES_OWNER_ACCEPTANCE_MODE") != "true"
        or os.environ.get("OPLATES_OWNER_TEST_CHECKOUT_ENABLED") != "false"):
    st.error("The isolated review environment is not configured.")
    st.stop()

render_auth_sidebar(show_debug=False)
if not verified_owner_access(
    AUTH_API, enabled=True, user_id_hint=current_user_id_hint(),
    headers={"x-api-key": os.environ.get("V71_REVIEW_AUTH_API_KEY", ""), **auth_headers()},
):
    st.info("Sign in with the existing approved staging owner account to review v7.1.")
    st.stop()

st.caption("ISOLATED VISUAL REVIEW · synthetic quotes · checkout, orders, emails and manufacturing writes unavailable")
content = st.container()
render_customer_footer()
with content:
    selected.run()
