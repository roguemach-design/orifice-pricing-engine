"""Customer order history and the exact stored approved PDF; no owner permissions."""

from datetime import datetime
from hashlib import sha256
from io import BytesIO
from urllib.parse import quote

import pypdfium2 as pdfium
import requests
import streamlit as st

from auth import api_get, api_post
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


def get(path, **kwargs):
    try:
        result = api_get(path, **kwargs)
    except requests.RequestException:
        st.error("Your order records are temporarily unavailable. Please retry.")
        return None
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
    for revision in plate["revisions"]:
        label = f'R{revision["number"]} · ' + (
            "Current revision" if revision["current"] else "Historical revision"
        )
        with st.expander(label, expanded=revision["current"] and revision["approved"]):
            st.caption(stamp(revision["created_at"]))
            if revision["approved"]:
                st.write("Approved · " + stamp(revision["approved_at"]))
                archived_drawing(order_id, revision)
            else:
                st.caption(
                    "Not approved — not available in the approved-drawing archive."
                )
            st.caption("Frozen drawing specifications (inches)")
            st.dataframe(
                [
                    {"Specification": k.replace("_", " ").capitalize(), "Value": str(v)}
                    for k, v in revision["specifications"].items()
                ],
                hide_index=True,
                width="stretch",
            )


def render():
    st.title("My Orders")
    st.caption("FIND IT. VERIFY IT. REORDER IT. · Order history & approved drawings")
    if st.button("Start a quote"):
        st.switch_page("pages/1_Quote.py")
    selected = st.session_state.get("orders_selected")
    if selected:
        if st.button("← All orders"):
            for k in (
                "orders_selected",
                "orders_pdf_selection",
                "orders_confirmation",
                "orders_review_plate",
            ):
                st.session_state.pop(k, None)
            st.rerun()
        response = get("/me/order-history/" + quote(selected, safe=""))
        if response is None:
            return
        order = response.json()
        st.header(order.get("order_number_display") or "Order number pending")
        mode(order)
        st.caption(stamp(order.get("created_at")))
        st.write(payment(order))
        st.metric("Recorded order total", money(order.get("amount_total_usd")))
        st.caption(
            "Subtotal "
            + money(order.get("amount_subtotal_usd"))
            + " · Shipping "
            + money(order.get("amount_shipping_usd"))
        )
        st.info(
            "Manufacturing, inspection and shipment are not confirmed by drawing approval. Fulfillment status is not recorded in this archive."
        )
        archive_response = get(f'/me/orders/{quote(selected, safe="")}/drawing-archive')
        archive = archive_response.json() if archive_response is not None else None
        for i, line in enumerate(order.get("lines", []), 1):
            with st.container(border=True):
                st.subheader(
                    f'Plate {i} · {line["specifications"].get("material", "Material not recorded")}'
                )
                spec = line["specifications"]
                st.caption("Quantity · " + str(spec.get("quantity", "Not recorded")))
                st.dataframe(
                    [
                        {"Specification": k, "Value": str(v)}
                        for k, v in customer_product_details(spec).items()
                    ],
                    hide_index=True,
                    width="stretch",
                )
                st.caption(
                    "Line/unit price is not recorded separately. The recorded order amounts above are not recalculated."
                )
                if archive is None:
                    st.warning(
                        "Drawing archive temporarily unavailable. No approval status has been inferred."
                    )
                else:
                    plate = next(
                        (p for p in archive if p["line_id"] == line["line_id"]), None
                    )
                    drawings(selected, line, plate)
        if not order.get("lines"):
            st.warning("Original plate specifications are not recorded for this order.")
        with st.expander("Shipping details & supporting documents"):
            st.write(order.get("shipping_name") or "Recipient not recorded")
            st.write(
                ", ".join(order.get("shipping_address", {}).values())
                or "Address not recorded"
            )
            st.caption(
                "Selected shipping service: "
                + (order.get("shipping_service") or "Not recorded")
            )
            st.write("Material certification: unavailable in this archive.")
            st.write("Final inspection report: unavailable in this archive.")
            st.caption(
                "No inspection or certification completion has been inferred."
            )
        return
    labels = {
        "Newest first": "newest",
        "Oldest first": "oldest",
        "Highest total": "total_high",
        "Lowest total": "total_low",
    }
    # These editable widgets are removed while details are open. Retain only
    # their ordinary filter values, never private response/PDF caches.
    previous_filter = st.session_state.get("orders_filter", ("", "Newest first"))
    if "orders_search" not in st.session_state:
        st.session_state["orders_search"] = previous_filter[0]
    if "orders_sort" not in st.session_state:
        st.session_state["orders_sort"] = previous_filter[1]
    search = st.text_input(
        "Find an order",
        placeholder="Order number, for example OP-0016",
        key="orders_search",
    )
    sort = st.selectbox("Sort orders", list(labels), key="orders_sort")
    identity = (search, sort)
    if st.session_state.get("orders_filter") != identity:
        st.session_state["orders_offset"] = 0
        st.session_state["orders_filter"] = identity
    offset = st.session_state.get("orders_offset", 0)
    response = get(
        "/me/order-history",
        params={"search": search, "sort": labels[sort], "offset": offset, "limit": 20},
    )
    if response is None:
        return
    data = response.json()
    # An empty list from older test/compatibility adapters is also an empty result.
    if data == []:
        data = {"orders": [], "total": 0}
    if not data.get("orders"):
        st.info(
            "No orders match this search."
            if search
            else "No orders are recorded for your account yet."
        )
        return
    st.caption(
        f'{offset+1}–{offset+len(data["orders"])} of {data["total"]} orders · Dates in UTC'
    )
    for order in data["orders"]:
        with st.container(border=True):
            columns = st.columns([3, 1])
            with columns[0]:
                st.subheader(
                    order.get("order_number_display") or "Order number pending"
                )
                st.caption(
                    stamp(order.get("created_at"))
                    + f' · {order.get("line_count", 0)} plate entries'
                )
                st.write(payment(order))
                mode(order)
            with columns[1]:
                st.write(money(order.get("amount_total_usd")))
                if st.button("View order", key="order-open-" + order["id"]):
                    st.session_state["orders_selected"] = order["id"]
                    st.session_state.pop("orders_pdf_selection", None)
                    st.rerun()
    prev, following = st.columns(2)
    if prev.button("Previous page", disabled=offset == 0):
        st.session_state["orders_offset"] = max(0, offset - 20)
        st.rerun()
    if following.button("Next page", disabled=offset + 20 >= data["total"]):
        st.session_state["orders_offset"] = offset + 20
        st.rerun()
