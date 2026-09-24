# auth.py
import base64
import json
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional
from urllib.parse import unquote

import requests
import streamlit as st
from supabase import Client, create_client

logger = logging.getLogger(__name__)

# Cookie manager (for "stay logged in")
try:
    import extra_streamlit_components as stx
except Exception:
    stx = None


# ----------------------------
# Env
# ----------------------------
API_BASE = (os.environ.get("API_BASE") or "").strip().rstrip("/")
if API_BASE and "://" not in API_BASE:
    # Render private-service host:port values intentionally have no URL scheme.
    API_BASE = f"http://{API_BASE}"
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


def _clear_local_auth() -> None:
    st.session_state.auth = {
        "access_token": None,
        "refresh_token": None,
        "user": None,
        "email": None,
    }
    _cookie_clear()


# ----------------------------
# Supabase client
# ----------------------------
def sb() -> Client:
    if not SUPABASE_URL or not SUPABASE_ANON_KEY:
        st.error("Account sign-in is temporarily unavailable.")
        st.stop()
    return create_client(SUPABASE_URL, SUPABASE_ANON_KEY)


# ----------------------------
# Cookie manager
# ----------------------------
def _cookie_mgr():
    if stx is None:
        return None

    manager = st.session_state.get("_cookie_mgr_instance")
    if manager is None:
        manager = stx.CookieManager(key="oplates_auth_cookie_manager")
        st.session_state["_cookie_mgr_instance"] = manager
    return manager


def _cookie_get() -> Optional[dict]:
    # Streamlit exposes cookies from the browser's initial websocket request.
    # This is synchronous and avoids depending on an asynchronously rendered
    # component during session restoration. The component remains responsible
    # only for writing and clearing cookies in the browser.
    context_available = False
    raw = None
    try:
        cookies = st.context.cookies
        context_available = True
        raw = cookies.get(COOKIE_NAME)
    except (AttributeError, RuntimeError):
        pass

    # Preserve compatibility with older Streamlit versions and bare unit-test
    # contexts that do not expose st.context.cookies.
    if not context_available:
        cm = _cookie_mgr()
        if cm is None:
            return None
        raw = cm.get(COOKIE_NAME)

    if not raw:
        return None
    try:
        return json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        try:
            return json.loads(unquote(raw))
        except (TypeError, json.JSONDecodeError):
            return None


def _cookie_set(payload: dict) -> None:
    cm = _cookie_mgr()
    if cm is None:
        return

    # ✅ CookieManager expects datetime (not float)
    expires_dt = datetime.now(timezone.utc) + timedelta(days=COOKIE_TTL_DAYS)

    try:
        cm.set(
            COOKIE_NAME,
            json.dumps(payload),
            expires_at=expires_dt,
        )
        st.session_state.pop("_auth_cookie_cleared", None)
    except Exception:
        pass


def _cookie_clear() -> None:
    st.session_state["_auth_cookie_cleared"] = True
    cm = _cookie_mgr()
    if cm is None:
        return
    try:
        cm.delete(COOKIE_NAME)
    except Exception:
        pass


def _restore_auth_from_cookie_if_needed() -> None:
    _ensure_auth_state()

    if st.session_state.auth.get("access_token"):
        return
    if st.session_state.get("_auth_cookie_cleared"):
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
        return True
    try:
        return (int(pl["exp"]) - int(time.time())) <= REFRESH_SKEW_SECONDS
    except (TypeError, ValueError):
        return True


def _token_is_expired(token: str) -> bool:
    payload = _jwt_payload(token)
    if not payload or payload.get("exp") is None:
        return True
    try:
        return int(payload["exp"]) <= int(time.time())
    except (TypeError, ValueError):
        return True


def _session_value(session: object, name: str):
    if isinstance(session, dict):
        return session.get(name)
    return getattr(session, name, None)


def _refresh_session_if_needed() -> None:
    _ensure_auth_state()

    access_token = st.session_state.auth.get("access_token")
    refresh_token = st.session_state.auth.get("refresh_token")

    if not access_token:
        return
    if not refresh_token:
        if _token_is_expired(access_token):
            _clear_local_auth()
        return

    if not _token_expires_soon(access_token):
        return

    try:
        resp = sb().auth.refresh_session(refresh_token)
        session = getattr(resp, "session", None) or (
            resp.get("session") if isinstance(resp, dict) else None
        )

        if not session:
            if _token_is_expired(access_token):
                _clear_local_auth()
            return

        new_access = _session_value(session, "access_token")
        new_refresh = _session_value(session, "refresh_token")

        if new_access:
            st.session_state.auth["access_token"] = new_access
        elif _token_is_expired(access_token):
            _clear_local_auth()
            return
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
        if _token_is_expired(access_token):
            _clear_local_auth()


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
    _clear_local_auth()
    st.rerun()


def auth_headers() -> Dict[str, str]:
    _restore_auth_from_cookie_if_needed()
    _refresh_session_if_needed()
    tok = st.session_state.auth.get("access_token")
    return {"Authorization": f"Bearer {tok}"} if tok else {}


def current_user_id_hint() -> Optional[str]:
    """Return the JWT subject for UI visibility only.

    This client-side decode is never an authorization decision. Internal
    drawing access is independently verified by the pricing API using the
    configured Supabase JWKS, issuer, audience, and server-side allowlist.
    """

    if not is_logged_in():
        return None
    token = st.session_state.auth.get("access_token")
    payload = _jwt_payload(token) if token else None
    subject = payload.get("sub") if payload else None
    return str(subject) if subject else None


def require_login(message: str = "Log in in the sidebar to continue.") -> None:
    if not is_logged_in():
        st.info(message)
        st.stop()


def api_get(
    path: str, *, params: dict | None = None, timeout: int = 30
) -> requests.Response:
    if not API_BASE:
        st.error("The O-Plates pricing service is not configured.")
        st.stop()
    return requests.get(
        f"{API_BASE}{path}", headers=auth_headers(), params=params, timeout=timeout
    )


# ----------------------------
# Sidebar UI
# ----------------------------
def _render_connection_debug() -> None:
    st.subheader("Connection")
    st.code(API_BASE)
    st.caption("Supabase URL:")
    st.code(SUPABASE_URL or "(missing)")


def render_auth_sidebar(*, show_debug: bool = False) -> None:
    # ✅ IMPORTANT: restore BEFORE widgets
    _ensure_auth_state()
    _restore_auth_from_cookie_if_needed()
    _refresh_session_if_needed()

    with st.sidebar:
        if show_debug:
            _render_connection_debug()
            st.divider()

        st.subheader("Account")

        if not is_logged_in():
            email = st.text_input(
                "Email", value=st.session_state.auth.get("email") or ""
            ).strip()

            c1, c2 = st.columns(2)
            send_code = c1.button("Send code")
            verify_code = c2.button("Verify code")

            otp_code = st.text_input("OTP code", placeholder="6–8 digit code").strip()

            if send_code:
                if not email:
                    st.error("Enter your email first.")
                else:
                    try:
                        sb().auth.sign_in_with_otp(
                            {
                                "email": email,
                                "options": {"should_create_user": True},
                            }
                        )
                        st.session_state.auth["email"] = email
                        st.success("Check your email for the sign-in code.")
                    except Exception as exc:
                        # Keep the customer-facing response generic, but retain the
                        # provider's non-sensitive classification for internal
                        # owner-acceptance diagnostics. Never log the email, token,
                        # API key, or exception message here.
                        logger.warning(
                            "Supabase OTP send failed: exception=%s status=%s code=%s",
                            type(exc).__name__,
                            getattr(exc, "status", None),
                            getattr(exc, "code", None),
                        )
                        st.error("We couldn’t send a sign-in code. Please try again.")

            if verify_code:
                if not email or not otp_code:
                    st.error("Enter email + OTP code.")
                else:
                    try:
                        resp = sb().auth.verify_otp(
                            {"email": email, "token": otp_code, "type": "email"}
                        )
                        session = _session_value(resp, "session")
                        access = _session_value(session, "access_token")
                        refresh = _session_value(session, "refresh_token")

                        if not access:
                            raise ValueError("Supabase did not return a session")

                        st.session_state.auth = {
                            "access_token": access,
                            "refresh_token": refresh,
                            "user": _session_value(resp, "user"),
                            "email": email,
                        }

                        _cookie_set(
                            {
                                "access_token": access,
                                "refresh_token": refresh,
                                "email": email,
                            }
                        )
                        st.success("You’re logged in.")
                    except Exception:
                        st.error(
                            "That sign-in code is invalid or expired. Request a new code."
                        )

        else:
            st.success(f"Logged in as {st.session_state.auth.get('email')}")
            if st.button("Log out"):
                logout()

        if show_debug:
            st.divider()
            st.write(
                "Has access token:", bool(st.session_state.auth.get("access_token"))
            )
