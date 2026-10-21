"""Allowlisted presentation observations. Never accepts a customer payload."""

import json
import os
from pathlib import Path
import streamlit as st
import streamlit.components.v1 as components
from .schema import CONSENT_VERSION

_component = None


def enabled():
    return os.environ.get("JOURNEY_UI_ENABLED") == "true"


def mount(source):
    global _component
    if not enabled():
        return
    try:
        if _component is None:
            _component = components.declare_component(
                "oplates_journey", path=str(Path(__file__).parent / "frontend")
            )
        from urllib.parse import urlsplit

        route = urlsplit(st.context.url).path.rstrip("/")
        entry = (
            "configurator"
            if route in ("", "/Quote")
            else "cart" if route == "/Quote_Cart" else None
        )
        value = _component(
            source=source,
            entry=entry,
            endpoint=os.environ.get("JOURNEY_PUBLIC_API", ""),
            key="journey_consent",
            default=None,
        )
        if isinstance(value, dict):
            token = value.get("session")
            if isinstance(token, str) and len(token) == 108:
                st.session_state["journey_session"] = token
            else:
                st.session_state.pop("journey_session", None)
    except Exception:
        pass


def emit(step, outcome="reached", category="none"):
    if not enabled():
        return
    try:
        from .schema import Event
        from uuid import uuid4
        from datetime import datetime, timezone

        source = "embed" if st.session_state.get("integrated_landing") else "direct"
        event = Event(
            version=1,
            event_id=uuid4(),
            timestamp=datetime.now(timezone.utc),
            step=step,
            outcome=outcome,
            category=category,
            source=source,
        )
        payload = event.model_dump_json().replace("<", "\\u003c")
        components.html(
            "<script>try { const p=window.parent; const e="
            + payload
            + "; if(p.__oplatesJourneyEmit)p.__oplatesJourneyEmit(e); } catch(_) {}</script>",
            height=0,
        )
    except Exception:
        pass


def headers():
    token = st.session_state.get("journey_session") if enabled() else None
    return (
        {"x-oplates-journey": token}
        if isinstance(token, str) and len(token) == 108
        else {}
    )


def mark_internal():
    if not enabled():
        return
    try:
        components.html(
            "<script>try{const p=window.parent;p.__oplatesJourneyOwnerTest=true;p.__oplatesJourneyInternal?.();}catch(_){}</script>",
            height=0,
        )
    except Exception:
        pass
