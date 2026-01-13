import streamlit as st
import requests
import os

from auth import render_auth_sidebar, require_login

render_auth_sidebar(show_debug=False)
require_login("Log in to view your order confirmation.")

API_BASE = os.environ.get("API_BASE", "https://orifice-pricing-api.onrender.com").rstrip("/")

st.title("Payment received ✅")
st.write("Thanks — we received your payment. We’re preparing your order now.")

session_id = st.query_params.get("session_id")
if isinstance(session_id, list):
    session_id = session_id[0] if session_id else None

if not session_id:
    st.error("Missing session ID.")
    st.stop()

with st.spinner("Loading order details…"):
    r = requests.get(f"{API_BASE}/orders/by-session/{session_id}", timeout=30)

if r.status_code != 200:
    st.warning("Order confirmed — details are still finalizing.")
    st.stop()

order = r.json()

st.subheader("Order summary")
st.write(f"Order #: **{order.get('order_number_display')}**")
st.write(f"Email: **{order.get('customer_email')}**")
st.write(f"Total paid: **${order.get('amount_total_usd'):.2f}**")

if st.button("View My Orders"):
    st.switch_page("pages/2_My_Orders.py")
