import os

import requests
import streamlit as st

from auth import auth_headers, is_logged_in, render_auth_sidebar


st.set_page_config(page_title="O-Plates Order Confirmation", layout="centered")
render_auth_sidebar(show_debug=False)

API_BASE = (os.environ.get("API_BASE") or "").strip().rstrip("/")

if not API_BASE:
    st.error("The O-Plates pricing service is not configured.")
    st.stop()


def _format_address(address: object) -> str:
    if not isinstance(address, dict):
        return ""
    city_state = ", ".join(
        value
        for value in [address.get("city"), address.get("state")]
        if value
    )
    lines = [address.get("line1"), address.get("line2")]
    locality = " ".join(
        value for value in [city_state, address.get("postal_code")] if value
    )
    lines.extend([locality, address.get("country")])
    return "\n".join(str(value) for value in lines if value)


def _shipping_service(code: str | None) -> str:
    return {
        "ups_ground": "UPS Ground",
        "ups_2day": "UPS 2nd Day Air",
        "ups_nextday": "UPS Next Day Air",
    }.get(code or "", (code or "").replace("_", " ").title())


session_id = st.query_params.get("session_id")
if isinstance(session_id, list):
    session_id = session_id[0] if session_id else None

if not session_id:
    st.error("This confirmation link is missing its checkout reference.")
    st.stop()

try:
    response = requests.get(
        f"{API_BASE}/orders/by-session/{session_id}",
        headers=auth_headers(),
        timeout=30,
    )
except requests.RequestException:
    response = None

if response is None or response.status_code != 200:
    st.title("Payment submitted")
    st.info("Your order details are still finalizing. Refresh this page in a moment.")
    if st.button("Refresh order status"):
        st.rerun()
    st.stop()

order = response.json()
if order.get("status") != "completed":
    st.title("Payment submitted")
    st.info("Stripe is confirming the payment. Your order will appear here shortly.")
    if st.button("Refresh order status"):
        st.rerun()
    st.stop()

st.title("Payment received ✅")
st.write("Thanks — your O-Plates order is confirmed.")

with st.container(border=True):
    st.subheader("Order summary")
    st.write(f"Order #: **{order.get('order_number_display') or '(finalizing…)'}**")
    st.write(f"Email: **{order.get('customer_email') or ''}**")
    st.write(f"Total paid: **${float(order.get('amount_total_usd') or 0):,.2f}**")
    shipping = _shipping_service(order.get("shipping_service"))
    if shipping:
        st.write(f"Shipping: **{shipping}**")

address = _format_address(order.get("shipping_address"))
if order.get("shipping_name") or address:
    st.subheader("Ship to")
    if order.get("shipping_name"):
        st.write(f"**{order['shipping_name']}**")
    if address:
        st.text(address)

st.caption("We’ll email the order confirmation and follow up with the approval drawing.")

if is_logged_in():
    if st.button("View My Orders"):
        st.switch_page("pages/2_My_Orders.py")
else:
    st.caption("Guest checkout is complete. You may close this page after saving your order number.")
