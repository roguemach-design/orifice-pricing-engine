"""Owned read-only history and immutable approved archive; entirely local fixtures."""

from copy import deepcopy
from dataclasses import replace
from hashlib import sha256
import json

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
import pytest

import api_app
from frozen_plate import api
from frozen_plate.repository import Repository
from frozen_plate.orders import complete_order, freeze_line
from test_frozen_plate_staging import order_snapshot
from test_pricing_configuration import client


@pytest.fixture
def archive(tmp_path, monkeypatch):
    repo = Repository(tmp_path, "synthetic-key-" * 12)
    snapshot = order_snapshot()
    snapshot["quote_payload"]["cart_items"] = [
        deepcopy(snapshot["quote_payload"]),
        deepcopy(snapshot["quote_payload"]),
    ]
    states = complete_order(repo, snapshot)
    monkeypatch.setattr(api, "repository", lambda: repo)

    def customer():
        return "customer1"

    app = FastAPI()
    app.include_router(api.router(customer, lambda: None, lambda _: snapshot))
    yield TestClient(app), repo, snapshot, states, app, customer


def approve(repo, revision):
    delivery = repo.create_delivery(revision)
    repo.approve(delivery["token"], "customer1")
    return delivery


def fingerprint(repo):
    with repo.connect() as db:
        return {
            name: [tuple(r) for r in db.execute("SELECT * FROM " + name)]
            for name in (
                "frozen_plates",
                "frozen_plate_revisions",
                "frozen_plate_artifacts",
                "frozen_plate_approvals",
                "frozen_plate_tokens",
                "frozen_plate_deliveries",
                "frozen_plate_sourcing",
            )
        }


def test_approved_archive_reads_exact_bytes_after_token_expiry_without_writes(archive):
    c, repo, snapshot, states, *_ = archive
    rid = states[0]["revision_id"]
    token = approve(repo, rid)["token"]
    repo.revoke(token, actor="synthetic", reason="expired-link-test")
    repo.clock = lambda: 10**12
    before = fingerprint(repo)
    listing = c.get("/me/orders/order-test/drawing-archive")
    assert listing.status_code == 200
    assert len(listing.json()) == 2
    r = listing.json()[0]["revisions"][0]
    assert r["approved"] and r["current"] and r["pdf_available"]
    assert not listing.json()[1]["revisions"][0]["approved"]
    result = c.get(f"/me/orders/order-test/drawings/{rid}/pdf")
    artifact = repo.revision(rid)["artifacts"]["pdf"]
    assert result.status_code == 200
    assert result.content == (repo.objects / artifact["object_key"]).read_bytes()
    assert (
        result.headers["X-Artifact-SHA256"]
        == sha256(result.content).hexdigest()
        == r["pdf_sha256"]
    )
    assert result.headers["X-Frozen-Revision"] == rid
    assert result.headers["cache-control"] == "private, no-store"
    assert fingerprint(repo) == before
    text = listing.text
    assert all(
        ('"' + secret + '"') not in text
        for secret in (
            "object_key",
            "source_json",
            "created_by",
            "audit_json",
            "token_fingerprint",
            "dxf",
            "nc",
        )
    )


def test_only_approved_historical_revisions_are_downloadable(archive):
    c, repo, snapshot, states, *_ = archive
    r1 = states[0]["revision_id"]
    approve(repo, r1)
    snapshot["quote_payload"]["cart_items"][0]["bore_dia"] = 1.7
    r2 = freeze_line(
        repo,
        snapshot,
        0,
        "REVISED",
        revision=True,
        expected_current=r1,
        reason="synthetic revision",
    )
    archive_rows = c.get("/me/orders/order-test/drawing-archive").json()[0]["revisions"]
    assert [r["number"] for r in archive_rows] == [2, 1]
    assert not archive_rows[0]["approved"] and not archive_rows[1]["current"]
    assert c.get(f"/me/orders/order-test/drawings/{r1}/pdf").status_code == 200
    assert c.get(f'/me/orders/order-test/drawings/{r2["id"]}/pdf').status_code == 409
    approve(repo, r2["id"])
    assert c.get(f'/me/orders/order-test/drawings/{r2["id"]}/pdf').status_code == 200


@pytest.mark.parametrize(
    "attack", ["other_customer", "other_order", "wrong_revision", "unauthenticated"]
)
def test_ownership_precedes_private_storage_read(archive, monkeypatch, attack):
    c, repo, snapshot, states, app, customer = archive
    rid = states[0]["revision_id"]
    approve(repo, rid)

    def forbidden(*a):
        raise AssertionError("Unauthorized storage read")

    monkeypatch.setattr(repo, "_read_object", forbidden)
    oid = "order-test"
    if attack == "other_customer":
        app.dependency_overrides[customer] = lambda: "other"
    if attack == "other_order":
        oid = "other-order"
        snapshot["customer_id"] = "other"
    if attack == "wrong_revision":
        rid = "missing-revision"
    if attack == "unauthenticated":

        def denied():
            raise HTTPException(401, "Sign in")

        app.dependency_overrides[customer] = denied
    assert c.get(f"/me/orders/{oid}/drawings/{rid}/pdf").status_code in (401, 404)


@pytest.mark.parametrize("target", ["spec", "source", "approval", "pdf"])
def test_tampered_binding_or_stored_pdf_fails_closed(archive, target, monkeypatch):
    c, repo, _, states, *_ = archive
    rid = states[0]["revision_id"]
    approve(repo, rid)
    if target == "pdf":
        monkeypatch.setattr(repo, "_read_object", lambda key: b"corrupt")
    else:
        # Corrupt the read adapter, retaining the real immutable SQL constraints.
        from contextlib import contextmanager

        original = repo.connect

        @contextmanager
        def corrupt_connection():
            with original() as db:

                class Connection:
                    def execute(self, sql, args=()):
                        cursor = db.execute(sql, args)
                        applies = (
                            "SELECT * FROM frozen_plate_revisions" in sql
                            if target in ("spec", "source")
                            else "SELECT * FROM frozen_plate_approvals" in sql
                        )
                        if not applies:
                            return cursor

                        class Cursor:
                            def fetchone(self):
                                row = cursor.fetchone()
                                if not row:
                                    return row
                                value = dict(row)
                                value[
                                    (
                                        target + "_sha256"
                                        if target != "approval"
                                        else "pdf_sha256"
                                    )
                                ] = ("0" * 64)
                                return value

                        return Cursor()

                yield Connection()

        monkeypatch.setattr(repo, "connect", corrupt_connection)
    assert c.get(f"/me/orders/order-test/drawings/{rid}/pdf").status_code == 409


def test_archive_download_reads_only_pdf_not_manufacturing_objects(
    archive, monkeypatch
):
    c, repo, _, states, *_ = archive
    rid = states[0]["revision_id"]
    approve(repo, rid)
    original = repo._read_object
    keys = []
    monkeypatch.setattr(
        repo, "_read_object", lambda key: (keys.append(key), original(key))[1]
    )
    assert c.get(f"/me/orders/order-test/drawings/{rid}/pdf").status_code == 200
    assert len(keys) == 1 and keys[0].endswith(".pdf")


def test_missing_historical_frozen_records_remain_empty_without_backfill(archive):
    c, repo, snapshot, states, *_ = archive
    snapshot["id"] = "historic-hold"
    before = fingerprint(repo)
    assert c.get("/me/orders/historic-hold/drawing-archive").json() == []
    assert fingerprint(repo) == before


def test_history_owned_search_pagination_sort_and_safe_snapshots(client, monkeypatch):
    c, factory = client
    monkeypatch.setattr(
        api_app,
        "_decode_supabase_user_id_from_bearer",
        lambda token: "customer1" if token == "Bearer synthetic" else None,
    )
    with factory() as db:
        for n in range(1, 24):
            db.add(
                api_app.Order(
                    id=f"order-{n}",
                    customer_id="customer1",
                    order_number=n,
                    status="pending" if n == 23 else "completed",
                    amount_total_cents=None if n == 23 else n * 100,
                    stripe_session_id=f"cs_test_{n}",
                    quote_payload={
                        "_payment": {"recipient": "PRIVATE"},
                        "cart_items": [
                            {
                                "material": "304",
                                "quantity": 2,
                                "internal_notes": "PRIVATE",
                            },
                            {"material": "316", "quantity": 1},
                        ],
                    },
                )
            )
        db.add(
            api_app.Order(
                id="other", customer_id="other", order_number=24, status="completed"
            )
        )
        db.commit()
    headers = {"authorization": "Bearer synthetic"}
    data = c.get(
        "/me/order-history", headers=headers, params={"sort": "total_high", "limit": 5}
    ).json()
    assert (
        data["total"] == 23
        and len(data["orders"]) == 5
        and data["orders"][0]["id"] == "order-22"
    )
    assert data["orders"][0]["line_count"] == 2
    data = c.get(
        "/me/order-history", headers=headers, params={"search": "OP-0016"}
    ).json()
    assert [o["id"] for o in data["orders"]] == ["order-16"]
    assert (
        c.get(
            "/me/order-history", headers=headers, params={"search": "OP-0024"}
        ).json()["total"]
        == 0
    )
    detail = c.get("/me/order-history/order-16", headers=headers)
    assert (
        detail.status_code == 200
        and len(detail.json()["lines"]) == 2
        and "PRIVATE" not in detail.text
    )
    assert c.get("/me/order-history/other", headers=headers).status_code == 404
    pending = c.get("/me/order-history/order-23", headers=headers).json()
    assert pending["status"] == "pending" and pending["amount_total_usd"] is None
    assert c.get("/me/order-history").status_code == 401
    assert c.get("/me/order-history/order-16").status_code == 401
    assert (
        c.get(
            "/me/order-history", headers=headers, params={"sort": "drop_table"}
        ).status_code
        == 422
    )
