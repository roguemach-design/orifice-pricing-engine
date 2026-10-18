"""Download-only manufacturing workflow; automatic staging never runs on view."""

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
            and b.get("staging", {}).get("mode") == "AUTOMATIC"
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
                and b.get("staging", {}).get("mode") == "AUTOMATIC"
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
