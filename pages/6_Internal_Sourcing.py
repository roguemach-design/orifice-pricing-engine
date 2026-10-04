"""Internal staging review; the API enforces admin authorization on every request."""

import os
import requests
import streamlit as st

st.set_page_config(page_title="O-Plates Internal Sourcing", layout="wide")
API = os.environ.get("API_BASE", "").rstrip("/")
if API != "https://oplates-pricing-api-staging.onrender.com":
    st.stop()
st.title("Frozen Plate — Internal Sourcing")
st.caption(
    "Staging only. Route selections do not submit files or release manufacturing."
)
key = st.text_input("Internal admin credential", type="password")
if not key:
    st.stop()
headers = {"x-api-key": key}


def call(method, path, **kwargs):
    try:
        response = requests.request(
            method, API + path, headers=headers, timeout=120, **kwargs
        )
    except requests.RequestException:
        st.error("Staging service unavailable.")
        st.stop()
    if response.status_code != 200:
        st.error("Request unavailable. Check admin access and the current revision.")
        st.stop()
    return response


orders = call("GET", "/admin/orders").json()
completed = [o for o in orders if o["status"] == "completed"]
if not completed:
    st.info("No completed staging orders.")
    st.stop()
order_id = st.selectbox("Completed order", [o["id"] for o in completed])
if st.button("Retry completed-order drawing capture"):
    states = call("POST", f"/admin/frozen-plates/orders/{order_id}/complete").json()
    st.json(states)
    if any(s["state"] == "HOLD" for s in states):
        st.warning(
            "HOLD: incomplete or invalid manufacturing configuration requires review."
        )
plates = call("GET", "/admin/frozen-plates", params={"order_id": order_id}).json()
for plate in plates:
    st.subheader(f"{plate['line_id']} · {plate['lifecycle']}")
    detail = call("GET", "/admin/frozen-plates/" + plate["id"]).json()
    rev = detail["revision"]
    if not rev:
        st.warning("No complete drawing revision.")
        continue
    st.write(f"Plate {plate['id']} · Revision R{rev['number']} · {rev['id']}")
    st.write("Spec SHA-256: " + rev["spec_sha256"])
    st.dataframe(
        [
            {
                "Kind": kind,
                "Filename": a["filename"],
                "Bytes": a["size"],
                "SHA-256": a["sha256"],
            }
            for kind, a in rev["artifacts"].items()
        ],
        hide_index=True,
    )
    for delivery in detail["deliveries"]:
        if st.button("Load captured confirmation", key="capture-" + delivery["id"]):
            eml = call(
                "GET", "/admin/frozen-plates/deliveries/" + delivery["id"] + "/capture"
            ).content
            st.download_button(
                "Download captured email",
                eml,
                file_name="confirmation.eml",
                mime="message/rfc822",
                key="eml-" + delivery["id"],
            )
    if detail["approvals"]:
        st.success("Current revision approved")
        dxf = call("GET", f"/admin/frozen-plates/revisions/{rev['id']}/dxf")
        st.download_button(
            "Download exact approved rough DXF",
            dxf.content,
            file_name=rev["artifacts"]["dxf"]["filename"],
            mime="application/dxf",
            key="dxf-" + rev["id"],
        )
        route = st.selectbox(
            "SOURCE ROUGH BLANK",
            ["SENDCUTSEND", "ALRO", "ROGUE_INTERNAL"],
            key="route-" + rev["id"],
        )
        if st.button("Record sourcing route", key="source-" + rev["id"]):
            call(
                "POST",
                f"/admin/frozen-plates/revisions/{rev['id']}/source",
                json={"route": route},
            )
            st.success("Route recorded. No vendor submission or manufacturing release.")
        st.json(detail["sourcing"])
    else:
        st.info("Customer approval is required before sourcing or DXF access.")
    with st.expander("Create a new immutable revision from the server order record"):
        part = st.text_input("Drawing part identifier", key="part-" + plate["id"])
        reason = st.text_input("Revision reason", key="reason-" + plate["id"])
        if st.button("Create revised drawing", key="revision-" + plate["id"]):
            call(
                "POST",
                f"/admin/frozen-plates/orders/{order_id}",
                json={
                    "line_index": int(plate["line_id"].split("-")[1]) - 1,
                    "part_identifier": part,
                    "expected_current": rev["id"],
                    "reason": reason,
                },
            )
            st.rerun()
