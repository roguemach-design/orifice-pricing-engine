# auth.py
import base64
import json
import os
import time
from typing import Dict, Optional

import requests
import streamlit as st
from supabase import Client, create_client

# Cookie manager (for "stay logged in")
try:
    import extra_streamlit_components as stx
except Exception:
    stx = None


# ----------------------------
# Env
# ----------------------------
API_BASE = os.environ.get("API_BASE", "https://orifice-pricing-api.onrender.com").rstrip("/")
SUPABASE_URL = (os.environ.get("SUPABASE_URL") or "").strip()
SUPABASE_ANON_KEY = (os.environ.get("SUPABASE_ANON_KEY") or "").strip()

COOKIE_NAME = os.environ.get("AUTH_COOKIE_NAME", "oplates_auth")
COOKIE_TTL_DAYS = int(os.environ.get("AUTH_COOKIE_TTL_DAYS", "14"))
REFRESH_SKEW_SECONDS = 120


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
# Cookie manager (singleton, NO caching)
# ----------------------------
def _cookie_mgr():
    if stx is None:
        return None

    if "_cookie_mgr_instance" not in st.session_state:
        st.session_state["_cookie_mgr_instance"] = stx.CookieManager()

    return st.session_state["_cookie_mgr_instance"]


def _cookie_get() -> Optional[dict]:
    cm = _cookie_mgr()
    if cm is None:
        return None
    raw = cm.get(COOKIE_NAME)
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        return None


def _cookie_set(payload: dict) -> None:
    cm = _cookie_mgr()
    if cm is None:
        return
    cm.set(
        COOKIE_NAME,
        json.dumps(payload),
        expires_at=time.time() + (COOKIE_TTL_DAYS * 86400),
    )


def _cookie_clear() -> None:
    cm = _cookie_mgr()
    if cm is None:
        return
    cm.delete(COOKIE_NAME)


def _restore_auth_from_cookie_if_needed() -> None:
    _ensure_auth_state()

    if st.session_state.auth.get("access_token"):
        return

    data = _cookie_get()
    if not data:
        return

    st.session_state.auth = {
        "access_token": data.get("access_token"),
        "refresh_token": data.get("refresh_token"),
        "user": None,
        "email": data.get("email"),
    }


# ----------------------------
# JWT helpers (read-only)
# ----------------------------
def _jwt_payload(token: str) -> Optional[dict]:
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return None
        payload_b64 = parts[1] + "=" * (-len(parts[1]) % 4)
        return json.loads(base64.urlsafe_b64decode(payload_b64).decode())
    except Exception:
        return None


def _token_expires_soon(token: str) -> bool:
    pl = _jwt_payload(token)
    if not pl or "exp" not in pl:
        return False
    return (pl["exp"] - int(time.time())) <= REFRESH_SKEW_SECONDS


def _refresh_session_if_needed() -> None:
    _ensure_auth_state()

    access_token = st.session_state.auth.get("access_token")
    refresh_token = st.session_state.auth.get("refresh_token")

    if not access_token or not refresh_token:
        return

    if not _token_expires_soon(access_token):
        return

    try:
        resp = sb().auth.refresh_session(refresh_token)
        session = getattr(resp, "session", None) or (resp.get("session") if isinstance(resp, dict) else None)

        if not session:
            return

        new_access = getattr(session, "access_token", None) or session.get("access_token")
        new_refresh = getattr(session, "refresh_token", None) or session.get("refresh_token")

        if new_access:
            st.session_state.auth["access_token"] = new_access
        if new_refresh:
            st.session_state.auth["refresh_token"] = new_refresh

        _cookie_set(
            {
                "access_token": st.session_state.auth.get("access_token"),
                "refresh_token": st.session_state.auth.get("refresh_token"),
                "email": st.session_state.auth.get("email"),
            }
        )

    except Exception:
        return


# ----------------------------
# Auth helpers
# ----------------------------
def is_logged_in() -> bool:
    _restore_auth_from_cookie_if_needed()
    _refresh_session_if_needed()
    _ensure_auth_state()
    return bool(st.session_state.auth.get("access_token"))


def logout() -> None:
    _ensure_auth_state()
    st.session_state.auth = {"access_token": None, "refresh_token": None, "user": None, "email": None}
    _cookie_clear()
    st.rerun()


def auth_headers() -> Dict[str, str]:
    _restore_auth_from_cookie_if_needed()
    _refresh_session_if_needed()
    tok = st.session_state.auth.get("access_token")
    return {"Authorization": f"Bearer {tok}"} if tok else {}


def require_login(message: str = "Log in in the sidebar to continue.") -> None:
    if not is_logged_in():
        st.info(message)
        st.stop()


def api_get(path: str, *, params: dict | None = None, timeout: int = 30) -> requests.Response:
    return requests.get(f"{API_BASE}{path}", headers=auth_headers(), params=params, timeout=timeout)


# ----------------------------
# Sidebar UI
# ----------------------------
def render_auth_sidebar(*, show_debug: bool = True) -> None:
    _ensure_auth_state()
    _restore_auth_from_cookie_if_needed()
    _refresh_session_if_needed()

    with st.sidebar:
        st.subheader("Connection")
        st.code(API_BASE)

        st.caption("Supabase URL:")
        st.code(SUPABASE_URL or "(missing)")

        st.divider()
        st.subheader("Login")

        if not is_logged_in():
            email = st.text_input("Email", value=st.session_state.auth.get("email") or "").strip()

            c1, c2 = st.columns(2)
            send_code = c1.button("Send code")
            verify_code = c2.button("Verify code")

            otp_code = st.text_input("OTP code", placeholder="6–8 digit code").strip()

            if send_code and email:
                sb().auth.sign_in_with_otp({"email": email})
                st.session_state.auth["email"] = email
                st.success("Code sent.")

            if verify_code and email and otp_code:
                resp = sb().auth.verify_otp({"email": email, "token": otp_code, "type": "email"})
                session = getattr(resp, "session", None) or resp.get("session")

                access = getattr(session, "access_token", None) or session.get("access_token")
                refresh = getattr(session, "refresh_token", None) or session.get("refresh_token")

                st.session_state.auth = {
                    "access_token": access,
                    "refresh_token": refresh,
                    "user": None,
                    "email": email,
                }

                _cookie_set({"access_token": access, "refresh_token": refresh, "email": email})
                st.success("Logged in.")
                st.rerun()

        else:
            st.success(f"Logged in as {st.session_state.auth.get('email')}")
            if st.button("Log out"):
                logout()

        if show_debug:
            st.divider()
            st.write("Has access token:", bool(st.session_state.auth.get("access_token")))
