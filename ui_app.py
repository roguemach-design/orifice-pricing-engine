# ui_app.py
import os
import streamlit as st
import requests

from pricing_engine import QuoteInputs, calculate_quote
import pricing_config as cfg

API_BASE = "https://orifice-pricing-api.onrender.com"


# -----------------------------
# Helpers (safe to keep)
# -----------------------------
def _estimate_area_sq_in(paddle_dia: float, handle_length_from_bore: float) -> float:
    return paddle_dia * (handle_length_from_bore + (paddle_dia / 2.0))


def _estimate_package_in(
    paddle_dia: float, handle_length_from_bore: float, thickness: float, qty: int
) -> dict:
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


def _quoteinputs_accepts(field_name: str) -> bool:
    if hasattr(QuoteInputs, "__dataclass_fields__"):
        return field_name in QuoteInputs.__dataclass_fields__
    if hasattr(QuoteInputs, "model_fields"):
        return field_name in QuoteInputs.model_fields
    if hasattr(QuoteInputs, "__fields__"):
        return field_name in QuoteInputs.__fields__
    return False


# -----------------------------
# Page setup
# -----------------------------
st.set_page_config(page_title="Orifice Plate Instant Quote", layout="centered")
st.title("Orifice Plate Instant Quote")


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
paddle_dia = st.number_input("Paddle Diameter (in)", min_value=0.01, value=3.0, step=0.01)
bore_dia = st.number_input("Bore Diameter (in)", min_value=0.01, value=1.0, step=0.01)

tol_options = sorted(cfg.INSPECTION_MINS_BY_TOL.keys())
bore_tolerance = st.selectbox(
    "Bore Tolerance (± in)",
    options=tol_options,
    index=tol_options.index(0.005) if 0.005 in tol_options else 0,
)

chamfer = st.checkbox("Chamfer", value=True)

handle_label = st.text_input(
    "Handle label (optional)",
    value="",
    help="If left blank, we’ll store 'No label'.",
).strip()

chamfer_width = None
if chamfer:
    chamfer_width = st.number_input(
        "Chamfer width (inches)",
        min_value=0.0,
        value=0.03,
        step=0.005,
        format="%.3f",
    )

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
    errors.append("Handle Length must exceed paddle radius.")

if errors:
    for e in errors:
        st.error(e)
    st.stop()


# -----------------------------
# Pricing
# -----------------------------
inputs_kwargs = dict(
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

if _quoteinputs_accepts("handle_label"):
    inputs_kwargs["handle_label"] = handle_label or "No label"
if _quoteinputs_accepts("chamfer_width"):
    inputs_kwargs["chamfer_width"] = chamfer_width

inputs = QuoteInputs(**inputs_kwargs)
result = calculate_quote(inputs)

c1, c2 = st.columns(2)
c1.metric("Unit Price", f"${result['unit_price']:,.2f}")
c2.metric("Total Price", f"${result['total_price']:,.2f}")


# -----------------------------
# Checkout
# -----------------------------
def start_checkout():
    payload = {
        "inputs": {
            "quantity": int(quantity),
            "material": str(material),
            "thickness": float(thickness),
            "handle_width": float(handle_width),
            "handle_length_from_bore": float(handle_length),
            "paddle_dia": float(paddle_dia),
            "bore_dia": float(bore_dia),
            "bore_tolerance": float(bore_tolerance),
            "ships_in_days": int(ships_in_days),
            "handle_label": handle_label or "No label",
            "chamfer": bool(chamfer),
            "chamfer_width": chamfer_width,
        }
    }

    API_KEY = os.environ.get("API_KEY", "")
    headers = {}
    if API_KEY:
        headers["x-api-key"] = API_KEY

    r = requests.post(
        f"{API_BASE}/checkout",
        json=payload,
        headers=headers,
        timeout=30,
    )

    if r.status_code != 200:
        st.error(f"Checkout API error: {r.status_code}")
        st.code(r.text)
        st.stop()

    checkout_url = r.json()["checkout_url"]
    st.markdown(
        f"<meta http-equiv='refresh' content='0; url={checkout_url}'>",
        unsafe_allow_html=True,
    )


if st.button("Place Order & Pay"):
    start_checkout()


# -----------------------------
# Shipping estimates
# -----------------------------
area_sq_in = result.get("area_sq_in", _estimate_area_sq_in(paddle_dia, handle_length))
weight_lb = result.get(
    "estimated_total_weight_lb",
    _estimate_total_weight_lb(material, area_sq_in, float(thickness), int(quantity)),
)
pkg = result.get(
    "estimated_package_in",
    _estimate_package_in(paddle_dia, handle_length, float(thickness), int(quantity)),
)

st.caption("Shipping estimates")
s1, s2 = st.columns(2)
s1.metric("Estimated Total Weight", f"{weight_lb:.2f} lb")
s2.metric("Estimated Package Size", f"{pkg['length']} × {pkg['width']} × {pkg['height']} in")
