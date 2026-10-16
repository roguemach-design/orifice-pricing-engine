"""Server-side legacy owner sessions. Never use the service's stored API key.

The API is the credential authority. Keys exist only in the server-side
Streamlit session, never in URLs, cookies, local storage or shared caches.
"""
from collections import deque
from threading import Lock
from time import monotonic
from urllib.parse import urlsplit
import os

import requests
import streamlit as st

_attempts = deque()
_attempt_lock = Lock()
WINDOW = 60
GLOBAL_LIMIT = 20
SESSION_LIMIT = 5
SESSION_TTL = 1800


class OwnerAccessError(Exception):
    """Fixed public message; never retain a transport exception or response."""


def api_base():
    base = os.environ.get("API_BASE", "").strip().rstrip("/")
    parsed = urlsplit(base)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise OwnerAccessError("Owner service configuration is unavailable.")
    return base


def clear_session():
    # Retain attempt timestamps, not authentication, customer data or widget values.
    attempts = st.session_state.get("legacy_attempts", [])
    st.session_state.clear()
    st.session_state["legacy_attempts"] = attempts


def active_session():
    auth = st.session_state.get("legacy_owner_session")
    if not isinstance(auth, dict) or not auth.get("key"):
        return False
    if monotonic() >= auth.get("expires", 0) or auth.get("base") != api_base():
        clear_session()
        return False
    return True


def allow_attempt():
    now = monotonic()
    recent = [t for t in st.session_state.get("legacy_attempts", []) if now - t < WINDOW]
    st.session_state["legacy_attempts"] = recent
    with _attempt_lock:
        while _attempts and now - _attempts[0] >= WINDOW:
            _attempts.popleft()
        if len(recent) >= SESSION_LIMIT or len(_attempts) >= GLOBAL_LIMIT:
            return False
        recent.append(now)
        _attempts.append(now)
    return True


def verify_owner(candidate):
    if not allow_attempt():
        return "Too many attempts. Wait one minute and retry."
    candidate = candidate.strip()
    if not candidate:
        return "Owner authentication failed."
    try:
        base = api_base()
        response = requests.get(base + "/admin/config", headers={"x-api-key": candidate}, timeout=15, allow_redirects=False)
        if response.status_code != 200 or not isinstance(response.json(), dict):
            return "Owner authentication failed or the service is unavailable."
    except (requests.RequestException, ValueError, OwnerAccessError):
        return "Owner authentication failed or the service is unavailable."
    # Only after the API verifies the submitted credential.
    clear_session()
    st.session_state["legacy_owner_session"] = {"key": candidate, "base": base, "expires": monotonic() + SESSION_TTL}
    return None


def unlock():
    candidate = st.session_state.pop("legacy_owner_input", "")
    error = verify_owner(candidate)
    if error:
        st.session_state["legacy_owner_error"] = error


def require_owner():
    try:
        valid = active_session()
        api_base()
    except OwnerAccessError:
        clear_session()
        st.error("Owner service configuration is unavailable.")
        st.stop()
    if not valid:
        st.title("Owner authentication")
        st.caption("Unlock the legacy fallback using your owner credential. No owner data loads before verification.")
        with st.form("legacy_unlock"):
            st.text_input("Owner credential", type="password", key="legacy_owner_input")
            st.form_submit_button("Unlock", on_click=unlock)
        if st.session_state.get("legacy_owner_error"):
            st.error(st.session_state["legacy_owner_error"])
        st.stop()
    st.sidebar.button("Lock", on_click=clear_session, key="legacy_owner_lock")


def owner_request(method, path, **kwargs):
    if not active_session():
        clear_session()
        raise OwnerAccessError("Owner authentication required.")
    if method not in {"GET", "PUT", "POST"} or not path.startswith("/admin/") or ".." in path or "?" in path or "#" in path:
        raise OwnerAccessError("Unsupported owner request.")
    auth = st.session_state["legacy_owner_session"]
    try:
        response = requests.request(method, auth["base"] + path, headers={"x-api-key": auth["key"]}, timeout=30, allow_redirects=False, **kwargs)
    except requests.RequestException:
        raise OwnerAccessError("Owner service request failed.") from None
    if response.status_code in (401, 403):
        clear_session()
        st.error("Owner session expired or was rejected. Unlock again.")
        st.stop()
    return response
