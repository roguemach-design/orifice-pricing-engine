"""Archive isolation and on-click exact-byte delivery, using real local records."""

from copy import deepcopy
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
import json

import pytest
from fastapi import FastAPI, Depends
from fastapi.testclient import TestClient
from sqlalchemy import inspect
import api_app
from frozen_plate import api as frozen_api
from frozen_plate.repository import Repository
from prototype_manufacturing import sample_spec
from owner_portal_transport import (
    OwnerClient,
    DownloadAccess,
    download_callable,
    clear_owner_session,
)
from test_checkout_workflow import database

HEADERS = {"x-api-key": "owner-fixture"}


@pytest.fixture
def world(database, monkeypatch, tmp_path):
    monkeypatch.setattr(api_app, "ADMIN_API_KEY", "owner-fixture")
    api_app._RATE_LIMITER._events.clear()
    with database() as db:
        db.add(
            api_app.Order(
                id="archive-order",
                order_number=14,
                status="completed",
                customer_id="c",
                stripe_session_id="cs_test_archive",
                stripe_payment_intent="pi_test_fixture",
                customer_email="fixture@example.test",
                shipping_name="Fixture Customer",
                amount_total_cents=12345,
                quote_payload={"quantity": 1, "material": "304"},
            )
        )
        db.add(
            api_app.Order(
                id="pending-live", status="pending", stripe_session_id="cs_live_pending"
            )
        )
        db.commit()
    repo = Repository(tmp_path / "frozen", "synthetic-signing-" * 8)
    pid = repo.create_plate(
        order_id="archive-order",
        line_id="line-1",
        configuration_id="cfg",
        customer_id="c",
        actor="fixture",
    )
    r1 = repo.create_revision(
        pid,
        sample_spec(),
        expected_current=None,
        reason="initial",
        actor="fixture",
        source_snapshot={},
    )
    repo.approve(repo.create_delivery(r1["id"])["token"], "c")
    r2 = repo.create_revision(
        pid,
        replace(sample_spec(), thickness=0.25),
        expected_current=r1["id"],
        reason="revision",
        actor="fixture",
        source_snapshot={},
    )
    repo.approve(repo.create_delivery(r2["id"])["token"], "c")
    for route in ("SENDCUTSEND", "ALRO", "ROGUE_INTERNAL"):
        repo.select_source(r2["id"], route, actor="fixture")
    monkeypatch.setattr(frozen_api, "repository", lambda: repo)
    app = FastAPI()
    app.add_api_route(
        "/admin/orders",
        api_app.admin_list_orders,
        dependencies=[Depends(api_app._rate_limit_admin)],
    )
    app.add_api_route(
        "/admin/orders/{order_id}",
        api_app.admin_get_order,
        dependencies=[Depends(api_app._rate_limit_admin)],
    )
    app.add_api_route(
        "/admin/orders/{order_id}/archive",
        api_app.admin_archive_order,
        methods=["PUT"],
        dependencies=[Depends(api_app._rate_limit_admin)],
    )
    app.include_router(
        frozen_api.router(
            lambda: "c",
            api_app._rate_limit_admin,
            lambda _: {"order_number_display": "OP-0014"},
        )
    )
    return SimpleNamespace(
        db=database, repo=repo, client=TestClient(app), pid=pid, r1=r1, r2=r2
    )


def snapshot(world):
    with world.db() as db:
        order = db.query(api_app.Order).filter_by(id="archive-order").one()
        fields = {
            c.key: deepcopy(getattr(order, c.key))
            for c in inspect(api_app.Order).columns
            if c.key != "owner_archived_at"
        }
    with world.repo.connect() as db:
        frozen = "\n".join(db.iterdump())
    files = {
        str(p.relative_to(world.repo.objects)): p.read_bytes()
        for p in world.repo.objects.rglob("*")
        if p.is_file()
    }
    return fields, frozen, files


def test_archive_round_trip_retains_every_order_field_and_frozen_object(world):
    client = world.client
    before = snapshot(world)
    url = "/admin/orders/archive-order/archive"
    for headers in (
        {},
        {"x-api-key": "public-quote-key"},
        {"authorization": "Bearer customer"},
    ):
        assert (
            client.put(url, headers=headers, json={"archived": True}).status_code == 401
        )
    assert (
        client.put(url, headers=HEADERS, json={"archived": "true"}).status_code == 422
    )
    assert (
        client.put(
            "/admin/orders/pending-live/archive",
            headers=HEADERS,
            json={"archived": True},
        ).status_code
        == 409
    )
    assert (
        client.put(
            "/admin/orders/missing/archive", headers=HEADERS, json={"archived": True}
        ).status_code
        == 404
    )
    first = client.put(url, headers=HEADERS, json={"archived": True})
    assert first.status_code == 200 and first.json()["owner_archived_at"]
    assert (
        client.put(url, headers=HEADERS, json={"archived": True}).json() == first.json()
    )
    assert not any(
        o["id"] == "archive-order"
        for o in client.get("/admin/orders", headers=HEADERS).json()
    )
    for view in ("Archived", "All"):
        for q in (
            "OP-0014",
            "fixture@example.test",
            "archive-order",
            "Fixture Customer",
            "cs_test_archive",
            "pi_test_fixture",
        ):
            rows = client.get(
                "/admin/orders", headers=HEADERS, params={"archive_view": view, "q": q}
            ).json()
            assert [o["id"] for o in rows] == ["archive-order"]
    assert snapshot(world) == before
    # All revisions/approval/sourcing/file reads still work while archived.
    root = "/admin/frozen-plates/"
    history = client.get(root + world.pid + "/revisions", headers=HEADERS).json()
    assert [r["id"] for r in history] == [world.r2["id"], world.r1["id"]]
    response = client.get(
        root + "revisions/" + world.r2["id"] + "/dxf", headers=HEADERS
    )
    assert response.status_code == 200
    assert (
        response.headers["content-disposition"]
        == 'attachment; filename="OP-304-.250-OP0014-L01-R2.dxf"'
    )
    assert (
        sha256(response.content).hexdigest() == world.r2["artifacts"]["dxf"]["sha256"]
    )
    assert (
        client.get(
            root + "revisions/" + world.r1["id"] + "/dxf", headers=HEADERS
        ).status_code
        == 409
    )
    assert snapshot(world) == before
    assert (
        client.put(url, headers=HEADERS, json={"archived": False}).json()[
            "owner_archived_at"
        ]
        is None
    )
    assert any(
        o["id"] == "archive-order"
        for o in client.get("/admin/orders", headers=HEADERS).json()
    )
    assert not client.get(
        "/admin/orders", headers=HEADERS, params={"archive_view": "Archived"}
    ).json()
    assert snapshot(world) == before


def test_global_archived_search_precedes_limit(world):
    with world.db() as db:
        for i in range(210):
            db.add(
                api_app.Order(
                    id=f"new-{i}",
                    status="completed",
                    stripe_session_id=f"cs_test_new{i}",
                )
            )
        db.commit()
    world.client.put(
        "/admin/orders/archive-order/archive", headers=HEADERS, json={"archived": True}
    )
    result = world.client.get(
        "/admin/orders",
        headers=HEADERS,
        params={"archive_view": "Archived", "q": "OP-0014", "limit": 1},
    ).json()
    assert [o["id"] for o in result] == ["archive-order"]


@pytest.mark.parametrize("kind", ["pdf", "dxf", "json"])
def test_one_click_is_lazy_verified_and_rechecks_on_every_click(
    world, monkeypatch, kind
):
    calls = []

    def get(url, headers, **kwargs):
        calls.append(url)
        return world.client.get(url.split("https://fixture.test")[-1], headers=headers)

    import requests

    monkeypatch.setattr(requests, "get", get)
    filename = (
        "OP-304-.250-OP0014-L01-R2.dxf"
        if kind == "dxf"
        else world.r2["artifacts"][kind]["filename"]
    )
    access = DownloadAccess(OwnerClient("https://fixture.test", "owner-fixture"))
    load = download_callable(access, world.r2, kind, filename)
    assert not calls
    before = snapshot(world)
    for _ in range(2):
        content = load()
        assert len(content) == world.r2["artifacts"][kind]["size"]
        assert sha256(content).hexdigest() == world.r2["artifacts"][kind]["sha256"]
    assert len(calls) == 2 and snapshot(world) == before
    from streamlit.runtime.memory_media_file_storage import MemoryMediaFileStorage
    from streamlit.runtime.media_file_manager import MediaFileManager
    from streamlit.runtime.media_file_storage import MediaFileStorageError

    storage = MemoryMediaFileStorage("/media")
    manager = MediaFileManager(storage)
    file_id = manager.add_deferred(
        load, "application/octet-stream", "fixture", filename
    )
    # The real backend gate rejects a tampered stored artifact, before any bytes
    # can be registered as downloadable by the framework.
    p = world.repo.objects / world.r2["artifacts"][kind]["object_key"]
    p.chmod(0o600)
    p.write_bytes(b"tampered")
    with pytest.raises(MediaFileStorageError, match="Download blocked"):
        manager.execute_deferred(file_id)
    assert not storage._files_by_id


@pytest.mark.parametrize("fault", ["sha", "length"])
def test_client_rejects_mismatched_api_bytes(fault, monkeypatch):
    import requests

    content = b"exact-bytes"
    a = {"sha256": sha256(content).hexdigest(), "size": len(content)}
    if fault == "sha":
        a["sha256"] = "0" * 64
    else:
        a["size"] += 1
    rev = {"id": "r1", "artifacts": {"pdf": a}}
    monkeypatch.setattr(
        requests,
        "get",
        lambda *a, **k: SimpleNamespace(status_code=200, content=content),
    )
    load = download_callable(
        DownloadAccess(OwnerClient("https://fixture", "owner")),
        rev,
        "pdf",
        "stored.pdf",
    )
    with pytest.raises(RuntimeError, match="integrity"):
        load()


def test_lock_revokes_inflight_and_old_download_callbacks(monkeypatch):
    calls = []
    client = SimpleNamespace(artifact=lambda *a: calls.append(a) or b"exact")
    access = DownloadAccess(client)
    load = download_callable(access, {"id": "r"}, "pdf", "r.pdf")
    state = {"mc_download_access": access, "mc_key": "fixture"}
    clear_owner_session(state)
    with pytest.raises(RuntimeError, match="locked"):
        load()
    assert not calls and state == {}
    access = DownloadAccess(client)

    def inflight(*args):
        access.revoke()
        return b"exact"

    client.artifact = inflight
    with pytest.raises(RuntimeError, match="locked"):
        access.load({"id": "r"}, "pdf", "r.pdf")
