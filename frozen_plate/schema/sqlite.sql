PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS frozen_plates (
 id TEXT PRIMARY KEY, order_id TEXT NOT NULL, line_id TEXT NOT NULL,
 configuration_id TEXT NOT NULL, customer_id TEXT NOT NULL,
 current_revision TEXT, lifecycle TEXT NOT NULL DEFAULT 'EMPTY'
 CHECK(lifecycle IN ('EMPTY','READY_FOR_CUSTOMER_CONFIRMATION','CUSTOMER_APPROVED','READY_FOR_RELEASE')),
 created_at TEXT NOT NULL, created_by TEXT NOT NULL,
 UNIQUE(order_id,line_id),
 CHECK((current_revision IS NULL AND lifecycle='EMPTY') OR (current_revision IS NOT NULL AND lifecycle<>'EMPTY')),
 FOREIGN KEY(current_revision,id) REFERENCES frozen_plate_revisions(id,plate_id) DEFERRABLE INITIALLY DEFERRED
);
CREATE TABLE IF NOT EXISTS frozen_plate_revisions (
 id TEXT PRIMARY KEY, plate_id TEXT NOT NULL REFERENCES frozen_plates(id),
 number INTEGER NOT NULL CHECK(number>0), spec_json TEXT NOT NULL,
 spec_sha256 TEXT NOT NULL CHECK(length(spec_sha256)=64),
 source_json TEXT NOT NULL, source_sha256 TEXT NOT NULL CHECK(length(source_sha256)=64),
 spec_schema INTEGER NOT NULL, generator_version TEXT NOT NULL, geometry_version TEXT NOT NULL,
 drawing_metadata_json TEXT NOT NULL, reason TEXT NOT NULL,
 created_at TEXT NOT NULL, created_by TEXT NOT NULL,
 UNIQUE(plate_id,number), UNIQUE(id,plate_id)
);
CREATE TABLE IF NOT EXISTS frozen_plate_artifacts (
 id TEXT PRIMARY KEY, revision_id TEXT NOT NULL REFERENCES frozen_plate_revisions(id),
 kind TEXT NOT NULL CHECK(kind IN ('pdf','dxf','json')),
 object_key TEXT NOT NULL UNIQUE, filename TEXT NOT NULL,
 sha256 TEXT NOT NULL CHECK(length(sha256)=64), size INTEGER NOT NULL CHECK(size>0),
 generator_version TEXT NOT NULL, generated_at TEXT NOT NULL,
 UNIQUE(revision_id,kind), UNIQUE(id,revision_id,kind)
);
CREATE TABLE IF NOT EXISTS frozen_plate_tokens (
 fingerprint TEXT PRIMARY KEY, revision_id TEXT NOT NULL REFERENCES frozen_plate_revisions(id),
 pdf_id TEXT NOT NULL, pdf_kind TEXT NOT NULL DEFAULT 'pdf' CHECK(pdf_kind='pdf'),
 pdf_sha256 TEXT NOT NULL, spec_sha256 TEXT NOT NULL,
 customer_id TEXT NOT NULL, order_id TEXT NOT NULL,
 created_at TEXT NOT NULL, expires_at REAL NOT NULL,
 UNIQUE(fingerprint,revision_id,pdf_id),
 FOREIGN KEY(pdf_id,revision_id,pdf_kind) REFERENCES frozen_plate_artifacts(id,revision_id,kind)
);
CREATE TABLE IF NOT EXISTS frozen_plate_revocations (
 fingerprint TEXT PRIMARY KEY REFERENCES frozen_plate_tokens(fingerprint),
 revoked_at TEXT NOT NULL, reason TEXT NOT NULL, actor TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS frozen_plate_deliveries (
 id TEXT PRIMARY KEY, revision_id TEXT NOT NULL, pdf_id TEXT NOT NULL,
 token_fingerprint TEXT NOT NULL, recipient_id TEXT NOT NULL,
 generated_at TEXT NOT NULL, sent_at TEXT CHECK(sent_at IS NULL),
 template_version TEXT NOT NULL, state TEXT NOT NULL CHECK(state='LOCAL_RENDERED'),
 mime_sha256 TEXT NOT NULL,
 FOREIGN KEY(token_fingerprint,revision_id,pdf_id) REFERENCES frozen_plate_tokens(fingerprint,revision_id,pdf_id)
);
CREATE TABLE IF NOT EXISTS frozen_plate_approvals (
 revision_id TEXT PRIMARY KEY REFERENCES frozen_plate_revisions(id),
 pdf_id TEXT NOT NULL, token_fingerprint TEXT NOT NULL,
 pdf_sha256 TEXT NOT NULL, spec_sha256 TEXT NOT NULL,
 customer_id TEXT NOT NULL, order_id TEXT NOT NULL,
 approved_at TEXT NOT NULL, status TEXT NOT NULL CHECK(status='CUSTOMER_APPROVED'),
 audit_json TEXT NOT NULL,
 FOREIGN KEY(token_fingerprint,revision_id,pdf_id) REFERENCES frozen_plate_tokens(fingerprint,revision_id,pdf_id)
);
CREATE TABLE IF NOT EXISTS frozen_plate_sourcing (
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
CREATE TRIGGER IF NOT EXISTS plate_identity_immutable BEFORE UPDATE OF id,order_id,line_id,configuration_id,customer_id,created_at,created_by ON frozen_plates
BEGIN SELECT RAISE(ABORT,'frozen plate identity is immutable'); END;
CREATE TRIGGER IF NOT EXISTS no_plate_delete BEFORE DELETE ON frozen_plates
BEGIN SELECT RAISE(ABORT,'frozen plate history is immutable'); END;
