import streamlit as st
from auth import render_auth_sidebar

st.set_page_config(page_title="O-Plates", layout="wide")
render_auth_sidebar()

st.title("O-Plates")
st.caption("Configure → Quote → Order → Reorder")

