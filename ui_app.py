import streamlit as st

from pricing_engine import QuoteInputs, calculate_quote
import pricing_config as cfg

st.set_page_config(page_title="Orifice Plate Instant Quote", layout="centered")

st.title("Orifice Plate Instant Quote")

with st.form("quote_form"):
    col1, col2 = st.columns(2)

    with col1:
        quantity = st.number_input("Quantity", min_value=1, value=1, step=1)
        material = st.selectbox("Material", options=list(cfg.PRICE_PER_SQ_IN.keys()))
        thickness = st.selectbox(
            "Thickness (in)",
            options=sorted(cfg.PRICE_PER_SQ_IN[material].keys()),
        )
        ships_in_days = st.selectbox(
            "Ships in (days)",
            options=sorted(cfg.LEAD_TIME_MULTIPLIER.keys()),
        )

    with col2:
        paddle_dia = st.number_input(
            "Paddle Diameter (in)", min_value=0.01, value=3.0, step=0.01
        )
        handle_length = st.number_input(
            "Handle Length from Bore Center (in)", min_value=0.0, value=9.0, step=0.01
        )
        handle_width = st.number_input(
            "Handle Width (in)", min_value=0.0, value=1.5, step=0.01
        )

    bore_dia = st.number_input(
        "Bore Diameter (in)", min_value=0.01, value=1.0, step=0.01
    )
    bore_tolerance = st.selectbox(
        "Bore Tolerance (± in)", options=sorted(cfg.INSPECTION_MINS_BY_TOL.keys())
    )
    chamfer = st.checkbox("Chamfer", value=True)

    submitted = st.form_submit_button("Calculate Quote")

if submitted:
    inputs = QuoteInputs(
        quantity=int(quantity),
        material=str(material),
        thickness=float(thickness),
        handle_width=float(handle_width),
        handle_length_from_bore=float(handle_length),
        paddle_dia=float(paddle_dia),
        bore_dia=float(bore_dia),
        bore_tolerance=float(bore_tolerance),
        chamfer=bool(chamfer),
        ships_in_days=int(ships_in_days),
    )

    try:
        result = calculate_quote(inputs)

        st.success("Quote calculated")

        st.metric("Unit Price", f"${result['unit_price']:,.2f}")
        st.metric("Total Price", f"${result['total_price']:,.2f}")

        with st.expander("Pricing breakdown"):
            st.json(result)

    except Exception as e:
        st.error("Error calculating quote")
        st.exception(e)




