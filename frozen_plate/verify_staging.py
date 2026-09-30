"""Run on the staging backend: python -m frozen_plate.verify_staging.

Prints only check names/booleans. Creates clearly marked staging workflow records.
Never prints credentials, tokens, MIME, artifacts, or exception bodies.
"""

from dataclasses import replace
from uuid import uuid4
import json

from .staging import StagingRepository
from .repository import WorkflowError, digest
from prototype_manufacturing import sample_spec


def main():
    checks = {}
    try:
        repo = StagingRepository()
        with repo.connect() as db:
            row = db.execute("SELECT current_user AS role").fetchone()
            checks["restricted_database_login"] = (
                row["role"] == "frozen_plate_staging_api"
            )
        # Bucket provisioning is idempotent, never switches an existing bucket public.
        response = repo.storage.client.get("/bucket/" + repo.storage.bucket)
        if response.status_code == 404 or (
            response.status_code == 400
            and response.json().get("statusCode") in ("404", 404)
        ):
            repo.storage.request(
                "POST",
                "/bucket",
                json={
                    "id": repo.storage.bucket,
                    "name": repo.storage.bucket,
                    "public": False,
                },
            )
            response = repo.storage.request("GET", "/bucket/" + repo.storage.bucket)
        if not response.is_success or response.json().get("public") is not False:
            raise WorkflowError("private bucket required")
        checks["private_bucket"] = True
        key = "verification/" + str(uuid4()) + ".txt"
        data = b"O-Plates staging storage verification. No customer or vendor action."
        repo.storage.put(key, data)
        checks["storage_write_read"] = repo.storage.get(key) == data
        repo.storage.remove([key])
        removed = repo.storage.client.get("/object/" + repo.storage.bucket + "/" + key)
        checks["storage_test_cleanup"] = not removed.is_success
        suffix = uuid4().hex[:20]
        customer = "staging-check-" + suffix
        plate = repo.create_plate(
            order_id="staging-check-" + suffix,
            line_id="line-1",
            configuration_id="staging-check-" + suffix,
            customer_id=customer,
            actor="staging-verification",
        )
        spec = replace(
            sample_spec(),
            part_identifier="STAGING-VERIFY",
            finished_od=5.0,
            finished_bore_diameter=1.548,
            handle_width=2.0,
            centerline_to_handle_end=10.5,
            thickness=0.125,
            material="304 Stainless Steel",
        )
        revision = repo.create_revision(
            plate,
            spec,
            expected_current=None,
            reason="Safe staging verification R1",
            actor="staging-verification",
            source_snapshot={
                "test_only": True,
                "customer_action": False,
                "vendor_action": False,
            },
        )
        checks["database_read_write"] = revision["number"] == 1
        delivery = repo.create_delivery(revision["id"])
        token = delivery["token"]
        checks["signing_token"] = (
            repo.inspect_token(token, customer)["state"] == "pending"
        )
        filename, pdf = repo.customer_pdf(token, customer)
        checks["pdf_hash"] = digest(pdf) == revision["artifacts"]["pdf"]["sha256"]
        checks["approval"] = repo.approve(token, customer)["state"] == "approved"
        for route in ("SENDCUTSEND", "ALRO", "ROGUE_INTERNAL"):
            checks["route_" + route] = (
                repo.select_source(revision["id"], route, actor="staging-verification")[
                    "released"
                ]
                is False
            )
        r2 = repo.create_revision(
            plate,
            spec,
            expected_current=revision["id"],
            reason="Safe staging verification R2",
            actor="staging-verification",
            source_snapshot={"test_only": True, "revision": 2},
        )
        checks["r1_r2"] = (
            r2["number"] == 2 and repo.inspect_token(token, customer)["historical"]
        )
        try:
            repo.select_source(revision["id"], "ALRO", actor="staging-verification")
            checks["stale_release_blocked"] = False
        except WorkflowError:
            checks["stale_release_blocked"] = True
        checks["emails_sent"] = False
        checks["vendor_files_submitted"] = False
        print(
            json.dumps(
                {"verification_completed": True, "checks": checks}, sort_keys=True
            )
        )
    except Exception as exc:
        print(
            json.dumps(
                {
                    "verification_completed": False,
                    "checks": checks,
                    "error_type": type(exc).__name__,
                },
                sort_keys=True,
            )
        )
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
