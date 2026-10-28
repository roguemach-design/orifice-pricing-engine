"""Operator-only PostgreSQL provisioning; never imported by application startup.

Uses an existing administrative connection supplied through protected environment.
Creates only the five journey tables and a new DML-only role. Does not rotate an
existing role, change business grants or modify existing business rows.
"""

from sqlalchemy import inspect, text
from sqlalchemy.engine import make_url
from psycopg2 import sql
from .store import metadata

ROLE = "oplates_journey_v1"


def provision(engine, password):
    if engine.dialect.name != "postgresql" or len(password) < 32:
        raise ValueError("PostgreSQL and a generated password are required")
    with engine.begin() as db:
        if db.scalar(text("SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname=:role)"), {"role": ROLE}):
            raise ValueError("Analytics role already exists; inspect it without rotating credentials")
        # Transactional DDL: failure rolls back both new tables and the role.
        metadata.create_all(db)
        for table in metadata.sorted_tables:
            actual = {c["name"] for c in inspect(db).get_columns(table.name, schema="public")}
            if actual != set(table.c.keys()):
                raise ValueError("Unexpected analytics table schema")
        raw = db.connection.driver_connection
        with raw.cursor() as cursor:
            cursor.execute(sql.SQL(
                "CREATE ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOCREATEDB NOCREATEROLE "
                "NOINHERIT NOREPLICATION NOBYPASSRLS CONNECTION LIMIT 4"
            ).format(sql.Identifier(ROLE), sql.Literal(password)))
            cursor.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
                sql.Identifier(db.scalar(text("SELECT current_database()"))), sql.Identifier(ROLE)))
            cursor.execute(sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(sql.Identifier(ROLE)))
            for name in metadata.tables:
                cursor.execute(sql.SQL("GRANT SELECT, INSERT, UPDATE, DELETE ON public.{} TO {}").format(
                    sql.Identifier(name), sql.Identifier(ROLE)))
        verify_access(db, ROLE)
    return make_url(engine.url).set(username=ROLE, password=password)


def verify_access(db, role=ROLE):
    row = db.execute(text(
        "SELECT rolsuper, rolcreatedb, rolcreaterole, rolreplication, rolbypassrls "
        "FROM pg_roles WHERE rolname=:role"
    ), {"role": role}).first()
    if not row or any(row):
        raise ValueError("Unsafe analytics role attributes")
    if db.scalar(text("SELECT has_schema_privilege(:role, 'public', 'CREATE')"), {"role": role}):
        raise ValueError("Analytics role must not have schema creation access")
    # Fail closed if inherited/PUBLIC grants expose any non-analytics relation.
    rows = db.execute(text(
        "SELECT n.nspname, c.relname, c.oid, c.relkind FROM pg_class c "
        "JOIN pg_namespace n ON n.oid=c.relnamespace "
        "WHERE c.relkind IN ('r','p','v','m','f','S') "
        "AND n.nspname NOT IN ('pg_catalog','information_schema') "
        "AND n.nspname NOT LIKE 'pg_toast%'"
    )).all()
    for schema, name, oid, kind in rows:
        if schema == "public" and name in metadata.tables:
            continue
        check = (
            "SELECT has_sequence_privilege(:role, CAST(:oid AS oid), 'USAGE,SELECT,UPDATE')"
            if kind == "S" else
            "SELECT has_table_privilege(:role, CAST(:oid AS oid), "
            "'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER')"
        )
        if db.scalar(text(check), {"role": role, "oid": oid}):
            raise ValueError("Analytics role can access a non-analytics relation")


def main():
    import os
    import secrets
    from pathlib import Path
    from sqlalchemy import create_engine

    # Output is a NEW owner-readable file, never a command line argument or log.
    destination = Path(os.environ["JOURNEY_BINDING_FILE"])
    fd = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        engine = create_engine(os.environ["JOURNEY_ADMIN_DATABASE_URL"], hide_parameters=True,
                               connect_args={"connect_timeout": 5})
        url = provision(engine, secrets.token_urlsafe(48))
        with os.fdopen(fd, "w") as out:
            fd = None
            out.write("JOURNEY_DATABASE_URL=" + url.render_as_string(hide_password=False) + "\n")
        print("Analytics tables and restricted role prepared. Binding saved to the protected output file.")
    except Exception:
        if fd is not None:
            os.close(fd)
        destination.unlink(missing_ok=True)
        # Never print database connection strings, SQL password literals or exceptions.
        raise SystemExit("Analytics provisioning failed; transaction rolled back. Inspect access/schema securely.") from None


if __name__ == "__main__":
    main()
