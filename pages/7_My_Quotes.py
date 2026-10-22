"""Saved quotes inside the existing customer account; checkout uses Quote Cart."""

import os
import copy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
from uuid import uuid4
from urllib.parse import quote
import streamlit as st
from auth import render_auth_sidebar, require_login, api_get, api_post
from customer_safety import customer_product_details, service_message
from quote_document import quote_filename

# Preserve fallback/invitation intent across the existing sign-in UI and reruns.
for param in ("quote", "invite"):
    if st.query_params.get(param):
        st.session_state["saved_" + param + "_intent"] = str(st.query_params[param])
        st.query_params.pop(param, None)
if st.session_state.get("saved_invite_intent"):
    st.query_params.pop("invite", None)
render_auth_sidebar(show_debug=False)
st.title("My Quotes")
if os.environ.get("SAVED_QUOTES_ENABLED") != "true":
    st.info("Saved quotes are not available yet.")
    st.stop()

with st.form("find_quote"):
    find = st.text_input(
        "Find a Quote by number",
        value=st.session_state.get("saved_quote_intent", ""),
        placeholder="Q-XXXXXXXXXX",
    )
    if st.form_submit_button("Find a Quote"):
        st.session_state["saved_quote_intent"] = find.strip().upper()
        st.rerun()

require_login(
    "Sign in with your own email to view saved quotes and purchasing invitations."
)
listed = api_get("/me/quotes")
if listed.status_code != 200:
    st.error(service_message(listed.status_code))
    st.stop()
for row in listed.json():
    with st.container(border=True):
        st.write(
            f"**{row['quote_id']}** · ${float(row['subtotal']):,.2f} · {row['status'].title()}"
        )
        st.caption(
            row["created_at"][:10]
            + (" · Shared with you" if row["shared_with_you"] else "")
        )
        if st.button("Open quote", key="open_" + row["quote_id"]):
            st.session_state["saved_quote_intent"] = row["quote_id"]
            st.rerun()

qid = st.session_state.get("saved_quote_intent", "").strip().upper()
if not qid:
    if not listed.json():
        st.info("Save a PDF quote from your Quote Cart to find it here.")
    st.stop()
path = "/quotes/" + quote(qid, safe="")
if st.session_state.get("saved_invite_intent"):
    st.info(
        "Accept this purchasing invitation using the exact email address it was sent to."
    )
    if st.button("Accept purchasing invitation"):
        accepted = api_post(
            path + "/accept", payload={"token": st.session_state["saved_invite_intent"]}
        )
        if accepted.status_code == 200:
            st.session_state.pop("saved_invite_intent", None)
            st.success("Invitation accepted.")
            st.rerun()
        else:
            st.error("Quote not available for this account.")
    st.stop()
response = api_get(path)
if response.status_code != 200:
    st.error(
        "Quote not available for this account."
        if response.status_code == 404
        else service_message(response.status_code)
    )
    st.stop()
q = response.json()
snapshot = q["snapshot"]
st.subheader(qid)
st.write(
    f"**{q['status'].title()}** · Quoted subtotal **${float(q['subtotal']):,.2f}**"
)
st.caption(
    "Valid through "
    + q["valid_through"][:10]
    + ". Shipping selected and tax calculated at checkout."
)
for i, line in enumerate(snapshot["lines"], 1):
    with st.expander(
        f"Plate {i} · Qty {line['inputs']['quantity']} · ${line['total_price']:,.2f}"
    ):
        st.table(
            {k: str(v) for k, v in customer_product_details(line["inputs"]).items()}
        )
pdf = api_get(path + "/pdf")
if pdf.status_code == 200:
    st.download_button(
        "Download saved PDF",
        pdf.content,
        file_name=quote_filename(qid),
        mime="application/pdf",
    )

if not q["shared_with_you"] and st.button("Email saved PDF to me"):
    sent = api_post(path + "/email", payload={})
    if sent.status_code == 200 and sent.json()["email_status"] == "accepted":
        st.success("Your saved PDF and View Your Quote link were sent.")
    elif sent.status_code == 200 and sent.json()["email_status"] == "captured":
        st.info("Quote email captured for review. No email was sent.")
    else:
        st.warning(
            "Email delivery needs review. Your saved PDF remains available to download."
        )

if q["status"] == "ordered":
    st.success("This quote has been ordered.")
    st.page_link(ROOT / "pages/2_My_Orders.py", label="View My Orders")
    st.stop()
if q["status"] == "superseded":
    st.info(
        "A newer revision is available in My Quotes. This document remains unchanged."
    )
    st.stop()

if q.get("checkout_in_progress"):
    st.info(
        "A checkout is in progress. Resume it below, or cancel it before revising this quote."
    )
    if st.button("Cancel active checkout"):
        canceled = api_post(path + "/checkout/cancel", payload={})
        if canceled.status_code == 200:
            st.rerun()
        else:
            st.error(
                "Checkout could not be canceled. It may already be paid; refresh your quote."
            )

if st.button(
    "Update Pricing"
    if q["status"] == "expired"
    else "Create a revision at current prices"
):
    rev = api_post(path + "/revisions", payload={})
    if rev.status_code == 200:
        st.session_state["saved_quote_intent"] = rev.json()["quote_id"]
        st.rerun()
    else:
        st.error(service_message(rev.status_code))
if st.button("Edit as new revision"):
    st.session_state["quote_revision_source"] = qid
    st.session_state["cart"] = [
        {"line_id": str(uuid4()), "inputs": copy.deepcopy(l["inputs"])}
        for l in snapshot["lines"]
    ]
    st.session_state["quote_customer"] = copy.deepcopy(snapshot["customer"])
    st.session_state.pop("saved_quote_cart", None)
    st.switch_page(str(ROOT / "pages/3_Quote_Cart.py"))
if q["status"] == "expired":
    st.warning(
        "This quote has expired. Update Pricing to create a new revision before ordering."
    )
    st.stop()

if not q["shared_with_you"]:
    with st.expander("Share with Purchasing"):
        st.caption(
            "Invite a verified buyer to review and order without reentering plate specifications."
        )
        with st.form("share_purchasing"):
            purchaser = st.text_input("Purchaser email")
            if st.form_submit_button("Send purchasing invitation"):
                sent = api_post(path + "/shares", payload={"email": purchaser})
                if sent.status_code == 200:
                    state = sent.json()["email_status"]
                    if state == "accepted":
                        st.success("Invitation sent.")
                    elif state == "captured":
                        st.info("Invitation captured for review. No email was sent.")
                    else:
                        st.warning(
                            "Invitation saved, but delivery needs review. Revoke it and retry when email is available."
                        )
                else:
                    st.error(service_message(sent.status_code))
        shared = api_get(path + "/shares")
        if shared.status_code == 200:
            for share in shared.json():
                st.write(
                    share["email"]
                    + (" · Accepted" if share["accepted"] else " · Pending")
                    + (" · Revoked" if share["revoked"] else "")
                )
                if not share["revoked"] and st.button(
                    "Revoke access", key="revoke_" + share["share_id"]
                ):
                    result = api_post(
                        path + "/shares/" + share["share_id"] + "/revoke", payload={}
                    )
                    if result.status_code == 200:
                        st.rerun()
                    else:
                        st.error(
                            "Access could not be revoked while checkout is in progress. Contact sales@o-plates.com."
                        )

st.subheader("Review & Order")
st.caption(
    "Current pricing and available lead times are checked before returning to your existing Quote Cart."
)
config = api_get("/config/active")
available = (
    config.json().get("lead_times_days", []) if config.status_code == 200 else []
)
choices = []
for i, line in enumerate(snapshot["lines"], 1):
    old = line["inputs"]["ships_in_days"]
    opts = sorted(set(available + [old]))
    choice = st.selectbox(
        f"Plate {i} lead time (calendar days)",
        opts,
        index=opts.index(old),
        format_func=lambda x: f"{x} days"
        + (" — unavailable; choose another" if x not in available else ""),
        key=f"lead_{qid}_{i}",
    )
    choices.append(choice)
if st.button("Review current pricing", type="primary"):
    r = api_post(path + "/revalidate", payload={"lead_times": choices})
    if r.status_code == 200:
        st.session_state["quote_review_" + qid] = {
            "result": r.json(),
            "choices": choices,
        }
    else:
        st.error(
            "A plate or lead time is unavailable. Choose an offered lead time or update the configuration."
            if r.status_code == 422
            else service_message(r.status_code)
        )
review = st.session_state.get("quote_review_" + qid)
if review and review["choices"] == choices:
    r = review["result"]
    st.table(
        [
            {
                "Plate": i,
                "Quoted": f"${old['total_price']:,.2f}",
                "Now": f"${new['total_price']:,.2f}",
                "Quoted lead time": old["inputs"]["ships_in_days"],
                "Current lead time": new["inputs"]["ships_in_days"],
            }
            for i, (old, new) in enumerate(zip(r["quoted_lines"], r["lines"]), 1)
        ]
    )
    st.write(
        f"Subtotal: **${float(r['quoted_subtotal']):,.2f} → ${float(r['current_subtotal']):,.2f}**"
    )
    ack = (
        st.checkbox("I've reviewed the changes", key="ack_" + r["review_id"])
        if r["changed"]
        else True
    )
    st.caption(
        "The existing checkout presents shipping services and payment. Current prices govern."
    )
    replace = (
        st.checkbox(
            "Replace my current Quote Cart with these saved configurations",
            key="replace_" + r["review_id"],
        )
        if st.session_state.get("cart")
        else True
    )
    if st.button(
        "Continue in Quote Cart", disabled=not ack or not replace, type="primary"
    ):
        st.session_state["cart"] = [
            {"line_id": str(uuid4()), "inputs": copy.deepcopy(l["inputs"])}
            for l in r["lines"]
        ]
        st.session_state["saved_quote_cart"] = {
            "quote_id": qid,
            "review_id": r["review_id"],
            "acknowledged": ack,
            "pricing_config_version": r["pricing_ref"],
            "inputs": [copy.deepcopy(l["inputs"]) for l in r["lines"]],
        }
        st.session_state.pop("quote_revision_source", None)
        st.session_state.pop("cart_checkout_attempt", None)
        st.switch_page(str(ROOT / "pages/3_Quote_Cart.py"))
