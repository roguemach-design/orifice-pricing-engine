"""Independent DXF reader, geometry, integrity, exact-parent and authorization tests."""

from dataclasses import asdict, replace
from hashlib import sha256
from io import StringIO
import json
from math import hypot, cos, sin, pi
from pathlib import Path
import sqlite3

import ezdxf
from fastapi import FastAPI, HTTPException, Header
from fastapi.testclient import TestClient
import pytest
from shapely.geometry import Polygon, Point
from haas_generator.contract import from_dict, CHECKS
from haas_generator.engineering import (
    Parameters,
    engineering_bundle,
    post_candidate,
    verify_geometry,
    POST_VERSION,
)
from haas_generator.generator import plan
from packaging_generator.generator import (
    Configuration,
    generate,
    layout,
    sampled_outline,
)
from plate_geometry import PlateSpec, build_plate_geometry
from frozen_plate.repository import Repository, WorkflowError, digest
from final4.service import DerivedService
from final4.api import router

ROOT = Path(__file__).resolve().parents[1]


def fixture_inputs():
    r, p = from_dict(
        json.loads((ROOT / "examples/haas/record.json").read_text()),
        json.loads((ROOT / "examples/haas/profile.json").read_text()),
    )
    config = Configuration(
        **json.loads((ROOT / "examples/final4/packaging-config.json").read_text())
    )
    params = Parameters(
        **json.loads((ROOT / "examples/final4/machining-parameters.json").read_text())
    )
    return r, p, config, params


def spec(**kw):
    return PlateSpec(
        **dict(
            finished_od=5,
            finished_bore_diameter=1.548,
            handle_width=2,
            centerline_to_handle_end=10.5,
            material="304 Stainless Steel",
            thickness=0.125,
            bore_tolerance=0.001,
            chamfer=False,
            part_identifier="SAMPLE-PLATE",
            **kw,
        )
    )


@pytest.mark.parametrize(
    "od,width,length,thickness",
    [
        (1, 0.25, 1, 0.125),
        (5, 2, 10.5, 0.125),
        (5, 2, 10.5, 0.5),
        (16, 4, 20, 0.5),
        (5, 4.8, 6, 0.25),
        (5, 0.1, 2.6, 0.125),
        (5, 2, 30, 0.375),
        (20, 6, 30, 0.5),
    ],
)
def test_packaging_independent_dxf_reader(od, width, length, thickness):
    _, _, c, _ = fixture_inputs()
    s = replace(
        spec(),
        finished_od=od,
        finished_bore_diameter=min(0.5, od / 2),
        handle_width=width,
        centerline_to_handle_end=length,
        thickness=thickness,
    )
    files = generate(s, c, {"revision": "R1"})
    assert files == generate(s, c, {"revision": "R1"})
    doc = ezdxf.read(StringIO(files["packaging.dxf"].decode("ascii")))
    assert not doc.audit().has_errors
    assert doc.units == ezdxf.units.IN
    d = layout(s, c)
    cuts = [e for e in doc.modelspace() if e.dxf.layer.startswith("CUT_")]
    assert len(cuts) == 1 + 2 * d["nest_layers"]
    assert all(e.dxftype() == "LWPOLYLINE" and e.closed for e in cuts)
    folds = [e for e in doc.modelspace() if e.dxf.layer == "SCORE_FOLD"]
    assert len(folds) == 4 and all(e.dxftype() == "LINE" for e in folds)
    assert not list(doc.modelspace().query('*[layer=="PERF_FOLD"]'))
    shell = [e for e in cuts if e.dxf.layer == "CUT_SHELL"][0]
    pts = list(shell.get_points("xy"))
    assert max(x for x, y in pts) - min(x for x, y in pts) == pytest.approx(
        d["flat_shell"][0]
    )
    assert max(y for x, y in pts) == pytest.approx(d["flat_shell"][1])
    # Independent analytic sample: every canonical arc point lies INSIDE the cut hole.
    hole = [e for e in cuts if e.dxf.layer == "CUT_NEST"][0]
    coords = list(hole.get_points("xy"))
    hole_poly = Polygon(coords)
    x0, y0 = d["frame_positions"][0]
    for seg in build_plate_geometry(s).segments:
        for i in range(101):
            if seg.kind == "arc":
                a = (seg.start_degrees + seg.sweep_degrees * i / 100) * pi / 180
                x, y = seg.center[0] + seg.radius * cos(a), seg.center[
                    1
                ] + seg.radius * sin(a)
            else:
                x, y = [a + (b - a) * i / 100 for a, b in zip(seg.start, seg.end)]
            point = Point(
                -y + d["panel_width"] / 2 + x0, x + c.margin + s.finished_od / 2 + y0
            )
            assert hole_poly.contains(point)
            assert (
                hole_poly.boundary.distance(point) >= c.clearance - c.kerf / 2 - 0.0002
            )
    assert d["compressed_nest_depth"] >= s.thickness + c.depth_clearance
    assert (d["nest_layers"] - 1) * c.caliper * (
        1 - c.compression_fraction
    ) < s.thickness + c.depth_clearance
    m = json.loads(files["manifest.json"])
    for name, a in m["files"].items():
        assert len(files[name]) == a["size"] and digest(files[name]) == a["sha256"]


def test_handle_hole_does_not_change_nest():
    _, _, c, _ = fixture_inputs()
    s = spec()
    with_hole = replace(
        s,
        handle_hole_enabled=True,
        handle_hole_diameter=0.375,
        handle_hole_center_from_handle_end=0.75,
    )
    assert (
        generate(s, c, {})["packaging.dxf"]
        == generate(with_hole, c, {})["packaging.dxf"]
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"caliper": float("nan")},
        {"compression_fraction": 1},
        {"kerf": 0.1},
        {"clearance": True},
        {"max_layers": True},
        {"margin": 0.5},
        {"closure": "TAPE"},
        {"flute_direction": "UNKNOWN"},
    ],
)
def test_bad_board_parameters_rejected(changes):
    _, _, c, _ = fixture_inputs()
    with pytest.raises(ValueError):
        replace(c, **changes)


def test_sheet_layer_and_thickness_bounds():
    _, _, c, _ = fixture_inputs()
    for s, p in [
        (replace(spec(), thickness=0.75), c),
        (spec(), replace(c, max_sheet_width=12, max_sheet_height=12)),
        (replace(spec(), thickness=0.5), replace(c, max_layers=1)),
        (
            replace(
                spec(),
                finished_od=24,
                handle_width=6,
                centerline_to_handle_end=36,
                thickness=0.5,
            ),
            c,
        ),
    ]:
        with pytest.raises(ValueError):
            layout(s, p)


def test_engineering_parameters_and_independent_verifier():
    r, p, _, params = fixture_inputs()
    parent = {"revision_id": "synthetic", "spec_sha256": "0" * 64}
    b = engineering_bundle(r, p, params, parent)
    assert b == engineering_bundle(r, p, params, parent)
    changed = engineering_bundle(
        r, p, replace(params, radial_step=0.025, finish_stock=0.012), parent
    )
    assert b["program.NC"] != changed["program.NC"]
    assert "#3000=1" in changed["program.NC"]
    assert not json.loads(b["readiness.json"])["release_eligible"]
    g = plan(r, p, params)
    g["paths"]["finish_wear_adjusted_tool_center"][0][0] += 0.05
    with pytest.raises(ValueError):
        verify_geometry(r, p, g)
    with pytest.raises(ValueError):
        post_candidate(r, p, params, parent, authorization={}, generator_actor="owner")


def test_candidate_post_requires_independent_exact_fingerprint():
    r, p, _, params = fixture_inputs()
    p = replace(
        p, verified_by="SYNTHETIC ONLY", evidence={k: "TEST EVIDENCE" for k in CHECKS}
    )
    b = engineering_bundle(r, p, params, {})
    a = {
        "programmer": "independent",
        "evidence_reference": "TEST ONLY",
        "profile_sha256": digest(
            json.dumps(asdict(p), sort_keys=True, separators=(",", ":"))
        ),
        "input_sha256": json.loads(b["manifest.json"])["input_sha256"],
        "post_version": POST_VERSION,
    }
    candidate = post_candidate(
        r, p, params, {}, authorization=a, generator_actor="owner"
    )
    assert "G20 G17 G90" in candidate["candidate.NC"]
    assert (
        json.loads(candidate["candidate-authorization.json"])["state"]
        == "MACHINE PROVE-OUT REQUIRED"
    )
    assert not json.loads(candidate["candidate-authorization.json"])[
        "manufacturing_release_enabled"
    ]
    for bad in (
        {**a, "programmer": "owner"},
        {**a, "input_sha256": "0" * 64},
        {**a, "post_version": "other"},
    ):
        with pytest.raises(ValueError):
            post_candidate(r, p, params, {}, authorization=bad, generator_actor="owner")


@pytest.fixture
def system(tmp_path):
    repo = Repository(tmp_path / "private", "test-only-approval-key-" + "x" * 40)
    plate = repo.create_plate(
        order_id="SYNTHETIC-001",
        line_id="L1",
        configuration_id="synthetic",
        customer_id="synthetic-customer",
        actor="owner",
    )
    s = spec()
    rev = repo.create_revision(
        plate,
        s,
        expected_current=None,
        reason="synthetic",
        actor="owner",
        source_snapshot={"synthetic": True},
    )
    delivery = repo.create_delivery(rev["id"])
    repo.approve(delivery["token"], "synthetic-customer")
    association = dict(
        order_id="SYNTHETIC-001",
        line_id="L1",
        plate_id=plate,
        revision_id=rev["id"],
        spec_sha256=rev["spec_sha256"],
        source_sha256=rev["source_sha256"],
    )
    r, p, c, params = fixture_inputs()
    r = replace(r, top_chamfer_width=0, source_sha256=rev["spec_sha256"])
    svc = DerivedService(
        repo, machine_profile=p, packaging_config=c, machining_parameters=params
    )
    svc.initialize_isolated_sqlite()
    return svc, association, r, s


@pytest.mark.parametrize("family", ["HAAS", "PACKAGING"])
def test_immutable_associated_artifacts_and_download(system, family):
    svc, a, r, s = system
    before = svc.repo.revision(a["revision_id"])
    b = svc.create(
        family,
        a,
        actor="owner",
        reviewed_record=asdict(r) if family == "HAAS" else None,
    )
    again = svc.create(
        family,
        a,
        actor="owner",
        reviewed_record=asdict(r) if family == "HAAS" else None,
    )
    assert b["id"] != again["id"]
    assert b["input_sha256"] == again["input_sha256"]
    assert (
        not b["statuses"]["physical_validation_completed"]
        and not b["statuses"]["release_eligible"]
    )
    for f in b["files"]:
        filename, hash_, data = svc.download(b["id"], f["name"])
        assert hash_ == digest(data) and len(data) == f["size"]
    assert svc.repo.revision(a["revision_id"]) == before
    for table in (
        "manufacturing_bundles",
        "manufacturing_bundle_files",
        "manufacturing_evidence",
    ):
        with svc.repo.transaction() as db:
            if table == "manufacturing_evidence":
                continue
            with pytest.raises(sqlite3.IntegrityError):
                db.execute(f"DELETE FROM {table}")


@pytest.mark.parametrize(
    "key",
    ["order_id", "line_id", "plate_id", "revision_id", "spec_sha256", "source_sha256"],
)
def test_wrong_association_rejected(system, key):
    svc, a, r, _ = system
    with pytest.raises(WorkflowError):
        svc.create("PACKAGING", {**a, key: "wrong"}, actor="owner")


@pytest.mark.parametrize(
    "changes",
    [
        {"finished_bore": 1.55},
        {"thickness": 0.25},
        {"material": "Carbon Steel"},
        {"drawing_revision": "R2"},
        {"source_sha256": "0" * 64},
        {"top_chamfer_width": 0.01},
        {"bore_tolerance": 0.002},
    ],
)
def test_record_spec_mismatch(system, changes):
    svc, a, r, _ = system
    with pytest.raises((WorkflowError, ValueError)):
        svc.create(
            "HAAS", a, actor="owner", reviewed_record=asdict(replace(r, **changes))
        )


def test_tampered_length_and_hash_rejected(system):
    svc, a, r, _ = system
    b = svc.create("PACKAGING", a, actor="owner")
    with svc.repo.connect() as db:
        row = db.execute(
            "SELECT * FROM manufacturing_bundle_files WHERE bundle_id=? AND name='packaging.dxf'",
            (b["id"],),
        ).fetchone()
    path = svc.repo.objects / row["object_key"]
    data = path.read_bytes()
    path.chmod(0o600)
    for bad in (data[:-1], b"X" + data[1:]):
        path.write_bytes(bad)
        with pytest.raises(WorkflowError):
            svc.download(b["id"], "packaging.dxf")
    path.write_bytes(data)
    assert svc.download(b["id"], "packaging.dxf")[2] == data


def test_superseded_artifact_historical_only(system):
    svc, a, r, s = system
    b = svc.create("PACKAGING", a, actor="owner")
    svc.repo.create_revision(
        a["plate_id"],
        replace(s, finished_bore_diameter=1.6),
        expected_current=a["revision_id"],
        reason="R2",
        actor="owner",
        source_snapshot={},
    )
    assert not svc.metadata(b["id"])["statuses"]["parent_current"]
    assert svc.download(b["id"], "packaging.dxf")[2]
    with pytest.raises(WorkflowError):
        svc.create("PACKAGING", a, actor="owner")
    with pytest.raises(WorkflowError):
        svc.record_evidence(
            b["id"],
            gate="ENGINEERING_REVIEW",
            reference="test",
            actor="independent",
            manifest_sha256=b["manifest_sha256"],
        )


def test_evidence_does_not_enable_release(system):
    svc, a, r, s = system
    b = svc.create("PACKAGING", a, actor="owner")
    with pytest.raises(WorkflowError):
        svc.record_evidence(
            b["id"],
            gate="ENGINEERING_REVIEW",
            reference="test",
            actor="owner",
            manifest_sha256=b["manifest_sha256"],
        )
    b = svc.record_evidence(
        b["id"],
        gate="ENGINEERING_REVIEW",
        reference="TEST REVIEW",
        actor="independent",
        manifest_sha256=b["manifest_sha256"],
    )
    assert b["statuses"]["engineering_review_completed"]
    with pytest.raises(WorkflowError):
        svc.record_evidence(
            b["id"],
            gate="PHYSICALLY_VERIFIED",
            reference="TEST",
            actor="independent",
            manifest_sha256=b["manifest_sha256"],
        )
    assert not b["statuses"]["manufacturing_release_approved"]


def test_owner_routes_authorization_and_no_profile_override(system):
    svc, a, r, s = system

    def auth(x_api_key: str | None = Header(default=None)):
        if x_api_key != "test-owner":
            raise HTTPException(401, "Unauthorized")

    app = FastAPI()
    app.include_router(router(auth, lambda: svc, server_actor="owner"))
    client = TestClient(app)
    for method, path in [
        ("post", "/admin/manufacturing/bundles"),
        ("post", "/admin/manufacturing/bundles/query"),
        ("get", "/admin/manufacturing/bundles/missing"),
        ("get", "/admin/manufacturing/bundles/missing/files/program.NC"),
    ]:
        assert getattr(client, method)(path).status_code == 401
    h = {"x-api-key": "test-owner"}
    req = {"family": "PACKAGING", "parent": a}
    assert (
        client.post(
            "/admin/manufacturing/bundles", json={**req, "profile": {}}, headers=h
        ).status_code
        == 422
    )
    response = client.post("/admin/manufacturing/bundles", json=req, headers=h)
    assert response.status_code == 200
    b = response.json()
    f = client.get(
        f"/admin/manufacturing/bundles/{b['id']}/files/packaging.dxf", headers=h
    )
    assert f.status_code == 200 and f.headers["x-artifact-sha256"] == digest(f.content)
    assert (
        f.headers["cache-control"] == "no-store"
        and "PACKAGING-PROTOTYPE" in f.headers["content-disposition"]
    )
    assert client.post("/admin/manufacturing/release", headers=h).status_code == 404


def test_unapproved_parent_and_incomplete_review_hold(system):
    svc, a, r, s = system
    r2 = svc.repo.create_revision(
        a["plate_id"],
        s,
        expected_current=a["revision_id"],
        reason="unapproved R2",
        actor="owner",
        source_snapshot={},
    )
    a = {
        **a,
        "revision_id": r2["id"],
        "spec_sha256": r2["spec_sha256"],
        "source_sha256": r2["source_sha256"],
    }
    with pytest.raises(WorkflowError):
        svc.create("PACKAGING", a, actor="owner")


def test_concurrent_generation_is_append_only(system):
    from concurrent.futures import ThreadPoolExecutor

    svc, a, r, s = system
    with ThreadPoolExecutor(max_workers=2) as pool:
        bundles = list(
            pool.map(lambda _: svc.create("PACKAGING", a, actor="owner"), range(2))
        )
    assert len({b["id"] for b in bundles}) == 2
    assert len(svc.list(a)) == 2
    assert bundles[0]["input_sha256"] == bundles[1]["input_sha256"]


def test_staging_harness_authentication_and_exact_download(monkeypatch):
    from final4.staging_app import create_app

    monkeypatch.setenv("FINAL4_ENV", "isolated-synthetic-staging")
    monkeypatch.setenv("FINAL4_STAGING_ADMIN_KEY", "TEST-ONLY-" + "z" * 40)
    monkeypatch.setenv("APP_ENV", "staging")
    with TestClient(create_app()) as client:
        assert client.get("/health").json()["manufacturing_release_enabled"] is False
        assert client.get("/admin/manufacturing/synthetic-fixture").status_code == 401
        h = {"x-api-key": "TEST-ONLY-" + "z" * 40}
        fixture = client.get("/admin/manufacturing/synthetic-fixture", headers=h).json()
        for b in fixture["bundles"]:
            for f in b["files"]:
                response = client.get(
                    f"/admin/manufacturing/bundles/{b['id']}/files/{f['name']}",
                    headers=h,
                )
                assert response.status_code == 200
                assert sha256(response.content).hexdigest() == f["sha256"]
        for family in ("HAAS", "PACKAGING"):
            payload = {"family": family, "parent": fixture["parent"]}
            if family == "HAAS":
                payload["reviewed_record"] = fixture["reviewed_record"]
            assert (
                client.post(
                    "/admin/manufacturing/bundles", headers=h, json=payload
                ).status_code
                == 200
            )
        assert (
            client.post(
                "/admin/manufacturing/bundles", content=b"x" * 65537, headers=h
            ).status_code
            == 413
        )
    monkeypatch.setenv("APP_ENV", "production")
    with pytest.raises(ValueError):
        create_app()
