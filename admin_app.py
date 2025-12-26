# admin_app.py
import os
from datetime import datetime

import requests
import streamlit as st
st.write("✅ ADMIN APP LOADED — build marker: v2-orders-debug")


st.set_page_config(page_title="O-Plates Admin", layout="wide")

st.title("O-Plates Admin Dashboard")
st.caption("View recent orders stored in Postgres via the Orifice Pricing API.")

# ----------------------------
# Config
# ----------------------------
API_BASE = os.environ.get("API_BASE", "https://orifice-pricing-api.onrender.com").rstrip("/")
DEFAULT_LIMIT = int(os.environ.get("ADMIN_DEFAULT_LIMIT", "50"))

# ----------------------------
# Sidebar
# ----------------------------
with st.sidebar:
    st.subheader("Connection")
    st.write("API Base:")
    st.code(API_BASE)

    admin_key = st.text_input(
        "Admin API Key",
        type="password",
        value=os.environ.get("ADMIN_API_KEY", ""),  # Render env var can prefill
        help="This is the same value as API_KEY on the API service.",
    ).strip()

    st.divider()
    st.subheader("Filters")
    limit = st.number_input("Max rows", min_value=1, max_value=500, value=DEFAULT_LIMIT, step=10)

    col1, col2 = st.columns(2)
    with col1:
        refresh = st.button("🔄 Refresh")
    with col2:
        ping = st.button("🩺 Ping API")

# ----------------------------
# Helpers
# ----------------------------
def _fmt_usd(cents: int | None) -> str:
    if cents is None:
        return ""
    return f"${(cents / 100.0):,.2f}"


def _fmt_dt(x) -> str:
    if not x:
        return ""
    try:
        if isinstance(x, str):
            return datetime.fromisoformat(x.replace("Z", "+00:00")).strftime("%Y-%m-%d %H:%M")
        return str(x)
    except Exception:
        return str(x)


def api_get(path: str, *, params: dict | None = None) -> requests.Response:
    headers = {}
    if admin_key:
        headers["x-api-key"] = admin_key
    return requests.get(f"{API_BASE}{path}", headers=headers, params=params, timeout=30)


# ----------------------------
# Top actions
# ----------------------------
if ping:
    try:
        r = requests.get(f"{API_BASE}/health", timeout=10)
        st.success(f"API /health: {r.status_code} {r.text}")
    except Exception as e:
        st.error(f"API ping failed: {e}")

st.divider()

# ----------------------------
# Guardrails so it never renders blank
# ----------------------------
if not admin_key:
    st.info("Enter your **Admin API Key** in the sidebar to load orders.")
    st.stop()

# ----------------------------
# Load orders
# ----------------------------
# Fetch when page loads, and when user clicks refresh
orders = []
if refresh or True:
    with st.spinner("Loading orders..."):
        try:
            r = api_get("/admin/orders", params={"limit": int(limit)})

            if r.status_code == 401:
                st.error("Unauthorized (401). Your Admin API Key is wrong or not being sent.")
                st.code(r.text)
                st.stop()

            if r.status_code == 404:
                st.error("404 Not Found. Your API does not have /admin/orders yet (or the route path differs).")
                st.write("Fix: add an admin endpoint in api_app.py, or change this app to call the correct route.")
                st.code(r.text)
                st.stop()

            if r.status_code != 200:
                st.error(f"API error: {r.status_code}")
                st.code(r.text)
                st.stop()

            try:
                data = r.json()
            except Exception:
                st.error("API did not return JSON.")
                st.code(r.text)
                st.stop()
                
            # --- TEMP DEBUG: show what the API returns ---
                st.subheader("DEBUG: First order JSON")
                st.json(orders[0] if orders else {})
                st.stop()


            # Support either:
            # 1) API returns {"orders": [...]} (dict)
            # 2) API returns [...] (list)
            if isinstance(data, dict):
                orders = data.get("orders", [])
            elif isinstance(data, list):
                orders = data
            else:
                st.error(f"Unexpected API response type: {type(data)}")
                st.stop()

        except Exception as e:
            st.error(f"Failed to load orders: {e}")
            st.stop()

# ----------------------------
# Render table
# ----------------------------
if not orders:
    st.warning("No orders returned.")
    st.stop()

rows = []
for o in orders:
    rows.append(
        {
            "Order ID": o.get("id") or "",
            "Created": _fmt_dt(o.get("created_at")),
            "Email": o.get("customer_email") or "",
            "Total": _fmt_usd(o.get("amount_total_cents")),
            "Subtotal": _fmt_usd(o.get("amount_subtotal_cents")),
            "Shipping": _fmt_usd(o.get("amount_shipping_cents")),
            "Ship Service": o.get("shipping_service") or "",
            "Stripe Session": o.get("stripe_session_id") or "",
            "Payment Intent": o.get("stripe_payment_intent") or "",
        }
    )

st.subheader(f"Orders ({len(rows)})")
st.dataframe(rows, use_container_width=True, hide_index=True)

st.caption(
    "Tip: If you see 404 above, your API endpoint name probably differs. Tell me what route you created and I’ll align this file."
)
