BEGIN;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '30s';
SET LOCAL search_path = frozen_plate_prototype, pg_catalog;
DO $guard$ BEGIN
 IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='frozen_plate_staging_api' AND NOT rolsuper AND NOT rolbypassrls)
 OR to_regprocedure('frozen_plate_prototype.reject_frozen_mutation()') IS NULL
 OR to_regclass('frozen_plate_prototype.frozen_plate_revisions') IS NULL THEN
 RAISE EXCEPTION 'accepted restricted Frozen Plate architecture required'; END IF;
END $guard$;

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

CREATE INDEX manufacturing_bundles_revision_created_idx ON manufacturing_bundles(revision_id,created_at,id);

ALTER TABLE manufacturing_bundles ENABLE ROW LEVEL SECURITY;
ALTER TABLE manufacturing_bundles FORCE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE manufacturing_bundles FROM PUBLIC, anon, authenticated;
GRANT SELECT, INSERT ON TABLE manufacturing_bundles TO frozen_plate_staging_api;
CREATE POLICY final4_select ON manufacturing_bundles FOR SELECT TO frozen_plate_staging_api USING (true);
CREATE POLICY final4_insert ON manufacturing_bundles FOR INSERT TO frozen_plate_staging_api WITH CHECK (true);
CREATE TRIGGER final4_immutable BEFORE UPDATE OR DELETE ON manufacturing_bundles
 FOR EACH ROW EXECUTE FUNCTION frozen_plate_prototype.reject_frozen_mutation();

ALTER TABLE manufacturing_bundle_files ENABLE ROW LEVEL SECURITY;
ALTER TABLE manufacturing_bundle_files FORCE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE manufacturing_bundle_files FROM PUBLIC, anon, authenticated;
GRANT SELECT, INSERT ON TABLE manufacturing_bundle_files TO frozen_plate_staging_api;
CREATE POLICY final4_select ON manufacturing_bundle_files FOR SELECT TO frozen_plate_staging_api USING (true);
CREATE POLICY final4_insert ON manufacturing_bundle_files FOR INSERT TO frozen_plate_staging_api WITH CHECK (true);
CREATE TRIGGER final4_immutable BEFORE UPDATE OR DELETE ON manufacturing_bundle_files
 FOR EACH ROW EXECUTE FUNCTION frozen_plate_prototype.reject_frozen_mutation();

ALTER TABLE manufacturing_evidence ENABLE ROW LEVEL SECURITY;
ALTER TABLE manufacturing_evidence FORCE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE manufacturing_evidence FROM PUBLIC, anon, authenticated;
GRANT SELECT, INSERT ON TABLE manufacturing_evidence TO frozen_plate_staging_api;
CREATE POLICY final4_select ON manufacturing_evidence FOR SELECT TO frozen_plate_staging_api USING (true);
CREATE POLICY final4_insert ON manufacturing_evidence FOR INSERT TO frozen_plate_staging_api WITH CHECK (true);
CREATE TRIGGER final4_immutable BEFORE UPDATE OR DELETE ON manufacturing_evidence
 FOR EACH ROW EXECUTE FUNCTION frozen_plate_prototype.reject_frozen_mutation();
ALTER TABLE manufacturing_bundles
 ADD CONSTRAINT bundle_input_hash CHECK (input_sha256 ~ '^[0-9a-f]{64}$'),
 ADD CONSTRAINT bundle_manifest_hash CHECK (manifest_sha256 ~ '^[0-9a-f]{64}$');
ALTER TABLE manufacturing_bundle_files
 ADD CONSTRAINT bundle_file_hash CHECK (sha256 ~ '^[0-9a-f]{64}$');
ALTER TABLE manufacturing_evidence
 ADD CONSTRAINT evidence_manifest_hash CHECK (bundle_manifest_sha256 ~ '^[0-9a-f]{64}$');
COMMIT;
