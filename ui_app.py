import streamlit as st

from pricing_engine import QuoteInputs, calculate_quote
import pricing_config as cfg

st.set_page_config(page_title="Orifice Plate Instant Quote", layout="centered")
st.title("Orifice Plate Instant Quote")

with st.form("quote_form"):
    # 1) Qty
    quantity = st.number_input("Qty", min_value=1, value=1, step=1)

    # 2) Material Type
    material = st.selectbox("Material Type", options=list(cfg.PRICE_PER_SQ_IN.keys()))

    # 3) Plate thickness
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
        "Handle Length (From Bore) (in)",
        min_value=0.0,
        value=9.0,
        step=0.01
    )

# 6) Handle Marking
handle_labeling = st.checkbox(
    "Handle Marking",
    value=False,
    help="Include permanent handle marking or engraving"
)

handle_marking_text = ""
if handle_labeling:
    handle_marking_text = st.text_input(
        "Handle Marking Text",
        placeholder="e.g. Line 4 – 6 in – 304 SS",
        help="Enter the exact text to be marked on the handle"
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

    # 9) Bore tolerance
    tol_options = sorted(cfg.INSPECTION_MINS_BY_TOL.keys())
bore_tolerance = st.selectbox(
    "Bore Tolerance (± in)",
    options=tol_options,
    index=tol_options.index(0.005) if 0.005 in tol_options else 0
)

    )

    # 10) Chamfer
    chamfer = st.checkbox("Chamfer", value=True)

    # 11) Chamfer width
    chamfer_width = 0.0
    if chamfer:
        chamfer_width = st.number_input(
            "Chamfer Width (in)",
            min_value=0.0,
            value=0.06,
            step=0.01
        )

    # 12) Ships in (days)
    ships_options = sorted(cfg.LEAD_TIME_MULTIPLIER.keys())
ships_in_days = st.selectbox(
    "Ships in (days)",
    options=ships_options,
    index=ships_options.index(21) if 21 in ships_options else 0
)

    )

    submitted = st.form_submit_button("Get Instant Quote")

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

    result = calculate_quote(inputs)

    st.success("Quote calculated")
    st.metric("Unit Price", f"${result['unit_price']:,.2f}")
    st.metric("Total Price", f"${result['total_price']:,.2f}")

    with st.expander("Detailed Cost Breakdown"):
        st.json(result)

    # Keep captured fields visible for now (not yet priced)
    with st.expander("Selections (not yet priced)"):
        st.write({"handle_labeling": handle_labeling, "chamfer_width": chamfer_width})

