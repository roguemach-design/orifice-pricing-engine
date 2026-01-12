# pages/2_My_Orders.py
from datetime import datetime
from typing import Any, Dict, Optional, List
import json

import pandas as pd
import streamlit as st

from auth import render_auth_sidebar, require_login, api_get


# ----------------------------
# Shared sidebar + guardrail
# ----------------------------
render_auth_sidebar(show_debug=True)   # flip to False after testing
require_login("Log in in the sidebar to view your orders.")


# ----------------------------
# Helpers
# ----------------------------
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


def _to_scalar(v: Any) -> Any:
    """
    Streamlit dataframe uses PyArrow; columns can't mix scalars with dict/list objects.
    Convert any complex value to a JSON string so Arrow conversion always succeeds.
    """
    if v is None:
        return ""
    if isinstance(v, (str, int, float, bool)):
        return v
    try:
        return json.dumps(v, indent=2, sort_keys=True, default=str)
    except Exception:
        return str(v)


def _kv_table(d: Dict[str, Any], order: Optional[list[str]] = None) -> pd.DataFrame:
    rows: list[tuple[str, Any]] = []
    if order:
        for k in order:
            if k in d:
                rows.append((k, _to_scalar(d.get(k, ""))))
        for k in d.keys():
            if k not in set(order):
                rows.append((k, _to_scalar(d.get(k, ""))))
    else:
        rows = [(k, _to_scalar(v)) for k, v in d.items()]
    return pd.DataFrame(rows, columns=["Field", "Value"])


# ----------------------------
# Page UI
# ----------------------------
st.title("My Orders")

# 👉 quick actions row
top = st.columns([1, 1, 2])
with top[0]:
    if st.button("➕ Start a Quote"):
        st.switch_page("pages/1_Quote.py")
with top[1]:
    if st.button("🧾 View Quote Cart"):
        st.switch_page("pages/3_Quote_Cart.py")

st.caption("View past orders tied to your login. Reorder coming next.")

top_cols = st.columns([1, 1, 2])
with top_cols[0]:
    refresh = st.button("🔄 Refresh")
with top_cols[1]:
    limit = st.number_input("Max rows", min_value=1, max_value=200, value=50, step=10)

orders: List[dict] = []

with st.spinner("Loading your orders..."):
    r = api_get("/me/orders", params={"limit": int(limit)})

    if r.status_code == 401:
        st.error("Unauthorized. Log out and log in again.")
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

if not orders:
    st.warning("No orders found for this account yet.")
    st.info(
        "Next step: if you have older orders from before login existed, "
        "we can add a **Claim past orders** button to attach them by email."
    )
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
    r2 = api_get(f"/me/orders/{selected_id}")

    if r2.status_code == 404:
        st.error("Order not found (or not owned by this user).")
        st.stop()
    if r2.status_code == 401:
        st.error("Unauthorized. Log out and log in again.")
        st.stop()
    if r2.status_code != 200:
        st.error(f"API error: {r2.status_code}")
        st.code(r2.text)
        st.stop()

    detail = r2.json()

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
