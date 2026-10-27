# Manufacturing Control checkout mode

This release adds CLOSED / TEST / LIVE to the existing owner portal and checkout workflow. The backend reads a singleton in the private `checkout_control` PostgreSQL schema using the existing restricted Frozen Plate database identity. All customer surfaces ask the API. Browser mode headers are compatibility input and never grant access. LIVE activation is deliberately unavailable in this release.

## Controls

Unlock Manufacturing Control with its existing owner credential. Open **Checkout Control**. Read the effective mode and exact readiness blockers. Select CLOSED or TEST, type `APPLY CLOSED` or `APPLY TEST`, then **Save / Apply**. The displayed effective mode comes from a fresh server response. To close immediately, confirm the close checkbox and press **Close New Checkout**. A stale version is rejected; refresh before retrying. Closing stops new Stripe sessions while preserving carts, existing orders, signed webhooks and drawing approvals.

TEST requires an authenticated customer ID in both the existing server allowlist and the private verified-email registry. A registered, enabled tester alone does not override the existing hard environment permissions. Confirmation mail is pinned to the server-owned verified recipient captured at checkout creation; Stripe-entered contact email cannot redirect it. TEST session IDs and livemode are checked. TEST webhooks use their independent signing secret and cannot complete LIVE orders. Closing does not gate completion of already-created sessions.

New TEST order snapshots carry payment provenance into their immutable Frozen Plate source. The exact PDF remains unchanged. Confirmation email, customer success and drawing approval carry TEST / NOT A REAL SALE labeling. TEST parents cannot be sourced or used for automatic/manual manufacturing output. TEST records remain reviewable in Orders and Frozen Plates but are excluded from LIVE sales and manufacturing summary totals.

## Safe rollout

1. Verify exact production branch/deploy SHAs. Keep Quote #41/#42 separate.
2. Run full CI, actual PostgreSQL concurrency/privilege checks, protected artifact comparisons and the existing browser smoke suite.
3. Apply the additive SQL in `migrations/checkout_control.sql` to the existing production Supabase project as migration owner. It starts CLOSED, grants only backend read, mode-column update and audit insert, and grants no customer access. RLS is enabled. The runtime role cannot change tester registrations, overwrite audit entries, or attest sandbox binding verification.
4. Register only an explicitly approved tester whose production Supabase email is confirmed. Record that confirmed address, customer ID and verification timestamp; do not copy unconfirmed/user-editable metadata.
5. Verify the existing provider bindings: a real TEST key, corresponding TEST webhook destination/signature, authenticated identity, order persistence, Frozen Plate private storage and exact-PDF delivery, approved email sender and recipient. Record the evidence before the migration owner sets `test_binding_verified_at`. This timestamp represents verified sandbox bindings, not a claim that the end-to-end production test has passed. Never set it merely from key prefixes.
6. Deploy the focused API first, then the customer UI and Manufacturing Control. Static landing does not change. Keep CLOSED until safety/staging checks pass. Use supervised TEST to run the actual single-plate and two-plate purchases through direct and embedded production routes. Check payment=false/livemode=false, webhook replay, email arrival, exact PDF hash, authenticated approval, empty LIVE revenue/fulfillment impact, close/reopen behavior and persistence after a restart. Close immediately on failure. Leave TEST only after all owner acceptance checks pass.

The legacy Stripe global key is preserved to avoid rebuilding or upgrading the accepted integration. Existing TEST calls always pass the separate TEST credential explicitly; no live credential or webhook secret is edited or returned by this feature.

## Rollback

First apply CLOSED and verify its effective state. Prefer reverting the customer and owner UI while retaining the mode-aware API. Leave the additive database schema/audit in place; do not delete paid or test orders, approvals or artifacts.

An API rollback to pre-selector code is **not** controlled by this new database setting. Before that rollback, verify both old hard purchasing permissions are disabled (`OPLATES_OWNER_TEST_CHECKOUT_ENABLED=false`, `FROZEN_PLATE_LIVE_CHECKOUT_READY=false`) and preserve the validation window. Verify the old API blocks owner TEST and LIVE session creation after deployment. Preserve all credential values and in-flight webhook paths. Do not rely on a Render rollback to reverse database state.

## Evidence limits

Automated fixtures simulate identity/provider responses and email transport. Their passing status does not prove Stripe account permissions, a production webhook delivery, SendGrid sender eligibility or inbox arrival. The real browser acceptance record must explicitly identify the TEST sessions, persisted orders/revisions, exact attachment hashes and received mail before final TEST activation is reported.

## Quote PR compatibility

Read-only merge-tree checks against the published Quote heads: Phase 1 #41 merges cleanly. Phase 2 #42 has one content conflict in `api_app.py` where both branches extend checkout. Reconcile by retaining the database mode gate, TEST recipient metadata and per-session lock around the existing Stripe call, then retaining Phase 2 saved-quote persistence after the pending order is stored. Do not restore header/environment authority during that merge. Neither Quote branch was modified.

Pre-selector compatibility: already-created owner TEST sessions without a recipient marker resolve only through the verified registry. Existing frozen sources are reused only when their full legacy source hash still matches exactly; no historical revision or artifact is rewritten. New TEST source provenance continues to block sourcing and manufacturing output.
