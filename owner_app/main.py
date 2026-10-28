"""Dedicated owner service. Explicit navigation excludes all customer routes."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import streamlit as st
from manufacturing_control.app import run

st.navigation([st.Page(run, title="Manufacturing Control", default=True)], position="hidden").run()
