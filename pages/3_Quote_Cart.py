# pages/3_Quote_Cart.py
from __future__ import annotations

from journey.ui import emit as journey_event, headers as journey_headers

from customer_safety import service_message, customer_product_details

import io
from pathlib import Path
import os
import uuid
import hashlib
import json
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List

import streamlit as st
import requests

from auth import (
    auth_headers,
    current_user_id_hint,
    is_logged_in,
    render_auth_sidebar,
    require_login,
)
from drawing_intake.checkout_context import attest_context
from drawing_intake.checkout_recovery import fetch_checkout_recovery, restore_quote_editor
from drawing_intake.configurator_integration import feature_flag_enabled
from drawing_intake.owner_access import verified_owner_access

render_auth_sidebar(show_debug=False)
if not is_logged_in():
    journey_event("cart", "blocked", "system_restriction")
require_login("Open Account and log in to manage quote carts.")
journey_event("cart")

st.title("Quote Cart")
st.caption("Build a multi-line quote with multiple configured plates. PDF + checkout included.")

# Ensure cart exists
if "cart" not in st.session_state or not isinstance(st.session_state.cart, list):
    st.session_state.cart = []

cart: List[Dict[str, Any]] = st.session_state.cart
saved_source = st.session_state.get("saved_quote_cart")
if saved_source:
    st.info("Reviewing saved quote " + saved_source["quote_id"] + ". Configurations are preserved for purchasing.")
    if st.button("Return to saved quote"):
        st.session_state["saved_quote_intent"] = saved_source["quote_id"]
        st.switch_page(str(Path(__file__).resolve().parent / "7_My_Quotes.py"))
API_BASE = (os.environ.get("API_BASE") or "").strip().rstrip("/")
if API_BASE and "://" not in API_BASE:
    API_BASE = f"http://{API_BASE}"
API_KEY = (os.environ.get("API_KEY") or "").strip()
OWNER_ACCEPTANCE_MODE = feature_flag_enabled(
    os.environ.get("OPLATES_OWNER_ACCEPTANCE_MODE")
)
OWNER_TEST_CHECKOUT_ENABLED = feature_flag_enabled(
    os.environ.get("OPLATES_OWNER_TEST_CHECKOUT_ENABLED")
)

if not API_BASE:
    st.error("Pricing is temporarily unavailable. Please try again shortly.")
    st.stop()

owner_test_checkout_allowed = verified_owner_access(
    API_BASE,
    enabled=OWNER_TEST_CHECKOUT_ENABLED and is_logged_in(),
    user_id_hint=current_user_id_hint() if is_logged_in() else None,
    headers=auth_headers() if is_logged_in() else {},
    access_path=("/internal/owner-test/access" if os.environ.get("APP_ENV") == "production"
                 else "/internal/drawing-intake/access"),
)

from checkout_access import checkout_access
purchasing_access = checkout_access(
    API_BASE, auth_headers(), owner_test_allowed=owner_test_checkout_allowed,
    owner_acceptance=OWNER_ACCEPTANCE_MODE,
)
owner_checkout_allowed = purchasing_access["available"]

checkout_return = st.query_params.get("checkout")
if isinstance(checkout_return, list):
    checkout_return = checkout_return[0] if checkout_return else None
if checkout_return == "cancelled":
    st.session_state.pop("cart_checkout_attempt", None)
    st.info("Checkout was canceled. No payment was completed.")
    reference = st.query_params.get("resume")
    if reference and st.session_state.get("cart_recovered_reference") != reference:
        try:
            recovered = fetch_checkout_recovery(
                API_BASE, str(reference), auth_headers()
            )
            if recovered["kind"] != "cart":
                raise ValueError("This recovery belongs to a single configuration.")
            st.session_state.cart = [
                {
                    "line_id": str(uuid.uuid4()),
                    "inputs": inputs,
                    "assisted_quote": True,
                    "selected_part_context": context,
                }
                for inputs, context in zip(
                    recovered["items"],
                    recovered.get("contexts", [None] * len(recovered["items"])),
                )
            ]
            cart = st.session_state.cart
            restore_quote_editor(
                st.session_state,
                recovered["items"][-1],
                recovered.get("contexts", [None])[-1],
            )
            st.session_state["cart_recovered_reference"] = reference
            st.session_state["cart_recovery_review_required"] = True
            st.query_params.pop("checkout", None)
            st.query_params.pop("resume", None)
            st.success(
                "Your independent cart configurations have been restored. Prices are recalculated below; review before checkout."
            )
        except ValueError as exc:
            st.error(str(exc))


# ----------------------------
# PDF / Quote constants
# ----------------------------
from quote_document import (
    SUPPLIER, QUOTE_VALID_DAYS, new_quote_meta, quote_filename,
    document_from_cart, render_quote_pdf,
)


# Customer info stored in session so you only type it once
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
    c["purchasing_name"] = st.text_input("Purchasing contact (optional)", value=c.get("purchasing_name", ""))
    c["purchasing_email"] = st.text_input("Purchasing email (optional)", value=c.get("purchasing_email", ""))
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
    """Recalculate each cart line through the authoritative pricing API."""
    headers = {"x-api-key": API_KEY} if API_KEY else {}
    try:
        response = requests.post(
            f"{API_BASE}/quote",
            json=inputs,
            headers=headers,
            timeout=20,
        )
    except requests.RequestException as exc:
        raise RuntimeError("Live cart pricing is temporarily unavailable.") from exc
    if response.status_code != 200:
        raise RuntimeError("This cart contains a configuration that cannot be priced.")
    return response.json()


def _make_pdf_quote(lines: List[Dict[str, Any]], *, customer: Dict[str, Any] | None = None) -> bytes:
    """Thin adapter from authoritative cart line responses to the PDF renderer."""
    meta = new_quote_meta()
    st.session_state.quote_meta = meta
    return render_quote_pdf(document_from_cart(
        lines, customer or {}, meta, cart_pricing_config_version,
    ))


# ----------------------------
# Top buttons
# ----------------------------
top = st.columns([1, 1, 2])
with top[0]:
    if st.button("➕ Add another plate", disabled=bool(saved_source)):
        if cart and cart[-1].get("assisted_quote"):
            st.session_state["phase1k_new_plate_requested"] = True
        st.switch_page("pages/1_Quote.py")
with top[1]:
    if st.button("🧹 Clear cart"):
        st.session_state.cart = []
        st.session_state.pop("saved_quote_cart", None)
        st.session_state.pop("quote_revision_source", None)
        st.session_state.pop("cart_recovery_review_required", None)
        st.session_state.pop("cart_recovered_reference", None)
        # Optional: reset quote number when cart is cleared
        if "quote_meta" in st.session_state:
            del st.session_state["quote_meta"]
        st.rerun()

if not cart:
    st.warning("Your Quote Cart is empty.")
    st.info("Go to **Configure your plate** and sign in to add plates to your cart.")
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

        assisted_line = bool(item.get("assisted_quote"))
        with cols[1]:
            new_qty = st.number_input(
                "Qty",
                min_value=1,
                value=int(inputs.get("quantity") or 1),
                step=1,
                key=f"qty_{line_id}",
                disabled=assisted_line or bool(saved_source),
            )
            if assisted_line:
                st.caption(
                    "To change this confirmed plate, remove it and configure it again."
                )
            else:
                inputs["quantity"] = int(new_qty)
                item["inputs"] = inputs  # existing manual-cart behavior

        # Live pricing
        try:
            res = _calc_line(inputs)
        except RuntimeError as exc:
            st.error(str(exc))
            st.caption("Checkout is disabled until every cart line has a verified live price.")
            st.stop()
        unit_price = float(res.get("unit_price") or 0.0)
        line_total = float(res.get("total_price") or 0.0)

        with cols[2]:
            st.metric("Unit", _usd(unit_price))
        with cols[3]:
            st.metric("Line", _usd(line_total))

        # Remove button
        rm_cols = st.columns([1, 5])
        with rm_cols[0]:
            if st.button("Remove", key=f"rm_{line_id}", disabled=bool(saved_source)):
                st.session_state.cart = [x for x in st.session_state.cart if x.get("line_id") != line_id]
                st.rerun()

        with st.expander("Configuration details"):
            st.table(customer_product_details(inputs))

    cart_subtotal += line_total
    line_views.append(
        {
            "line_id": line_id,
            "inputs": inputs,
            "unit_price": unit_price,
            "line_total": line_total,
            "pricing_config_version": res.get("pricing_config_version"),
            "qty_discount_multiplier": res.get("qty_discount_multiplier", 1),
            "estimated_total_weight_lb": res.get("estimated_total_weight_lb", 0),
        }
    )

pricing_versions = {
    line["pricing_config_version"]
    for line in line_views
    if line.get("pricing_config_version")
}
if len(pricing_versions) != 1:
    st.warning("Cart pricing changed while loading. Refresh before checkout.")
    st.stop()
cart_pricing_config_version = next(iter(pricing_versions))

st.divider()

st.subheader("Totals")
st.metric("Cart Subtotal", _usd(cart_subtotal))

st.divider()


# ----------------------------
# Next actions: PDF + Checkout
# ----------------------------
st.subheader("Next actions")

recovery_review_current = True
if st.session_state.get("cart_recovery_review_required"):
    recovery_fingerprint = hashlib.sha256(
        json.dumps([line["inputs"] for line in line_views], sort_keys=True).encode()
    ).hexdigest()
    recovery_review_current = st.checkbox(
        "I have reviewed the restored cart specifications and confirm them for checkout.",
        key=f"cart_recovery_confirm_{recovery_fingerprint}",
    )
    if not recovery_review_current:
        st.error("Confirmation required before checkout.")

c1, c2 = st.columns(2)

with c1:
    if os.environ.get("SAVED_QUOTES_ENABLED") == "true":
        from auth import api_post, api_get
        from urllib.parse import quote as quote_path
        if saved_source:
            response = api_get("/quotes/" + quote_path(saved_source["quote_id"], safe="") + "/pdf")
            if response.status_code == 200:
                st.download_button("Download saved PDF", response.content, file_name=quote_filename(saved_source["quote_id"]), mime="application/pdf")
        elif st.button("Save branded PDF quote", use_container_width=True):
            source = st.session_state.get("quote_revision_source")
            payload = {"items": [l["inputs"] for l in line_views], "customer": st.session_state.quote_customer}
            if not source: payload["pricing_config_version"] = cart_pricing_config_version
            response = api_post("/quotes/" + quote_path(source, safe="") + "/revisions" if source else "/quotes", payload=payload)
            if response.status_code == 200:
                st.session_state["saved_quote_intent"] = response.json()["quote_id"]
                st.session_state.pop("quote_revision_source", None)
                st.switch_page(str(Path(__file__).resolve().parent / "7_My_Quotes.py"))
            else: st.error(service_message(response.status_code))
        st.caption("Save configurations and a branded PDF in My Quotes, then share with Purchasing.")
    else:
        pdf_bytes = _make_pdf_quote(line_views, customer=st.session_state.quote_customer)
        filename = quote_filename(st.session_state.quote_meta["quote_id"])
        if st.download_button("📄 Generate PDF Quote", data=pdf_bytes, file_name=filename,
                              mime="application/pdf", use_container_width=True):
            journey_event("pdf_quote", "success")
        st.caption("Downloads a PDF summary of the current cart.")

saved_review_current = not saved_source or (
    [l["inputs"] for l in line_views] == saved_source["inputs"]
    and cart_pricing_config_version == saved_source["pricing_config_version"]
)
if not saved_review_current:
    st.warning("This cart has changed. Return to the saved quote and review current pricing again.")

with c2:
    if not owner_checkout_allowed:
        journey_event("checkout", "blocked", "system_restriction")
    st.caption("Prices are revalidated before Stripe checkout.")
    if OWNER_ACCEPTANCE_MODE and not owner_checkout_allowed:
        st.caption(
            "Checkout is currently closed."
        )
    if st.button(
        "💳 Checkout All Items",
        use_container_width=True,
        disabled=not owner_checkout_allowed or not recovery_review_current or not saved_review_current,
    ):
        cart_items = [lv["inputs"] for lv in line_views]
        fingerprint = hashlib.sha256(
            json.dumps(
                {
                    "items": cart_items,
                    "pricing_config_version": cart_pricing_config_version,
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        journey_event("checkout", "attempted")
        checkout_attempt = st.session_state.get("cart_checkout_attempt")
        if not isinstance(checkout_attempt, dict) or checkout_attempt.get("fingerprint") != fingerprint:
            checkout_attempt = {
                "fingerprint": fingerprint,
                "idempotency_key": str(uuid.uuid4()),
            }
            st.session_state.cart_checkout_attempt = checkout_attempt

        try:
            r = requests.post(
                f"{API_BASE}/checkout/cart/create",
                json={
                    "items": cart_items,
                    **({"saved_quote_id": saved_source["quote_id"],
                        "saved_quote_review_id": saved_source["review_id"],
                        "saved_quote_acknowledged": saved_source["acknowledged"]} if saved_source else {}),
                    "recovery_contexts": [
                        (
                            attest_context(
                                item["selected_part_context"],
                                inputs,
                                current_user_id_hint(),
                                API_KEY,
                            )
                            if item.get("selected_part_context")
                            else None
                        )
                        for item, inputs in zip(cart, cart_items)
                    ],
                    "pricing_config_version": cart_pricing_config_version,
                    "idempotency_key": checkout_attempt["idempotency_key"],
                },
                headers={**auth_headers(), **journey_headers(), **({"x-oplates-checkout-mode": "owner_test"}
                         if purchasing_access["mode"] == "owner_test" else {})},
                timeout=30,
            )
        except requests.RequestException:
            journey_event("checkout", "error", "api_failure")
            st.error("Checkout is temporarily unavailable. Please try again.")
            st.stop()

        if r.status_code != 200:
            journey_event("checkout", "error", "api_failure")
            st.error(service_message(r.status_code))
            st.stop()

        resp = r.json()
        url = resp.get("checkout_url")
        if not url:
            st.error("Checkout couldn’t be started. Please try again.")
            st.stop()

        # redirect
        from customer_navigation import render_integrated_checkout
        if render_integrated_checkout(url):
            st.stop()
        st.markdown(f"<meta http-equiv='refresh' content='0; url={url}'>", unsafe_allow_html=True)
        st.link_button("Continue to Stripe Checkout", url, use_container_width=True)
