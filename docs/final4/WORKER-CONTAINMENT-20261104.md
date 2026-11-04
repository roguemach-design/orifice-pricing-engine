# OP-IMP-008 — default-off automatic worker containment

Prepared November 4, 2026. **Review only: no merge, deployment, configuration
change, service restart, migration or worker activation is authorized.**

## Release scope and compatibility

Exact production API parent: `6b3c5de962c87f5ef59948c658947cddb1d92a56`.
The isolated PR targets `review/imp008-production-6b3c5de9`, pinned to that parent;
it must not target or deploy the unrelated integration branch head containing #52.

Only `final4/worker.py` and `final4/runtime.py` change runtime behavior. The existing
synthetic automatic-worker tests explicitly opt in, and the new containment tests
exercise default-off execution, real approval callbacks, lifecycle concurrency,
shutdown, restart and authenticated manual TEST generation. This document and the
51-hash evidence JSON are the other changed files. No generators, protected
fixtures, pricing, customer UI, API routes, checkout code, dependencies, SQL,
database adapter or storage implementation change. PR #52 is excluded.

No database migration or new privilege is needed. The existing production private
schema, restricted role and immutable records remain compatible by unchanged code
and isolated regression evidence. No live database writes or artifact generation
were used to validate this candidate. Production runtime acceptance remains a
separate gate. `GET /health` still returns `{"ok": true}`; it is liveness, not proof
of worker inactivity. The Render API command remains
`uvicorn api_app:app --host 0.0.0.0 --port 10000` on service
`srv-d51l6ch5pdvs73ealnh0`. No health-check setting or other service changes.

## Configuration semantics and precedence

The retained setting name **`FINAL4_AUTOMATIC_STAGING_ENABLED` applies to both
production and staging**. It is not limited to the staging environment.

| Setting value | Automatic worker behavior |
| --- | --- |
| Absent | Disabled; no thread or service/discovery construction |
| Exact literal `false` | Disabled |
| Exact literal `true` | Enables the existing behavior, subject to application gates |
| Empty, `TRUE`, `1`, whitespace or any other value | Disabled |

There is no secondary alias or conflicting precedence rule. This deliberately
differs from #51/#52's absent-means-enabled behavior. The application must first
pass the existing Frozen Plate binding/environment gate and `FINAL4_ENABLED=true`
to register its manual routes and runner. The independent switch can only restrict
automatic execution: it cannot enable the application integration on its own.
`FINAL4_ENABLED` retains its original meaning and must remain unchanged to preserve
manual engineering. `runtime.automatic()` supplies profiles/shared services for
manual TEST generation; constructing it is not an automatic scan.

Configuration/status responses now truthfully report disabled automatic staging.
Manual configuration metadata still uses the existing repository, but disabled
worker startup, direct `run`/`sweep`, and approval notifications do not construct a
service, discover parents or read artifact bytes.

## Every startup, wake-up and retry location

1. `api_app.py`'s final additive integration block calls cached
   `final4.runtime.worker()` and assigns `app.state.manufacturing_stager` only under
   the existing Frozen Plate and FINAL4 gates. Construction alone does no scan.
2. `api_app.platform_lifespan` enters `final4.worker.lifespan`, whose `runner.start()`
   now checks the independent switch. The only thread constructor/start is
   `StagingWorker.start`, naming the daemon `manufacturing-stager`.
3. `StagingWorker.run` guards its loop; `sweep` guards its entry and each family
   boundary before attempting work. The preexisting 30-second retry remains only
   when explicitly enabled; this containment PR adds no retry ledger/backoff.
4. `api_app.notify_manufacturing_approval` calls `final4.worker.request_scan` after
   approval. `request_scan` now ignores disabled notifications, so customer
   approval cannot start/wake automatic work. Direct sweep calls are also guarded.
5. On lifespan shutdown, `stop()` sets the stop event and wakes a waiting thread.
   This shutdown wake is not a generation request. Start/stop use a lifecycle lock;
   repeated/concurrent start cannot create a duplicate, and a cached runner can
   restart after a completed stop. A timed-out join retains its live thread handle
   and stop flag; subsequent start cannot clear it or spawn another runner.

Synchronous in-flight DB/Storage/generator calls cannot be forcibly cancelled by a
Python event. The existing two-second join is bounded, not a guarantee that an
already-running provider call has completed. Stop prevents the next family/retry;
operators must confirm retirement of the old process during deployment. Changing
an OS environment setting requires a new service process; this is not a hot remote
kill endpoint. Disabled startup creates no background manufacturing task at all.

The independent Journey sidecar in platform_lifespan is unchanged and can still
produce legitimate analytics database activity. Worker containment does not mean
zero total API/DB traffic. The synthetic `final4.staging_app` harness remains a
separate temporary-local repository entry point, not this periodic worker.

## Offline validation evidence

`tests/test_worker_containment.py` covers missing/false and malformed values;
disabled lifespan restart, direct start/run/sweep and approval notifications;
literal-true synthetic behavior; concurrent starts; stop during blocked work;
timed-out stop without duplicate creation; cached-runner restart; disabling between
families; truthful configuration; and authenticated owner TEST generation of both
families with unchanged Frozen Plate rows and no release eligibility.

Existing automatic staging regressions opt in only inside their own temporary
local fixture module. Existing manual authorization, provenance, immutable bytes,
tamper, supersession, TEST/LIVE restrictions and checkout tests remain unchanged.
No test is configured with live provider credentials. Production generation is not
an acceptance method for this PR.

`worker-containment-hashes-20261104.json` records all **51 SHA-256 values**, generated
independently in the exact baseline worktree and this candidate with
`scripts/drawing_isolation_hashes.py`; all match. These are synthetic manufacturing
outputs, not downloaded production-artifact fingerprints. Final local and exact-head
CI results are recorded in the PR/issue acceptance update, outside the code commit
to avoid changing the tested head to report its own CI result.

## Proposed production deployment authorization package

**Not executed. Owner must approve the exact final candidate SHA and CI evidence.**

Target only production API `srv-d51l6ch5pdvs73ealnh0`; preserve its command, other
environment variables, manual integration, Checkout **TEST version 7**, UI, landing,
MC, staging states and protected records. Do not deploy the entire PR #52 branch.

1. Verify current production baseline/active deployments and export only a safe
   nonsecret configuration inventory. Confirm the release contains the reviewed
   switch and no migrations. Record baseline scan counters, reset timestamp,
   Storage requests/errors and connection-event rate. Confirm the existing rollback
   situation with the owner before beginning.
2. Merge **only** `FINAL4_AUTOMATIC_STAGING_ENABLED=false` into this API's environment;
   do not replace all variables. Preserve `FINAL4_ENABLED=true`. Explicitly choose
   Render's save behavior to avoid an unintended separate old-code redeploy.
   **The setting alone cannot stop the currently deployed old binary.**
3. Deploy only the separately approved exact candidate SHA. Keep automatic-deploy
   off. Confirm new instance is live and every old API instance is terminated;
   never treat “new deploy started” as containment. No true setting is authorized.
4. Verify `GET /health` returns HTTP 200 with `{"ok":true}`. Read the authorized
   manufacturing configuration and require `automatic_staging=false`; verify
   staging-status responses say `AUTOMATIC STAGING DISABLED`. Check representative
   read-only pricing/customer availability and TEST-only checkout authority.
5. After old instances retire, record time T0, the following counter and
   `pg_stat_statements_info.stats_reset`. Record again **at least 180 seconds later**
   (more than 150 seconds / five old sweep periods). Require unchanged calls and
   reset timestamp. Missing/evicted counters, reset/decreasing values, or a new
   startup are inconclusive; restart the observation window rather than pass it.

   ```sql
   SELECT now() AS observed_at, queryid::text, calls, rows
   FROM pg_stat_statements
   WHERE queryid = -7114739673449014159;
   SELECT stats_reset FROM pg_stat_statements_info;
   ```

6. Inspect a controlled ten-minute Storage/edge/pool-log window, then a later
   24-hour window. Classify legitimate manual/customer reads separately using
   existing logs; do not download artifacts to test accessibility. Require no
   worker-origin repeated object pattern, no 402/429 burst and no growing scan
   counter. Connection counts need not become zero because customer/manual/API
   reads and Journey remain active. Late log ingestion is possible.
7. Verify manual TEST generation remains registered, authorized and visible
   without invoking it: inspect existing owner controls/configuration, and verify
   the POST-only route remains registered via a non-generating request/method
   check. Do not press Generate or submit generation. Synthetic API tests provide
   the actual generation acceptance for this release. Preserve all existing
   manufacturing records and compare read-only metadata fingerprints.
8. Stop deployment acceptance for failed health, lost manual route/authorization,
   a scan counter increase after old-process retirement, enabled status, unexplained
   repeated object downloads, a quota/error burst, changed TEST authority or
   unexplained protected-record differences. Do not re-enable the worker or run
   #52/migrations to repair acceptance. Escalate the concrete evidence and apply
   only the emergency action separately authorized by the owner.

The owner must approve this exact service, final SHA, false-only variable update,
health/counter/usage/manual-route checks, observation windows and emergency tradeoff.
This document grants none of those permissions by itself.

## Safe fallback and emergency response

The code-only containment commit is pinned at
**`833cdf001afc5b76cf876da370e20da33734658c`**. The final PR adds only release/hash
documentation to that code. After its CI/review and production acceptance, retain
the exact SHA/build as the switch-capable fallback for later #52 work. Confirm the
same runtime files in the final candidate and pinned fallback. Keep the independent
switch false during any approved fallback deployment. Do not assume a Git branch
name always points to this commit or that a retained Render deploy is available
until it has actually been created and verified.

**There is no previously production-accepted switch-capable rollback today.** The
pinned commit is a prepared fallback, not a claim it is already live or independently
proven in production. If the first containment deployment itself fails, restoring
the same runtime code is not a remedy. Obtain an explicit owner incident decision:

- Suspend the production API to stop all its worker activity, accepting customer
  API unavailability; or
- restore an approved older binary only with `FINAL4_ENABLED=false`, accepting the
  loss of manual engineering routes and the necessary redeploy. Independently
  preserve all other settings. This is a broad emergency measure, not normal
  rollback and not currently authorized.

Never describe restoring **`6b3c5de962c87f5ef59948c658947cddb1d92a56`** with
`FINAL4_ENABLED=true` as safe: that old build ignores the independent false flag and
reactivates scanning. Do not pause production Supabase or alter historical records
as a worker kill switch. Preserve evidence, verify old-process termination and
recheck scan counters after any owner-approved emergency action.

## Deferred work

PR #52 retry suppression/pooling/cache, hard request/byte ceilings, alerts and future
automatic activation remain separate approvals. This PR intentionally leaves
explicit-true retry behavior unchanged and does not qualify it for production use.
Keep main staging suspended. Supabase staging disposition remains an owner decision.
