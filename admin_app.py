# admin_app.py
import os
from datetime import datetime
from typing import Any, Dict, Optional

import pandas as pd
import requests
import streamlit as st

# IMPORTANT: set_page_config must be the first Streamlit call
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

    admin_key = (
        st.text_input(
            "Admin API Key",
            type="password",
            value=os.environ.get("ADMIN_API_KEY", ""),
            help="Must match ADMIN_API_KEY on the API service (or API_KEY if admin falls back).",
        )
        .strip()
    )

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
def api_get(path: str, *, params: dict | None = None) -> requests.Response:
    headers: dict[str, str] = {}
    if admin_key:
        headers["x-api-key"] = admin_key
    return requests.get(f"{API_BASE}{path}", headers=headers, params=params, timeout=30)


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
    """
    Render dict as a clean 2-col dataframe (Field / Value) in a stable order.
    """
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


def _df_height_for_rows(n_rows: int) -> int:
    """
    Approximate a dataframe height so it doesn't scroll.
    """
    header = 38
    row_h = 34
    padding = 10
    # cap to keep page usable; adjust if you want even taller
    return min(900, header + n_rows * row_h + padding)


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
# Guardrails
# ----------------------------
if not admin_key:
    st.info("Enter your **Admin API Key** in the sidebar to load orders.")
    st.stop()

# ----------------------------
# Load orders
# ----------------------------
orders: list[dict] = []

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
                st.code(r.text)
                st.stop()

            if r.status_code != 200:
                st.error(f"API error: {r.status_code}")
                st.code(r.text)
                st.stop()

            data = r.json()

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
# Orders table
# ----------------------------
if not orders:
    st.warning("No orders returned.")
    st.stop()

rows = []
for o in orders:
    rows.append(
        {
            "Order #": o.get("order_number_display") or "",
            # keep internal ID for selection/lookups (not shown)
            "_order_id": o.get("id", ""),
            "Created": _dt(o.get("created_at", "")),
            "Email": o.get("customer_email", ""),
            "Total": _usd(o.get("amount_total_usd")),
            "Shipping": _usd(o.get("amount_shipping_usd")),
            "Ship Service": o.get("shipping_service") or "",
        }
    )

df = pd.DataFrame(rows)

st.subheader(f"Orders ({len(df)})")
st.dataframe(
    df.drop(columns=["_order_id"]),
    use_container_width=True,
    hide_index=True,
)

st.divider()

# ----------------------------
# Order details (clean table view)
# ----------------------------
st.subheader("Order details")

# Select by internal ID, but show a friendly label
order_options = df["_order_id"].tolist()

def _label_for_order_id(oid: str) -> str:
    row = df[df["_order_id"] == oid]
    if row.empty:
        return oid
    r0 = row.iloc[0]
    order_num = r0.get("Order #") or "OP-????"
    created = r0.get("Created") or ""
    email = r0.get("Email") or ""
    return f"{order_num} — {email} — {created}"

selected_id = st.selectbox("Select an order", order_options, format_func=_label_for_order_id)

detail: Optional[Dict[str, Any]] = None
try:
    r2 = api_get(f"/admin/orders/{selected_id}")
    if r2.status_code == 200:
        detail = r2.json()
    elif r2.status_code == 401:
        st.error("Unauthorized (401) when loading order details. Check your Admin API Key.")
        st.code(r2.text)
        st.stop()
    else:
        st.error(f"Could not load details: {r2.status_code}")
        st.code(r2.text)
        st.stop()
except Exception as e:
    st.error(f"Could not load details: {e}")
    st.stop()

if not detail:
    st.warning("No detail found for selected order.")
    st.stop()

# --- Order Summary table ---
order_summary = {
    "Order #": detail.get("order_number_display") or "",
    "Internal Order ID": detail.get("id", ""),
    "Created": _dt(detail.get("created_at", "")),
    "Customer Email": detail.get("customer_email", ""),
    "Subtotal": _usd(detail.get("amount_subtotal_usd")),
    "Shipping": _usd(detail.get("amount_shipping_usd")),
    "Total": _usd(detail.get("amount_total_usd")),
    "Shipping Service": detail.get("shipping_service", ""),
    "Ship To Name": detail.get("shipping_name", ""),
}

st.subheader("Order summary")
summary_df = _kv_table(
    order_summary,
    order=[
        "Order #",
        "Created",
        "Customer Email",
        "Subtotal",
        "Shipping",
        "Total",
        "Shipping Service",
        "Ship To Name",
        "Internal Order ID",
    ],
)
st.dataframe(
    summary_df,
    use_container_width=True,
    hide_index=True,
    height=_df_height_for_rows(len(summary_df)),
)

# --- Configured Inputs table (quote_payload) ---
qp = _safe_dict(detail.get("quote_payload"))
if qp:
    qp_display = dict(qp)

    # Ensure display defaults
    qp_display["handle_label"] = (qp_display.get("handle_label") or "").strip() or "No label"

    if not qp_display.get("chamfer"):
        qp_display["chamfer_width"] = None
    elif qp_display.get("chamfer_width") is None:
        qp_display["chamfer_width"] = 0.062

    # Pretty formatting for chamfer width
    if qp_display.get("chamfer_width") is not None:
        try:
            qp_display["chamfer_width"] = f'{float(qp_display["chamfer_width"]):.3f}'
        except Exception:
            pass

    st.subheader("Configured inputs")
    inputs_df = _kv_table(
        qp_display,
        order=[
            "quantity",
            "material",
            "thickness",
            "handle_width",
            "handle_length_from_bore",
            "paddle_dia",
            "bore_dia",
            "bore_tolerance",
            "chamfer",
            "chamfer_width",
            "handle_label",
            "ships_in_days",
        ],
    )

    st.dataframe(
        inputs_df,
        use_container_width=True,
        hide_index=True,
        height=_df_height_for_rows(len(inputs_df)),
    )

with st.expander("Show full order JSON"):
    st.json(detail)
