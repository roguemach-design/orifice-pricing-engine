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
admin_key = (os.environ.get("ADMIN_API_KEY") or os.environ.get("API_KEY") or "").strip()

# ----------------------------
# Helpers
# ----------------------------
def _df_height_for_rows(n: int) -> int:
    if n <= 5:
        return 220
    if n <= 12:
        return 340
    return 480


def _safe_dict(x) -> Dict[str, Any]:
    return x if isinstance(x, dict) else {}


def _kv_table(d: Dict[str, Any], order: Optional[list[str]] = None) -> pd.DataFrame:
    """Render dict as a clean 2-col dataframe (Field / Value) in a stable order."""
    rows: list[tuple[str, Any]] = []
    if order:
        for k in order:
            if k in d:
                rows.append((k, d.get(k, "")))
        for k in d.keys():
            if k not in order:
                rows.append((k, d.get(k, "")))
    else:
        for k, v in d.items():
            rows.append((k, v))

    return pd.DataFrame(rows, columns=["Field", "Value"])


def api_get(path: str, *, params: dict | None = None) -> requests.Response:
    headers: dict[str, str] = {}
    if admin_key:
        headers["x-api-key"] = admin_key
    return requests.get(f"{API_BASE}{path}", headers=headers, params=params, timeout=30)


def api_put(path: str, *, json_body: dict | None = None) -> requests.Response:
    headers: dict[str, str] = {}
    if admin_key:
        headers["x-api-key"] = admin_key
    return requests.put(f"{API_BASE}{path}", headers=headers, json=json_body, timeout=30)


# ----------------------------
# DEBUG OUTPUT (optional)
# ----------------------------
with st.sidebar:
    debug = st.toggle("Debug mode", value=False)

# ----------------------------
# Guardrails
# ----------------------------
if not admin_key:
    st.warning("Missing ADMIN_API_KEY (or API_KEY). Set it in your Render env vars for this service.")
    st.stop()

# ----------------------------
# Pricing knobs (Admin-editable)
# ----------------------------
st.subheader("Pricing knobs")
st.caption("Toggle materials / thickness / lead times without redeploy. Saved in Postgres via the API.")

cfg_data: dict | None = None
cfg_load_error: Optional[str] = None

try:
    r_cfg = api_get("/admin/config")
    if r_cfg.status_code == 200:
        cfg_data = r_cfg.json() if isinstance(r_cfg.json(), dict) else None
        if cfg_data is None:
            cfg_load_error = "Config response was not a JSON object."
    elif r_cfg.status_code == 404:
        cfg_load_error = "API does not have /admin/config yet. Deploy the updated api_app.py."
    elif r_cfg.status_code == 401:
        cfg_load_error = "Unauthorized (401). Check ADMIN_API_KEY."
    else:
        cfg_load_error = f"Failed to load config: {r_cfg.status_code} {r_cfg.text}"
except Exception as e:
    cfg_load_error = f"Failed to load config: {e}"

if cfg_load_error:
    st.warning(cfg_load_error)

if cfg_data:
    material_enabled: dict = cfg_data.get("material_enabled", {}) or {}
    thickness_enabled_by_material: dict = cfg_data.get("thickness_enabled_by_material", {}) or {}
    lead_time_enabled: dict = cfg_data.get("lead_time_enabled", {}) or {}
    default_lead_time_days = cfg_data.get("default_lead_time_days", 21)

    # ---- Materials ----
    st.markdown("### Availability")
    st.markdown("**Materials**")

    mats = sorted(material_enabled.keys())
    if not mats:
        st.info("No materials found in config.")
    else:
        mat_cols = st.columns(min(4, max(1, len(mats))))
        new_material_enabled = dict(material_enabled)

        for i, m in enumerate(mats):
            with mat_cols[i % len(mat_cols)]:
                new_material_enabled[m] = st.checkbox(
                    m,
                    value=bool(material_enabled.get(m, False)),
                    key=f"mat_{m}",
                )

    # ---- Lead times ----
    st.markdown("**Lead times (days)**")
    lt_days = sorted([int(x) for x in lead_time_enabled.keys()]) if lead_time_enabled else []
    new_lead_time_enabled = {str(d): bool(lead_time_enabled.get(str(d), False)) for d in lt_days}

    if not lt_days:
        st.info("No lead times found in config.")
    else:
        lt_cols = st.columns(min(4, max(1, len(lt_days))))
        for i, d in enumerate(lt_days):
            with lt_cols[i % len(lt_cols)]:
                new_lead_time_enabled[str(d)] = st.checkbox(
                    f"{d} days",
                    value=bool(lead_time_enabled.get(str(d), False)),
                    key=f"lt_{d}",
                )

    default_lead_time_days = st.number_input(
        "Default lead time (days)",
        min_value=1,
        max_value=365,
        value=int(default_lead_time_days) if str(default_lead_time_days).isdigit() else 21,
        step=1,
        key="default_lt",
    )

    # ---- Thickness by material ----
    st.markdown("**Thickness by material**")
    new_thickness_enabled_by_material: dict[str, dict[str, bool]] = {}

    if not thickness_enabled_by_material:
        st.info("No thickness map found in config.")
    else:
        for m in sorted(thickness_enabled_by_material.keys()):
            tmap = thickness_enabled_by_material.get(m, {}) or {}
            # keys are strings like "0.25"
            th_keys = sorted(tmap.keys(), key=lambda x: float(x))

            with st.expander(f"{m} thickness availability", expanded=False):
                th_cols = st.columns(min(4, max(1, len(th_keys))))
                new_map = dict(tmap)
                for i, t in enumerate(th_keys):
                    label = f'{float(t):.3f}"'
                    with th_cols[i % len(th_cols)]:
                        new_map[t] = st.checkbox(
                            label,
                            value=bool(tmap.get(t, False)),
                            key=f"th_{m}_{t}",
                        )
                new_thickness_enabled_by_material[m] = new_map

    # ---- Save ----
    c1, c2 = st.columns([1, 2])
    with c1:
        save_cfg = st.button("💾 Save pricing knobs", type="primary", use_container_width=True)
    with c2:
        st.caption("Tip: uncheck a lead time to remove it from quoting immediately (no redeploy).")

    if save_cfg:
        payload = dict(cfg_data)

        # Only overwrite if we successfully built the new maps
        if mats:
            payload["material_enabled"] = new_material_enabled
        if lt_days:
            payload["lead_time_enabled"] = new_lead_time_enabled
        payload["default_lead_time_days"] = int(default_lead_time_days)

        if thickness_enabled_by_material:
            payload["thickness_enabled_by_material"] = new_thickness_enabled_by_material

        try:
            r_save = api_put("/admin/config", json_body=payload)
            if r_save.status_code == 200:
                st.success("Saved. New settings apply immediately for pricing/checkout.")
            elif r_save.status_code == 401:
                st.error("Unauthorized (401) saving config. Check ADMIN_API_KEY.")
                if debug:
                    st.code(r_save.text)
            else:
                st.error(f"Failed to save: {r_save.status_code}")
                if debug:
                    st.code(r_save.text)
        except Exception as e:
            st.error(f"Failed to save config: {e}")

    if debug:
        st.subheader("DEBUG: /admin/config raw")
        st.json(cfg_data)

st.divider()

# ----------------------------
# Orders viewer
# ----------------------------
st.subheader("Orders")

colA, colB, colC = st.columns([2, 1, 1])
with colA:
    q = st.text_input("Search (email / session id / order id)", value="")
with colB:
    limit = st.number_input("Limit", min_value=1, max_value=200, value=50, step=1)
with colC:
    refresh = st.button("🔄 Refresh", use_container_width=True)

params = {"q": q.strip(), "limit": int(limit)} if q.strip() else {"limit": int(limit)}

try:
    r = api_get("/admin/orders", params=params)
    if r.status_code != 200:
        st.error(f"API error: {r.status_code}")
        if debug:
            st.code(r.text)
        st.stop()
    orders = r.json()
except Exception as e:
    st.error(f"Failed to load orders: {e}")
    st.stop()

if debug:
    st.subheader("DEBUG: Orders response type")
    st.write(type(orders))
    st.subheader("DEBUG: First order JSON")
    st.json(orders[0] if isinstance(orders, list) and orders else {"note": "No orders returned"})

if not orders:
    st.info("No orders found.")
    st.stop()

df = pd.DataFrame(orders)

# Friendly columns
for c in ["created_at", "amount_total_usd", "amount_shipping_usd"]:
    if c not in df.columns:
        df[c] = None

# Sort newest first if created_at exists
try:
    df["created_at_dt"] = pd.to_datetime(df["created_at"], errors="coerce")
    df = df.sort_values("created_at_dt", ascending=False).drop(columns=["created_at_dt"])
except Exception:
    pass

show_cols = [c for c in ["order_number_display", "created_at", "customer_email", "amount_total_usd", "shipping_service"] if c in df.columns]
st.dataframe(df[show_cols], use_container_width=True, hide_index=True, height=_df_height_for_rows(len(df)))

# Select an order to view detail
order_ids = df["id"].tolist() if "id" in df.columns else []
order_labels = []
for _, row in df.iterrows():
    label = (row.get("order_number_display") or "").strip() or row.get("id", "")
    email = (row.get("customer_email") or "").strip()
    created = (row.get("created_at") or "").strip()
    order_labels.append(f"{label} — {email} — {created}")

selected = st.selectbox("Select an order", options=list(range(len(order_ids))), format_func=lambda i: order_labels[i])

order_id = order_ids[selected]

st.subheader("Order detail")

try:
    r2 = api_get(f"/admin/orders/{order_id}")
    if r2.status_code != 200:
        st.error(f"API error: {r2.status_code}")
        if debug:
            st.code(r2.text)
        st.stop()
    detail = r2.json()
except Exception as e:
    st.error(f"Failed to load order detail: {e}")
    st.stop()

# Display top-level fields
top_order = _safe_dict(detail)
order_df = _kv_table(
    top_order,
    order=[
        "order_number_display",
        "created_at",
        "customer_email",
        "amount_subtotal_usd",
        "amount_shipping_usd",
        "amount_total_usd",
        "shipping_service",
        "shipping_name",
        "stripe_session_id",
        "stripe_payment_intent",
        "customer_id",
        "id",
    ],
)

st.dataframe(order_df, use_container_width=True, hide_index=True, height=_df_height_for_rows(len(order_df)))

# Quote payload details
quote_payload = _safe_dict(detail.get("quote_payload"))
if quote_payload:
    st.subheader("Quote payload")

    # Cart case
    if "cart_items" in quote_payload and isinstance(quote_payload["cart_items"], list):
        cart_items = quote_payload["cart_items"]
        st.caption(f"Cart items: {len(cart_items)}")
        items_df = pd.DataFrame(cart_items)
        st.dataframe(items_df, use_container_width=True, hide_index=True, height=_df_height_for_rows(len(items_df)))
    else:
        inputs_df = _kv_table(
            quote_payload,
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
