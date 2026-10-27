"""Owner engineering actions and verified downloads; passive views never generate."""

import json
from copy import deepcopy
from functools import partial
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


def download(client, bundle, artifact, label, *, audit=False):
    if "mc_download_access" not in st.session_state:
        st.session_state["mc_download_access"] = DownloadAccess(client)
    st.download_button(
        label,
        data=partial(
            st.session_state["mc_download_access"].load_derived,
            bundle["id"],
            deepcopy(artifact),
            historical=audit,
        ),
        file_name=artifact["filename"],
        help=artifact["filename"],
        mime=(
            "application/dxf"
            if artifact["name"].endswith(".dxf")
            else "application/octet-stream"
        ),
        on_click="ignore",
        width="stretch",
        key=f'mc_derived_{"audit" if audit else "shop"}_{bundle["id"]}_{artifact["name"]}',
    )


def show(
    client, rev, plate, current, approved, *, frozen_audit=None, include_audit=True
):
    bundles, config, staging = [], None, {}
    try:
        test_order = json.loads(rev.get("source_json") or "{}").get("_payment", {}).get("mode") == "owner_test"
    except (ValueError, TypeError):
        test_order = False
    if test_order:
        st.info("TEST / NOT A REAL SALE: automatic staging is intentionally excluded. Owner engineering generation never releases production.")
        engineering_confirmed = st.checkbox(
            "I confirm TEST engineering review only; no manufacturing or shipping authorization.",
            key="mc_test_engineering_confirm_" + rev["id"],
        )
    if all(rev.get(k) for k in ("id", "spec_sha256", "source_sha256")):
        try:
            config = client.json("/admin/manufacturing/configuration")
            bundles = client.manufacturing_post(
                "/admin/manufacturing/bundles/query", association(rev, plate)
            )
            staging = client.json("/admin/manufacturing/staging/" + rev["id"])
        except PortalError as error:
            st.info(
                "Internal manufacturing files unavailable: " + ERRORS[error.category]
            )
    else:
        st.caption(
            "Historical revision lacks complete parent identity. Original files remain available under their existing gates."
        )
    for family, title, output, label, warning in (
        (
            "HAAS",
            "Haas bore program",
            "program.NC",
            "Download NC",
            "REVIEW / SETUP VERIFICATION REQUIRED · Not machine-proven or released.",
        ),
        (
            "PACKAGING",
            "Corrugated packaging",
            "packaging.dxf",
            "Download Packaging DXF",
            "PROTOTYPE / ENGINEERING REVIEW · Not physically qualified for shipping.",
        ),
    ):
        expected = (config or {}).get("staging_profiles", {}).get(family)
        found = [
            b
            for b in bundles
            if b["family"] == family
            and b.get("staging", {}).get("mode") == ("OWNER_TEST_ENGINEERING" if test_order else "AUTOMATIC")
            and expected
            and b["staging"].get("profile_sha256") == expected
        ]
        # Preserve access to immutable earlier packaging after a prospective
        # generator upgrade. Never substitute earlier HAAS machine profiles.
        retained_packaging = False
        if family == "PACKAGING" and not found:
            found = [
                b
                for b in bundles
                if b["family"] == family
                and b.get("staging", {}).get("mode") == ("OWNER_TEST_ENGINEERING" if test_order else "AUTOMATIC")
            ]
            retained_packaging = bool(found)
        latest = max(found, key=lambda b: (b["created_at"], b["id"])) if found else None
        if retained_packaging:
            st.caption(
                "Retained packaging prototype: "
                + str(latest.get("generator_version", "earlier version"))
                + ". Existing bytes are unchanged; new geometry requires a new derived bundle."
            )
        with st.container(border=True, key=f'mc_card_derived_{rev["id"]}_{family}'):
            label_col, action_col = st.columns([1.45, 1], gap="small")
            with label_col:
                st.markdown("**" + title + "**")
                st.caption(warning)
            with action_col:
                if test_order:
                    st.caption("NOT MACHINE-PROVEN / REVIEW REQUIRED" if family == "HAAS"
                               else "PROTOTYPE / NOT QUALIFIED FOR SHIPPING")
                    if st.button("Generate TEST " + ("Haas NC" if family == "HAAS" else "Packaging DXF"),
                                 key=f"mc_test_generate_{rev['id']}_{family}",
                                 disabled=not (current and approved and config and engineering_confirmed),
                                 width="stretch"):
                        try:
                            generated = client.manufacturing_post(
                                "/admin/manufacturing/test-engineering",
                                dict(parent=association(rev, plate), family=family, confirmed=True),
                            )
                            bundles = [b for b in bundles if b["id"] != generated["id"]] + [generated]
                            latest = generated
                            st.success("Generated · immutable verified TEST engineering bundle")
                            st.session_state.pop(f"mc_test_result_{rev['id']}_{family}", None)
                        except PortalError as error:
                            st.session_state[f"mc_test_result_{rev['id']}_{family}"] = ERRORS[error.category]
                    failure = st.session_state.get(f"mc_test_result_{rev['id']}_{family}")
                    if failure:
                        st.warning("Blocked / unavailable: " + failure)
                artifact = next(
                    (f for f in (latest or {}).get("files", []) if f["name"] == output),
                    None,
                )
                if current and approved and artifact:
                    download(client, latest, artifact, label)
                elif not (current and approved):
                    st.button(
                        label,
                        disabled=True,
                        key=f"mc_derived_locked_{rev['id']}_{family}",
                        width="stretch",
                    )
                    st.caption(
                        "Available only for the current customer-approved Frozen Plate revision. Historical files remain in audit."
                    )
                else:
                    st.button(
                        label,
                        disabled=True,
                        key=f"mc_derived_missing_{rev['id']}_{family}",
                        width="stretch",
                    )
                    if test_order:
                        st.info("Not generated for the active controlled profile. Use the explicit owner action above after approval.")
                        continue
                    state = staging.get(family, {})
                    st.info(state.get("state", "Automatic staging pending"))
                    st.caption(
                        state.get(
                            "detail",
                            "Files are staged automatically after approval. Refresh to check readiness; this view does not generate files.",
                        )
                    )
    if include_audit:
        with st.expander("Engineering details / audit files", expanded=False):
            if frozen_audit:
                frozen_audit()
            audit_details(client, config, bundles)
    return config, bundles


def audit_details(client, config, bundles):
    if config:
        with st.expander(
            "Controlled machine / fixture / generator profiles", expanded=False
        ):
            for name in (
                "machine_profile",
                "fixture_profile",
                "machining_parameters",
                "packaging_configuration",
            ):
                if name in config:
                    st.markdown("**" + name.replace("_", " ").capitalize() + "**")
                    st.json(config[name])
    st.caption(
        "Stored artifacts are immutable. Historical audit downloads retrieve verified stored bytes. No download regenerates a file or releases manufacturing."
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
