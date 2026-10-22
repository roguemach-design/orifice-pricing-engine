import copy
import hashlib
from datetime import timedelta
from urllib.parse import urlparse, parse_qs
from types import SimpleNamespace
from concurrent.futures import ThreadPoolExecutor
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
import api_app as api
import saved_quotes as sq
from test_checkout_workflow import (
    database,
    checkout_client,
    quote_inputs,
    install_idempotent_stripe,
    completed_session,
    install_completed_webhook,
)


def headers(who="owner"):
    return {"Authorization": "Bearer " + who}


@pytest.fixture
def quotes(monkeypatch, checkout_client, database):
    monkeypatch.setenv("SAVED_QUOTES_ENABLED", "true")
    monkeypatch.delenv("SAVED_QUOTES_LIVE", raising=False)
    people = {
        "owner": {"id": "owner", "email": "engineer@example.test"},
        "buyer": {"id": "buyer", "email": "purchasing@example.test"},
        "stranger": {"id": "stranger", "email": "wrong@example.test"},
    }

    def identity(api, auth):
        token = (auth or "").removeprefix("Bearer ")
        if token not in people:
            raise HTTPException(401, "Unauthorized")
        return people[token]

    monkeypatch.setattr(sq, "verified_identity", identity)
    monkeypatch.setattr(
        api,
        "_decode_supabase_user_id_from_bearer",
        lambda a: people.get((a or "").removeprefix("Bearer "), {}).get("id"),
    )
    messages = []
    monkeypatch.setattr(
        api.SAVED_QUOTES, "mail", lambda *a, **k: messages.append((a, k)) or "captured"
    )
    calls = install_idempotent_stripe(monkeypatch)
    return SimpleNamespace(
        client=checkout_client,
        db=database,
        people=people,
        messages=messages,
        calls=calls,
    )


def save(q, **kw):
    payload = {
        "items": [quote_inputs(chamfer=False, chamfer_width=None)],
        "customer": {"company": "Synthetic Process Co."},
        "pricing_config_version": "version-current",
        **kw,
    }
    r = q.client.post("/quotes", headers=headers(), json=payload)
    assert r.status_code == 200, r.text
    return r.json()


def invite(q, qid):
    r = q.client.post(
        f"/quotes/{qid}/shares",
        headers=headers(),
        json={"email": "purchasing@example.test"},
    )
    assert r.status_code == 200, r.text
    html = q.messages[-1][0][2]
    import re, html as htmlmodule

    url = htmlmodule.unescape(re.search('href="([^"]+)', html).group(1))
    return r.json()["share_id"], parse_qs(urlparse(url).query)["invite"][0]


def accept(q, qid, token, who="buyer"):
    return q.client.post(
        f"/quotes/{qid}/accept", headers=headers(who), json={"token": token}
    )


def review(q, qid, who="owner", **kw):
    r = q.client.post(f"/quotes/{qid}/revalidate", headers=headers(who), json=kw)
    assert r.status_code == 200, r.text
    return r.json()


def checkout(q, qid, r, who="owner", ack=True, **changes):
    payload = {
        "items": [l["inputs"] for l in r["lines"]],
        "pricing_config_version": r["pricing_ref"],
        "saved_quote_id": qid,
        "saved_quote_review_id": r["review_id"],
        "saved_quote_acknowledged": ack,
        **changes,
    }
    return q.client.post("/checkout/cart/create", headers=headers(who), json=payload)


def test_save_redownload_immutable_pdf_and_email(quotes):
    q = quotes
    x = save(q)
    qid = x["quote_id"]
    a = q.client.get(f"/quotes/{qid}/pdf", headers=headers())
    b = q.client.get(f"/quotes/{qid}/pdf", headers=headers())
    assert a.content == b.content
    assert hashlib.sha256(a.content).hexdigest() == x["pdf_sha256"]
    assert qid in a.headers["content-disposition"]
    assert q.messages[0][0][3] == a.content
    assert "View Your Quote" in q.messages[0][0][2]
    assert "?quote=" + qid in q.messages[0][0][2]
    assert q.client.get("/me/quotes", headers=headers()).json()[0]["quote_id"] == qid
    with q.db() as db:
        assert {e.action for e in db.query(api.QUOTE_MODELS.Event)} >= {
            "create",
            "download",
            "list",
        }
        original = db.get(api.QUOTE_MODELS.Quote, qid)
        original.snapshot = {**original.snapshot, "pricing_ref": "tampered"}
        with pytest.raises(ValueError, match="immutable"):
            db.commit()


def test_revisions_r2_r3_keep_original_exact(quotes):
    q = quotes
    x = save(q)
    qid = x["quote_id"]
    a = q.client.get(f"/quotes/{qid}/pdf", headers=headers()).content
    r2 = q.client.post(
        f"/quotes/{qid}/revisions",
        headers=headers(),
        json={"items": [quote_inputs(quantity=4, chamfer=False)]},
    )
    assert r2.status_code == 200, r2.text
    assert r2.json()["quote_id"] == qid + "-R2"
    r3 = q.client.post(f"/quotes/{qid}-R2/revisions", headers=headers(), json={})
    assert r3.json()["quote_id"] == qid + "-R3"
    assert q.client.get(f"/quotes/{qid}/pdf", headers=headers()).content == a
    assert (
        q.client.get(f"/quotes/{qid}", headers=headers()).json()["status"]
        == "superseded"
    )
    assert (
        q.client.post(
            f"/quotes/{qid}/revisions", headers=headers(), json={}
        ).status_code
        == 409
    )


def test_nonexistent_unowned_expired_revoked_share_identical(quotes):
    q = quotes
    x = save(q)
    qid = x["quote_id"]
    sid, token = invite(q, qid)
    missing = q.client.get("/quotes/Q-UNKNOWN000", headers=headers("buyer"))
    unowned = q.client.get(f"/quotes/{qid}", headers=headers("buyer"))
    assert (
        (missing.status_code, missing.content)
        == (unowned.status_code, unowned.content)
        == (404, b'{"detail":"Quote not available for this account."}')
    )
    assert accept(q, qid, token).status_code == 200
    with q.db.begin() as db:
        db.get(api.QUOTE_MODELS.Share, sid).expires_at = sq.now() - timedelta(seconds=1)
    expired = q.client.get(f"/quotes/{qid}", headers=headers("buyer"))
    assert expired.content == missing.content
    with q.db.begin() as db:
        s = db.get(api.QUOTE_MODELS.Share, sid)
        s.expires_at = sq.now() + timedelta(days=1)
        s.revoked_at = sq.now()
    revoked = q.client.get(f"/quotes/{qid}", headers=headers("buyer"))
    assert (revoked.status_code, revoked.content) == (
        expired.status_code,
        expired.content,
    )


def test_invitation_exact_email_single_use_hashed_and_revocable(quotes):
    q = quotes
    qid = save(q)["quote_id"]
    sid, token = invite(q, qid)
    assert accept(q, qid, token, "stranger").status_code == 404
    assert accept(q, qid, token).status_code == 200
    assert accept(q, qid, token).status_code == 404
    listed = q.client.get("/me/quotes", headers=headers("buyer")).json()
    assert listed[0]["shared_with_you"] is True
    with q.db() as db:
        share = db.get(api.QUOTE_MODELS.Share, sid)
        assert share.token_hash == hashlib.sha256(token.encode()).hexdigest()
        assert token not in repr(share.__dict__)
        assert share.accepted_user_id == "buyer"
    assert (
        q.client.post(
            f"/quotes/{qid}/shares/{sid}/revoke", headers=headers("stranger"), json={}
        ).status_code
        == 404
    )
    assert (
        q.client.post(
            f"/quotes/{qid}/shares/{sid}/revoke", headers=headers(), json={}
        ).status_code
        == 200
    )
    assert (
        q.client.get(f"/quotes/{qid}/pdf", headers=headers("buyer")).status_code == 404
    )


def test_all_routes_auth_and_forwarded_number_no_access(quotes):
    q = quotes
    qid = save(q)["quote_id"]
    for route in [
        "/me/quotes",
        f"/quotes/{qid}",
        f"/quotes/{qid}/pdf",
        f"/quotes/{qid}/shares",
    ]:
        assert q.client.get(route).status_code == 401
    for suffix, payload in [
        ("revisions", {}),
        ("revalidate", {}),
        ("shares", {"email": "another@example.test"}),
    ]:
        assert (
            q.client.post(
                f"/quotes/{qid}/{suffix}", headers=headers("stranger"), json=payload
            ).status_code
            == 404
        )


def test_purchaser_review_checkout_order_frozen_plate_approval_identity(
    quotes, monkeypatch, tmp_path
):
    q = quotes
    x = save(q)
    qid = x["quote_id"]
    sid, token = invite(q, qid)
    assert accept(q, qid, token).status_code == 200
    r = review(q, qid, "buyer")
    created = checkout(q, qid, r, "buyer")
    assert created.status_code == 200, created.text
    assert q.calls[0]["customer_email"] == "purchasing@example.test"
    assert q.calls[0]["client_reference_id"] == "buyer"
    assert q.calls[0]["metadata"]["customer_id"] == "buyer"
    assert q.calls[0]["metadata"]["saved_quote_id"] == qid
    assert q.calls[0]["line_items"][0]["price_data"]["unit_amount"] == 12500
    assert len(q.calls[0]["shipping_options"]) == 3
    with q.db() as db:
        order = db.query(api.Order).one()
        oid = order.id
        assert order.customer_id == "buyer"
        assert order.quote_payload["cart_items"] == [l["inputs"] for l in r["lines"]]
        assert order.quote_payload["saved_quote_id"] == qid
    # Signed provider completion uses the existing webhook and manufacturing adapter.
    session = completed_session(created.json()["session_id"], "buyer")
    install_completed_webhook(monkeypatch, session)
    monkeypatch.setattr(api, "_send_email", lambda **kw: None)
    done = q.client.post(
        "/stripe/webhook", content=b"{}", headers={"stripe-signature": "valid"}
    )
    assert done.status_code == 200, done.text
    # A repeated signed completion must retain the purchasing identity and one
    # order/audit transition, even if Stripe's receipt email differs.
    replay = q.client.post('/stripe/webhook', content=b'{}', headers={'stripe-signature':'valid'})
    assert replay.status_code == 200, replay.text
    with q.db() as db:
        assert db.query(api.Order).count() == 1
        assert db.get(api.Order, oid).customer_email == 'purchasing@example.test'
        assert db.query(api.QUOTE_MODELS.Event).filter_by(quote_id=qid, action='order').count() == 1
    assert (
        q.client.get(f"/me/orders/{oid}", headers=headers("owner")).status_code == 404
    )
    assert (
        q.client.get(f"/me/orders/{oid}", headers=headers("buyer")).status_code == 200
    )
    with q.db() as db:
        saved = db.get(api.QUOTE_MODELS.Quote, qid)
        assert saved.status == "ordered" and saved.ordered_order_id == oid
        order = db.get(api.Order, oid)
        snapshot = {
            "id": oid,
            "customer_id": order.customer_id,
            "quote_payload": copy.deepcopy(order.quote_payload),
            "order_number_display": "OP-0001",
            "customer_email": "purchasing@example.test",
        }
    from frozen_plate.repository import Repository, WorkflowError
    from frozen_plate.orders import complete_order

    repo = Repository(tmp_path / "frozen", "synthetic-approval-key-" + "x" * 48)
    states = complete_order(repo, snapshot)
    assert states[0]["state"] == "FROZEN"
    plate = repo.plate(states[0]["plate_id"])
    assert plate["customer_id"] == "buyer"
    delivery = repo.create_delivery(states[0]["revision_id"])
    with pytest.raises(WorkflowError):
        repo.approve(delivery["token"], "owner")
    approval = repo.approve(delivery["token"], "buyer")
    assert approval["approval"]["revision_id"] == states[0]["revision_id"]
    assert checkout(q, qid, r, "buyer").status_code == 409
    assert len(q.calls) == 1


def test_same_quote_retries_return_one_checkout_and_other_buyer_blocked(quotes):
    q = quotes
    qid = save(q)["quote_id"]
    r = review(q, qid)
    a = checkout(q, qid, r)
    b = checkout(q, qid, r)
    assert a.status_code == b.status_code == 200 and a.json() == b.json()
    assert len(q.calls) == 1
    sid, token = invite(q, qid)
    accept(q, qid, token)
    br = review(q, qid, "buyer")
    assert checkout(q, qid, br, "buyer").status_code == 409
    with q.db() as db:
        assert db.query(api.Order).count() == 1


def test_price_change_requires_ack_and_current_amount(quotes, monkeypatch):
    q = quotes
    qid = save(q)["quote_id"]
    original = api._calculate_quote_with_db_knobs

    def changed(inputs):
        return {
            **original(inputs),
            "unit_price": 150,
            "total_price": 150 * inputs.quantity,
            "total_price_cents": 15000 * inputs.quantity,
            "pricing_config_version": "new-version",
        }

    monkeypatch.setattr(api, "_calculate_quote_with_db_knobs", changed)
    r = review(q, qid)
    assert (
        r["changed"]
        and r["quoted_subtotal"] == "125.0"
        and r["current_subtotal"] == "150"
    )
    assert checkout(q, qid, r, ack=False).status_code == 409 and not q.calls
    assert checkout(q, qid, r).status_code == 200
    assert q.calls[0]["line_items"][0]["price_data"]["unit_amount"] == 15000


def test_unavailable_lead_time_requires_new_choice_and_ack(quotes, monkeypatch):
    q = quotes
    qid = save(q)["quote_id"]
    original = api._calculate_quote_with_db_knobs

    def changed(inputs):
        if inputs.ships_in_days == 14:
            raise ValueError("disabled")
        return original(inputs)

    monkeypatch.setattr(api, "_calculate_quote_with_db_knobs", changed)
    assert (
        q.client.post(
            f"/quotes/{qid}/revalidate", headers=headers(), json={}
        ).status_code
        == 422
    )
    r = review(q, qid, lead_times=[21])
    assert r["changed"]
    assert checkout(q, qid, r, ack=False).status_code == 409
    assert checkout(q, qid, r).status_code == 200
    with q.db() as db:
        assert (
            db.query(api.Order).one().quote_payload["cart_items"][0]["ships_in_days"]
            == 21
        )


def test_stale_review_wrong_owner_and_tampered_cart_rejected(quotes, monkeypatch):
    q = quotes
    qid = save(q)["quote_id"]
    r = review(q, qid)
    sid, token = invite(q, qid)
    accept(q, qid, token)
    assert checkout(q, qid, r, "buyer").status_code == 409
    tampered = copy.deepcopy(r["lines"][0]["inputs"])
    tampered["quantity"] = 99
    assert checkout(q, qid, r, items=[tampered]).status_code == 409
    original = api._calculate_quote_with_db_knobs
    monkeypatch.setattr(
        api,
        "_calculate_quote_with_db_knobs",
        lambda i: {**original(i), "pricing_config_version": "changed"},
    )
    assert checkout(q, qid, r).status_code == 409 and not q.calls


def test_expired_update_pricing_preserves_pdf(quotes, monkeypatch):
    q = quotes
    qid = save(q)["quote_id"]
    original = q.client.get(f"/quotes/{qid}/pdf", headers=headers()).content
    future = sq.now() + timedelta(days=31)
    monkeypatch.setattr(sq, "now", lambda: future)
    assert (
        q.client.get(f"/quotes/{qid}", headers=headers()).json()["status"] == "expired"
    )
    assert (
        q.client.post(
            f"/quotes/{qid}/revalidate", headers=headers(), json={}
        ).status_code
        == 409
    )
    r = q.client.post(f"/quotes/{qid}/revisions", headers=headers(), json={})
    assert r.status_code == 200 and r.json()["quote_id"] == qid + "-R2"
    assert q.client.get(f"/quotes/{qid}/pdf", headers=headers()).content == original


def test_shared_edit_creates_own_quote_never_mutates_owner(quotes):
    q = quotes
    qid = save(q)["quote_id"]
    sid, token = invite(q, qid)
    accept(q, qid, token)
    r = q.client.post(f"/quotes/{qid}/revisions", headers=headers("buyer"), json={})
    assert r.status_code == 200 and r.json()["root_quote_id"] != qid
    assert q.client.get(f"/quotes/{qid}", headers=headers()).json()["status"] == "open"
    assert (
        q.client.get("/quotes/" + r.json()["quote_id"], headers=headers()).status_code
        == 404
    )


def test_feature_and_pdf_copy_default_off(quotes, monkeypatch):
    q = quotes
    x = save(q)
    assert x["snapshot"]["retrieval_live"] is False
    monkeypatch.setenv("SAVED_QUOTES_ENABLED", "false")
    assert q.client.get("/me/quotes", headers=headers()).status_code == 404
    assert q.client.get("/quotes/availability").json() == {"enabled": False}


def test_rate_limit_find_by_user_and_ip(quotes):
    q = quotes
    responses = [
        q.client.get("/quotes/Q-NOTKNOWN", headers=headers()) for _ in range(65)
    ]
    assert responses[-1].status_code == 429


def test_provider_verified_email_not_metadata(monkeypatch):
    import supabase

    monkeypatch.setenv("SUPABASE_URL", "https://synthetic.supabase.co")
    monkeypatch.setenv("SUPABASE_PUBLISHABLE_KEY", "synthetic-publishable")
    monkeypatch.setattr(api, "_require_customer_user_id", lambda a: "buyer")
    user = SimpleNamespace(
        id="buyer",
        email="buyer@example.test",
        email_confirmed_at=None,
        is_anonymous=False,
        user_metadata={"email_verified": True},
    )
    monkeypatch.setattr(
        supabase,
        "create_client",
        lambda *a: SimpleNamespace(
            auth=SimpleNamespace(get_user=lambda token: SimpleNamespace(user=user))
        ),
    )
    with pytest.raises(HTTPException) as exc:
        sq.verified_identity(api, "Bearer verified")
    assert exc.value.status_code == 401
    user.email_confirmed_at = sq.now()
    assert sq.verified_identity(api, "Bearer verified") == {
        "id": "buyer",
        "email": "buyer@example.test",
    }


def test_retry_after_order_persist_failure_uses_same_stripe_key(quotes, monkeypatch):
    q = quotes
    qid = save(q)["quote_id"]
    r = review(q, qid)
    original = api._persist_pending_order
    calls = []

    def fail_once(**kw):
        calls.append(kw)
        if len(calls) == 1:
            raise HTTPException(503, "Retry")
        return original(**kw)

    monkeypatch.setattr(api, "_persist_pending_order", fail_once)
    assert checkout(q, qid, r).status_code == 503
    with q.db() as db:
        assert (
            db.get(api.QUOTE_MODELS.Quote, qid).checkout["review_id"] == r["review_id"]
        )
    # A retry in a later second must keep ALL Stripe parameters identical,
    # including expiration, rather than only reusing its idempotency key.
    later = sq.now() + timedelta(minutes=1)
    monkeypatch.setattr(sq, "now", lambda: later)
    assert checkout(q, qid, r).status_code == 200
    assert q.calls[0] == q.calls[1]
    with q.db() as db:
        assert db.query(api.Order).count() == 1


def test_revoke_expires_existing_stripe_checkout_before_access_removed(
    quotes, monkeypatch
):
    q = quotes
    qid = save(q)["quote_id"]
    sid, token = invite(q, qid)
    accept(q, qid, token)
    r = review(q, qid, "buyer")
    assert checkout(q, qid, r, "buyer").status_code == 200
    expired = []
    monkeypatch.setattr(
        api.stripe.checkout.Session, "retrieve", lambda *a, **k: {"status": "open"}
    )
    monkeypatch.setattr(
        api.stripe.checkout.Session,
        "expire",
        lambda *a, **k: expired.append(a[0]) or {"status": "expired"},
    )
    assert (
        q.client.post(
            f"/quotes/{qid}/shares/{sid}/revoke", headers=headers(), json={}
        ).status_code
        == 200
    )
    assert expired == ["cs_test_1"]
    assert q.client.get(f"/quotes/{qid}", headers=headers("buyer")).status_code == 404
    assert checkout(q, qid, r, "buyer").status_code == 404


def test_pdf_links_require_server_flag_and_saved_snapshot(quotes, monkeypatch):
    from pypdf import PdfReader
    from io import BytesIO

    q = quotes
    x = save(q)
    old = q.client.get("/quotes/" + x["quote_id"] + "/pdf", headers=headers()).content
    monkeypatch.setenv("SAVED_QUOTES_LIVE", "true")
    y = save(q)
    new = q.client.get("/quotes/" + y["quote_id"] + "/pdf", headers=headers()).content
    assert "View or order this quote" in "\n".join(
        p.extract_text() for p in PdfReader(BytesIO(new)).pages
    )
    assert y["snapshot"]["retrieval_url"].endswith("/My_Quotes?quote=" + y["quote_id"])
    assert (
        q.client.get("/quotes/" + x["quote_id"] + "/pdf", headers=headers()).content
        == old
    )


def test_sendgrid_message_has_exact_pdf_and_legal_footer(quotes, monkeypatch):
    import sendgrid, base64

    sent = []
    monkeypatch.setenv("SAVED_QUOTES_EMAIL_MODE", "sendgrid")
    monkeypatch.setattr(api, "SENDGRID_API_KEY", "synthetic-not-a-real-key")
    monkeypatch.setattr(
        sendgrid,
        "SendGridAPIClient",
        lambda key: SimpleNamespace(
            send=lambda msg: sent.append(msg.get()) or SimpleNamespace(status_code=202)
        ),
    )
    # Call the real class implementation; the fixture captures all other mail.
    status = sq.Service.mail(
        api.SAVED_QUOTES,
        "owner@example.test",
        "Quote Q-SYNTHETIC",
        '<a href="https://quote.example.test/My_Quotes?quote=Q-SYNTHETIC">View Your Quote</a>',
        b"%PDF exact-snapshot",
        "O-Plates_Quote_Q-SYNTHETIC.pdf",
    )
    assert status == "accepted"
    assert (
        base64.b64decode(sent[0]["attachments"][0]["content"]) == b"%PDF exact-snapshot"
    )
    assert sent[0]["attachments"][0]["filename"] == "O-Plates_Quote_Q-SYNTHETIC.pdf"
    assert "400 Public Rd, Yorkville, OH 43971" in sent[0]["content"][0]["value"]
    assert sent[0]["reply_to"]["email"] == "sales@o-plates.com"


def test_owner_can_retry_quote_email_without_reissuing_pdf(quotes):
    q = quotes
    x = save(q)
    qid = x["quote_id"]
    assert (
        q.client.post(
            f"/quotes/{qid}/email", headers=headers("stranger"), json={}
        ).status_code
        == 404
    )
    result = q.client.post(f"/quotes/{qid}/email", headers=headers(), json={})
    assert result.status_code == 200 and result.json()["email_status"] == "captured"
    assert q.messages[0][0][3] == q.messages[1][0][3]
    with q.db() as db:
        assert db.query(api.QUOTE_MODELS.Quote).count() == 1
