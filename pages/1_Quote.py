from journey.ui import emit as journey_event, headers as journey_headers

from customer_safety import service_message
# pages/1_Quote.py
import os
import copy
import hashlib
import json
import time
from typing import Any, Dict, Optional

import requests
import streamlit as st
import streamlit.components.v1 as components

from auth import (
    auth_headers,
    current_user_id_hint,
    is_logged_in,
    render_auth_sidebar,
)
from drawing_intake.checkout_context import attest_context, selected_part_context
from drawing_intake.checkout_recovery import (
    fetch_checkout_recovery,
    recovered_quote_session,
)
from drawing_intake.assisted_quote import (
    FIELD_LABELS,
    AssistedQuoteSession,
    FieldAttentionKind,
    availability_from_active_config,
    confirm_configuration,
    canonical_required_fields,
    reject_drawing_proposal,
    review_assisted_quote,
)
from drawing_intake.configurator_integration import (
    DrawingProcessingBusyError,
    DrawingProcessingError,
    DrawingProcessingTimeoutError,
    DrawingUploadValidationError,
    FormValueOrigin,
    feature_flag_enabled,
    inspect_validated_upload,
    integrate_selected_session,
    recognize_selected_candidate,
    synchronize_session_from_form,
    upload_limits_from_environment,
    validate_drawing_upload,
)
from drawing_intake.pricing_gate import confirmed_drawing_quote_inputs
from drawing_intake.cart_gate import verified_assisted_cart_inputs
from drawing_intake.owner_access import verified_owner_access
from drawing_intake.owner_acceptance import (
    AcceptanceEventKind,
    OwnerAcceptanceRun,
    feedback_json,
    record_event,
    record_field_change,
    start_owner_acceptance_run,
    summarize_owner_acceptance,
    update_run,
)
from plate_preview import render_plate_svg
from customer_controls import choice_buttons, material_cards
from bore_edge_control import bore_edge_choice

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
IMAGE_TOP_SPACER_PX = 0  # move image down more/less
LEFT_TIGHTEN = True  # tighter left column spacing
PAY_BUTTON_HEIGHT_PX = 56  # taller button
PAY_BUTTON_FONT_PX = 18
PAY_BUTTON_WIDTH_RATIO = 0.56  # how wide button is (0.40-0.80) of the input column
# ---------------------------

st.markdown(
    f"""
    <style>
    /* Dominant configurator heading */
    h1 {{
      font-family: Arial, sans-serif;
      font-weight: 800;
      letter-spacing: 0.2px;
      margin-bottom: 0.25rem;
      text-align: left;
      font-size: 2rem;
    }}

    /* tighten vertical spacing between widgets */
    div[data-testid="stVerticalBlock"] > div {{
        gap: 0.45rem;
    }}

    /* Compact secondary upload path and aligned configurator start. */
    .st-key-drawing_upload [data-testid="stVerticalBlock"] {{gap:0.2rem}}
    .st-key-drawing_upload [data-testid="stButton"] button {{
        height:auto;min-height:36px;padding:.35rem .75rem;font-size:.875rem;
    }}
    .st-key-configurator_start [data-testid="stVerticalBlock"] {{gap:.55rem}}
    .st-key-configurator_start h3 {{margin-top:0;padding-top:0}}

    /* Bound the feedback column to this configurator's scrolling input row. */
    @media (min-width: 901px) {{
      .st-key-configurator_start > [data-testid="stLayoutWrapper"] > [data-testid="stHorizontalBlock"] {{align-items:flex-start}}
      .st-key-configurator_start > [data-testid="stLayoutWrapper"] > [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:first-child {{
        position:sticky;top:4rem;align-self:flex-start;min-width:0;
        overflow:visible;padding-right:.25rem;
      }}
    }}
    @media (max-width: 900px) {{
      .st-key-configurator_start > [data-testid="stLayoutWrapper"] > [data-testid="stHorizontalBlock"] {{flex-direction:column}}
      .st-key-configurator_start > [data-testid="stLayoutWrapper"] > [data-testid="stHorizontalBlock"] > [data-testid="stColumn"] {{
        position:static;top:auto;width:100%!important;flex:1 1 100%;min-width:0;
        max-height:none;overflow:visible;padding-right:0;
      }}
    }}

    /* Hide the source feedback only after the trusted landing host enables its sticky copy. */
    html.oplates-parent-preview .st-key-configurator_start > [data-testid="stLayoutWrapper"] > [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:first-child {{visibility:hidden;pointer-events:none}}

    /* Streamlit captions explicitly set visibility; suppress the source copy only on the landing host. */
    html.oplates-parent-preview .st-key-configurator_start > [data-testid="stLayoutWrapper"] > [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:first-child [data-testid="stCaptionContainer"],
    html.oplates-parent-preview .st-key-configurator_start > [data-testid="stLayoutWrapper"] > [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:first-child [data-testid="stCaptionContainer"] * {{visibility:hidden!important}}

    .st-key-preview_fulfillment [data-testid="stMetricValue"] {{font-size:1.5rem;line-height:1.25}}
    .st-key-preview_fulfillment [data-testid="stMetricValue"] > div {{white-space:normal;overflow-wrap:anywhere}}
    html.oplates-parent-preview .st-key-preview_fulfillment,
    html.oplates-parent-preview .st-key-preview_fulfillment * {{visibility:hidden!important}}

    /* The native dialog is portaled to body, above the app root. */
    html.oplates-viewport-modal body,
    html.oplates-viewport-modal #root {{background:transparent!important}}
    html.oplates-viewport-modal #root,
    html.oplates-viewport-modal #root * {{visibility:hidden!important}}
    html.oplates-viewport-modal [data-testid="stDialog"] {{inset:0;z-index:1000061;max-height:100dvh;overflow:auto}}

    .st-key-configurator_starter {{border:1px solid #2b3c50;border-radius:16px;
      padding:1.1rem 1.25rem;background:linear-gradient(115deg,#111d2a,#0e1620)}}
    .st-key-configurator_starter [data-testid="stVerticalBlock"] {{gap:.4rem}}
    .starter-upload-title {{display:flex;align-items:center;gap:.65rem;font-size:1rem}}
    .starter-upload-title span {{font-size:1.6rem;color:#a7c5e8}}
    .st-key-configurator_starter [data-testid="stButton"] button {{height:auto;min-height:38px;padding:.4rem .75rem;font-size:.875rem}}
    .st-key-configurator_starter [data-testid="stAlert"] {{padding:.85rem;border-radius:10px}}
    .st-key-starter_file_picker [data-testid="stFileUploaderDropzoneInstructions"] {{display:none}}
    .st-key-starter_file_picker [data-testid="stFileUploaderDropzone"] {{padding:0;border:0;background:transparent}}
    .st-key-starter_file_picker [data-testid="stFileUploaderDropzone"] button {{background:#1761b9;color:#fff;border:1px solid #4b99ef;min-height:42px}}
    .st-key-starter_file_picker [data-testid="stFileUploaderDropzone"] button p {{font-size:0}}
    .st-key-starter_file_picker [data-testid="stFileUploaderDropzone"] button p::after {{content:"Upload drawing";font-size:.875rem}}
    .st-key-configurator_starter [data-testid="stHorizontalBlock"] > [data-testid="stColumn"] {{min-width:0}}
    @media(max-width:900px) {{
      .st-key-configurator_starter > [data-testid="stLayoutWrapper"] > [data-testid="stHorizontalBlock"] {{flex-direction:column}}
      .st-key-configurator_starter > [data-testid="stLayoutWrapper"] > [data-testid="stHorizontalBlock"] > [data-testid="stColumn"] {{width:100%!important;flex:1 1 100%}}
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
render_auth_sidebar(show_debug=False, placement="deferred")

# ✅ NEW: cart support (session state)
import uuid
from datetime import datetime, timezone

if "cart" not in st.session_state or not isinstance(st.session_state.cart, list):
    st.session_state.cart = []

if not st.session_state.get("integrated_landing"):
    st.caption("BUILD FROM YOUR KNOWN DIMENSIONS")
    st.title("Configure your plate")
    st.markdown(
        "<p style='margin-top:0;margin-bottom:0.5rem'>"
        "Upload a drawing or enter dimensions below. Your verified price updates automatically."
        "</p>",
        unsafe_allow_html=True,
    )


# -----------------------------
# Config
# -----------------------------
API_BASE = (os.environ.get("API_BASE") or "").strip().rstrip("/")
if API_BASE and "://" not in API_BASE:
    API_BASE = f"http://{API_BASE}"
API_KEY = (os.environ.get("API_KEY") or "").strip()

LOCAL_IMAGE_PATH = os.environ.get("PRODUCT_IMAGE_PATH", "oplatetemp.png")
PRODUCT_IMAGE_URL = (os.environ.get("PRODUCT_IMAGE_URL") or "").strip()
DRAWING_ASSISTED_ENABLED = feature_flag_enabled(
    os.environ.get("OPLATES_DRAWING_ASSISTED_ENABLED")
)
OWNER_ACCEPTANCE_MODE = feature_flag_enabled(
    os.environ.get("OPLATES_OWNER_ACCEPTANCE_MODE")
)
OWNER_TEST_CHECKOUT_ENABLED = feature_flag_enabled(
    os.environ.get("OPLATES_OWNER_TEST_CHECKOUT_ENABLED")
)

_DRAWING_UPLOAD_KEY = "phase1g_processed_upload"
_DRAWING_PENDING_KEY = "phase1g_pending_session"
_DRAWING_SESSION_KEY = "phase1g_assisted_session"
_DRAWING_CONFLICTS_KEY = "phase1g_merge_conflicts"
_DRAWING_CONFIRM_KEY = "phase1g_customer_confirmation"
_DRAWING_RESET_UPLOAD_KEY = "phase1g_reset_upload_widget"
_FORM_ORIGINS_KEY = "phase1g_form_origins"
_FORM_SNAPSHOT_KEY = "phase1g_form_snapshot"
_OWNER_ACCEPTANCE_RUN_KEY = "phase1h_owner_acceptance_run"
_OWNER_ACCEPTANCE_NOTES_KEY = "phase1h_owner_acceptance_notes"
_FORM_KEYS = {
    name: f"quote_field_{name}"
    for name in (
        "quantity",
        "material",
        "thickness",
        "handle_width",
        "handle_length_from_bore",
        "handle_hole_enabled",
        "handle_hole_diameter",
        "handle_hole_center_from_handle_end",
        "paddle_dia",
        "bore_dia",
        "bore_tolerance",
        "chamfer",
        "ships_in_days",
        "handle_label",
        "chamfer_width",
    )
}

if not API_BASE:
    st.error("Pricing is temporarily unavailable. Please try again shortly.")
    st.stop()


def _internal_drawing_access_allowed() -> bool:
    """Gate owner testing with the existing verified JWT and allowlist.

    This limited test gate does not define the eventual public guest-upload UX.
    """

    return verified_owner_access(
        API_BASE,
        enabled=DRAWING_ASSISTED_ENABLED and is_logged_in(),
        user_id_hint=current_user_id_hint() if is_logged_in() else None,
        headers=auth_headers() if is_logged_in() else {},
    )


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
    st.info(
        "Checkout was canceled. No payment was completed. Sign in to recover your saved configuration, then review and confirm it again."
    )


# -----------------------------
# Helpers (shipping estimates)
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


def _estimate_total_weight_lb(
    material: str, area_sq_in: float, thickness: float, qty: int
) -> float:
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
    st.info(
        "Add product image: include `oplatetemp.png` in the repo root or set PRODUCT_IMAGE_URL."
    )


# -----------------------------
# Checkout
# -----------------------------
def start_checkout(payload_inputs: dict, priced_configuration: dict) -> None:
    journey_event("checkout", "attempted")
    customer_context = st.session_state.auth.get("email") if is_logged_in() else "guest"
    fingerprint = hashlib.sha256(
        json.dumps(
            {
                "inputs": payload_inputs,
                "pricing_config_version": priced_configuration.get(
                    "pricing_config_version"
                ),
                "customer_context": customer_context,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    checkout_attempt = st.session_state.get("checkout_attempt")
    if (
        not isinstance(checkout_attempt, dict)
        or checkout_attempt.get("fingerprint") != fingerprint
    ):
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

    assisted_session = st.session_state.get("phase1g_assisted_session")
    if assisted_session is not None:
        body["recovery_context"] = attest_context(
            selected_part_context(assisted_session),
            payload_inputs,
            current_user_id_hint(),
            API_KEY,
        )
    headers: Dict[str, str] = journey_headers()

    # Logged-in customers: use Bearer token so API saves customer_id on the order
    if is_logged_in():
        headers.update(auth_headers())
        if owner_test_checkout_allowed and os.environ.get("APP_ENV") == "production":
            headers["x-oplates-checkout-mode"] = "owner_test"
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
        journey_event("checkout", "error", "api_failure")
        st.error("Checkout is temporarily unavailable. Please try again.")
        st.stop()

    if r.status_code != 200:
        journey_event("checkout", "blocked" if r.status_code in (401,403,503) else "error",
                      "system_restriction" if r.status_code in (401,403) else "api_failure")
        st.error(service_message(r.status_code))
        st.stop()

    resp = r.json()
    checkout_url = resp.get("checkout_url")
    if not checkout_url:
        st.error("Checkout couldn’t be started. Please try again.")
        st.stop()

    from customer_navigation import render_integrated_checkout
    if render_integrated_checkout(checkout_url):
        return

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


def request_authoritative_price(
    payload_inputs: dict,
) -> tuple[Optional[dict], Optional[str]]:
    headers = {**({"x-api-key": API_KEY} if API_KEY else {}), **journey_headers()}
    try:
        response = requests.post(
            f"{API_BASE}/quote",
            json=payload_inputs,
            headers=headers,
            timeout=20,
        )
    except requests.RequestException:
        journey_event("quote", "error", "api_failure")
        return (
            None,
            "Live pricing is temporarily unavailable. Your entries are preserved; please try again.",
        )

    if response.status_code == 200:
        return response.json(), None

    journey_event("quote", "error", "unsupported" if response.status_code == 400 else
                  "invalid_input" if response.status_code == 422 else "api_failure")
    return None, service_message(response.status_code, pricing=True)


try:
    active_config = load_active_config()
except requests.RequestException:
    journey_event("configurator", "error", "api_failure")
    st.error(
        "The configurator cannot load current product availability. Please try again shortly."
    )
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
form_availability = availability_from_active_config(active_config)


def _thickness_options(material_name: str | None) -> list[float]:
    if not material_name:
        return []
    return sorted(
        active_config.get("thicknesses_by_material", {}).get(material_name, [])
        or [
            float(value)
            for value, enabled in active_config.get("thickness_enabled_by_material", {})
            .get(material_name, {})
            .items()
            if enabled
        ]
    )


tol_options = sorted(active_config.get("tolerance_options_in") or [])
ships_options = sorted(lead_time_options)
default_ship = int(active_config.get("default_lead_time_days") or ships_options[-1])
default_material = material_options[0]
default_thickness_options = _thickness_options(default_material)
default_form_values = {
    "quantity": 1,
    "material": default_material,
    "thickness": default_thickness_options[0],
    "handle_hole_enabled": False,
    "handle_hole_diameter": None,
    "handle_hole_center_from_handle_end": None,
    "handle_width": 1.5,
    "handle_length_from_bore": 9.0,
    "paddle_dia": 3.0,
    "bore_dia": 1.0,
    "bore_tolerance": 0.005 if 0.005 in tol_options else tol_options[0],
    "chamfer": False,
    "ships_in_days": (
        default_ship if default_ship in ships_options else ships_options[0]
    ),
    "handle_label": "",
    "chamfer_width": None,
}


def _form_values_from_state() -> dict[str, Any]:
    return {
        field: st.session_state.get(widget_key)
        for field, widget_key in _FORM_KEYS.items()
    }


def _initialize_form_state() -> None:
    if _FORM_ORIGINS_KEY not in st.session_state:
        for field, default in default_form_values.items():
            key = _FORM_KEYS[field]
            if default is not None:
                st.session_state[key] = default
        st.session_state[_FORM_ORIGINS_KEY] = {
            field: FormValueOrigin.DEFAULT.value for field in default_form_values
        }
    if _FORM_SNAPSHOT_KEY not in st.session_state:
        st.session_state[_FORM_SNAPSHOT_KEY] = _form_values_from_state()


def _install_form_integration(result) -> None:
    for field, value in result.values.items():
        key = _FORM_KEYS[field]
        if value is None and field == "handle_label":
            st.session_state.pop(key, None)
        else:
            # Explicit None clears the previously rendered manual default. Merely
            # removing the key lets Streamlit restore its old widget value.
            st.session_state[key] = value
    for field in ("handle_hole_diameter", "handle_hole_center_from_handle_end"):
        value = result.values.get(field)
        st.session_state[_FORM_KEYS[field] + "_text"] = "" if value is None else str(value)
    st.session_state[_FORM_ORIGINS_KEY] = {
        field: origin.value if isinstance(origin, FormValueOrigin) else str(origin)
        for field, origin in result.origins.items()
    }
    st.session_state[_FORM_SNAPSHOT_KEY] = dict(result.values)
    st.session_state[_DRAWING_SESSION_KEY] = result.session
    st.session_state[_DRAWING_CONFLICTS_KEY] = [
        conflict.model_dump() for conflict in result.conflicts
    ]
    st.session_state[_DRAWING_CONFIRM_KEY] = False


def _reset_to_manual_defaults() -> None:
    for key in (
        _DRAWING_UPLOAD_KEY,
        _DRAWING_PENDING_KEY,
        _DRAWING_SESSION_KEY,
        _DRAWING_CONFLICTS_KEY,
        _OWNER_ACCEPTANCE_RUN_KEY,
        _OWNER_ACCEPTANCE_NOTES_KEY,
    ):
        st.session_state.pop(key, None)
    for field, value in default_form_values.items():
        key = _FORM_KEYS[field]
        if field in ("handle_hole_diameter", "handle_hole_center_from_handle_end"):
            st.session_state[key + "_text"] = ""
        if value is None:
            st.session_state.pop(key, None)
        else:
            st.session_state[key] = value
    st.session_state[_FORM_ORIGINS_KEY] = {
        field: FormValueOrigin.DEFAULT.value for field in default_form_values
    }
    st.session_state[_FORM_SNAPSHOT_KEY] = dict(default_form_values)
    st.session_state[_DRAWING_CONFIRM_KEY] = False
    st.session_state[_DRAWING_RESET_UPLOAD_KEY] = True


def _required_field_highlights(review) -> tuple[list[str], str]:
    """Mark incomplete controls and then the purchaser confirmation control."""

    needs_attention = set(review.missing_required_fields) | set(review.invalid_fields)
    fields = [field for field in _FORM_KEYS if field in needs_attention]
    confirmation_needed = (
        not review.missing_required_fields
        and not review.invalid_fields
        and not review.confirmation_current
    )
    if not fields and not confirmation_needed:
        return [], ""
    selectors = [f".st-key-{_FORM_KEYS[field]}" for field in fields]
    if confirmation_needed:
        selectors.append(f".st-key-{_DRAWING_CONFIRM_KEY}")
    return fields, (
        "<style>\n"
        + ",\n".join(selectors)
        + " { outline: 2px solid #e02424; outline-offset: 2px; "
        "border-radius: 0.5rem; background: rgba(224, 36, 36, 0.10); "
        "padding: 0.35rem 0.5rem; }\n</style>"
    )


def _recognize_candidate(processed, candidate_id: str) -> AssistedQuoteSession:
    limits = upload_limits_from_environment()
    started = time.perf_counter()
    try:
        with st.spinner("Reading the selected plate locally..."):
            return recognize_selected_candidate(
                processed,
                candidate_id,
                availability=form_availability,
                timeout_seconds=limits.processing_timeout_seconds,
            )
    finally:
        run = st.session_state.get(_OWNER_ACCEPTANCE_RUN_KEY)
        if isinstance(run, OwnerAcceptanceRun):
            elapsed = time.perf_counter() - started
            previous = run.recognition_seconds or 0.0
            st.session_state[_OWNER_ACCEPTANCE_RUN_KEY] = update_run(
                run,
                recognition_seconds=previous + elapsed,
            )


def _apply_assisted_session(selected: AssistedQuoteSession) -> None:
    merged = integrate_selected_session(
        selected,
        current_values=_form_values_from_state(),
        current_origins=st.session_state.get(_FORM_ORIGINS_KEY, {}),
        availability=form_availability,
    )
    _install_form_integration(merged)
    owner_run = st.session_state.get(_OWNER_ACCEPTANCE_RUN_KEY)
    if isinstance(owner_run, OwnerAcceptanceRun):
        owner_run = record_event(owner_run, AcceptanceEventKind.APPLY_VALUES)
        st.session_state[_OWNER_ACCEPTANCE_RUN_KEY] = update_run(
            owner_run,
            auto_populated_fields=(
                field
                for field, origin in merged.origins.items()
                if origin == FormValueOrigin.DRAWING
            ),
        )
    st.session_state.pop(_DRAWING_PENDING_KEY, None)


def _can_prefill_single_plate() -> bool:
    """Prefill a fresh form only; retain explicit approval for edited forms."""

    origins = st.session_state.get(_FORM_ORIGINS_KEY, {})
    return (
        _DRAWING_SESSION_KEY not in st.session_state
        and all(origin == FormValueOrigin.DEFAULT.value for origin in origins.values())
        and _form_values_from_state() == st.session_state.get(_FORM_SNAPSHOT_KEY, {})
    )


if st.session_state.pop("phase1k_new_plate_requested", False):
    _reset_to_manual_defaults()
_initialize_form_state()
resume_reference = _qp_get("resume") if _qp_get("checkout") == "cancelled" else None
if (
    resume_reference
    and st.session_state.get("checkout_recovered_reference") != resume_reference
):
    if not is_logged_in():
        st.warning("Sign in to recover the configuration submitted to checkout.")
    else:
        try:
            recovered = fetch_checkout_recovery(
                API_BASE, resume_reference, auth_headers()
            )
            if recovered["kind"] != "direct" or len(recovered["items"]) != 1:
                raise ValueError("This recovery belongs to a quote cart.")
            values = recovered["items"][0]
            for field in _FORM_KEYS:
                st.session_state[_FORM_KEYS[field]] = values.get(field)
                if field in ("handle_hole_diameter", "handle_hole_center_from_handle_end"):
                    value = values.get(field)
                    st.session_state[_FORM_KEYS[field] + "_text"] = "" if value is None else str(value)
            st.session_state[_FORM_ORIGINS_KEY] = {
                field: FormValueOrigin.CUSTOMER.value for field in _FORM_KEYS
            }
            st.session_state[_FORM_SNAPSHOT_KEY] = dict(values)
            st.session_state[_DRAWING_SESSION_KEY] = recovered_quote_session(
                values, recovered.get("contexts", [None])[0]
            )
            st.session_state[_DRAWING_CONFIRM_KEY] = False
            st.session_state[_DRAWING_CONFLICTS_KEY] = []
            st.session_state["checkout_recovered_reference"] = resume_reference
            st.query_params.pop("checkout", None)
            st.query_params.pop("resume", None)
            st.success(
                "Your submitted configuration has been restored. Review and confirm it for fresh pricing."
            )
        except ValueError as exc:
            st.error(str(exc))
drawing_access_allowed = _internal_drawing_access_allowed()
owner_test_checkout_allowed = bool(
    OWNER_TEST_CHECKOUT_ENABLED and verified_owner_access(
        API_BASE,
        enabled=is_logged_in(),
        user_id_hint=current_user_id_hint() if is_logged_in() else None,
        headers=auth_headers() if is_logged_in() else {},
        access_path=("/internal/owner-test/access" if os.environ.get("APP_ENV") == "production"
                     else "/internal/drawing-intake/access"),
    )
)

@st.dialog("Sign in")
def _starter_sign_in():
    st.caption("Sign in to analyze a print, build a quote cart, or view your orders.")
    render_auth_sidebar(show_debug=False, placement="inline")


with st.container(key="configurator_starter", border=False):
    starter_upload, starter_analysis, starter_account = st.columns([4, 4, 2], gap="medium", vertical_alignment="center")
    with starter_upload:
        st.markdown(
            '<div class="starter-upload-title"><span aria-hidden="true">↥</span>'
            '<strong>Upload a drawing</strong></div>', unsafe_allow_html=True
        )
        st.caption("PDF, PNG, JPG · processed for this session")
    with starter_analysis:
        starter_status = st.empty()
    with starter_account:
        if is_logged_in():
            render_auth_sidebar(show_debug=False, placement="inline")
        else:
            st.caption("Manage your orders and quote cart")
            if st.button("Sign in", key="starter_sign_in", type="secondary"):
                _starter_sign_in()

starter_notice_shown = False


def _starter_notice(kind, message):
    global starter_notice_shown
    starter_notice_shown = True
    getattr(starter_status, kind)(message)


if not drawing_access_allowed:
    with starter_upload:
        if st.button(
            "Upload drawing", icon=":material/upload:", type="primary",
            key="drawing_sign_in_cta", disabled=not DRAWING_ASSISTED_ENABLED or is_logged_in(),
        ):
            _starter_sign_in()

if drawing_access_allowed:
    with starter_upload:
        if st.session_state.pop(_DRAWING_RESET_UPLOAD_KEY, False):
            st.session_state.pop("phase1g_uploaded_drawing", None)
            st.session_state.pop("phase1g_candidate_label", None)
        upload_column = st.container(key="starter_file_picker")
        analyze_column = st.container()
        uploaded_drawing = upload_column.file_uploader(
            "Upload drawing",
            type=["pdf", "png", "jpg", "jpeg"],
            key="phase1g_uploaded_drawing",
            label_visibility="collapsed",
        )

        if uploaded_drawing is not None and analyze_column.button(
            "Analyze drawing", key="phase1g_analyze_drawing",
        ):
            journey_event("analyzer", "attempted")
            try:
                limits = upload_limits_from_environment()
                validated_upload = validate_drawing_upload(
                    uploaded_drawing.getvalue(),
                    uploaded_drawing.name,
                    uploaded_drawing.type,
                    limits=limits,
                )
                owner_run = start_owner_acceptance_run(
                    upload_media_type=validated_upload.media_type,
                    upload_bytes=len(validated_upload.data),
                    page_count=validated_upload.page_count,
                )
                owner_run = record_event(owner_run, AcceptanceEventKind.ANALYZE_DRAWING)
                st.session_state[_OWNER_ACCEPTANCE_RUN_KEY] = owner_run
                st.session_state.pop(_OWNER_ACCEPTANCE_NOTES_KEY, None)
                inspection_started = time.perf_counter()
                with st.spinner("Analyzing your drawing..."):
                    processed_upload = inspect_validated_upload(
                        validated_upload,
                        timeout_seconds=limits.processing_timeout_seconds,
                    )
                owner_run = st.session_state[_OWNER_ACCEPTANCE_RUN_KEY]
                st.session_state[_OWNER_ACCEPTANCE_RUN_KEY] = update_run(
                    owner_run,
                    candidate_count=len(processed_upload.review.candidates),
                    inspection_seconds=time.perf_counter() - inspection_started,
                )
                journey_event("analyzer", "success" if processed_upload.review.quote_specific else "blocked",
                              "none" if processed_upload.review.quote_specific else "unsupported")
                st.session_state[_DRAWING_UPLOAD_KEY] = processed_upload
                st.session_state.pop(_DRAWING_PENDING_KEY, None)
                st.session_state.pop("phase1g_candidate_label", None)
                if len(processed_upload.review.candidates) == 1:
                    only_candidate = processed_upload.review.candidates[0]
                    recognized = _recognize_candidate(
                        processed_upload, only_candidate.candidate_id
                    )
                    if (
                        processed_upload.review.quote_specific
                        and _can_prefill_single_plate()
                    ):
                        _apply_assisted_session(recognized)
                    else:
                        st.session_state[_DRAWING_PENDING_KEY] = recognized
                st.rerun()
            except DrawingUploadValidationError as exc:
                journey_event("analyzer", "error", "invalid_input")
                _starter_notice("error", str(exc))
            except DrawingProcessingBusyError:
                journey_event("analyzer", "blocked", "system_restriction")
                _starter_notice("error",
                    "Another drawing is processing. Try again when it finishes; your form is unchanged."
                )
            except DrawingProcessingTimeoutError:
                journey_event("analyzer", "error", "technical_failure")
                _starter_notice("error",
                    "The drawing took too long to process. Your current configuration was preserved."
                )
            except DrawingProcessingError:
                journey_event("analyzer", "error", "technical_failure")
                _starter_notice("error",
                    "We couldn't process that drawing safely. You can continue with manual entry."
                )

        processed_upload = st.session_state.get(_DRAWING_UPLOAD_KEY)
        uploaded_sha256 = (
            hashlib.sha256(uploaded_drawing.getvalue()).hexdigest()
            if uploaded_drawing is not None
            else None
        )
        if processed_upload is not None and (
            uploaded_sha256 is None
            or uploaded_sha256 != processed_upload.document.sha256
        ):
            st.session_state.pop(_DRAWING_UPLOAD_KEY, None)
            st.session_state.pop(_DRAWING_PENDING_KEY, None)
            st.session_state.pop("phase1g_candidate_label", None)
            processed_upload = None
            if uploaded_sha256 is not None:
                _starter_notice("info",
                    "A different file is selected. Analyze it before applying values."
                )
        if processed_upload is not None:
            candidate_options = processed_upload.review.candidates
            if not processed_upload.review.quote_specific or not candidate_options:
                _starter_notice("warning",
                    "This file does not identify one quote-specific plate. Continue with the manual configuration below."
                )
            elif len(candidate_options) > 1:
                _starter_notice("success",
                    f"Drawing processed. We found {len(candidate_options)} possible plates. Select the one you want to quote."
                )
                candidate_by_label = {
                    f"{option.label} · page {option.page_number}": option.candidate_id
                    for option in candidate_options
                }
                selected_label = st.selectbox(
                    "Plate or schedule row",
                    options=list(candidate_by_label),
                    index=None,
                    placeholder="Select one plate",
                    key="phase1g_candidate_label",
                )
                active_drawing_exists = _DRAWING_SESSION_KEY in st.session_state
                action_label = (
                    "Use selected plate and replace previous drawing suggestions"
                    if active_drawing_exists
                    else "Use selected plate"
                )
                if st.button(
                    action_label,
                    disabled=selected_label is None,
                    key="phase1g_recognize_selected",
                ):
                    try:
                        owner_run = st.session_state.get(_OWNER_ACCEPTANCE_RUN_KEY)
                        if isinstance(owner_run, OwnerAcceptanceRun):
                            st.session_state[_OWNER_ACCEPTANCE_RUN_KEY] = record_event(
                                owner_run,
                                AcceptanceEventKind.SELECT_CANDIDATE,
                            )
                        pending = _recognize_candidate(
                            processed_upload,
                            candidate_by_label[selected_label],
                        )
                        st.session_state[_DRAWING_PENDING_KEY] = pending
                        st.rerun()
                    except DrawingProcessingBusyError:
                        _starter_notice("error",
                            "Another drawing is processing. Try again when it finishes; your form is unchanged."
                        )
                    except DrawingProcessingTimeoutError:
                        _starter_notice("error",
                            "The selected plate took too long to process. Your current configuration was preserved."
                        )
                    except DrawingProcessingError:
                        _starter_notice("error",
                            "We couldn't read the selected plate safely. Continue with manual entry."
                        )

        pending_session = st.session_state.get(_DRAWING_PENDING_KEY)
        if pending_session is not None:
            if st.button("Apply identified values", key="phase1g_apply_values"):
                _apply_assisted_session(pending_session)
                st.rerun()

        active_assisted_session = st.session_state.get(_DRAWING_SESSION_KEY)
        if active_assisted_session is not None:
            with st.popover("Drawing details and source references"):
                conflicts = st.session_state.get(_DRAWING_CONFLICTS_KEY, [])
                for conflict in conflicts:
                    label = FIELD_LABELS.get(conflict["canonical_field"], conflict["canonical_field"])
                    st.warning(
                        f"{label}: kept your value {conflict['customer_value']}; "
                        f"the drawing suggested {conflict['drawing_value']}."
                    )
                origins = st.session_state.get(_FORM_ORIGINS_KEY, {})
                for proposal in active_assisted_session.proposals:
                    if not proposal.canonical_field or (
                        proposal.proposed_value is None and not proposal.raw_text
                    ):
                        continue
                    canonical = proposal.canonical_field
                    label = FIELD_LABELS.get(canonical, canonical)
                    if proposal.unsupported:
                        state_label = "Unsupported"
                    elif origins.get(canonical) == FormValueOrigin.DRAWING.value:
                        state_label = "Prefilled"
                    elif origins.get(canonical) == FormValueOrigin.CUSTOMER.value:
                        state_label = "Customer value retained"
                    elif canonical == "handle_label":
                        state_label = "Optional — not populated"
                    else:
                        state_label = "Needs your input"
                    source = (
                        f"page {proposal.source_page}"
                        if proposal.source_page
                        else "source page unavailable"
                    )
                    st.write(
                        f"**{label} — {state_label}**  \n"
                        f"Detected: `{proposal.raw_text or proposal.proposed_value}` · {source}"
                    )
                    active_value = active_assisted_session.configuration.get(canonical)
                    if (
                        active_value is not None
                        and active_value.origin == FormValueOrigin.DRAWING.value
                        and active_value.extraction_field
                        and proposal.extraction_field
                        in active_value.extraction_field.split("+")
                    ):
                        if st.button(
                            f"Clear prefilled {label.lower()}",
                            key=f"phase1g_reject_{proposal.extraction_field}",
                        ):
                            rejected = reject_drawing_proposal(
                                active_assisted_session,
                                proposal.extraction_field,
                            )
                            st.session_state[_DRAWING_SESSION_KEY] = rejected
                            if canonical == "handle_label":
                                st.session_state.pop(_FORM_KEYS[canonical], None)
                            else:
                                st.session_state[_FORM_KEYS[canonical]] = None
                            st.session_state[_FORM_ORIGINS_KEY].pop(canonical, None)
                            st.session_state[_FORM_SNAPSHOT_KEY][canonical] = None
                            st.session_state[_DRAWING_CONFIRM_KEY] = False
                            st.rerun()

                if st.button(
                    "Reset quote and return to manual entry",
                    key="phase1g_reset_to_manual",
                ):
                    owner_run = st.session_state.get(_OWNER_ACCEPTANCE_RUN_KEY)
                    if isinstance(owner_run, OwnerAcceptanceRun):
                        st.session_state[_OWNER_ACCEPTANCE_RUN_KEY] = record_event(
                            owner_run, AcceptanceEventKind.RESET_TO_MANUAL
                        )
                    _reset_to_manual_defaults()
                    st.rerun()


# -----------------------------
# Two-column layout
# -----------------------------
configurator_start = st.container(key="configurator_start")
left, right = configurator_start.columns([1.12, 1.38], gap="medium")

# -----------------------------
# LEFT: image + summary (tight)
# -----------------------------
with left:
    st.subheader("Configuration Drawing")
    st.caption("Entered dimensions are reflected below. Drawing is not to scale (NTS).")

# -----------------------------
# RIGHT: inputs (narrowed) + Pay button bottom-center
# -----------------------------
drawing_mode = _DRAWING_SESSION_KEY in st.session_state


def _number_field(label: str, field: str, **kwargs):
    key = _FORM_KEYS[field]
    if st.session_state.get(key) is not None:
        return st.number_input(label, key=key, **kwargs)
    return st.number_input(label, value=None, key=key, **kwargs)


def _select_field(label: str, field: str, options, **kwargs):
    # Keep canonical values and unresolved analyzer fields; only selection UX changes.
    return choice_buttons(label, options, key=_FORM_KEYS[field], **kwargs)


with right:
    attention_style = st.empty() if drawing_mode else None
    form_col = st.container()

    with form_col:
        attention_prompt = st.empty() if drawing_mode else None
        st.caption("PRODUCT")
        quantity = _number_field("Quantity", "quantity", min_value=1, step=1)
        material = material_cards(material_options, key=_FORM_KEYS["material"])

        thickness_options = _thickness_options(material)
        existing_thickness = st.session_state.get(_FORM_KEYS["thickness"])
        if existing_thickness not in thickness_options:
            if drawing_mode:
                st.session_state[_FORM_KEYS["thickness"]] = None
            elif thickness_options:
                st.session_state[_FORM_KEYS["thickness"]] = thickness_options[0]
        thickness = _select_field(
            "Plate thickness (in.)",
            "thickness",
            thickness_options,
            placeholder="Select plate thickness",
            help="Finished nominal plate thickness.",
            format_func=lambda value: f'{value:g}"',
        )

        st.caption("DIMENSIONS")
        r2c1, r2c2 = st.columns(2)
        with r2c1:
            paddle_dia = _number_field(
                "Plate outside diameter (in.)",
                "paddle_dia",
                min_value=0.01,
                max_value=max_paddle_dia,
                step=0.001,
                format="%.3f",
            )
        with r2c2:
            bore_dia = _number_field(
                "Bore diameter (in.)",
                "bore_dia",
                min_value=0.01,
                max_value=max_bore_dia,
                step=0.001,
                format="%.3f",
            )

        r3c1, r3c2 = st.columns(2)
        with r3c1:
            handle_width = _number_field(
                "Handle width (in.)",
                "handle_width",
                min_value=0.0,
                step=0.001,
                format="%.3f",
                help="Width of the rectangular handle.",
            )
        with r3c2:
            handle_length = _number_field(
                "Handle Length (From Bore Center) (in.)",
                "handle_length_from_bore",
                min_value=0.0,
                step=0.001,
                format="%.3f",
                help="Distance from the bore center to the end of the handle.",
            )

        if st.session_state.get(_FORM_KEYS["handle_hole_enabled"]) is None:
            st.session_state[_FORM_KEYS["handle_hole_enabled"]] = False
        handle_hole_enabled = _select_field(
            "Handle Hole", "handle_hole_enabled", [False, True],
            format_func=lambda value: "HANDLE HOLE" if value else "NO HANDLE HOLE",
        )
        handle_hole_diameter = None
        handle_hole_center_from_handle_end = None
        if handle_hole_enabled:
            from drawing_intake.value_normalization import parse_number
            for field, label, help_text in (
                ("handle_hole_diameter", "Handle Hole Diameter (in.)", "Finished diameter of the laser/waterjet-cut hole in the handle."),
                ("handle_hole_center_from_handle_end", "Handle End to Hole Center (in.)", "Distance from the end edge of the handle to the centerline of the hole."),
            ):
                raw = st.text_input(label, value=str(st.session_state.get(_FORM_KEYS[field]) or ""),
                                    key=_FORM_KEYS[field] + "_text", help=help_text)
                try:
                    value = parse_number(raw) if raw.strip() else None
                except (ValueError, ZeroDivisionError):
                    value = None
                st.session_state[_FORM_KEYS[field]] = value
            handle_hole_diameter = st.session_state.get(_FORM_KEYS["handle_hole_diameter"])
            handle_hole_center_from_handle_end = st.session_state.get(_FORM_KEYS["handle_hole_center_from_handle_end"])

        st.caption("REQUIREMENTS")
        bore_tolerance = _select_field(
            "Bore tolerance (± in.)",
            "bore_tolerance",
            tol_options,
            placeholder="Select bore tolerance",
            help="Permitted variation from the specified finished bore diameter.",
            format_func=lambda value: f"±{value:g} in.",
        )

        handle_label = st.text_input(
            "Handle marking (optional)",
            key=_FORM_KEYS["handle_label"],
            placeholder="Optional text for your plate handle",
            max_chars=max_handle_label_chars,
            help=f"Maximum {max_handle_label_chars} characters. Letters, numbers, spaces, and standard shop-marking punctuation only.",
        )

        chamfer = bore_edge_choice(key=_FORM_KEYS["chamfer"])
        chamfer_width = None
        chamfer_details = {}
        if chamfer is True:
            chamfer_width = _number_field(
                "Chamfer Width (in.)",
                "chamfer_width",
                min_value=0.001,
                step=0.0001,
                format="%.4f",
                placeholder="Enter width",
                help="No width is assumed. Enter the required chamfer width.",
            )
            if chamfer_width is None:
                st.caption(
                    "Enter a chamfer width and press Enter or click outside the field to apply it."
                )
            if OWNER_ACCEPTANCE_MODE and not drawing_mode:
                # Optional explicit geometry remains supported, but the public
                # YES/NO + size contract never requires hidden legacy fields.
                chamfer_details = {
                    "chamfer_angle_degrees": st.session_state.get("staging_chamfer_angle"),
                    "chamfer_side": st.session_state.get("staging_chamfer_side"),
                    "flow_orientation": st.session_state.get("staging_chamfer_flow"),
                    "chamfer_width_definition": st.session_state.get("staging_chamfer_definition"),
                }
                chamfer_details = {
                    key: value for key, value in chamfer_details.items() if value is not None
                }

        st.caption("DELIVERY")
        st.caption("Lead-time selection updates the verified quote total below.")
        ships_in_days = _select_field(
            "Lead time",
            "ships_in_days",
            ships_options,
            placeholder="Select lead time",
            format_func=lambda days: f"{days} calendar days",
            help="Timing is estimated and subject to material availability and order-specific review.",
        )


current_form_values = {
    "handle_hole_enabled": handle_hole_enabled,
    "handle_hole_diameter": handle_hole_diameter,
    "handle_hole_center_from_handle_end": handle_hole_center_from_handle_end,
    "quantity": quantity,
    "material": material,
    "thickness": thickness,
    "handle_width": handle_width,
    "handle_length_from_bore": handle_length,
    "paddle_dia": paddle_dia,
    "bore_dia": bore_dia,
    "bore_tolerance": bore_tolerance,
    "chamfer": chamfer,
    "chamfer_width": chamfer_width,
    "handle_label": handle_label,
    "ships_in_days": ships_in_days,
}

previous_form_values = st.session_state.get(_FORM_SNAPSHOT_KEY, {})
form_origins = st.session_state.get(_FORM_ORIGINS_KEY, {})
active_assisted_session = st.session_state.get(_DRAWING_SESSION_KEY)
if active_assisted_session is not None:
    form_changed = any(
        (bool(previous_form_values.get(field)) != bool(value)
         if field == "handle_hole_enabled" else previous_form_values.get(field) != value)
        for field, value in current_form_values.items()
    )
    synchronized = synchronize_session_from_form(
        active_assisted_session,
        previous_values=previous_form_values,
        current_values=current_form_values,
        current_origins=form_origins,
    )
    owner_run = st.session_state.get(_OWNER_ACCEPTANCE_RUN_KEY)
    if isinstance(owner_run, OwnerAcceptanceRun):
        for field, after in current_form_values.items():
            before = previous_form_values.get(field)
            if before == after:
                continue
            owner_run = record_field_change(
                owner_run,
                canonical_field=field,
                previous_origin=form_origins.get(field),
                previous_value_present=(before is not None and before != ""),
            )
        st.session_state[_OWNER_ACCEPTANCE_RUN_KEY] = owner_run
    st.session_state[_DRAWING_SESSION_KEY] = synchronized.session
    st.session_state[_FORM_ORIGINS_KEY] = {
        field: origin.value if isinstance(origin, FormValueOrigin) else str(origin)
        for field, origin in synchronized.origins.items()
    }
    if form_changed:
        st.session_state[_DRAWING_CONFIRM_KEY] = False
    active_assisted_session = synchronized.session
else:
    for field, value in current_form_values.items():
        if previous_form_values.get(field) != value:
            form_origins[field] = FormValueOrigin.CUSTOMER.value
    st.session_state[_FORM_ORIGINS_KEY] = form_origins
st.session_state[_FORM_SNAPSHOT_KEY] = dict(current_form_values)


assisted_review = None
if active_assisted_session is not None:
    assisted_review = review_assisted_quote(
        active_assisted_session,
        availability=form_availability,
    )
    owner_run = st.session_state.get(_OWNER_ACCEPTANCE_RUN_KEY)
    if isinstance(owner_run, OwnerAcceptanceRun):
        owner_run = update_run(
            owner_run,
            current_missing_fields=assisted_review.missing_required_fields,
            current_invalid_fields=assisted_review.invalid_fields,
            current_unsupported_fields=assisted_review.unsupported_fields,
            confirmation_current=assisted_review.confirmation_current,
        )
        st.session_state[_OWNER_ACCEPTANCE_RUN_KEY] = owner_run
    with right:
        with form_col:
            st.divider()
            st.subheader("Review your drawing-assisted configuration")
            with st.expander("Drawing evidence and fields needing review"):
                st.caption(
                    "Drawing readings are proposals. Review and correct the configuration before confirming it."
                )
                st.dataframe(
                    [
                        {
                            "Field": proposal.extraction_field.replace(
                                "_", " "
                            ).title(),
                            "Proposed value": (
                                str(proposal.proposed_value)
                                if proposal.proposed_value is not None
                                else "Unresolved"
                            ),
                            "Units": proposal.normalized_unit or "",
                            "Evidence": proposal.raw_text or "",
                            "Source": (proposal.source_type or "unspecified").replace(
                                "_", " "
                            ),
                            "Review": (
                                "Conflict / alternatives: "
                                + str(proposal.competing_values)
                                if len(proposal.competing_values) > 1
                                else str(proposal.evidence_status).replace("_", " ")
                            ),
                            "Use": (
                                "Configuration proposal"
                                if proposal.canonical_field
                                else "Reference only"
                            ),
                        }
                        for proposal in active_assisted_session.proposals
                    ],
                    hide_index=True,
                    width="stretch",
                )
                st.caption(
                    "Secondary holes and transition radii are reference observations; this form does not configure those features. Unreadable notes require manual entry."
                )
            if assisted_review.attention:
                for attention in assisted_review.attention:
                    message = f"**{attention.label}:** {attention.message}"
                    if attention.kind == FieldAttentionKind.INVALID:
                        st.error(message)
                    elif attention.kind == FieldAttentionKind.UNSUPPORTED:
                        st.warning(message)
                    elif attention.kind == FieldAttentionKind.MISSING_REQUIRED:
                        st.info(message)
            else:
                st.success("All required fields are complete and valid.")

            confirmation_disabled = bool(
                assisted_review.missing_required_fields
                or assisted_review.invalid_fields
            )
            confirmed = st.checkbox(
                "I have reviewed the dimensions and specifications above and confirm that they represent the part I want manufactured.",
                key=_DRAWING_CONFIRM_KEY,
                disabled=confirmation_disabled,
            )
            if confirmed and not assisted_review.confirmation_current:
                try:
                    active_assisted_session = confirm_configuration(
                        active_assisted_session,
                        availability=form_availability,
                    )
                    st.session_state[_DRAWING_SESSION_KEY] = active_assisted_session
                    assisted_review = review_assisted_quote(
                        active_assisted_session,
                        availability=form_availability,
                    )
                    owner_run = st.session_state.get(_OWNER_ACCEPTANCE_RUN_KEY)
                    if isinstance(owner_run, OwnerAcceptanceRun):
                        owner_run = record_event(
                            owner_run,
                            AcceptanceEventKind.CONFIRM_CONFIGURATION,
                        )
                        st.session_state[_OWNER_ACCEPTANCE_RUN_KEY] = update_run(
                            owner_run,
                            current_missing_fields=assisted_review.missing_required_fields,
                            current_invalid_fields=assisted_review.invalid_fields,
                            current_unsupported_fields=assisted_review.unsupported_fields,
                            confirmation_current=assisted_review.confirmation_current,
                        )
                except ValueError:
                    st.error(
                        "Complete and correct the highlighted fields before confirming."
                    )
            elif not confirmed and assisted_review.confirmation_current:
                active_assisted_session = active_assisted_session.model_copy(
                    update={"confirmation_fingerprint": None}
                )
                st.session_state[_DRAWING_SESSION_KEY] = active_assisted_session
                assisted_review = review_assisted_quote(
                    active_assisted_session,
                    availability=form_availability,
                )

            highlighted_fields, highlight_css = _required_field_highlights(
                assisted_review
            )
            if highlight_css:
                attention_style.markdown(highlight_css, unsafe_allow_html=True)
            else:
                attention_style.empty()
            if highlighted_fields:
                labels = ", ".join(FIELD_LABELS[field] for field in highlighted_fields)
                attention_prompt.error(
                    f"Complete or correct the fields outlined in red: {labels}."
                )
            elif not assisted_review.confirmation_current:
                attention_prompt.error("Confirmation required before pricing.")
            else:
                attention_prompt.empty()




if not starter_notice_shown:
    with starter_status.container():
        if active_assisted_session is not None and assisted_review is not None:
            required = canonical_required_fields(chamfer=current_form_values.get("chamfer"))
            if current_form_values.get("handle_hole_enabled"):
                required += ["handle_hole_diameter", "handle_hole_center_from_handle_end"]
            missing = set(assisted_review.missing_required_fields)
            populated = sum(field not in missing for field in required)
            attention_count = len(missing | set(assisted_review.invalid_fields))
            st.success(f"Drawing analysis complete — {populated} of {len(required)} fields populated.")
            if attention_count:
                st.caption(f"Complete or correct the {attention_count} highlighted fields below.")
            else:
                st.caption("All required fields are populated. Review them below before pricing.")
            st.caption("Detected values can be reviewed and edited before pricing.")
        elif st.session_state.get(_DRAWING_PENDING_KEY) is not None:
            pending = st.session_state[_DRAWING_PENDING_KEY]
            st.info(f"Drawing analysis complete — {len(pending.configuration)} fields identified.")
            st.caption("Apply identified values to the fields below. Your existing entries are preserved.")
        elif drawing_access_allowed and uploaded_drawing is not None:
            st.markdown("**Your drawing is ready to analyze.**")
            st.caption("Analyze it to populate the fields below.")
        elif is_logged_in() and DRAWING_ASSISTED_ENABLED and not drawing_access_allowed:
            st.markdown("**Drawing analysis is unavailable for this account.**")
            st.caption("You can complete the configurator fields below.")
        else:
            st.markdown("**Ready to read your print.**")
            st.caption("Detected values appear below and remain editable.")


# -----------------------------
# Validation
# -----------------------------
errors = []
if bore_dia is not None and paddle_dia is not None and bore_dia >= paddle_dia:
    errors.append("Bore diameter must be smaller than the plate outside diameter.")
if (
    handle_length is not None
    and paddle_dia is not None
    and handle_length <= (paddle_dia / 2)
):
    errors.append("Handle length from bore center must extend beyond the plate radius.")
if handle_width is not None and handle_width <= 0:
    errors.append("Handle width must be greater than zero.")

if handle_hole_enabled:
    from plate_geometry import validate_handle_hole
    if all(v is not None for v in (paddle_dia, handle_width, handle_length)):
        try:
            validate_handle_hole(paddle_dia, handle_width, handle_length, True,
                                 handle_hole_diameter, handle_hole_center_from_handle_end)
        except ValueError as exc:
            errors.append("Drawing HOLD: " + str(exc))

if errors:
    with right:
        st.divider()
        for e in errors:
            st.error(e)
    if active_assisted_session is None:
        st.stop()

# -----------------------------
# Pricing (authoritative API)
# -----------------------------
payload_inputs = None
if all(
    value is not None
    for field, value in current_form_values.items()
    if field not in {"chamfer_width", "handle_hole_diameter", "handle_hole_center_from_handle_end"}
) and (chamfer is not True or chamfer_width is not None):
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
        "chamfer_width": (float(chamfer_width) if chamfer_width is not None else None),
        "handle_label": (handle_label or "").strip() or "No label",
        "ships_in_days": int(ships_in_days),
        **chamfer_details,
        **({
            "handle_hole_enabled": True,
            "handle_hole_diameter": handle_hole_diameter,
            "handle_hole_center_from_handle_end": handle_hole_center_from_handle_end,
        } if handle_hole_enabled else {}),
    }

if os.environ.get("APP_ENV") == "production" and is_logged_in() and owner_test_checkout_allowed:
    from journey.ui import mark_internal
    mark_internal()
journey_event("configurator")
if errors:
    journey_event("configuration", "error", "invalid_input")
if active_assisted_session is not None and assisted_review is not None and assisted_review.attention:
    if any(a.kind == FieldAttentionKind.UNSUPPORTED for a in assisted_review.attention):
        journey_event("configuration", "blocked", "unsupported")
result = None
pricing_error = None
pricing_payload = None
if payload_inputs is not None and not errors:
    if active_assisted_session is None:
        pricing_payload = payload_inputs
    elif (
        OWNER_ACCEPTANCE_MODE
        and drawing_access_allowed
        and assisted_review is not None
        and assisted_review.confirmation_current
    ):
        try:
            pricing_payload = confirmed_drawing_quote_inputs(
                active_assisted_session,
                payload_inputs,
                availability=form_availability,
            )
        except ValueError:
            pricing_error = "The current configuration needs review and confirmation before pricing."

if pricing_payload is not None:
    journey_event("configuration", "success")
    result, pricing_error = request_authoritative_price(pricing_payload)
    if result:
        journey_event("quote", "success")

    if pricing_error:
        with right:
            st.error(pricing_error)
            st.caption("Checkout is disabled until the live price can be verified.")
        result = None
elif pricing_error:
    with right:
        st.error(pricing_error)

# Shipping estimates (computed once)
area_sq_in = result.get("area_sq_in") if result else None
weight_lb = result.get("estimated_total_weight_lb") if result else None
pkg = result.get("estimated_package_in") if result else None

# -----------------------------
# LEFT: Quote summary + shipping estimates (tight)
# -----------------------------
with left:
    preview_ready = payload_inputs is not None and not errors
    if preview_ready:
        components.html(
            "<style>html,body{margin:0;height:100%}"
            "svg{width:100%!important;height:100%!important}</style>"
            + render_plate_svg(
                handle_hole_enabled=handle_hole_enabled,
                handle_hole_diameter=handle_hole_diameter,
                handle_hole_center_from_handle_end=handle_hole_center_from_handle_end,
                paddle_dia=paddle_dia,
                bore_dia=bore_dia,
                handle_width=handle_width,
                handle_length_from_bore=handle_length,
                thickness=float(thickness),
                material=material,
                bore_tolerance=float(bore_tolerance),
                handle_label=(handle_label or "").strip() or "No label",
                chamfer=bool(chamfer),
                chamfer_width=(
                    float(chamfer_width) if chamfer_width is not None else None
                ),
            ),
            height=300,
            scrolling=False,
        )
    else:
        st.info("Complete the required dimensions to update the plate preview.")
    with st.container(border=True):
        if result:
            c1, c2 = st.columns(2)
            c1.metric("Unit price", f"${result['unit_price']:,.2f}")
            c2.metric("Total price", f"${result['total_price']:,.2f}")
        elif active_assisted_session is not None and pricing_error:
            st.warning(
                "A verified price is not currently available. Your configuration is preserved."
            )
        elif active_assisted_session is not None:
            if (
                assisted_review is not None
                and not assisted_review.missing_required_fields
                and not assisted_review.invalid_fields
                and not assisted_review.confirmation_current
            ):
                st.error("Confirmation required before pricing.")
            else:
                st.info(
                    "Complete the required fields before confirming the configuration."
                )
        elif payload_inputs is None:
            st.info("Complete the required fields to see a verified price.")
        else:
            st.warning("A verified price is not currently available.")

    if not LEFT_TIGHTEN:
        st.divider()

    if result and weight_lb is not None and pkg:
        with st.container(key="preview_fulfillment"):
            st.metric("Estimated ship time", f"{int(ships_in_days)} calendar days")
            st.markdown("**Shipping estimates**")
            shipping_weight, shipping_package = st.columns([1, 1.4])
            shipping_weight.metric("Estimated total weight", f"{weight_lb:.2f} lb")
            shipping_package.metric(
                "Estimated package",
                f"{pkg['length']} × {pkg['width']} × {pkg['height']} in.",
            )


# -----------------------------
# Cart helper (NEW)
# -----------------------------
def _add_to_cart(payload_inputs: dict, result: dict, *, assisted: bool = False) -> None:
    st.session_state.cart.append(
        {
            "line_id": str(uuid.uuid4()),
            "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "inputs": copy.deepcopy(payload_inputs),
            # snapshot pricing at time added (optional but useful)
            "unit_price": float(result.get("unit_price") or 0),
            "total_price": float(result.get("total_price") or 0),
            "material": payload_inputs.get("material"),
            "thickness": payload_inputs.get("thickness"),
            # Browser-session metadata only. Checkout sends only canonical inputs.
            "assisted_quote": assisted,
            "selected_part_context": (
                selected_part_context(active_assisted_session) if assisted else None
            ),
            "configuration_id": result.get("configuration_id"),
            "pricing_config_version": result.get("pricing_config_version"),
        }
    )


# -----------------------------
# RIGHT: Pay button (bottom-center, not full width)
# -----------------------------
with right:
    st.markdown("<div style='height:18px'></div>", unsafe_allow_html=True)

    form_col = st.container()
    with form_col:
        # Logged-in indicator (ties the order to account)
        if is_logged_in():
            st.success("You’re logged in — this order will be saved to your account.")
        else:
            st.info(
                "Checkout as guest — open Account to save orders to your account."
            )

        if (OWNER_ACCEPTANCE_MODE or os.environ.get("APP_ENV") == "production") and not owner_test_checkout_allowed:
            st.caption(
                "Checkout is currently closed."
            )
        elif active_assisted_session is not None and not owner_test_checkout_allowed:
            st.caption("Checkout remains disabled for drawing-assisted configurations.")
        else:
            st.caption(
                "Price is revalidated before checkout; shipping is selected there."
            )

        left_pad = max(0.0, (1.0 - PAY_BUTTON_WIDTH_RATIO) / 2.0)
        btn_cols = st.columns([left_pad, PAY_BUTTON_WIDTH_RATIO, left_pad])

        with btn_cols[1]:
            checkout_disabled = (
                result is None
                or ((OWNER_ACCEPTANCE_MODE or os.environ.get("APP_ENV") == "production") and not owner_test_checkout_allowed)
                or (
                    active_assisted_session is not None
                    and not owner_test_checkout_allowed
                )
            )
            if checkout_disabled and result is not None:
                journey_event("checkout", "blocked", "system_restriction")
            if st.button("Continue to secure checkout", disabled=checkout_disabled):
                if active_assisted_session is not None:
                    try:
                        verified_assisted_cart_inputs(
                            active_assisted_session,
                            pricing_payload,
                            result,
                            availability=form_availability,
                        )
                    except (ValueError, KeyError, TypeError):
                        st.error(
                            "Review and confirm the current verified quote before checkout."
                        )
                        st.stop()
                start_checkout(pricing_payload, result)

            # Under your existing "Place Order & Pay" button block:
            st.markdown("<div style='height:10px'></div>", unsafe_allow_html=True)

            # Only for logged-in users (multi-item workflow)
            add_disabled = (
                not is_logged_in()
                or result is None
                or ((OWNER_ACCEPTANCE_MODE or os.environ.get("APP_ENV") == "production") and not owner_test_checkout_allowed)
                or (
                    active_assisted_session is not None
                    and not owner_test_checkout_allowed
                )
            )
            if st.button(
                "Add another plate", disabled=add_disabled, use_container_width=True
            ):
                if active_assisted_session is not None:
                    try:
                        cart_inputs = verified_assisted_cart_inputs(
                            active_assisted_session,
                            pricing_payload,
                            result,
                            availability=form_availability,
                        )
                    except (ValueError, KeyError, TypeError):
                        st.error(
                            "Review and confirm the current verified quote before adding it."
                        )
                        st.stop()
                else:
                    cart_inputs = pricing_payload
                journey_event("cart", "success")
                _add_to_cart(
                    cart_inputs, result, assisted=active_assisted_session is not None
                )
                st.success(
                    f"Added to Quote Cart. Items in cart: {len(st.session_state.cart)}"
                )
                # Optional: jump them to cart immediately
                st.switch_page("pages/3_Quote_Cart.py")

            if add_disabled:
                st.caption(
                    "Log in to add multiple plates; a verified live price is required."
                )
