"""Owner-only diagnostics, using the existing protected transport."""

import streamlit as st


def run(client):
    st.title("Customer Journey")
    st.caption(
        "Anonymous, opt-in diagnostics · no session replay · no historical reconstruction"
    )
    windows = {"24 hours": 24, "7 days": 168, "30 days": 720, "90 days": 2160}
    cols = st.columns(2)
    label = cols[0].selectbox(
        "Date range", list(windows), index=1, key="mc_journey_window"
    )
    internal = cols[1].checkbox(
        "Internal / staging traffic only", key="mc_journey_internal"
    )
    data = client.json(
        "/admin/journey",
        params={"hours": windows[label], "internal": str(internal).lower()},
    )
    if not data.get("enabled"):
        st.info(data.get("message", "Collection is disabled."))
        return
    st.caption("As of " + data["generated_at"] + " · Counts: " + data["funnel_unit"])
    labels = {
        "landing": "Landing",
        "configurator": "Configurator",
        "configuration": "Valid configuration",
        "quote": "Quote displayed",
        "cart": "Cart",
        "pdf_quote": "PDF quote requested",
        "checkout": "Checkout attempted",
        "paid_order": "Paid order (server confirmed)",
    }
    st.subheader("Stage reaches")
    st.dataframe(
        [{"Stage": labels[k], "Count": v} for k, v in data["funnel"].items()],
        hide_index=True,
        width="stretch",
    )
    st.caption(
        "Cart and PDF are optional branches. Direct entry can skip landing. Counts are not a forced linear conversion rate."
    )
    st.subheader("Top errors and restrictions · last 7 days maximum")
    (
        st.dataframe(data["errors"], hide_index=True, width="stretch")
        if data["errors"]
        else st.info("No observed blockers in this diagnostic window.")
    )
    st.subheader("Anonymous sessions · last 7 days maximum")
    rows = data["sessions"]
    if rows:
        st.dataframe(
            [{k: v for k, v in r.items() if k != "timeline"} for r in rows],
            hide_index=True,
            width="stretch",
        )
        sid = st.selectbox(
            "Session timeline", [r["session"] for r in rows], key="mc_journey_session"
        )
        chosen = next(r for r in rows if r["session"] == sid)
        st.caption(
            "Last successful step: "
            + chosen["last_successful_step"]
            + " · "
            + chosen["classification"]
        )
        st.dataframe(chosen["timeline"], hide_index=True, width="stretch")
    else:
        st.info(
            "No opted-in sessions observed. This does not mean there were no customers."
        )
    for note in data["notes"]:
        st.caption(note)
    st.caption(
        "Retention: 7 days diagnostic records; 90 days daily aggregates. Session list limited to the latest 100 sessions."
    )
    st.caption(
        "Collection health: "
        + str(data["coverage"]["queue_drops_or_storage_failures"])
        + " dropped/failed server observations since process start."
    )
