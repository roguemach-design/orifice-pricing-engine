"""Internal-only drawing-assisted quote prototype.

Run locally with:
    OPLATES_INTERNAL_DRAWING_PROTOTYPE=1 \
      .venv/bin/streamlit run internal_drawing_quote_app.py

This entry point never calls pricing, checkout, storage, or an external OCR service.
"""

from __future__ import annotations

import os
from typing import Any

import streamlit as st
import streamlit.components.v1 as components

from drawing_intake.assisted_intake import (
    inspect_assisted_upload,
    manual_session_for_upload,
    select_assisted_candidate,
)
from drawing_intake.assisted_quote import (
    FIELD_LABELS,
    AssistedQuoteSession,
    AssistedQuoteStatus,
    ConfigurationValueOrigin,
    FieldAttentionKind,
    build_pricing_handoff_preview,
    confirm_configuration,
    local_form_availability,
    reject_drawing_proposal,
    review_assisted_quote,
    set_customer_value,
)
from plate_preview import render_plate_svg

st.set_page_config(page_title="Internal Drawing-Assisted Quote", layout="wide")

if os.environ.get("OPLATES_INTERNAL_DRAWING_PROTOTYPE") != "1":
    st.error(
        "This internal prototype is disabled. Set OPLATES_INTERNAL_DRAWING_PROTOTYPE=1 locally to run it."
    )
    st.stop()


PRODUCT = local_form_availability()
FORM_FIELD_ORDER = list(FIELD_LABELS)


def _reset_workflow() -> None:
    for key in list(st.session_state):
        if key.startswith("phase1f_"):
            del st.session_state[key]


def _install_session(session: AssistedQuoteSession) -> None:
    for key in list(st.session_state):
        if key.startswith("phase1f_field_"):
            del st.session_state[key]
    st.session_state.phase1f_session = session
    st.session_state.phase1f_handoff = None


def _value(session: AssistedQuoteSession, field: str) -> Any:
    state = session.configuration.get(field)
    return state.value if state else None


def _apply_widget_value(
    session: AssistedQuoteSession,
    field: str,
    widget_value: Any,
) -> AssistedQuoteSession:
    current = _value(session, field)
    if current == widget_value:
        return session
    return set_customer_value(session, field, widget_value)


def _source_caption(session: AssistedQuoteSession, field: str) -> None:
    state = session.configuration.get(field)
    if state and state.origin == ConfigurationValueOrigin.DRAWING:
        st.caption("Prefilled from drawing — review before confirming.")
    elif state and state.origin == ConfigurationValueOrigin.CUSTOMER:
        st.caption("Customer-entered value.")


st.title("Drawing-Assisted Quote — Internal Prototype")
st.info(
    "We've prefilled the information we could identify from your drawing. "
    "Please review the values and complete the remaining fields."
)
st.caption(
    "Local deterministic OCR only · in-memory upload · no pricing · no checkout · no order creation"
)

with st.expander(
    "1. Upload and analyze drawing", expanded="phase1f_session" not in st.session_state
):
    upload = st.file_uploader(
        "Drawing",
        type=["pdf", "png", "jpg", "jpeg"],
        help="The file is processed locally in memory and is not sent to an external service.",
    )
    left_action, right_action = st.columns([1, 4])
    with left_action:
        analyze = st.button("Analyze drawing", disabled=upload is None, type="primary")
    with right_action:
        if st.button("Start over"):
            _reset_workflow()
            st.rerun()

    if analyze and upload is not None:
        _reset_workflow()
        with st.spinner("Reading drawing locally…"):
            processed = inspect_assisted_upload(
                upload.getvalue(),
                upload.name,
                upload.type,
            )
        st.session_state.phase1f_upload = processed
        if len(processed.review.candidates) == 1:
            with st.spinner("Recognizing the selected plate…"):
                _install_session(
                    select_assisted_candidate(
                        processed,
                        processed.review.candidates[0].candidate_id,
                    )
                )
        elif not processed.review.candidates:
            _install_session(manual_session_for_upload(processed))


processed = st.session_state.get("phase1f_upload")
if processed is not None:
    review = processed.review
    active_session = st.session_state.get("phase1f_session")
    selection_complete = bool(
        active_session
        and active_session.source_sha256 == processed.document.sha256
        and active_session.selected_candidate_id
    )
    st.caption(
        f"Document: {review.document_class} · {len(review.candidates)} candidate(s) · "
        f"{review.processing_seconds:.2f}s classification"
    )
    if review.selection_required and not selection_complete:
        st.warning(
            "This drawing contains multiple plate candidates. Select one before populating the form."
        )
        option_by_id = {
            candidate.candidate_id: candidate for candidate in review.candidates
        }
        selected = st.selectbox(
            "Plate or schedule row",
            options=list(option_by_id),
            format_func=lambda value: option_by_id[value].label,
            key="phase1f_candidate_selection",
        )
        if st.button("Use selected plate", type="primary"):
            with st.spinner("Recognizing only the selected plate…"):
                _install_session(select_assisted_candidate(processed, selected))
            st.rerun()
    elif selection_complete:
        st.success(f"Selected candidate: {active_session.selected_candidate_id}")
    elif not review.quote_specific:
        st.warning(
            "This document does not identify one quote-specific plate. "
            "Continue with the normal manual configuration below."
        )


session: AssistedQuoteSession | None = st.session_state.get("phase1f_session")
if session is None:
    st.stop()

st.divider()
form_col, preview_col = st.columns([1.25, 1], gap="large")

with form_col:
    st.subheader("2. Review and complete configuration")
    session = st.session_state.phase1f_session

    c1, c2 = st.columns(2)
    with c1:
        quantity = st.number_input(
            "Quantity",
            min_value=1,
            step=1,
            value=_value(session, "quantity"),
            key="phase1f_field_quantity",
        )
        session = _apply_widget_value(session, "quantity", quantity)
        _source_caption(session, "quantity")
    with c2:
        material_options = [None, *PRODUCT.materials]
        material = st.selectbox(
            "Material",
            options=material_options,
            index=(
                material_options.index(_value(session, "material"))
                if _value(session, "material") in material_options
                else 0
            ),
            format_func=lambda value: "Select material" if value is None else value,
            key="phase1f_field_material",
        )
        session = _apply_widget_value(session, "material", material)
        _source_caption(session, "material")

    thickness_options = [
        None,
        *PRODUCT.thicknesses_by_material.get(str(material), []),
    ]
    current_thickness = _value(session, "thickness")
    if current_thickness not in thickness_options and current_thickness is not None:
        thickness_options.append(current_thickness)
    thickness = st.selectbox(
        "Plate thickness (in.)",
        options=thickness_options,
        index=(
            thickness_options.index(current_thickness)
            if current_thickness in thickness_options
            else 0
        ),
        format_func=lambda value: (
            "Select thickness" if value is None else f"{float(value):.3f}"
        ),
        key="phase1f_field_thickness",
    )
    session = _apply_widget_value(session, "thickness", thickness)
    _source_caption(session, "thickness")

    c1, c2 = st.columns(2)
    with c1:
        paddle = st.number_input(
            "Plate outside diameter (in.)",
            min_value=0.001,
            max_value=PRODUCT.max_paddle_dia_in,
            step=0.001,
            format="%.3f",
            value=_value(session, "paddle_dia"),
            key="phase1f_field_paddle_dia",
        )
        session = _apply_widget_value(session, "paddle_dia", paddle)
        _source_caption(session, "paddle_dia")
    with c2:
        bore = st.number_input(
            "Bore diameter (in.)",
            min_value=0.001,
            max_value=PRODUCT.max_bore_dia_in,
            step=0.001,
            format="%.3f",
            value=_value(session, "bore_dia"),
            key="phase1f_field_bore_dia",
        )
        session = _apply_widget_value(session, "bore_dia", bore)
        _source_caption(session, "bore_dia")

    c1, c2 = st.columns(2)
    with c1:
        handle_width = st.number_input(
            "Handle width (in.)",
            min_value=0.001,
            step=0.001,
            format="%.3f",
            value=_value(session, "handle_width"),
            key="phase1f_field_handle_width",
        )
        session = _apply_widget_value(session, "handle_width", handle_width)
    with c2:
        handle_length = st.number_input(
            "Handle length from bore center (in.)",
            min_value=0.001,
            step=0.001,
            format="%.3f",
            value=_value(session, "handle_length_from_bore"),
            key="phase1f_field_handle_length_from_bore",
        )
        session = _apply_widget_value(
            session,
            "handle_length_from_bore",
            handle_length,
        )

    tolerance_options = [None, *PRODUCT.tolerance_options_in]
    current_tolerance = _value(session, "bore_tolerance")
    tolerance = st.selectbox(
        "Bore tolerance (± in.)",
        options=tolerance_options,
        index=(
            tolerance_options.index(current_tolerance)
            if current_tolerance in tolerance_options
            else 0
        ),
        format_func=lambda value: (
            "Select tolerance" if value is None else f"±{value:.3f}"
        ),
        key="phase1f_field_bore_tolerance",
    )
    session = _apply_widget_value(session, "bore_tolerance", tolerance)
    _source_caption(session, "bore_tolerance")

    chamfer_options = [None, False, True]
    current_chamfer = _value(session, "chamfer")
    chamfer = st.selectbox(
        "Chamfer",
        options=chamfer_options,
        index=(
            chamfer_options.index(current_chamfer)
            if current_chamfer in chamfer_options
            else 0
        ),
        format_func=lambda value: (
            "Select" if value is None else ("Yes" if value else "No")
        ),
        key="phase1f_field_chamfer",
    )
    session = _apply_widget_value(session, "chamfer", chamfer)
    _source_caption(session, "chamfer")
    if chamfer is True:
        chamfer_width = st.number_input(
            "Chamfer Width (in.)",
            min_value=0.001,
            step=0.001,
            format="%.3f",
            value=_value(session, "chamfer_width"),
            key="phase1f_field_chamfer_width",
        )
        session = _apply_widget_value(session, "chamfer_width", chamfer_width)

    handle_label = st.text_input(
        "Handle marking (optional)",
        value=str(_value(session, "handle_label") or ""),
        max_chars=PRODUCT.max_handle_label_chars,
        key="phase1f_field_handle_label",
    )
    session = _apply_widget_value(session, "handle_label", handle_label or None)
    _source_caption(session, "handle_label")

    lead_options = [None, *PRODUCT.lead_times_days]
    current_lead = _value(session, "ships_in_days")
    lead_time = st.selectbox(
        "Lead time",
        options=lead_options,
        index=lead_options.index(current_lead) if current_lead in lead_options else 0,
        format_func=lambda value: (
            "Select lead time" if value is None else f"{value} calendar days"
        ),
        key="phase1f_field_ships_in_days",
    )
    session = _apply_widget_value(session, "ships_in_days", lead_time)
    st.session_state.phase1f_session = session

    review = review_assisted_quote(session)
    st.subheader("Still needs attention")
    blockers = [item for item in review.attention if item.blocks_readiness]
    warnings = [
        item for item in review.attention if item.kind == FieldAttentionKind.UNSUPPORTED
    ]
    if blockers:
        for item in blockers:
            st.warning(f"**{item.label}:** {item.message}")
    else:
        st.success("All required fields are present and valid.")
    for item in warnings:
        st.error(f"**{item.label}:** {item.message}")

    with st.expander("Drawing observations and source evidence"):
        if not session.proposals:
            st.write(
                "No quote-specific drawing proposals were available. Complete the form manually."
            )
        for proposal in session.proposals:
            if proposal.proposed_value is None and not proposal.competing_values:
                continue
            st.markdown(
                f"**{FIELD_LABELS.get(proposal.canonical_field or '', proposal.extraction_field)}** — "
                f"{proposal.raw_text or proposal.proposed_value or proposal.competing_values}"
            )
            source = (
                f"page {proposal.source_page}"
                if proposal.source_page
                else "page unavailable"
            )
            if proposal.source_bbox:
                source += (
                    f", bbox {tuple(round(value, 2) for value in proposal.source_bbox)}"
                )
            st.caption(f"Source: {source} · status: {proposal.validation_status}")
            if st.button(
                "Reject this drawing proposal",
                key=f"phase1f_reject_{proposal.extraction_field}",
            ):
                session = reject_drawing_proposal(
                    st.session_state.phase1f_session,
                    proposal.extraction_field,
                )
                if proposal.canonical_field:
                    st.session_state.pop(
                        f"phase1f_field_{proposal.canonical_field}", None
                    )
                st.session_state.phase1f_session = session
                st.session_state.phase1f_handoff = None
                st.rerun()

    confirmation_text = (
        "I have reviewed the dimensions and specifications above and confirm that they "
        "represent the part I want manufactured."
    )
    st.caption(confirmation_text)
    if st.button(
        "Confirm configuration",
        type="primary",
        disabled=bool(review.missing_required_fields or review.invalid_fields),
    ):
        try:
            session = confirm_configuration(session)
            st.session_state.phase1f_session = session
            st.session_state.phase1f_handoff = build_pricing_handoff_preview(session)
            st.success(
                "Configuration confirmed. Ready for the existing pricing workflow."
            )
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))

    review = review_assisted_quote(st.session_state.phase1f_session)
    if review.status == AssistedQuoteStatus.READY_FOR_PRICING:
        st.success(
            "Configuration complete · customer confirmed · ready for existing pricing workflow"
        )
        handoff = st.session_state.get(
            "phase1f_handoff"
        ) or build_pricing_handoff_preview(st.session_state.phase1f_session)
        st.json(handoff.quote_request)
        st.caption(
            "Preview only. No price was calculated and no checkout or order operation ran."
        )

with preview_col:
    st.subheader("Configuration Drawing")
    st.caption(
        "The preview reflects the editable configuration, not the uploaded drawing."
    )
    current = review_assisted_quote(st.session_state.phase1f_session).configuration
    geometry_fields = {
        "paddle_dia",
        "bore_dia",
        "handle_width",
        "handle_length_from_bore",
        "thickness",
        "material",
        "bore_tolerance",
        "chamfer",
    }
    if geometry_fields.issubset(current) and all(
        current[name] is not None for name in geometry_fields
    ):
        components.html(
            render_plate_svg(
                paddle_dia=float(current["paddle_dia"]),
                bore_dia=float(current["bore_dia"]),
                handle_width=float(current["handle_width"]),
                handle_length_from_bore=float(current["handle_length_from_bore"]),
                thickness=float(current["thickness"]),
                material=str(current["material"]),
                bore_tolerance=float(current["bore_tolerance"]),
                handle_label=str(current.get("handle_label") or "No label"),
                chamfer=bool(current["chamfer"]),
                chamfer_width=(
                    float(current["chamfer_width"])
                    if current.get("chamfer_width") is not None
                    else None
                ),
            ),
            height=430,
            scrolling=False,
        )
    else:
        st.info(
            "Complete the required geometry fields to display the existing O-Plates SVG preview."
        )

    st.subheader("Field status")
    current_session = st.session_state.phase1f_session
    current_review = review_assisted_quote(current_session)
    for field in FORM_FIELD_ORDER:
        state = current_session.configuration.get(field)
        if state:
            source = (
                "Prefilled from drawing"
                if state.origin == ConfigurationValueOrigin.DRAWING
                else "Customer-entered"
            )
            st.write(f"**{FIELD_LABELS.get(field, field)}:** {state.value} — {source}")
        elif field in current_review.missing_required_fields:
            st.write(f"**{FIELD_LABELS.get(field, field)}:** Needs your input")
