# Production wiring rollout

Owner approved existing-service rollout on October 6, 2026, and explicitly froze
the accepted UI. This candidate changes environment wiring and backend delivery,
not the configurator, pricing, layout or approved copy.

## Exact production targets

| Function | Service | ID | Public address |
| --- | --- | --- | --- |
| API | orifice-pricing-api | srv-d51l6ch5pdvs73ealnh0 | https://orifice-pricing-api.onrender.com |
| Unified UI | orifice-pricing-engine | srv-d530k8re5dus73ahqr0g | https://quote.o-plates.com |
| Landing | landing page | srv-d5eqjn6r433s738u2jn0 | Existing o-plates.com landing service |

The quote domain actually belongs to orifice-pricing-engine. Do not move its DNS
to the older customer-portal service. The accepted UI must start app.py on this
existing service. Other legacy UI services are not independently upgraded.

All production targets currently use main with automatic deployment disabled.
API and quote UI currently run native Python 3.13.4 with requirements.txt;
the tested staging image uses Python 3.12.14 and requirements-frozen-plate.txt.
Install the union of dependencies and pin the reviewed Python runtime before
deployment. The existing production Docker runtime cannot be assumed: its
startup explicitly accepts staging service names only.

Internal drawing intake remains disabled/allowlisted by its existing gates.
The observed native production runtime has no Tesseract. Do not enable intake
until its native OCR dependency is installed and verified. This does not change
manual configuration or deterministic PDF/DXF generation.

## Confirmed data identities

- Render orders: dpg-d56smommcj7s7383tv50-a / orifice_pricing_db. Available;
  22 historical TEST orders and no live orders. Preserve every row.
- Supabase production: kboaovlhilonlymcuqcr, Orifice plate, us-west-2.
  It was paused; the authorized resume succeeded and ACTIVE_HEALTHY was verified.
  Two existing auth users remain. Existing API issuer/JWKS bindings match it.
- Production Frozen Plate schemas/roles/buckets were genuinely absent.
- Supabase staging remains ixhnanttetuhpzvrnvdc, with its existing role/schema,
  bucket/signing/storage credentials preserved.

Production configuration has a TEST Stripe key, no APP_ENV, no separate admin
key, no Frozen Plate database binding and no SendGrid provider key. Presence or
prefix checks never disclose actual secret values.

## Production-only schema and bindings

frozen_plate/schema/production_backend_proposal.sql creates only
frozen_plate_production and frozen_plate_production_api. The restricted role is
NOLOGIN initially; no existing auth, order table or staging objects are replaced.
All eight tables retain immutable record protections and role-scoped RLS. The
backend can select/insert and update only plate current_revision/lifecycle;
anon/authenticated have no access, and the backend has no delete permission.

API backend bindings:

| Setting | Required value/source |
| --- | --- |
| APP_ENV | production |
| APP_BASE_URL | https://quote.o-plates.com |
| FROZEN_PLATE_ENABLED | true after separate production bindings are ready |
| FROZEN_PLATE_LIVE_CHECKOUT_READY | false until all runtime gates pass; true is the final activation |
| FROZEN_PLATE_SUPABASE_URL | https://kboaovlhilonlymcuqcr.supabase.co |
| FROZEN_PLATE_BUCKET | frozen-plate-production, private |
| FROZEN_PLATE_DATABASE_URL | Production restricted role, project session pooler on port 5432, /postgres, sslmode=require |
| FROZEN_PLATE_STORAGE_KEY | Modern production sb_secret credential, backend only |
| FROZEN_PLATE_SIGNING_KEY | New independent strong random production secret, at least 64 characters |
| ADMIN_API_KEY | New dedicated admin credential, separate from API_KEY |
| SENDGRID_API_KEY | Dedicated production order-email credential; Mail Send only |
| FROM_EMAIL | Verified orders@o-plates.com or no-reply@o-plates.com |
| FROZEN_PLATE_EMAIL_MODE | send |
| STRIPE_SECRET_KEY | Restricted LIVE production key: Checkout Sessions Write and Shipping Rates Read |
| STRIPE_WEBHOOK_SECRET | LIVE destination secret for this production API's /stripe/webhook endpoint |
| SUPABASE_JWT_ISSUER / SUPABASE_JWKS_URL | Preserve verified production project identities |
| DATABASE_URL | Preserve existing production Render order DB |

UI receives APP_ENV=production, API_BASE=https://orifice-pricing-api.onrender.com,
FROZEN_PLATE_ENABLED=true, production SUPABASE_URL and a browser-safe modern
production publishable key under the existing SUPABASE_ANON_KEY setting.
Never send the storage/server secret, DB password or signing secret to the UI.

## Secure owner steps

Prepare credentials privately; never paste any value in chat. Saving Render
environment changes can redeploy: first verify the service ID and the reviewed
guarded candidate are deployed. Do not put LIVE credentials into the old API.

1. In the existing production Supabase project, securely enable LOGIN and set
   a new password for frozen_plate_production_api after the additive schema is
   applied. Use that restricted role's session-pooler connection, never postgres.
2. Create/select the modern production server secret and modern publishable key.
   The server secret belongs only in the API's FROZEN_PLATE_STORAGE_KEY.
3. Generate separate production signing and admin secrets privately. Configure
   only the API backend, not source, reports, client settings or environment groups.
4. In the existing SendGrid account, prepare a distinct production order-email
   key restricted to Mail Send. Confirm verified sender and continued availability
   beyond the displayed October 9 trial end. Do not silently change billing.
5. In the correct Stripe LIVE account, prepare the restricted live key and LIVE
   webhook destination for https://orifice-pricing-api.onrender.com/stripe/webhook,
   selecting checkout.session.completed and checkout.session.async_payment_succeeded.
   Preserve the existing staging TEST key and webhook.
6. Enter values through protected provider/Render fields when the guarded
   deployment is ready. No secret is requested as a chat message or file.

Confirm rotation of the specific historical exposed standard TEST key separately;
do not repeat completed legacy Supabase invalidation or rotate the working
restricted staging key unnecessarily.

## Activation sequence and verification

1. Review/test wiring candidate and run CI. Verify it on the existing staging
   services with capture mode unchanged and all backend checks passing.
2. Preserve production rollback references and existing bindings privately.
3. Apply the reviewed additive production schema, configure the restricted
   identity and private bucket, and complete separate backend bindings.
4. Deploy the candidate API with live checkout activation false. Deploy the
   accepted app.py UI on the existing quote service, then landing assets.
5. Run python -m frozen_plate.verify_production. Every required boolean must
   actually be true; the command must exit zero. It makes no payment, email,
   customer approval or vendor call. DB write proof is rolled back and its
   clearly marked storage test object is deleted.
6. Verify production auth/session persistence, ownership restrictions, order
   history, API_BASE, payment return URLs and actual LIVE webhook configuration.
   Presence of a webhook secret alone does not prove it belongs to LIVE mode.
7. Activate FROZEN_PLATE_LIVE_CHECKOUT_READY only after all prerequisites pass.
   No live charge or unsolicited customer email is used as a verification probe.

Production rejects TEST events/sessions and cannot create a live Checkout session
with only a live key and incomplete confirmation wiring. Historical TEST orders
are preserved but cannot be replayed into production drawing/email generation.

## Email operation and limits

Completed order -> immutable revision/PDF/DXF/JSON -> exact captured PDF email
-> durable atomic claim -> provider submission. The captured PDF/spec/current
revision/customer/token are reverified before sending. Each line has its own
revision email; any HOLD prevents partially confirming an order.

accepted.json records provider acceptance, not inbox delivery. Claimed attempts
without acceptance require reconciliation. They are not automatically resent,
including network timeout, provider rejection or acceptance-journal failure.
Use the authenticated GET /admin/frozen-plates/revisions/{revision_id}/email-status
endpoint to distinguish NOT_ATTEMPTED, PROVIDER_ACCEPTED and
RECONCILIATION_REQUIRED. Operator recovery after a proven failed send is a separate
deliberate action; never delete claims and blindly rerun.

Admin retry-completion uses the same delivery safeguards. Normal staging remains
capture-only. The pinned owner-test CLI is not repurposed for customer sending.
GET/HEAD never approve; DXF/JSON remain private and vendor routing remains local.

## Rollback anchors

API: f0a72168d1fd04f6d83421701dcb27620e1010fc, dep-d9qcf4p5efls73f6maug.
Quote UI: record its actual latest live deployment before changing it.
Landing: 9b648d93486a925d8b8ecab063b16e98d5cda4f6, dep-data092d0e5s73aahfo0.
Keep main and production auto-deploy disabled until the deliberate cutover.
Rollback traffic/code/start commands; retain additive schema and immutable
production records. A rollback cannot recall email, payment or approval.

No production application deploy, live charge, customer email, vendor quote,
vendor submission, manufacturing release, Fusion or runtime LLM generation is
performed while preparing this candidate.
