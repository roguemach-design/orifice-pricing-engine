"""PostgreSQL invariants for new commercial quote tables only."""

from sqlalchemy import text

DDL = """
CREATE OR REPLACE FUNCTION protect_saved_quote_snapshot() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'Saved quote records are immutable';
  END IF;
  IF ROW(NEW.quote_id,NEW.root_quote_id,NEW.revision,NEW.supersedes_quote_id,
         NEW.owner_user_id,NEW.created_at,NEW.valid_through,NEW.snapshot::text,
         NEW.pdf_bytes,NEW.pdf_sha256)
     IS DISTINCT FROM
     ROW(OLD.quote_id,OLD.root_quote_id,OLD.revision,OLD.supersedes_quote_id,
         OLD.owner_user_id,OLD.created_at,OLD.valid_through,OLD.snapshot::text,
         OLD.pdf_bytes,OLD.pdf_sha256) THEN
    RAISE EXCEPTION 'Saved quote snapshots are immutable; create a revision';
  END IF;
  RETURN NEW;
END; $$;
DROP TRIGGER IF EXISTS saved_quote_snapshot_guard ON saved_quotes;
CREATE TRIGGER saved_quote_snapshot_guard BEFORE UPDATE OR DELETE ON saved_quotes
FOR EACH ROW EXECUTE FUNCTION protect_saved_quote_snapshot();
REVOKE ALL ON FUNCTION protect_saved_quote_snapshot() FROM PUBLIC;
CREATE OR REPLACE FUNCTION protect_quote_audit() RETURNS trigger
LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'Quote audit events are append-only'; END; $$;
DROP TRIGGER IF EXISTS quote_audit_guard ON quote_events;
CREATE TRIGGER quote_audit_guard BEFORE UPDATE OR DELETE ON quote_events
FOR EACH ROW EXECUTE FUNCTION protect_quote_audit();
REVOKE ALL ON FUNCTION protect_quote_audit() FROM PUBLIC;
REVOKE ALL ON saved_quotes,quote_shares,quote_events,quote_reviews,quote_mail FROM PUBLIC;
ALTER TABLE saved_quotes ENABLE ROW LEVEL SECURITY;
ALTER TABLE quote_shares ENABLE ROW LEVEL SECURITY;
ALTER TABLE quote_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE quote_reviews ENABLE ROW LEVEL SECURITY;
ALTER TABLE quote_mail ENABLE ROW LEVEL SECURITY;
-- These records are served only through the server-owned API, never PostgREST.
-- Supabase can grant its browser roles independently of PUBLIC by default.
DO $$ DECLARE browser_role text; BEGIN
  FOREACH browser_role IN ARRAY ARRAY['anon','authenticated'] LOOP
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = browser_role) THEN
      EXECUTE format('REVOKE ALL ON saved_quotes,quote_shares,quote_events,quote_reviews,quote_mail FROM %I', browser_role);
    END IF;
  END LOOP;
END; $$;
"""


def install(engine):
    if engine.dialect.name == "postgresql":
        with engine.begin() as connection:
            connection.execute(text(DDL))
