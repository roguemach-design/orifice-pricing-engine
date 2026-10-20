-- Production-only additive schema proposal; never run against staging.
-- Existing production auth users and order DB are outside this schema.
-- Role remains NOLOGIN until owner securely supplies its dedicated password.




BEGIN;
CREATE SCHEMA frozen_plate_production;
SET LOCAL search_path = frozen_plate_production, pg_catalog;
CREATE TABLE frozen_plates (
 id TEXT PRIMARY KEY, order_id TEXT NOT NULL, line_id TEXT NOT NULL,
 configuration_id TEXT NOT NULL, customer_id TEXT NOT NULL,
 current_revision TEXT, lifecycle TEXT NOT NULL DEFAULT 'EMPTY'
 CHECK(lifecycle IN ('EMPTY','READY_FOR_CUSTOMER_CONFIRMATION','CUSTOMER_APPROVED','READY_FOR_RELEASE')),
 created_at TEXT NOT NULL, created_by TEXT NOT NULL,
 UNIQUE(order_id,line_id),
 CHECK((current_revision IS NULL AND lifecycle='EMPTY') OR (current_revision IS NOT NULL AND lifecycle<>'EMPTY'))
);
CREATE TABLE frozen_plate_revisions (
 id TEXT PRIMARY KEY, plate_id TEXT NOT NULL REFERENCES frozen_plates(id),
 number INTEGER NOT NULL CHECK(number>0), spec_json TEXT NOT NULL,
 spec_sha256 TEXT NOT NULL CHECK(length(spec_sha256)=64),
 source_json TEXT NOT NULL, source_sha256 TEXT NOT NULL CHECK(length(source_sha256)=64),
 spec_schema INTEGER NOT NULL, generator_version TEXT NOT NULL, geometry_version TEXT NOT NULL,
 drawing_metadata_json TEXT NOT NULL, reason TEXT NOT NULL,
 created_at TEXT NOT NULL, created_by TEXT NOT NULL,
 UNIQUE(plate_id,number), UNIQUE(id,plate_id)
);
CREATE TABLE frozen_plate_artifacts (
 id TEXT PRIMARY KEY, revision_id TEXT NOT NULL REFERENCES frozen_plate_revisions(id),
 kind TEXT NOT NULL CHECK(kind IN ('pdf','dxf','json')),
 object_key TEXT NOT NULL UNIQUE, filename TEXT NOT NULL,
 sha256 TEXT NOT NULL CHECK(length(sha256)=64), size INTEGER NOT NULL CHECK(size>0),
 generator_version TEXT NOT NULL, generated_at TEXT NOT NULL,
 UNIQUE(revision_id,kind), UNIQUE(id,revision_id,kind)
);
CREATE TABLE frozen_plate_tokens (
 fingerprint TEXT PRIMARY KEY, revision_id TEXT NOT NULL REFERENCES frozen_plate_revisions(id),
 pdf_id TEXT NOT NULL, pdf_kind TEXT NOT NULL DEFAULT 'pdf' CHECK(pdf_kind='pdf'),
 pdf_sha256 TEXT NOT NULL, spec_sha256 TEXT NOT NULL,
 customer_id TEXT NOT NULL, order_id TEXT NOT NULL,
 created_at TEXT NOT NULL, expires_at DOUBLE PRECISION NOT NULL,
 UNIQUE(fingerprint,revision_id,pdf_id),
 FOREIGN KEY(pdf_id,revision_id,pdf_kind) REFERENCES frozen_plate_artifacts(id,revision_id,kind)
);
CREATE TABLE frozen_plate_revocations (
 fingerprint TEXT PRIMARY KEY REFERENCES frozen_plate_tokens(fingerprint),
 revoked_at TEXT NOT NULL, reason TEXT NOT NULL, actor TEXT NOT NULL
);
CREATE TABLE frozen_plate_deliveries (
 id TEXT PRIMARY KEY, revision_id TEXT NOT NULL, pdf_id TEXT NOT NULL,
 token_fingerprint TEXT NOT NULL, recipient_id TEXT NOT NULL,
 generated_at TEXT NOT NULL, sent_at TEXT CHECK(sent_at IS NULL),
 template_version TEXT NOT NULL, state TEXT NOT NULL CHECK(state='LOCAL_RENDERED'),
 mime_sha256 TEXT NOT NULL,
 FOREIGN KEY(token_fingerprint,revision_id,pdf_id) REFERENCES frozen_plate_tokens(fingerprint,revision_id,pdf_id)
);
CREATE TABLE frozen_plate_approvals (
 revision_id TEXT PRIMARY KEY REFERENCES frozen_plate_revisions(id),
 pdf_id TEXT NOT NULL, token_fingerprint TEXT NOT NULL,
 pdf_sha256 TEXT NOT NULL, spec_sha256 TEXT NOT NULL,
 customer_id TEXT NOT NULL, order_id TEXT NOT NULL,
 approved_at TEXT NOT NULL, status TEXT NOT NULL CHECK(status='CUSTOMER_APPROVED'),
 audit_json TEXT NOT NULL,
 FOREIGN KEY(token_fingerprint,revision_id,pdf_id) REFERENCES frozen_plate_tokens(fingerprint,revision_id,pdf_id)
);
CREATE TABLE frozen_plate_sourcing (
 id TEXT PRIMARY KEY, revision_id TEXT NOT NULL REFERENCES frozen_plate_approvals(revision_id),
 dxf_id TEXT NOT NULL, dxf_kind TEXT NOT NULL DEFAULT 'dxf' CHECK(dxf_kind='dxf'),
 route TEXT NOT NULL CHECK(route IN ('SENDCUTSEND','ALRO','ROGUE_INTERNAL')),
 state TEXT NOT NULL CHECK(state='LOCAL_SELECTION_ONLY'),
 selection_status TEXT NOT NULL DEFAULT 'SELECTED_FOR_REVIEW' CHECK(selection_status IN ('SELECTED_FOR_REVIEW','REJECTED')),
 internal_manufacturing_state TEXT NOT NULL DEFAULT 'NOT_RELEASED' CHECK(internal_manufacturing_state='NOT_RELEASED'),
 selected_at TEXT NOT NULL, selected_by TEXT NOT NULL,
 vendor_reference TEXT, quote_price_cents INTEGER CHECK(quote_price_cents>=0),
 currency TEXT, lead_time_days INTEGER CHECK(lead_time_days>=0),
 quote_status TEXT NOT NULL DEFAULT 'NOT_REQUESTED' CHECK(quote_status='NOT_REQUESTED'),
 submitted_at TEXT CHECK(submitted_at IS NULL),
 UNIQUE(revision_id,route),
 FOREIGN KEY(dxf_id,revision_id,dxf_kind) REFERENCES frozen_plate_artifacts(id,revision_id,kind)
);

ALTER TABLE frozen_plates ADD CONSTRAINT current_revision_same_plate
 FOREIGN KEY(current_revision,id) REFERENCES frozen_plate_revisions(id,plate_id)
 DEFERRABLE INITIALLY DEFERRED;
CREATE FUNCTION reject_frozen_mutation() RETURNS trigger LANGUAGE plpgsql SET search_path = pg_catalog AS $$
BEGIN RAISE EXCEPTION 'immutable frozen record'; END;
$$;
CREATE FUNCTION protect_plate_identity() RETURNS trigger LANGUAGE plpgsql SET search_path = pg_catalog AS $$
BEGIN
 IF TG_OP = 'DELETE' THEN RAISE EXCEPTION 'immutable plate history'; END IF;
 IF ROW(NEW.id,NEW.order_id,NEW.line_id,NEW.configuration_id,NEW.customer_id,NEW.created_at,NEW.created_by)
 IS DISTINCT FROM ROW(OLD.id,OLD.order_id,OLD.line_id,OLD.configuration_id,OLD.customer_id,OLD.created_at,OLD.created_by)
 THEN RAISE EXCEPTION 'immutable plate identity'; END IF;
 RETURN NEW;
END;
$$;
CREATE TRIGGER plate_identity BEFORE UPDATE OR DELETE ON frozen_plates
 FOR EACH ROW EXECUTE FUNCTION protect_plate_identity();
CREATE TRIGGER immutable_revisions BEFORE UPDATE OR DELETE ON frozen_plate_revisions
 FOR EACH ROW EXECUTE FUNCTION reject_frozen_mutation();
CREATE TRIGGER immutable_artifacts BEFORE UPDATE OR DELETE ON frozen_plate_artifacts
 FOR EACH ROW EXECUTE FUNCTION reject_frozen_mutation();
CREATE TRIGGER immutable_tokens BEFORE UPDATE OR DELETE ON frozen_plate_tokens
 FOR EACH ROW EXECUTE FUNCTION reject_frozen_mutation();
CREATE TRIGGER immutable_revocations BEFORE UPDATE OR DELETE ON frozen_plate_revocations
 FOR EACH ROW EXECUTE FUNCTION reject_frozen_mutation();
CREATE TRIGGER immutable_deliveries BEFORE UPDATE OR DELETE ON frozen_plate_deliveries
 FOR EACH ROW EXECUTE FUNCTION reject_frozen_mutation();
CREATE TRIGGER immutable_approvals BEFORE UPDATE OR DELETE ON frozen_plate_approvals
 FOR EACH ROW EXECUTE FUNCTION reject_frozen_mutation();
CREATE TRIGGER immutable_sourcing BEFORE UPDATE OR DELETE ON frozen_plate_sourcing
 FOR EACH ROW EXECUTE FUNCTION reject_frozen_mutation();
ALTER TABLE frozen_plates ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON frozen_plates FROM PUBLIC, anon, authenticated;
ALTER TABLE frozen_plate_revisions ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON frozen_plate_revisions FROM PUBLIC, anon, authenticated;
ALTER TABLE frozen_plate_artifacts ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON frozen_plate_artifacts FROM PUBLIC, anon, authenticated;
ALTER TABLE frozen_plate_tokens ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON frozen_plate_tokens FROM PUBLIC, anon, authenticated;
ALTER TABLE frozen_plate_revocations ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON frozen_plate_revocations FROM PUBLIC, anon, authenticated;
ALTER TABLE frozen_plate_deliveries ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON frozen_plate_deliveries FROM PUBLIC, anon, authenticated;
ALTER TABLE frozen_plate_approvals ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON frozen_plate_approvals FROM PUBLIC, anon, authenticated;
ALTER TABLE frozen_plate_sourcing ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON frozen_plate_sourcing FROM PUBLIC, anon, authenticated;
REVOKE ALL ON SCHEMA frozen_plate_production FROM PUBLIC, anon, authenticated;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA frozen_plate_production FROM PUBLIC, anon, authenticated;


CREATE ROLE frozen_plate_production_api NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS;
GRANT USAGE ON SCHEMA frozen_plate_production TO frozen_plate_production_api;
GRANT SELECT, INSERT ON ALL TABLES IN SCHEMA frozen_plate_production TO frozen_plate_production_api;
GRANT UPDATE(current_revision,lifecycle) ON frozen_plates TO frozen_plate_production_api;
DO $policies$ DECLARE t text; BEGIN
FOR t IN SELECT tablename FROM pg_tables WHERE schemaname='frozen_plate_production' LOOP
EXECUTE format('CREATE POLICY backend_select ON frozen_plate_production.%I FOR SELECT TO frozen_plate_production_api USING (true)',t);
EXECUTE format('CREATE POLICY backend_insert ON frozen_plate_production.%I FOR INSERT TO frozen_plate_production_api WITH CHECK (true)',t);
END LOOP; END $policies$;
CREATE POLICY backend_update ON frozen_plates FOR UPDATE TO frozen_plate_production_api USING (true) WITH CHECK (true);
COMMIT;

