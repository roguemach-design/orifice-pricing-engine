-- UNAPPLIED proposal. Explicit DBA review and separate deployment authorization required.
-- psql -v ON_ERROR_STOP=1 -v final4_schema=frozen_plate_prototype -f this-file.sql
-- No default schema. Never run this through application startup.
BEGIN;
SET LOCAL search_path TO :"final4_schema", pg_catalog;
DO $$
DECLARE target text := current_schema(); service_role text;
BEGIN
 IF target NOT IN ('frozen_plate_prototype','frozen_plate_production') THEN
  RAISE EXCEPTION 'explicit existing Frozen Plate schema required';
 END IF;
 service_role := CASE target WHEN 'frozen_plate_prototype' THEN 'frozen_plate_staging_api'
                 ELSE 'frozen_plate_production_api' END;
 IF NOT EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname=service_role
                AND NOT rolsuper AND NOT rolbypassrls) THEN
  RAISE EXCEPTION 'existing restricted backend role required';
 END IF;
 IF to_regclass(target || '.frozen_plate_revisions') IS NULL THEN
  RAISE EXCEPTION 'accepted Frozen Plate schema must already exist';
 END IF;
END;
$$;

CREATE TABLE manufacturing_bundles (
 id TEXT PRIMARY KEY, revision_id TEXT NOT NULL REFERENCES frozen_plate_revisions(id),
 family TEXT NOT NULL CHECK(family IN ('HAAS','PACKAGING')),
 parent_json TEXT NOT NULL, input_json TEXT NOT NULL, input_sha256 TEXT NOT NULL,
 generator_version TEXT NOT NULL, created_at TEXT NOT NULL, created_by TEXT NOT NULL,
 manifest_json TEXT NOT NULL, manifest_sha256 TEXT NOT NULL
);
CREATE TABLE manufacturing_bundle_files (
 bundle_id TEXT NOT NULL REFERENCES manufacturing_bundles(id), name TEXT NOT NULL,
 filename TEXT NOT NULL, object_key TEXT NOT NULL UNIQUE, size INTEGER NOT NULL CHECK(size>0),
 sha256 TEXT NOT NULL, PRIMARY KEY(bundle_id,name)
);
CREATE TABLE manufacturing_evidence (
 id TEXT PRIMARY KEY, bundle_id TEXT NOT NULL REFERENCES manufacturing_bundles(id),
 gate TEXT NOT NULL CHECK(gate IN ('ENGINEERING_REVIEW','SIMULATION_VERIFIED')),
 bundle_manifest_sha256 TEXT NOT NULL, reference TEXT NOT NULL, actor TEXT NOT NULL,
 created_at TEXT NOT NULL, UNIQUE(bundle_id,gate)
);

CREATE INDEX manufacturing_bundles_revision_created_idx
 ON manufacturing_bundles(revision_id,created_at,id);
-- File/evidence foreign keys are covered by their bundle_id-leading primary/unique indexes.
DO $$
DECLARE target text := current_schema(); service_role text; t text;
BEGIN
 service_role := CASE target WHEN 'frozen_plate_prototype' THEN 'frozen_plate_staging_api'
                 ELSE 'frozen_plate_production_api' END;
 FOREACH t IN ARRAY ARRAY['manufacturing_bundles','manufacturing_bundle_files','manufacturing_evidence'] LOOP
  EXECUTE format('ALTER TABLE %I.%I ENABLE ROW LEVEL SECURITY',target,t);
  EXECUTE format('ALTER TABLE %I.%I FORCE ROW LEVEL SECURITY',target,t);
  EXECUTE format('REVOKE ALL ON TABLE %I.%I FROM PUBLIC',target,t);
  EXECUTE format('GRANT SELECT,INSERT ON TABLE %I.%I TO %I',target,t,service_role);
  EXECUTE format('CREATE POLICY final4_backend_select ON %I.%I FOR SELECT TO %I USING (true)',target,t,service_role);
  EXECUTE format('CREATE POLICY final4_backend_insert ON %I.%I FOR INSERT TO %I WITH CHECK (true)',target,t,service_role);
  EXECUTE format('CREATE TRIGGER final4_immutable BEFORE UPDATE OR DELETE ON %I.%I FOR EACH ROW EXECUTE FUNCTION %I.reject_frozen_mutation()',target,t,target);
 END LOOP;
END;
$$;
COMMIT;
-- No existing frozen row, original artifact, auth user or order is modified.
-- Test role grants/RLS, UPDATE/DELETE rejection, advisory serialization and real
-- private object publication in an isolated PostgreSQL environment before use.
