# O-Plates deployment contract

The customer experience is the Streamlit multipage application rooted at
`app.py`. The canonical service commands are:

- Customer UI: `streamlit run app.py --server.address 0.0.0.0 --server.port $PORT`
- Pricing API: `uvicorn api_app:app --host 0.0.0.0 --port $PORT`
- Admin UI: `streamlit run admin_app.py --server.address 0.0.0.0 --server.port $PORT`

`ui_app.py`, `customer_portal.py`, `quote_cart_app.py`, and
`my_orders_app.py` remain only as compatibility entrypoints. They immediately
route into the canonical multipage application and contain no pricing, auth,
or checkout implementation.

## Customer UI environment

Required:

- `API_BASE`
- `API_KEY`
- `SUPABASE_URL`
- `SUPABASE_ANON_KEY`

Optional session settings:

- `AUTH_COOKIE_NAME`
- `AUTH_COOKIE_TTL_DAYS`

Internal-only drawing-assisted quote acceptance (disabled by default):

- `OPLATES_DRAWING_ASSISTED_ENABLED` — set to `true` on both the customer UI
  and pricing API only for an approved internal environment.
- `OPLATES_DRAWING_ASSISTED_ALLOWED_USER_IDS` — comma-separated Supabase user
  UUIDs, configured on the pricing API. An empty list fails closed.
- `DRAWING_ASSISTED_MAX_FILE_BYTES`, `DRAWING_ASSISTED_MAX_PDF_PAGES`,
  `DRAWING_ASSISTED_MAX_IMAGE_DIMENSION_PX`,
  `DRAWING_ASSISTED_MAX_TOTAL_PIXELS`, and
  `DRAWING_ASSISTED_PROCESSING_TIMEOUT_SECONDS` — optional UI-server resource
  limits. The code defaults to 15 MiB, 10 pages, 16,000 pixels per dimension,
  80 million total pixels, and 90 seconds.

The customer UI must receive an affirmative response from the API's
server-verified `/internal/drawing-intake/access` gate before it displays or
processes a drawing. The API verifies the Supabase JWT and allowlisted user ID.
No drawing bytes are sent to that endpoint, stored persistently, or sent to an
external service.

`SUPABASE_ANON_KEY` is the staging project's browser-safe publishable/anon key.
Never configure a Supabase service-role key in the customer UI service.

## Pricing API environment

Required:

- `APP_ENV` — one of `production`, `staging`, `preview`, or `test`
- `APP_BASE_URL` — the HTTPS customer UI origin for Stripe return URLs
- `DATABASE_URL`
- `API_KEY`
- `ADMIN_API_KEY`
- `STRIPE_SECRET_KEY`
- `STRIPE_WEBHOOK_SECRET`
- `SUPABASE_JWKS_URL`
- `SUPABASE_JWT_ISSUER`
- `SUPABASE_JWT_AUD`

For staging, preview, and test environments, `STRIPE_SECRET_KEY` must be a
Stripe test-mode secret or restricted key. The API rejects live Stripe keys in
those environments. `APP_ENV` and `APP_BASE_URL` intentionally have no
production fallback.

Optional order-confirmation email settings:

- `SENDGRID_API_KEY`
- `FROM_EMAIL`

These API settings are independent from Supabase custom SMTP. Leave them unset
until staging order-confirmation email is intentionally enabled and tested.

## Database compatibility

API startup performs additive, idempotent PostgreSQL changes for the order
lifecycle fields (`status`, `paid_at`, and `last_stripe_event_id`) and their
indexes. It also backfills legacy rows that already have a Stripe payment
intent to `completed`. No column or table is dropped or renamed.

Before the first production deployment, run the same statements against a
production-schema clone or approved backup and confirm the database role can
alter `orders` and create indexes. A migration failure aborts API startup; it
does not run the API against a partially compatible schema.

## Stacked pull requests

The current implementation is intentionally linear:

1. PR #1 — pricing validation and regression guardrails
2. PR #2 — API-authoritative pricing
3. PR #3 — staging SVG preview
4. PR #4 — engineering purchase-workflow UX
5. PR #5 — staging transaction and authentication completion

Merge in that order. Preserve commit ancestry with merge commits, or fully
rebase each remaining branch onto `main` after any squash merge before
retargeting the next PR.
