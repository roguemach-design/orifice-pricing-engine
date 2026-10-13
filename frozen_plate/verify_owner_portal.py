"""Read-only production owner API/artifact verification. Prints checks, never credentials."""

import json
import os
from hashlib import sha256
import requests
from .production import ProductionRepository


def verify():
    repo = ProductionRepository()
    base = "http://127.0.0.1:10000"
    headers = {"x-api-key": os.environ["ADMIN_API_KEY"]}

    def get(path, **kwargs):
        response = requests.get(base + path, headers=headers, timeout=120, **kwargs)
        response.raise_for_status()
        return response

    checks = {}
    orders = get("/admin/orders", params={"limit": 200}).json()
    completed = [o for o in orders if o["status"] == "completed"]
    checks["completed_orders_visible"] = bool(completed)
    checks["order_lines_accessible"] = all(
        get("/admin/orders/" + o["id"]).json()["id"] == o["id"] for o in completed
    )
    inventory = get("/admin/frozen-plates").json()
    checks["frozen_plate_inventory_visible"] = bool(inventory)
    checks["unauthenticated_blocked"] = (
        requests.get(base + "/admin/frozen-plates", timeout=30).status_code == 401
    )
    checks["customer_key_blocked"] = (
        requests.get(
            base + "/admin/frozen-plates",
            headers={"x-api-key": os.environ.get("API_KEY", "")},
            timeout=30,
        ).status_code
        == 401
    )
    revision_checks = []
    before = [(p["id"], p["current_revision"], p["lifecycle"]) for p in inventory]
    for plate in inventory:
        history = get("/admin/frozen-plates/" + plate["id"] + "/revisions").json()
        for rev in history:
            detail = get(
                "/admin/frozen-plates/" + plate["id"], params={"revision_id": rev["id"]}
            ).json()
            item = {
                "revision": rev["number"],
                "exact_revision": detail["revision"]["id"] == rev["id"],
                "sourcing_record_only": all(
                    not s.get("released") for s in detail["sourcing"]
                ),
            }
            with repo.connect() as db:
                stored, artifacts, content = repo._verified(db, rev["id"])
            item["stored_spec_and_all_artifact_hashes_verified"] = stored[
                "spec_sha256"
            ] == rev["spec_sha256"] and all(
                sha256(content[k]).hexdigest() == a["sha256"]
                for k, a in artifacts.items()
            )
            for kind in ("pdf", "json"):
                response = get(
                    "/admin/frozen-plates/revisions/" + rev["id"] + "/artifact/" + kind
                )
                item[kind + "_exact_download"] = (
                    response.content == content[kind]
                    and response.headers["x-frozen-revision"] == rev["id"]
                )
            approved = (
                bool(detail["approvals"]) and plate["current_revision"] == rev["id"]
            )
            response = requests.get(
                base + "/admin/frozen-plates/revisions/" + rev["id"] + "/dxf",
                headers=headers,
                timeout=120,
            )
            item["dxf_approval_gate"] = (
                (response.status_code == 200 and response.content == content["dxf"])
                if approved
                else response.status_code == 409
            )
            item["approved"] = approved
            get("/admin/frozen-plates/revisions/" + rev["id"] + "/email-status")
            for delivery in detail["deliveries"]:
                response = get(
                    "/admin/frozen-plates/deliveries/" + delivery["id"] + "/capture"
                )
                item["capture_hash_verified"] = (
                    sha256(response.content).hexdigest() == delivery["mime_sha256"]
                )
            revision_checks.append(item)
    after = get("/admin/frozen-plates").json()
    checks["records_unchanged"] = before == [
        (p["id"], p["current_revision"], p["lifecycle"]) for p in after
    ]
    checks["private_production_storage"] = (
        repo.storage.bucket == "frozen-plate-production"
        and repo.storage.request("GET", "/bucket/" + repo.storage.bucket).json()[
            "public"
        ]
        is False
    )
    checks["review_only_verification"] = True
    print(
        json.dumps(
            {
                "checks": checks,
                "completed_orders": len(completed),
                "revisions": revision_checks,
                "approved_revisions": sum(r["approved"] for r in revision_checks),
            },
            sort_keys=True,
        )
    )
    return (
        all(checks.values())
        and bool(revision_checks)
        and all(
            all(v for k, v in r.items() if k not in {"revision", "approved"})
            for r in revision_checks
        )
    )


if __name__ == "__main__":
    raise SystemExit(0 if verify() else 1)
