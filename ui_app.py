import streamlit as st
st.write("✅ ui_app.py is running")

try:
    from pricing_engine import QuoteInputs, calculate_quote
    import pricing_config as cfg
    st.write("✅ Imported pricing_engine + pricing_config")
except Exception as e:
    st.error("Import failed:")
    st.exception(e)
    st.stop()
st.title("Orifice Plate Instant Quote")
st.write("If you can see this title, the UI is rendering.")


