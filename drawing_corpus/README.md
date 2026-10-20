# Drawing corpus

This directory defines versioned ground-truth formats for drawing-intake
benchmarks. `synthetic/` contains generated software-test fixtures only.
Synthetic results are not evidence of customer-drawing accuracy.

Do not commit proprietary customer drawings. Put local source files and any
customer-identifying annotations under `private/`, which is git-ignored. A future
shared corpus should keep drawing bytes in approved restricted storage and commit
only non-sensitive ground-truth records or opaque document references after review.

Each `*.ground_truth.json` file records:

- an opaque document id and source reference;
- whether the source is synthetic;
- test categories;
- expected field values/statuses/units;
- expected deterministic validation issue codes.

Ground truth should eventually be produced by two independent annotators with
adjudication and source bounding boxes for critical values.

## Restricted-corpus intake

Use this sequence when another authorized drawing becomes available:

1. place source bytes in approved restricted storage and materialize only into
   `drawing_corpus/private/` for local work;
2. assign an opaque `source_group_id`, then attach related revisions, exports,
   and derived crops to that same group;
3. record `real_document`, `derived_real_region`, or
   `reference_vendor_datasheet` classification metadata;
4. annotate each manufacturing-critical value from the original source with
   page, raw text, unit, source bbox, and `verified`/`provisional` status;
5. obtain an independent human review when possible and keep unresolved values
   provisional rather than copying recognizer output into truth;
6. run native, OCR, deterministic, domain-validation, and wrong-authoritative
   benchmarks separately;
7. review every wrong value and abstention by source group before changing a
   generic rule; and
8. add only non-proprietary regression metadata or synthetic fixtures to git.

Never count revisions or derived regions as independent drawings. Synthetic
transformations expand software coverage only; they do not increase real-corpus
accuracy evidence.

## Real-corpus metadata

`real/manifest.json` tracks metadata only. It classifies entries as
`real_document`, `derived_real_region`, or `synthetic_fixture` and groups related
exports with `source_group_id` so correlated files are not counted as independent
drawings. Adjacent `*.document_ground_truth.json` files record document-level
facts and expected safe behavior without copying proprietary drawing contents.

A `derived_real_region` must include its source page and source bounding box. It
remains part of its source group and never increases the independent-document
count. Source PDFs and derived crops stay under ignored `private/` storage.

Run the local document-safety view with:

```bash
python -m drawing_intake.corpus drawing_corpus/real/manifest.json \
  --private-root drawing_corpus/private
```

This is separate from the synthetic field-accuracy benchmark. A successful
multi-part document result means safe abstention, not successful field extraction.

## Private deterministic-region benchmark

Phase 1B can keep adjudicated per-region values in an ignored private JSON file.
Those records and any rendered crops are proprietary and must remain under
`private/`. Derived regions keep their source group, filename, page, and original
PDF bounding box; they never increase the independent-document count.

With approved private files present, run the local-only benchmark with:

```bash
python -m drawing_intake.deterministic_benchmark \
  --private-root drawing_corpus/private \
  --ground-truth drawing_corpus/private/phase1b_region_ground_truth.json
```

The command invokes the installed local Tesseract executable and makes no network
request. Its native-only, OCR-observation, and deterministic-recognition stages are
reported separately.

## Private ruled-schedule benchmark

Phase 1E adds a verified/provisional-aware benchmark for table-driven schedules.
Private ground truth remains ignored and is never inferred from parser output.

```bash
python -m drawing_intake.schedule_benchmark \
  --source drawing_corpus/private/<source>.pdf \
  --ground-truth drawing_corpus/private/<schedule-ground-truth>.json
```

The report keeps provisional annotations out of verified totals, records
row/column binding, audits product support separately from recognition, requires
explicit row selection, and never invokes pricing.
