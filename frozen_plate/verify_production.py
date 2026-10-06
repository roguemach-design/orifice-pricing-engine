"""Production preflight: no payment, customer email, approval or vendor action.

DB write proof is rolled back; one marked storage probe is deleted afterward.
Only boolean check results are printed, never secrets or exception details.
"""

import json
import os
import shutil
from urllib.parse import urlsplit
from uuid import uuid4

from .production import ProductionRepository, ROLE, SCHEMA
from .repository import WorkflowError


def run(environ=None):
    env = os.environ if environ is None else environ
    checks = {}
    repo = ProductionRepository(env)
    db_url = urlsplit(env.get("DATABASE_URL", ""))
    checks["production_order_database"] = (
        bool(
            db_url.hostname and db_url.hostname.startswith("dpg-d56smommcj7s7383tv50-a")
        )
        and db_url.path == "/orifice_pricing_db"
    )
    checks["production_auth_project"] = all(
        "kboaovlhilonlymcuqcr" in env.get(k, "")
        for k in ("SUPABASE_JWT_ISSUER", "SUPABASE_JWKS_URL")
    )
    checks["live_stripe_key"] = env.get("STRIPE_SECRET_KEY", "").startswith(
        ("sk_live_", "rk_live_")
    )
    checks["live_webhook_binding_present"] = bool(env.get("STRIPE_WEBHOOK_SECRET"))
    checks["email_provider_binding"] = (
        bool(env.get("SENDGRID_API_KEY"))
        and env.get("FROZEN_PLATE_EMAIL_MODE") == "send"
        and env.get("FROM_EMAIL", "orders@o-plates.com")
        in {"orders@o-plates.com", "no-reply@o-plates.com"}
    )
    checks["separate_admin_binding"] = bool(env.get("ADMIN_API_KEY")) and env.get(
        "ADMIN_API_KEY"
    ) != env.get("API_KEY")
    # Native OCR is required only when the existing internal intake is enabled.
    checks["ocr_runtime"] = env.get(
        "OPLATES_DRAWING_ASSISTED_ENABLED", ""
    ).lower() not in {"1", "true", "yes", "on"} or bool(shutil.which("tesseract"))
    with repo.connect() as db:
        identity = db.execute(
            "SELECT current_user AS role,rolsuper,rolbypassrls,rolcreatedb,rolcreaterole,rolreplication FROM pg_roles WHERE rolname=current_user"
        ).fetchone()
        checks["restricted_database_identity"] = identity["role"] == ROLE and not any(
            identity[k]
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
                "SELECT tablename,rowsecurity,has_table_privilege(current_user,quote_ident(schemaname)||'.'||quote_ident(tablename),'SELECT,INSERT') AS backend,has_table_privilege('anon',quote_ident(schemaname)||'.'||quote_ident(tablename),'SELECT') AS anon_read,has_table_privilege('authenticated',quote_ident(schemaname)||'.'||quote_ident(tablename),'SELECT') AS customer_read,has_table_privilege(current_user,quote_ident(schemaname)||'.'||quote_ident(tablename),'DELETE') AS backend_delete FROM pg_tables WHERE schemaname=?",
                (SCHEMA,),
            )
        )
        checks["schema_permissions_rls"] = len(tables) == 8 and all(
            t["rowsecurity"]
            and t["backend"]
            and not t["anon_read"]
            and not t["customer_read"]
            and not t["backend_delete"]
            for t in tables
        )
        policies = list(
            db.execute("SELECT roles FROM pg_policies WHERE schemaname=?", (SCHEMA,))
        )
        checks["role_scoped_policies"] = len(policies) == 17 and all(
            p["roles"] == [ROLE] for p in policies
        )
        marker = "production-preflight-" + uuid4().hex
        db.execute("BEGIN")
        try:
            db.execute(
                "INSERT INTO frozen_plates(id,order_id,line_id,configuration_id,customer_id,created_at,created_by) VALUES (?,?,?,?,?,?,?)",
                (
                    marker,
                    marker,
                    "probe",
                    marker,
                    marker,
                    repo.now(),
                    "rolled-back-preflight",
                ),
            )
            checks["database_write_read_rollback"] = (
                db.execute(
                    "SELECT id FROM frozen_plates WHERE id=?", (marker,)
                ).fetchone()["id"]
                == marker
            )
        finally:
            db.execute("ROLLBACK")
        checks["database_probe_absent"] = (
            db.execute("SELECT id FROM frozen_plates WHERE id=?", (marker,)).fetchone()
            is None
        )
    bucket = repo.storage.request("GET", "/bucket/" + repo.storage.bucket).json()
    checks["bucket_private"] = bucket.get("public") is False
    object_key = "verification/production-preflight-" + uuid4().hex + ".txt"
    data = b"O-Plates production storage preflight; no customer action."
    try:
        repo.storage.put(object_key, data)
        checks["storage_exact_write_read"] = repo.storage.get(object_key) == data
    finally:
        repo.storage.remove([object_key])
    checks["storage_probe_deleted"] = repo.storage.get_optional(object_key) is None
    token = repo.signer.dumps({"nonce": "synthetic-preflight"})
    checks["signing_validation"] = repo.signer.loads(token) == {
        "nonce": "synthetic-preflight"
    }
    return checks


def main():
    try:
        checks = run()
        passed = bool(checks) and all(value is True for value in checks.values())
        print(json.dumps({"checks": checks, "all_passed": passed}, sort_keys=True))
    except Exception:
        print(
            json.dumps({"all_passed": False, "production_preflight_unavailable": True})
        )
        raise SystemExit(1) from None
    if not passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
