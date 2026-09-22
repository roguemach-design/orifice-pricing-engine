# Phase 1H controlled owner acceptance

Phase 1H exposes the accepted drawing-assisted quote form only in an isolated,
authenticated owner-test environment. It does not enable drawing-assisted
pricing, checkout, orders, public uploads, permanent drawing storage, or an
external recognition provider.

## Proposed deployment boundary

The preferred deployment is the two-service Blueprint in
`render.phase1h.yaml`:

- `oplates-owner-acceptance-ui`: public HTTPS Streamlit UI, one 512 MiB
  instance, Docker runtime with local Tesseract.
- `oplates-owner-acceptance-api`: private-network FastAPI service, one 512 MiB
  instance, Docker runtime. It exposes the existing verified internal-access
  gate only to the UI service.

Both services use the Phase 1H branch, have automatic deploys disabled, and
reuse the existing staging Supabase project and staging database/configuration.
No new database is created. The shared customer UI/API staging services and the
landing-page staging service are unchanged.

`OPLATES_OWNER_ACCEPTANCE_MODE=true` disables all checkout buttons in this
isolated UI so an acceptance session cannot create a Stripe session or order.
The flag defaults off and does not change the shared staging or production
manual workflow. Manual configuration, validation, preview, and staging pricing
remain testable in the isolated UI.

Render currently lists the 0.5 CPU / 512 MiB web-service plan at $7 per month.
The isolated pair therefore costs at most $14 per full month plus ordinary
bandwidth and is prorated while running. Source:
<https://render.com/pricing>.

## Required protected configuration

Never put these values in Git, logs, screenshots, or reports:

- UI: staging `SUPABASE_URL` and browser-safe `SUPABASE_ANON_KEY`.
- API: staging `DATABASE_URL`, Stripe test credentials, Supabase JWKS URL and
  issuer, and the approved owner's Supabase user UUID.

The Blueprint generates the UI/API shared API key and admin key. The API
allowlist is `OPLATES_DRAWING_ASSISTED_ALLOWED_USER_IDS`; an empty value fails
closed. Both services must set `OPLATES_DRAWING_ASSISTED_ENABLED=true`.

## Access boundary

The upload controls are rendered only after all three checks pass:

1. The UI feature flag is enabled.
2. The current browser session contains a Supabase access token.
3. The private API verifies the token signature, issuer, audience, expiry, and
   subject, then finds that subject in the server-side allowlist.

Anonymous users and ordinary authenticated users keep the manual quote page but
cannot see or invoke drawing recognition. The UI contains the OCR worker; there
is no public upload API to call around the gate.

## Upload and processing controls

Owner-test limits are intentionally lower than the Phase 1G defaults:

- 10 MiB per file;
- PDF, PNG, or JPEG with matching extension, declared type, and file signature;
- at most five PDF pages;
- at most 12,000 pixels on either image dimension;
- at most 35 million classification pixels;
- 60-second isolated-worker timeout;
- one recognition job per UI process;
- non-root Docker process;
- no persistent upload directory and no drawing-content logging;
- no external document or OCR transmission.

Measured locally on the available corpus, the eight-detail vector PDF peaked at
approximately 108 MiB in the recognition child and the 13-row schedule peaked
at approximately 171 MiB. The latter took approximately 41 seconds to inspect.
This supports one serialized job on the proposed 512 MiB UI, subject to remote
verification.

This is sufficient only for controlled, allowlisted owner acceptance. It is not
a production upload-security claim: there is no malware scanner, no dedicated
worker service, no distributed concurrency queue, and no hardened document
sandbox beyond the container, child process, validation, and timeout.

## Temporary data and retention

Uploaded bytes live in the Streamlit session and short-lived recognition child
process. The integration does not write them to Git, object storage, a database,
or an external provider. They disappear when the session/process is discarded.
Application-platform memory and transient runtime behavior remain subject to
Render's service lifecycle; Phase 1H does not promise secure erasure.

The downloadable acceptance record contains no filename, file hash, OCR text,
source coordinates, dimensions, drawing number, or customer identity. It is
kept only in session memory unless the owner downloads the JSON file.

## Friction measurement definitions

- **Explicit app click:** activation of Analyze, Apply, Confirm, or Reset. The
  OS file-picker interaction and typing are not guessed as clicks.
- **Drawing upload/selection action:** Analyze, an explicit candidate/row
  selection, or Apply.
- **Customer action:** each recorded app click, candidate choice, or changed
  form field.
- **Manual field entry:** one distinct previously blank canonical field filled
  by the owner. Keystrokes are not counted as clicks.
- **Correction:** one distinct drawing-prefilled field changed by the owner.
- **Page transition:** navigation to another application page. The integrated
  quote workflow has zero transitions unless the user leaves it.
- **Processing wait:** measured wall time for document inspection plus selected
  candidate recognition.
- **Elapsed time:** wall time from a validated Analyze action to the current
  downloadable record. This is not time-to-checkout.

## Deployment and rollback

Deployment requires explicit owner approval before the branch is pushed or any
Render resource is created or changed.

After approval:

1. Push only the Phase 1H feature branch and its reviewed commit.
2. Create the isolated Blueprint services with automatic deploys off.
3. Enter protected staging values in Render without exposing them in chat.
4. Verify container Tesseract, both health checks, the active configuration,
   all four access states, and the upload limits.
5. Run desktop and mobile browser acceptance against the verified HTTPS URL.

Rollback is to disable the API and UI feature flags, suspend/delete the two
isolated services, and delete the remote Phase 1H branch if desired. The shared
staging pair remains on its existing branch and commit throughout.
