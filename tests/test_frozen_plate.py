"""Phase 4 integrity, transport and real concurrent SQLite transactions."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, replace
from email import policy
from email.parser import BytesParser
from hashlib import sha256
import json
import sqlite3
from threading import Barrier

from fastapi.testclient import TestClient
import pytest

from frozen_plate.repository import Repository, WorkflowError, ROUTES, canonical, digest
from frozen_plate.order_adapter import specification_from_order
from frozen_plate.presentation import APPROVAL_COPY, BUTTON
from frozen_plate.web import create_app, ORIGIN
from prototype_manufacturing import sample_spec


@pytest.fixture
def setup(tmp_path):
    repo = Repository(tmp_path / "private", "dedicated-approval-test-key-" + "a" * 32)
    plate = repo.create_plate(
        order_id="OP-PROTOTYPE-001",
        line_id="L1",
        configuration_id="fixture-1",
        customer_id="customer-1",
        actor="test-admin",
    )
    spec = replace(sample_spec(), part_identifier="PROTOTYPE-001")
    return repo, plate, spec


def freeze(setup, *, expected=None, spec=None):
    repo, plate, original = setup
    return repo.create_revision(
        plate,
        spec or original,
        expected_current=expected,
        reason="test revision",
        actor="test-admin",
        source_snapshot={"fixture": "test", "spec": asdict(spec or original)},
    )


def count(repo, table):
    with repo.connect() as db:
        return db.execute("SELECT COUNT(*) FROM frozen_plate_" + table).fetchone()[0]


def test_freeze_pair_hashes_and_immutable_history(setup):
    repo, plate, spec = setup
    r1 = freeze(setup)
    from plate_geometry import canonical_specification
    assert json.loads(r1["spec_json"]) == canonical_specification(spec)
    assert digest(r1["spec_json"]) == r1["spec_sha256"]
    for kind, artifact in r1["artifacts"].items():
        raw = (repo.objects / artifact["object_key"]).read_bytes()
        assert digest(raw) == artifact["sha256"] and len(raw) == artifact["size"]
        assert artifact["revision_id"] == r1["id"]
        assert artifact["filename"] == f"OP-PROTOTYPE-001-L1-R1.{kind}"
    r2 = freeze(
        setup, expected=r1["id"], spec=replace(spec, finished_bore_diameter=1.6)
    )
    assert r2["number"] == 2 and r2["spec_sha256"] != r1["spec_sha256"]
    assert repo.revision(r1["id"]) == r1
    assert repo.plate(plate)["current_revision"] == r2["id"]
    for kind in ("pdf", "dxf", "json"):
        assert r2["artifacts"][kind]["sha256"] != r1["artifacts"][kind]["sha256"]
        assert "R2." in r2["artifacts"][kind]["filename"]


@pytest.mark.parametrize(
    "table,column", [("revisions", "spec_json"), ("artifacts", "sha256")]
)
def test_database_rejects_frozen_mutation(setup, table, column):
    repo, _, _ = setup
    freeze(setup)
    with repo.transaction() as db:
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            db.execute(f"UPDATE frozen_plate_{table} SET {column}='changed'")
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            db.execute(f"DELETE FROM frozen_plate_{table}")


@pytest.mark.parametrize("failure", ["generator", "validation", "database"])
def test_failed_generation_leaves_no_approvable_revision(setup, monkeypatch, failure):
    import frozen_plate.repository as module

    repo, plate, _ = setup
    if failure == "database":
        with repo.connect() as db:
            db.execute(
                "CREATE TRIGGER inject_failure BEFORE INSERT ON frozen_plate_artifacts BEGIN SELECT RAISE(ABORT,'injected failure'); END"
            )
    else:
        target = "generate_package" if failure == "generator" else "validate_package"

        def fail(*a, **kw):
            raise ValueError("injected failure")

        monkeypatch.setattr(module, target, fail)
    with pytest.raises((ValueError, sqlite3.IntegrityError)):
        freeze(setup)
    assert repo.plate(plate)["current_revision"] is None
    assert (
        count(repo, "revisions")
        == count(repo, "artifacts")
        == count(repo, "tokens")
        == 0
    )
    assert not list(repo.objects.rglob("*.pdf"))


def test_delivery_has_only_exact_pdf_and_fixed_copy(setup):
    repo, _, _ = setup
    r1 = freeze(setup)
    delivery = repo.create_delivery(r1["id"])
    msg = BytesParser(policy=policy.default).parsebytes(delivery["mime"])
    attachments = list(msg.iter_attachments())
    assert (
        len(attachments) == 1 and attachments[0].get_content_type() == "application/pdf"
    )
    assert (
        digest(attachments[0].get_payload(decode=True))
        == r1["artifacts"]["pdf"]["sha256"]
    )
    html = msg.get_body(preferencelist=("html",)).get_content()
    assert APPROVAL_COPY in html and BUTTON in html
    assert (
        ".dxf" not in html.lower()
        and "DXF" not in msg.get_body(preferencelist=("plain",)).get_content()
    )
    with repo.connect() as db:
        row = dict(db.execute("SELECT * FROM frozen_plate_deliveries").fetchone())
    assert (
        row["pdf_id"] == r1["artifacts"]["pdf"]["id"]
        and row["state"] == "LOCAL_RENDERED"
        and row["sent_at"] is None
    )
    assert delivery["token"].encode() not in repo.db_path.read_bytes()


def test_approval_exact_and_idempotent(setup):
    repo, plate, _ = setup
    r1 = freeze(setup)
    d = repo.create_delivery(r1["id"])
    first = repo.approve(d["token"], "customer-1")
    second = repo.approve(d["token"], "customer-1")
    assert first == second and count(repo, "approvals") == 1
    a = first["approval"]
    assert a["revision_id"] == r1["id"] and a["pdf_id"] == r1["artifacts"]["pdf"]["id"]
    assert (
        a["pdf_sha256"] == r1["artifacts"]["pdf"]["sha256"]
        and a["spec_sha256"] == r1["spec_sha256"]
    )
    assert repo.plate(plate)["lifecycle"] == "CUSTOMER_APPROVED"


@pytest.mark.parametrize(
    "alter", ["invalid", "tampered", "wrong-customer", "expired", "revoked"]
)
def test_token_failure(setup, alter):
    repo, _, _ = setup
    r = freeze(setup)
    token = repo.create_delivery(r["id"])["token"]
    customer = "customer-1"
    if alter == "invalid":
        token = "invalid"
    if alter == "tampered":
        token = "x" + token[1:]
    if alter == "wrong-customer":
        customer = "customer-2"
    if alter == "expired":
        repo.clock = lambda: 9999999999
    if alter == "revoked":
        repo.revoke(token, actor="test-admin", reason="replacement")
    with pytest.raises(WorkflowError):
        repo.approve(token, customer)
    assert count(repo, "approvals") == 0


def test_superseded_pending_token_cannot_approve_r2(setup):
    repo, plate, _ = setup
    r1 = freeze(setup)
    token = repo.create_delivery(r1["id"])["token"]
    r2 = freeze(setup, expected=r1["id"])
    assert repo.inspect_token(token, "customer-1")["state"] == "superseded"
    with pytest.raises(WorkflowError, match="superseded"):
        repo.approve(token, "customer-1")
    assert count(repo, "approvals") == 0
    new = repo.create_delivery(r2["id"])
    assert (
        repo.approve(new["token"], "customer-1")["approval"]["revision_id"] == r2["id"]
    )


def test_approved_old_revision_remains_success_but_cannot_source(setup):
    repo, plate, _ = setup
    r1 = freeze(setup)
    token = repo.create_delivery(r1["id"])["token"]
    repo.approve(token, "customer-1")
    freeze(setup, expected=r1["id"])
    old = repo.approve(token, "customer-1")
    assert (
        old["state"] == "approved"
        and old["historical"]
        and count(repo, "approvals") == 1
    )
    assert repo.plate(plate)["lifecycle"] == "READY_FOR_CUSTOMER_CONFIRMATION"
    with pytest.raises(WorkflowError):
        repo.select_source(r1["id"], "ALRO", actor="admin")


@pytest.mark.parametrize("kind", ["pdf", "dxf", "json"])
@pytest.mark.parametrize("operation", ["approve", "source"])
def test_modified_objects_block_approval_and_routing(setup, kind, operation):
    repo, _, _ = setup
    r = freeze(setup)
    token = repo.create_delivery(r["id"])["token"]
    if operation == "source":
        repo.approve(token, "customer-1")
    path = repo.objects / r["artifacts"][kind]["object_key"]
    path.chmod(0o600)
    path.write_bytes(path.read_bytes() + b"altered")
    with pytest.raises(WorkflowError, match="integrity"):
        if operation == "approve":
            repo.approve(token, "customer-1")
        else:
            repo.select_source(r["id"], "ALRO", actor="admin")
    assert count(repo, "sourcing") == 0


def test_missing_file_blocks_delivery(setup):
    repo, _, _ = setup
    r = freeze(setup)
    (repo.objects / r["artifacts"]["pdf"]["object_key"]).unlink()
    with pytest.raises(WorkflowError, match="unavailable"):
        repo.create_delivery(r["id"])
    assert count(repo, "deliveries") == 0


def test_cross_revision_foreign_keys_and_unique_artifacts(setup):
    repo, _, _ = setup
    r1 = freeze(setup)
    r2 = freeze(setup, expected=r1["id"])
    with repo.transaction() as db:
        with pytest.raises(sqlite3.IntegrityError):
            db.execute(
                "INSERT INTO frozen_plate_tokens(fingerprint,revision_id,pdf_id,pdf_sha256,spec_sha256,customer_id,order_id,created_at,expires_at) VALUES ('bad',?,?,? ,?,'customer-1','order','now',9999999999)",
                (
                    r2["id"],
                    r1["artifacts"]["pdf"]["id"],
                    r1["artifacts"]["pdf"]["sha256"],
                    r2["spec_sha256"],
                ),
            )
        a = r1["artifacts"]["dxf"]
        with pytest.raises(sqlite3.IntegrityError):
            db.execute(
                "INSERT INTO frozen_plate_artifacts VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    "new",
                    r1["id"],
                    "dxf",
                    "other-key",
                    "other.dxf",
                    a["sha256"],
                    a["size"],
                    a["generator_version"],
                    a["generated_at"],
                ),
            )


def test_atomic_approval_rollback(setup):
    repo, plate, _ = setup
    r = freeze(setup)
    token = repo.create_delivery(r["id"])["token"]
    with repo.connect() as db:
        db.execute(
            "CREATE TRIGGER fail_state BEFORE UPDATE OF lifecycle ON frozen_plates WHEN NEW.lifecycle='CUSTOMER_APPROVED' BEGIN SELECT RAISE(ABORT,'state failure'); END"
        )
    with pytest.raises(sqlite3.IntegrityError):
        repo.approve(token, "customer-1")
    assert (
        count(repo, "approvals") == 0
        and repo.plate(plate)["lifecycle"] == "READY_FOR_CUSTOMER_CONFIRMATION"
    )


@pytest.mark.parametrize("route", ROUTES)
def test_routes_reference_exact_approved_dxf_no_submission(setup, route):
    repo, plate, _ = setup
    r = freeze(setup)
    with pytest.raises(WorkflowError):
        repo.select_source(r["id"], route, actor="admin")
    token = repo.create_delivery(r["id"])["token"]
    repo.approve(token, "customer-1")
    selection = repo.select_source(r["id"], route, actor="admin")
    assert selection == repo.select_source(r["id"], route, actor="admin")
    assert selection["dxf_id"] == r["artifacts"]["dxf"]["id"]
    assert selection["dxf_sha256"] == r["artifacts"]["dxf"]["sha256"]
    assert (
        selection["state"] == "LOCAL_SELECTION_ONLY"
        and selection["submitted_at"] is None
        and not selection["released"]
    )
    assert repo.plate(plate)["lifecycle"] == "READY_FOR_RELEASE"


def concurrent(*actions):
    barrier = Barrier(len(actions))

    def run(action):
        barrier.wait()
        try:
            return action()
        except WorkflowError as error:
            return error

    with ThreadPoolExecutor(max_workers=len(actions)) as pool:
        return list(pool.map(run, actions))


def test_concurrent_double_approval(setup):
    repo, _, _ = setup
    r = freeze(setup)
    token = repo.create_delivery(r["id"])["token"]
    results = concurrent(
        lambda: repo.approve(token, "customer-1"),
        lambda: repo.approve(token, "customer-1"),
    )
    assert (
        all(r["state"] == "approved" for r in results) and count(repo, "approvals") == 1
    )


def test_concurrent_duplicate_revision(setup):
    repo, _, _ = setup
    r1 = freeze(setup)
    results = concurrent(
        lambda: freeze(setup, expected=r1["id"]),
        lambda: freeze(setup, expected=r1["id"]),
    )
    assert (
        sum(isinstance(r, WorkflowError) for r in results) == 1
        and count(repo, "revisions") == 2
    )


def test_approval_vs_supersession_race(setup):
    repo, plate, _ = setup
    r1 = freeze(setup)
    token = repo.create_delivery(r1["id"])["token"]
    results = concurrent(
        lambda: repo.approve(token, "customer-1"),
        lambda: freeze(setup, expected=r1["id"]),
    )
    assert count(repo, "revisions") == 2
    r2 = repo.plate(plate)["current_revision"]
    with repo.connect() as db:
        assert not db.execute(
            "SELECT 1 FROM frozen_plate_approvals WHERE revision_id=?", (r2,)
        ).fetchone()
    assert repo.plate(plate)["lifecycle"] == "READY_FOR_CUSTOMER_CONFIRMATION"
    assert (
        isinstance(results[0], WorkflowError)
        or results[0]["approval"]["revision_id"] == r1["id"]
    )


def web_fixture(setup):
    repo, _, _ = setup
    r = freeze(setup)
    d = repo.create_delivery(r["id"])
    app = create_app(repo, session_key="s" * 32, admin_key="a" * 32)
    client = TestClient(app, base_url=ORIGIN)
    cookie, csrf = app.state.local_sessions.issue("customer-1")
    client.cookies.set("fp_local_session", cookie)
    return repo, r, d, app, client, csrf


def test_one_deliberate_form_post_success_and_passive_requests(setup):
    repo, r, d, app, client, csrf = web_fixture(setup)
    token = d["token"]
    for path in ("/approve/", "/local-email/"):
        assert client.get(path + token).status_code == 200
    assert client.head("/approve/" + token).status_code == 200
    assert count(repo, "approvals") == 0
    html = client.get("/local-email/" + token).text
    assert html.count("<button") == 1 and 'method="post"' in html
    response = client.post(
        "/approve/" + token, data={"csrf": csrf}, headers={"Origin": ORIGIN}
    )
    assert (
        response.status_code == 200 and "YOUR ORDER IS IN PRODUCTION" in response.text
    )
    assert "<button" not in response.text and "READY_FOR_RELEASE" not in response.text
    assert count(repo, "approvals") == 1
    assert (
        client.get("/approve/" + token).status_code == 200
        and count(repo, "approvals") == 1
    )
    pdf = client.get("/attachment/" + token)
    assert digest(pdf.content) == r["artifacts"]["pdf"]["sha256"]
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize(
    "attack",
    [
        "no-session",
        "wrong-session",
        "no-csrf",
        "wrong-origin",
        "cross-site",
        "forged-session",
    ],
)
def test_request_authentication_and_csrf(setup, attack):
    repo, r, d, app, client, csrf = web_fixture(setup)
    origin = ORIGIN
    headers = {}
    if attack == "no-session":
        client.cookies.clear()
    if attack == "wrong-session":
        client.cookies.set(
            "fp_local_session", app.state.local_sessions.issue("customer-2")[0]
        )
    if attack == "no-csrf":
        csrf = ""
    if attack == "wrong-origin":
        origin = "https://attacker.invalid"
    if attack == "cross-site":
        headers["sec-fetch-site"] = "cross-site"
    if attack == "forged-session":
        client.cookies.set("fp_local_session", "forged")
    response = client.post(
        "/approve/" + d["token"],
        data={"csrf": csrf},
        headers={"Origin": origin, **headers},
    )
    assert response.status_code in (401, 403, 409)
    assert count(repo, "approvals") == 0


def test_customer_token_grants_no_internal_rights(setup):
    repo, r, d, app, client, csrf = web_fixture(setup)
    path = f'/internal/revisions/{r["id"]}/source'
    assert client.get(path).status_code == 401
    assert (
        client.post(
            path, json={"route": "ALRO"}, headers={"x-api-key": d["token"]}
        ).status_code
        == 401
    )
    assert (
        client.get("/objects/" + r["artifacts"]["dxf"]["object_key"]).status_code == 404
    )
    assert client.get("/attachment/" + d["token"] + "/dxf").status_code == 404
    client.post(
        "/approve/" + d["token"], data={"csrf": csrf}, headers={"Origin": ORIGIN}
    )
    assert client.get(path, headers={"x-api-key": "a" * 32}).status_code == 200
    response = client.post(
        path, json={"route": "ALRO"}, headers={"x-api-key": "a" * 32}
    )
    assert (
        response.status_code == 200
        and response.json()["dxf_id"] == r["artifacts"]["dxf"]["id"]
    )


def test_order_adapter_handles_current_single_and_cart_payloads():
    config = {
        "paddle_dia": 5,
        "bore_dia": 1.548,
        "handle_width": 2,
        "handle_length_from_bore": 10.5,
        "material": "304 stainless steel",
        "thickness": 0.125,
        "quantity": 1,
    }
    for payload in (config, {"cart_items": [config]}):
        spec, source = specification_from_order(
            {"id": "order", "customer_id": "customer", "quote_payload": payload},
            line_index=0,
            part_identifier="PROTOTYPE-001",
        )
        assert (
            spec.finished_bore_diameter == 1.548 and source["configuration"] == config
        )
        with pytest.raises(WorkflowError):
            specification_from_order(
                {"id": "order", "customer_id": "customer", "quote_payload": payload},
                line_index=1,
                part_identifier="PROTOTYPE-001",
            )


def test_customer_token_cannot_select_other_plate(setup):
    repo, plate, spec = setup
    r1 = freeze(setup)
    token = repo.create_delivery(r1["id"])["token"]
    other = repo.create_plate(
        order_id="OTHER",
        line_id="L1",
        configuration_id="other-config",
        customer_id="customer-1",
        actor="admin",
    )
    r2 = repo.create_revision(
        other,
        spec,
        expected_current=None,
        reason="another order",
        actor="admin",
        source_snapshot={"fixture": "other"},
    )
    repo.approve(token, "customer-1")
    assert repo.plate(other)["lifecycle"] == "READY_FOR_CUSTOMER_CONFIRMATION"
    with repo.connect() as db:
        assert not db.execute(
            "SELECT 1 FROM frozen_plate_approvals WHERE revision_id=?", (r2["id"],)
        ).fetchone()
    assert count(repo, "approvals") == 1


def test_cross_revision_sourcing_rejected_by_database(setup):
    repo, _, _ = setup
    r1 = freeze(setup)
    repo.approve(repo.create_delivery(r1["id"])["token"], "customer-1")
    r2 = freeze(setup, expected=r1["id"])
    repo.approve(repo.create_delivery(r2["id"])["token"], "customer-1")
    with repo.transaction() as db:
        with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
            db.execute(
                "INSERT INTO frozen_plate_sourcing(id,revision_id,dxf_id,route,state,selected_at,selected_by) VALUES ('bad',?,?,'ALRO','LOCAL_SELECTION_ONLY','now','admin')",
                (r2["id"], r1["artifacts"]["dxf"]["id"]),
            )


def test_frozen_hashes_are_deterministic_across_repositories(setup, tmp_path):
    repo, _, spec = setup
    r1 = freeze(setup)
    other = Repository(tmp_path / "other", "k" * 32)
    plate = other.create_plate(
        order_id="OP-PROTOTYPE-001",
        line_id="L1",
        configuration_id="fixture-1",
        customer_id="customer-1",
        actor="test-admin",
    )
    r2 = freeze((other, plate, spec))
    assert r1["id"] != r2["id"] and r1["spec_sha256"] == r2["spec_sha256"]
    assert {k: v["sha256"] for k, v in r1["artifacts"].items()} == {
        k: v["sha256"] for k, v in r2["artifacts"].items()
    }


def test_concurrent_duplicate_sourcing(setup):
    repo, _, _ = setup
    r = freeze(setup)
    repo.approve(repo.create_delivery(r["id"])["token"], "customer-1")
    results = concurrent(
        lambda: repo.select_source(r["id"], "ALRO", actor="admin"),
        lambda: repo.select_source(r["id"], "ALRO", actor="admin"),
    )
    assert results[0] == results[1] and count(repo, "sourcing") == 1


def test_internal_source_control_form_is_authorized(setup):
    repo, r, d, app, client, csrf = web_fixture(setup)
    repo.approve(d["token"], "customer-1")
    path = f'/internal/revisions/{r["id"]}/source'
    response = client.post(
        path,
        data={"route": "ROGUE_INTERNAL"},
        headers={"x-api-key": "a" * 32, "Origin": ORIGIN},
    )
    assert response.status_code == 200 and response.json()["route"] == "ROGUE_INTERNAL"
    assert response.json()["internal_manufacturing_state"] == "NOT_RELEASED"


def test_failed_r2_preserves_approved_r1(setup, monkeypatch):
    repo, plate, _ = setup
    r1 = freeze(setup)
    repo.approve(repo.create_delivery(r1["id"])["token"], "customer-1")
    import frozen_plate.repository as module

    def fail(*args, **kwargs):
        raise ValueError("failure")

    monkeypatch.setattr(module, "generate_package", fail)
    with pytest.raises(ValueError):
        freeze(setup, expected=r1["id"])
    assert repo.revision(r1["id"]) == r1
    assert repo.plate(plate)["current_revision"] == r1["id"]
    assert repo.plate(plate)["lifecycle"] == "CUSTOMER_APPROVED"
