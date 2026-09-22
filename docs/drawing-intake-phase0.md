# Drawing intake Phase 0

## Purpose and boundary

This isolated module turns one O-Plate drawing into a structured candidate. It
does not price, create orders, upload customer files, or change the existing API,
UI, checkout, or pricing engine.

Pipeline:

`document -> normalization -> extraction -> schema validation -> domain validation -> candidate`

Manual entry and a future drawing workflow must both converge on the existing
`QuoteRequest` / `QuoteInputs` object. Only the existing API-authoritative quote
path may call pricing.

## Existing configuration mapping

| Drawing field | Existing canonical field | Current representation / rule |
| --- | --- | --- |
| quantity | `quantity` | integer count, minimum 1; quantity-tier pricing |
| material | `material` | enabled string from active config; baseline `304`, `316`, `Carbon Steel` |
| thickness | `thickness` | float inches; enabled discrete values by material |
| outside diameter | `paddle_dia` | float inches; positive and at most active OD limit (baseline 48 in) |
| bore/orifice diameter | `bore_dia` | float inches; positive, below OD, at most active bore limit (baseline 19 in) |
| bore tolerance plus/minus | `bore_tolerance` | only maps when symmetric and enabled; baseline ±0.001, ±0.002, ±0.005 in |
| chamfer present | `chamfer` | boolean |
| chamfer width | `chamfer_width` | optional positive float inches; never defaulted |
| marking text | `handle_label` | string, baseline maximum 40 characters and existing character allowlist |

Existing required fields with no Phase 0 drawing mapping are `handle_width`,
`handle_length_from_bore`, and `ships_in_days`; they remain manual. Global units
are used to normalize drawing dimensions to the canonical inch representation.
General tolerance, chamfer depth/angle, customer part number, drawing number, and
revision remain traceability/reconciliation data because `QuoteInputs` has no
corresponding field. They do not affect price.

Frontend fields are built from public `/config/active` availability and limits.
The frontend sends the canonical names to `/quote`; the API validates
`QuoteRequest`, constructs `QuoteInputs`, applies active database knobs, and calls
the existing `calculate_quote()` implementation.

## Schema and abstention

`DrawingFields` is a strict Pydantic schema. Every field contains its own value,
normalized unit, raw text, confidence, status, evidence, validation state, and
warnings. Evidence can retain a page number and source bounding box.

Statuses include `detected`, `not_detected`, `ambiguous`, `unsupported`,
`conflict_detected`, `low_confidence`, and `unreadable`. A detected field must
have a value. A missing or unreadable field cannot contain one.

The extraction result records what the drawing appears to say. The separate
domain-validation result records whether O-Plates supports it. Unsupported values
are retained as observed; they are not substituted with a valid catalog value.

## Document path

`normalize_document()` accepts PDF, PNG, JPG, and JPEG bytes in memory. For PDFs,
`pdfplumber` extracts native text with page-relative PDF-point bounding boxes and
records page size, rotation, orientation, images, metadata, and whether each page
has native text or appears image-only. Native text is preferred over OCR. Image-only
pages are identified and the native provider abstains.

`render_page_png()` can render a page on demand for a future OCR/vision adapter.
It does not save an intermediate file. Original bytes are retained only in the
ephemeral normalized object and are excluded from model serialization.

## Provider interface

Providers implement:

`extract_drawing(document) -> DrawingExtractionResult`

`NativeTextExtractionProvider` is the first working path for clearly labeled
digital PDFs. `StructuredModelExtractionProvider` is a vendor-neutral strict-JSON
adapter. It supplies the fixed O-Plate prompt and `DrawingFields` JSON schema to a
caller-provided completion function, then rejects prose, malformed JSON, extra
fields, and incomplete detected fields.

No live AI provider is configured in Phase 0 and no credential is required for the
offline path. A live adapter will require its provider API credential, model/endpoint
configuration, and an explicit retention/data-residency setting supplied through
environment or secret management. Vendor response objects must stay inside the
adapter. External-service use and retention behavior are explicit in
`ProviderDataHandling`.

## Validation and reconciliation

`validate_extraction()` reuses current values from `tuning_knobs` for materials,
thicknesses, tolerances, maximum diameters, and marking length. It checks positive
dimensions, units, bore < OD, supported envelopes/material/thickness/tolerance,
tolerance coherence, chamfer consistency, and marking constraints. The resulting
`CanonicalConfigurationCandidate` uses exact `QuoteInputs` names but remains
partial and cannot price itself.

`compare_extraction_to_configuration()` reports `match`, `mismatch`,
`extraction_unknown`, `unsupported`, or `not_comparable`, retaining both customer
and drawing values. It never mutates or overwrites manual configuration.

`CriticalFieldVerifier` and `reconcile_independent_verification()` define the
second-pass boundary for OD, bore, thickness, material, units, and bore tolerance.
No live verifier is enabled in Phase 0.

## Corpus and benchmark

`drawing_corpus/synthetic` contains five generated fixtures: clean digital PDF,
missing field, ambiguous values, unsupported values, and metric normalization.
They are software tests only. `drawing_corpus/private` is ignored and must not be
used to commit proprietary drawings.

Run:

```bash
python scripts/generate_synthetic_drawing_fixtures.py
python -m drawing_intake.benchmark drawing_corpus/synthetic \
  --high-confidence-threshold 0.95
```

The threshold is deliberately required and configurable. The report includes
per-document and aggregate detection, exact/normalized numeric, material, unit,
tolerance, chamfer, metadata, abstention, incorrect-confident-extraction, and DHCE
results. Synthetic success is not a real-world accuracy claim.

## Phase 1 minimum

Add a small approved corpus of real historical single-plate drawings with dual
annotation and adjudication. Run the benchmark unchanged, review failures by
critical field, then add one enterprise vision adapter and an independent critical-
field verifier only if the real corpus demonstrates that the native path is
insufficient. Customer UI, storage, checkout blocking, and pricing integration
remain out of scope until real-print accuracy and DHCE behavior are understood.
