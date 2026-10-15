"""Additive review/prototype controls. No physical acceptance or release actions."""

from copy import deepcopy
from functools import partial
import json
import streamlit as st
from owner_portal_transport import DownloadAccess, PortalError, ERRORS


def association(rev, plate):
    return dict(
        order_id=plate["order_id"],
        line_id=plate["line_id"],
        plate_id=plate["id"],
        revision_id=rev["id"],
        spec_sha256=rev["spec_sha256"],
        source_sha256=rev["source_sha256"],
    )


def show(client, rev, plate, current, approved):
    if not all(rev.get(k) for k in ("id", "spec_sha256", "source_sha256")):
        st.caption(
            "Derived tools unavailable: historical revision lacks complete parent identity. Original files remain available under their existing gates."
        )
        return
    parent = association(rev, plate)
    # No bundle generation on view. Server configuration may be disabled during rollout.
    try:
        config = client.json("/admin/manufacturing/configuration")
        bundles = client.manufacturing_post(
            "/admin/manufacturing/bundles/query", parent
        )
    except PortalError as error:
        st.caption("Derived manufacturing tools unavailable: " + ERRORS[error.category])
        return
    spec = json.loads(rev["spec_json"])
    for family, title, warning in (
        (
            "HAAS",
            "Haas bore program · REVIEW ONLY",
            "Programmer review, verified machine/setup and physical prove-out remain required. No machine transmission or manufacturing release.",
        ),
        (
            "PACKAGING",
            "Corrugated packaging · PROTOTYPE",
            "Board, fold, closure and shipping acceptance remain required. Not approved for shipping.",
        ),
    ):
        with st.container(border=True, key=f'mc_card_derived_{rev["id"]}_{family}'):
            st.markdown("**" + title + "**")
            st.warning(warning)
            found = [b for b in bundles if b["family"] == family]
            st.caption(
                f'R{rev["number"]} · {len(found)} stored bundles · '
                + ("Current revision" if current else "Historical audit")
            )
            with st.expander("Generation inputs and profile"):
                if family == "PACKAGING":
                    st.json(config["packaging_configuration"])
                else:
                    st.json(config["machine_profile"])
                    st.json(config["machining_parameters"])
            if current and approved:
                with st.form(f'mc_generate_{rev["id"]}_{family}'):
                    record = None
                    if family == "HAAS":
                        st.caption(
                            "Enter measured/reviewed inputs. Frozen dimensions and revision identity are bound automatically."
                        )
                        blank = st.number_input(
                            "Measured minimum blank bore (in)",
                            value=None,
                            format="%.5f",
                        )
                        uncertainty = st.number_input(
                            "Blank radial uncertainty (in)", value=None, format="%.5f"
                        )
                        reviewer = st.text_input("Reviewed by")
                        reference = st.text_input("Review reference")
                        face = st.selectbox(
                            "Physical top face", [None, "upstream", "downstream"]
                        )
                        orientation = st.text_input("Fixture orientation reference")
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
                            top_chamfer_width=(
                                spec["chamfer_width"] if spec.get("chamfer") else 0
                            ),
                        )
                        if face is not None:
                            record["setup_context"] = dict(
                                top_face_side=face,
                                fixture_orientation_reference=orientation,
                            )
                    acknowledge = st.checkbox(
                        "I understand this creates an internal review/prototype bundle only."
                    )
                    generate = st.form_submit_button(
                        (
                            "Generate review bundle"
                            if family == "HAAS"
                            else "Generate packaging prototype"
                        ),
                    )
                    if generate and not acknowledge:
                        st.error("Acknowledge the review/prototype status before generating.")
                    if generate and acknowledge:
                        try:
                            client.manufacturing_post(
                                "/admin/manufacturing/bundles",
                                dict(
                                    parent=parent, family=family, reviewed_record=record
                                ),
                            )
                            st.rerun()
                        except PortalError as error:
                            st.error(ERRORS[error.category])
            else:
                st.caption(
                    "New generation requires the current exact customer-approved revision."
                )
            for bundle in reversed(found):
                st.caption(
                    bundle["generator_version"]
                    + " · "
                    + bundle["state"]
                    + " · Bundle "
                    + bundle["id"]
                )
                if "mc_download_access" not in st.session_state:
                    st.session_state["mc_download_access"] = DownloadAccess(client)
                for artifact in bundle["files"]:
                    st.download_button(
                        "Download " + artifact["name"],
                        data=partial(
                            st.session_state["mc_download_access"].load_derived,
                            bundle["id"],
                            deepcopy(artifact),
                        ),
                        file_name=artifact["filename"],
                        mime="application/octet-stream",
                        on_click="ignore",
                        key=f'mc_derived_{bundle["id"]}_{artifact["name"]}',
                    )
                with st.expander(
                    "Identity, hashes and review evidence · " + bundle["id"][:8]
                ):
                    st.json(bundle)
