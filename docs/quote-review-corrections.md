# Owner-authorized quote review corrections

Phase 1 is normal PR #41, based on `work/final-integration-production-cutover`, head `2472c33e954ca19bd2b02218ac1001d125598994`. Phase 2 targets `work/quote-phase1-rev2` and must remain DRAFT. No merge or deployment is authorized.

## Presentation and test coverage

The two historical PDF tests retain their original quantities, unit and extended amounts, lead times, November 18 validity, shipping/tax semantics and exclusion of internal copy. They additionally assert the complete original customer specifications, new legal address and quote number. The fixture now uses an explicit New York business date; a separate timezone-boundary regression remains. See the assertion mapping in `quote-phase1-review.md`.

Phase 2 reduces only vertical spacing in the ordering/terms panels. Font size and complete specifications are retained. Eight regression cases cover ordinary A1/B5 plates with standard customer details, initial/R2 numbering and ordering links disabled/enabled; all fit on one page. Optional features explicitly display None. The long-marking and 1/6/25/60-line coverage remains.

Future printed links display `quote.o-plates.com/My_Quotes` and an unbroken full quote number, without `https://`. The actual annotation and email link retain the implemented `/My_Quotes?quote=Q-...` route and full quote number. A new `/quotes/Q-...` alias would need routing outside the existing Streamlit app, so no speculative alias is printed. The route preserves sign-in intent and every quote request enforces server authorization. The link demonstration is synthetic and clearly marked; the route is not claimed to be production accepted. `SAVED_QUOTES_LIVE` remains off until the real production route passes acceptance.

Corrected A, B and both R2 renderings were visually inspected. A and both one-plate R2 variants are one page; B is two pages; the 25/60-line specimens are 6/13 pages. The panels stay above the footer and specification continuations are retained.

## Checkout review

`api_app.py` retains the direct single-plate implementation. The cart adds an optional saved-quote branch and a request-local context carrying verified buyer email, saved quote ID and stable expiration. Ordinary carts enter the original path. Existing single/cart identity and idempotency tests now run with the feature both off and on.

The existing webhook retains its signed-event, payment-status, environment and server-owned customer checks. Saved-quote completion validates the reserved buyer and order, sets the quote association and uses the verified purchaser email. The original Frozen Plate completion then runs with that purchaser. A duplicate completion regression asserts one order, one quote order event and the same purchasing email. Tests deny the engineer access to the buyer's order and drawing approval. No payment method, Stripe SDK, credential, LIVE activation, shipping, pricing or manufacturing workflow migration is included.

Local correction regression: 184 passed, followed by 8 passed for flag-off/flag-on single/cart checkout and UI. These runs overlap. Provider responses are mocked, not real payment evidence.

## Manufacturing scope reconciliation

All **51** protected regenerated output SHA-256 values match `review/drawing-v6/exact-output-baseline.json`, covering standard/long/hole/chamfer geometry packages, packaging and Haas outputs. Separately, all **42** tracked historical artifact Git blob hashes match production baseline `45ee4dc58ac9c2556a1b891c30512fa1eb28fe04`. The counts describe different scopes and hash algorithms; no nine artifacts were dropped. Per-entry expected/actual values are in `review/quote-phase2/manufacturing-baseline-reconciliation.json`.

## Acceptance evidence and remaining gates

GitHub CI runs the full test suite, compile check, existing configurator browser smoke and the added saved-quote browser journey. Disposable PostgreSQL verifies two competing authenticated principals, one checkout/order, repeatable guards, immutable snapshots/audit events, RLS and denied anon/authenticated direct table reads. Browser fixtures capture account, number lookup, actual captured email return URL, invitation acceptance, wrong/expired/revoked access denial and cart handoff. These fixtures explicitly simulate identity and never inherit provider credentials or send mail.

Actual staged Supabase login and invitation identity, TEST Stripe payment/webhook delivery, staged Frozen Plate approval binding, provider email acceptance/delivery and production-route acceptance remain separate release gates. The connected Stripe session exposes only the LIVE Rogue Machine account, so no TEST payment was attempted through it. The O-Plates Staging Supabase project is active, but that alone is not authentication acceptance. SendGrid billing evidence includes a recent successful payment; current sending authorization, sender verification, API mail-send permission and account restrictions remain unverified because its dashboard requires sign-in. No trial/billing state is assumed.

All production flags remain unchanged/off for saved quotes. No production database migration, deployment, merge, real payment or customer mail occurred. Phase 2 remains draft until the outstanding integration gates are completed and reviewed; PDF links additionally require production acceptance and established owner release approval.
