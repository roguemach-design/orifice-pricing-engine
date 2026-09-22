# Drawing intake Phase 1F: assisted quoting prototype

Phase 1F adds an isolated, internal-only drawing-assisted configuration workflow.
It demonstrates the intended product direction: the reader prefills usable values,
the purchaser completes or corrects the configuration, and one explicit
confirmation produces a schema-compatible handoff for the existing pricing path.

It does not modify or call the production quote page, pricing API, checkout,
Stripe, authentication, storage, staging, or production.

## Run locally

Tesseract must be installed locally. From the repository root:

```bash
OPLATES_INTERNAL_DRAWING_PROTOTYPE=1 \
  .venv/bin/streamlit run internal_drawing_quote_app.py
```

The separate environment gate and separate entry point prevent the prototype from
appearing in the current customer multipage application. Uploaded bytes stay in
the Streamlit process memory. No external OCR or document service is used.

## Implemented workflow

```text
UPLOAD PDF / PNG / JPEG
  -> LOCAL NORMALIZATION + DOCUMENT CLASSIFICATION
  -> EXPLICIT REGION / SCHEDULE-ROW SELECTION WHEN NEEDED
  -> EXISTING DETERMINISTIC RECOGNITION
  -> EDITABLE CANONICAL FORM STATE
  -> DYNAMIC MISSING / INVALID / UNSUPPORTED REVIEW
  -> CUSTOMER CONFIRMATION
  -> QUOTE-REQUEST HANDOFF PREVIEW (NO PRICING CALL)
```

Reference documents and unreadable or unsupported uploads may proceed through the
normal manual configuration path. Recognition is an assistant rather than a gate:
a missing or ambiguous field stays blank and becomes customer input.

## Existing configuration compatibility

The prototype derives required fields from the real `QuoteInputs` Pydantic model.
It uses the same canonical names and reuses the existing `render_plate_svg`
preview. Local product availability comes from the same accepted
`tuning_knobs.py` values used by the local pricing engine, but no pricing formula
is called.

| Drawing observation | Canonical field | Population rule |
| --- | --- | --- |
| outside diameter | `paddle_dia` | normalize to inches; retain source |
| bore diameter | `bore_dia` | normalize to inches; retain source |
| thickness | `thickness` | populate only if representable; otherwise flag unsupported |
| material | `material` | populate only a supported normalized material |
| quantity | `quantity` | proposed as customer-confirmable input |
| equal supported tolerance sides | `bore_tolerance` | both sides required; asymmetric/incomplete stays manual |
| chamfer presence | `chamfer` | explicit observed value only |
| chamfer width | `chamfer_width` | required dynamically when chamfer is enabled |
| marking | `handle_label` | optional; existing character/length rules apply |

`handle_width`, `handle_length_from_bore`, and `ships_in_days` normally remain
manual. `handle_label` retains the existing `No label` canonical default. No
manufacturing dimension is invented.

## Dynamic attention model

`review_assisted_quote` recalculates state from the current editable configuration
on every interaction. It distinguishes:

- missing required values;
- invalid values or relationships;
- drawing-prefilled values awaiting the purchaser's overall confirmation;
- readable but unsupported drawing specifications; and
- optional values that do not block completion.

The required list is derived from `QuoteInputs.model_fields`. Chamfer width is a
conditional UI requirement only when chamfer is `True`. Clearing a required field
adds it back immediately. Entering a valid value removes it.

## Customer precedence and confirmation

The original proposal remains immutable and carries raw text, document hash, page,
bbox, coordinate unit, evidence state, and validation state. Customer edits are
stored in a separate canonical value with `origin=customer`; they never mutate the
proposal. Rejecting a proposal clears only a drawing-origin value.

Confirmation fingerprints the complete canonical configuration. Any later edit
clears the fingerprint, so the customer must confirm the revised part. Individual
OCR tokens do not require separate approval.

## Unsupported drawing specifications

A readable unsupported observation remains attached to the session and appears in
the attention list. It is never replaced by the nearest catalog value. A customer
may deliberately choose a supported configuration value; the original drawing
observation remains visible as a discrepancy for review.

For the existing cc300 schedule, the selected row's OD, bore, material, and
quantity can populate. Its 6 mm plate thickness and metric tolerance magnitude are
preserved as unsupported and remain manual/RFQ decisions.

## Multi-part and schedule isolation

`inspect_assisted_upload` enumerates candidates but creates no configuration.
`select_assisted_candidate` accepts exactly one region or schedule-row identifier
and builds state only from that candidate. Reference sheets expose no random row.
Raster-derived regions retain original pixel coordinates; PDF regions retain PDF
points.

## Pricing boundary

`build_pricing_handoff_preview` is available only after the configuration is
complete, valid, and currently confirmed. It validates against `QuoteInputs` and
returns the exact existing field set with this declared destination:

```text
QuoteRequest -> QuoteInputs -> existing API-authoritative pricing
```

The preview records `pricing_invoked=false`, `checkout_invoked=false`, and
`order_created=false`. It contains no formulas and returns no dollar amount.

## Internal components

- `drawing_intake/assisted_intake.py`: upload classification, candidate enumeration,
  selected-region recognition, schedule-row conversion, and manual fallback.
- `drawing_intake/assisted_quote.py`: editable state, dynamic attention, validation,
  customer precedence, confirmation, and pricing-handoff preview.
- `internal_drawing_quote_app.py`: environment-gated Streamlit demonstration using
  the existing SVG preview.

## Known limits

- This is an internal workflow prototype, not a customer UI or security-reviewed
  upload service.
- Local availability uses repository defaults rather than a live `/config/active`
  response; actual integration must use the active API configuration.
- Drawing source bboxes are displayed as evidence text; polished page highlighting
  is not implemented.
- The deterministic recognition limits and insufficient independent drawing
  coverage documented in Phase 1E remain unchanged.
- Schedule values remain confirmation-only even when OCR and table binding agree.
- No production persistence, retention policy, malware scanning, authentication,
  rate limiting, accessibility review, or operational monitoring exists for
  uploads.

The smallest next integration step is to adapt the accepted workflow state to the
actual customer form behind a disabled/internal feature flag, source product
availability from `/config/active`, and keep pricing disabled until independent UX
and upload-security review is complete.
