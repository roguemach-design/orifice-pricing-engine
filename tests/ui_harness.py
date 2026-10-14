"""Run a customer page with the same registered routes used by the service."""

from pathlib import Path
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]


def customer_page_test(path, *, default_timeout=20):
    routes = [
        ("pages/1_Quote.py", "Quote"),
        ("pages/2_My_Orders.py", "My_Orders"),
        ("pages/3_Quote_Cart.py", "Quote_Cart"),
        ("pages/4_Success.py", "Success"),
        ("pages/5_Drawing_Approval.py", "Drawing_Approval"),
        ("pages/6_Internal_Sourcing.py", "Internal_Sourcing"),
    ]
    script = "import streamlit as st\n"
    declarations = [
        f"st.Page({str(ROOT/p)!r}, url_path={route!r}, default={p==path!r}, visibility='hidden')"
        for p, route in routes
    ]
    script += (
        "st.navigation([" + ",".join(declarations) + "], position='hidden').run()\n"
    )
    return AppTest.from_string(script, default_timeout=default_timeout)
