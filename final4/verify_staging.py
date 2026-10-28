"""Explicit synthetic-only HTTP acceptance. Credential in env, never logged.

Run with FINAL4_STAGING_URL and FINAL4_STAGING_ADMIN_KEY; creates only derived
bundles for the harness's own synthetic fixture. No production routes imported.
"""

import hashlib
import json
import os
from pathlib import Path
import httpx


def main():
    base = os.environ["FINAL4_STAGING_URL"]
    if base != "https://oplates-final4-engineering-staging.onrender.com":
        raise ValueError("only isolated Final 4 staging origin accepted")
    c = httpx.Client(base_url=base, timeout=45)
    h = {"x-api-key": os.environ["FINAL4_STAGING_ADMIN_KEY"]}
    checks = {}
    health = c.get("/health")
    health.raise_for_status()
    checks["health"] = (
        health.json()["scope"] == "isolated-synthetic-staging"
        and health.json()["manufacturing_release_enabled"] is False
    )
    assert checks["health"]
    checks["anonymous_blocked"] = (
        c.get("/admin/manufacturing/synthetic-fixture").status_code == 401
    )
    checks["wrong_key_blocked"] = (
        c.get(
            "/admin/manufacturing/synthetic-fixture", headers={"x-api-key": "wrong"}
        ).status_code
        == 401
    )
    fixture = c.get("/admin/manufacturing/synthetic-fixture", headers=h)
    fixture.raise_for_status()
    f = fixture.json()
    assert f["parent"]["order_id"] == "SYNTHETIC-001"
    files = []
    for family in ("HAAS", "PACKAGING"):
        payload = {"family": family, "parent": f["parent"]}
        if family == "HAAS":
            payload["reviewed_record"] = f["reviewed_record"]
        result = c.post("/admin/manufacturing/bundles", headers=h, json=payload)
        result.raise_for_status()
        b = result.json()
        checks[family + "_generation"] = (
            b["family"] == family and not b["statuses"]["release_eligible"]
        )
        for a in b["files"]:
            path = "/admin/manufacturing/bundles/" + b["id"] + "/files/" + a["name"]
            response = c.get(path, headers=h)
            response.raise_for_status()
            assert (
                len(response.content) == a["size"]
                and hashlib.sha256(response.content).hexdigest() == a["sha256"]
            )
            assert (
                response.headers["x-artifact-sha256"] == a["sha256"]
                and response.headers["x-artifact-verified"] == "true"
            )
            assert response.headers["cache-control"] == "no-store"
            files.append(
                {
                    "family": family,
                    "name": a["name"],
                    "size": a["size"],
                    "sha256": a["sha256"],
                }
            )
            if a["name"] == "program.NC":
                assert b"#3000=1" in response.content
        checks[family + "_all_files_verified"] = True
    checks["wrong_parent_rejected"] = (
        c.post(
            "/admin/manufacturing/bundles",
            headers=h,
            json={"family": "PACKAGING", "parent": {**f["parent"], "line_id": "WRONG"}},
        ).status_code
        == 409
    )
    checks["profile_override_rejected"] = (
        c.post(
            "/admin/manufacturing/bundles",
            headers=h,
            json={"family": "PACKAGING", "parent": f["parent"], "profile": {}},
        ).status_code
        == 422
    )
    checks["request_bound"] = (
        c.post(
            "/admin/manufacturing/bundles", headers=h, content=b"x" * 65537
        ).status_code
        == 413
    )
    checks["no_release_route"] = (
        c.post("/admin/manufacturing/release", headers=h).status_code == 404
    )
    query = c.post("/admin/manufacturing/bundles/query", headers=h, json=f["parent"])
    query.raise_for_status()
    checks["query"] = len(query.json()) >= 4
    assert all(checks.values()), checks
    report = {
        "scope": "isolated-synthetic-staging",
        "deploy_sha": os.environ["FINAL4_VERIFIED_DEPLOY_SHA"],
        "checks": checks,
        "verified_file_count": len(files),
        "files": files,
        "physical_validation_completed": False,
        "manufacturing_release_approved": False,
    }
    Path(os.environ["FINAL4_EVIDENCE_OUTPUT"]).write_text(
        json.dumps(report, sort_keys=True, indent=2) + "\n"
    )
    print(json.dumps({"checks": checks, "verified_file_count": len(files)}))


if __name__ == "__main__":
    main()
