"""Customer routes; internal tools retain their own authorization and URLs."""

from pathlib import Path
import json
from urllib.parse import urlsplit

import streamlit as st
import streamlit.components.v1 as components


def render_integrated_checkout(checkout_url: str) -> bool:
    """Let the trusted landing host open the existing sandbox session outside the iframe."""
    if not st.session_state.get("integrated_landing"):
        return False
    target = urlsplit(checkout_url)
    if (target.scheme != "https" or target.netloc != "checkout.stripe.com"
            or not target.path.startswith("/c/pay/cs_test_")):
        st.error("Checkout is currently unavailable. Please contact sales@o-plates.com.")
        return True
    payload = json.dumps({"type": "oplates:checkout", "url": checkout_url}).replace("<", "\\u003c")
    components.html(
        "<script>for (const origin of ['https://o-plates.com', 'https://www.o-plates.com']) "
        f"window.parent.parent.postMessage({payload}, origin);</script>",
        height=0,
    )
    st.link_button("Continue to Stripe Checkout", checkout_url)
    return True


def _legacy_root():
    target = (
        "pages/4_Success.py"
        if st.query_params.get("session_id")
        else "pages/1_Quote.py"
    )
    st.switch_page(target)


def run_customer_app():
    st.set_page_config(page_title="O-Plates", layout="wide")
    selected = st.navigation(
        [
            st.Page(_legacy_root, default=True, visibility="hidden"),
            st.Page("pages/1_Quote.py", title="Configure your plate", url_path="Quote"),
            st.Page("pages/2_My_Orders.py", title="My Orders", url_path="My_Orders"),
            st.Page("pages/3_Quote_Cart.py", title="Quote Cart", url_path="Quote_Cart"),
            st.Page("pages/4_Success.py", url_path="Success", visibility="hidden"),
            st.Page(
                "pages/5_Drawing_Approval.py",
                url_path="Drawing_Approval",
                visibility="hidden",
            ),
            st.Page(
                "pages/6_Internal_Sourcing.py",
                url_path="Internal_Sourcing",
                visibility="hidden",
            ),
        ],
        position="hidden",
    )
    try:
        selected.run()
    finally:
        if selected.url_path != "Internal_Sourcing":
            render_customer_footer()


def render_customer_footer():
    from datetime import datetime, timezone

    st.markdown(
        f'<footer class="customer-footer">© {datetime.now(timezone.utc).year} O-Plates'
        ' · Operated by Rogue Machine LLC · '
        '<a href="mailto:sales@o-plates.com">Contact</a> · '
        '<a href="https://www.o-plates.com/terms.html" target="_blank" rel="noopener">Terms of Sale</a> · '
        '<a href="https://www.o-plates.com/privacy.html" target="_blank" rel="noopener">Privacy Policy</a></footer>',
        unsafe_allow_html=True,
    )


def render_customer_shell():
    """Render on direct page entry as well as initialized root navigation."""
    st.markdown(
        """<style>
        [data-testid="stMainBlockContainer"]{max-width:1500px}
        [data-testid="stButtonGroup"] button{min-height:44px;white-space:normal}
        [data-testid="stButtonGroup"] button[aria-pressed="true"]{font-weight:800;border-width:2px}
        .customer-footer{margin-top:2rem;padding:1rem 0;border-top:1px solid #303846;
          font-size:.8rem;color:#b2bed3;line-height:1.8;overflow-wrap:anywhere}
        .customer-footer a{color:inherit}
        @media(max-width:700px){
          [data-testid="stMainBlockContainer"]{padding-left:1rem;padding-right:1rem}
          [data-testid="stHorizontalBlock"]{flex-wrap:wrap}
          [data-testid="stColumn"]{min-width:min(100%,280px);flex:1 1 100%}
        }
    </style>""",
        unsafe_allow_html=True,
    )
    # Presentation only: never reads or posts form/auth/order data.
    if st.query_params.get("integrated") == "1":
        st.session_state["integrated_landing"] = True
    if st.session_state.get("integrated_landing"):
        components.html(
            "<script>" + (Path(__file__).resolve().parent / "assets" / "configurator-layout-bridge.js").read_text() + "</script>",
            height=0,
        )
    with st.container(horizontal=True):
        st.page_link(
            Path(__file__).resolve().parent / "pages/1_Quote.py",
            label="Configure your plate",
        )
        st.page_link(
            Path(__file__).resolve().parent / "pages/2_My_Orders.py", label="My Orders"
        )
        st.page_link(
            Path(__file__).resolve().parent / "pages/3_Quote_Cart.py",
            label="Quote Cart",
        )
