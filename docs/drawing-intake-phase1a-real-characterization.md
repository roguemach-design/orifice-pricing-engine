# Drawing intake Phase 1A: real-drawing characterization

## Scope and data handling

This phase evaluates two proprietary CAD PDFs locally. Both source files remain
under ignored `drawing_corpus/private/`; no source drawing or derived crop is
tracked, transmitted to an external provider, deployed, or connected to pricing,
checkout, staging, or customer UI.

The files are related exports/versions of drawing `706928890`, not two independent
production samples. All accuracy conclusions are therefore limited to one source
group.

## Preserved Phase 0 baseline

The accepted Phase 0 pipeline was run before parser changes. Both files normalized
without an exception and had a native text layer, but the native provider detected
zero of the 17 V1 extraction fields.

| Local source | Pages | Normalized page | Rotation | Content kind | Text blocks / normalized characters | Extraction and validation |
| --- | ---: | --- | ---: | --- | ---: | --- |
| `706928890-0000-Layout1.pdf` | 1 | 1224 x 792 pt, landscape | 270 degrees | `native_text` | 37 / 1,793 | All 17 fields `not_detected`; no validation issues; no canonical values |
| `706928890-Model.pdf` | 1 | 1224 x 792 pt, landscape | 270 degrees | `native_text` | 38 / 1,768 | All 17 fields `not_detected`; no validation issues; no canonical values |

There were no baseline document warnings. Both partial canonical candidates lacked
all ten quote-required fields: quantity, material, thickness, handle width, handle
length from bore, OD, bore, bore tolerance, chamfer, and ship-days selection. This
was a safe empty result, but Phase 0 did not explain the multi-part cause.

## PDF characterization

Both inputs are one-page PDF 1.7 CAD/vector exports with embedded fonts, no raster
images, and usable bounding boxes for the limited native text. A native text layer
is therefore not evidence that manufacturing annotations are machine-readable.

| Local source | PDF creator | Native objects | Rendering observation |
| --- | --- | --- | --- |
| `706928890-0000-Layout1.pdf` | AutoCAD Mechanical 2024 | 6,489 lines, 3,900 curves, 1 rectangle, 1,610 native characters, 0 images | 150-DPI render was legible at 2550 x 1650 px |
| `706928890-Model.pdf` | AutoCAD Mechanical 2022 | 5,978 lines, 4,537 curves, 1 rectangle, 1,584 native characters, 0 images | 150-DPI render was legible at 2550 x 1650 px |

The native text consists mainly of title-block, grid, revision, and copyright
content. Most visible part-detail labels and values are vector outlines and do not
appear in ordinary text extraction. Page rotation is preserved as 270 degrees;
the normalized dimensions/orientation and rendered page are landscape and usable.
Native bounding boxes remain usable for native metadata, but cannot provide
provenance for annotations that are absent from the text layer.

Each sheet visibly contains eight O-Plate detail blocks in a two-by-four layout.
A generic diagnostic found 24 circular vector profiles, clustered as three
concentric profiles at each of eight centers. This supports safe page-structure
detection; it does not infer dimensions from vector scale.

## Related revision pair

| Local source | Verified drawing / revision | Relationship and changed-region observation |
| --- | --- | --- |
| `706928890-Model.pdf` | `706928890`, visible revision marker `-` | Older/base export created in 2023 |
| `706928890-0000-Layout1.pdf` | `706928890`, revision `B` | Newer export created in 2025; revision history includes A and B |

The revision-B sheet has a revision cloud and B marker around the two upper-right
plate blocks. The visually apparent changes are localized to those blocks and
their conditions/tags plus revision metadata. The pair is useful for future
revision-awareness, changed-region traceability, and reconciliation tests. No
revision-diff engine was built.

The drawing number and revision are present in the native title-block text, but
label/value separation across text blocks prevents the current provider from
binding them semantically. Ground truth was established by local native-text and
visual review, not by accepting the provider's empty result.

## Native extraction failure taxonomy

This table describes both related PDFs. “Multiple” means the whole sheet has
several legitimate per-plate values; it does not mean a value was promoted.

| V1 field | Native/visual classification | Phase 1A result |
| --- | --- | --- |
| OD / `paddle_dia` | Visible but absent from native text; multiple plate candidates | Not detected; needs region-aware vision/semantic reading |
| Bore / `bore_dia` | Visible but absent from native text; multiple plate candidates | Not detected; needs region-aware vision/semantic reading |
| Thickness | Visible but absent from native text and repeated by region | Not detected; needs region-aware vision/semantic reading |
| Material | Visible but absent from native text and repeated by region | Not detected; needs region-aware vision/semantic reading and catalog validation |
| Quantity | Visible per detail but absent from native text; candidate context differs | Not detected; must be scoped to a selected region |
| Global units | Inch notation is visually implied per annotation; no safely bound global native value | Not detected; needs semantic interpretation and confirmation |
| Bore tolerance | Visible but absent from native text; multiple plate candidates | Not detected; critical field requiring independent verification |
| Chamfer present | Section/detail geometry is visible but not natively semantic | Not detected; requires vision plus conservative interpretation |
| Chamfer width | Detail annotation is not available as native text | Not detected; requires region-aware vision if applicable |
| Marking text | Visible and differs by plate, but is absent from native text | Not detected; must be scoped to a selected region |
| Drawing number | Native text available; label/value binding failed | Not detected by provider; reusable metadata-layout work may recover it |
| Revision | Native text available; label/value binding failed | Not detected by provider; reusable metadata-layout work may recover it |
| Customer part number | No unambiguous field matching the V1 concept was established | Abstain; do not reinterpret contract/tag fields |

No unsupported canonical manufacturing value was assessed because no
manufacturing value was natively extracted. The dominant failures are vector-
outlined annotations, multiple candidate regions, and semantic binding—not unit
normalization or downstream O-Plates validation.

## Multi-part safety

Normalization now retains small generic vector-profile hints, not full drawing
content. `assess_document_structure()` clusters repeated concentric profiles by
page position. More than one qualifying cluster produces:

- document status `multiple_candidates`;
- candidate-region count and PDF-point bounding boxes;
- abstention reason `unsupported_multi_part_sheet_requires_part_selection`.

The pipeline then adds the blocking validation issue
`unsupported_multi_part_sheet` and replaces the canonical candidate with a fully
empty partial candidate. Provider observations remain inspectable, but no value
can silently cross the structure gate into one quote-shaped configuration. The
gate neither prices nor modifies the existing canonical/pricing path.

This heuristic is intentionally conservative. False-positive abstention is safer
than combining or selecting values, and broader real-drawing testing is required
before treating its candidate count as general segmentation.

## Corpus and ground truth

Tracked metadata is under `drawing_corpus/real/`:

- `manifest.json` records two `real_document` entries with one shared
  `source_group_id`;
- one document-level ground-truth file per export records drawing/revision, one
  page, multi-part status, eight visible regions, and expected abstention;
- classification supports `real_document`, `derived_real_region`, and
  `synthetic_fixture`;
- derived-region entries require source page and source bounding box and do not
  increase independent-source counts.

No derived crops were created. Isolating a region would not make vector-outlined
critical annotations available to the native-text provider, so it would not answer
the Phase 1A native-capability question. Manual regions remain the preferred first
vision-provider benchmark because they can preserve source provenance without an
automatic segmentation project.

## Benchmark results

### Whole-document production-safety view

The local real-corpus benchmark processed two files representing one independent
source group. Both matched `multiple_candidates`, both found eight candidate
regions, both emitted `unsupported_multi_part_sheet`, and neither populated a
canonical candidate: 2/2 expected safe outcomes. This is a safety result, not a
field-extraction accuracy rate.

### Derived-region extraction-capability view

Not run: zero derived regions exist. The benchmark reports this view separately as
`not_run_no_derived_regions` and assigns it zero independent source groups.

### Synthetic software-fixture view

The unchanged five-fixture benchmark at a configurable 0.95 high-confidence
threshold scored 39/39 field detections, 23/23 exact and normalized numeric
matches, 5/5 material matches, 25/25 unit matches, 4/4 tolerance matches, 3/3
chamfer checks, 4/4 metadata matches, 2/2 correct abstentions, and zero dangerous
high-confidence errors. These generated fixtures test software behavior only and
say nothing about production accuracy.

## Phase 1B recommendation

A live enterprise vision experiment is now justified for diagnostic benchmarking:
critical manufacturing annotations are visibly legible in the render but absent
from native text. It is not yet justified as customer-facing extraction, and one
correlated source group is not enough for model/provider selection.

The first provider benchmark should use both views: full-page input to test
multi-part recognition/safe abstention, and manually selected single-plate regions
to test OD, bore, bore tolerance, thickness, material, quantity, units, chamfer,
and marking extraction. Manual region selection is sufficient initially; automatic
segmentation should wait for evidence that it is necessary. Full-page multi-part
documents, uncertain part identity, critical-field disagreement, unreadable values,
and unsupported catalog values must remain abstain/manual-confirmation cases.

Before transmitting proprietary drawings, a provider must support contractually
acceptable no-training use, configurable minimal/zero retention, encryption in
transit and at rest, access controls and auditability, approved data residency and
subprocessors, secret-managed credentials, and explicit external-provider
configuration. No ITAR claim should be made without a separate legal/compliance
review.

The smallest useful next batch is 8–10 independently sourced drawings: three clean
single-plate digital PDFs, examples covering bilateral and unilateral bore
tolerances, paired chamfer/no-chamfer cases, one metric drawing, one older or poor
scan, and one genuinely ambiguous print. Categories may overlap, but each source
must retain independent grouping and adjudicated critical-field ground truth.

## Known limitations

- The real corpus represents one source drawing and one organization/layout style.
- Document-level candidate regions are generic circle-cluster hints, not automatic
  part segmentation or vector-dimension interpretation.
- Drawing-number and revision parsing was not tuned to this title block.
- No per-region ground truth, real field-accuracy score, OCR, or vision benchmark
  exists yet.
- No revision comparison, customer workflow, storage, pricing, checkout, or
  production behavior was added.
