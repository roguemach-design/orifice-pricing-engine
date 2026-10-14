# Phase C: owner sandbox on the production application

The production customer workflow supports an explicit `owner_test` Checkout mode.
It uses the existing verified Supabase bearer identity and internal owner allowlist.
An API key or browser identity hint alone cannot authorize a test purchase.

## Server and UI gate

Set `OPLATES_OWNER_TEST_CHECKOUT_ENABLED=true` on both production services only
after the credential, webhook and public-ingress checks below pass. The API also
requires the existing `OPLATES_DRAWING_ASSISTED_ENABLED` capability and membership
in `OPLATES_DRAWING_ASSISTED_ALLOWED_USER_IDS`. These existing owner controls are
reused; the allowlist is not changed by this implementation.

The UI verifies `/internal/owner-test/access` and sends
`x-oplates-checkout-mode: owner_test`. Both direct and cart Checkout independently
enforce this mode on the server. Normal production Checkout still uses the
existing LIVE-only guard and `FROZEN_PLATE_LIVE_CHECKOUT_READY`; keep that flag
`false`. The owner path cannot fall through to LIVE Stripe.

## Separate credentials and webhook

On the **existing production API** add:

- `STRIPE_TEST_SECRET_KEY`: the sandbox restricted/secret key, beginning with
  `rk_test_` or `sk_test_`; permissions must support Checkout session creation and
  retrieval and ShippingRate retrieval.
- `STRIPE_TEST_WEBHOOK_SECRET`: the signing secret for the sandbox destination
  described below. It must differ from `STRIPE_WEBHOOK_SECRET`.

Leave `STRIPE_SECRET_KEY` and `STRIPE_WEBHOOK_SECRET` untouched. No key is stored
in source or sent to the customer browser. Sandbox Stripe API calls pass the
TEST key per request; they never mutate Stripe's global LIVE credential.

Sandbox destination:
`https://orifice-pricing-api.onrender.com/stripe/test/webhook`

Subscribe to `checkout.session.completed` and
`checkout.session.async_payment_succeeded`. This destination requires a valid
TEST signature, `livemode=false`, an authoritative TEST Checkout session, the
server-generated Stripe owner-test metadata, and the matching pending order's
immutable TEST marker and owner identity. It reuses order-completion locking,
event uniqueness, Frozen Plate generation, exact artifacts, hashes, private
storage and production confirmation delivery. Existing LIVE verification is
unchanged. Signed retries can complete an already-created TEST purchase even
after the new-purchase gate is switched off.

## Public ingress prerequisite

Render maintenance on the production API blocks the public Stripe destination
and the existing confirmation links at `/approve/...`. The customer UI can still
reach the API privately, so owner-portal success does not establish webhook or
email-link reachability. Resolve public ingress before enabling the owner gate.
Do not enable checkout merely because separate secret names have been saved.

## TEST identity and non-release

The server adds `quote_payload._payment = {mode: owner_test, owner_id: ...}`.
Owner order responses and portal selectors label these orders `OWNER TEST`.
Geometry, manufacturing specifications and artifact generators are unchanged.
The production snapshot loader admits only marked, customer-bound TEST orders;
unmarked TEST sessions remain excluded. Approval remains deliberate and bound to
the exact immutable PDF/revision. The portal continues to offer review/downloads
only. No vendor or manufacturing integration is invoked.

## Activation and first owner buy

During the temporary live-site validation window, set
`OPLATES_STRIPE_TEST_VALIDATION_WINDOW=true` on the production API. This explicitly
blocks the normal production checkout path and session factory even if
`FROZEN_PLATE_LIVE_CHECKOUT_READY` is accidentally enabled. The existing verified
owner checkout uses the separate TEST credentials and retains its authorization.

1. Deploy the accepted Phase C commit to the existing production API and UI.
   Keep the owner gate off until checks pass; use the exact commit rather than
   each service's older configured source branch.
2. Bind the separate TEST credential and matching sandbox destination secret.
   Verify public webhook and approval ingress while retaining application
   authentication, signature verification, public-checkout closure and LIVE
   activation controls.
3. Verify unauthorized, customer and flag-off rejection on the deployed API;
   verify TEST signature isolation and the authenticated owner capability.
4. Enable the owner flag on both existing production services. Verify deployed
   commit IDs, the allowlisted owner's capability and closed public checkout.
5. The owner performs the first browser sandbox purchase on `quote.o-plates.com`,
   reviews the success return and exact confirmation PDF, deliberately approves,
   and inspects the TEST order in `/Internal_Sourcing`. No automated purchase is
   performed by this rollout.

Rollback closes the owner flag on both production services; existing signed
completion retries remain valid for already-created marked TEST orders.
