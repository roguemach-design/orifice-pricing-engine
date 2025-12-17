import streamlit as st

from pricing_engine import QuoteInputs, calculate_quote
import pricing_config as cfg

st.set_page_config(page_title="Orifice Plate Instant Quote", layout="centered")
st.title("Orifice Plate Instant Quote")


    # 2) Material Type
    material = st.selectbox(
        "Material Type",
        options=list(cfg.PRICE_PER_SQ_IN.keys())
    )

    # 3) Plate Thickness
    thickness = st.selectbox(
        "Plate Thickness (in)",
        options=sorted(cfg.PRICE_PER_SQ_IN[material].keys())
    )

    # 4) Handle Width
    handle_width = st.number_input(
        "Handle Width (in)",
        min_value=0.0,
        value=1.5,
        step=0.01
    )

    # 5) Handle Length (From Bore)
    handle_length = st.number_input(
        "Handle Length from Bore Center (in)",
        min_value=0.0,
        value=9.0,
        step=0.01
    )

    # 6) Handle Labeling
    handle_labeling = st.checkbox(
        "Handle Labeling",
        value=False,
        help="Include permanent handle marking or engraving"
    )

    # 7) Paddle Diameter
    paddle_dia = st.number_input(
        "Paddle Diameter (in)",
        min_value=0.01,
        value=3.0,
        step=0.01
    )

    # 8) Bore Diameter
    bore_dia = st.number_input(
        "Bore Diameter (in)",
        min_value=0.01,
        value=1.0,
        step=0.01
    )

    # 9) Bore Tolerance
    bore_tolerance = st.selectbox(
        "Bore Tolerance (± in)",
        options=sorted(cfg.INSPECTION_MINS_BY_TOL.keys())
    )

    # 10) Chamfer
    chamfer = st.checkbox(
        "Chamfer",
        value=True
    )

    # 11) Chamfer Width (conditional display)
    chamfer_width = 0.0
    if chamfer:
        chamfer_width = st.number_input(
            "Chamfer Width (in)",
            min_value=0.0,
            value=0.06,
            step=0.01
        )

    # 12) Ships In (days)
    ships_in_days = st.selectbox(
        "Ships in (days)",
        options=sorted(cfg.LEAD_TIME_MULTIPLIER.keys())
    )

    submitted = st.form_submit_button("Get Instant Quote")

