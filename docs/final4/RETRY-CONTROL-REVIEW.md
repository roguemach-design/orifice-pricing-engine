# Automatic engineering retry correction — review only

No provider setting, service, database or artifact has been changed or deployed. Production pricing, checkout mode, approval behavior and TEST isolation are outside this PR's scope.

## Operational containment is a separate patch

The existing deployed staging binary has no independent worker-only enable setting. FINAL4_ENABLED also disables manual engineering routes. The separate switch-only PR, based on the exact deployed staging commit, is the minimal deployment candidate for separately authorized containment. This full correction must not be used as an urgent unreviewed deployment.

This correction preserves the same independent FINAL4_AUTOMATIC_STAGING_ENABLED switch. Keep it false on staging through any later installation/deployment until the owner separately approves re-enabling. Absence preserves the previous default; no code or migration writes a service environment setting or enables a worker.

## Persistent suppression and retries

A new private manufacturing_retry_control table holds only automatic retry control; it is separate from immutable Frozen Plate, approval and bundle records. Permanent rejection keys include family, exact parent identity/spec/source hashes and controlled profile/generator hashes. Unchanged failures are skipped after repeated sweeps and process restarts. A new revision or controlled profile has a new key. Logical HAAS failure does not block packaging.

Only a generator/profile ValueError is classified as ProfileBlocked. Storage, database, metadata-integrity and unknown errors are not permanent profile rejections. No provider response body, credential, connection string, arbitrary exception text or customer data is logged or written as a failure detail.

Transient job retries use 30/60/120... seconds, capped at 15 minutes. HTTP 402 starts at five minutes and caps at one hour. A provider circuit is shared across families in the private project ledger, so one outage does not trigger requests for every parent. The circuit survives restart while its database is reachable. A missing ledger migration or database outage stops automatic work and uses bounded in-process scan backoff; it never falls back to an in-memory permanent-failure ledger. If the database itself is unavailable, new backoff state cannot be persisted there; a process restart necessarily makes one bounded recovery attempt.

Automatic status reports disabled/cooling-down states, rather than claiming generated artifacts are available. Manual engineering authorization and verified download restrictions remain independent.

## Bytes and connections

Remote repositories cache verified original artifact bytes for up to five minutes, bounded to 32 MiB and 256 entries per repository. Keys include object identity, expected SHA-256 and size. Cold loads and cache hits verify the digest and size. Unverified bytes are never cached. Metadata, identity, current-revision and approval checks remain in their existing paths; caching grants no release eligibility or cross-customer access. Local immutable-repository behavior remains uncached for deterministic integrity tests.

Private database contexts share a lazily created, thread-safe pool with at most four connections per repository/process. Checkout for a connection waits at most five seconds; connection establishment is bounded by the existing 15-second timeout. The validated DSN, private role, SSL and search path are preserved. Cursors close and transactions roll back before a connection is returned; broken connections are discarded. Replicas/processes each have their own bounded pool, so the deployment's aggregate limit must still respect the database connection budget.

## Explicit migration and release boundary

final4.postgres.retry_migration(schema) renders an additive migration for only the existing allowlisted staging or production schema. It checks the restricted role/architecture, forces RLS, revokes PUBLIC/anon/authenticated access and grants SELECT/INSERT/UPDATE only on the retry-control table to the existing private API role. It grants no DELETE and changes no protected artifact/workflow table. No startup DDL exists. Nothing has been applied to Supabase.

A future approved release must install the reviewed migration in its explicitly approved environment before enabling automatic work. The migration is not needed for the separate switch-only containment patch. Existing backend role, credentials and schemas are reused; there is no new service or paid dependency.

Rollback: keep automatic staging disabled, restore the previous application build, and retain the additive control table for investigation. Never delete Frozen Plates, approvals or bundles, and never toggle FINAL4_ENABLED or checkout mode as a substitute. Re-enabling is a separate owner action, not a rollback side effect.

## Regression evidence

Tests cover disabled startup/wake/sweep without service construction; default compatibility; permanent suppression over sweeps and restart; revision/spec/source/profile changes; independent packaging; durable shared HTTP 402 circuit and exponential caps; nonpermanent integrity failures; missing migration failure; actual profile rejection without repeated parent reads; SHA-256 validation on cold/cache-hit/expired/tampered bytes; bounded LRU memory; parallel connection bounds and cleanup; sanitized database failures; and private migration grants. Existing automatic staging, Frozen Plate and production wiring regressions are retained.

All 51 protected output hashes must match the accepted baseline. Runtime integrity checks and immutable-generation rules are unchanged. Quote/session/chamfer PRs are not merged or modified.
