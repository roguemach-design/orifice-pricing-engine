"""Owner-only chart of aggregate data, without customer identities."""
import altair as alt
import pandas as pd
import streamlit as st


def render(client):
    st.subheader("Sales")
    labels = {"1 Year": "1y", "6 Months": "6m", "3 Months": "3m", "1 Month": "1m"}
    selected = st.radio("Sales period", list(labels), horizontal=True, key="mc_sales_period")
    data = client.json("/admin/sales", params={"period": labels[selected]})
    st.markdown(f"**LIVE paid order total · ${data['total_cents'] / 100:,.2f}**")
    st.caption(f"{selected} · {data['start'][:10]} through {data['end'][:10]} · UTC · {data['order_count']} paid orders")
    rows = pd.DataFrame([{"Date": p["date"], "Total": p["amount_cents"] / 100, "Orders": p["order_count"]} for p in data["points"]])
    chart = alt.Chart(rows).mark_line(color="#4B7DFF", point=alt.OverlayMarkDef(color="#6EE7FF"), strokeWidth=3).encode(
        x=alt.X("Date:T", title="Paid date (UTC)"),
        y=alt.Y("Total:Q", title="LIVE paid order total (USD)", axis=alt.Axis(format="$,.0f"), scale=alt.Scale(zero=True)),
        tooltip=[alt.Tooltip("Date:T", format="%b %d, %Y"), alt.Tooltip("Total:Q", format="$,.2f"), "Orders:Q"],
    ).properties(height=220).configure(background="#121A26").configure_axis(labelColor="#B2BED3", titleColor="#E9EEF7", gridColor="#223049")
    st.altair_chart(chart, width="stretch")
    if not data["order_count"]:
        st.caption("No qualifying LIVE paid sales in this period. TEST and OWNER TEST orders are excluded.")
    st.caption(data["basis"])
