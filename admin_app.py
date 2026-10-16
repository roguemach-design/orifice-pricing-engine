"""Single secured entrypoint; automatic pages-directory routes are disabled."""
import runpy
from pathlib import Path
import streamlit as st

st.set_page_config(page_title="O-Plates Admin", layout="wide")


def admin_page():
    runpy.run_path(str(Path(__file__).with_name("legacy_admin_ui.py")))


st.navigation([st.Page(admin_page, title="Owner administration", default=True)]).run()
