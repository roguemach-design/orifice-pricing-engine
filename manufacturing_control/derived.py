"""Four shop files first; immutable supporting bundles remain in collapsed audit."""

from copy import deepcopy
from functools import partial
import json
import streamlit as st
from owner_portal_transport import DownloadAccess, PortalError, ERRORS
from packaging_generator import VERSION as PACKAGING_VERSION


def association(rev, plate):
    return dict(
        order_id=plate["order_id"],
        line_id=plate["line_id"],
        plate_id=plate["id"],
        revision_id=rev["id"],
        spec_sha256=rev["spec_sha256"],
        source_sha256=rev["source_sha256"],
    )


def download(client, bundle, artifact, label, *, audit=False):
    if "mc_download_access" not in st.session_state:
        st.session_state["mc_download_access"] = DownloadAccess(client)
    st.download_button(
        label,
        data=partial(
            st.session_state["mc_download_access"].load_derived,
            bundle["id"],
            deepcopy(artifact),
        ),
        file_name=artifact["filename"],
        mime=(
            "application/dxf"
            if artifact["name"].endswith(".dxf")
            else "application/octet-stream"
        ),
        on_click="ignore",
        width="stretch",
        key=f'mc_derived_{"audit" if audit else "shop"}_{bundle["id"]}_{artifact["name"]}',
    )


def reviewed_form(client, rev, plate, spec, latest):
    """Preserve measured values and the accepted contract; never infer blank size."""
    prefix = f'mc_haas_{rev["id"]}_'
    prior = next(
        (f for f in (latest or {}).get("files", []) if f["name"] == "inputs.json"), None
    )
    if prior and st.button("Load previous reviewed inputs", key=prefix + "load"):
        try:
            saved = json.loads(client.derived_artifact(latest["id"], prior))
            record = saved["record"]
            context = saved.get("setup_context") or {}
            for field in (
                "actual_blank_bore",
                "blank_radial_uncertainty",
                "reviewed_by",
                "review_reference",
            ):
                st.session_state[prefix + field] = record[field]
            st.session_state[prefix + "face"] = context.get("top_face_side")
            st.session_state[prefix + "orientation"] = context.get(
                "fixture_orientation_reference", ""
            )
            st.info(
                "Previous measured inputs loaded from verified stored bytes. Review them for this setup before generating again."
            )
        except (PortalError, ValueError, KeyError, TypeError) as error:
            st.error(
                ERRORS[error.category]
                if isinstance(error, PortalError)
                else "Previous reviewed inputs are unavailable."
            )
    st.caption(
        "Frozen dimensions, machine profile and strategy are supplied automatically. Confirm the measured blank and physical setup below."
    )
    blank = st.number_input(
        "Measured minimum blank bore (in)",
        value=None,
        format="%.5f",
        key=prefix + "actual_blank_bore",
    )
    uncertainty = st.number_input(
        "Blank radial uncertainty (in)",
        value=None,
        format="%.5f",
        key=prefix + "blank_radial_uncertainty",
    )
    reviewer = st.text_input("Reviewed by", key=prefix + "reviewed_by")
    reference = st.text_input("Review reference", key=prefix + "review_reference")
    face = st.selectbox(
        "Physical top face", [None, "upstream", "downstream"], key=prefix + "face"
    )
    orientation = st.text_input(
        "Fixture orientation reference", key=prefix + "orientation"
    )
    record = dict(
        schema_version="1",
        units="inch",
        job_id=plate["order_id"],
        part_id=spec["part_identifier"],
        drawing_revision=f'R{rev["number"]}',
        source_kind="manual",
        source_sha256=rev["spec_sha256"],
        reviewed_by=reviewer,
        review_reference=reference,
        finished_bore=spec["finished_bore_diameter"],
        bore_tolerance=spec["bore_tolerance"],
        actual_blank_bore=blank,
        blank_radial_uncertainty=uncertainty,
        thickness=spec["thickness"],
        material=spec["material"],
        top_chamfer_width=spec["chamfer_width"] if spec.get("chamfer") else 0,
    )
    if face is not None:
        record["setup_context"] = dict(
            top_face_side=face, fixture_orientation_reference=orientation
        )
    return record


def show(client, rev, plate, current, approved, *, frozen_audit=None):
    bundles, config, parent = [], None, None
    if all(rev.get(k) for k in ("id", "spec_sha256", "source_sha256")):
        parent = association(rev, plate)
        try:
            config = client.json("/admin/manufacturing/configuration")
            bundles = client.manufacturing_post(
                "/admin/manufacturing/bundles/query", parent
            )
        except PortalError as error:
            config = None
            st.info(
                "Internal manufacturing files unavailable: " + ERRORS[error.category]
            )
    else:
        st.caption(
            "Historical revision lacks complete parent identity. Original files remain available under their existing gates."
        )
    try:
        spec = json.loads(rev["spec_json"])
        if not isinstance(spec, dict):
            raise ValueError("invalid specification")
    except (ValueError, KeyError, TypeError):
        spec, config = {}, None
        st.info(
            "Frozen specification unavailable. Generation is blocked; your revision selection is kept."
        )
    for family, title, output, button, warning in (
        (
            "HAAS",
            "Haas bore program",
            "program.NC",
            "NC",
            "ENGINEERING REVIEW · Programmer review, setup verification and physical prove-out required. The accepted NC safety stops remain in place.",
        ),
        (
            "PACKAGING",
            "Corrugated packaging",
            "packaging.dxf",
            "Packaging DXF",
            "PROTOTYPE / ENGINEERING REVIEW · Cardboard cutting, folding, closure and shipping acceptance remain required.",
        ),
    ):
        found = sorted(
            (b for b in bundles if b["family"] == family),
            key=lambda b: (b["created_at"], b["id"]),
        )
        latest = found[-1] if found else None
        # Historical bundles remain in audit; never present them as current shop files.
        with st.container(border=True, key=f'mc_card_derived_{rev["id"]}_{family}'):
            st.markdown("**" + title + "**")
            st.caption(
                f'R{rev["number"]} · '
                + (
                    "Current Frozen Plate revision"
                    if current
                    else "Superseded revision · audit only"
                )
            )
            st.caption(warning)
            artifact = next(
                (f for f in (latest or {}).get("files", []) if f["name"] == output),
                None,
            )
            if current and artifact:
                st.write(artifact["filename"])
                st.caption(
                    latest["state"]
                    + " · "
                    + latest["generator_version"]
                    + " · Integrity checked on download"
                )
                if (
                    family == "PACKAGING"
                    and latest["generator_version"] != PACKAGING_VERSION
                ):
                    st.info(
                        "Earlier packaging layout retained. Regenerate for the center-panel cutout and perforated folds."
                    )
                download(client, latest, artifact, "Download " + button)
            elif current:
                st.caption("Not generated for this revision.")
            if config is None:
                st.caption(
                    "Generation unavailable until the manufacturing service is available."
                )
            elif not (current and approved):
                st.caption(
                    "Generation requires the current exact customer-approved PDF/spec revision."
                )
            else:
                action = ("Regenerate " if latest else "Generate ") + button
                with st.expander(action, expanded=False):
                    # Reuse is an explicit verified read, outside the generation form.
                    if family == "HAAS":
                        record = reviewed_form(client, rev, plate, spec, latest)
                    else:
                        record = None
                        st.caption(
                            "Uses the stored packaging profile automatically. No per-order packaging dimensions are required."
                        )
                    with st.form(f'mc_generate_{rev["id"]}_{family}'):
                        acknowledge = st.checkbox(
                            "I understand this creates an internal review/prototype file only."
                        )
                        generate = st.form_submit_button(action, type="primary")
                        if generate and not acknowledge:
                            st.error(
                                "Acknowledge the review/prototype status before generating."
                            )
                        if generate and acknowledge:
                            try:
                                client.manufacturing_post(
                                    "/admin/manufacturing/bundles",
                                    dict(
                                        parent=parent,
                                        family=family,
                                        reviewed_record=record,
                                    ),
                                )
                                st.rerun()
                            except PortalError as error:
                                st.error(ERRORS[error.category])
    with st.expander("Engineering details / audit files", expanded=False):
        if frozen_audit:
            frozen_audit()
        if config:
            with st.expander("Stored generator profiles", expanded=False):
                for name in (
                    "machine_profile",
                    "machining_parameters",
                    "packaging_configuration",
                ):
                    st.markdown("**" + name.replace("_", " ").capitalize() + "**")
                    st.json(config[name])
        st.caption(
            "All stored bundles are immutable. Downloads retrieve verified stored bytes, including historical outputs; generation never releases manufacturing."
        )
        with st.expander(f"Generation history ({len(bundles)})", expanded=False):
            for bundle in reversed(bundles):
                with st.expander(
                    f'{bundle["family"]} · {bundle["created_at"]} · {bundle["id"][:8]}',
                    expanded=False,
                ):
                    st.caption(bundle["generator_version"] + " · " + bundle["state"])
                    for artifact in bundle["files"]:
                        download(
                            client,
                            bundle,
                            artifact,
                            "Download " + artifact["name"],
                            audit=True,
                        )
                    st.json(bundle)
