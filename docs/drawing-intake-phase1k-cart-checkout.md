# Phase 1K: owner-test cart and checkout handoff

Phase 1J recognition optimization is deferred. This branch changes no recognition,
pricing formula, checkout API, payment implementation, or order schema.

## Existing paths

The manual Quote page sends canonical `QuoteInputs` to `POST /quote`. Its response
includes a fresh `configuration_id`, normalized configuration, pricing version,
validation result, unit and total prices, and shipping estimates. The displayed
price is not a durable price lock: `/quote` says it is **revalidated at checkout**.
There is no fixed API quote expiration. The Quote Cart has a browser-session list
of line snapshots, a separate PDF quote identifier with 30-day PDF validity, and
reprices each line with `POST /quote` on render. The PDF validity is not a checkout
price guarantee. Cart checkout sends only the canonical item inputs, current
pricing version, and an idempotency key to `POST /checkout/cart/create`.

The API validates each `QuoteRequest` as `QuoteInputs`, recalculates each line from
the active price configuration, and rejects a changed pricing version with 409
before creating Stripe Checkout. Single-item `POST /checkout/create` follows the
same validation and repricing. An authenticated bearer identity links pending
orders to a Supabase user; the existing single-item path permits guest checkout
with the UI API key. Quote Cart requires login. The API stores the canonical
payload on the pending order, then a signed paid Stripe webhook completes it
under a database lock. Replays do not create another completed order or resend
the confirmation email. Success and My Orders read the same order endpoints.
Stripe's cancellation URL returns to the form/cart with its session state; no
post-purchase return/refund workflow is implemented here.

## Drawing handoff

The existing Phase 1I `confirmed_drawing_quote_inputs` gate requires an explicit
quote-specific selection, complete and valid canonical values, and a current
purchaser confirmation. Phase 1K additionally compares those inputs with the
successful API quote's normalized configuration and validation status. The
current UI request and its response must agree before direct checkout or cart
addition. Recognition evidence, raw drawings, filenames, and confirmation
metadata are never sent to `/checkout/*` or Stripe.

The cart stores a separate canonical input snapshot per line. Its `assisted_quote`
flag and original quote identity are browser-session metadata only. Editing the
original Quote form does not mutate a cart line. Quantity edits on an assisted
line are disabled in the cart; remove and reconfigure the plate to obtain a new
confirmation. Manual cart quantities retain their existing editable behavior.
The cart still reprices every line and checkout independently recalculates every
item. Choosing “Add another plate” after an assisted line resets the editor but
keeps existing cart snapshots. A multi-plate drawing still requires an explicit
region selection before any assisted quote can pass the handoff gate.

The Quote page's direct single-plate checkout and add-to-cart actions, as well as
the Cart page checkout action, remain disabled in owner mode unless
`OPLATES_OWNER_TEST_CHECKOUT_ENABLED=true` **and** the existing API JWT/allowlist
gate confirms the account. The switch is disabled by default. Outside owner mode,
the established manual buttons remain unchanged; a stale drawing session cannot
enable checkout there. Customer confirmation is a UI gating requirement; the
server independently validates and reprices canonical manufacturing inputs.

## Deployment gate

Before enabling owner TEST checkout in the isolated services, verify without
revealing secrets that the isolated API uses `APP_ENV=test` (or the intended
nonproduction environment), a Stripe TEST key, a TEST webhook secret, the
isolated HTTPS `APP_BASE_URL`, and an isolated order database. The API already
fails closed for live Stripe keys in test/staging/preview. Verify the owner
allowlist and feature flags. Keep the new UI switch off if any of these cannot
be established. No API deployment is needed for this code path.

The local tests use mocked Stripe TEST sessions and a disposable database for
pending/completed order, My Orders, webhook replay, two independent cart lines,
and corrected OD propagation. They do not represent a real Stripe TEST payment
in the deployed owner environment. That hands-on test requires a separately
approved UI deployment and confirmation of the isolated payment configuration.
