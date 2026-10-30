"""Canonical authenticated customer order history. The standalone portal stays retired."""
from auth import render_auth_sidebar, require_login
from customer_orders_ui import render

render_auth_sidebar(show_debug=False)
require_login('Open Account and log in to view your orders.')
render()
