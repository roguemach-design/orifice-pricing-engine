# Drawing intake Phase 1C: deterministic generalization

## Purpose and boundary

Phase 1C extends the isolated, local drawing-recognition spike. It adds no upload
UI, pricing call, checkout behavior, customer storage, deployment, cloud OCR, or
generative inference. Manufacturing interpretation remains explicit code:

`document -> classify -> region/table -> local render -> local OCR -> engineering grammar -> spatial/geometric binding -> field rules -> existing validation -> result`

Tesseract 5.3.4 and the installed English data remain the only OCR dependency.
All page pixels and text stay local. Tesseract is Apache-2.0 licensed; absence of
the executable remains an explicit error rather than a cloud fallback.

## Document classification

`classify_drawing_document` produces one of:

- `single_plate_drawing`;
- `multi_plate_drawing`;
- `table_driven_plate_schedule`;
- `reference_vendor_datasheet`;
- `ambiguous_document`;
- `unsupported_document`.

Rules use concentric-profile counts, ruled grids, semantic schedule headers,
multiple generic product headings, dimension-variable legends, and catalog or
ordering language. Company names and drawing numbers are not inputs. A reference
sheet can contain recognizable plate geometry and numeric tables while remaining
non-quote-specific.

## Targeted callout OCR and preprocessing

The selected-region path first performs the Phase 1B 300-DPI PSM 6/11 passes.
Only unresolved BORE, DIA/OD, THK, and quantity neighborhoods are then expanded
in source coordinates and rendered at 600 DPI. The BORE neighborhood also gets an
Otsu-thresholded variant. Raw observations are retained, targeted tokens are
marked, and their purpose is scoped so a bore crop cannot change material,
quantity, or another detector.

Targeted variants are corroboration, not independent observations. A repaired
value or a value that wins over a competing base reading remains
`requires_confirmation`. The implementation does not rerun high-resolution OCR
when the base evidence is already sufficient.

The useful preprocessing experiments were:

- expanded 600-DPI neighborhoods recovered leading digits lost by whole-region
  OCR;
- contextual compact-fraction grammar recovered `Y%4`/similar distortions as
  `1/4` only next to a thickness label;
- thresholding preserved some tolerance glyph structure but did not itself
  justify a tolerance interpretation;
- high-resolution full-page/table OCR did not materially improve the schedule
  cells and was not retained as a recurring cost.

## Tolerance glyph rule

CAD-outline `±` glyphs were commonly emitted as `+`, `£`, or `#` plus a number.
Text substitution alone is unsafe, so Phase 1C inspects the original token pixels.
A `+`/`£`/numeric-prefix glyph becomes `±` only when its crop contains two
separated, substantial horizontal ink bands: the plus crossbar and lower minus
bar. The rule name and raw OCR text remain attached to the token.

A single crossbar remains a plus. `+0.005` therefore remains a partial unilateral
tolerance and never becomes symmetric merely because symmetry is common. Decimal
comma repair is limited to tolerance context and is also recorded. All visual or
punctuation repairs require confirmation.

## Evidence rules

| Critical field | Strong / verified | Confirmation | Ambiguous / abstain |
| --- | --- | --- | --- |
| Bore | Two base OCR modes agree on a BORE-adjacent value; concentric profiles corroborate; bore is less than OD | Targeted OCR, contextual repair, or dominant reading over a competitor | Equal competing labeled values or no local label/value pair |
| OD | Two base modes agree on an OD/DIA-adjacent value; geometry corroborates; OD is greater than bore | Targeted OCR, repair, or resolved competition | Equal competitors or no local pair |
| Thickness | Two unmodified base readings agree on a THK/THICK value with explicit unit | Compact-fraction or targeted recovery | Competing or missing local thickness callout |
| Material | Same selected-region material phrase appears in two base modes | One base-mode phrase | Multiple recognized materials or none |
| Units | Repeated explicit units agree across base modes | One explicit observation | Conflicting inch/metric evidence or none |
| Bore tolerance | Complete BORE-bound grammar without repair | Visual glyph recovery, decimal-comma repair, targeted OCR, or unilateral/partial syntax | Competing complete tolerances, incoherent magnitude, unreadable/missing side |

Downstream catalog support remains separate. A clear but unsupported value is
retained as the drawing observation and rejected by the existing validator; it is
never replaced with a supported catalog value.

## Generic table schedule parser

`TableScheduleParser` uses grayscale projection profiles to locate substantial
horizontal and vertical rules, then assigns OCR tokens by cell center. Top-level
section text scopes repeated headers such as OD and THK to the `ORIFICE PLATE DIM`
section instead of flange or pipe columns. The parser binds tag, quantity, OD,
thickness, bore, tolerance, material, and units while retaining cell provenance.

Every row is a separate confirmation-required candidate. The parser never picks a
row and `quote_candidate_created` is always false. Tests shift the entire grid to
prove the parser is not tied to the observed source coordinates.

## Generalization findings

The untouched Phase 1B baseline was captured before tuning.

| Source group | Phase 1B behavior before Phase 1C |
| --- | --- |
| Original correlated `706928890` family | Bore 12/16; OD 13/16; thickness 12/16; material/units 16/16; tolerance plus 13/16, minus 0/16; quantity 4/16 correct plus one confirmation-only wrong reading |
| Independent `836026-204-03` | Bore 7/8 plus one confirmation-only wrong reading; OD 5/8; thickness 6/8 plus two confirmation-only wrong readings; material/units/tolerance-plus 8/8; tolerance-minus 0/8; quantity 6/8 |
| Independent `cc300120404` | One misleading vector-profile candidate; no manufacturing fields; units ambiguous |
| Reference datasheet | Unknown document, no candidate and no fields |

After Phase 1C:

| Source group | Class / candidates | Bore | OD | Thickness | Material / units | Bore tolerance | Quantity | Safety |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `706928890` | multi-plate / 8 per document | 16/16 | 13/16, 3 ambiguous | 13/16, 2 missing, 1 ambiguous | 16/16 | plus 14/16; minus 12/16, all repaired/confirmation | 10/16 correct, 5 missing, 1 confirmation-only wrong | No wrong critical value strong/verified |
| `836026-204-03` | multi-plate / 8 | 8/8 | 8/8 | 8/8 | 8/8 | plus/minus 8/8, repaired/confirmation | 8/8 | No wrong critical value strong/verified |
| `cc300120404` | table schedule / 13 rows | 13 row values reconstructed | 13 | 13 | 13 | 11/13 rows; 2 abstentions | 5/13 observed, remainder abstained | No row selected; no canonical candidate |
| Reference datasheet | reference / non-quote-specific | Not scored | Not scored | Not scored | Not scored | Not scored | Not scored | Tables/variables never become a quote |

The first two rows above use adjudicated private region ground truth. The schedule
row counts describe deterministic reconstruction and visual characterization, not
a production accuracy claim; it still needs a separately adjudicated row-level
ground-truth record. Regions within a sheet are correlated and are not counted as
independent customer drawings.

## Table and reference-sheet findings

The alternate schedule page is sideways in the source PDF. A local orientation
comparison accepted a 90-degree rotation only after readable engineering-term
evidence materially exceeded the original orientation. The ruled grid then
yielded 13 rows. PSM 11 retained decimal points more reliably than PSM 6, so table
cell binding prefers PSM 11 while preserving both raw passes. OD, thickness, bore,
316 stainless material, and millimeter units reconstructed for all rows. Eleven
tolerance cells reconstructed; two safely abstained. Quantity OCR remains weak
and all row fields require explicit row selection/confirmation.

The reference sheet was classified from multiple generic product types, a
symbolic dimension legend, catalog language, and selection tables. It exposed 25
generic table rows to the structural parser but remained
`reference_vendor_datasheet`, `quote_specific=false`, and produced no canonical
candidate. This proves that “contains O-Plate information” is not treated as
“specifies one ordered plate.”

## Performance

Representative final local runs on this development environment were:

- selected detail region: approximately 2.3-2.5 seconds mean when targeted
  600-DPI OCR was needed, versus approximately 0.9 seconds for the Phase 1B base
  path;
- whole repeated-detail page classification: approximately 6.3 seconds;
- sideways table page classification, orientation OCR, and grid interpretation:
  approximately 11.3 seconds after dropping an unproductive recurring high-DPI
  table pass;
- reference JPEG classification: approximately 4.6 seconds.

These are sequential spike measurements, not optimized service targets. Document
normalization and page observations can be reused in an interactive workflow.

## Remaining limitations and deterministic ceiling

- OD remains ambiguous in three original-family regions because targeted text and
  profile evidence do not uniquely bind competing local dimensions.
- Three original-family thicknesses remain missing/ambiguous.
- Quantity reconstruction improved but remains secondary and produced one known
  confirmation-only wrong reading.
- Tolerance recovery is effective on the observed outline glyph, but every
  repaired tolerance still requires confirmation; other fonts/scans need tests.
- The schedule parser reconstructs rows but does not yet have formal adjudicated
  ground truth, robust tag cleanup, or reliable quantity coverage.
- Lightweight leader-line analysis was reconsidered. Mixed text-outline,
  dimension, centerline, and profile segments still make endpoints brittle; no
  leader rule was promoted merely to improve coverage.
- Scanned/degraded and phone-photo inputs remain largely untested.

The architecture generalizes beyond the original repeated-detail template:
engineering grammar, local OCR provenance, region isolation, material/units,
glyph evidence, and grid topology are reusable. A specialized
`TableScheduleParser` is justified; a customer- or drawing-number parser is not.
The remaining failures are predominantly OCR preprocessing, local binding, and
corpus-diversity engineering problems. There is no evidence from this phase that
generative interpretation is necessary.

## Running tests

```bash
.venv/bin/pytest -q tests/test_drawing_phase1c.py
.venv/bin/pytest -q tests/test_drawing_deterministic.py tests/test_drawing_intake.py
.venv/bin/pytest -q
.venv/bin/black --check drawing_intake tests/test_drawing_intake.py tests/test_drawing_deterministic.py tests/test_drawing_phase1c.py
git diff --check
```

Private PDFs, JPEGs, derived crops, and adjudicated private ground truth stay
under `drawing_corpus/private/`, which is git-ignored.

## Smallest next step

Phase 1D should add the smallest high-information corpus: three independently
sourced, clean single-plate digital PDFs from different organizations; one metric
unilateral-tolerance print; one bilateral-tolerance print; one chamfer and one
explicit no-chamfer example; one older degraded scan; and one genuinely ambiguous
print. Categories may overlap. Ground truth should include critical field values,
document type, explicit abstentions, and source regions.

First adjudicate the 13 schedule rows, then rerun the per-source safety audit. Only
after that should a selected-region/manual-configuration reconciliation prototype
be considered. No customer-facing integration is implied.
