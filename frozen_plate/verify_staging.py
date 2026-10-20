"""Run on the staging backend: python -m frozen_plate.verify_staging.

Prints only check names/booleans. Creates clearly marked staging workflow records.
Never prints credentials, tokens, MIME, artifacts, or exception bodies.
"""

from dataclasses import replace
from uuid import uuid4
import json
from email.parser import BytesParser
from email import policy

from .staging import StagingRepository
from .repository import WorkflowError, digest
from prototype_manufacturing import sample_spec


def main():
    checks = {}
    try:
        repo = StagingRepository()
        with repo.connect() as db:
            row = db.execute(
                "SELECT current_user AS role, rolsuper,rolbypassrls,rolcreatedb,rolcreaterole,rolreplication FROM pg_roles WHERE rolname=current_user"
            ).fetchone()
            checks["restricted_database_login"] = row[
                "role"
            ] == "frozen_plate_staging_api" and not any(
                row[k]
                for k in (
                    "rolsuper",
                    "rolbypassrls",
                    "rolcreatedb",
                    "rolcreaterole",
                    "rolreplication",
                )
            )
            tables = list(
                db.execute(
                    "SELECT tablename,rowsecurity,has_table_privilege(current_user,quote_ident(schemaname)||'.'||quote_ident(tablename),'SELECT,INSERT') AS backend,has_table_privilege('anon',quote_ident(schemaname)||'.'||quote_ident(tablename),'SELECT') AS anon_read,has_table_privilege('authenticated',quote_ident(schemaname)||'.'||quote_ident(tablename),'SELECT') AS customer_read,has_table_privilege(current_user,quote_ident(schemaname)||'.'||quote_ident(tablename),'DELETE') AS backend_delete FROM pg_tables WHERE schemaname='frozen_plate_prototype'"
                )
            )
            checks["schema_rls_permissions"] = len(tables) == 8 and all(
                t["rowsecurity"]
                and t["backend"]
                and not t["anon_read"]
                and not t["customer_read"]
                and not t["backend_delete"]
                for t in tables
            )
            policies = list(
                db.execute(
                    "SELECT roles FROM pg_policies WHERE schemaname='frozen_plate_prototype'"
                )
            )
            checks["role_scoped_rls"] = len(policies) == 17 and all(
                p["roles"] == ["frozen_plate_staging_api"] for p in policies
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
        checks["artifact_hashes_sizes"] = all(
            digest(repo.storage.get(a["object_key"])) == a["sha256"]
            and len(repo.storage.get(a["object_key"])) == a["size"]
            for a in revision["artifacts"].values()
        )
        captured = repo.storage.get("confirmation/" + delivery["id"] + ".eml")
        message = BytesParser(policy=policy.default).parsebytes(captured)
        attachments = list(message.iter_attachments())
        checks["captured_exact_pdf"] = (
            captured == delivery["mime"]
            and len(attachments) == 1
            and attachments[0].get_payload(decode=True) == pdf
        )

        def rejects(action):
            try:
                action()
            except WorkflowError:
                return True
            return False

        checks["tamper_rejected"] = rejects(lambda: repo.approve(token + "x", customer))
        checks["wrong_owner_rejected"] = rejects(
            lambda: repo.approve(token, customer + "other")
        )
        checks["approval"] = repo.approve(token, customer)["state"] == "approved"
        checks["approval_idempotent"] = (
            repo.approve(token, customer)["state"] == "approved"
        )
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
        checks["r2_not_approved_by_r1"] = (
            repo.plate(plate)["lifecycle"] == "READY_FOR_CUSTOMER_CONFIRMATION"
            and repo.approve(token, customer)["historical"]
        )
        r2_delivery = repo.create_delivery(r2["id"])
        checks["r2_approval"] = (
            repo.approve(r2_delivery["token"], customer)["context"]["revision"] == "R2"
        )
        checks["emails_sent"] = False
        checks["vendor_files_submitted"] = False
        passed = all(
            value
            is (False if name in ("emails_sent", "vendor_files_submitted") else True)
            for name, value in checks.items()
        )
        print(
            json.dumps(
                {"verification_completed": passed, "checks": checks}, sort_keys=True
            )
        )
        if not passed:
            raise SystemExit(1)
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
