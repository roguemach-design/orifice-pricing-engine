# pages/3_Quote_Cart.py
from __future__ import annotations

import io
import os
import uuid
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List

import streamlit as st
import requests

from auth import render_auth_sidebar, require_login, auth_headers
from pricing_engine import QuoteInputs, calculate_quote


render_auth_sidebar(show_debug=False)
require_login("Log in in the sidebar to manage quote carts.")

st.title("Quote Cart")
st.caption("Build a multi-line quote with multiple configured plates. PDF + checkout included.")

# Ensure cart exists
if "cart" not in st.session_state or not isinstance(st.session_state.cart, list):
    st.session_state.cart = []

cart: List[Dict[str, Any]] = st.session_state.cart


# ----------------------------
# PDF / Quote constants
# ----------------------------
SUPPLIER = {
    "name": "Rogue Machine LLC",
    "addr1": "736 Stone and Shannon Rd",
    "city_state_zip": "Wheeling WV 26003",
    "country": "United States",
    "phone": "+1 304-639-0595",
}

SUPPLIER_LOGOS = [
    "assets/Rogue Machine Logo.jpg",
    "assets/Rogue Machine Full Logo.jpg",
]

QUOTE_VALID_DAYS = 30


def _ensure_quote_meta() -> Dict[str, Any]:
    """
    Creates a stable quote id for the current cart session so the PDF has a quote number.
    """
    if "quote_meta" not in st.session_state or not isinstance(st.session_state.quote_meta, dict):
        qid = "Q-" + uuid.uuid4().hex[:10].upper()
        created = datetime.now(timezone.utc)
        st.session_state.quote_meta = {"quote_id": qid, "created_at": created}
    return st.session_state.quote_meta


# Customer info stored in session so you only type it once
_ensure_quote_meta()
if "quote_customer" not in st.session_state or not isinstance(st.session_state.quote_customer, dict):
    st.session_state.quote_customer = {
        "company": "",
        "name": "",
        "email": st.session_state.auth.get("email") or "",
        "phone": "",
        "addr1": "",
        "addr2": "",
        "city_state_zip": "",
        "country": "United States",
    }

with st.expander("Customer info (shows on PDF)", expanded=False):
    c = st.session_state.quote_customer
    c["company"] = st.text_input("Company", value=c.get("company", ""))
    c["name"] = st.text_input("Name", value=c.get("name", ""))
    c["email"] = st.text_input("Email", value=c.get("email", st.session_state.auth.get("email") or ""))
    c["phone"] = st.text_input("Phone", value=c.get("phone", ""))
    c["addr1"] = st.text_input("Address line 1", value=c.get("addr1", ""))
    c["addr2"] = st.text_input("Address line 2", value=c.get("addr2", ""))
    c["city_state_zip"] = st.text_input("City / State / ZIP", value=c.get("city_state_zip", ""))
    c["country"] = st.text_input("Country", value=c.get("country", "United States"))
    st.session_state.quote_customer = c


# ----------------------------
# Helpers
# ----------------------------
def _usd(x: float | int | None) -> str:
    try:
        if x is None:
            return ""
        return f"${float(x):,.2f}"
    except Exception:
        return str(x)


def _calc_line(inputs: Dict[str, Any]) -> Dict[str, Any]:
    """
    Recalculate pricing live based on current qty, using pricing_engine locally.
    This keeps cart prices accurate even after editing qty.
    """
    qi = QuoteInputs(**inputs)
    res = calculate_quote(qi)
    return res


def _make_pdf_quote(lines: List[Dict[str, Any]], *, customer: Dict[str, Any] | None = None) -> bytes:
    """
    Generate a nicer PDF quote using ReportLab.
    Adds logos, gray header bar, supplier + customer blocks, quote number and validity.
    """
    from reportlab.lib.pagesizes import LETTER
    from reportlab.lib.units import inch
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas
    from reportlab.lib import colors

    meta = _ensure_quote_meta()
    quote_id = meta["quote_id"]
    created_at = meta["created_at"]
    valid_until = created_at + timedelta(days=QUOTE_VALID_DAYS)

    customer = customer or {}

    cust_lines: List[str] = []
    if (customer.get("company") or "").strip():
        cust_lines.append(customer["company"].strip())
    if (customer.get("name") or "").strip():
        cust_lines.append(customer["name"].strip())
    if (customer.get("email") or "").strip():
        cust_lines.append(customer["email"].strip())
    if (customer.get("phone") or "").strip():
        cust_lines.append(customer["phone"].strip())
    if (customer.get("addr1") or "").strip():
        cust_lines.append(customer["addr1"].strip())
    if (customer.get("addr2") or "").strip():
        cust_lines.append(customer["addr2"].strip())
    if (customer.get("city_state_zip") or "").strip():
        cust_lines.append(customer["city_state_zip"].strip())
    if (customer.get("country") or "").strip():
        cust_lines.append(customer["country"].strip())

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=LETTER)
    w, h = LETTER

    margin = 0.75 * inch

    # --- Light gray header bar (across the top) ---
    header_h = 0.95 * inch
    c.setFillColor(colors.HexColor("#EFEFEF"))
    c.rect(0, h - header_h, w, header_h, fill=1, stroke=0)

    # --- Logo on header (left) ---
    logo_drawn = False
    for p in SUPPLIER_LOGOS:
        if os.path.exists(p):
            try:
                img = ImageReader(p)
                logo_h = 0.70 * inch
                logo_w = 2.7 * inch
                c.drawImage(
                    img,
                    margin,
                    h - header_h + (header_h - logo_h) / 2.0,
                    width=logo_w,
                    height=logo_h,
                    mask="auto",
                    preserveAspectRatio=True,
                    anchor="sw",
                )
                logo_drawn = True
                break
            except Exception:
                pass

    # --- Header text (right) ---
    c.setFillColor(colors.black)
    c.setFont("Helvetica-Bold", 18)
    c.drawRightString(w - margin, h - 0.35 * inch, "QUOTE")

    c.setFont("Helvetica", 10)
    c.drawRightString(w - margin, h - 0.58 * inch, f"Quote #: {quote_id}")
    c.drawRightString(w - margin, h - 0.74 * inch, f"Issued: {created_at.strftime('%Y-%m-%d')}")
    c.drawRightString(w - margin, h - 0.90 * inch, f"Valid until: {valid_until.strftime('%Y-%m-%d')}")

    y = h - header_h - 0.35 * inch

    # Divider
    c.setStrokeColor(colors.HexColor("#222222"))
    c.line(margin, y, w - margin, y)
    y -= 0.30 * inch

    # --- Supplier + Customer blocks ---
    left_x = margin
    right_x = w / 2 + 0.25 * inch

    c.setFont("Helvetica-Bold", 11)
    c.drawString(left_x, y, "Supplier")
    c.drawString(right_x, y, "Customer")
    y -= 0.18 * inch

    c.setFont("Helvetica", 10)
    supplier_lines = [
        SUPPLIER["name"],
        SUPPLIER["addr1"],
        SUPPLIER["city_state_zip"],
        SUPPLIER["country"],
        SUPPLIER["phone"],
    ]

    block_top_y = y
    yy = block_top_y
    for line in supplier_lines:
        c.drawString(left_x, yy, line)
        yy -= 0.16 * inch

    yy2 = block_top_y
    if cust_lines:
        for line in cust_lines[:10]:
            c.drawString(right_x, yy2, line)
            yy2 -= 0.16 * inch
    else:
        c.setFont("Helvetica-Oblique", 10)
        c.drawString(right_x, yy2, "(customer info not provided)")
        c.setFont("Helvetica", 10)

    y = min(yy, yy2) - 0.25 * inch

    c.setFont("Helvetica", 9)
    c.drawString(margin, y, "Notes: Shipping is selected at checkout. Prices shown exclude tax.")
    y -= 0.25 * inch

    # --- Line items table header ---
    c.setFont("Helvetica-Bold", 10)
    c.drawString(margin, y, "Item")
    c.drawRightString(w - margin - 200, y, "Qty")
    c.drawRightString(w - margin - 120, y, "Unit")
    c.drawRightString(w - margin, y, "Line Total")
    y -= 0.12 * inch
    c.line(margin, y, w - margin, y)
    y -= 0.18 * inch

    subtotal = 0.0
    c.setFont("Helvetica", 9)

    for i, line in enumerate(lines, start=1):
        inputs = line["inputs"]
        unit_price = float(line["unit_price"])
        line_total = float(line["line_total"])
        qty = int(inputs.get("quantity") or 1)

        desc = (
            f"{inputs.get('material')} | t={inputs.get('thickness')} | "
            f"paddle={inputs.get('paddle_dia')} | bore={inputs.get('bore_dia')} | "
            f"tol=±{inputs.get('bore_tolerance')} | ships={inputs.get('ships_in_days')}d"
        )

        # page break
        if y < 1.25 * inch:
            c.showPage()

            # redraw header bar on new page
            c.setFillColor(colors.HexColor("#EFEFEF"))
            c.rect(0, h - header_h, w, header_h, fill=1, stroke=0)

            c.setFillColor(colors.black)
            c.setFont("Helvetica-Bold", 14)
            c.drawString(margin, h - 0.55 * inch, f"Quote #{quote_id} (continued)")

            y = h - header_h - 0.35 * inch

            c.setFont("Helvetica-Bold", 10)
            c.drawString(margin, y, "Item")
            c.drawRightString(w - margin - 200, y, "Qty")
            c.drawRightString(w - margin - 120, y, "Unit")
            c.drawRightString(w - margin, y, "Line Total")
            y -= 0.12 * inch
            c.line(margin, y, w - margin, y)
            y -= 0.18 * inch
            c.setFont("Helvetica", 9)

        c.drawString(margin, y, f"{i}. {desc[:110]}")
        c.drawRightString(w - margin - 200, y, str(qty))
        c.drawRightString(w - margin - 120, y, _usd(unit_price))
        c.drawRightString(w - margin, y, _usd(line_total))
        y -= 0.18 * inch

        label = (inputs.get("handle_label") or "").strip()
        if label and label != "No label":
            c.setFont("Helvetica-Oblique", 8.5)
            c.drawString(margin + 14, y, f"Label: {label[:120]}")
            c.setFont("Helvetica", 9)
            y -= 0.16 * inch

        subtotal += line_total

    y -= 0.08 * inch
    c.line(margin, y, w - margin, y)
    y -= 0.22 * inch

    c.setFont("Helvetica-Bold", 11)
    c.drawRightString(w - margin - 120, y, "Subtotal:")
    c.drawRightString(w - margin, y, _usd(subtotal))
    y -= 0.25 * inch

    c.setFont("Helvetica", 9)
    c.drawString(margin, y, f"Quote valid for {QUOTE_VALID_DAYS} days unless otherwise agreed.")
    y -= 0.18 * inch
    c.setFont("Helvetica", 8)
    c.drawString(margin, y, "Thank you for the opportunity — Rogue Machine LLC.")

    c.save()
    buf.seek(0)
    return buf.read()


# ----------------------------
# Top buttons
# ----------------------------
top = st.columns([1, 1, 2])
with top[0]:
    if st.button("➕ Add another plate"):
        st.switch_page("pages/1_Quote.py")
with top[1]:
    if st.button("🧹 Clear cart"):
        st.session_state.cart = []
        # Optional: reset quote number when cart is cleared
        if "quote_meta" in st.session_state:
            del st.session_state["quote_meta"]
        st.rerun()

if not cart:
    st.warning("Your Quote Cart is empty.")
    st.info("Go to **Quote** and click **Add to Quote** to build a multi-line quote.")
    st.stop()


# ----------------------------
# Recalculate all lines live (so qty edits update prices)
# ----------------------------
line_views: List[Dict[str, Any]] = []
cart_subtotal = 0.0

st.subheader(f"Line items ({len(cart)})")

for idx, item in enumerate(cart):
    inputs = item.get("inputs") or {}
    line_id = item.get("line_id", f"line-{idx}")

    # Ensure qty exists
    if "quantity" not in inputs or not inputs["quantity"]:
        inputs["quantity"] = 1

    with st.container(border=True):
        cols = st.columns([2.3, 1.2, 1.2, 1.0])

        with cols[0]:
            st.markdown(
                f"**{idx+1}. {inputs.get('material')}** | "
                f"{inputs.get('thickness')} in | "
                f"Paddle {inputs.get('paddle_dia')} in | "
                f"Bore {inputs.get('bore_dia')} in"
            )
            st.caption(f"Label: {inputs.get('handle_label') or 'No label'}")

        with cols[1]:
            new_qty = st.number_input(
                "Qty",
                min_value=1,
                value=int(inputs.get("quantity") or 1),
                step=1,
                key=f"qty_{line_id}",
            )
            inputs["quantity"] = int(new_qty)
            item["inputs"] = inputs  # persist edit in session

        # Live pricing
        res = _calc_line(inputs)
        unit_price = float(res.get("unit_price") or 0.0)
        line_total = float(res.get("total_price") or 0.0)

        with cols[2]:
            st.metric("Unit", _usd(unit_price))
        with cols[3]:
            st.metric("Line", _usd(line_total))

        # Remove button
        rm_cols = st.columns([1, 5])
        with rm_cols[0]:
            if st.button("Remove", key=f"rm_{line_id}"):
                st.session_state.cart = [x for x in st.session_state.cart if x.get("line_id") != line_id]
                st.rerun()

        with st.expander("Show configuration JSON"):
            st.json(inputs)

    cart_subtotal += line_total
    line_views.append(
        {
            "line_id": line_id,
            "inputs": inputs,
            "unit_price": unit_price,
            "line_total": line_total,
        }
    )

st.divider()

st.subheader("Totals")
st.metric("Cart Subtotal", _usd(cart_subtotal))

st.divider()


# ----------------------------
# Next actions: PDF + Checkout
# ----------------------------
st.subheader("Next actions")

c1, c2 = st.columns(2)

with c1:
    pdf_bytes = _make_pdf_quote(line_views, customer=st.session_state.quote_customer)
    meta = _ensure_quote_meta()
    filename = f"o-plates-quote-{meta['quote_id']}-{datetime.now().strftime('%Y%m%d-%H%M')}.pdf"
    st.download_button(
        "📄 Generate PDF Quote",
        data=pdf_bytes,
        file_name=filename,
        mime="application/pdf",
        use_container_width=True,
    )
    st.caption("Downloads a PDF summary of the current cart.")

with c2:
    st.caption("Creates a Stripe checkout for the entire cart.")
    if st.button("💳 Checkout All Items", use_container_width=True):
        API_BASE = os.environ.get("API_BASE", "https://orifice-pricing-api.onrender.com").rstrip("/")

        r = requests.post(
            f"{API_BASE}/checkout/cart/create",
            json={"items": [lv["inputs"] for lv in line_views]},
            headers=auth_headers(),
            timeout=30,
        )

        if r.status_code != 200:
            st.error(f"Cart checkout API error: {r.status_code}")
            st.code(r.text)
            st.stop()

        resp = r.json()
        url = resp.get("checkout_url")
        if not url:
            st.error("API did not return checkout_url.")
            st.json(resp)
            st.stop()

        # redirect
        st.markdown(f"<meta http-equiv='refresh' content='0; url={url}'>", unsafe_allow_html=True)
        st.link_button("Continue to Stripe Checkout", url, use_container_width=True)
