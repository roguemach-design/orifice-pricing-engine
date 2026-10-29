"""Owner-only pricing editor. All writes go to the existing pricing API."""

import copy
import hashlib
import json

import streamlit as st
from pricing_configuration import changes

LABELS = {
    "precision_bore_allowance_per_in": "Precision bore commercial allowance · $ / bore diameter inch",
    "chamfer_allowance_per_in": "Chamfer commercial allowance · $ / bore diameter inch",
    "today_2_day_multiplier": "Today / 2-Day · future multiplier (Coming Soon; unavailable)",
    "material_enabled": "Material availability",
    "thickness_enabled_by_material": "Thickness availability by material",
    "price_per_sq_in": "Material price · $ / square inch",
    "lead_time_enabled": "Lead-time availability · days",
    "lead_time_multipliers": "Effective lead-time multipliers",
    "default_lead_time_days": "Default lead time · days",
    "laser_per_linear_in": "Laser cost · $ / linear inch",
    "mill_labor_per_hr": "Shop labor rate · $ / hour",
    "mill_speed_ipm": "Bore machining speed · inches / minute",
    "chamfer_speed_ipm": "Chamfer speed · inches / minute",
    "load_time_mins": "Load time · minutes",
    "inspection_mins_by_tol": "Inspection minutes by tolerance · inches",
    "density_lb_per_in3": "Density · lb / cubic inch",
    "max_paddle_dia_in": "Maximum plate diameter · inches",
    "max_bore_dia_in": "Maximum bore diameter · inches",
    "max_handle_label_chars": "Maximum handle marking · characters",
}


def discard():
    for key in list(st.session_state):
        if str(key).startswith("mc_price_"):
            del st.session_state[key]


def edit_map(label, value, prefix, unsupported=()):
    result = copy.deepcopy(value)
    st.markdown("**" + label + "**")
    for key, current in value.items():
        widget = prefix + "_" + str(key)
        if isinstance(current, dict):
            with st.expander(str(key), expanded=prefix == "mc_price_prices"):
                result[key] = edit_map("", current, widget)
        elif type(current) is bool:
            result[key] = st.checkbox(
                str(key), value=current, key=widget, disabled=key in unsupported
            )
        else:
            result[key] = st.number_input(
                str(key), value=float(current), min_value=0.0, format="%.6f", key=widget
            )
    return result


def run(client):
    st.title("Pricing & Availability")
    workspace = st.radio(
        "Pricing workspace", ["Pricing settings", "Checkout Control"],
        key="mc_pricing_workspace", horizontal=True,
    )
    if workspace == "Checkout Control":
        # Independent control: no pricing fetch/save is required, even on outage.
        from .checkout import run as checkout_control
        checkout_control(client)
        return
    st.caption(
        "One active configuration · Changes affect future calculations. Historical order and approval evidence stays unchanged."
    )
    if "mc_price_snapshot" not in st.session_state:
        st.session_state["mc_price_snapshot"] = client.json("/admin/config/editor")
    snapshot = st.session_state["mc_price_snapshot"]
    original = snapshot["config"]
    draft = copy.deepcopy(original)
    st.caption("Current configuration version: " + snapshot["version"])
    st.info(
        "Changes remain unsaved until you review the before/after summary, confirm, and select Save Changes."
    )
    tabs = st.tabs(
        [
            "Availability",
            "Material prices",
            "Process & discounts",
            "Weights & limits",
            "Recovery",
        ]
    )
    with tabs[0]:
        for key in (
            "material_enabled",
            "thickness_enabled_by_material",
            "lead_time_enabled",
        ):
            unsupported = (
                tuple(
                    k
                    for k in original[key]
                    if k not in original["lead_time_multipliers"]
                )
                if key == "lead_time_enabled"
                else ()
            )
            draft[key] = edit_map(
                LABELS[key], original[key], "mc_price_" + key, unsupported
            )
        st.caption(
            "Lead times without a supported runtime multiplier cannot be enabled here."
        )
        draft["default_lead_time_days"] = st.number_input(
            LABELS["default_lead_time_days"],
            min_value=1,
            value=int(original["default_lead_time_days"]),
            key="mc_price_default",
        )
    with tabs[1]:
        draft["price_per_sq_in"] = edit_map(
            LABELS["price_per_sq_in"], original["price_per_sq_in"], "mc_price_prices"
        )
    with tabs[2]:
        rates, timing = st.columns(2, gap="large")
        with rates:
            st.subheader("Shop & cutting rates")
            for key in ("mill_labor_per_hr", "laser_per_linear_in",
                        "precision_bore_allowance_per_in", "chamfer_allowance_per_in",
                        "today_2_day_multiplier"):
                draft[key] = st.number_input(
                    LABELS[key],
                    value=float(original[key]),
                    min_value=0.0,
                    format="%.4f",
                    key="mc_price_" + key,
                )
            st.subheader("Effective lead-time multipliers")
            draft["lead_time_multipliers"] = edit_map(
                "Days → effective multiplier",
                original["lead_time_multipliers"],
                "mc_price_lead_time_multipliers",
            )
        with timing:
            st.subheader("Machining & handling times")
            for key in ("mill_speed_ipm", "chamfer_speed_ipm", "load_time_mins"):
                draft[key] = st.number_input(
                    LABELS[key],
                    value=float(original[key]),
                    min_value=0.0,
                    format="%.4f",
                    key="mc_price_" + key,
                )
            draft["inspection_mins_by_tol"] = edit_map(
                LABELS["inspection_mins_by_tol"],
                original["inspection_mins_by_tol"],
                "mc_price_inspection_mins_by_tol",
            )
        st.markdown("**Quantity discount tiers**")
        st.caption(
            "Start at quantity 1; quantities increase and multipliers decrease. A multiplier of 0.97 means 3% off."
        )
        # Keep the editor's input stable while its row deltas are mounted. When
        # navigation removes the widget, seed its next mount from ordinary draft
        # rows, never by assigning to the read-only data_editor widget key.
        if "mc_price_tiers" not in st.session_state:
            st.session_state["mc_price_tiers_input"] = copy.deepcopy(
                st.session_state.get("mc_price_tiers_draft", original["qty_discount_tiers"])
            )
        draft["qty_discount_tiers"] = st.data_editor(
            st.session_state["mc_price_tiers_input"], num_rows="dynamic", key="mc_price_tiers"
        )
        st.session_state["mc_price_tiers_draft"] = copy.deepcopy(draft["qty_discount_tiers"])
    with tabs[3]:
        draft["density_lb_per_in3"] = edit_map(
            LABELS["density_lb_per_in3"],
            original["density_lb_per_in3"],
            "mc_price_density",
        )
        for key in ("max_paddle_dia_in", "max_bore_dia_in"):
            draft[key] = st.number_input(
                LABELS[key],
                value=float(original[key]),
                min_value=0.0,
                key="mc_price_" + key,
            )
        draft["max_handle_label_chars"] = st.number_input(
            LABELS["max_handle_label_chars"],
            value=int(original["max_handle_label_chars"]),
            min_value=1,
            key="mc_price_chars",
        )
        st.markdown("**Stored weight multipliers · inactive**")
        st.caption(
            "The current formula does not use these values. They are preserved as read-only records."
        )
        st.json(original["weight_multiplier_by_material"])
    delta = changes(original, draft)
    st.session_state["mc_price_dirty"] = bool(delta)
    if delta:
        st.warning(
            "Unsaved changes. Keep this session open until you save or discard them. Switching workspace preserves the draft."
        )
        st.subheader("Review changes")
        st.dataframe(
            [
                {
                    "Setting": r["setting"],
                    "Before": str(r["before"]),
                    "After": str(r["after"]),
                }
                for r in delta
            ],
            hide_index=True,
            width="stretch",
        )
    digest = hashlib.sha256(
        json.dumps(draft, sort_keys=True, default=str).encode()
    ).hexdigest()[:16]
    confirmed = st.checkbox(
        "I reviewed these changes and understand that future prices or availability may change.",
        key="mc_price_confirm_" + digest,
    )
    if st.button("Save Changes", type="primary", disabled=not delta or not confirmed):
        result = client.config_write(
            "save",
            {**draft, "_version": snapshot["version"], "_confirmation": "SAVE CHANGES"},
        )
        if result:
            discard()
            st.session_state["mc_price_notice"] = (
                "Changes saved. The prior configuration is available in Recovery."
            )
            st.rerun()
    if st.session_state.get("mc_price_notice"):
        st.success(st.session_state.pop("mc_price_notice"))
    discard_ok = st.checkbox(
        "Discard my unsaved changes and reload the current configuration",
        key="mc_price_discard_ok",
    )
    if st.button("Reload configuration", disabled=bool(delta) and not discard_ok):
        discard()
        st.rerun()
    with tabs[4]:
        st.warning(
            "Reset and restore change active prices or availability. Review every difference before confirming. Each successful action preserves the previous configuration."
        )
        action = st.selectbox(
            "Recovery action",
            ["Restore saved configuration", "Reset to defaults"],
            key="mc_price_recovery_action",
        )
        target, history_id = None, None
        if action == "Reset to defaults":
            target = snapshot["defaults"]
            phrase, operation = "RESET DEFAULTS", "reset"
        else:
            history = snapshot["history"]
            if history:
                history_id = st.selectbox(
                    "Prior configuration",
                    [h["id"] for h in history],
                    format_func=lambda i: next(
                        h["saved_at"] for h in history if h["id"] == i
                    ),
                    key="mc_price_history",
                )
                target = next(h["config"] for h in history if h["id"] == history_id)
            else:
                st.caption(
                    "No recovery snapshots yet. The first successful save will preserve the previous configuration."
                )
            phrase, operation = "RESTORE CONFIGURATION", "restore"
        if target is not None:
            diff = changes(original, target)
            st.dataframe(
                [
                    {
                        "Setting": r["setting"],
                        "Before": str(r["before"]),
                        "After": str(r["after"]),
                    }
                    for r in diff
                ],
                hide_index=True,
                width="stretch",
            )
            typed = st.text_input(
                "Type " + phrase + " to confirm",
                key="mc_price_recovery_" + operation + str(history_id),
            )
            if st.button(
                "Apply recovery action", disabled=typed != phrase or bool(delta)
            ):
                if client.config_write(
                    operation,
                    {
                        "_version": snapshot["version"],
                        "_confirmation": phrase,
                        "history_id": history_id,
                    },
                ):
                    discard()
                    st.session_state["mc_price_notice"] = (
                        "Recovery completed. The previous configuration was preserved."
                    )
                    st.rerun()
        st.caption(
            "Resolve unsaved edits before recovery. Latest 50 recovery snapshots are shown; older snapshots remain in the database."
        )
