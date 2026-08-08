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
