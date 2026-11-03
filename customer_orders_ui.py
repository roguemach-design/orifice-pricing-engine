"""Customer order history and the exact stored approved PDF; no owner permissions."""

from datetime import datetime
from hashlib import sha256
from io import BytesIO
from html import escape
from pathlib import Path
from urllib.parse import quote

import pypdfium2 as pdfium
import requests
import streamlit as st

from auth import api_get, api_post
from customer_orders_state import clear_orders_state
from customer_safety import customer_product_details, service_message
from frozen_plate.presentation import APPROVAL_COPY, BUTTON


def money(value):
    return "Not recorded" if value is None else f"${value:,.2f}"


def stamp(value):
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).strftime(
            "%b %d, %Y · %H:%M UTC"
        )
    except (AttributeError, ValueError):
        return "Date not recorded"


def purchased_details(spec):
    details = customer_product_details(spec)
    for key, label in {
        "chamfer_angle_degrees": "Chamfer angle (degrees)",
        "chamfer_side": "Chamfer face",
        "flow_orientation": "Section flow orientation",
        "chamfer_width_definition": "Chamfer width definition",
    }.items():
        if key in spec:
            details[label] = spec[key]
    return details


def get(path, **kwargs):
    try:
        result = api_get(path, **kwargs)
    except requests.RequestException:
        st.error("Your order records are temporarily unavailable. Please retry.")
        return None
    if result.status_code in (401, 403):
        clear_orders_state(st.session_state)
    if result.status_code != 200:
        st.error(service_message(result.status_code))
        return None
    return result


def payment(order):
    return {
        "completed": "Payment recorded",
        "pending": "Awaiting payment",
        "failed": "Payment failed",
        "canceled": "Canceled",
        "cancelled": "Canceled",
        "refunded": "Refund recorded",
    }.get(order.get("status"), "Payment status unavailable")


def mode(order):
    if order.get("payment_mode") in ("TEST", "OWNER TEST"):
        st.warning("TEST / NOT A REAL SALE — no manufacturing or shipment.")
    else:
        st.caption(
            "LIVE order"
            if order.get("payment_mode") == "LIVE"
            else "Payment mode not recorded"
        )


def preview(content):
    # Rasterize the actual verified PDF, never regenerate a drawing from geometry.
    try:
        document = pdfium.PdfDocument(content)
        try:
            page = document[0]
            try:
                width, height = page.get_size()
                bitmap = page.render(scale=min(1.5, 1200 / width, 1800 / height))
                try:
                    image = BytesIO()
                    bitmap.to_pil().save(image, format="PNG")
                    st.image(
                        image.getvalue(),
                        caption="Stored drawing PDF · page 1",
                        width="stretch",
                    )
                finally:
                    bitmap.close()
            finally:
                page.close()
        finally:
            document.close()
    except Exception:
        st.info("Preview unavailable. Download the verified PDF to view all pages.")


def archived_drawing(order_id, revision):
    rid = quote(revision["id"], safe="")
    path = f'/me/orders/{quote(order_id, safe="")}/drawings/{rid}/pdf'
    if st.button("View approved drawing", key="archive-view-" + revision["id"]):
        st.session_state["orders_pdf_selection"] = (order_id, revision["id"])
    if st.session_state.get("orders_pdf_selection") != (order_id, revision["id"]):
        return
    response = get(path)
    if response is None:
        return
    content = response.content
    if (
        response.headers.get("X-Artifact-SHA256") != revision["pdf_sha256"]
        or response.headers.get("X-Frozen-Revision") != revision["id"]
        or sha256(content).hexdigest() != revision["pdf_sha256"]
        or len(content) != revision["pdf_size"]
    ):
        st.error("Drawing verification failed. No file was displayed or downloaded.")
        return
    preview(content)
    st.download_button(
        "Download approved PDF",
        content,
        file_name=revision["filename"],
        mime="application/pdf",
        key="archive-download-" + revision["id"],
    )
    st.caption("SHA-256 · " + revision["pdf_sha256"])


def pending_drawing(plate):
    # Keep the existing deliberate token-bound approval pathway separate from the read-only archive.
    session_key = "orders_confirmation_" + plate["current_revision"]
    if st.button("Review drawing for approval", key="review-" + plate["id"]):
        try:
            response = api_post(
                f'/me/frozen-plates/{quote(plate["id"], safe="")}/confirmation',
                payload={},
            )
            if response.status_code == 200:
                st.session_state[session_key] = response.json()
            else:
                st.error("Drawing review is unavailable. Refresh the order and retry.")
        except requests.RequestException:
            st.error("Drawing review is temporarily unavailable.")
    confirmation = st.session_state.get(session_key)
    if (
        not confirmation
        or confirmation.get("context", {}).get("revision")
        != f'R{plate["revisions"][0]["number"]}'
    ):
        return
    try:
        response = api_post(
            "/me/frozen-plates/pdf", payload={"token": confirmation["token"]}
        )
        if response.status_code != 200:
            st.error(
                "The pending drawing could not be verified. Refresh and review again."
            )
            return
        preview(response.content)
        st.download_button(
            "Download review PDF",
            response.content,
            file_name=confirmation["context"]["filename"],
            mime="application/pdf",
            key="review-pdf-" + plate["id"],
        )
        st.write(APPROVAL_COPY)
        if st.button(BUTTON, key="approve-" + plate["id"]):
            result = api_post(
                "/me/frozen-plates/approve", payload={"token": confirmation["token"]}
            )
            if result.status_code == 200:
                st.session_state.pop(session_key, None)
                st.rerun()
            else:
                st.error(
                    "Approval was not recorded. Refresh and review the current drawing."
                )
    except requests.RequestException:
        st.error("Drawing review is temporarily unavailable.")


def drawings(order_id, line, plate):
    st.markdown("**Drawings**")
    if not plate or not plate.get("revisions"):
        message = "No Frozen Plate drawing is recorded for this plate."
        spec = line["specifications"]
        if spec.get("chamfer") and any(
            spec.get(k) is None
            for k in (
                "chamfer_angle_degrees",
                "chamfer_side",
                "flow_orientation",
                "chamfer_width_definition",
            )
        ):
            message = "Historical chamfer specification is incomplete. Drawing review is required; no approved drawing is available."
        st.warning(message)
        return
    current = next((r for r in plate["revisions"] if r["current"]), None)
    if current and current["approved"]:
        st.success(
            f'Current drawing R{current["number"]} approved · {stamp(current["approved_at"])}'
        )
    elif current:
        st.info(f'Current drawing R{current["number"]} awaits customer approval.')
        if plate["lifecycle"] == "READY_FOR_CUSTOMER_CONFIRMATION":
            pending_drawing(plate)
    else:
        st.warning(
            "Current revision is unavailable. Historical revisions below remain distinct."
        )
    approved = [r for r in plate["revisions"] if r["approved"]]
    if not approved:
        st.caption("No approved PDF is available for this plate.")
        return
    options = {r["id"]: r for r in approved}
    selection_key = "orders_revision_" + line["line_id"]
    if st.session_state.get(selection_key) not in options:
        stored_revision = st.session_state.get("orders_revision_selection", {}).get(
            line["line_id"]
        )
        st.session_state[selection_key] = (
            stored_revision
            if stored_revision in options
            else next((r["id"] for r in approved if r["current"]), approved[0]["id"])
        )
    rid = st.selectbox(
        "Approved revision",
        list(options),
        key=selection_key,
        format_func=lambda value: f'R{options[value]["number"]} · '
        + (
            "Current approved"
            if options[value]["current"]
            else "Historical approved — superseded"
        ),
    )
    st.session_state.setdefault("orders_revision_selection", {})[line["line_id"]] = rid
    revision = options[rid]
    st.caption("Approved · " + stamp(revision["approved_at"]))
    archived_drawing(order_id, revision)
    with st.expander("Selected revision specifications"):
        st.dataframe(
            [
                {"Specification": k.replace("_", " ").capitalize(), "Value": str(v)}
                for k, v in revision["specifications"].items()
            ],
            hide_index=True,
            width="stretch",
        )


SORTS = {
    "Newest first": "newest",
    "Oldest first": "oldest",
    "Highest total": "total_high",
    "Lowest total": "total_low",
}


def choose_order(order_id):
    st.session_state["orders_selected"] = order_id
    for key in ("orders_line", "orders_pdf_selection"):
        st.session_state.pop(key, None)


def history(*, compact=False):
    previous = st.session_state.get("orders_filter", ("", "Newest first"))
    for key, value in zip(("orders_search", "orders_sort"), previous):
        if key not in st.session_state:
            st.session_state[key] = value
    search = st.text_input(
        "Find an order", placeholder="Order number", key="orders_search"
    )
    sort = st.selectbox("Sort orders", list(SORTS), key="orders_sort")
    identity = (search, sort)
    if st.session_state.get("orders_filter") != identity:
        st.session_state["orders_offset"] = 0
        st.session_state["orders_filter"] = identity
    offset = st.session_state.get("orders_offset", 0)
    with st.spinner("Loading your orders…"):
        response = get(
            "/me/order-history",
            params={
                "search": search,
                "sort": SORTS[sort],
                "offset": offset,
                "limit": 20,
            },
        )
    if response is None:
        return
    data = response.json() or {"orders": [], "total": 0}
    if not data.get("orders"):
        st.info(
            "No orders match this search."
            if search
            else "No orders are recorded for your account yet."
        )
        return
    st.caption(
        f'{offset + 1}–{offset + len(data["orders"])} of {data["total"]} orders · Dates in UTC'
    )
    for order in data["orders"]:
        with st.container(border=True):
            number = order.get("order_number_display") or "Order number pending"
            if compact:
                if st.button(
                    number,
                    key="order-open-" + order["id"],
                    type=(
                        "primary"
                        if st.session_state.get("orders_selected") == order["id"]
                        else "secondary"
                    ),
                    width="stretch",
                ):
                    choose_order(order["id"])
                    st.rerun()
            else:
                st.subheader(number)
            st.caption(
                stamp(order.get("created_at"))
                + f' · {order.get("line_count", 0)} plate entries'
            )
            st.markdown(
                '<div class="orders-card">'
                + escape(payment(order))
                + " · "
                + escape(money(order.get("amount_total_usd")))
                + "</div>",
                unsafe_allow_html=True,
            )
            if compact:
                st.caption(
                    "TEST · no manufacturing"
                    if order.get("payment_mode") in ("TEST", "OWNER TEST")
                    else (
                        "LIVE order"
                        if order.get("payment_mode") == "LIVE"
                        else "Payment mode not recorded"
                    )
                )
            else:
                mode(order)
            if not compact and st.button(
                "View order", key="order-open-" + order["id"], width="stretch"
            ):
                choose_order(order["id"])
                st.rerun()
    if st.button("Previous page", disabled=offset == 0, key="orders_previous"):
        st.session_state["orders_offset"] = max(0, offset - 20)
        st.rerun()
    if st.button("Next page", disabled=offset + 20 >= data["total"], key="orders_next"):
        st.session_state["orders_offset"] = offset + 20
        st.rerun()


def order_workspace(selected):
    if st.button("← Back to Orders", key="orders_back"):
        st.session_state.pop("orders_selected", None)
        st.session_state.pop("orders_pdf_selection", None)
        st.rerun()
    with st.spinner("Loading order…"):
        response = get("/me/order-history/" + quote(selected, safe=""))
    if response is None:
        return
    order = response.json()
    st.header(order.get("order_number_display") or "Order number pending")
    st.caption("Placed " + stamp(order.get("created_at")))
    mode(order)
    st.markdown(
        '<div class="orders-context"><span class="orders-status">'
        + escape(payment(order))
        + "</span><p>Recorded order total · "
        + escape(money(order.get("amount_total_usd")))
        + "</p></div>",
        unsafe_allow_html=True,
    )
    lines = {line["line_id"]: line for line in order.get("lines", [])}
    if not lines:
        st.warning("Original plate specifications are not recorded for this order.")
        return
    if st.session_state.get("orders_line") not in lines:
        stored = st.session_state.get("orders_plate_selection", (None, None))
        st.session_state["orders_line"] = (
            stored[1]
            if stored[0] == selected and stored[1] in lines
            else next(iter(lines))
        )
    indices = {line_id: i for i, line_id in enumerate(lines, 1)}

    def plate_label(line_id):
        spec = lines[line_id]["specifications"]
        return f'Plate {indices[line_id]} · {spec.get("material", "Material not recorded")} · Qty {spec.get("quantity", "Not recorded")}'

    line_id = st.selectbox(
        "Select plate", list(lines), format_func=plate_label, key="orders_line"
    )
    st.session_state["orders_plate_selection"] = (selected, line_id)
    line = lines[line_id]
    st.subheader(
        f'Plate {indices[line_id]} · {line["specifications"].get("material", "Material not recorded")}'
    )
    archive_response = get(f'/me/orders/{quote(selected, safe="")}/drawing-archive')
    if archive_response is None:
        st.warning(
            "Drawing archive temporarily unavailable. No approval status has been inferred."
        )
    else:
        plate = next(
            (p for p in archive_response.json() if p["line_id"] == line_id), None
        )
        drawings(selected, line, plate)
    st.subheader("Original purchased specifications")
    st.caption(
        "Quantity · " + str(line["specifications"].get("quantity", "Not recorded"))
    )
    st.dataframe(
        [
            {"Specification": k, "Value": str(v)}
            for k, v in purchased_details(line["specifications"]).items()
        ],
        hide_index=True,
        width="stretch",
    )
    st.caption(
        "Line/unit price is not recorded separately. The recorded order amounts are not recalculated."
    )
    with st.expander("Original order details"):
        st.write("Recorded subtotal · " + money(order.get("amount_subtotal_usd")))
        st.write("Recorded shipping · " + money(order.get("amount_shipping_usd")))
        st.write("Customer PO · Not recorded")
        st.caption(
            "Manufacturing, inspection and shipment are not confirmed by drawing approval. Fulfillment status is not recorded in this archive."
        )
    with st.expander("Shipping & documentation"):
        st.write(order.get("shipping_name") or "Recipient not recorded")
        st.write(
            ", ".join(order.get("shipping_address", {}).values())
            or "Address not recorded"
        )
        st.caption(
            "Selected shipping service: "
            + (order.get("shipping_service") or "Not recorded")
        )
        st.write("Carrier / tracking: not recorded.")
        st.write("Material certification: unavailable in this archive.")
        st.write("Final inspection report: unavailable in this archive.")
        st.caption("No inspection or certification completion has been inferred.")


def render():
    st.markdown(
        "<style>"
        + (Path(__file__).parent / "assets/customer-orders.css").read_text()
        + "</style>",
        unsafe_allow_html=True,
    )
    with st.container(key="orders_workspace"):
        st.title("My Orders")
        st.caption("FIND IT. VERIFY IT. · Your orders & approved drawings")
        if st.button("Start a quote"):
            st.switch_page("pages/1_Quote.py")
        selected = st.session_state.get("orders_selected")
        if selected:
            with st.container(key="orders_layout"):
                rail, workspace = st.columns([200, 700], gap="small")
                with rail:
                    with st.container(key="orders_rail"):
                        st.markdown("**YOUR ORDERS**")
                        history(compact=True)
                with workspace:
                    # A failed history request may have invalidated the active identity.
                    if st.session_state.get("orders_selected") == selected:
                        order_workspace(selected)
        else:
            history()
