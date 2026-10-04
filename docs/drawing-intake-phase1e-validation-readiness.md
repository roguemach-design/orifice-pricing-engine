# Drawing intake Phase 1E: corpus validation and integration readiness

Phase 1E completes the work possible with the available private corpus. It does
not add a customer UI, production storage, pricing call, checkout behavior,
deployment, cloud OCR, or generative interpretation.

## Architecture and safety boundary

```text
DOCUMENT
  -> DOCUMENT CLASSIFICATION
  -> CANDIDATE IDENTIFICATION
  -> EXPLICIT SELECTION WHEN REQUIRED
  -> LOCAL RENDER / TESSERACT
  -> ENGINEERING + SPATIAL / TABLE RULES
  -> DOMAIN VALIDATION
  -> CUSTOMER-CONFIRMATION CONTRACT
  -> EXISTING CONFIGURATION PATH (future; not invoked here)
```

Whole multi-part sheets and table schedules still cannot create a canonical
candidate. Reference documents remain non-quote-specific. Recognition evidence
and product support are separate: a clearly read value may still be outside the
instant-quote catalog. No recognized value overwrites a customer value.

## Available source groups

| Source group | Role | Independent customer evidence |
| --- | --- | --- |
| `706928890` | Two related vector exports, eight regions each | One correlated source group |
| `836026-204-03` | Separate vector multi-plate drawing, eight regions | One independent source group |
| `cc300120404` | Table-driven assembly/schedule, 13 rows | One independent source group |
| `846673` | Low-resolution crop derived from an existing family | No; derived evidence only |
| AVCO datasheet | Vendor/reference negative case | No; reference classification only |

The available corpus is useful for architecture and failure analysis but is not
large or diverse enough for a production-accuracy claim: **INSUFFICIENT
INDEPENDENT DRAWING COVERAGE**.

## cc300 adjudication and deterministic improvement

The original PDF was reviewed directly at 300 DPI. Its ruled schedule contains
13 rows and eight distinct plate configurations. Row values, tag association,
OD, bore, 6 mm thickness, symmetric bore tolerance, S.S.-316 material, metric
units, and quantity one are independently readable. Private ground truth stores
page-one PDF-point bboxes and keeps recognizer output out of the truth source.

Two observed failure modes justified bounded changes:

- quantity OCR merged digits with cell borders and misread three `1` values as
  `2`; each quantity cell is now rerendered locally at 600 DPI with a small
  border inset, while the full-page raw observation remains attached;
- two `±0.05` tolerance cells lost the symbol at 150 DPI; ambiguous tolerance
  cells now receive a 600-DPI local rerender, and `±` is recovered only when the
  cell is already bound to the tolerance column and two separated horizontal
  glyph bands are visible.

All table values remain `low_confidence` and require explicit row selection and
customer confirmation. Targeted OCR cannot promote a schedule value to
authoritative status.

Run the private benchmark with:

```bash
.venv/bin/python -m drawing_intake.schedule_benchmark \
  --source drawing_corpus/private/phase1e_library/cc300120404.pdf \
  --ground-truth drawing_corpus/private/phase1e_cc300_schedule_ground_truth.json
```

The support audit normalizes metric dimensions through existing domain rules.
All 13 rows are readable but outside the current instant-quote catalog because
6 mm is not an enabled 316 thickness and the metric tolerance magnitudes do not
equal a supported canonical tolerance. Values are retained and marked
unsupported; they are not substituted.

## Canonical configuration mapping

| Drawing field | Existing `QuoteInputs` field | Readiness rule |
| --- | --- | --- |
| `outside_diameter` | `paddle_dia` | Normalize to inches; confirm before use |
| `bore_diameter` | `bore_dia` | Normalize to inches; confirm before use |
| `thickness` | `thickness` | Normalize, then validate against material catalog |
| `material` | `material` | Normalize only recognized material aliases |
| `quantity` | `quantity` | Secondary field; confirm |
| tolerance plus + minus | `bore_tolerance` | Map only when both sides exist, agree, and are supported |
| `chamfer_present` | `chamfer` | Confirm; never infer from catalog fit |
| `chamfer_width` | `chamfer_width` | Optional existing field |
| `marking_text` | `handle_label` | Preserve raw instruction for review |
| `global_units` | none | Interpretation/provenance only; dimensions normalize individually |
| drawing/revision/part number | none | Traceability/order metadata only |

`handle_width`, `handle_length_from_bore`, and `ships_in_days` remain manual. An
asymmetric tolerance is retained as two drawing values and cannot be converted
to the symmetric `bore_tolerance` field. The production quote schema is
unchanged.

## Customer-confirmation contract

`CustomerConfirmationContract` is a UI-neutral, immutable review payload. Each
field proposal carries the normalized value, raw text, source document hash,
page/bbox, coordinate unit, deterministic evidence state, validation state,
unsupported flag, competing values, and confirmation requirement.

Customer actions are recorded separately:

- confirm retains the proposed value and evidence;
- correct retains the proposal and records a distinct customer value;
- reject retains evidence but marks the proposal rejected;
- complete a manual field records it outside extraction; and
- multi-part documents remain `selection_required` until a region/row is chosen.

The contract never constructs `QuoteInputs`, overwrites a manual configuration,
or invokes pricing. A later internal integration may pass only customer-resolved
values into `QuoteRequest -> QuoteInputs -> existing API-authoritative pricing`.

## Reconciliation review matrix

| Case | Required result |
| --- | --- |
| Exact supported agreement | `match` at data level; not proof of full drawing verification |
| Bore/OD mismatch | `requires_resolution`; preserve both values |
| Missing drawing field | `requires_resolution`; customer value remains unchanged |
| Unsupported drawing value | `blocked`; no substitution |
| Ambiguous/incomplete tolerance | `requires_resolution` or `blocked` according to domain outcome |
| Multiple candidates | `selection_required`; no automatic selection |
| Reference document | `not_quote_specific`; no candidate |
| Metric drawing vs inch configuration | Compare normalized values; retain original unit evidence |
| Ambiguous units | `requires_resolution`; do not invent units |

## Remaining limits

- Three independent customer source groups are not sufficient to estimate a
  production error rate.
- The raster crop is too low resolution to establish OCR reliability for real
  degraded scans.
- The schedule title-block drawing number/revision are visually adjudicated but
  are not yet part of the schedule extraction result.
- Chamfer/no-chamfer diversity is weak in the real corpus.
- Customer confirmation and reconciliation have stable data contracts but no UI
  or internal end-to-end workflow yet.

The smallest responsible next step is an internal-only confirmation and
reconciliation workflow prototype using existing fixtures and the current
canonical configuration path, with pricing explicitly stubbed. Production
recognition readiness still requires more independent single-plate drawings,
metric/unilateral/asymmetric tolerance examples, chamfer variants, and a
readable degraded scan from unrelated organizations.
