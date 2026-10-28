"""Explicit additive migration and runtime checks for the accepted PG repository.

No application startup DDL; existing revisions/objects are never rewritten.
"""

from .service import SCHEMA
from frozen_plate.repository import WorkflowError

TARGETS = {
    "frozen_plate_prototype": "frozen_plate_staging_api",
    "frozen_plate_production": "frozen_plate_production_api",
}
TABLES = (
    "manufacturing_bundles",
    "manufacturing_bundle_files",
    "manufacturing_evidence",
)


def migration(schema):
    if schema not in TARGETS:
        raise ValueError("accepted private schema required")
    role = TARGETS[schema]
    # Names come exclusively from the server-owned allowlist above.
    ddl = SCHEMA.replace("IF NOT EXISTS ", "")
    sql = f"""BEGIN;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '30s';
SET LOCAL search_path = {schema}, pg_catalog;
DO $guard$ BEGIN
 IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='{role}' AND NOT rolsuper AND NOT rolbypassrls)
 OR to_regprocedure('{schema}.reject_frozen_mutation()') IS NULL
 OR to_regclass('{schema}.frozen_plate_revisions') IS NULL THEN
 RAISE EXCEPTION 'accepted restricted Frozen Plate architecture required'; END IF;
END $guard$;
{ddl}
CREATE INDEX manufacturing_bundles_revision_created_idx ON manufacturing_bundles(revision_id,created_at,id);
"""
    for table in TABLES:
        sql += f"""
ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;
ALTER TABLE {table} FORCE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE {table} FROM PUBLIC, anon, authenticated;
GRANT SELECT, INSERT ON TABLE {table} TO {role};
CREATE POLICY final4_select ON {table} FOR SELECT TO {role} USING (true);
CREATE POLICY final4_insert ON {table} FOR INSERT TO {role} WITH CHECK (true);
CREATE TRIGGER final4_immutable BEFORE UPDATE OR DELETE ON {table}
 FOR EACH ROW EXECUTE FUNCTION {schema}.reject_frozen_mutation();
"""
    sql += """ALTER TABLE manufacturing_bundles
 ADD CONSTRAINT bundle_input_hash CHECK (input_sha256 ~ '^[0-9a-f]{64}$'),
 ADD CONSTRAINT bundle_manifest_hash CHECK (manifest_sha256 ~ '^[0-9a-f]{64}$');
ALTER TABLE manufacturing_bundle_files
 ADD CONSTRAINT bundle_file_hash CHECK (sha256 ~ '^[0-9a-f]{64}$');
ALTER TABLE manufacturing_evidence
 ADD CONSTRAINT evidence_manifest_hash CHECK (bundle_manifest_sha256 ~ '^[0-9a-f]{64}$');
COMMIT;
"""
    return sql


def verify_repository(repo):
    from frozen_plate.staging import StagingRepository
    from frozen_plate.production import ProductionRepository

    if not isinstance(repo, (StagingRepository, ProductionRepository)):
        raise WorkflowError(
            "PostgreSQL Frozen Plate repository required; no SQLite fallback"
        )
    with repo.connect() as db:
        row = db.execute(
            "SELECT current_schema() AS schema, current_user AS role"
        ).fetchone()
        schema = row["schema"]
        if schema not in TARGETS or row["role"] != TARGETS[schema]:
            raise WorkflowError("restricted PostgreSQL binding mismatch")
        count = db.execute(
            "SELECT count(*) AS n FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname=? AND c.relname IN ('manufacturing_bundles','manufacturing_bundle_files','manufacturing_evidence') AND c.relrowsecurity AND c.relforcerowsecurity",
            (schema,),
        ).fetchone()["n"]
        if count != 3:
            raise WorkflowError("reviewed additive PostgreSQL migration required")
    return schema


def retry_migration(schema):
    """Review/apply separately; never install control state on application startup."""
    if schema not in TARGETS:
        raise ValueError("accepted private schema required")
    from .retry import SCHEMA as RETRY_SCHEMA

    role = TARGETS[schema]
    return f"""BEGIN;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '30s';
SET LOCAL search_path = {schema}, pg_catalog;
DO $guard$ BEGIN
 IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='{role}' AND NOT rolsuper AND NOT rolbypassrls)
 OR to_regclass('{schema}.frozen_plate_revisions') IS NULL THEN
 RAISE EXCEPTION 'accepted restricted Frozen Plate architecture required'; END IF;
END $guard$;
{RETRY_SCHEMA.replace('IF NOT EXISTS ', '')}
ALTER TABLE manufacturing_retry_control ENABLE ROW LEVEL SECURITY;
ALTER TABLE manufacturing_retry_control FORCE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE manufacturing_retry_control FROM PUBLIC, anon, authenticated;
GRANT SELECT, INSERT, UPDATE ON TABLE manufacturing_retry_control TO {role};
CREATE POLICY retry_select ON manufacturing_retry_control FOR SELECT TO {role} USING (true);
CREATE POLICY retry_insert ON manufacturing_retry_control FOR INSERT TO {role} WITH CHECK (true);
CREATE POLICY retry_update ON manufacturing_retry_control FOR UPDATE TO {role} USING (true) WITH CHECK (true);
COMMIT;
"""
