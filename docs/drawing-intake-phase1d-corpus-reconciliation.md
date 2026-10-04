# Drawing intake Phase 1D: raster corpus and reconciliation readiness

Phase 1D extends the isolated deterministic spike in two bounded directions:

1. add inspectable raster profile detection and resolution-aware local rendering;
2. prove the data-level reconciliation gate without UI, pricing, checkout, storage,
   deployment, or customer exposure.

The phase remains local-only. Tesseract is the only OCR engine. No document bytes
leave the process and no generative model or external inference service is used.

## Pipeline

```text
DOCUMENT
  -> NATIVE/VECTOR OR RASTER STRUCTURE
  -> DOCUMENT CLASSIFICATION
  -> EXPLICIT CANDIDATE SELECTION WHEN REQUIRED
  -> RESOLUTION-AWARE LOCAL RENDERING
  -> LOCAL OCR + DETERMINISTIC FIELD RULES
  -> DOMAIN VALIDATION
  -> EVIDENCE-AWARE COMPARISON WITH MANUAL CONFIGURATION
  -> MATCH / REQUIRES RESOLUTION / BLOCKED
```

Reconciliation never mutates the supplied configuration, never selects a
multi-part candidate, and never invokes pricing.

## Raster structure recognition

`detect_raster_plate_structure()` uses only pixel geometry. Candidate centers
must have crossing long centerline-like ink runs plus two separated circular
perimeter bands. It does not inspect vendor names, filenames, drawing numbers,
or catalog fit. Detected regions retain original-image pixel coordinates.

Raster rendering now treats native pixels as a 96-DPI observation and applies a
deterministic Lanczos resize for requested OCR DPI. The inverse transform always
maps OCR boxes back to original source pixels. Original evidence is not replaced
or thresholded by this step.

## Reconciliation gates

| State | Rule | Effect |
| --- | --- | --- |
| `not_quote_specific` | Reference, ambiguous, or unsupported document | No comparison candidate |
| `selection_required` | Multi-plate drawing or table schedule | No automatic row/region selection |
| `eligible_single_candidate` | Exactly one quote-specific candidate | Selected recognition may proceed |
| `match` | All critical observations are supported, authoritative, and match | Data-level match only |
| `requires_resolution` | Mismatch, missing field, ambiguity, or confirmation-only evidence | Preserve both values for review |
| `blocked` | Unsupported or contradictory critical drawing value | No promotion or substitution |

`automatic_overwrite_permitted` and `pricing_invoked` are always false in this
prototype. A value with `requires_confirmation` evidence remains review-only even
when its normalized number equals the manually entered value.

## Private corpus audit

The generic `drawing_intake.corpus_audit` harness accepts a private manifest,
reports by source group, and counts wrong critical values only when they reached
`strong` or `verified`. Customer documents, image crops, filenames, and private
ground truth remain under the ignored `drawing_corpus/private/` tree.

Run it with:

```bash
.venv/bin/python -m drawing_intake.corpus_audit \
  --private-root drawing_corpus/private/phase1d_library \
  --manifest drawing_corpus/private/phase1d_library/manifest.private.json
```

### Phase 1D sample results

| Source group | Class | Candidates | Adjudicated field result | Safety result |
| --- | --- | ---: | --- | --- |
| `846673` derived raster | multi-plate drawing | 2 | 3/16 correct confirmation-only; 13/16 abstained | selection required; 0 wrong critical strong/verified |
| AVCO raster reference | reference vendor datasheet | none | not scored as a customer order | non-quote-specific; 0 false quote candidates |

The `846673` crop is one correlated source group, not two independent customer
drawings. Its low resolution materially limits OCR. The useful result is that
generic raster geometry finds both plate regions while uncertain text does not
become authoritative.

The accepted Phase 1B base benchmark was rerun unchanged: two documents, 16
derived regions, two safe whole-document blocks, and zero deterministic wrong
critical fields. Base-only field totals remained bore 12/16, OD 13/16,
thickness 12/16, material 16/16, units 16/16, tolerance plus 14/16, tolerance
minus 0/16, and quantity 8/16 correct with one noncritical wrong reading. This
base-only harness intentionally does not include the later targeted OCR pass.

## Reconciliation proof on the real raster crop

The left `846673` region was compared with an independently entered configuration.
The review returned `requires_resolution`: no mismatches, five critical unknowns,
and bore/units confirmation requirements. Both customer and drawing values were
preserved. No overwrite, canonical quote candidate, or pricing call occurred.

## Limitations and next step

- Raster geometry is intentionally a bounded circle/centerline detector, not CAD
  reconstruction. It needs testing on scans without explicit centerlines.
- The new real crop is only 891 x 491 pixels. Rendering can improve sampling but
  cannot restore characters absent from the source.
- Full-page reference OCR now takes roughly 14 seconds locally because the image
  is resolution-normalized; this is acceptable for a spike but should be cached
  or staged before interactive use.
- Reconciliation has no UI and makes no ordering decision.
- The schedule rows still need independent adjudicated ground truth.

The smallest Phase 1E should add three clean single-plate customer PDFs from
different organizations and one genuinely degraded scan at materially higher
source resolution. It should adjudicate the existing 13-row schedule, then run
the same wrong-authoritative safety audit and reconciliation review without
changing evidence thresholds.
