# auth.py
import os
from typing import Dict, Optional

import requests
import streamlit as st
from supabase import Client, create_client


# ----------------------------
# Env
# ----------------------------
API_BASE = os.environ.get("API_BASE", "https://orifice-pricing-api.onrender.com").rstrip("/")
SUPABASE_URL = (os.environ.get("SUPABASE_URL") or "").strip()
SUPABASE_ANON_KEY = (os.environ.get("SUPABASE_ANON_KEY") or "").strip()


# ----------------------------
# Session init
# ----------------------------
def _ensure_auth_state() -> None:
    if "auth" not in st.session_state or not isinstance(st.session_state.auth, dict):
        st.session_state.auth = {
            "access_token": None,
            "refresh_token": None,
            "user": None,
            "email": None,
        }


# ----------------------------
# Supabase client
# ----------------------------
def sb() -> Client:
    if not SUPABASE_URL or not SUPABASE_ANON_KEY:
        st.error("Missing SUPABASE_URL / SUPABASE_ANON_KEY env vars on this Streamlit service.")
        st.stop()
    return create_client(SUPABASE_URL, SUPABASE_ANON_KEY)


# ----------------------------
# Auth helpers
# ----------------------------
def is_logged_in() -> bool:
    _ensure_auth_state()
    return bool(st.session_state.auth.get("access_token"))


def logout() -> None:
    _ensure_auth_state()
    st.session_state.auth = {"access_token": None, "refresh_token": None, "user": None, "email": None}
    st.rerun()


def auth_headers() -> Dict[str, str]:
    _ensure_auth_state()
    tok = st.session_state.auth.get("access_token")
    return {"Authorization": f"Bearer {tok}"} if tok else {}


def require_login(message: str = "Log in in the sidebar to continue.") -> None:
    if not is_logged_in():
        st.info(message)
        st.stop()


# ----------------------------
# Convenience API call
# ----------------------------
def api_get(path: str, *, params: dict | None = None, timeout: int = 30) -> requests.Response:
    return requests.get(f"{API_BASE}{path}", headers=auth_headers(), params=params, timeout=timeout)


# ----------------------------
# Sidebar UI
# ----------------------------
def render_auth_sidebar(*, show_debug: bool = True) -> None:
    """
    Call this at the top of app.py and at the top of each page file.
    It renders a consistent login/logout experience and stores session tokens in st.session_state.auth.
    """
    _ensure_auth_state()

    with st.sidebar:
        st.subheader("Connection")
        st.write("API Base:")
        st.code(API_BASE)

        # It's safe to show SUPABASE_URL (not the key)
        st.caption("Supabase URL:")
        st.code(SUPABASE_URL or "(missing)")

        st.divider()
        st.subheader("Login")

        if not is_logged_in():
            email = st.text_input(
                "Email",
                value=st.session_state.auth.get("email") or "",
                placeholder="you@company.com",
            ).strip()

            col1, col2 = st.columns(2)
            with col1:
                send_code = st.button("Send code")
            with col2:
                verify_code = st.button("Verify code")

            # Supabase sometimes uses 6 digits, sometimes 8. Don’t cap at 6.
            otp_code = st.text_input(
                "OTP code",
                value="",
                placeholder="123456 (sometimes 8 digits)",
                max_chars=12,
            ).strip()

            if send_code:
                if not email:
                    st.error("Enter your email first.")
                else:
                    try:
                        sb().auth.sign_in_with_otp({"email": email})
                        st.session_state.auth["email"] = email
                        st.success("Code sent. Check your email.")
                    except Exception as e:
                        st.error(f"Failed to send code: {e}")

            if verify_code:
                if not email or not otp_code:
                    st.error("Enter email + the OTP code.")
                elif (not otp_code.isdigit()) or (len(otp_code) < 6):
                    st.error("OTP must be numeric and at least 6 digits.")
                else:
                    try:
                        resp = sb().auth.verify_otp(
                            {
                                "email": email,
                                "token": otp_code,
                                "type": "email",
                            }
                        )

                        # supabase-py may return an object with .session/.user OR a dict
                        session = getattr(resp, "session", None)
                        user = getattr(resp, "user", None)

                        if session is None and isinstance(resp, dict):
                            session = resp.get("session")
                            user = resp.get("user")

                        # Extract tokens across both shapes
                        access_token: Optional[str] = None
                        refresh_token: Optional[str] = None

                        if isinstance(session, dict):
                            access_token = session.get("access_token")
                            refresh_token = session.get("refresh_token")
                        else:
                            access_token = getattr(session, "access_token", None)
                            refresh_token = getattr(session, "refresh_token", None)

                        if not access_token:
                            st.error("OTP verify succeeded but no access token was returned. Check Supabase Auth settings.")
                            st.stop()

                        st.session_state.auth = {
                            "access_token": access_token,
                            "refresh_token": refresh_token,
                            "user": user,
                            "email": email,
                        }
                        st.success("Logged in.")
                        st.rerun()

                    except Exception as e:
                        st.error(f"Verify failed: {e}")

        else:
            st.success(f"Logged in as: {st.session_state.auth.get('email')}")
            if st.button("Log out"):
                logout()

        # ----------------------------
        # TEMP DEBUG
        # ----------------------------
        if show_debug:
            st.divider()
            st.subheader("DEBUG (temporary)")
            tok = st.session_state.auth.get("access_token")
            st.write("Has access token:", bool(tok))
            if tok:
                st.write("Token prefix:", tok[:20])

