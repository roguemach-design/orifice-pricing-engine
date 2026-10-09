# Drawing intake Phase 1B: deterministic recognition

## Purpose and boundary

Phase 1B tests the field-recognition ceiling of local deterministic software. It
does not add a public upload flow, storage, pricing calls, checkout behavior,
customer warnings, cloud OCR, a generative model, or any external inference API.

The implemented sequence is:

`PDF -> region -> local render -> local OCR -> engineering grammar -> spatial and geometric evidence -> field detector -> existing domain validation -> result`

Whole-document multi-part safety remains authoritative. Field recognition runs
only against an explicitly selected derived region, while the normal whole-page
pipeline still returns `multiple_candidates`, a blocking
`unsupported_multi_part_sheet` issue, and an empty canonical candidate.

## Local OCR implementation

The engine invokes the locally installed Tesseract 5.3.4 executable directly and
parses its TSV output. No Python OCR wrapper, network connection, hosted API, or
document transmission is involved. The installed English data is used. Tesseract
and the Debian package metadata identify the applicable license as Apache-2.0.

Two fixed page-segmentation configurations are used:

- PSM 6, which treats the region as a text block and is useful for tolerance and
  tabular lines;
- PSM 11, which treats the drawing as sparse text and is useful for isolated
  callouts.

Agreement between modes is deterministic corroboration, not a probability. The
Tesseract engine score is retained per token but is never the sole reason a
manufacturing value is accepted.

The required OS-level dependency is `tesseract` with the `eng` language data.
Absence produces an explicit dependency error; the code never falls back to a
cloud service.

## Region derivation and rendering

The Phase 1A concentric-profile boxes identify plate centers. Phase 1B groups
centers into rows and partitions each page at neighbor midpoints. Outer boundaries
are extrapolated from neighbor spacing. This creates stable detail cells without
hard-coding a company, drawing number, or page coordinate.

Each `DerivedDrawingRegion` retains:

- source group and filename;
- source page;
- candidate-profile bounding box;
- expanded original PDF bounding box;
- derivation method and `derived_real_region` classification.

PDFium renders only the selected region in memory. The render records DPI, pixel
dimensions, PNG and uncompressed sizes, elapsed time, and a reversible transform
from OCR pixel boxes to original top-origin PDF points.

## Engineering text and spatial rules

The grammar supports decimal and leading-decimal inches, fractions, mixed
fractions, metric measurements, inch/diameter/degree notation, symmetric,
bilateral, unilateral, and limit tolerances, chamfer width-by-angle notation, and
common O-Plates material aliases.

Context-limited OCR repairs retain both the raw token and rule name. Implemented
examples include Unicode engineering symbols, O/I/l in an otherwise numeric token,
S between digits, a pound-like glyph used where a tolerance sign is expected, and
compact/missing fraction slashes adjacent to a thickness label. No value is
changed merely because another value fits the O-Plates catalog.

Spatial association uses relative token/line overlap and distance inside one
selected region. Tokens from another region are ineligible. BORE, DIA/OD, THK,
material, quantity, and tolerance detectors therefore bind labels and values by
local topology rather than fixed x/y positions.

## Vector and geometry evidence

The current useful vector evidence is the generic nested/concentric profile group.
It establishes that the selected cell contains inner and outer plate profiles and
supports the OD/bore role check. The detector also requires the labeled bore to be
less than the labeled OD before promoting strong readings to `verified`.

Leader-line endpoint association was investigated but not promoted into the engine.
A representative selected region contains 82 vector line segments longer than five
PDF points, including roughly 29-30 longer than 20 points. Text-outline, centerline,
dimension, profile, and leader segments are intermingled, making a generic endpoint
graph brittle at this stage. Phase 1B stops short of a drawing-specific rule or full
CAD reconstruction.

## Evidence rules

Evidence class is independent of downstream catalog support.

| Critical field | Strong / verified | Requires confirmation | Ambiguous / abstain |
| --- | --- | --- | --- |
| Bore | Numeric token adjacent to BORE in selected region; two OCR modes agree; concentric profiles present. Promoted to verified when one uniquely supported candidate is less than OD. | One OCR mode, contextual repair, materially stronger but competing reading, or OD relationship conflict. | Equally supported distinct candidates; no adjacent labeled value. |
| OD | Numeric token adjacent to DIA/OD; two modes agree; concentric profiles present. Verified when uniquely supported and greater than bore. | One mode, contextual repair, dominant but competing reading, or bore relationship conflict. | Equally supported distinct candidates; no adjacent labeled value. |
| Thickness | Numeric/fraction token adjacent to THK/THICK with an explicit local unit; two uncorrected modes may be strong. | Fraction/slash repair or one-mode result. | Competing thickness readings or no label/value pair. |
| Material | Recognized grade and family on one selected-region line; two modes agree. | One-mode material phrase. | Multiple material phrases or no recognized phrase. |
| Units | Repeated explicit inch or metric marks across two OCR modes with no conflict. | Only one explicit unit observation. | Inch and metric evidence conflict, or no explicit unit. |
| Bore tolerance | Explicit tolerance grammar on a BORE line with coherent magnitudes. Clean complete grammar may be strong. | OCR sign repair or unilateral/incomplete representation. | Distinct plausible tolerances, incoherent magnitude, or missing side/value. |

The existing domain validator subsequently checks supported material, dimensions,
thickness, tolerances, and bore/OD constraints. A strongly read unsupported value
is retained as observed and separately marked unsupported; it is never replaced.

## Real source-group results

The two related exports produce eight regions each, but all 16 regions belong to
one independent source group. They are correlated revision/export examples, not 16
independent customer drawings.

Whole-sheet safety remained correct for 2/2 documents. Each exposed eight regions,
and neither produced a canonical candidate.

### Field-stage comparison

| Field | Native PDF | OCR contains expected observation | Deterministic correct | Deterministic wrong | Remaining |
| --- | ---: | ---: | ---: | ---: | --- |
| Bore | 0/16 | 16/16 | 12/16 | 0 | 4 ambiguous |
| OD | 0/16 | 16/16 | 13/16 | 0 | 3 ambiguous |
| Thickness | 0/16 | 16/16 | 12/16 | 0 | 1 ambiguous, 3 not detected |
| Material | 0/16 | 16/16 | 16/16 | 0 | none |
| Units | 0/16 | 16/16 | 16/16 | 0 | none |
| Bore tolerance plus | 0/16 | 16/16 | 13/16 | 0 | 3 ambiguous |
| Bore tolerance minus | 0/16 | 0/16 | 0/16 | 0 | 3 ambiguous, 13 not detected |
| Quantity | 0/16 | 11/16 | 4/16 | 1 confirmation-only wrong reading | 11 not detected |

The missing tolerance-minus result is the clearest ceiling observed: Tesseract
usually converted the printed plus/minus glyph into a plain plus or another glyph.
The rules retained a possible plus-side reading but did not invent symmetry.

Document drawing number and revision were recovered from native title-block text
using label proximity and were strong on both files. Chamfer, marking scope, and
customer part number were not safely established as authoritative selected-region
values.

### Per-region outcome

Each cell below reports correct ground-truth fields out of the eight benchmarked
fields; failures remain abstentions/ambiguities unless explicitly noted.

| Export | Region | Correct | Unresolved or incorrect |
| --- | --- | ---: | --- |
| Layout1 revision B | r1c1 | 7/8 | tolerance minus not detected |
| Layout1 revision B | r1c2 | 6/8 | thickness and tolerance minus not detected |
| Layout1 revision B | r1c3 | 5/8 | thickness not detected; tolerance sides ambiguous |
| Layout1 revision B | r1c4 | 6/8 | quantity and tolerance minus not detected |
| Layout1 revision B | r2c1 | 5/8 | thickness ambiguous; quantity and tolerance minus not detected |
| Layout1 revision B | r2c2 | 6/8 | quantity and tolerance minus not detected |
| Layout1 revision B | r2c3 | 7/8 | tolerance minus not detected |
| Layout1 revision B | r2c4 | 3/8 | bore/OD ambiguous; thickness and tolerance minus absent; quantity was a wrong confirmation-only reading |
| Model/base export | r1c1 | 6/8 | quantity and tolerance minus not detected |
| Model/base export | r1c2 | 6/8 | quantity and tolerance minus not detected |
| Model/base export | r1c3 | 5/8 | bore ambiguous; quantity and tolerance minus not detected |
| Model/base export | r1c4 | 5/8 | quantity absent; both tolerance sides ambiguous |
| Model/base export | r2c1 | 5/8 | bore ambiguous; quantity and tolerance minus not detected |
| Model/base export | r2c2 | 5/8 | OD ambiguous; quantity and tolerance minus not detected |
| Model/base export | r2c3 | 5/8 | bore ambiguous; quantity and tolerance minus not detected |
| Model/base export | r2c4 | 4/8 | OD and both tolerance sides ambiguous; quantity not detected |

No wrong critical bore, OD, thickness, material, unit, or bore-tolerance value was
promoted. The one wrong quantity result remained `requires_confirmation` and did
not become an authoritative whole-sheet or canonical value.

## DPI and performance observations

The representative first region produced the same six of seven critical-field
results at 300, 400, and 600 DPI; the unresolved field was tolerance minus.

| DPI | Pixels | PNG | Approx. grayscale memory | Render | Two-pass OCR |
| ---: | --- | ---: | ---: | ---: | ---: |
| 300 | 1126 x 1182 | 75 KB | 1.33 MB | 0.14 s | 0.73 s |
| 400 | 1502 x 1575 | 107 KB | 2.37 MB | 0.14 s | 0.83 s |
| 600 | 2254 x 2365 | 162 KB | 5.33 MB | 0.18 s | 1.05 s |

300 DPI is therefore the default: higher DPI increased pixels/memory and OCR time
without improving this region's recognition result.

Across all 16 regions in one sequential run:

- two-document normalization: approximately 2.23 seconds total;
- structure/region derivation: under 0.001 seconds total after normalization;
- rendering: approximately 2.12 seconds total;
- two-pass OCR: approximately 12.93 seconds total;
- deterministic interpretation: approximately 0.17 seconds total;
- mean selected-region render/OCR/interpretation time: approximately 0.95 seconds.

The initial PDF normalization cost is roughly one second per document and can be
reused across selected-region operations. Sequentially processing all eight regions
is slower than the intended explicit one-region interaction and was done only for
benchmarking.

## Failure taxonomy

- OCR failure: plus/minus glyph loss, compact fractions, missed quantity words,
  and occasional conflicting dimension readings.
- Normalization limitation: safe contextual fraction repairs recover many but not
  all thicknesses; no decimal point is inserted merely to create a plausible value.
- Spatial binding limitation: four bore and three OD cases retain equally plausible
  candidates and abstain.
- Geometry-binding limitation: concentric profiles support role classification,
  but leader-line endpoints are not yet robustly bound.
- Drawing ambiguity: marking scope and chamfer meaning cannot be made authoritative
  from a weak or purely graphical signal.
- Unsupported-domain behavior: synthetic tests confirm clearly read unsupported
  material/dimensions remain observed and are rejected separately by domain rules.
- Missing information: customer part number is not inferred from contract/tag
  identifiers.
- Parser weakness: quantity line reconstruction needs improvement and produced one
  confirmation-only wrong reading.

## Deterministic ceiling and next step

The evidence supports continuing the deterministic architecture. Region detection,
local OCR, material, units, drawing metadata, and most labeled OD/bore readings are
readily solvable. The remaining failures are mostly engineering problems—targeted
glyph preprocessing, line reconstruction, tolerance grammar, and stronger spatial
association—not proof that generative interpretation is required.

Phase 1C should remain deterministic and focus on:

1. targeted callout crops and binarization/scale experiments for tolerance and
   fraction glyphs;
2. explicit multi-pass glyph reconciliation that preserves unilateral versus
   symmetric meaning;
3. stronger line reconstruction for thickness and quantity;
4. carefully bounded leader-line association for bore/OD verification;
5. an 8-10 drawing independent corpus before any production accuracy claim.

The highest-value next corpus is three clean single-plate digital PDFs from
different templates, one unilateral tolerance, one bilateral tolerance, a chamfer
and no-chamfer pair, one metric drawing, one degraded scan, and one genuinely
ambiguous print. Categories may overlap, but source groups must be independent and
critical-field ground truth adjudicated.

Generative vision is not recommended for Phase 1C. It should remain only a future
research option if broader examples reveal genuinely semantic variation that
targeted OCR, grammar, spatial topology, and vector evidence cannot handle
economically.
