# Drawing-assisted configurator integration — Phase 1G

Phase 1G integrates the accepted deterministic drawing reader into the real
Streamlit quote page (`pages/1_Quote.py`). It remains disabled by default and
is for internal acceptance only.

## Architecture

The existing customer page remains authoritative:

```text
Upload PDF/PNG/JPEG
  -> server-verified internal access check
  -> in-memory validation and bounded local worker
  -> existing deterministic document/candidate recognition
  -> explicit plate or schedule-row selection when needed
  -> Phase 1F assisted quote session
  -> existing quote-form widget state
  -> existing validation and SVG preview
  -> customer confirmation
  -> QuoteInputs-compatible handoff preview
```

Manual entry and drawing-assisted entry use the same canonical field names,
form controls, active product options, `render_plate_svg`, and `QuoteInputs`
shape. The drawing path does not calculate or request a price.

## Actual configurator integration points

- Entry point: `pages/1_Quote.py`
- Active options: the page's existing cached `GET /config/active` request
- Canonical request: `pricing_engine.QuoteInputs`
- Production price boundary: the existing `POST /quote` helper
- Preview: `plate_preview.render_plate_svg`
- Customer identity: the existing Supabase session in `auth.py`

When drawing assistance is unused or disabled, the existing manual form still
calls the existing API-authoritative pricing path. When a drawing-derived
session is active, live pricing and checkout remain intercepted.

## Internal access boundary

Both services must set:

```text
OPLATES_DRAWING_ASSISTED_ENABLED=true
```

The pricing API must also set:

```text
OPLATES_DRAWING_ASSISTED_ALLOWED_USER_IDS=<comma-separated Supabase user UUIDs>
```

The page displays and runs the upload workflow only after
`GET /internal/drawing-intake/access` succeeds. That endpoint verifies the
Supabase JWT with the existing JWKS/issuer/audience settings and checks the
verified `sub` against the server-side allowlist. A missing flag returns 404;
a missing/invalid identity returns 401; a non-allowlisted identity returns 403;
and an empty allowlist fails closed.

The API endpoint accepts no file content. Drawing bytes remain within the
Streamlit server's in-memory session and local recognition worker.

## Upload safeguards

Defaults:

| Limit | Default |
|---|---:|
| File size | 15 MiB |
| PDF pages | 10 |
| Image/page dimension | 16,000 px |
| Total render pixels | 80,000,000 |
| Processing timeout | 90 seconds |

Validation checks magic bytes, extension, declared MIME type, PDF readability,
page count, projected PDF render dimensions, image format, image dimensions,
and total pixels. Filenames are reduced to a basename and never used to build a
shell command or filesystem path. Processing runs in a terminated-on-timeout
local child process. No persistent upload or crop is created, no drawing text
is logged, and no external service is called.

The limit environment variables are documented in `DEPLOYMENT.md`.

## Active configuration

The same `/config/active` response already consumed by the manual form is
validated into `CanonicalFormAvailability`. Drawing mapping and review honor
the response's enabled materials, thicknesses, bore tolerances, lead times,
dimension maxima, and marking length. The integration does not use Phase 1F's
local tuning defaults.

## Form state and customer precedence

The real form tracks each canonical value as `default`, `drawing`, or
`customer` state:

- A recognized supported value may replace an untouched manual default.
- A customer-entered value is preserved when a drawing is uploaded or
  reanalyzed.
- A conflicting proposal is shown beside the retained customer value.
- Missing recognized fields remain blank and appear in the checklist.
- Clearing a required field immediately returns it to the checklist.
- Unsupported or ambiguous proposals remain evidence-only.
- A prefilled value can be cleared without discarding its source evidence.
- Changing a candidate requires an explicit “Use selected plate” action.
- Selecting a new file invalidates stale pending extraction results.
- Reset restores the original manual defaults and manual pricing behavior.

Recognized fields map to the existing form as follows:

| Extraction | Canonical form field |
|---|---|
| Outside diameter | `paddle_dia` |
| Bore diameter | `bore_dia` |
| Thickness | `thickness` |
| Material | `material` |
| Quantity | `quantity` |
| Equal supported plus/minus tolerance | `bore_tolerance` |
| Chamfer present | `chamfer` |
| Chamfer width | `chamfer_width` |
| Marking text | `handle_label` |

Asymmetric or incomplete tolerances are not converted into the existing
symmetric `bore_tolerance` field.

## Confirmation and pricing boundary

The confirmation text applies to the complete current form state. The Phase 1F
fingerprint is reused, so any subsequent value change invalidates confirmation.
The customer does not acknowledge individual OCR tokens.

After confirmation, the integration validates both the manual form payload and
the assisted-session preview through `QuoteInputs` and checks exact equality.
The preview reports:

```text
pricing_invoked = false
checkout_invoked = false
order_created = false
```

No simulated price, Stripe call, checkout session, cart line, or order is
created by the drawing-assisted path.

## Internal run

Use only an approved local/internal environment with a real API and allowlisted
Supabase test user:

```bash
OPLATES_DRAWING_ASSISTED_ENABLED=true \
API_BASE=http://127.0.0.1:8000 \
.venv/bin/streamlit run app.py
```

The API process needs the same feature flag, the allowlisted user UUID, and the
existing Supabase JWT verification variables. Do not set these variables in a
public or production environment during Phase 1G.

## Phase 1G limitations

- This is internal acceptance, not a production upload system.
- Upload processing currently runs in a bounded child process on the Streamlit
  service. A production-ready queue/worker topology has not been selected.
- There is no malware scanner, durable quarantine, retention policy, or
  operational monitoring.
- Source page/bbox provenance is retained, but polished visual highlighting is
  not implemented.
- The existing deterministic recognition and small-corpus limitations remain.
- The existing quote schema still represents bore tolerance symmetrically.
- Formal accessibility and cross-device acceptance require a controlled
  browser environment before customer exposure.

## Smallest Phase 1H

Keep the feature internal. Run controlled staff acceptance against the actual
staging UI/API with a test user allowlist and intercepted pricing, add malware
scanning/temporary-file policy and worker-isolation review, complete responsive
and accessibility checks, and collect usability findings. Do not enable public
uploads or drawing-driven live pricing until those controls and additional
independent drawing evidence are reviewed.
