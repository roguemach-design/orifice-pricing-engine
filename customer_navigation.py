"""Customer routes; internal tools retain their own authorization and URLs."""

from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components


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
    selected.run()


def render_customer_shell():
    """Render on direct page entry as well as initialized root navigation."""
    st.markdown(
        """<style>
        [data-testid="stMainBlockContainer"]{max-width:1500px}
        [data-testid="stButtonGroup"] button{min-height:44px;white-space:normal}
        [data-testid="stButtonGroup"] button[aria-pressed="true"]{font-weight:800;border-width:2px}
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
            """<script>
          const app = window.parent;
          const block = app.document.querySelector('[data-testid="stMainBlockContainer"]');
          let previous = 0;
          function resize() {
            if (!block) return;
            const height = Math.ceil(block.getBoundingClientRect().height + 100);
            if (Math.abs(height - previous) < 4) return;
            previous = height;
            for (const origin of ['https://www.o-plates.com','https://o-plates.com']) {
              app.parent.postMessage({type:'oplates:height',height},origin);
            }
          }
          if (block) {new ResizeObserver(resize).observe(block); resize();}
        </script>""",
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
