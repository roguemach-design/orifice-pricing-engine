# pages/3_Quote_Cart.py
from datetime import datetime
from typing import Any, Dict, List

import streamlit as st

from auth import render_auth_sidebar, require_login


render_auth_sidebar(show_debug=False)
require_login("Log in in the sidebar to manage quote carts.")


st.title("Quote Cart")
st.caption("Build a multi-line quote with multiple configured plates. PDF + checkout next.")

if "cart" not in st.session_state or not isinstance(st.session_state.cart, list):
    st.session_state.cart = []

cart: List[Dict[str, Any]] = st.session_state.cart

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

st.subheader(f"Line items ({len(cart)})")

# Render each line item with editable quantity + remove
for idx, item in enumerate(cart):
    inputs = item.get("inputs") or {}
    line_id = item.get("line_id", f"line-{idx}")

    with st.container(border=True):
        cols = st.columns([2, 1, 1])
        with cols[0]:
            st.markdown(
                f"**{idx+1}. {inputs.get('material')}** | "
                f"{inputs.get('thickness')} in | "
                f"Paddle {inputs.get('paddle_dia')} in | "
                f"Bore {inputs.get('bore_dia')} in"
            )
            st.caption(f"Handle label: {inputs.get('handle_label') or 'No label'}")

        with cols[1]:
            new_qty = st.number_input(
                "Qty",
                min_value=1,
                value=int(inputs.get("quantity") or 1),
                step=1,
                key=f"qty_{line_id}",
            )
            # update stored qty live
            inputs["quantity"] = int(new_qty)
            item["inputs"] = inputs

        with cols[2]:
            if st.button("Remove", key=f"rm_{line_id}"):
                st.session_state.cart = [x for x in st.session_state.cart if x.get("line_id") != line_id]
                st.rerun()

        with st.expander("Show configuration JSON"):
            st.json(inputs)

st.divider()

# Placeholder totals (real totals come from API once we implement quote-save/checkout-from-cart)
st.subheader("Next actions")

c1, c2 = st.columns(2)
with c1:
    st.button("📄 Generate PDF Quote (next)", disabled=True)
    st.caption("Tomorrow: we’ll generate a PDF with line items + quote # and store it.")
with c2:
    st.button("💳 Checkout All Items (next)", disabled=True)
    st.caption("Tomorrow: we’ll create a checkout session from all cart items.")

st.info(
    "MVP today: build a multi-line cart. Next: persist quotes to Postgres + generate PDF + checkout from quote number."
)
