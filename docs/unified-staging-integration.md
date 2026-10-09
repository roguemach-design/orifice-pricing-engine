# Unified staging acceptance candidate

Owner approved Phase 5 staging as the combined target on 2026-10-02.

Accepted inputs preserved:
- main 94731f295fd842cdac8dbbbea44cc0e54f1832e8: deterministic manufacturing, Frozen Plate core, landing.
- work/drawing-intake-phase1k-cart-checkout fc1315583ce586c136bf5c001b2a76c2a1e798d7: deterministic drawing intake, canonical quote confirmation, cart, recovery, paid-order and shipping repairs.
- work/frozen-plate-staging-integration 863c7ec6a34c8c2a03e0871c56f3fb7e49ac3b9c: completed-order capture, private immutable artifacts, exact-PDF captured email, deliberate approval, sourcing UI.

Integration resolves CI and auth conflicts by retaining both implementations. Recovery supports staging and preview under the same authenticated allowlist gate; production stays excluded. Landing, pricing core and accepted owner quote/cart pages are preserved. Docker supplies local Tesseract and the union of manufacturing/application dependencies.

Automated validation: 501 passed, 5 skipped (private corpus unavailable), two existing framework deprecation warnings. Compile and whitespace checks passed. New webhook integration tests cover direct/two-line orders, committed snapshots including recovery metadata, replay safety, shipping, exact PDF attachment bytes/hash, independent geometry/quantity and capture-only behavior. Existing recovery tests run against preview and staging.

Deployment target ONLY:
- API srv-d9ritcijobas73didpbg, oplates-pricing-api-staging
- UI srv-d9rj427avr4c739dufkg, oplates-customer-ui-staging
- Orders DB oplates_staging_db (existing Render staging DB)
- Supabase staging ixhnanttetuhpzvrnvdc, existing restricted Frozen Plate schema/role/private bucket/signer/server storage binding

Preserve URLs, all existing credentials, bindings and authenticated sessions. Enable drawing intake only for the existing owner allowlist; retain owner acceptance checkout gate disabled. No new paid transaction is required to reproduce accepted checkout tests. Runtime verification uses synthetic staging fixtures and capture-only email. No production or supplier actions.

Rollback: prior Phase 5 commit 863c7ec and Python runtime commands recorded in the reconciliation report. Owner-acceptance services/branch/DB remain unchanged for comparison. Production cutover requires separate owner authorization after integrated staging acceptance.
