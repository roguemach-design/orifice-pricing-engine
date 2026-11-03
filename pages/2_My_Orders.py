"""Canonical authenticated customer order history. The standalone portal stays retired."""

import streamlit as st

from auth import current_user_id_hint, render_auth_sidebar, require_login
from customer_orders_state import bind_orders_owner
from customer_orders_ui import render

render_auth_sidebar(show_debug=False)
bind_orders_owner(st.session_state, current_user_id_hint())
require_login("Open Account and log in to view your orders.")
render()
