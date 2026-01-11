# pages/3_Quote_Cart.py
from __future__ import annotations

import io
from datetime import datetime, timezone
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


def _make_pdf_quote(lines: List[Dict[str, Any]], *, customer_email: str | None = None) -> bytes:
    """
    Generate a simple PDF quote using ReportLab.
    """
    from reportlab.lib.pagesizes import LETTER
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=LETTER)
    w, h = LETTER

    # Header
    y = h - 54
    c.setFont("Helvetica-Bold", 16)
    c.drawString(54, y, "O-Plates Quote")
    y -= 18

    c.setFont("Helvetica", 10)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    c.drawString(54, y, f"Generated: {now}")
    y -= 14
    if customer_email:
        c.drawString(54, y, f"Customer: {customer_email}")
        y -= 14

    c.drawString(54, y, "Notes: Shipping is selected at checkout. Prices shown exclude tax.")
    y -= 18

    # Table header
    c.setFont("Helvetica-Bold", 10)
    c.drawString(54, y, "Item")
    c.drawString(265, y, "Qty")
    c.drawString(310, y, "Unit")
    c.drawString(390, y, "Line Total")
    y -= 12
    c.line(54, y, w - 54, y)
    y -= 12

    subtotal = 0.0

    c.setFont("Helvetica", 10)
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

        # page break if needed
        if y < 90:
            c.showPage()
            y = h - 54
            c.setFont("Helvetica-Bold", 10)
            c.drawString(54, y, "Item")
            c.drawString(265, y, "Qty")
            c.drawString(310, y, "Unit")
            c.drawString(390, y, "Line Total")
            y -= 12
            c.line(54, y, w - 54, y)
            y -= 12
            c.setFont("Helvetica", 10)

        c.drawString(54, y, f"{i}. {desc[:90]}")
        c.drawRightString(290, y, str(qty))
        c.drawRightString(370, y, _usd(unit_price))
        c.drawRightString(w - 54, y, _usd(line_total))
        y -= 14

        label = (inputs.get("handle_label") or "").strip()
        if label and label != "No label":
            c.setFont("Helvetica-Oblique", 9)
            c.drawString(70, y, f"Label: {label[:100]}")
            y -= 12
            c.setFont("Helvetica", 10)

        subtotal += line_total

    y -= 8
    c.line(54, y, w - 54, y)
    y -= 16

    c.setFont("Helvetica-Bold", 11)
    c.drawRightString(370, y, "Subtotal:")
    c.drawRightString(w - 54, y, _usd(subtotal))
    y -= 18

    c.setFont("Helvetica", 9)
    c.drawString(54, y, "Quote valid for 14 days unless otherwise agreed.")
    y -= 12

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
    pdf_bytes = _make_pdf_quote(line_views, customer_email=st.session_state.auth.get("email"))
    filename = f"o-plates-quote-{datetime.now().strftime('%Y%m%d-%H%M')}.pdf"
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
        # Call API endpoint we will add below (api_app.py change)
        r = requests.post(
            f"{st.secrets.get('API_BASE', '')}".rstrip("/") + "/checkout/cart/create"
            if "API_BASE" in st.secrets
            else None,
        )

        # If you're not using st.secrets, do it from env (most likely):
        import os
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
