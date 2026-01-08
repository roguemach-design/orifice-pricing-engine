# customer_portal.py
import os
from datetime import datetime
from typing import Any, Dict, Optional, List

import pandas as pd
import requests
import streamlit as st
from supabase import create_client, Client


# ----------------------------
# Page setup
# ----------------------------
st.set_page_config(page_title="O-Plates Customer Portal", layout="wide")
st.title("O-Plates Customer Portal")
st.caption("Login → view past orders → reorder (next)")

API_BASE = os.environ.get("API_BASE", "https://orifice-pricing-api.onrender.com").rstrip("/")
SUPABASE_URL = (os.environ.get("SUPABASE_URL") or "").strip()
SUPABASE_ANON_KEY = (os.environ.get("SUPABASE_ANON_KEY") or "").strip()

if "auth" not in st.session_state:
    st.session_state.auth = {
        "access_token": None,
        "refresh_token": None,
        "user": None,
        "email": None,
    }

def _sb() -> Client:
    if not SUPABASE_URL or not SUPABASE_ANON_KEY:
        st.error("Missing SUPABASE_URL / SUPABASE_ANON_KEY env vars.")
        st.stop()
    return create_client(SUPABASE_URL, SUPABASE_ANON_KEY)

def _is_logged_in() -> bool:
    return bool(st.session_state.auth.get("access_token"))

def _logout() -> None:
    st.session_state.auth = {"access_token": None, "refresh_token": None, "user": None, "email": None}
    st.rerun()

def _headers() -> Dict[str, str]:
    tok = st.session_state.auth.get("access_token")
    return {"Authorization": f"Bearer {tok}"} if tok else {}

def api_get(path: str, *, params: dict | None = None) -> requests.Response:
    return requests.get(f"{API_BASE}{path}", headers=_headers(), params=params, timeout=30)

def _usd(x) -> str:
    try:
        if x is None:
            return ""
        return f"${float(x):,.2f}"
    except Exception:
        return str(x)

def _dt(x: str) -> str:
    try:
        if not x:
            return ""
        return datetime.fromisoformat(x.replace("Z", "+00:00")).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return str(x)

def _safe_dict(x) -> Dict[str, Any]:
    return x if isinstance(x, dict) else {}

def _kv_table(d: Dict[str, Any], order: Optional[list[str]] = None) -> pd.DataFrame:
    rows: list[tuple[str, Any]] = []
    if order:
        for k in order:
            if k in d:
                rows.append((k, d.get(k, "")))
        for k in d.keys():
            if k not in set(order):
                rows.append((k, d.get(k, "")))
    else:
        rows = [(k, v) for k, v in d.items()]
    return pd.DataFrame(rows, columns=["Field", "Value"])


# ----------------------------
# Sidebar: auth
# ----------------------------
with st.sidebar:
    st.subheader("Connection")
    st.write("API Base:")
    st.code(API_BASE)

    st.divider()
    st.subheader("Login")

    if not _is_logged_in():
        email = st.text_input("Email", value=st.session_state.auth.get("email") or "", placeholder="you@company.com").strip()

        col1, col2 = st.columns(2)
        with col1:
            send_code = st.button("Send code")
        with col2:
            verify_code = st.button("Verify code")

        otp_code = st.text_input("6-digit code", value="", placeholder="123456", max_chars=6).strip()

        if send_code:
            if not email:
                st.error("Enter your email first.")
            else:
                try:
                    sb = _sb()
                    # Supabase Email OTP (sends a 6-digit code if enabled in Supabase Auth settings)
                    sb.auth.sign_in_with_otp({"email": email})
                    st.session_state.auth["email"] = email
                    st.success("Code sent. Check your email.")
                except Exception as e:
                    st.error(f"Failed to send code: {e}")

        if verify_code:
            if not email or not otp_code:
                st.error("Enter email + the 6-digit code.")
            else:
                try:
                    sb = _sb()
                    resp = sb.auth.verify_otp(
                        {
                            "email": email,
                            "token": otp_code,
                            "type": "email",
                        }
                    )
                    # resp has session + user
                    session = getattr(resp, "session", None) or (resp.get("session") if isinstance(resp, dict) else None)
                    user = getattr(resp, "user", None) or (resp.get("user") if isinstance(resp, dict) else None)

                    if not session:
                        st.error("OTP verify did not return a session. Check Supabase OTP settings.")
                    else:
                        st.session_state.auth = {
                            "access_token": session.access_token,
                            "refresh_token": session.refresh_token,
                            "user": user,
                            "email": email,
                        }
                        st.success("Logged in.")
                        st.rerun()
                except Exception as e:
                    st.error(f"Verify failed: {e}")

    else:
        st.success(f"Logged in as: {st.session_state.auth.get('email')}")
        if st.button("Log out"):
            _logout()


# ----------------------------
# Guardrail
# ----------------------------
if not _is_logged_in():
    st.info("Log in to view your orders.")
    st.stop()


# ----------------------------
# My Orders
# ----------------------------
st.subheader("My Orders")

top_cols = st.columns([1, 1, 2])
with top_cols[0]:
    refresh = st.button("🔄 Refresh")
with top_cols[1]:
    limit = st.number_input("Max rows", min_value=1, max_value=200, value=50, step=10)

orders: List[dict] = []

with st.spinner("Loading your orders..."):
    try:
        r = api_get("/me/orders", params={"limit": int(limit)})
        if r.status_code == 401:
            st.error("Unauthorized. Your session may have expired. Log out and log in again.")
            st.stop()
        if r.status_code != 200:
            st.error(f"API error: {r.status_code}")
            st.code(r.text)
            st.stop()

        data = r.json()
        if isinstance(data, list):
            orders = data
        else:
            orders = data.get("orders", [])
    except Exception as e:
        st.error(f"Failed to load orders: {e}")
        st.stop()

if not orders:
    st.warning("No orders found for this account yet.")
    st.stop()

rows = []
for o in orders:
    rows.append(
        {
            "Order #": o.get("order_number_display") or "(finalizing...)",
            "_order_id": o.get("id", ""),
            "Created": _dt(o.get("created_at", "")),
            "Email": o.get("customer_email", ""),
            "Total": _usd(o.get("amount_total_usd")),
            "Shipping": _usd(o.get("amount_shipping_usd")),
            "Ship Service": o.get("shipping_service") or "",
        }
    )

df = pd.DataFrame(rows)

st.dataframe(df.drop(columns=["_order_id"]), use_container_width=True, hide_index=True)
st.divider()


# ----------------------------
# Order details
# ----------------------------
st.subheader("Order details")

order_ids = df["_order_id"].tolist()

def _label(oid: str) -> str:
    row = df[df["_order_id"] == oid]
    if row.empty:
        return oid
    r0 = row.iloc[0]
    return f"{r0.get('Order #')} — {r0.get('Created')}"

selected_id = st.selectbox("Select an order", order_ids, format_func=_label)

detail: Optional[Dict[str, Any]] = None
with st.spinner("Loading order details..."):
    try:
        r2 = api_get(f"/me/orders/{selected_id}")
        if r2.status_code == 404:
            st.error("Order not found (or not owned by this user).")
            st.stop()
        if r2.status_code != 200:
            st.error(f"API error: {r2.status_code}")
            st.code(r2.text)
            st.stop()
        detail = r2.json()
    except Exception as e:
        st.error(f"Failed to load order detail: {e}")
        st.stop()

summary = {
    "Order #": detail.get("order_number_display") or "",
    "Created": _dt(detail.get("created_at", "")),
    "Email": detail.get("customer_email", ""),
    "Subtotal": _usd(detail.get("amount_subtotal_usd")),
    "Shipping": _usd(detail.get("amount_shipping_usd")),
    "Total": _usd(detail.get("amount_total_usd")),
    "Shipping Service": detail.get("shipping_service") or "",
    "Ship To Name": detail.get("shipping_name") or "",
}

st.subheader("Order summary")
st.dataframe(_kv_table(summary), use_container_width=True, hide_index=True)

qp = _safe_dict(detail.get("quote_payload"))
if qp:
    # normalize display defaults to match your quote expectations
    qp["handle_label"] = (qp.get("handle_label") or "").strip() or "No label"
    if not qp.get("chamfer"):
        qp["chamfer_width"] = None

    st.subheader("Configured inputs")
    st.dataframe(_kv_table(qp), use_container_width=True, hide_index=True)

st.divider()

# ----------------------------
# Reorder (next step)
# ----------------------------
st.subheader("Reorder")
st.info(
    "Next: a **Reorder** button will push this order’s `quote_payload` back into the configurator "
    "(or create a saved cart/quote)."
)

with st.expander("Show full order JSON"):
    st.json(detail)

