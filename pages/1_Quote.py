# pages/1_Quote.py
import os
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
from drawing_intake.assisted_quote import (
    FIELD_LABELS,
    AssistedQuoteSession,
    FieldAttentionKind,
    availability_from_active_config,
    confirm_configuration,
    reject_drawing_proposal,
    review_assisted_quote,
)
from drawing_intake.configurator_integration import (
    DrawingProcessingBusyError,
    DrawingProcessingError,
    DrawingProcessingTimeoutError,
    DrawingUploadValidationError,
    FormValueOrigin,
    accept_pricing_boundary_without_invocation,
    feature_flag_enabled,
    inspect_validated_upload,
    integrate_selected_session,
    recognize_selected_candidate,
    synchronize_session_from_form,
    upload_limits_from_environment,
    validate_drawing_upload,
)
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
RIGHT_FORM_WIDTH = 0.72  # 0.55 - 0.85 (smaller = narrower input column)
IMAGE_TOP_SPACER_PX = 10  # move image down more/less
LEFT_TIGHTEN = True  # tighter left column spacing
PAY_BUTTON_HEIGHT_PX = 56  # taller button
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
    st.error("The O-Plates pricing service is not configured.")
    st.stop()


def _internal_drawing_access_allowed() -> bool:
    """Ask the existing API to verify the current Supabase JWT and allowlist."""

    if not DRAWING_ASSISTED_ENABLED or not is_logged_in():
        return False
    user_hint = current_user_id_hint()
    if not user_hint:
        return False
    try:
        response = requests.get(
            f"{API_BASE}/internal/drawing-intake/access",
            headers=auth_headers(),
            timeout=5,
        )
        if response.status_code != 200:
            return False
        body = response.json()
        return bool(
            body.get("enabled")
            and body.get("authorized")
            and body.get("user_id") == user_hint
        )
    except (requests.RequestException, ValueError):
        return False


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


def request_authoritative_price(
    payload_inputs: dict,
) -> tuple[Optional[dict], Optional[str]]:
    headers = {"x-api-key": API_KEY} if API_KEY else {}
    try:
        response = requests.post(
            f"{API_BASE}/quote",
            json=payload_inputs,
            headers=headers,
            timeout=20,
        )
    except requests.RequestException:
        return (
            None,
            "Live pricing is temporarily unavailable. Your entries are preserved; please try again.",
        )

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
        if value is None:
            st.session_state.pop(key, None)
        else:
            st.session_state[key] = value
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


_initialize_form_state()
drawing_access_allowed = _internal_drawing_access_allowed()

if drawing_access_allowed:
    with st.expander(
        "Upload a Drawing",
        expanded=_DRAWING_SESSION_KEY not in st.session_state,
    ):
        st.write("Upload your print and we'll fill in the details we can identify.")
        st.caption(
            "Internal acceptance only · PDF, PNG, or JPEG · local processing · no drawing storage"
        )
        if st.session_state.pop(_DRAWING_RESET_UPLOAD_KEY, False):
            st.session_state.pop("phase1g_uploaded_drawing", None)
            st.session_state.pop("phase1g_candidate_label", None)
        uploaded_drawing = st.file_uploader(
            "Drawing file",
            type=["pdf", "png", "jpg", "jpeg"],
            key="phase1g_uploaded_drawing",
        )

        if st.button(
            "Analyze drawing",
            disabled=uploaded_drawing is None,
            key="phase1g_analyze_drawing",
        ):
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
                with st.spinner("Analyzing the drawing locally..."):
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
                st.session_state[_DRAWING_UPLOAD_KEY] = processed_upload
                st.session_state.pop(_DRAWING_PENDING_KEY, None)
                st.session_state.pop("phase1g_candidate_label", None)
                if len(processed_upload.review.candidates) == 1:
                    only_candidate = processed_upload.review.candidates[0]
                    st.session_state[_DRAWING_PENDING_KEY] = _recognize_candidate(
                        processed_upload, only_candidate.candidate_id
                    )
                st.rerun()
            except DrawingUploadValidationError as exc:
                st.error(str(exc))
            except DrawingProcessingBusyError:
                st.error(
                    "Another internal drawing test is processing. Try again when it finishes; your form is unchanged."
                )
            except DrawingProcessingTimeoutError:
                st.error(
                    "The drawing took too long to process. Your current configuration was preserved."
                )
            except DrawingProcessingError:
                st.error(
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
                st.info(
                    "A different file is selected. Analyze it before applying values."
                )
        if processed_upload is not None:
            candidate_options = processed_upload.review.candidates
            if not processed_upload.review.quote_specific or not candidate_options:
                st.warning(
                    "This file does not identify one quote-specific plate. Continue with the manual configuration below."
                )
            elif len(candidate_options) > 1:
                st.success(
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
                        st.error(
                            "Another internal drawing test is processing. Try again when it finishes; your form is unchanged."
                        )
                    except DrawingProcessingTimeoutError:
                        st.error(
                            "The selected plate took too long to process. Your current configuration was preserved."
                        )
                    except DrawingProcessingError:
                        st.error(
                            "We couldn't read the selected plate safely. Continue with manual entry."
                        )
            else:
                st.success(
                    "Your drawing has been processed. Review the identified values before applying them."
                )

        pending_session = st.session_state.get(_DRAWING_PENDING_KEY)
        if pending_session is not None:
            proposed_count = len(pending_session.configuration)
            st.info(
                f"Ready to prefill {proposed_count} field{'s' if proposed_count != 1 else ''}. "
                "Your existing entries will be preserved if they conflict."
            )
            if st.button("Apply identified values", key="phase1g_apply_values"):
                merged = integrate_selected_session(
                    pending_session,
                    current_values=_form_values_from_state(),
                    current_origins=st.session_state.get(_FORM_ORIGINS_KEY, {}),
                    availability=form_availability,
                )
                _install_form_integration(merged)
                owner_run = st.session_state.get(_OWNER_ACCEPTANCE_RUN_KEY)
                if isinstance(owner_run, OwnerAcceptanceRun):
                    owner_run = record_event(
                        owner_run, AcceptanceEventKind.APPLY_VALUES
                    )
                    st.session_state[_OWNER_ACCEPTANCE_RUN_KEY] = update_run(
                        owner_run,
                        auto_populated_fields=(
                            field
                            for field, origin in merged.origins.items()
                            if origin == FormValueOrigin.DRAWING
                        ),
                    )
                st.session_state.pop(_DRAWING_PENDING_KEY, None)
                st.rerun()

        active_assisted_session = st.session_state.get(_DRAWING_SESSION_KEY)
        if active_assisted_session is not None:
            st.success(
                "Drawing values are connected to this quote form. Review them and complete the items marked below."
            )
            conflicts = st.session_state.get(_DRAWING_CONFLICTS_KEY, [])
            for conflict in conflicts:
                label = FIELD_LABELS.get(
                    conflict["canonical_field"], conflict["canonical_field"]
                )
                st.warning(
                    f"{label}: kept your value {conflict['customer_value']}; "
                    f"the drawing suggested {conflict['drawing_value']}."
                )

            with st.expander("Drawing details and source references"):
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
                            st.session_state.pop(_FORM_KEYS[canonical], None)
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
left, right = st.columns([1.12, 1.38], gap="large")

# -----------------------------
# LEFT: image + summary (tight)
# -----------------------------
with left:
    st.markdown(
        f"<div style='height:{IMAGE_TOP_SPACER_PX}px'></div>", unsafe_allow_html=True
    )
    st.subheader("Configuration Drawing")
    st.caption("Entered dimensions are reflected below. Drawing is not to scale (NTS).")

# -----------------------------
# RIGHT: inputs (narrowed) + Pay button bottom-center
# -----------------------------
drawing_mode = _DRAWING_SESSION_KEY in st.session_state


def _number_field(label: str, field: str, **kwargs):
    key = _FORM_KEYS[field]
    if key in st.session_state:
        return st.number_input(label, key=key, **kwargs)
    return st.number_input(label, value=None, key=key, **kwargs)


def _select_field(label: str, field: str, options, **kwargs):
    key = _FORM_KEYS[field]
    if key in st.session_state and st.session_state.get(key) in options:
        return st.selectbox(label, options=options, key=key, **kwargs)
    st.session_state.pop(key, None)
    return st.selectbox(label, options=options, index=None, key=key, **kwargs)


with right:
    _spacer, form_col = st.columns(
        [1 - RIGHT_FORM_WIDTH, RIGHT_FORM_WIDTH], gap="medium"
    )

    with form_col:
        st.caption("PRODUCT")
        r1c1, r1c2 = st.columns([1, 2])
        with r1c1:
            quantity = _number_field("Quantity", "quantity", min_value=1, step=1)
        with r1c2:
            material = _select_field("Material", "material", material_options)

        thickness_options = _thickness_options(material)
        existing_thickness = st.session_state.get(_FORM_KEYS["thickness"])
        if existing_thickness not in thickness_options:
            if drawing_mode:
                st.session_state.pop(_FORM_KEYS["thickness"], None)
            elif thickness_options:
                st.session_state[_FORM_KEYS["thickness"]] = thickness_options[0]
        thickness = _select_field(
            "Plate thickness (in.)",
            "thickness",
            thickness_options,
            placeholder="Select plate thickness",
            help="Finished nominal plate thickness.",
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
                "Handle length from bore center (in.)",
                "handle_length_from_bore",
                min_value=0.0,
                step=0.001,
                format="%.3f",
                help="Distance from the bore center to the end of the handle.",
            )

        st.caption("REQUIREMENTS")
        bore_tolerance = _select_field(
            "Bore tolerance (± in.)",
            "bore_tolerance",
            tol_options,
            placeholder="Select bore tolerance",
            help="Permitted variation from the specified finished bore diameter.",
        )

        handle_label = st.text_input(
            "Handle marking (optional)",
            key=_FORM_KEYS["handle_label"],
            placeholder="UPSTREAM x.xxx BORE x.xxx BETA",
            max_chars=max_handle_label_chars,
            help=f"Maximum {max_handle_label_chars} characters. Letters, numbers, spaces, and standard shop-marking punctuation only.",
        )

        if drawing_mode:
            chamfer = _select_field(
                "Chamfer",
                "chamfer",
                [False, True],
                placeholder="Select yes or no",
                format_func=lambda value: "Yes" if value else "No",
            )
        else:
            chamfer = st.checkbox("Chamfer", value=False)
            st.session_state[_FORM_KEYS["chamfer"]] = chamfer
        chamfer_width = None
        if chamfer is True:
            chamfer_width = _number_field(
                "Chamfer Width (in.)",
                "chamfer_width",
                min_value=0.001,
                step=0.001,
                format="%.3f",
                placeholder="Enter width",
                help="No width is assumed. Enter the required chamfer width.",
            )

        st.caption("DELIVERY")
        ships_in_days = _select_field(
            "Lead time",
            "ships_in_days",
            ships_options,
            placeholder="Select lead time",
            format_func=lambda days: f"{days} calendar days",
            help="Timing is estimated and subject to material availability and order-specific review.",
        )


current_form_values = {
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
        previous_form_values.get(field) != value
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

            owner_run = st.session_state.get(_OWNER_ACCEPTANCE_RUN_KEY)
            if isinstance(owner_run, OwnerAcceptanceRun):
                with st.expander("Internal test feedback"):
                    st.caption(
                        "This summary stays in this browser session unless you download it. "
                        "It excludes the file name, drawing content, OCR text, dimensions, and customer data."
                    )
                    owner_notes = st.text_area(
                        "Optional owner notes",
                        key=_OWNER_ACCEPTANCE_NOTES_KEY,
                        placeholder="Describe confusing steps or recognition behavior without copying proprietary drawing content.",
                    )
                    summary = summarize_owner_acceptance(
                        owner_run,
                        optional_owner_notes=owner_notes,
                    )
                    st.write(
                        f"**Measured:** {summary.processing_wait_seconds:.1f}s processing · "
                        f"{summary.distinct_auto_populated_fields} prefilled fields · "
                        f"{summary.distinct_manual_field_entries} manually completed · "
                        f"{summary.distinct_corrected_fields} corrected"
                    )
                    st.caption(
                        "Click = an explicit app button or confirmation activation. "
                        "A candidate choice and each changed field are separate customer actions, not clicks. "
                        "Typing in one field counts as one distinct manual field entry. "
                        "This single-page workflow records zero page transitions."
                    )
                    st.download_button(
                        "Download test feedback (JSON)",
                        data=feedback_json(summary),
                        file_name=f"oplates-owner-feedback-{summary.run_id[:8]}.json",
                        mime="application/json",
                    )


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
    if field != "chamfer_width"
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
    }

result = None
pricing_error = None
pricing_boundary = None
if active_assisted_session is None:
    result, pricing_error = request_authoritative_price(payload_inputs)
    if pricing_error:
        with right:
            st.error(pricing_error)
            st.caption("Checkout is disabled until the live price can be verified.")
        result = None
elif (
    payload_inputs is not None
    and assisted_review is not None
    and assisted_review.confirmation_current
):
    pricing_boundary = accept_pricing_boundary_without_invocation(
        active_assisted_session,
        payload_inputs,
        availability=form_availability,
    )
    with right:
        with form_col:
            if pricing_boundary.structures_equal:
                st.success(
                    "Configuration confirmed and ready for the existing pricing workflow. Pricing is disabled during internal acceptance."
                )
            else:
                st.error("The drawing-assisted handoff does not match the quote form.")

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
                chamfer_width=(
                    float(chamfer_width) if chamfer_width is not None else None
                ),
            ),
            height=430,
            scrolling=False,
        )
    else:
        st.info("Complete the required dimensions to update the plate preview.")
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
        elif active_assisted_session is not None and pricing_boundary is not None:
            st.success("Customer-confirmed configuration is ready for pricing review.")
            st.caption(
                "No live price was requested during Phase 1G internal acceptance."
            )
        elif active_assisted_session is not None:
            st.info(
                "Complete and confirm the configuration to make it ready for pricing."
            )
        else:
            st.warning("A verified price is not currently available.")

    if not LEFT_TIGHTEN:
        st.divider()

    if result and weight_lb is not None and pkg:
        st.caption("Shipping estimates")
        s1, s2 = st.columns(2)
        s1.metric("Estimated total weight", f"{weight_lb:.2f} lb")
        s2.metric(
            "Estimated package",
            f"{pkg['length']} × {pkg['width']} × {pkg['height']} in.",
        )


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

    _spacer, form_col = st.columns(
        [1 - RIGHT_FORM_WIDTH, RIGHT_FORM_WIDTH], gap="large"
    )
    with form_col:
        # Logged-in indicator (ties the order to account)
        if is_logged_in():
            st.success("You’re logged in — this order will be saved to your account.")
        else:
            st.info(
                "Checkout as guest — log in from the sidebar to save orders to your account."
            )

        if OWNER_ACCEPTANCE_MODE:
            st.caption(
                "Checkout is disabled in this controlled owner-acceptance environment."
            )
        elif active_assisted_session is not None:
            st.caption(
                "Pricing and checkout are disabled for the internal drawing-assisted acceptance flow."
            )
        else:
            st.caption(
                "Price is revalidated before checkout; shipping is selected there."
            )

        left_pad = max(0.0, (1.0 - PAY_BUTTON_WIDTH_RATIO) / 2.0)
        btn_cols = st.columns([left_pad, PAY_BUTTON_WIDTH_RATIO, left_pad])

        with btn_cols[1]:
            checkout_disabled = result is None or OWNER_ACCEPTANCE_MODE
            if st.button("Continue to secure checkout", disabled=checkout_disabled):
                start_checkout(payload_inputs, result)

            # Under your existing "Place Order & Pay" button block:
            st.markdown("<div style='height:10px'></div>", unsafe_allow_html=True)

            # Only for logged-in users (multi-item workflow)
            add_disabled = not is_logged_in() or result is None or OWNER_ACCEPTANCE_MODE
            if st.button(
                "Add another plate", disabled=add_disabled, use_container_width=True
            ):
                _add_to_cart(payload_inputs, result)
                st.success(
                    f"Added to Quote Cart. Items in cart: {len(st.session_state.cart)}"
                )
                # Optional: jump them to cart immediately
                st.switch_page("pages/3_Quote_Cart.py")

            if add_disabled:
                st.caption(
                    "Log in to add multiple plates; a verified live price is required."
                )
