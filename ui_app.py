# ui_app.py
import os
from datetime import datetime
from typing import Any, Dict, Optional

import requests
import streamlit as st

from pricing_engine import QuoteInputs, calculate_quote
import pricing_config as cfg


# -----------------------------
# Page setup (MUST be first Streamlit call)
# -----------------------------
st.set_page_config(page_title="Orifice Plate Instant Quote", layout="centered")

st.markdown(
    """
    <style>
    h1 {
      font-family: Arial, sans-serif;
      font-weight: 800;
      letter-spacing: 0.2px;
      margin-bottom: 0.25rem;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("Orifice Plate Instant Quote")


# -----------------------------
# Config
# -----------------------------
API_BASE = os.environ.get("API_BASE", "https://orifice-pricing-api.onrender.com").rstrip("/")
API_KEY = (os.environ.get("API_KEY") or "").strip()


# -----------------------------
# Sidebar debug
# -----------------------------
with st.sidebar:
    st.subheader("Diagnostics")
    st.write("API_BASE:", API_BASE)
    st.write("DEBUG UI has API_KEY?", bool(API_KEY))
    st.write("DEBUG API_KEY length:", len(API_KEY))
    debug_mode = st.toggle("Debug mode", value=False)


# -----------------------------
# Helpers (safe to keep)
# -----------------------------
def _estimate_area_sq_in(paddle_dia: float, handle_length_from_bore: float) -> float:
    return paddle_dia * (handle_length_from_bore + (paddle_dia / 2.0))


def _estimate_package_in(paddle_dia: float, handle_length_from_bore: float, thickness: float, qty: int) -> dict:
    paddle_radius = paddle_dia / 2.0
    product_length = handle_length_from_bore + paddle_radius
    product_width = paddle_dia
    return {
        "length": round(product_length + 4.0, 2),
        "width": round(product_width + 4.0, 2),
        "height": round(1.0 + (thickness if qty <= 1 else thickness * qty), 2),
    }


def _estimate_total_weight_lb(material: str, area_sq_in: float, thickness: float, qty: int) -> float:
    densities = {
        "304": 0.289,
        "316": 0.289,
        "Carbon Steel": 0.283,
        "Monel": 0.319,
        "Hastelloy": 0.321,
    }
    density = densities.get(material, 0.289)
    return round(area_sq_in * thickness * density * qty, 2)


def _qp_get(name: str) -> Optional[str]:
    """
    Streamlit query params can be str or list[str] depending on version.
    Return a single string if present.
    """
    qp = st.query_params
    if name not in qp:
        return None
    v = qp[name]
    if isinstance(v, list):
        return v[0] if v else None
    return v


# -----------------------------
# Success page (session_id in query params)
# -----------------------------
session_id = _qp_get("session_id")
if session_id:
    st.title("Payment received ✅")
    st.write("Thanks — we received your payment. We’re preparing your order now.")

    try:
        r = requests.get(f"{API_BASE}/orders/by-session/{session_id}", timeout=30)
        if r.status_code == 200:
            order = r.json()
            st.subheader("Order summary")
            st.write(f"Order ID: **{order.get('id','')}**")
            st.write(f"Email: **{order.get('customer_email','')}**")
            amt = order.get("amount_total_usd")
            if isinstance(amt, (int, float)):
                st.write(f"Total paid: **${amt:.2f}**")
            else:
                st.write(f"Total paid: **{amt}**")
            st.write(f"Shipping: **{order.get('shipping_service')}**")
            st.write("We’ll email your confirmation and approval drawing next.")
        else:
            st.info("Payment confirmed. Finalizing your order details… (refresh in a moment)")
            if debug_mode:
                st.write("orders/by-session status:", r.status_code)
                st.code(r.text)
    except Exception as e:
        st.info("Payment confirmed. Finalizing your order details… (refresh in a moment)")
        if debug_mode:
            st.write("Exception:", str(e))

    st.stop()


# -----------------------------
# Inputs
# -----------------------------
quantity = st.number_input("Qty", min_value=1, value=1, step=1)

material = st.selectbox("Material Type", options=list(cfg.PRICE_PER_SQ_IN.keys()))

thickness = st.selectbox(
    "Plate Thickness (in)",
    options=sorted(cfg.PRICE_PER_SQ_IN[material].keys()),
)

handle_width = st.number_input("Handle Width (in)", min_value=0.0, value=1.5, step=0.01)
handle_length = st.number_input("Handle Length from Bore (in)", min_value=0.0, value=9.0, step=0.01)
paddle_dia = st.number_input("Paddle Diameter (in)", min_value=0.01, max_value=48.0, value=3.0, step=0.01)
bore_dia = st.number_input("Bore Diameter (in)", min_value=0.01, value=1.0, step=0.01)

tol_options = sorted(cfg.INSPECTION_MINS_BY_TOL.keys())
bore_tolerance = st.selectbox(
    "Bore Tolerance (± in)",
    options=tol_options,
    index=tol_options.index(0.005) if 0.005 in tol_options else 0,
)

chamfer = st.checkbox("Chamfer", value=True)

ships_options = sorted(cfg.LEAD_TIME_MULTIPLIER.keys())
ships_in_days = st.selectbox(
    "Ships in (days)",
    options=ships_options,
    index=ships_options.index(21) if 21 in ships_options else 0,
)

st.divider()
st.subheader("Quote Summary")


# -----------------------------
# Validation
# -----------------------------
errors = []
if bore_dia >= paddle_dia:
    errors.append("Bore Diameter must be smaller than Paddle Diameter.")
if handle_length <= (paddle_dia / 2):
    errors.append("Handle Length (From Bore) must be longer than the Paddle Radius.")

if errors:
    for e in errors:
        st.error(e)
    st.stop()


# -----------------------------
# Pricing (local preview)
# -----------------------------
inputs = QuoteInputs(
    quantity=int(quantity),
    material=str(material),
    thickness=float(thickness),
    handle_width=float(handle_width),
    handle_length_from_bore=float(handle_length),
    paddle_dia=float(paddle_dia),
    bore_dia=float(bore_dia),
    bore_tolerance=float(bore_tolerance),
    chamfer=bool(chamfer),
    ships_in_days=int(ships_in_days),
)

result = calculate_quote(inputs)

c1, c2 = st.columns(2)
c1.metric("Unit Price", f"${result['unit_price']:,.2f}")
c2.metric("Total Price", f"${result['total_price']:,.2f}")


# -----------------------------
# Checkout
# -----------------------------
def start_checkout() -> None:
    # IMPORTANT: API expects {"inputs": QuoteRequest} per /openapi.json
    body = {
        "inputs": {
            "quantity": int(quantity),
            "material": str(material),
            "thickness": float(thickness),
            "handle_width": float(handle_width),
            "handle_length_from_bore": float(handle_length),
            "paddle_dia": float(paddle_dia),
            "bore_dia": float(bore_dia),
            "bore_tolerance": float(bore_tolerance),
            "chamfer": bool(chamfer),
            "ships_in_days": int(ships_in_days),
        }
    }

    headers: Dict[str, str] = {}
    if API_KEY:
        headers["x-api-key"] = API_KEY

    if debug_mode:
        st.sidebar.write("DEBUG sending x-api-key?", bool(headers.get("x-api-key")))
        st.sidebar.write("DEBUG sending x-api-key len:", len(headers.get("x-api-key") or ""))
        st.sidebar.write("DEBUG checkout URL:", f"{API_BASE}/checkout/create")
        st.sidebar.write("DEBUG request body keys:", list(body.get("inputs", {}).keys()))

    r = requests.post(f"{API_BASE}/checkout/create", json=body, headers=headers, timeout=30)

    if r.status_code != 200:
        st.error(f"Checkout API error: {r.status_code}")
        try:
            st.json(r.json())
        except Exception:
            st.code(r.text)
        st.stop()

    resp = r.json()
    checkout_url = resp.get("checkout_url")
    if not checkout_url:
        st.error("Checkout API did not return checkout_url.")
        st.json(resp)
        st.stop()

    # Redirect to Stripe Checkout
    st.markdown(
        f"<meta http-equiv='refresh' content='0; url={checkout_url}'>",
        unsafe_allow_html=True,
    )
    st.link_button("Continue to Stripe Checkout", checkout_url)


if st.button("Place Order & Pay"):
    start_checkout()


# -----------------------------
# Shipping display
# -----------------------------
area_sq_in = result.get("area_sq_in", _estimate_area_sq_in(paddle_dia, handle_length))
weight_lb = result.get(
    "estimated_total_weight_lb",
    _estimate_total_weight_lb(material, area_sq_in, thickness, int(quantity)),
)
pkg = result.get(
    "estimated_package_in",
    _estimate_package_in(paddle_dia, handle_length, float(thickness), int(quantity)),
)

st.caption("Shipping estimates")
s1, s2 = st.columns(2)
s1.metric("Estimated Total Weight", f"{weight_lb:.2f} lb")
s2.metric("Estimated Package Size", f"{pkg['length']} x {pkg['width']} x {pkg['height']} in")
