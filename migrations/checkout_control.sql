-- Additive; run as the existing orders DB migration owner, not a customer role.
-- Review the runtime role against DATABASE_URL before granting anything.
BEGIN;
CREATE SCHEMA IF NOT EXISTS checkout_control;
REVOKE ALL ON SCHEMA checkout_control FROM PUBLIC;
CREATE TABLE checkout_control.mode_state (
 id integer PRIMARY KEY CHECK (id=1),
 requested_mode text NOT NULL CHECK (requested_mode IN ('CLOSED','TEST','LIVE')),
 version bigint NOT NULL CHECK (version>=1),
 changed_at timestamptz NOT NULL,
 test_binding_verified_at timestamptz
);
CREATE TABLE checkout_control.mode_audit (
 id text PRIMARY KEY, version bigint UNIQUE NOT NULL,
 previous_mode text NOT NULL, requested_mode text NOT NULL,
 changed_at timestamptz NOT NULL, actor text NOT NULL
);
CREATE TABLE checkout_control.test_accounts (
 customer_id text PRIMARY KEY, email text UNIQUE NOT NULL,
 enabled boolean NOT NULL DEFAULT false, verified_at timestamptz,
 CHECK (email = lower(email))
);
INSERT INTO checkout_control.mode_state VALUES (1,'CLOSED',1,now(),NULL);
INSERT INTO checkout_control.mode_audit VALUES ('initial-closed',1,'CLOSED','CLOSED',now(),'migration-owner');
REVOKE ALL ON ALL TABLES IN SCHEMA checkout_control FROM PUBLIC;
-- Existing backend-only least-privilege identity; no new credentials.
GRANT USAGE ON SCHEMA checkout_control TO frozen_plate_production_api;
GRANT SELECT ON ALL TABLES IN SCHEMA checkout_control TO frozen_plate_production_api;
GRANT UPDATE(requested_mode,version,changed_at) ON checkout_control.mode_state TO frozen_plate_production_api;
GRANT INSERT ON checkout_control.mode_audit TO frozen_plate_production_api;
ALTER TABLE checkout_control.mode_state ENABLE ROW LEVEL SECURITY;
ALTER TABLE checkout_control.mode_audit ENABLE ROW LEVEL SECURITY;
ALTER TABLE checkout_control.test_accounts ENABLE ROW LEVEL SECURITY;
CREATE POLICY backend_read ON checkout_control.mode_state FOR SELECT TO frozen_plate_production_api USING (true);
CREATE POLICY backend_update ON checkout_control.mode_state FOR UPDATE TO frozen_plate_production_api USING (id=1) WITH CHECK (id=1);
CREATE POLICY backend_read ON checkout_control.mode_audit FOR SELECT TO frozen_plate_production_api USING (true);
CREATE POLICY backend_append ON checkout_control.mode_audit FOR INSERT TO frozen_plate_production_api WITH CHECK (true);
CREATE POLICY backend_read ON checkout_control.test_accounts FOR SELECT TO frozen_plate_production_api USING (true);
-- Registrations and test_binding_verified_at remain migration-owner-only.
-- Never populate binding verification from configured secret prefixes alone.
COMMIT;
