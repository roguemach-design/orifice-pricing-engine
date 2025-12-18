import streamlit as st

from pricing_engine import QuoteInputs, calculate_quote
import pricing_config as cfg

st.set_page_config(page_title="Orifice Plate Instant Quote", layout="centered")

# Heading font/style
st.markdown(
    """
    <style>
    h1 {
      font-family: Arial, sans-serif;
      font-weight: 800;
      letter-spacing: 0.2px;
      margin-bottom: 0.25rem;
    }
    </style>
    """,
    unsafe_allow_html=True
)

st.title("Orifice Plate Instant Quote")

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

# 6) Handle Marking (recommended: show text only when checked)
handle_marking = st.checkbox(
    "Handle Marking",
    value=False,
    help="Include permanent handle marking or engraving"
)

handle_marking_text = ""
if handle_marking:
    handle_marking_text = st.text_input(
        "Handle Marking Text",
        placeholder="e.g. UPSTREAM BORE XXX BETA XXX",
        help="Enter the exact text to be marked on the handle"
    )

# 7) Paddle Diameter (max 48")
paddle_dia = st.number_input(
    "Paddle Diameter (in)",
    min_value=0.01,
    max_value=48.0,
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

# 9) Bore tolerance (default 0.005, dropdown only)
tol_options = sorted(cfg.INSPECTION_MINS_BY_TOL.keys())
bore_tolerance = st.selectbox(
    "Bore Tolerance (± in)",
    options=tol_options,
    index=tol_options.index(0.005) if 0.005 in tol_options else 0,
    help="Tighter tolerances require additional inspection time."
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

# 12) Ships in (days) (default 21)
ships_options = sorted(cfg.LEAD_TIME_MULTIPLIER.keys())
ships_in_days = st.selectbox(
    "Ships in (days)",
    options=ships_options,
    index=ships_options.index(21) if 21 in ships_options else 0
)
# --- Validation flags ---
bore_error = bore_dia >= paddle_dia
handle_error = handle_length <= (paddle_dia / 2)

# Inline-style errors (appear right after inputs)
if bore_error:
    st.error("Bore Diameter must be smaller than Paddle Diameter.")

if handle_error:
    st.error("Handle Length (From Bore) must be longer than the Paddle Radius.")

st.divider()
st.subheader("Quote Summary")

# --- Customer-friendly validation ---
errors = []

if bore_dia >= paddle_dia:
    errors.append("Bore Diameter must be smaller than Paddle Diameter.")

paddle_radius = paddle_dia / 2
if handle_length <= paddle_radius:
    errors.append("Handle Length (From Bore) must be longer than the Paddle Radius.")

if paddle_dia > 48.0:
    errors.append("Paddle Diameter cannot exceed 48 inches.")

if errors:
    for msg in errors:
        st.error(msg)
    st.info("Adjust the inputs above to see pricing.")
    st.stop()

# --- Live calculation ---
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

c1, c2 = st.columns(2)
c1.metric("Unit Price", f"${result['unit_price']:,.2f}")
c2.metric("Total Price", f"${result['total_price']:,.2f}")





