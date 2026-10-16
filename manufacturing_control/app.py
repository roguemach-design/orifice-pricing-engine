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
    st.query_params.clear()


def refresh():
    for key in list(st.session_state):
        if str(key).startswith(
            ("mc_snapshot", "mc_inventory", "mc_verified", "mc_email")
        ):
            del st.session_state[key]


def open_order(order_id):
    st.session_state["mc_order"] = order_id
    st.session_state["mc_nav"] = "Orders"
    st.query_params.clear()


def nav_to(value):
    st.session_state["mc_nav"] = value
    st.session_state.pop("mc_order", None)
    sync_navigation()


def open_plate(plate_id):
    st.session_state["mc_plate"] = plate_id
    st.session_state["mc_nav"] = "Frozen Plates"
    sync_navigation()


def sync_navigation():
    # Selection only; credentials and customer details never enter the URL.
    st.query_params.clear()
    if st.session_state.get("mc_nav") == "Frozen Plates" and st.session_state.get(
        "mc_plate"
    ):
        st.query_params["plate"] = st.session_state["mc_plate"]


def order_table(orders, key):
    """Compact selectable rows; server callbacks retain owner authorization."""
    with st.container(key="mc_table_" + key):
        cols = st.columns([1.1, 1.8, 1, 0.8, 0.6, 1.4, 0.8])
        for col, label in zip(
            cols,
            [
                "Order",
                "Customer",
                "Date",
                "Mode",
                "Plates",
                "Drawing approval",
                "Archive",
            ],
        ):
            col.markdown("**" + label + "**")
        for order in orders:
            cols = st.columns([1.1, 1.8, 1, 0.8, 0.6, 1.4, 0.8])
            cols[0].button(
                order.get("order_number_display") or order["id"],
                key=key + order["id"],
                on_click=open_order,
                args=(order["id"],),
                width="stretch",
            )
            for col, value in zip(
                cols[1:],
                [
                    order.get("customer_email") or "Unavailable",
                    (order.get("created_at") or "")[:10] or "Unavailable",
                    order.get("payment_mode") or "UNKNOWN",
                    str(len(order.get("lines", []))),
                    row_approval(order),
                    "Archived" if order.get("owner_archived_at") else "Active",
                ],
            ):
                col.write(value)


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
    st.caption(
        "Scope: "
        + snapshot["scope"]
        + " · "
        + stamp(snapshot["snapshot_at"])
        + ". Filters cover this bounded snapshot."
    )


def overview(snapshot):
    st.title("Rogue Command Center")
    st.caption(
        "Where every plate stands between customer approval and routing. Nothing here changes a record."
    )
    scope(snapshot)
    counts = snapshot["counts"]
    metrics = [
        (
            "Recent orders",
            len(snapshot["orders"]),
            "Completed orders in the loaded scope",
        ),
        (
            "Awaiting customer approval",
            sum(
                any(l["metadata_available"] and not l["approved"] for l in o["lines"])
                for o in snapshot["orders"]
            ),
            "Orders with an unapproved current plate",
        ),
        (
            "Approved Frozen Plates",
            counts["approved"],
            "Current PDF/spec approval evidence",
        ),
        (
            "Owner attention",
            sum(
                not o["lines"]
                or any(
                    not l["metadata_available"] or not l["approved"] for l in o["lines"]
                )
                for o in snapshot["orders"]
            ),
            "Missing records or approval outstanding",
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
    st.subheader("Recent orders")
    order_table(snapshot["orders"][:6], "mc_recent_")
    st.button("View all loaded orders", on_click=nav_to, args=("Orders",))
    with st.expander("Owner attention · approval and missing records", expanded=True):
        attention = [
            o
            for o in snapshot["orders"]
            if not o["lines"]
            or any(not l["approved"] or not l["metadata_available"] for l in o["lines"])
        ]
        if attention:
            table(
                [
                    (o.get("order_number_display") or o["id"], row_approval(o))
                    for o in attention[:6]
                ],
                ["Order", "Review needed"],
            )
        else:
            st.caption("No missing-record or approval issues in this scope.")
    st.caption(
        "File readiness is checked against stored artifact metadata in each plate workspace. Approval alone is not file verification or manufacturing release."
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
    sorting = st.selectbox(
        "Sort orders",
        ["Newest first", "Oldest first", "Order number", "Customer"],
        key="mc_order_sort",
    )
    rows.sort(
        key=lambda o: (
            str(o.get("order_number_display") or o["id"])
            if sorting == "Order number"
            else (
                str(o.get("customer_email") or "")
                if sorting == "Customer"
                else str(o.get("created_at") or "")
            )
        ),
        reverse=sorting == "Newest first",
    )
    order_table(rows[(page - 1) * 10 : page * 10], "mc_open_")
    if sourcing:
        st.caption(
            "Rows contain stored sourcing evidence. Open an order's Sourcing section to review exact revision associations."
        )
    st.caption(
        f"Showing {(page-1)*10+1 if rows else 0}–{min(page*10,len(rows))} of {len(rows)} matching orders in this snapshot"
    )
    st.number_input("Page", min_value=1, max_value=pages, step=1, key="mc_page")


def inventory_workspace(client):
    st.title("Frozen Plates")
    if st.session_state.get("mc_plate"):
        plate_id = st.session_state["mc_plate"]
        detail = client.json("/admin/frozen-plates/" + quote(plate_id, safe=""))
        plate = detail["plate"]
        if st.button("← Plate inventory"):
            st.session_state.pop("mc_plate", None)
            sync_navigation()
            st.rerun()
        st.caption("Plate " + plate["id"] + " · " + plate["line_id"])
        order = {"id": plate["order_id"]}
        try:
            order = client.json("/admin/orders/" + quote(plate["order_id"], safe=""))
        except PortalError as error:
            if error.category != "missing":
                raise
            st.info(
                "Associated order unavailable. Stored plate evidence remains accessible."
            )
        st.button(
            "View Associated Order", on_click=open_order, args=(plate["order_id"],)
        )
        line_detail(client, plate, order)
        return
    st.caption(
        "Independent plate inventory · latest 200 records. Viewing never creates records or regenerates files."
    )
    if "mc_inventory" not in st.session_state:
        st.session_state["mc_inventory"] = client.json("/admin/frozen-plates")
    q = st.text_input(
        "Search plate, order ID or line", key="mc_plate_search"
    ).casefold()
    plates = [
        p
        for p in st.session_state["mc_inventory"]
        if q
        in " ".join(str(p.get(k, "")) for k in ("id", "order_id", "line_id")).casefold()
    ]
    pages = max(1, math.ceil(len(plates) / 10))
    page = st.number_input("Inventory page", min_value=1, max_value=pages, value=1)
    for plate in plates[(page - 1) * 10 : page * 10]:
        detail = client.json("/admin/frozen-plates/" + quote(plate["id"], safe=""))
        rev = detail.get("revision")
        cols = st.columns([1.1, 2, 2, 0.7, 1.2])
        cols[0].button(
            plate["line_id"],
            key="mc_plate_" + plate["id"],
            on_click=open_plate,
            args=(plate["id"],),
            width="stretch",
        )
        cols[1].caption("Plate " + plate["id"])
        cols[2].caption("Order " + plate["order_id"])
        cols[3].write(f"R{rev['number']}" if rev else "Unavailable")
        cols[4].write(
            "Approved"
            if rev and approved(rev, detail.get("approvals", []))
            else "Awaiting approval" if rev else "Revision unavailable"
        )
    st.caption(
        f"{len(plates)} matching plates · select a line to review its exact revisions"
    )


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
            "Exact stored customer drawing",
        ),
        (
            "json",
            "Frozen Plate specification · JSON",
            "Exact stored immutable revision record",
        ),
        (
            "dxf",
            "Rough-blank steel cut file · DXF",
            "Rough bore · 0.125 in diametral allowance",
        ),
    ]:
        artifact = rev.get("artifacts", {}).get(kind)
        with st.container(border=True, key=f"mc_card_file_{rev['id']}_{kind}"):
            label_col, action_col = st.columns([1.45, 1], gap="small")
            with label_col:
                st.markdown("**" + title + "**")
                st.caption(desc)
            with action_col:
                if not artifact:
                    st.button(
                        "Download " + kind.upper(),
                        disabled=True,
                        key=f"mc_missing_{rev['id']}_{kind}",
                        width="stretch",
                    )
                    st.caption("Artifact metadata unavailable.")
                    continue

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
                if "mc_download_access" not in st.session_state:
                    st.session_state["mc_download_access"] = DownloadAccess(client)
                st.download_button(
                    "Download " + kind.upper(),
                    data=download_callable(
                        st.session_state["mc_download_access"], rev, kind, filename
                    ),
                    file_name=filename,
                    help=filename,
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
        index=next(
            (
                i
                for i, r in enumerate(revisions)
                if r["id"] == plate["current_revision"]
            ),
            0,
        ),
        key="mc_revision_" + plate["id"],
        label_visibility="collapsed",
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
    with st.container(key="mc_workspace"):
        file_col, info_col = st.columns([1, 1.35], gap="medium")
        with file_col, st.container(key="mc_files"):
            files(client, rev, plate, order, current, is_approved)
            from .derived import show as derived_files

            config, bundles = derived_files(
                client, rev, plate, current, is_approved, include_audit=False
            )
        with info_col:
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
                    (
                        "Thickness",
                        f"{spec['thickness']} in" if spec.get("thickness") else None,
                    ),
                    ("Quantity", spec.get("quantity")),
                    ("Finished OD", spec.get("finished_od")),
                    ("Finished bore", spec.get("finished_bore_diameter")),
                    (
                        "Handle · C/L to end × width",
                        (
                            f"{spec['centerline_to_handle_end']} × {spec['handle_width']} in"
                            if all(
                                k in spec
                                for k in ("centerline_to_handle_end", "handle_width")
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
                                if spec.get("chamfer") is True
                                and spec.get("chamfer_width")
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
                    matches = [
                        a for a in detail.get("approvals", []) if approved(rev, [a])
                    ]
                    html(
                        '<div class="mc-approved">Customer approved this exact PDF and specification · '
                        + text(stamp(matches[0].get("approved_at")))
                        + "</div>"
                    )
            with st.expander("Revision history & customer approval evidence"):
                history(client, detail)
            with st.expander(f"Sourcing · R{rev['number']}"):
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

            with st.expander("Manufacturing specification & audit evidence"):
                frozen_audit_files(client, rev, plate)
                from .derived import audit_details

                audit_details(client, config, bundles)


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


def order_detail(client, order_id, snapshot):
    st.sidebar.button("← Orders", on_click=nav_to, args=("Orders",))
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
    mode = order.get("payment_mode", "UNKNOWN")
    html(
        '<div class="mc-row"><h1>'
        + text(order.get("order_number_display") or "Frozen Plate review")
        + "</h1>"
        + mode_chip(mode)
        + chip(str(order.get("status") or "Order record unavailable").capitalize())
        + "</div>"
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
    if not plates:
        st.info(
            "Manufacturing record unavailable. Viewing does not create records or files."
        )
    else:
        if len(plates) == 1:
            selected = plates[0]["id"]
        else:
            selected = st.selectbox(
                "Plate / line",
                [p["id"] for p in plates],
                format_func=lambda i: next(
                    p["line_id"] + " · " + p["id"] for p in plates if p["id"] == i
                ),
                key="mc_line_" + order_id,
            )
        line_detail(client, next(p for p in plates if p["id"] == selected), order)
    with st.expander("Organize order · archive"):
        if order.get("status") == "completed" or mode in ("TEST", "OWNER TEST"):
            if st.button(
                "Unarchive order" if archived else "Archive order",
                key="mc_archive_action",
            ):
                try:
                    client.archive(order_id, not archived)
                    refresh()
                    st.rerun()
                except PortalError as error:
                    show_error(error)
    with st.expander("Order record"):
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
    with st.expander("Customer"):
        st.subheader("Customer")
        st.caption("Customer contact from the order record")
        st.write(order.get("customer_email") or "Email not provided")
    with st.expander("Shipping"):
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
        st.caption("Service: " + str(order.get("shipping_service") or "Not provided"))
        st.caption("Tracking, labels and fulfillment are not part of this portal.")
    with st.expander("Order totals"):
        st.subheader("Order totals")

        def money(k):
            value = order.get(k)
            return (
                f"${value:,.2f}" if isinstance(value, (float, int)) else "Unavailable"
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
        '<div class="mc-top"><span class="mc-mark">RM</span><div><div class="mc-brand">ROGUE MACHINE / O-PLATES</div><div class="mc-title">Manufacturing Control</div></div><span class="mc-session">Owner operations &nbsp; · &nbsp; Owner session · shared key</span></div>'
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
    if "mc_nav" not in st.session_state and st.query_params.get("plate"):
        st.session_state["mc_nav"] = "Frozen Plates"
        st.session_state["mc_plate"] = st.query_params["plate"]
    # Preserve pricing widgets while another workspace is rendered.
    for key in list(st.session_state):
        if str(key).startswith("mc_price_"):
            st.session_state[key] = st.session_state[key]
    with st.sidebar:
        st.caption("ROGUE MACHINE / O-PLATES")
        st.subheader("Manufacturing Control")
        st.radio(
            "Workspace",
            [
                "Overview",
                "Orders",
                "Frozen Plates",
                "Sourcing records",
                "Pricing & Availability",
            ],
            key="mc_nav",
            on_change=sync_navigation,
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
            "Order archive is organizational only. Pricing changes require explicit review and confirmation."
        )
    if (
        st.session_state.get("mc_price_dirty")
        and st.session_state.get("mc_nav") != "Pricing & Availability"
    ):
        st.warning(
            "Unsaved Pricing & Availability changes are retained in this session. Return there to save or discard before closing."
        )
    st.sidebar.button("Refresh", on_click=refresh, width="stretch")
    client = OwnerClient(os.environ.get("API_BASE", ""), st.session_state["mc_key"])
    try:
        if st.session_state.get("mc_nav") == "Pricing & Availability":
            from .pricing import run as pricing_workspace

            pricing_workspace(client)
            return
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
