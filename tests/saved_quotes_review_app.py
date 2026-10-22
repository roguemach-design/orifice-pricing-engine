"""LOCAL ONLY synthetic UI acceptance fixture. Never run as the production app."""

import os, sys, time, base64, json, re, html
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["APP_ENV"] = "test"
os.environ["API_BASE"] = "http://synthetic-quote-api"
os.environ["SAVED_QUOTES_ENABLED"] = "true"
os.environ["SAVED_QUOTES_EMAIL_MODE"] = "capture"
os.environ.pop("DATABASE_URL", None)
os.environ.pop("FROZEN_PLATE_DATABASE_URL", None)
import streamlit as st
import requests
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from types import SimpleNamespace
import api_app as api
import auth, saved_quotes
from pricing_engine import calculate_quote
from customer_navigation import run_customer_app


@st.cache_resource
def fixture():
    db = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    api.Base.metadata.create_all(db)
    api.SessionLocal = sessionmaker(bind=db)
    api.APP_ENV = "test"
    api.APP_BASE_URL = os.environ['QUOTE_REVIEW_ORIGIN']
    api.API_KEY = "synthetic-only"
    api._calculate_quote_with_db_knobs = lambda inputs: {
        **calculate_quote(inputs),
        "pricing_config_version": "review-v1",
    }
    def actor_for(h):
        return (h or '').removeprefix('Bearer synthetic.').rstrip('.')
    api._decode_supabase_user_id_from_bearer = actor_for
    saved_quotes.verified_identity = lambda a, h: {
        "id": actor_for(h),
        "email": {'buyer':'purchasing','owner':'engineer','stranger':'wrong'}[actor_for(h)]+'@example.test',
    }
    messages = []
    api.SAVED_QUOTES.mail = lambda *a, **k: messages.append(a) or 'captured'
    inputs = dict(
        quantity=1,
        material="304",
        thickness=0.125,
        handle_width=1.5,
        handle_length_from_bore=9.0,
        paddle_dia=3.0,
        bore_dia=1.0,
        bore_tolerance=0.005,
        chamfer=False,
        ships_in_days=14,
        handle_label="REVIEW PLATE",
    )
    client = TestClient(api.app)
    x = client.post(
        "/quotes",
        headers={"Authorization": "Bearer synthetic.owner."},
        json={
            "items": [inputs],
            "customer": {
                "company": "Example Process Co. (synthetic)",
                "name": "Jordan Example",
            },
            "pricing_config_version": "review-v1",
        },
    ).json()
    qid = x["quote_id"]
    from datetime import timedelta

    with api.SessionLocal.begin() as session:
        session.add(
            api.QUOTE_MODELS.Share(
                id="synthetic-expired-share",
                quote_id=qid,
                invited_email="purchasing@example.test",
                token_hash=__import__('hashlib').sha256(b'expired-synthetic-token').hexdigest(),
                expires_at=saved_quotes.now() - timedelta(days=1),
                delivery_state="captured",
            )
        )
    return client, qid, messages


client, qid, messages = fixture()
if st.query_params.get("actor") in ("owner", "buyer", "stranger"):
    st.session_state["fixture_actor"] = st.query_params["actor"]
actor = st.session_state.get("fixture_actor", "owner")
# UI-only test session; production verifies every request independently.
encoded = (
    base64.urlsafe_b64encode(
        json.dumps({"sub": actor, "exp": int(time.time()) + 3600}).encode()
    )
    .decode()
    .rstrip("=")
)
st.session_state["auth"] = {
    "access_token": "header." + encoded + ".signature",
    "refresh_token": None,
    "email": {'buyer':'purchasing','owner':'engineer','stranger':'wrong'}[actor] + "@example.test",
    "user": None,
}
auth.API_BASE = "http://synthetic-quote-api"
auth._restore_auth_from_cookie_if_needed = lambda: None
auth._refresh_session_if_needed = lambda: None
if st.query_params.get("fixture_quote") == "1":
    st.session_state["saved_quote_intent"] = qid
    st.query_params.pop('fixture_quote',None)
with st.sidebar:
    st.caption('Synthetic local acceptance fixture; authentication is simulated.')
    for kind, match in [('quote','Quotation'),('invitation','Invitation')]:
        found = [m for m in messages if (('Invitation' in m[1]) == (kind=='invitation'))]
        if found:
            link = html.unescape(re.search('href="([^"]+)',found[-1][2]).group(1))
            st.link_button('Captured '+kind+' email link',link)
    st.link_button('Expired synthetic invitation',api.SAVED_QUOTES.quote_url(qid,'expired-synthetic-token'))


def get(url, **kwargs):
    path = url.removeprefix("http://synthetic-quote-api")
    if path == "/checkout/availability":
        return SimpleNamespace(
            status_code=200, json=lambda: {"available": True, "mode": "test"}
        )
    return client.get(
        path,
        params=kwargs.get("params"),
        headers={
            "Authorization": "Bearer synthetic." + actor + ".",
            "x-api-key": "synthetic-only",
        },
    )


def post(url, **kwargs):
    return client.post(
        url.removeprefix("http://synthetic-quote-api"),
        json=kwargs.get("json"),
        headers={
            "Authorization": "Bearer synthetic." + actor + ".",
            "x-api-key": "synthetic-only",
        },
    )


requests.get = get
requests.post = post
original_page = st.Page
original_switch_page = st.switch_page


def local_page(page, *args, **kwargs):
    if isinstance(page, str) and page.startswith(("pages/", "journey/")):
        page = str(Path(__file__).resolve().parents[1] / page)
    return original_page(page, *args, **kwargs)


st.Page = local_page
def local_switch_page(page, *args, **kwargs):
    if isinstance(page,str) and page.startswith(('pages/','journey/')):
        page=str(Path(__file__).resolve().parents[1]/page)
    return original_switch_page(page,*args,**kwargs)
st.switch_page = local_switch_page
try:
    run_customer_app()
finally:
    st.Page = original_page
    st.switch_page = original_switch_page
