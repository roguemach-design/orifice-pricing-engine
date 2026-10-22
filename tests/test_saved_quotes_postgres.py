"""Real PostgreSQL races and snapshot SQL invariants, on the disposable CI DB only."""

import os
import copy
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.exc import DBAPIError
import api_app as api
import saved_quotes as sq
from saved_quote_guards import install
from test_checkout_workflow import (
    authoritative_result,
    quote_inputs,
    install_idempotent_stripe,
)


def test_postgres_two_buyers_one_checkout_and_sql_immutability(monkeypatch):
    url = os.environ.get("JOURNEY_CI_POSTGRES_URL")
    if not url:
        pytest.skip("Disposable PostgreSQL binding unavailable")
    engine = create_engine(url)
    assert engine.url.database == "journey_ci"
    tables = [api.Order.__table__, api.AppConfig.__table__] + [
        v.__table__ for v in vars(api.QUOTE_MODELS).values()
    ]
    api.Base.metadata.create_all(engine, tables=tables)
    with engine.begin() as db:
        for role in ('anon','authenticated'):
            if not db.execute(text('SELECT 1 FROM pg_roles WHERE rolname=:role'),{'role':role}).scalar():
                db.execute(text('CREATE ROLE '+role+' NOLOGIN'))
            db.execute(text('GRANT ALL ON saved_quotes,quote_shares,quote_events,quote_reviews,quote_mail TO '+role))
    install(engine)
    install(engine)  # migration is repeatable without changing stored records
    with engine.begin() as db:
        for role in ('anon','authenticated'):
            with pytest.raises(DBAPIError):
                with db.begin_nested():
                    db.execute(text('SET LOCAL ROLE '+role))
                    db.execute(text('SELECT * FROM saved_quotes'))
    monkeypatch.setattr(api, "SessionLocal", sessionmaker(bind=engine))
    monkeypatch.setattr(api, "APP_ENV", "test")
    monkeypatch.setattr(api, "APP_BASE_URL", "https://synthetic.example.test")
    monkeypatch.setattr(api, "_calculate_quote_with_db_knobs", authoritative_result)
    monkeypatch.setattr(api.stripe, "api_key", "sk_test_synthetic")
    monkeypatch.setenv("SAVED_QUOTES_ENABLED", "true")
    calls = install_idempotent_stripe(monkeypatch)
    owner = {"id": "pg-owner", "email": "owner@example.test"}
    buyer = {"id": "pg-buyer", "email": "buyer@example.test"}
    s = api.SAVED_QUOTES
    with api.SessionLocal.begin() as db:
        q, mail = s.save(
            db, owner, [quote_inputs(chamfer=False)], {}, version="version-current"
        )
        qid = q.quote_id
        original = q.pdf_bytes
        db.add(
            api.QUOTE_MODELS.Share(
                id="pg-share",
                quote_id=qid,
                invited_email=buyer["email"],
                accepted_user_id=buyer["id"],
                token_hash="pg-hash",
                expires_at=q.valid_through,
                accepted_at=sq.now(),
                delivery_state="captured",
            )
        )
    requests = []
    for person in (owner, buyer):
        with api.SessionLocal.begin() as db:
            q = db.get(api.QUOTE_MODELS.Quote, qid)
            review = api.QUOTE_MODELS.Review(
                id="review-" + person["id"],
                quote_id=qid,
                buyer_user_id=person["id"],
                expires_at=q.valid_through,
                snapshot={
                    "lines": q.snapshot["lines"],
                    "pricing_ref": "version-current",
                    "changed": False,
                },
            )
            db.add(review)
            req = api.CartCheckoutCreateRequest(
                items=[l["inputs"] for l in q.snapshot["lines"]],
                saved_quote_id=qid,
                saved_quote_review_id=review.id,
                pricing_config_version="version-current",
            )
            requests.append((req, person))

    def checkout(value):
        from fastapi import HTTPException

        try:
            return s.checkout(value[0], value[1], None, None)
        except HTTPException as e:
            return e.status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(checkout, requests))
    assert sum(isinstance(r, dict) for r in results) == 1 and 409 in results
    assert len(calls) == 1
    with engine.begin() as db:
        policies = db.execute(
            text(
                "SELECT relname, relrowsecurity FROM pg_class WHERE relname IN "
                "('saved_quotes','quote_shares','quote_events','quote_reviews','quote_mail')"
            )
        ).all()
        assert len(policies) == 5 and all(enabled for name, enabled in policies)
        for sql in (
            "UPDATE saved_quotes SET pdf_sha256='tampered' WHERE quote_id=:id",
            "DELETE FROM saved_quotes WHERE quote_id=:id",
            "UPDATE quote_events SET actor_user_id='tampered' WHERE quote_id=:id",
            "DELETE FROM quote_events WHERE quote_id=:id",
        ):
            with pytest.raises(DBAPIError):
                with db.begin_nested():
                    db.execute(text(sql), {"id": qid})
    engine.dispose()
    # A fresh connection/session sees the same immutable snapshot and reservation.
    engine = create_engine(url)
    with engine.connect() as db:
        assert (
            bytes(
                db.execute(
                    text("SELECT pdf_bytes FROM saved_quotes WHERE quote_id=:id"),
                    {"id": qid},
                ).scalar()
            )
            == original
        )
        assert (
            db.execute(
                text(
                    "SELECT count(*) FROM orders WHERE quote_payload->>'saved_quote_id'=:id"
                ),
                {"id": qid},
            ).scalar()
            == 1
        )
    engine.dispose()
