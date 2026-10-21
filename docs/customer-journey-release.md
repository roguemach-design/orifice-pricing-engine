# Customer Journey — soft-launch release candidate

This feature adds owner-only Customer Journey reporting to Manufacturing Control. It is independent of packaging DXF work. Production collection is disabled by default. The owner has authorized a focused production release, conditional on staging acceptance, durable restricted storage, privacy checks and regression verification. A failed mandatory gate keeps collection disabled.

## Behavior and interpretation

- Stage reaches: landing, configurator, valid configuration, quote displayed, cart, PDF quote requested, checkout attempted, and server-confirmed paid order. Cart/PDF are optional branches; direct entry can skip landing. These are not a forced linear conversion rate.
- Date filters: 24 hours, 7 days, 30 days, 90 days. Short windows count distinct observed sessions. Long windows sum UTC session-days from daily aggregates, explicitly labeled; they are not unique visitors.
- Error observations include safe category, frequency, affected anonymous sessions and source. The latest 100 diagnostic sessions show coarse timelines and last successful step.
- Possible abandonment is an inference after 30 minutes inactive with no remaining observed blocker. Missing telemetry, consent refusal, browser blocking and outages are unknown. Invalid input, unsupported configurations, API failures, technical failures and intentional restrictions remain separate. Checkout CLOSED is an intentional restriction.
- Only a committed, verified backend payment transition can populate paid order. Anonymous client observations are untrusted and never prove payment or drawing approval. A checkout-to-session association must already exist; unlinked/historical orders are not reconstructed. Analytics never approves or releases manufacturing.

## Data and privacy

Event schema v1 allows only an event UUID, timestamp, coarse step, outcome, error category and source, associated with a server-issued random anonymous session. No field values, dimensions, names, emails, user IDs, payment details, drawing contents, uploaded files, private URLs, approval tokens, keystrokes, heatmaps or replay are accepted. Checkout linkage stores a purpose-specific HMAC, never the raw payment-session reference. No third-party tracking service is introduced.

Collection requires explicit optional opt-in. Declining does not block quoting/purchasing. Global Privacy Control and Do Not Track disable collection. Versioned disclosures ship before collection can be enabled. Browser preferences expire after 30 days; anonymous session tokens expire within 24 hours and rotate after 30 minutes inactive. Secure SameSite first-party cookies support direct cross-subdomain continuity; embedded handoff verifies exact origins, source window and a per-frame nonce. Tokens authorize analytics only, never account/order access. Requests omit account credentials and referrers. Withdrawal stops collection and requests removal of the current session; failure to confirm a deletion does not resume collection.

Diagnostic/session/linkage records expire from reports after 7 days and are physically removed by hourly cleanup; service outages can delay physical removal. Anonymous daily aggregates retain 90 UTC calendar days. Cleanup remains enabled when collection is disabled. Reporting uses existing owner authorization, no shared data cache, no public report endpoint and no identity-to-session lookup. Owner Lock clears the UI state.

Internal/staging traffic is excluded from customer totals. Staging always forces internal status. Owner-test checkout associations and verified owner-test UI sessions promote the entire retained session to internal and correct its prior daily counts. A deliberate internal-test checkbox supports manual QA. Unidentified internal visitors cannot be inferred from an anonymous session; operators must mark test traffic before starting or decline collection.

## Reliability and limits

Analytics uses bounded separate request workers and a non-blocking 256-item server observation queue. No analytics failure may change a quote, checkout result or payment outcome. Best-effort observations can be lost; the owner report exposes process-local server queue/storage failures. This is diagnostic coverage, not accounting reconciliation.

Limits: 2 KB event requests, 3-second body timeout, 300 requests/minute/process, 60 new sessions/minute/process, 30 events/minute/session, 100 events/session, 3,000 new sessions/day and 30,000 events/day. Browser rerender duplicates and server payment replays are suppressed. The existing single-instance API is the reviewed deployment shape; multi-instance scaling requires shared/global admission control and transaction review. Anonymous telemetry cannot be made immune to deliberate fabrication; its counts are not transaction proof.

## Staging

Use the isolated feature branch for existing staging API/UI/static services only. Do not merge the production integration branch as a shortcut to staging. Static staging uses `python journey/stage_static.py` to bind its existing staging UI/API; the committed production static config stays disabled. The staging customer service exposes `/JourneyOwner` only in non-production when journey UI is enabled; the existing owner unlock remains mandatory. Production owner navigation lives in the existing dedicated owner application.

Staging analytics can use a dedicated disposable SQLite file outside application/order storage. It is explicitly non-durable across deploys; production approval requires persistent Postgres storage. Synthetic fixtures and staging traffic must never be labeled as historical customer activity. Live staging checks must not initiate payment, approve drawings or release manufacturing.

## Production release gates

1. Owner reviews the staged report, consent control, amended Privacy Policy, category meanings and retention policy. Confirm applicability of consent/disclosures for the intended audience before collection.
2. Approve a durable analytics database binding and least-privilege access to only the new `journey_*_v1` tables. No existing order, pricing or Frozen Plate schema is changed by analytics. Verify restore, capacity and retention operation against the persistent database.
3. Approve the exact tested source SHA and deploy sequence: disclose first; API/reporting with collection off; customer UI/owner UI with collection off; verify; explicitly enable collection last. Static production activation requires an explicit reviewed config change, never the staging build command.
4. Enable API collection with `JOURNEY_ENABLED=true` and the matching `JOURNEY_DISCLOSURE_VERSION=journey-2026-10-v1`; keep `JOURNEY_STORAGE_ENABLED=true` for ongoing retention. Bind `JOURNEY_DATABASE_URL` through protected configuration. Production never falls back to business-owner credentials or creates tables at runtime. Use a dedicated DML-only login for the five analytics tables; no access to business tables or schema creation. Pooling is capped at two connections with no overflow. The operator-only `journey.provision` module prepares transactional DDL and rejects broad inherited access; CI verifies privileges, persistence, retention and rollback compatibility against disposable PostgreSQL. A dedicated `JOURNEY_SIGNING_KEY` is supported; otherwise a purpose-derived existing admin secret signs analytics-only tokens. Never put secret values in source or reports.
5. Customer collection uses `JOURNEY_UI_ENABLED=true` and the approved `JOURNEY_PUBLIC_API`; no Stripe, payment-mode, checkout-state, pricing, geometry, Frozen Plate, artifact, email or manufacturing settings are changed. Reverify public flows, refusal/withdrawal and internal test exclusion.

Rollback: disable client collection and `JOURNEY_ENABLED`, retaining storage cleanup. Revert application deploys if needed; analytics tables are isolated and ignored by prior application versions. No order/artifact restoration or payment operation is part of rollback. Owner authorization remains required for production deployment and collection activation.

## Current reconciliation

The candidate incorporates accepted production UI changes through `3c202c7d5a6cfddfc62421690c236a9a88d0cedd`, including current SVG, field validation and ghosted lead-time controls. Protected pricing, manufacturing, Frozen Plate, packaging and Haas files are unchanged relative to that production source. No historical event reconstruction is included.

Withdrawal remains available while collection is disabled, provided retention storage remains bound. Turning collection off is the first rollback action. Previous application builds ignore the isolated analytics tables; rollback does not drop tables, modify business evidence or reverse orders. Staging uses its existing disposable database until authenticated durable-storage acceptance is possible.
