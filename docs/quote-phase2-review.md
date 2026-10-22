# Saved quotes and purchasing handoff — revision 2

Status: owner authorized publication as a DRAFT PR, based on `work/quote-phase1-rev2`. No release, deployment or production migration is authorized. Current correction evidence and remaining provider gates are in `quote-review-corrections.md`.

## Scope and implementation

The existing Quote Cart is reused. `/checkout/cart/create` accepts a saved quote/review reference, verifies the current purchasing identity, locks the saved quote, checks its server-owned configurations and review, then invokes the existing checkout implementation. Pricing still uses `_calculate_quote_with_db_knobs`, the same authority used by `/quote` and checkout. Shipping selection remains in the existing Stripe Checkout. No second cart, checkout or purchasing portal was created.

The existing customer application gains `/My_Quotes` and a My Quotes account navigation link. It supports saved PDFs, number lookup, expiry, revision creation, invitations and revocation, current-price review, and direct restoration into the existing cart. Find-by-number intent survives sign-in. A shared quote copied for editing becomes a new quote owned by that buyer; it never changes the original owner's record.

New private tables in the existing order database: `saved_quotes`, `quote_shares`, `quote_events`, `quote_reviews`, `quote_mail`. Saved quotes contain canonical line payloads, authoritative priced snapshots, immutable PDF bytes and SHA-256, numbering/revision lineage, ownership, and separate lifecycle/checkout state. No existing orders or artifacts are migrated or rewritten.

The new PostgreSQL trigger rejects direct changes to immutable snapshot fields or deletion; audit events are append-only. The five new tables enable row security with no browser policies and revoke PUBLIC/anon/authenticated grants, so records are served only by the existing server-owned API connection. The API database role must own these new tables; no browser or service credentials are changed. PostgreSQL's default-deny policy and owner semantics are documented at https://www.postgresql.org/docs/current/ddl-rowsecurity.html. Application guards protect snapshots in local tests too. Share tokens are random, hashed, single-use, expiring and exact-email-bound. Supabase's existing JWT verification plus a fresh `get_user` check supplies the verified buyer; browser emails and user metadata do not authorize access. The auth configuration uses existing publishable configuration and does not require Stripe credential changes.

A checkout reservation is committed before external I/O. Ambiguous retries use the same buyer, reviewed snapshot, email, expiration and Stripe idempotency key; a delayed-retry test compares every submitted Stripe parameter. Competing buyers are rejected. Canceling a retained session or revoking its purchaser first confirms Stripe expiration; paid/uncertain sessions fail closed. A quote expiring in under 31 minutes must be repriced before checkout, and a created Stripe session cannot outlive quote validity. Paid webhooks retain the existing identity guard, mark the saved quote ordered, and continue the unchanged Frozen Plate workflow using the authenticated buyer.

Quote mail attaches the exact saved PDF. An owner can explicitly retry emailing it without reissuing the document. Durable delivery records distinguish pending, sending, provider-accepted, captured, and needs-review. Ambiguous delivery is not automatically resent. Invitations store only the token hash; a failed/uncertain invitation is revoked and replaced rather than silently reused.

## Local evidence

- Full suite snapshot: **1213 passed, 6 skipped**. The skips were the pre-existing private fixture/PostgreSQL-dependent tests.
- Final focused quote/cart/checkout/authentication/sandbox regression: **153 passed, 1 skipped**; the new PostgreSQL gate was skipped because no disposable database was available.
- Subsequent final PDF-link, mail, saved-quote and Streamlit UI delta: **34 passed**.
- Final delayed-payment-retry, saved-quote, checkout, PDF and Streamlit UI regression: **101 passed**. These runs overlap; do not add the counts together.
- **42 historical tracked manufacturing/review artifacts** matched the baseline Git object hashes exactly. `review/quote-phase2/historical-artifact-check.json` contains each path and digest.
- Synthetic mocked-provider completion verified invited buyer → existing checkout → paid order → Frozen Plate → drawing approval. The quote owner could not view the purchaser's order or approve the purchaser's drawing. These were local tests, NOT a real Stripe payment or production acceptance.
- Quote number/PDF hash stability, R2/R3, immutable original, unknown/unowned/expired/revoked denial equivalence, wrong-email and replay rejection, price and lead-time acknowledgement, stale-review and payload-tamper rejection, duplicate checkout, failure/retry idempotency, share revocation, expiration and Update Pricing are covered.
- Real Streamlit AppTest exercised account retrieval, sharing, review acknowledgement, source-config preservation in the existing cart, purchaser restrictions, expiry and signed-out number retention.
- A/B rendered comparisons plus 1/6/25/60-line PDFs are available. The 25-line test is 6 pages; 60 lines is 13 pages. R2 documents demonstrate default-disabled ordering copy and the future enabled rendering separately. `scripts/review_saved_quote_pdf.py` reproduces the R2 specimens without changing any feature flag. Their latest rendered pages and clickable annotations were inspected.

## Outstanding gates — do not treat as completed

1. Publish Phase 2 as draft; Phase 1 is published as PR #41. Record exact head CI in the PRs.
2. Run the existing GitHub CI, including `tests/test_saved_quotes_postgres.py`. It uses the existing disposable CI PostgreSQL service, checks two competing buyers, SQL snapshot protection, and persistence across connections. The container could not install/start PostgreSQL; SQLite tests do not prove row-lock behavior.
3. Run `tests/saved_quotes_browser.py` for desktop/mobile account, retrieval, purchasing and existing-cart screenshots. The connected cloud browser cannot reach the local server, and the local Chromium download failed. No fabricated screenshots are supplied. The new CI step retains its screenshots with the existing browser artifacts.
4. Verify staged actual Supabase identities, captured quote/invitation emails, delivery configuration, cancellation and existing TEST checkout/Frozen Plate approval end to end. No external mail or real payment occurred during this work.
5. Obtain established owner production release approval; run production acceptance before enabling PDF ordering links.

## Configuration and sequencing

All defaults remain closed. No environment was changed remotely.

- `SAVED_QUOTES_ENABLED=true` on the API and existing customer UI enables the feature after approval. It does not change any existing checkout activation gate.
- `SAVED_QUOTES_EMAIL_MODE=capture` is the default. Only the exact value `sendgrid` sends through the existing SendGrid account; unknown modes fail closed. Validate attachment, sender, reply address and delivery before enabling send mode.
- API verification requires its existing `SUPABASE_URL` (or JWT issuer) and `SUPABASE_PUBLISHABLE_KEY` (or the existing publishable-compatible `SUPABASE_ANON_KEY` name). No secrets are in this repository. Confirm availability during staging; no credentials were changed here.
- `APP_BASE_URL` must be the existing customer UI's trusted HTTPS origin. Links use the real implemented `/My_Quotes?quote=Q-…` route. Quote numbers/forwarded URLs grant no access.
- `SAVED_QUOTES_LIVE` defaults off. Keep it off through staging and production acceptance. Enable only after the owner release gate and production acceptance, for newly saved PDFs. Previously saved PDFs never change when this flag changes.

## Rollback

Disable `SAVED_QUOTES_ENABLED` on API/UI and keep `SAVED_QUOTES_LIVE` off. This closes quote actions and hides navigation while the existing cart and checkout keep their original behavior. Keep the additive webhook association code running until all existing quote checkouts settle or are explicitly expired. Preserve all new quote tables, PDFs, events, orders and manufacturing artifacts. Do not drop records or roll back immutable history. Before rolling application code back to Phase 1, verify no unresolved quote checkouts; before re-enabling, reconcile completed orders against their saved-quote associations.

An ambiguous checkout without a returned session stays reserved for its original review. It requires reconciliation if the review expires; the app does not create another payment session with new parameters. This is an intentional fail-closed operational condition, and must be exercised during staging.

## Unchanged boundaries

No Stripe key, LIVE activation flag, pricing calculation, handle-hole charge, lead multiplier, shipping calculation, manufacturing geometry, Frozen Plate artifact, existing order, DNS, or production deployment was changed. No marketing campaign was edited or sent.
