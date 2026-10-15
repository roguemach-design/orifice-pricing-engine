"""Manufacturing Control. A read-only presentation of existing immutable evidence."""

from datetime import datetime, timezone
from html import escape
import json
import math
import os
from pathlib import Path
from urllib.parse import quote

import streamlit as st
from frozen_plate.control_data import approved
from frozen_plate.download_names import dxf_delivery_name
from frozen_plate.runtime import ui_enabled
from .client import (
    OwnerClient,
    PortalError,
    ERRORS,
    clear_owner_session,
    DownloadAccess,
    download_callable,
)


def html(value):
    st.markdown(value, unsafe_allow_html=True)


def text(value):
    return escape(str(value)) if value is not None and value != "" else "Unavailable"


def stamp(value):
    if not value:
        return "Not recorded"
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).strftime(
            "%b %d, %Y · %H:%M UTC"
        )
    except (ValueError, AttributeError):
        return "Timestamp unavailable"


def chip(label, kind=""):
    return f'<span class="mc-chip {kind}">{text(label)}</span>'


def mode_chip(mode):
    return chip(
        "Mode unknown" if mode not in ("LIVE", "TEST", "OWNER TEST") else mode,
        "test" if mode in ("TEST", "OWNER TEST") else "live" if mode == "LIVE" else "",
    )


def pairs(values):
    html(
        '<div class="mc-kv">'
        + "".join(
            f"<span>{text(k)}</span><strong>{text(v)}</strong>" for k, v in values
        )
        + "</div>"
    )


def show_error(error):
    st.error(ERRORS[error.category])
    if error.category == "conflict":
        st.caption(
            "The API combines supersession, missing evidence and integrity conflicts. It does not expose a more specific reason."
        )


def unlock():
    st.session_state["mc_key"] = st.session_state.get(
        "owner_admin_credential", ""
    ).strip()
    st.session_state["owner_admin_credential"] = ""


def lock():
    clear_owner_session(st.session_state)


def refresh():
    for key in list(st.session_state):
        if str(key).startswith(
            ("mc_snapshot", "mc_inventory", "mc_verified", "mc_email")
        ):
            del st.session_state[key]


def open_order(order_id):
    st.session_state["mc_order"] = order_id
    st.session_state["mc_nav"] = "Orders"


def nav_to(value):
    st.session_state["mc_nav"] = value
    st.session_state.pop("mc_order", None)


def table(rows, headings):
    html(
        '<table class="mc-table"><thead><tr>'
        + "".join(f"<th>{text(h)}</th>" for h in headings)
        + "</tr></thead><tbody>"
        + "".join(
            "<tr>"
            + "".join(
                f'<td data-label="{text(h)}">{text(v)}</td>'
                for h, v in zip(headings, row)
            )
            + "</tr>"
            for row in rows
        )
        + "</tbody></table>"
    )


def row_approval(order):
    lines = order.get("lines", [])
    if not lines:
        return "Record unavailable"
    return f"{sum(l['approved'] for l in lines)} of {len(lines)} records approved"


def scope(snapshot):
    st.warning("Partial scope · " + snapshot["scope"])
    st.caption(
        "Snapshot "
        + stamp(snapshot["snapshot_at"])
        + ". Filters and pagination apply only to this loaded snapshot. Counts are line records, not manufacturing releases. Email reconciliation is loaded per revision on request."
    )


def overview(snapshot):
    st.title("Overview")
    st.caption(
        "Where every plate stands between customer approval and routing. Nothing here changes a record."
    )
    scope(snapshot)
    counts = snapshot["counts"]
    metrics = [
        (
            "Awaiting customer approval",
            counts["awaiting_approval"],
            "Current revision metadata; not yet approved",
        ),
        (
            "Approved · current revision",
            counts["approved"],
            "Matching PDF/spec approval evidence; files not yet verified",
        ),
        (
            "Ready for release",
            counts["ready_for_release"],
            "Stored routing readiness only — not released",
        ),
        (
            "Sourcing recorded",
            counts["sourcing_recorded"],
            "Line records with review notes; never sent",
        ),
        ("HOLD tracking", "—", "Unavailable: no durable HOLD reason is stored"),
        (
            "Email needs reconciliation",
            "—",
            "Load provider evidence on the selected revision",
        ),
    ]
    html(
        '<div class="mc-grid">'
        + "".join(
            f'<div class="mc-metric"><div>{text(title)}</div><div class="mc-number">{text(n)}</div><div class="mc-muted">{text(desc)}</div></div>'
            for title, n, desc in metrics
        )
        + "</div>"
    )
    left, right = st.columns([1, 1.4], gap="medium")
    with left, st.container(border=True, key="mc_card_attention"):
        st.subheader("Needs attention")
        attention = [
            o
            for o in snapshot["orders"]
            if not o["lines"] or any(not l["approved"] for l in o["lines"])
        ]
        if not attention:
            st.caption(
                "No approval or missing-record issues within this snapshot. Email status has not been checked."
            )
        for order in attention[:6]:
            html(
                chip(
                    "Record unavailable" if not order["lines"] else "Review approval",
                    "wait",
                )
            )
            st.button(
                order.get("order_number_display") or order["id"],
                key="mc_attention_" + order["id"],
                on_click=open_order,
                args=(order["id"],),
                width="stretch",
            )
    with right, st.container(border=True, key="mc_card_recent"):
        st.subheader("Recent completed orders")
        for order in snapshot["orders"][:5]:
            html(mode_chip(order.get("payment_mode")) + chip(row_approval(order)))
            st.button(
                order.get("order_number_display") or order["id"],
                key="mc_recent_" + order["id"],
                on_click=open_order,
                args=(order["id"],),
                width="stretch",
            )
        if not snapshot["orders"]:
            st.info("No completed orders within the latest 200 records.")
        st.button(
            "View all loaded orders", on_click=nav_to, args=("Orders",), width="stretch"
        )


def orders_workspace(snapshot, *, sourcing=False):
    st.title("Sourcing records" if sourcing else "Orders")
    scope(snapshot)
    search = st.text_input(
        "Search by order number, customer or identifiers", key="mc_search"
    )
    f1, f2, f3, f4 = st.columns(4)
    with f1:
        status = st.selectbox(
            "Approval",
            ["All", "Approved", "Awaiting approval", "Record unavailable"],
            key="mc_filter_approval",
        )
    with f2:
        mode = st.selectbox(
            "Payment mode",
            ["All", "LIVE", "TEST", "OWNER TEST", "UNKNOWN"],
            key="mc_filter_mode",
        )
    materials = sorted(
        {
            str(l["material"])
            for o in snapshot["orders"]
            for l in o["lines"]
            if l.get("material")
        }
    )
    with f3:
        material = st.selectbox(
            "Material", ["All"] + materials, key="mc_filter_material"
        )
    thicknesses = sorted(
        {
            str(l["thickness"])
            for o in snapshot["orders"]
            for l in o["lines"]
            if l.get("thickness") is not None
        }
    )
    with f4:
        thickness = st.selectbox(
            "Thickness (in)", ["All"] + thicknesses, key="mc_filter_thickness"
        )
    date_from = st.date_input(
        "Created on or after (optional)", value=None, key="mc_filter_date"
    )

    def matches(order):
        lines = order["lines"]
        if mode != "All" and mode != order.get("payment_mode", "UNKNOWN"):
            return False
        if material != "All" and not any(l["material"] == material for l in lines):
            return False
        if thickness != "All" and not any(
            str(l["thickness"]) == thickness for l in lines
        ):
            return False
        if date_from and (order.get("created_at") or "")[:10] < date_from.isoformat():
            return False
        if sourcing and not any(l["sourcing_count"] for l in lines):
            return False
        if status == "Approved" and not (lines and all(l["approved"] for l in lines)):
            return False
        if status == "Awaiting approval" and not any(
            l["metadata_available"] and not l["approved"] for l in lines
        ):
            return False
        if (
            status == "Record unavailable"
            and lines
            and all(l["metadata_available"] for l in lines)
        ):
            return False
        return True

    rows = [o for o in snapshot["orders"] if matches(o)]
    filter_key = (search, status, mode, material, thickness, str(date_from), sourcing)
    if st.session_state.get("mc_filter_signature") != filter_key:
        st.session_state["mc_page"] = 1
        st.session_state["mc_filter_signature"] = filter_key
    pages = max(1, math.ceil(len(rows) / 10))
    page = min(st.session_state.get("mc_page", 1), pages)
    st.session_state["mc_page"] = page
    if not rows:
        st.info("No records match these filters within the loaded snapshot.")
    for order in rows[(page - 1) * 10 : page * 10]:
        with st.container(border=True, key=f"mc_card_order_{order['id']}"):
            html(
                mode_chip(order.get("payment_mode"))
                + chip(
                    row_approval(order),
                    (
                        "good"
                        if order["lines"] and all(l["approved"] for l in order["lines"])
                        else ""
                    ),
                )
            )
            st.button(
                order.get("order_number_display") or order["id"],
                key="mc_open_" + order["id"],
                on_click=open_order,
                args=(order["id"],),
                width="stretch",
            )
            st.caption(
                stamp(order.get("created_at"))
                + " · "
                + (order.get("customer_email") or "Customer unavailable")
            )
            table(
                [
                    (
                        l["line_id"],
                        l["material"],
                        l["thickness"],
                        l["quantity"],
                        (
                            f"R{l['revision_number']}"
                            if l["revision_number"]
                            else "Unavailable"
                        ),
                        (
                            "Approved"
                            if l["approved"]
                            else (
                                "Awaiting approval"
                                if l["metadata_available"]
                                else "Record unavailable"
                            )
                        ),
                    )
                    for l in order["lines"]
                ],
                [
                    "Line",
                    "Material",
                    "Thickness (in)",
                    "Quantity",
                    "Current",
                    "Approval",
                ],
            )
            if not order["lines"]:
                st.caption(
                    "Manufacturing record unavailable. Viewing does not create a record."
                )
    st.caption(
        f"Showing {(page-1)*10+1 if rows else 0}–{min(page*10,len(rows))} of {len(rows)} matching orders in this snapshot"
    )
    st.number_input("Page", min_value=1, max_value=pages, step=1, key="mc_page")


def inventory_workspace(client):
    st.title("Frozen Plates")
    st.caption(
        "Latest 200 Frozen Plate records, independent of the order snapshot. An order outside the snapshot is not proof of a missing order."
    )
    if "mc_inventory" not in st.session_state:
        st.session_state["mc_inventory"] = client.json("/admin/frozen-plates")
    plates = st.session_state["mc_inventory"]
    q = st.text_input(
        "Search plate, order ID or line", key="mc_plate_search"
    ).casefold()
    for plate in plates:
        if (
            q
            not in " ".join(
                str(plate.get(k, "")) for k in ("id", "order_id", "line_id")
            ).casefold()
        ):
            continue
        with st.container(border=True, key=f"mc_card_plate_{plate['id']}"):
            st.subheader(plate["line_id"])
            st.caption("Plate " + plate["id"])
            st.caption("Order " + plate["order_id"])
            st.button(
                "Review order and revisions",
                key="mc_plate_" + plate["id"],
                on_click=open_order,
                args=(plate["order_id"],),
            )
    if not plates:
        st.info("No Frozen Plate records available.")


def frozen_spec(rev):
    try:
        spec = json.loads(rev["spec_json"])
        return spec if isinstance(spec, dict) else {}
    except (ValueError, TypeError, KeyError):
        return {}


def files(client, rev, plate, order, is_current, is_approved):
    st.subheader(f"Manufacturing files · R{rev['number']}")
    st.caption(
        "Downloads verify exact stored bytes against Frozen Plate SHA-256 and byte length before delivery."
    )
    spec = frozen_spec(rev)
    for kind, title, desc in [
        (
            "pdf",
            "Finished-part drawing · PDF",
            "Finished geometry · customer confirmation drawing",
        ),
        (
            "dxf",
            "Rough-blank cut file · DXF",
            "Bore 0.125 in undersize on diameter (0.0625 in per side)",
        ),
    ]:
        artifact = rev.get("artifacts", {}).get(kind)
        with st.container(border=True, key=f"mc_card_file_{rev['id']}_{kind}"):
            st.markdown("**" + title + "**")
            st.caption(desc)
            if not artifact:
                st.caption("Artifact metadata unavailable.")
                continue
            st.caption(f"{artifact['size']:,} bytes · Integrity checked on download")
            if kind == "dxf" and not (is_current and is_approved):
                st.button("DXF locked", disabled=True, key="mc_locked_" + rev["id"])
                st.caption(
                    "Superseded revision — historical review only."
                    if not is_current
                    else "Current revision awaits matching customer PDF/spec approval."
                )
                continue
            filename = artifact["filename"]
            if kind == "dxf":
                try:
                    filename = dxf_delivery_name(
                        spec,
                        order.get("order_number_display"),
                        plate["line_id"],
                        rev["number"],
                    )
                except ValueError:
                    st.caption(
                        "Authoritative delivery name unavailable. Stored file is unchanged; DXF download blocked."
                    )
                    continue
            st.write(filename)
            if "mc_download_access" not in st.session_state:
                st.session_state["mc_download_access"] = DownloadAccess(client)
            st.download_button(
                "Download " + kind.upper(),
                data=download_callable(
                    st.session_state["mc_download_access"], rev, kind, filename
                ),
                file_name=filename,
                mime={
                    "pdf": "application/pdf",
                    "dxf": "application/dxf",
                    "json": "application/json",
                }[kind],
                key=f"mc_save_{rev['id']}_{kind}",
                type="primary" if kind == "dxf" else "secondary",
                on_click="ignore",
                width="stretch",
            )
    st.caption(
        "Approval and metadata alone do not verify file bytes. Downloads do not release manufacturing."
    )


def history(client, detail):
    rev = detail["revision"]
    with st.container(border=True, key=f"mc_card_history_{rev['id']}"):
        st.subheader(f"Revision history · R{rev['number']}")
        events = [(rev.get("created_at"), "Revision created", rev.get("reason"))]
        for a in detail.get("approvals", []):
            events.append(
                (
                    a.get("approved_at"),
                    "Customer drawing approved",
                    (
                        "Exact PDF/spec match"
                        if approved(rev, [a])
                        else "Approval evidence does not match"
                    ),
                )
            )
        for d in detail.get("deliveries", []):
            events.append(
                (
                    d.get("generated_at"),
                    "Confirmation email captured",
                    "Stored copy; not proof of sending",
                )
            )
        for s in detail.get("sourcing", []):
            events.append(
                (s.get("selected_at"), "Sourcing recorded for review", s.get("route"))
            )
        for when, title, desc in sorted(events, key=lambda e: e[0] or "", reverse=True):
            html(
                f'<div class="mc-evidence"><strong>{text(title)}</strong><div class="mc-muted">{text(stamp(when))} · {text(desc)}</div></div>'
            )
        if st.button("Load email provider evidence", key="mc_email_load_" + rev["id"]):
            try:
                with st.spinner("Checking email evidence…"):
                    st.session_state["mc_email_" + rev["id"]] = client.json(
                        f"/admin/frozen-plates/revisions/{rev['id']}/email-status"
                    )
            except PortalError as error:
                show_error(error)
        status = st.session_state.get("mc_email_" + rev["id"])
        if status:
            state = status.get("state")
            labels = {
                "NOT_ATTEMPTED": "Not attempted — no send attempt recorded",
                "PROVIDER_ACCEPTED": "Accepted by email provider — not proof of inbox delivery",
                "RECONCILIATION_REQUIRED": "Needs reconciliation — send outcome uncertain; check the provider",
            }
            st.info(labels.get(state, "Email provider evidence unavailable"))
        st.caption(
            "Provider evidence verification may read stored artifacts. Captured email content is not displayed because it can contain a bearer approval link."
        )


def line_detail(client, plate, order):
    revisions = client.json(
        f"/admin/frozen-plates/{quote(plate['id'],safe='')}/revisions"
    )
    if not revisions:
        st.info(
            plate["line_id"]
            + " · Revision record unavailable. Nothing is generated by viewing."
        )
        return
    revisions.sort(key=lambda r: r["number"], reverse=True)
    rid = st.selectbox(
        "Revision · " + plate["line_id"],
        [r["id"] for r in revisions],
        format_func=lambda i: next(
            f"R{r['number']} · {'Current' if i==plate['current_revision'] else 'Superseded'}"
            for r in revisions
            if r["id"] == i
        ),
        key="mc_revision_" + plate["id"],
    )
    detail = client.json(
        f"/admin/frozen-plates/{quote(plate['id'],safe='')}",
        params={"revision_id": rid},
    )
    rev = detail.get("revision")
    if not rev:
        st.info("Revision record unavailable.")
        return
    current = rid == detail["plate"]["current_revision"]
    is_approved = approved(rev, detail.get("approvals", []))
    spec = frozen_spec(rev)
    with st.container(border=True, key=f"mc_card_line_{rev['id']}"):
        html(
            f'<div class="mc-row"><h3>{text(plate["line_id"].replace("line-","Line "))}</h3>'
            + chip(
                f"{'Current' if current else 'Superseded'} R{rev['number']}",
                "current" if current else "",
            )
            + chip(
                "Approved" if is_approved else "Awaiting approval",
                "good" if is_approved else "wait",
            )
            + "</div>"
        )
        if not current:
            st.warning(
                f"Viewing historical R{rev['number']}. Current revision differs. DXF is blocked."
            )
        vals = [
            ("Material", spec.get("material")),
            ("Thickness", f"{spec['thickness']} in" if spec.get("thickness") else None),
            ("Quantity", spec.get("quantity")),
            ("Finished OD", spec.get("finished_od")),
            ("Finished bore", spec.get("finished_bore_diameter")),
            (
                "Handle · C/L to end × width",
                (
                    f"{spec['centerline_to_handle_end']} × {spec['handle_width']} in"
                    if all(
                        k in spec for k in ("centerline_to_handle_end", "handle_width")
                    )
                    else None
                ),
            ),
            ("Bore tolerance", spec.get("bore_tolerance")),
            (
                "Chamfer",
                (
                    "No"
                    if spec.get("chamfer") is False
                    else (
                        f"Yes · {spec.get('chamfer_width')} in"
                        if spec.get("chamfer") is True and spec.get("chamfer_width")
                        else "Unspecified"
                    )
                ),
            ),
            ("Handle hole", "Yes" if spec.get("handle_hole_enabled") else "No"),
        ]
        html(
            '<div class="mc-specs">'
            + "".join(
                f'<div><div class="mc-label">{text(k)}</div><div class="mc-value">{text(v)}</div></div>'
                for k, v in vals
            )
            + "</div>"
        )
        st.caption(
            f"Values from frozen R{rev['number']} specification. Dimensions in inches; not the editable order payload."
        )
        if is_approved:
            matches = [a for a in detail.get("approvals", []) if approved(rev, [a])]
            html(
                '<div class="mc-approved">Customer approved this exact PDF and specification · '
                + text(stamp(matches[0].get("approved_at")))
                + "</div>"
            )
        files(client, rev, plate, order, current, is_approved)
        from .derived import show as derived_files

        derived_files(
            client,
            rev,
            plate,
            current,
            is_approved,
            frozen_audit=lambda: frozen_audit_files(client, rev, plate),
        )
    history(client, detail)
    with st.container(border=True, key=f"mc_card_source_{rev['id']}"):
        st.subheader(f"Sourcing · R{rev['number']}")
        html(chip("Not released"))
        sources = sorted(
            detail.get("sourcing", []),
            key=lambda s: s.get("selected_at") or "",
            reverse=True,
        )
        if not sources:
            st.info("No sourcing records for this revision.")
        for source in sources:
            pairs(
                [
                    ("Route", source.get("route")),
                    ("State", source.get("selection_status")),
                    ("Recorded", stamp(source.get("selected_at"))),
                ]
            )
        st.caption(
            "Recorded for review only. Several routes may be present. Nothing is sent to SendCutSend, Alro or Rogue Internal from this portal."
        )


def frozen_audit_files(client, rev, plate):
    # Explicit field allowlist excludes object locations, tokens, fingerprints and audit payloads.
    pairs(
        [
            ("Plate ID", plate["id"]),
            ("Revision ID", rev["id"]),
            ("Spec SHA-256", rev.get("spec_sha256")),
            ("Source SHA-256", rev.get("source_sha256")),
            ("Generator", rev.get("generator_version")),
            ("Geometry", rev.get("geometry_version")),
            ("Spec schema", rev.get("spec_schema")),
        ]
    )
    for kind, a in rev.get("artifacts", {}).items():
        st.markdown("**" + kind.upper() + " · original stored file**")
        st.code(
            f"{a['filename']}\n{a['size']} bytes\nSHA-256 {a['sha256']}",
            language=None,
        )
    with st.expander("Frozen canonical specification"):
        st.json(frozen_spec(rev))
    artifact = rev.get("artifacts", {}).get("json")
    if artifact:
        if "mc_download_access" not in st.session_state:
            st.session_state["mc_download_access"] = DownloadAccess(client)
        st.download_button(
            "Download JSON",
            data=download_callable(
                st.session_state["mc_download_access"],
                rev,
                "json",
                artifact["filename"],
            ),
            file_name=artifact["filename"],
            mime="application/json",
            on_click="ignore",
            key="mc_save_" + rev["id"] + "_json",
        )


def order_detail(client, order_id, snapshot):
    st.button("← Orders", on_click=nav_to, args=("Orders",))
    try:
        order = client.json("/admin/orders/" + quote(order_id, safe=""))
    except PortalError as error:
        if error.category != "missing":
            raise
        order = {"id": order_id}
        st.info(
            "No matching order record. Existing Frozen Plate evidence remains reviewable; order details are unavailable."
        )
    plates = client.json("/admin/frozen-plates", params={"order_id": order_id})
    st.title(order.get("order_number_display") or "Frozen Plate review")
    mode = order.get("payment_mode", "UNKNOWN")
    html(
        mode_chip(mode)
        + chip(order.get("status", "Order record unavailable").capitalize())
    )
    if mode in ("TEST", "OWNER TEST"):
        html(
            '<div class="mc-banner"><strong>'
            + text(mode)
            + " order.</strong> Not a LIVE charge. Approved means the customer approved the drawing — not charged LIVE, shipped or released to manufacturing.</div>"
        )
    archived = bool(order.get("owner_archived_at"))
    if archived:
        html(chip("Archived"))
        st.caption(
            "Archived "
            + stamp(order["owner_archived_at"])
            + " · organizational only; manufacturing history retained"
        )
    if order.get("status") == "completed" or mode in ("TEST", "OWNER TEST"):
        if st.button(
            "Unarchive order" if archived else "Archive order", key="mc_archive_action"
        ):
            try:
                client.archive(order_id, not archived)
                refresh()
                st.rerun()
            except PortalError as error:
                show_error(error)
    st.caption(
        "Created "
        + stamp(order.get("created_at"))
        + " · Paid "
        + stamp(order.get("paid_at"))
    )
    main, aside = st.columns([2.2, 1], gap="medium")
    with main:
        if not plates:
            st.info(
                "Manufacturing record unavailable. No files exist to download. Viewing does not create one. This is not a stored HOLD."
            )
        for plate in plates:
            try:
                line_detail(client, plate, order)
            except PortalError as error:
                show_error(error)
    with aside:
        with st.container(border=True, key="mc_card_order_record"):
            st.subheader("Order record")
            pairs(
                [
                    ("Order", order.get("order_number_display")),
                    ("Status", order.get("status")),
                    ("Payment mode", mode),
                    ("Created", stamp(order.get("created_at"))),
                    ("Paid", stamp(order.get("paid_at"))),
                ]
            )
        with st.container(border=True, key="mc_card_customer"):
            st.subheader("Customer")
            st.caption("Customer contact from the order record")
            st.write(order.get("customer_email") or "Email not provided")
        with st.container(border=True, key="mc_card_shipping"):
            st.subheader("Shipping")
            address = order.get("shipping_address")
            if isinstance(address, dict) and address:
                st.write(order.get("shipping_name") or "Recipient not provided")
                for field in (
                    "line1",
                    "line2",
                    "city",
                    "state",
                    "postal_code",
                    "country",
                ):
                    if address.get(field):
                        st.write(str(address[field]))
            else:
                st.write("Not provided on this order.")
            st.caption(
                "Service: " + str(order.get("shipping_service") or "Not provided")
            )
            st.caption("Tracking, labels and fulfillment are not part of this portal.")
        with st.container(border=True, key="mc_card_totals"):
            st.subheader("Order totals")

            def money(k):
                value = order.get(k)
                return (
                    f"${value:,.2f}"
                    if isinstance(value, (float, int))
                    else "Unavailable"
                )

            pairs(
                [
                    ("Subtotal", money("amount_subtotal_usd")),
                    ("Shipping", money("amount_shipping_usd")),
                    ("Total", money("amount_total_usd")),
                ]
            )
            st.caption("Order-level totals only. Per-line prices are not split out.")


def run():
    st.set_page_config(
        page_title="O-Plates · Manufacturing Control",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    html("<style>" + Path(__file__).with_name("style.css").read_text() + "</style>")
    html(
        '<div class="mc-top"><span class="mc-mark">RM</span><div><div class="mc-brand">ROGUE MACHINE / O-PLATES</div><div class="mc-title">Manufacturing Control</div></div><span class="mc-session">Review-only &nbsp; · &nbsp; Owner session · shared key</span></div>'
    )
    if not ui_enabled():
        st.error("Owner portal environment binding is unavailable.")
        return
    if not st.session_state.get("mc_key"):
        with st.container(border=True, key="mc_card_unlock"):
            st.title("Manufacturing Control")
            st.write(
                "Internal review portal. Enter the owner credential to load orders."
            )
            with st.form("mc_unlock_form"):
                st.text_input(
                    "Internal admin credential",
                    type="password",
                    key="owner_admin_credential",
                )
                st.form_submit_button(
                    "Unlock", on_click=unlock, type="primary", width="stretch"
                )
            st.caption(
                "Held only in this browser session. Never saved to the address bar or local storage. No order data loads until unlocked."
            )
        return
    with st.sidebar:
        st.caption("ROGUE MACHINE / O-PLATES")
        st.subheader("Manufacturing Control")
        st.radio(
            "Workspace",
            ["Overview", "Orders", "Frozen Plates", "Sourcing records"],
            key="mc_nav",
            label_visibility="collapsed",
        )
        st.radio(
            "Orders visibility", ["Active", "Archived", "All"], key="mc_archive_view"
        )
        st.button("Lock", on_click=lock, width="stretch")
        st.caption("Owner session · shared key")
        st.divider()
        st.markdown("**Manufacturing review only**")
        st.caption(
            "Viewing never approves, regenerates, emails, records sourcing, submits to a vendor or releases manufacturing."
        )
        st.caption(
            "Order archive is organizational only. Pricing settings remain in the separate legacy admin."
        )
    st.button("Refresh", on_click=refresh)
    client = OwnerClient(os.environ.get("API_BASE", ""), st.session_state["mc_key"])
    try:
        archive_view = st.session_state.get("mc_archive_view", "Active")
        nav = st.session_state.get("mc_nav", "Overview")
        search = (
            st.session_state.get("mc_search", "")
            if nav in ("Orders", "Sourcing records")
            else ""
        )
        signature = (archive_view, search)
        if st.session_state.get("mc_snapshot_signature") != signature:
            st.session_state.pop("mc_snapshot", None)
            st.session_state["mc_snapshot_signature"] = signature
        if "mc_snapshot" not in st.session_state:
            with st.spinner(
                "Loading order metadata… Files are not fetched until requested."
            ):
                st.session_state["mc_snapshot"] = client.json(
                    "/admin/manufacturing-summary",
                    params={"archive_view": archive_view, "q": search},
                )
        snapshot = st.session_state["mc_snapshot"]
        selected = st.session_state.get("mc_order")
        nav = st.session_state.get("mc_nav", "Overview")
        if selected and nav == "Orders":
            order_detail(client, selected, snapshot)
        elif nav == "Overview":
            overview(snapshot)
        elif nav == "Frozen Plates":
            inventory_workspace(client)
        else:
            orders_workspace(snapshot, sourcing=nav == "Sourcing records")
    except PortalError as error:
        show_error(error)
        st.button("Try again", on_click=refresh)
