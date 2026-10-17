"""Run in the staging API runtime: synthetic PostgreSQL + private-storage acceptance.

No remote credentials are exported. Existing records and bytes are never changed.
"""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, replace
from hashlib import sha256
import json
import os
from uuid import uuid4
from pathlib import Path
from frozen_plate.runtime import repository
from frozen_plate.repository import WorkflowError, canonical
from haas_generator.contract import from_dict
from .runtime import service
from .postgres import verify_repository
from plate_geometry import PlateSpec


def main():
    if os.environ.get("APP_ENV") != "staging":
        raise RuntimeError("synthetic verification restricted to staging")
    s = service()
    repo = s.repo
    schema = verify_repository(repo)
    checks = []

    def check(name, value):
        if not value:
            raise AssertionError(name)
        checks.append(name)

    def rejected(name, action):
        try:
            action()
        except (WorkflowError, ValueError, TypeError, KeyError):
            checks.append(name)
        else:
            raise AssertionError(name)

    # Retain original rows byte-for-byte in memory for comparison after new records.
    tables = (
        "frozen_plates",
        "frozen_plate_revisions",
        "frozen_plate_artifacts",
        "frozen_plate_approvals",
        "frozen_plate_tokens",
        "frozen_plate_deliveries",
        "frozen_plate_sourcing",
    )
    with repo.connect() as db:
        original = {
            t: [dict(r) for r in db.execute("SELECT * FROM " + t)] for t in tables
        }
    job = "FINAL4-SYNTHETIC-" + uuid4().hex[:12]
    r, _ = from_dict(
        json.loads(
            (
                Path(__file__).resolve().parents[1] / "examples/haas/record.json"
            ).read_text()
        ),
        asdict(s.profile),
    )
    spec = PlateSpec(
        finished_od=5,
        finished_bore_diameter=r.finished_bore,
        handle_width=2,
        centerline_to_handle_end=10.5,
        material=r.material,
        thickness=r.thickness,
        bore_tolerance=r.bore_tolerance,
        chamfer=False,
        part_identifier=r.part_id,
    )
    pid = repo.create_plate(
        order_id=job,
        line_id="line-1",
        configuration_id=job,
        customer_id="final4-synthetic",
        actor="final4-staging-acceptance",
    )
    rev = repo.create_revision(
        pid,
        spec,
        expected_current=None,
        reason="synthetic PostgreSQL acceptance",
        actor="final4-staging-acceptance",
        source_snapshot={"synthetic": True},
    )
    parent = dict(
        order_id=job,
        line_id="line-1",
        plate_id=pid,
        revision_id=rev["id"],
        spec_sha256=rev["spec_sha256"],
        source_sha256=rev["source_sha256"],
    )
    rejected(
        "unapproved_parent_rejected",
        lambda: s.create("PACKAGING", parent, actor="synthetic"),
    )
    repo.approve(repo.create_delivery(rev["id"])["token"], "final4-synthetic")
    record = asdict(
        replace(r, job_id=job, source_sha256=rev["spec_sha256"], top_chamfer_width=0)
    )
    bundles = [
        s.create(
            f,
            parent,
            actor="synthetic",
            reviewed_record=record if f == "HAAS" else None,
        )
        for f in ("HAAS", "PACKAGING")
    ]
    count = 0
    for b in bundles:
        check(
            b["family"] + "_parent", all(b["parent"][k] == v for k, v in parent.items())
        )
        check(
            b["family"] + "_no_release",
            b["statuses"]["release_eligible"] is False
            and b["statuses"]["manufacturing_release_approved"] is False,
        )
        for f in b["files"]:
            filename, digest, raw = s.download(b["id"], f["name"])
            check(
                "verified_" + b["family"] + "_" + f["name"],
                filename == f["filename"]
                and len(raw) == f["size"]
                and sha256(raw).hexdigest() == digest == f["sha256"],
            )
            count += 1
    # Concurrent generation uses the accepted PG advisory lock and append-only inserts.
    with ThreadPoolExecutor(max_workers=2) as pool:
        concurrent = list(
            pool.map(
                lambda _: s.create("PACKAGING", parent, actor="synthetic-concurrency"),
                range(2),
            )
        )
    check("concurrent_distinct_bundles", len({b["id"] for b in concurrent}) == 2)
    check("all_bundles_persisted", len(s.list(parent)) == 4)
    bad = dict(parent, spec_sha256="0" * 64)
    rejected(
        "wrong_parent_rejected", lambda: s.create("PACKAGING", bad, actor="synthetic")
    )
    # Real restricted role cannot mutate/delete. All probes roll back.
    import psycopg2

    for table in (
        "manufacturing_bundles",
        "manufacturing_bundle_files",
        "manufacturing_evidence",
    ):
        for operation in ("UPDATE", "DELETE"):
            try:
                with repo.transaction() as db:
                    db.execute(
                        f"{operation} {table} SET id=id"
                        if operation == "UPDATE"
                        and table != "manufacturing_bundle_files"
                        else (
                            f"{operation} {table} SET name=name"
                            if operation == "UPDATE"
                            else f"DELETE FROM {table}"
                        )
                    )
            except psycopg2.errors.InsufficientPrivilege:
                checks.append(table + "_" + operation + "_denied")
            else:
                raise AssertionError("mutation privilege unexpectedly allowed")
    r2 = repo.create_revision(
        pid,
        replace(spec, thickness=0.25),
        expected_current=rev["id"],
        reason="synthetic supersession",
        actor="final4-staging-acceptance",
        source_snapshot={"synthetic": True, "revision": 2},
    )
    rejected(
        "superseded_generation_rejected",
        lambda: s.create("PACKAGING", parent, actor="synthetic"),
    )
    rejected(
        "superseded_evidence_rejected",
        lambda: s.record_evidence(
            bundles[0]["id"],
            gate="ENGINEERING_REVIEW",
            reference="synthetic-review",
            actor="independent",
            manifest_sha256=bundles[0]["manifest_sha256"],
        ),
    )
    check(
        "historical_download",
        bool(s.download(bundles[0]["id"], bundles[0]["files"][0]["name"])[2]),
    )
    check(
        "r2_unapproved",
        repo.plate(pid)["lifecycle"] == "READY_FOR_CUSTOMER_CONFIRMATION",
    )
    with repo.connect() as db:
        for table, rows in original.items():
            now = [dict(r) for r in db.execute("SELECT * FROM " + table)]
            check("original_" + table + "_unchanged", all(row in now for row in rows))
    # HTTP checks against the deployed API: uses runtime admin credential, never prints it.
    import httpx

    headers = {"x-api-key": os.environ["ADMIN_API_KEY"]}
    base = "http://127.0.0.1:" + os.environ.get("PORT", "10000")
    with httpx.Client(base_url=base, timeout=120) as http:
        check(
            "anonymous_rejected",
            http.get("/admin/manufacturing/bundles/" + bundles[0]["id"]).status_code
            == 401,
        )
        check(
            "wrong_credential_rejected",
            http.get(
                "/admin/manufacturing/bundles/" + bundles[0]["id"],
                headers={"x-api-key": "wrong"},
            ).status_code
            == 401,
        )
        c = http.get("/admin/manufacturing/configuration", headers=headers)
        check(
            "http_postgresql_configuration",
            c.status_code == 200 and c.json()["adapter"] == "postgresql",
        )
        check(
            "http_query",
            http.post(
                "/admin/manufacturing/bundles/query", json=parent, headers=headers
            ).status_code
            == 200,
        )
        f = bundles[0]["files"][0]
        response = http.get(
            "/admin/manufacturing/bundles/" + bundles[0]["id"] + "/files/" + f["name"],
            headers=headers,
        )
        check(
            "http_verified_download",
            response.status_code == 200
            and sha256(response.content).hexdigest() == f["sha256"]
            and len(response.content) == f["size"],
        )
        check(
            "oversized_rejected",
            http.post(
                "/admin/manufacturing/bundles", content=b"x" * 65537, headers=headers
            ).status_code
            == 413,
        )
        check(
            "release_route_absent",
            http.post("/admin/manufacturing/release", headers=headers).status_code
            == 404,
        )
    evidence = dict(
        status="PASS",
        adapter="postgresql",
        schema=schema,
        synthetic_order=job,
        plate_id=pid,
        revision_id=rev["id"],
        r2=r2["id"],
        bundles=[b["id"] for b in bundles],
        verified_files=count,
        checks=checks,
    )
    raw = canonical(evidence).encode()
    key = "acceptance/final4/" + job + ".json"
    repo.storage.put(key, raw)
    check("evidence_private_persistence", repo.storage.get(key) == raw)
    print(json.dumps(dict(evidence, checks=checks, evidence_key=key), sort_keys=True))


if __name__ == "__main__":
    main()
