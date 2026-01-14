# ui_app.py
import os
from typing import Dict, Optional, Any

import requests
import streamlit as st

from pricing_engine import QuoteInputs, calculate_quote  # calculate_quote kept as fallback
import tuning_knobs as cfg


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
    </style>
    """,
    unsafe_allow_html=True,
)

# ---- EASY TUNING KNOBS (UI-only layout knobs) ----
RIGHT_FORM_WIDTH = 0.72      # 0.55 - 0.85 (smaller = narrower input column)
IMAGE_TOP_SPACER_PX = 10     # move image down more/less
LEFT_TIGHTEN = True          # tighter left column spacing
PAY_BUTTON_HEIGHT_PX = 56    # taller button
PAY_BUTTON_FONT_PX = 18
PAY_BUTTON_WIDTH_RATIO = 0.56  # how wide button is (0.40-0.80) of the input column
# -----------------------------------------------

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

st.markdown("<h1>Orifice Plate Instant Quote</h1>", unsafe_allow_html=True)


# -----------------------------
# Config
# -----------------------------
API_BASE = os.environ.get("API_BASE", "https://orifice-pricing-api.onrender.com").rstrip("/")
API_KEY = (os.environ.get("API_KEY") or "").strip()

LOCAL_IMAGE_PATH = os.environ.get("PRODUCT_IMAGE_PATH", "oplatetemp.png")
PRODUCT_IMAGE_URL = (os.environ.get("PRODUCT_IMAGE_URL") or "").strip()


# -----------------------------
# Live config + API quote (NO REDEPLOY REQUIRED)
# -----------------------------
@st.cache_data(ttl=5, show_spinner=False)
def fetch_active_config() -> dict:
    """
    Pull live availability toggles from API.
    Falls back to empty dict if unreachable.
    """
    headers: Dict[str, str] = {}
    if API_KEY:
        headers["x-api-key"] = API_KEY

    try:
        r = requests.get(f"{API_BASE}/config/active", headers=headers, timeout=10)
        if r.status_code == 200:
            j = r.json()
            if isinstance(j, dict):
                return j
    except Exception:
        pass

    return {}


def _to_bool_map(d: Any) -> Dict[str, bool]:
    if not isinstance(d, dict):
        return {}
    return {str(k): bool(v) for k, v in d.items()}


def _to_int_bool_map(d: Any) -> Dict[int, bool]:
    out: Dict[int, bool] = {}
    if not isinstance(d, dict):
        return out
    for k, v in d.items():
        try:
            out[int(k)] = bool(v)
        except Exception:
            continue
    return out


def _to_float_bool_map_by_material(d: Any) -> Dict[str, Dict[float, bool]]:
    out: Dict[str, Dict[float, bool]] = {}
    if not isinstance(d, dict):
        return out
    for mat, tmap in d.items():
        if not isinstance(tmap, dict):
            continue
        out[str(mat)] = {}
        for t, enabled in tmap.items():
            try:
                out[str(mat)][float(t)] = bool(enabled)
            except Exception:
                continue
    return out


def quote_via_api(payload: dict) -> dict:
    """
    Source-of-truth pricing via API so admin knob changes apply immediately.
    """
    headers: Dict[str, str] = {}
    if API_KEY:
        headers["x-api-key"] = API_KEY

    r = requests.post(f"{API_BASE}/quote", json=payload, headers=headers, timeout=20)
    if r.status_code != 200:
        raise RuntimeError(f"Quote API error {r.status_code}: {r.text}")
    j = r.json()
    if not isinstance(j, dict):
        raise RuntimeError("Quote API returned non-JSON-object response.")
    return j


ACTIVE_CFG = fetch_active_config()


# -----------------------------
# Helpers (existing)
# -----------------------------
def _qp_get(name: str) -> Optional[str]:
    qp = st.query_params
    if name not in qp:
        return None
    v = qp[name]
    if isinstance(v, list):
        return v[0] if v else None
    return v


def _fmt_usd(x) -> str:
    try:
        if x is None:
            return ""
        return f"${float(x):.2f}"
    except Exception:
        return str(x)


def _pretty_shipping_service(code: str | None) -> str:
    if not code:
        return "(finalizing...)"
    mapping = {
        "ups_ground": "UPS Ground",
        "ups_2day": "UPS 2nd Day Air",
        "ups_nextday": "UPS Next Day Air",
    }
    return mapping.get(code, code.replace("_", " ").title())


def _format_order_number(order: dict) -> str:
    disp = (order.get("order_number_display") or "").strip()
    if disp:
        return disp

    n = order.get("order_number")
    try:
        if n is not None:
            return f"OP-{int(n):04d}"
    except Exception:
        pass

    return "(finalizing...)"


def _format_address(addr: object) -> str:
    if not isinstance(addr, dict):
        return ""

    line1 = (addr.get("line1") or "").strip()
    line2 = (addr.get("line2") or "").strip()
    city = (addr.get("city") or "").strip()
    state = (addr.get("state") or "").strip()
    postal = (addr.get("postal_code") or "").strip()
    country = (addr.get("country") or "").strip()

    lines = []
    if line1:
        lines.append(line1)
    if line2:
        lines.append(line2)

    city_state = ", ".join([p for p in [city, state] if p]).strip()
    if city_state and postal:
        lines.append(f"{city_state} {postal}".strip())
    elif city_state:
        lines.append(city_state)
    elif postal:
        lines.append(postal)

    if country:
        lines.append(country)

    return "\n".join([ln for ln in lines if ln.strip()])


# -----------------------------
# Success page (session_id in query params)
# -----------------------------
session_id = _qp_get("session_id")
if session_id:
    st.title("Payment received ✅")
    st.write("Thanks — we received your payment. We’re preparing your order now.")

    refresh_status = st.button("🔄 Refresh order status")

    try:
        r = requests.get(f"{API_BASE}/orders/by-session/{session_id}", timeout=30)
        if r.status_code == 200:
            order = r.json()

            st.subheader("Order summary")
            st.write(f"Order #: **{_format_order_number(order)}**")
            st.write(f"Email: **{order.get('customer_email','')}**")

            total = order.get("amount_total_usd")
            ship = order.get("amount_shipping_usd")
            service = order.get("shipping_service")

            st.write(f"Total paid: **{_fmt_usd(total)}**")
            st.write(f"Shipping cost: **{_fmt_usd(ship)}**")
            st.write(f"Shipping option: **{_pretty_shipping_service(service)}**")

            ship_name = (order.get("shipping_name") or "").strip()
            ship_addr = order.get("shipping_address")
            addr_text = _format_address(ship_addr)

            if ship_name or addr_text:
                st.subheader("Ship to")
                if ship_name:
                    st.write(f"**{ship_name}**")
                if addr_text:
                    st.code(addr_text)
                else:
                    st.write("(Address not available yet)")

            st.write("We’ll email your confirmation and approval drawing next.")

            if _format_order_number(order) == "(finalizing...)" or not service or (not ship_name and not addr_text):
                st.info(
                    "If this page shows “finalizing…” or is missing address/shipping option, "
                    "Stripe’s webhook may still be saving details. Click **Refresh order status** in a moment."
                )
        else:
            st.info("Payment confirmed. Finalizing your order details… (refresh in a moment)")
    except Exception:
        st.info("Payment confirmed. Finalizing your order details… (refresh in a moment)")

    if refresh_status:
        st.rerun()

    st.stop()


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
    densities = getattr(cfg, "DENSITY_LB_PER_IN3", None)
    if not isinstance(densities, dict) or not densities:
        densities = {
            "304": 0.289,
            "316": 0.289,
            "Carbon Steel": 0.283,
            "Monel": 0.319,
            "Hastelloy": 0.321,
        }

    mult_map = getattr(cfg, "WEIGHT_MULTIPLIER_BY_MATERIAL", None)
    if not isinstance(mult_map, dict) or not mult_map:
        mult_map = {}

    density = float(densities.get(material, 0.289))
    mult = float(mult_map.get(material, 1.0))

    return round(area_sq_in * thickness * density * qty * mult, 2)


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
def start_checkout(payload_inputs: dict) -> None:
    body = {"inputs": payload_inputs}

    headers: Dict[str, str] = {}
    if API_KEY:
        headers["x-api-key"] = API_KEY

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

    st.markdown(
        f"<meta http-equiv='refresh' content='0; url={checkout_url}'>",
        unsafe_allow_html=True,
    )
    st.link_button("Continue to Stripe Checkout", checkout_url)


# -----------------------------
# Two-column layout
# -----------------------------
left, right = st.columns([1.0, 1.45], gap="large")

# -----------------------------
# LEFT: image + summary (tight)
# -----------------------------
with left:
    st.markdown(f"<div style='height:{IMAGE_TOP_SPACER_PX}px'></div>", unsafe_allow_html=True)
    _render_product_image()

    if not LEFT_TIGHTEN:
        st.divider()

    st.subheader("Quote Summary")

# -----------------------------
# RIGHT: inputs (narrowed)
# -----------------------------
with right:
    _spacer, form_col = st.columns([1 - RIGHT_FORM_WIDTH, RIGHT_FORM_WIDTH], gap="medium")

    with form_col:
        r1c1, r1c2 = st.columns([1, 2])
        with r1c1:
            quantity = st.number_input("Qty", min_value=1, value=1, step=1)

        # -----------------------------
        # Live availability maps (prefer API, fallback to local cfg)
        # -----------------------------
        material_enabled_map = _to_bool_map(ACTIVE_CFG.get("material_enabled")) or getattr(cfg, "MATERIAL_ENABLED", {})
        if not material_enabled_map:
            # fallback: everything present in cfg.PRICE_PER_SQ_IN enabled
            material_enabled_map = {m: True for m in getattr(cfg, "PRICE_PER_SQ_IN", {}).keys()}

        thickness_enabled_by_material = _to_float_bool_map_by_material(
            ACTIVE_CFG.get("thickness_enabled_by_material")
        ) or getattr(cfg, "THICKNESS_ENABLED_BY_MATERIAL", {})

        lead_enabled_map = _to_int_bool_map(ACTIVE_CFG.get("lead_time_enabled")) or getattr(cfg, "LEAD_TIME_ENABLED", {})
        if not lead_enabled_map:
            lead_enabled_map = {int(d): True for d in getattr(cfg, "LEAD_TIME_MULTIPLIER", {}).keys()}

        # -----------------------------
        # Material dropdown (show unavailable)
        # -----------------------------
        materials_all = sorted(material_enabled_map.keys())

        def _material_label(m: str) -> str:
            return m if material_enabled_map.get(m, False) else f"{m} (unavailable)"

        material_labels = [_material_label(m) for m in materials_all]
        label_to_material = dict(zip(material_labels, materials_all))

        default_material = next((m for m in materials_all if material_enabled_map.get(m, False)), materials_all[0])
        default_index = materials_all.index(default_material)

        with r1c2:
            selected_material_label = st.selectbox("Material Type", options=material_labels, index=default_index)
            material = label_to_material[selected_material_label]

        if not material_enabled_map.get(material, False):
            st.warning(f"⚠️ **{material}** is currently unavailable. Please choose a different material.")
            st.stop()

        # -----------------------------
        # Thickness dropdown (show unavailable)
        # -----------------------------
        # Build a master thickness list from API config if present, else fallback to cfg.PRICE_PER_SQ_IN union
        thickness_master = []
        if thickness_enabled_by_material:
            all_t = set()
            for m, tmap in thickness_enabled_by_material.items():
                for t, _en in (tmap or {}).items():
                    try:
                        all_t.add(float(t))
                    except Exception:
                        continue
            thickness_master = sorted(all_t)

        if not thickness_master:
            # fallback to local cfg union
            all_t = set()
            ppsi = getattr(cfg, "PRICE_PER_SQ_IN", {})
            if isinstance(ppsi, dict):
                for _m, tmap in ppsi.items():
                    if isinstance(tmap, dict):
                        for t in tmap.keys():
                            try:
                                all_t.add(float(t))
                            except Exception:
                                pass
            thickness_master = sorted(all_t)

        # available thickness for this material = enabled True in API map; fallback to cfg.PRICE_PER_SQ_IN
        enabled_map_for_mat = thickness_enabled_by_material.get(material) if isinstance(thickness_enabled_by_material, dict) else None
        if isinstance(enabled_map_for_mat, dict) and enabled_map_for_mat:
            available_thicknesses = sorted([t for t, en in enabled_map_for_mat.items() if en])
        else:
            available_thicknesses = sorted(getattr(cfg, "PRICE_PER_SQ_IN", {}).get(material, {}).keys())

        def _th_label(t: float) -> str:
            base = f'{float(t):.3f}"'
            return base if t in available_thicknesses else f"{base} (unavailable)"

        th_labels = [_th_label(t) for t in thickness_master]
        th_label_to_val = dict(zip(th_labels, thickness_master))

        default_th = available_thicknesses[0] if available_thicknesses else thickness_master[0]
        default_th_idx = thickness_master.index(default_th) if default_th in thickness_master else 0

        selected_th_label = st.selectbox("Plate Thickness (in)", options=th_labels, index=default_th_idx)
        thickness = float(th_label_to_val[selected_th_label])

        if thickness not in available_thicknesses:
            st.warning(f"⚠️ **{material}** in **{thickness:.3f}\"** is currently unavailable.")
            st.stop()

        r2c1, r2c2 = st.columns(2)
        with r2c1:
            handle_width = st.number_input(
                "Handle Width (in)",
                min_value=0.0,
                value=1.500,
                step=0.001,
                format="%.3f",
            )
        with r2c2:
            handle_length = st.number_input(
                "Handle Length from Bore (in)",
                min_value=0.0,
                value=9.000,
                step=0.001,
                format="%.3f",
            )

        r3c1, r3c2 = st.columns(2)
        with r3c1:
            paddle_dia = st.number_input(
                "Paddle Diameter (in)",
                min_value=0.01,
                max_value=48.0,
                value=3.000,
                step=0.001,
                format="%.3f",
            )
        with r3c2:
            bore_dia = st.number_input(
                "Bore Diameter (in)",
                min_value=0.01,
                value=1.000,
                step=0.001,
                format="%.3f",
            )

        tol_options = sorted(cfg.INSPECTION_MINS_BY_TOL.keys())
        bore_tolerance = st.selectbox(
            "Bore Tolerance (± in)",
            options=tol_options,
            index=tol_options.index(0.005) if 0.005 in tol_options else 0,
        )

        handle_label = st.text_input(
            "Handle Label (optional)",
            value="",
            placeholder="UPSTREAM x.xxx BORE x.xxx BETA",
        )

        chamfer = st.checkbox("Chamfer", value=True)

        chamfer_width: Optional[float] = None
        if chamfer:
            chamfer_width = st.number_input(
                "Chamfer Width (in)",
                min_value=0.0,
                value=0.062,
                step=0.001,
                format="%.3f",
            )

        # -----------------------------
        # Lead time dropdown (show unavailable)
        # -----------------------------
        lead_days_all = sorted(lead_enabled_map.keys())

        def _ld_label(d: int) -> str:
            base = f"{int(d)} days"
            return base if lead_enabled_map.get(d, False) else f"{base} (unavailable)"

        lead_labels = [_ld_label(d) for d in lead_days_all]
        lead_label_to_day = dict(zip(lead_labels, lead_days_all))

        default_lt = ACTIVE_CFG.get("default_lead_time_days")
        try:
            default_lt = int(default_lt)
        except Exception:
            default_lt = None

        if default_lt is None or default_lt not in lead_days_all or not lead_enabled_map.get(default_lt, False):
            default_lt = next((d for d in lead_days_all if lead_enabled_map.get(d, False)), lead_days_all[0])
        default_lt_idx = lead_days_all.index(default_lt)

        selected_lt_label = st.selectbox("Ships in (days)", options=lead_labels, index=default_lt_idx)
        ships_in_days = int(lead_label_to_day[selected_lt_label])

        if not lead_enabled_map.get(ships_in_days, False):
            st.warning(f"⚠️ **{ships_in_days} days** is currently unavailable.")
            st.stop()


# -----------------------------
# Validation
# -----------------------------
errors = []
if bore_dia >= paddle_dia:
    errors.append("Bore Diameter must be smaller than Paddle Diameter.")
if handle_length <= (paddle_dia / 2):
    errors.append("Handle Length (From Bore) must be longer than the Paddle Radius.")

if errors:
    with right:
        st.divider()
        for e in errors:
            st.error(e)
    st.stop()

# -----------------------------
# Pricing (API is source of truth)
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
    chamfer_width=float(chamfer_width) if chamfer and chamfer_width is not None else None,
    handle_label=(handle_label or "").strip() or "No label",
    ships_in_days=int(ships_in_days),
)

# Build payload for API quote
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
    "chamfer_width": float(chamfer_width) if chamfer and chamfer_width is not None else None,
    "handle_label": (handle_label or "").strip() or "No label",
    "ships_in_days": int(ships_in_days),
}

try:
    result = quote_via_api(payload_inputs)
except Exception as e:
    st.error("Quote API error — pricing is currently unavailable.")
    st.code(str(e))
    st.stop()


# Shipping estimates (computed once)
area_sq_in = result.get("area_sq_in", _estimate_area_sq_in(paddle_dia, handle_length))
weight_lb = result.get(
    "estimated_total_weight_lb",
    _estimate_total_weight_lb(material, area_sq_in, float(thickness), int(quantity)),
)
pkg = result.get(
    "estimated_package_in",
    _estimate_package_in(paddle_dia, handle_length, float(thickness), int(quantity)),
)

# -----------------------------
# LEFT: Quote summary + shipping estimates
# -----------------------------
with left:
    c1, c2 = st.columns(2)
    c1.metric("Unit Price", f"${result.get('unit_price', 0):,.2f}")
    c2.metric("Total Price", f"${result.get('total_price', 0):,.2f}")

    if not LEFT_TIGHTEN:
        st.divider()

    st.caption("Shipping estimates")
    s1, s2 = st.columns(2)
    s1.metric("Estimated Total Weight", f"{weight_lb:.2f} lb")
    s2.metric("Estimated Package Size", f"{pkg['length']} x {pkg['width']} x {pkg['height']} in")

# -----------------------------
# RIGHT: Pay button
# -----------------------------
with right:
    st.markdown("<div style='height:18px'></div>", unsafe_allow_html=True)

    _spacer, form_col = st.columns([1 - RIGHT_FORM_WIDTH, RIGHT_FORM_WIDTH], gap="large")
    with form_col:
        st.caption("Shipping option is selected during checkout.")

        left_pad = max(0.0, (1.0 - PAY_BUTTON_WIDTH_RATIO) / 2.0)
        btn_cols = st.columns([left_pad, PAY_BUTTON_WIDTH_RATIO, left_pad])

        with btn_cols[1]:
            if st.button("Place Order & Pay"):
                start_checkout(payload_inputs)

