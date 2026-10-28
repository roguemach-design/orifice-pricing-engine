# Worker-only containment switch — not deployed

The pinned staging release 64d3b70fcb6cabf280c0851f74c038dd8b7d99fe has only FINAL4_ENABLED. That flag also removes manual owner engineering routes, so it does not satisfy worker-only containment.

This branch adds only FINAL4_AUTOMATIC_STAGING_ENABLED. An absent value preserves existing behavior; literal true enables the worker; false (or any other explicit value) disables its startup, sweeps and approval wake-ups. The owner configuration/status reports the disabled worker accurately. FINAL4_ENABLED and manual engineering routes stay unchanged.

This isolated patch is based on the exact deployed staging commit, not the newer staging branch head. It contains no pricing, authentication, storage, database migration, pooling or retry-ledger changes. Production must not be deployed or configured from this branch.

No live setting was changed during preparation. Deployment of this small code patch requires separate owner approval because the current authorization permits configuration-only containment and forbids deployment of the code correction.

After separate approval: deploy this switch-only commit to the staging pricing API, with FINAL4_AUTOMATIC_STAGING_ENABLED=false merged into that service's existing environment. Preserve every other variable and the existing API command. Do not deploy the staging branch's unrelated commits. Leave the switch false when reviewing/deploying a later reliability fix; never automatically re-enable it.

Verify /health and read-only pricing availability, manual owner routes remaining registered, no new worker warnings, and no worker-origin Supabase object requests/connection churn during several complete previous sweep periods. Compare pre/post protected revision, artifact, approval and bundle fingerprints. Provider 402 restrictions may remain after traffic stops; containment cannot erase already accumulated usage.

Reversal, only after separate owner approval: set FINAL4_AUTOMATIC_STAGING_ENABLED=true on this one service and deploy the same approved source. Do not change FINAL4_ENABLED, checkout mode or production. This resumes automatic staging, so it must not be used as an automatic rollback while the retry defect remains.
