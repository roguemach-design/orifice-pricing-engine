# auth.py
import base64
import json
import os
import time
from typing import Dict, Optional, Tuple

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

# Cookie settings
COOKIE_NAME = os.environ.get("AUTH_COOKIE_NAME", "oplates_auth")
COOKIE_TTL_DAYS = int(os.environ.get("AUTH_COOKIE_TTL_DAYS", "14"))  # keep login for 14 days
REFRESH_SKEW_SECONDS = 120  # refresh if token expires within 2 minutes


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
# Cookie manager
# ----------------------------
def _cookie_mgr():
    # IMPORTANT: do NOT cache this. CookieManager is a Streamlit component.
    if stx is None:
        return None

    if "_cookie_manager" not in st.session_state:
        st.session_state["_cookie_manager"] = stx.CookieManager()

    return st.session_state["_cookie_manager"]


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
    """
    If session_state is empty but cookie exists, restore tokens into session_state.
    """
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
# JWT helpers (no extra deps)
# ----------------------------
def _jwt_payload(token: str) -> Optional[dict]:
    """
    Decode JWT payload WITHOUT verifying signature.
    Used only to read `exp` for refresh timing.
    """
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return None
        payload_b64 = parts[1]
        # pad base64url
        payload_b64 += "=" * (-len(payload_b64) % 4)
        payload = base64.urlsafe_b64decode(payload_b64.encode("utf-8")).decode("utf-8")
        return json.loads(payload)
    except Exception:
        return None


def _token_expires_soon(token: str, *, skew_seconds: int = REFRESH_SKEW_SECONDS) -> bool:
    pl = _jwt_payload(token)
    if not pl:
        return False
    exp = pl.get("exp")
    if not isinstance(exp, int):
        return False
    return (exp - int(time.time())) <= skew_seconds


def _refresh_session_if_needed() -> None:
    """
    If access_token is missing or expiring soon, try refresh_session(refresh_token).
    """
    _ensure_auth_state()
    access_token = st.session_state.auth.get("access_token")
    refresh_token = st.session_state.auth.get("refresh_token")

    if not access_token or not refresh_token:
        return

    if not _token_expires_soon(access_token):
        return

    try:
        resp = sb().auth.refresh_session(refresh_token)

        session = getattr(resp, "session", None)
        user = getattr(resp, "user", None)
        if session is None and isinstance(resp, dict):
            session = resp.get("session")
            user = resp.get("user")

        new_access: Optional[str] = None
        new_refresh: Optional[str] = None

        if isinstance(session, dict):
            new_access = session.get("access_token")
            new_refresh = session.get("refresh_token")
        else:
            new_access = getattr(session, "access_token", None)
            new_refresh = getattr(session, "refresh_token", None)

        if new_access:
            st.session_state.auth["access_token"] = new_access
        if new_refresh:
            st.session_state.auth["refresh_token"] = new_refresh

        # persist refreshed tokens back to cookie
        _cookie_set(
            {
                "access_token": st.session_state.auth.get("access_token"),
                "refresh_token": st.session_state.auth.get("refresh_token"),
                "email": st.session_state.auth.get("email"),
            }
        )

    except Exception:
        # If refresh fails, we don't hard-stop; next API call may fail and user can relog.
        return


# ----------------------------
# Auth helpers
# ----------------------------
def is_logged_in() -> bool:
    _ensure_auth_state()
    return bool(st.session_state.auth.get("access_token"))


def logout() -> None:
    _ensure_auth_state()
    st.session_state.auth = {"access_token": None, "refresh_token": None, "user": None, "email": None}
    _cookie_clear()
    st.rerun()


def auth_headers() -> Dict[str, str]:
    """
    Always try to restore + refresh tokens before returning headers,
    so all API calls benefit (orders, carts, etc.).
    """
    _restore_auth_from_cookie_if_needed()
    _refresh_session_if_needed()

    _ensure_auth_state()
    tok = st.session_state.auth.get("access_token")
    return {"Authorization": f"Bearer {tok}"} if tok else {}


def require_login(message: str = "Log in in the sidebar to continue.") -> None:
    _restore_auth_from_cookie_if_needed()
    _refresh_session_if_needed()
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
    Renders a consistent login/logout experience and stores session tokens in st.session_state.auth.
    """
    _ensure_auth_state()

    # Restore login early so sidebar immediately shows "Logged in"
    _restore_auth_from_cookie_if_needed()
    _refresh_session_if_needed()

    with st.sidebar:
        st.subheader("Connection")
        st.write("API Base:")
        st.code(API_BASE)

        # It's safe to show SUPABASE_URL (not the key)
        st.caption("Supabase URL:")
        st.code(SUPABASE_URL or "(missing)")

        if stx is None:
            st.warning(
                "Cookie persistence is OFF (missing extra-streamlit-components). "
                "Add `extra-streamlit-components==0.1.71` to requirements.txt to stay logged in."
            )

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
                            st.error(
                                "OTP verify succeeded but no access token was returned. "
                                "Check Supabase Auth settings."
                            )
                            st.stop()

                        st.session_state.auth = {
                            "access_token": access_token,
                            "refresh_token": refresh_token,
                            "user": user,
                            "email": email,
                        }

                        # Persist to cookie so user stays logged in across reloads
                        _cookie_set(
                            {
                                "access_token": access_token,
                                "refresh_token": refresh_token,
                                "email": email,
                            }
                        )

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
            rt = st.session_state.auth.get("refresh_token")
            st.write("Has refresh token:", bool(rt))
