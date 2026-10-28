"""Private, verified pre-migration snapshot. Run explicitly in the API runtime.

Snapshot stays in the existing private bucket. Never prints customer/token data.
Rollback leaves additive tables in place and redeploys the old application builds.
Disaster restoration requires a DBA and an empty isolated database; never overwrite
immutable live rows. This backup is an extra logical snapshot, not a PITR claim.
"""

import json
from uuid import uuid4
from hashlib import sha256
from frozen_plate.runtime import repository

TABLES = (
    "frozen_plates",
    "frozen_plate_revisions",
    "frozen_plate_artifacts",
    "frozen_plate_tokens",
    "frozen_plate_revocations",
    "frozen_plate_deliveries",
    "frozen_plate_approvals",
    "frozen_plate_sourcing",
)


def main():
    repo = repository()
    with repo.connect() as db:
        db.execute("BEGIN")
        rows = {
            table: [dict(r) for r in db.execute("SELECT * FROM " + table)]
            for table in TABLES
        }
        objects = [
            dict(r)
            for r in db.execute(
                "SELECT object_key,size,sha256 FROM frozen_plate_artifacts"
            )
        ]
        # Record schema, ACL, policy and trigger metadata, never role passwords.
        catalog = [
            dict(r)
            for r in db.execute(
                "SELECT n.nspname,c.relname,c.relacl::text,c.relrowsecurity,c.relforcerowsecurity FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname=current_schema() AND c.relkind='r'"
            )
        ]
    # Snapshot order rows from the existing server database, without changing them.
    from sqlalchemy import create_engine, text
    import os

    engine = create_engine(os.environ["DATABASE_URL"])
    with engine.connect() as connection:
        orders = [
            dict(r._mapping) for r in connection.execute(text("SELECT * FROM orders"))
        ]
    verified = 0
    for o in objects:
        raw = repo._read_object(o["object_key"])
        if len(raw) != o["size"] or sha256(raw).hexdigest() != o["sha256"]:
            raise RuntimeError("Pre-migration original artifact integrity failure")
        verified += 1
    payload = json.dumps(
        dict(
            format="oplates-pre-cutover-logical-snapshot-v1",
            frozen=rows,
            orders=orders,
            catalog=catalog,
            objects=objects,
        ),
        sort_keys=True,
        default=str,
        separators=(",", ":"),
    ).encode()
    key = "backups/final4/pre-cutover-" + uuid4().hex + ".json"
    repo.storage.put(key, payload)
    if repo.storage.get(key) != payload:
        raise RuntimeError("Private backup byte verification failed")
    print(
        json.dumps(
            dict(
                status="PASS",
                backup_key=key,
                bytes=len(payload),
                sha256=sha256(payload).hexdigest(),
                row_counts={t: len(v) for t, v in rows.items()},
                orders=len(orders),
                original_files_verified=verified,
            )
        )
    )


if __name__ == "__main__":
    main()
