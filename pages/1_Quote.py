# pages/1_Quote.py
import os
import hashlib
import json
from typing import Dict, Optional

import requests
import streamlit as st
import streamlit.components.v1 as components

from auth import render_auth_sidebar, auth_headers, is_logged_in
from plate_preview import render_plate_svg


# -----------------------------
# Page setup (MUST be first Streamlit call)
# -----------------------------
st.set_page_config(page_title="Orifice Plate Instant Quote", layout="wide")

st.markdown(
    """
    <style>
    /* Remove extra top padding */
    .block-container {
        padding-top: 0.5rem !important;
        max-width: 1500px;
        padding-left: 2.5rem;
        padding-right: 2.5rem;
        margin-left: auto;
        margin-right: auto;
    }

    /* Reduce overall vertical spacing */
    section[data-testid="stMain"] > div {
        padding-top: 0.5rem;
    }

    @media (max-width: 768px) {
        .block-container {
            padding-left: 1rem !important;
            padding-right: 1rem !important;
        }
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# ---- EASY TUNING KNOBS ----
RIGHT_FORM_WIDTH = 0.72      # 0.55 - 0.85 (smaller = narrower input column)
IMAGE_TOP_SPACER_PX = 10     # move image down more/less
LEFT_TIGHTEN = True          # tighter left column spacing
PAY_BUTTON_HEIGHT_PX = 56    # taller button
PAY_BUTTON_FONT_PX = 18
PAY_BUTTON_WIDTH_RATIO = 0.56  # how wide button is (0.40-0.80) of the input column
# ---------------------------

st.markdown(
    f"""
    <style>
    /* Centered H1 */
    h1 {{
      font-family: Arial, sans-serif;
      font-weight: 800;
      letter-spacing: 0.2px;
      margin-bottom: 0.25rem;
      text-align: center;
    }}

    /* tighten vertical spacing between widgets */
    div[data-testid="stVerticalBlock"] > div {{
        gap: 0.45rem;
    }}

    /* Make Streamlit buttons taller */
    div[data-testid="stButton"] > button {{
        height: {PAY_BUTTON_HEIGHT_PX}px;
        padding: 0.55rem 1.25rem;
        font-size: {PAY_BUTTON_FONT_PX}px;
        border-radius: 12px;
        font-weight: 800;
    }}
    </style>
    """,
    unsafe_allow_html=True,
)

# -----------------------------
# Shared auth sidebar (login persists across pages)
# -----------------------------
render_auth_sidebar(show_debug=False)

# ✅ NEW: cart support (session state)
import uuid
from datetime import datetime

if "cart" not in st.session_state or not isinstance(st.session_state.cart, list):
    st.session_state.cart = []

st.markdown("<h1>Orifice Plate Instant Quote</h1>", unsafe_allow_html=True)
st.markdown(
    "<p style='text-align:center;color:#526174;margin-top:-0.25rem'>"
    "Enter the part dimensions shown in the drawing. Your verified price updates automatically."
    "</p>",
    unsafe_allow_html=True,
)


# -----------------------------
# Config
# -----------------------------
API_BASE = (os.environ.get("API_BASE") or "").strip().rstrip("/")
API_KEY = (os.environ.get("API_KEY") or "").strip()

LOCAL_IMAGE_PATH = os.environ.get("PRODUCT_IMAGE_PATH", "oplatetemp.png")
PRODUCT_IMAGE_URL = (os.environ.get("PRODUCT_IMAGE_URL") or "").strip()

if not API_BASE:
    st.error("The O-Plates pricing service is not configured.")
    st.stop()


def _qp_get(name: str) -> Optional[str]:
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
    st.switch_page("pages/4_Success.py")

if _qp_get("checkout") == "cancelled":
    st.session_state.pop("checkout_attempt", None)
    st.info("Checkout was canceled. Your configuration is still available below.")


# -----------------------------
# Helpers (shipping estimates)
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


def _render_product_image() -> None:
    if os.path.exists(LOCAL_IMAGE_PATH):
        st.image(LOCAL_IMAGE_PATH, use_container_width=True)
        return
    if PRODUCT_IMAGE_URL:
        st.image(PRODUCT_IMAGE_URL, use_container_width=True)
        return
    st.info("Add product image: include `oplatetemp.png` in the repo root or set PRODUCT_IMAGE_URL.")


# -----------------------------
# Checkout
# -----------------------------
def start_checkout(payload_inputs: dict, priced_configuration: dict) -> None:
    customer_context = st.session_state.auth.get("email") if is_logged_in() else "guest"
    fingerprint = hashlib.sha256(
        json.dumps(
            {
                "inputs": payload_inputs,
                "pricing_config_version": priced_configuration.get("pricing_config_version"),
                "customer_context": customer_context,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    checkout_attempt = st.session_state.get("checkout_attempt")
    if not isinstance(checkout_attempt, dict) or checkout_attempt.get("fingerprint") != fingerprint:
        checkout_attempt = {
            "fingerprint": fingerprint,
            "idempotency_key": str(uuid.uuid4()),
            "configuration_id": priced_configuration.get("configuration_id"),
        }
        st.session_state.checkout_attempt = checkout_attempt

    body = {
        "inputs": payload_inputs,
        "configuration_id": checkout_attempt.get("configuration_id"),
        "pricing_config_version": priced_configuration.get("pricing_config_version"),
        "idempotency_key": checkout_attempt["idempotency_key"],
    }

    headers: Dict[str, str] = {}

    # Logged-in customers: use Bearer token so API saves customer_id on the order
    if is_logged_in():
        headers.update(auth_headers())
    else:
        # Guest flow (existing behavior)
        if API_KEY:
            headers["x-api-key"] = API_KEY

    try:
        r = requests.post(
            f"{API_BASE}/checkout/create",
            json=body,
            headers=headers,
            timeout=30,
        )
    except requests.RequestException:
        st.error("Checkout is temporarily unavailable. Please try again.")
        st.stop()

    if r.status_code != 200:
        try:
            detail = r.json().get("detail")
        except Exception:
            detail = None
        if isinstance(detail, dict):
            message = detail.get("message")
        else:
            message = str(detail or "")
        st.error(message or "Checkout couldn’t be started. Please try again.")
        st.stop()

    resp = r.json()
    checkout_url = resp.get("checkout_url")
    if not checkout_url:
        st.error("Checkout API did not return checkout_url.")
        st.json(resp)
        st.stop()

    st.markdown(
        f"<meta http-equiv='refresh' content='0; url={checkout_url}'>",
        unsafe_allow_html=True,
    )
    st.link_button("Continue to Stripe Checkout", checkout_url)


@st.cache_data(ttl=60, show_spinner=False)
def load_active_config() -> dict:
    response = requests.get(f"{API_BASE}/config/active", timeout=15)
    response.raise_for_status()
    return response.json()


def request_authoritative_price(payload_inputs: dict) -> tuple[Optional[dict], Optional[str]]:
    headers = {"x-api-key": API_KEY} if API_KEY else {}
    try:
        response = requests.post(
            f"{API_BASE}/quote",
            json=payload_inputs,
            headers=headers,
            timeout=20,
        )
    except requests.RequestException:
        return None, "Live pricing is temporarily unavailable. Your entries are preserved; please try again."

    if response.status_code == 200:
        return response.json(), None

    try:
        detail = response.json().get("detail")
    except Exception:
        detail = None
    if isinstance(detail, dict):
        message = detail.get("message") or "This configuration could not be priced."
    elif isinstance(detail, list):
        message = "; ".join(str(item.get("msg") or item) for item in detail)
    else:
        message = str(detail or "Live pricing is temporarily unavailable.")
    return None, message


try:
    active_config = load_active_config()
except requests.RequestException:
    st.error("The configurator cannot load current product availability. Please try again shortly.")
    st.stop()

material_options = active_config.get("materials") or [
    name
    for name, enabled in active_config.get("material_enabled", {}).items()
    if enabled
]
lead_time_options = active_config.get("lead_times_days") or [
    int(days)
    for days, enabled in active_config.get("lead_time_enabled", {}).items()
    if enabled
]
max_paddle_dia = float(active_config["max_paddle_dia_in"])
max_bore_dia = float(active_config["max_bore_dia_in"])
max_handle_label_chars = int(active_config["max_handle_label_chars"])


# -----------------------------
# Two-column layout
# -----------------------------
left, right = st.columns([1.12, 1.38], gap="large")

# -----------------------------
# LEFT: image + summary (tight)
# -----------------------------
with left:
    st.markdown(f"<div style='height:{IMAGE_TOP_SPACER_PX}px'></div>", unsafe_allow_html=True)
    st.subheader("Configuration Drawing")
    st.caption("Entered dimensions are reflected below. Drawing is not to scale (NTS).")

# -----------------------------
# RIGHT: inputs (narrowed) + Pay button bottom-center
# -----------------------------
with right:
    _spacer, form_col = st.columns([1 - RIGHT_FORM_WIDTH, RIGHT_FORM_WIDTH], gap="medium")

    with form_col:
        st.caption("PRODUCT")
        r1c1, r1c2 = st.columns([1, 2])
        with r1c1:
            quantity = st.number_input("Quantity", min_value=1, value=1, step=1)
        with r1c2:
            material = st.selectbox("Material", options=material_options)

        thickness_options = sorted(
            active_config.get("thicknesses_by_material", {}).get(material, [])
            or [
                float(value)
                for value, enabled in active_config.get(
                    "thickness_enabled_by_material", {}
                ).get(material, {}).items()
                if enabled
            ]
        )
        thickness = st.selectbox(
            "Plate thickness (in.)",
            options=thickness_options,
            help="Finished nominal plate thickness.",
        )

        st.caption("DIMENSIONS")
        r2c1, r2c2 = st.columns(2)
        with r2c1:
            paddle_dia = st.number_input(
                "Plate outside diameter (in.)",
                min_value=0.01,
                max_value=max_paddle_dia,
                value=3.000,
                step=0.001,
                format="%.3f",
            )
        with r2c2:
            bore_dia = st.number_input(
                "Bore diameter (in.)",
                min_value=0.01,
                max_value=max_bore_dia,
                value=1.000,
                step=0.001,
                format="%.3f",
            )

        r3c1, r3c2 = st.columns(2)
        with r3c1:
            handle_width = st.number_input(
                "Handle width (in.)",
                min_value=0.0,
                value=1.500,
                step=0.001,
                format="%.3f",
                help="Width of the rectangular handle.",
            )
        with r3c2:
            handle_length = st.number_input(
                "Handle length from bore center (in.)",
                min_value=0.0,
                value=9.000,
                step=0.001,
                format="%.3f",
                help="Distance from the bore center to the end of the handle.",
            )

        st.caption("REQUIREMENTS")
        tol_options = sorted(active_config.get("tolerance_options_in") or [0.001, 0.002, 0.005])
        bore_tolerance = st.selectbox(
            "Bore tolerance (± in.)",
            options=tol_options,
            index=tol_options.index(0.005) if 0.005 in tol_options else 0,
            help="Permitted variation from the specified finished bore diameter.",
        )

        handle_label = st.text_input(
            "Handle marking (optional)",
            value="",
            placeholder="UPSTREAM x.xxx BORE x.xxx BETA",
            max_chars=max_handle_label_chars,
            help=f"Maximum {max_handle_label_chars} characters. Letters, numbers, spaces, and standard shop-marking punctuation only.",
        )

        chamfer = st.checkbox("Chamfer", value=False)
        chamfer_width = None
        if chamfer:
            chamfer_width = st.number_input(
                "Chamfer Width (in.)",
                min_value=0.001,
                value=None,
                step=0.001,
                format="%.3f",
                placeholder="Enter width",
                help="No width is assumed. Enter the required chamfer width.",
            )

        st.caption("DELIVERY")
        ships_options = sorted(lead_time_options)
        default_ship = int(active_config.get("default_lead_time_days") or ships_options[-1])
        ships_in_days = st.selectbox(
            "Lead time",
            options=ships_options,
            index=ships_options.index(default_ship) if default_ship in ships_options else 0,
            format_func=lambda days: f"{days} calendar days",
            help="Timing is estimated and subject to material availability and order-specific review.",
        )


# -----------------------------
# Validation
# -----------------------------
errors = []
if bore_dia >= paddle_dia:
    errors.append("Bore diameter must be smaller than the plate outside diameter.")
if handle_length <= (paddle_dia / 2):
    errors.append("Handle length from bore center must extend beyond the plate radius.")
if handle_width <= 0:
    errors.append("Handle width must be greater than zero.")

if errors:
    with right:
        st.divider()
        for e in errors:
            st.error(e)
    st.stop()

# -----------------------------
# Pricing (authoritative API)
# -----------------------------
payload_inputs = {
    "quantity": int(quantity),
    "material": str(material),
    "thickness": float(thickness),
    "handle_width": float(handle_width),
    "handle_length_from_bore": float(handle_length),
    "paddle_dia": float(paddle_dia),
    "bore_dia": float(bore_dia),
    "bore_tolerance": float(bore_tolerance),
    "chamfer": bool(chamfer),
    "chamfer_width": float(chamfer_width) if chamfer_width is not None else None,
    "handle_label": (handle_label or "").strip() or "No label",
    "ships_in_days": int(ships_in_days),
}

result, pricing_error = request_authoritative_price(payload_inputs)
if pricing_error:
    with right:
        st.error(pricing_error)
        st.caption("Checkout is disabled until the live price can be verified.")
    result = None

# Shipping estimates (computed once)
area_sq_in = result.get("area_sq_in") if result else None
weight_lb = result.get("estimated_total_weight_lb") if result else None
pkg = result.get("estimated_package_in") if result else None

# -----------------------------
# LEFT: Quote summary + shipping estimates (tight)
# -----------------------------
with left:
    components.html(
        render_plate_svg(
            paddle_dia=paddle_dia,
            bore_dia=bore_dia,
            handle_width=handle_width,
            handle_length_from_bore=handle_length,
            thickness=float(thickness),
            material=material,
            bore_tolerance=float(bore_tolerance),
            handle_label=(handle_label or "").strip() or "No label",
            chamfer=bool(chamfer),
            chamfer_width=float(chamfer_width) if chamfer_width is not None else None,
        ),
        height=430,
        scrolling=False,
    )
    with st.container(border=True):
        st.subheader("Quote Summary")
        if result:
            c1, c2 = st.columns(2)
            c1.metric("Unit price", f"${result['unit_price']:,.2f}")
            c2.metric("Total price", f"${result['total_price']:,.2f}")
            st.caption(
                f"{material} · {float(thickness):.3f} in. thick · "
                f"Ø {float(paddle_dia):.3f} OD / Ø {float(bore_dia):.3f} bore · "
                f"Qty {int(quantity)}"
            )
            st.success(f"Estimated to ship within {int(ships_in_days)} calendar days.")
            st.caption(
                f"Quote reference: {result.get('configuration_id', '')} · "
                "Verified using the active pricing and availability configuration."
            )
        else:
            st.warning("A verified price is not currently available.")

    if not LEFT_TIGHTEN:
        st.divider()

    if result and weight_lb is not None and pkg:
        st.caption("Shipping estimates")
        s1, s2 = st.columns(2)
        s1.metric("Estimated total weight", f"{weight_lb:.2f} lb")
        s2.metric("Estimated package", f"{pkg['length']} × {pkg['width']} × {pkg['height']} in.")


# -----------------------------
# Cart helper (NEW)
# -----------------------------
def _add_to_cart(payload_inputs: dict, result: dict) -> None:
    st.session_state.cart.append(
        {
            "line_id": str(uuid.uuid4()),
            "created_at": datetime.utcnow().isoformat() + "Z",
            "inputs": payload_inputs,
            # snapshot pricing at time added (optional but useful)
            "unit_price": float(result.get("unit_price") or 0),
            "total_price": float(result.get("total_price") or 0),
            "material": payload_inputs.get("material"),
            "thickness": payload_inputs.get("thickness"),
        }
    )


# -----------------------------
# RIGHT: Pay button (bottom-center, not full width)
# -----------------------------
with right:
    st.markdown("<div style='height:18px'></div>", unsafe_allow_html=True)

    _spacer, form_col = st.columns([1 - RIGHT_FORM_WIDTH, RIGHT_FORM_WIDTH], gap="large")
    with form_col:
        # Logged-in indicator (ties the order to account)
        if is_logged_in():
            st.success("You’re logged in — this order will be saved to your account.")
        else:
            st.info("Checkout as guest — log in from the sidebar to save orders to your account.")

        st.caption("Price is revalidated before checkout; shipping is selected there.")

        left_pad = max(0.0, (1.0 - PAY_BUTTON_WIDTH_RATIO) / 2.0)
        btn_cols = st.columns([left_pad, PAY_BUTTON_WIDTH_RATIO, left_pad])

        with btn_cols[1]:
            if st.button("Continue to secure checkout", disabled=result is None):
                start_checkout(payload_inputs, result)

            # Under your existing "Place Order & Pay" button block:
            st.markdown("<div style='height:10px'></div>", unsafe_allow_html=True)

            # Only for logged-in users (multi-item workflow)
            add_disabled = not is_logged_in() or result is None
            if st.button("Add another plate", disabled=add_disabled, use_container_width=True):
                _add_to_cart(payload_inputs, result)
                st.success(f"Added to Quote Cart. Items in cart: {len(st.session_state.cart)}")
                # Optional: jump them to cart immediately
                st.switch_page("pages/3_Quote_Cart.py")

            if add_disabled:
                st.caption("Log in to add multiple plates; a verified live price is required.")
