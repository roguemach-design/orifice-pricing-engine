"""Approval-triggered, idempotent staging; no owner-view/download generation."""

from dataclasses import asdict, replace
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
import json
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException
from fastapi.testclient import TestClient
import pytest
from final4.automatic import AutomaticStager
from final4.worker import StagingWorker
from final4.api import router as derived_router
from frozen_plate.api import router as frozen_router
from frozen_plate import api as frozen_api
from frozen_plate.repository import WorkflowError
from haas_generator.staging import FixtureProfile, VERSION
from test_final4 import system

ROOT = Path(__file__).resolve().parents[1]


def stager(svc):
    return AutomaticStager(
        svc,
        FixtureProfile(
            **json.loads((ROOT / "examples/final4/fixture-profile.json").read_text())
        ),
    )


def parent_for(svc, a, rev):
    return {
        **a,
        "revision_id": rev["id"],
        "spec_sha256": rev["spec_sha256"],
        "source_sha256": rev["source_sha256"],
    }


def test_approval_automatically_stages_files_without_generation_request(
    system, monkeypatch
):
    svc, a, _, spec = system
    r = svc.repo.create_revision(
        a["plate_id"],
        spec,
        expected_current=a["revision_id"],
        reason="new",
        actor="fixture",
        source_snapshot={},
    )
    a = parent_for(svc, a, r)
    delivery = svc.repo.create_delivery(r["id"])
    worker = StagingWorker(lambda: stager(svc))
    assert worker.sweep() == {}
    original = svc.repo.revision(r["id"])
    monkeypatch.setattr(frozen_api, "repository", lambda: svc.repo)
    app = FastAPI()
    app.include_router(
        frozen_router(
            lambda: "synthetic-customer",
            lambda: None,
            lambda _: None,
            approval_committed=worker.sweep,
        )
    )
    client = TestClient(app)
    assert client.get("/approve/" + delivery["token"]).status_code == 200
    assert not svc.list(a)
    approved = client.post(
        "/me/frozen-plates/approve", json={"token": delivery["token"]}
    )
    assert approved.status_code == 200 and approved.json()["state"] == "approved"
    states = worker.status(r["id"])
    assert {k: v["state"] for k, v in states.items()} == {
        "HAAS": "STAGED",
        "PACKAGING": "STAGED",
    }
    assert svc.repo.revision(r["id"]) == original
    assert (
        client.post(
            "/me/frozen-plates/approve", json={"token": delivery["token"]}
        ).status_code
        == 200
    )
    assert len(svc.list(a)) == 2
    for b in svc.list(a):
        assert (
            b["parent"]["revision_id"] == r["id"]
            and not b["statuses"]["release_eligible"]
        )
        assert not b["statuses"]["manufacturing_release_approved"]
        for f in b["files"]:
            raw = svc.download(b["id"], f["name"])[2]
            assert len(raw) == f["size"] and sha256(raw).hexdigest() == f["sha256"]


def test_internal_notification_failure_does_not_change_customer_approval(
    system, monkeypatch
):
    svc, a, _, spec = system
    r = svc.repo.create_revision(
        a["plate_id"],
        spec,
        expected_current=a["revision_id"],
        reason="new",
        actor="fixture",
        source_snapshot={},
    )
    delivery = svc.repo.create_delivery(r["id"])
    monkeypatch.setattr(frozen_api, "repository", lambda: svc.repo)

    def unavailable():
        raise RuntimeError("synthetic notification failure")

    app = FastAPI()
    app.include_router(
        frozen_router(
            lambda: "synthetic-customer",
            lambda: None,
            lambda _: None,
            approval_committed=unavailable,
        )
    )
    response = TestClient(app).post(
        "/me/frozen-plates/approve", json={"token": delivery["token"]}
    )
    assert response.status_code == 200 and response.json()["state"] == "approved"
    w = StagingWorker(lambda: stager(svc))
    w.sweep()
    assert w.status(r["id"])["HAAS"]["state"] == "STAGED"


@pytest.mark.parametrize("side", [None, "upstream", "downstream"])
def test_complete_nc_consumes_frozen_dimensions_and_controlled_profiles(system, side):
    svc, a, _, s = system
    if side:
        s = replace(
            s,
            chamfer=True,
            chamfer_width=0.02,
            chamfer_side=side,
            chamfer_angle_degrees=45,
            chamfer_width_definition="radial-angle-from-face",
            quantity=3,
        )
        r = svc.repo.create_revision(
            a["plate_id"],
            s,
            expected_current=a["revision_id"],
            reason="chamfer",
            actor="fixture",
            source_snapshot={},
        )
        svc.repo.approve(
            svc.repo.create_delivery(r["id"])["token"], "synthetic-customer"
        )
        a = parent_for(svc, a, r)
    auto = stager(svc)
    bid = auto.ensure("HAAS", a)
    b = svc.metadata(bid)
    text = svc.download(bid, "program.NC")[2].decode()
    inputs = json.loads(svc.download(bid, "inputs.json")[2])
    readiness = json.loads(svc.download(bid, "readiness.json")[2])
    record = inputs["record"]
    assert record["nominal_blank_bore"] == pytest.approx(
        s.finished_bore_diameter - 0.125
    )
    assert (
        "actual_blank_bore" not in record
        and "reviewed_by" not in record
        and "review_reference" not in record
    )
    assert record["blank_basis"] == "NOMINAL TARGET - NOT A MEASUREMENT"
    assert (
        record["finished_bore"] == s.finished_bore_diameter
        and record["thickness"] == s.thickness
    )
    assert record["material"] == s.material and record["quantity"] == s.quantity
    assert record["top_chamfer_width"] == (s.chamfer_width if side else 0)
    assert b["generator_version"] == VERSION
    assert b["staging"]["profile_sha256"] == auto.profiles()["HAAS"]
    assert b["staging"]["machine_profile"]["sha256"] in text
    assert b["staging"]["machine_profile"]["revision"] in text
    assert (
        a["spec_sha256"] in text and a["revision_id"] in text and a["plate_id"] in text
    )
    assert "#3000=1 (SETUP PROVE OUT REQUIRED)" in text
    lines = text.splitlines()
    assert (
        lines.index("T20 M06")
        < lines.index("T1 M06")
        < max(i for i, v in enumerate(lines) if v == "T20 M06")
    )
    assert ("T2 M06" in lines) == bool(side)
    assert lines.index("M30") > lines.index("T1 M06")
    assert any(v.startswith("G65 P9814") and "S1" in v for v in lines)
    assert sum(v.startswith("G65 P9814") for v in lines) == 2
    assert not any(
        "G10" in v or v.startswith("#188=") or v.startswith("#2001=") for v in lines
    )
    assert (
        not readiness["physical_validation_completed"]
        and not readiness["engineering_review_completed"]
    )
    assert (
        not readiness["manufacturing_release_enabled"]
        and not readiness["release_eligible"]
    )
    assert inputs["setup_context"]["top_face_side"] == (side or "upstream")


def test_concurrent_staging_is_idempotent_and_existing_hits_do_not_read_bytes(
    system, monkeypatch
):
    svc, a, _, _ = system
    auto = stager(svc)
    with ThreadPoolExecutor(max_workers=4) as ex:
        ids = list(ex.map(lambda _: auto.ensure("HAAS", a), range(4)))
    assert len(set(ids)) == 1 and len(svc.list(a)) == 1

    def forbidden(*a, **k):
        raise AssertionError("existing staging fetched or regenerated bytes")

    monkeypatch.setattr(svc.repo, "_read_object", forbidden)
    monkeypatch.setattr("final4.automatic.haas", forbidden)
    assert auto.ensure("HAAS", a) == ids[0]


def test_profile_changes_create_new_immutable_derivative(system):
    svc, a, _, _ = system
    auto = stager(svc)
    old = auto.ensure("HAAS", a)
    oldraw = svc.download(old, "program.NC")[2]
    auto.fixture = replace(auto.fixture, fixture_revision="SYNTHETIC-2")
    new = auto.ensure("HAAS", a)
    assert old != new and len(svc.list(a)) == 2
    assert svc.download(old, "program.NC")[2] == oldraw
    assert svc.download(new, "program.NC")[2] != oldraw
    assert auto.ensure("HAAS", a) == new


def test_unapproved_superseded_and_historical_download_gates(system):
    svc, a, _, s = system
    auto = stager(svc)
    old = auto.ensure("HAAS", a)
    raw = svc.download(old, "program.NC")[2]
    r = svc.repo.create_revision(
        a["plate_id"],
        replace(s, finished_bore_diameter=1.6),
        expected_current=a["revision_id"],
        reason="new",
        actor="fixture",
        source_snapshot={},
    )
    fresh = parent_for(svc, a, r)
    assert not auto.parents()
    for parent in (a, fresh):
        with pytest.raises(WorkflowError):
            auto.ensure("HAAS", parent)
    with pytest.raises(WorkflowError):
        svc.download(old, "program.NC")
    assert svc.download(old, "program.NC", historical=True)[2] == raw
    svc.repo.approve(svc.repo.create_delivery(r["id"])["token"], "synthetic-customer")
    assert auto.ensure("HAAS", fresh) != old


def test_download_reads_stored_bytes_without_generation_and_rejects_tamper(
    system, monkeypatch
):
    svc, a, _, _ = system
    bid = stager(svc).ensure("HAAS", a)

    def forbidden(*a, **k):
        raise AssertionError("download generated content")

    monkeypatch.setattr("final4.automatic.haas", forbidden)
    monkeypatch.setattr("final4.automatic.packaging", forbidden)

    def auth(x_api_key: str | None = Header(None)):
        if x_api_key != "fixture-owner":
            raise HTTPException(401)

    app = FastAPI()
    app.include_router(derived_router(auth, lambda: svc, server_actor="fixture"))
    c = TestClient(app)
    url = f"/admin/manufacturing/bundles/{bid}/files/program.NC"
    assert c.get(url).status_code == 401
    response = c.get(url, headers={"x-api-key": "fixture-owner"})
    assert response.status_code == 200
    f = next(f for f in svc.metadata(bid)["files"] if f["name"] == "program.NC")
    assert (
        len(response.content) == f["size"]
        and sha256(response.content).hexdigest() == f["sha256"]
    )
    with svc.repo.connect() as db:
        key = db.execute(
            "SELECT object_key FROM manufacturing_bundle_files WHERE bundle_id=? AND name=?",
            (bid, "program.NC"),
        ).fetchone()["object_key"]
    path = svc.repo.objects / key
    original = path.read_bytes()
    path.chmod(0o600)
    for tampered in (original[:-1], b"X" + original[1:]):
        path.write_bytes(tampered)
        assert c.get(url, headers={"x-api-key": "fixture-owner"}).status_code == 409


def test_unsupported_material_blocks_nc_independently_of_packaging(system):
    svc, a, _, s = system
    r = svc.repo.create_revision(
        a["plate_id"],
        replace(s, material="316 Stainless Steel"),
        expected_current=a["revision_id"],
        reason="material",
        actor="fixture",
        source_snapshot={},
    )
    svc.repo.approve(svc.repo.create_delivery(r["id"])["token"], "synthetic-customer")
    w = StagingWorker(lambda: stager(svc))
    states = w.sweep()[r["id"]]
    assert states["HAAS"]["state"] == "SETUP / PROFILE VERIFICATION REQUIRED"
    assert states["PACKAGING"]["state"] == "STAGED"
    assert not any(b["family"] == "HAAS" for b in svc.list(parent_for(svc, a, r)))


def test_background_startup_recovers_approved_records_without_owner_view(system):
    from threading import Event

    svc, a, _, _ = system
    worker = StagingWorker(lambda: stager(svc), interval=600)
    done = Event()
    sweep = worker.sweep

    def observed():
        result = sweep()
        done.set()
        return result

    worker.sweep = observed
    try:
        worker.start()
        assert done.wait(timeout=5)
        assert worker.status(a["revision_id"])["HAAS"]["state"] == "STAGED"
        assert worker.status(a["revision_id"])["PACKAGING"]["state"] == "STAGED"
    finally:
        worker.stop()
    assert not worker.thread.is_alive()


def test_metadata_views_and_downloads_do_not_append_bundles(system, monkeypatch):
    svc, a, _, _ = system
    auto = stager(svc)
    ids = [auto.ensure(f, a) for f in ("HAAS", "PACKAGING")]
    with svc.repo.connect() as db:
        before = "\n".join(db.iterdump())

    def forbidden(*a, **k):
        raise AssertionError("passive activity requested staging")

    monkeypatch.setattr(auto, "ensure", forbidden)
    for _ in range(2):
        for bid in ids:
            metadata = svc.metadata(bid)
            for f in metadata["files"]:
                svc.download(bid, f["name"])
        svc.list(a)
    with svc.repo.connect() as db:
        assert "\n".join(db.iterdump()) == before
