from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_marketing_start_quote_links_directly_to_configurator():
    marketing_html = (ROOT / "o-plates landing" / "index.html").read_text()

    assert (
        'class="btn btn--primary btn--lg" href="https://quote.o-plates.com/Quote"'
        in marketing_html
    )


def test_application_root_routes_directly_to_quote_without_interstitial():
    root_app = (ROOT / "app.py").read_text()

    assert root_app.rstrip().endswith('st.switch_page("pages/1_Quote.py")')
    assert 'st.title("O-Plates")' not in root_app
    assert "Build a Plate" not in root_app
    assert "My Orders" not in root_app


def test_connection_details_are_hidden_in_customer_sidebar():
    auth_source = (ROOT / "auth.py").read_text()
    customer_pages = [
        ROOT / "pages" / "1_Quote.py",
        ROOT / "pages" / "2_My_Orders.py",
        ROOT / "pages" / "3_Quote_Cart.py",
        ROOT / "pages" / "4_Success.py",
    ]

    assert "if show_debug:\n            _render_connection_debug()" in auth_source
    for page in customer_pages:
        assert "render_auth_sidebar(show_debug=False)" in page.read_text()
    assert 'st.subheader("Account")' in auth_source


def test_quote_keeps_engineering_workflow_and_prominent_summary():
    quote_source = (ROOT / "pages" / "1_Quote.py").read_text()

    expected_order = [
        'st.caption("PRODUCT")',
        'st.caption("DIMENSIONS")',
        '"Plate outside diameter (in.)"',
        '"Bore diameter (in.)"',
        '"Handle width (in.)"',
        '"Handle length from bore center (in.)"',
        'st.caption("REQUIREMENTS")',
        'st.caption("DELIVERY")',
    ]
    positions = [quote_source.index(item) for item in expected_order]

    assert positions == sorted(positions)
    assert 'st.subheader("Configuration Drawing")' in quote_source
    assert 'with st.container(border=True):\n        st.subheader("Quote Summary")' in quote_source
    assert 'c1.metric("Unit price"' in quote_source
    assert 'c2.metric("Total price"' in quote_source
    assert "calendar days" in quote_source


def test_quote_keeps_lean_owner_approved_controls():
    quote_source = (ROOT / "pages" / "1_Quote.py").read_text()

    assert '"Plate style"' not in quote_source
    assert 'st.checkbox("Chamfer", value=False)' in quote_source
    assert '"Chamfer Width (in.)"' in quote_source
    assert 'value=None' in quote_source
    assert '"Lead time"' in quote_source
    assert 'format_func=lambda days: f"{days} calendar days"' in quote_source
    assert quote_source.count("Estimated to ship within") == 1


def test_success_page_allows_guest_confirmation():
    success_source = (ROOT / "pages" / "4_Success.py").read_text()

    assert "require_login" not in success_source
    assert 'order.get("status") != "completed"' in success_source
    assert 'st.title("Payment received ✅")' in success_source


def test_customer_entrypoints_do_not_fall_back_to_production_api():
    customer_files = [
        ROOT / "auth.py",
        ROOT / "pages" / "1_Quote.py",
        ROOT / "pages" / "3_Quote_Cart.py",
        ROOT / "pages" / "4_Success.py",
    ]

    for path in customer_files:
        source = path.read_text()
        assert "https://orifice-pricing-api.onrender.com" not in source


def test_legacy_entrypoints_are_routing_only_compatibility_shims():
    expected_routes = {
        "ui_app.py": 'st.switch_page("pages/1_Quote.py")',
        "customer_portal.py": 'st.switch_page("pages/2_My_Orders.py")',
        "my_orders_app.py": 'st.switch_page("pages/2_My_Orders.py")',
        "quote_cart_app.py": 'st.switch_page("pages/3_Quote_Cart.py")',
    }

    for filename, route in expected_routes.items():
        source = (ROOT / filename).read_text()
        assert route in source
        assert "calculate_quote" not in source
        assert "0.062" not in source
        assert "SUPABASE_URL" not in source
