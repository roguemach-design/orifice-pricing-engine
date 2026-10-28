"""Private durable retry control; never changes a Frozen Plate or bundle."""

import json
from frozen_plate.repository import canonical, digest, WorkflowError
from frozen_plate.transport import ProviderUnavailable

SCHEMA = """
CREATE TABLE IF NOT EXISTS manufacturing_retry_control (
 retry_key TEXT PRIMARY KEY CHECK(length(retry_key)=64),
 state TEXT NOT NULL CHECK(state IN ('PERMANENT','RETRY','READY','CIRCUIT')),
 attempts INTEGER NOT NULL CHECK(attempts BETWEEN 0 AND 32),
 retry_at DOUBLE PRECISION NOT NULL CHECK(retry_at>=0),
 result_json TEXT NOT NULL,
 updated_at DOUBLE PRECISION NOT NULL
);
"""


class ProfileBlocked(ValueError):
    """Only an actual generator/profile rejection is permanent."""


CIRCUIT_KEY = digest("automatic-engineering-provider-circuit-v1")


def job_key(family, parent, signature):
    return digest(canonical(dict(family=family, parent=parent, profile=signature)))


def delay(attempts, status=None):
    base, ceiling = (300, 3600) if status == 402 else (30, 900)
    return min(ceiling, base * 2 ** min(max(attempts - 1, 0), 7))


class RetryLedger:
    def __init__(self, repo):
        self.repo = repo

    def get(self, key):
        with self.repo.connect() as db:
            row = db.execute(
                "SELECT state,attempts,retry_at,result_json FROM manufacturing_retry_control WHERE retry_key=?",
                (key,),
            ).fetchone()
        if not row:
            return None
        result = dict(row)
        result["result"] = json.loads(result.pop("result_json"))
        return result

    def put(self, key, state, attempts, retry_at, result, now):
        with self.repo.transaction() as db:
            db.execute(
                """INSERT INTO manufacturing_retry_control
                (retry_key,state,attempts,retry_at,result_json,updated_at) VALUES (?,?,?,?,?,?)
                ON CONFLICT (retry_key) DO UPDATE SET state=excluded.state,
                attempts=excluded.attempts,retry_at=excluded.retry_at,
                result_json=excluded.result_json,updated_at=excluded.updated_at""",
                (key, state, min(attempts, 32), retry_at, canonical(result), now),
            )
