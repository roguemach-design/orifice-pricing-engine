> Current controlled-print implementation: [PHASE3D_REVIEW.md](PHASE3D_REVIEW.md). This document is historical; its review artifacts are now under `prototype_output/archive/phase3c/`.

# Phase 3C — NTS drawing template review

Branch: `work/deterministic-manufacturing-prototype`.
Baseline checked before edits: `9157f5b58b18519c46dfe2be11ddca8863d0bda7`.
The resulting commit is the local commit containing this report (`git log -1`). No push, PR, deployment, production configuration, payment, database or fulfillment changes were made.

## Result and visual review

The renderer now produces a compact NTS engineering data sheet. The actual owner crop was inspected and used as the controlling composition reference. The golden sample was rendered first, compared visually, then the illustrative chamfer sheet was inspected at full-sheet and enlarged-detail sizes. The normal package generator now uses that layout. This is a development template lock based on this visual review, not a claim of owner approval or manufacturing release.

| Visual criterion | Phase 3C treatment / comparison |
|---|---|
| Overall composition | Underlined centered heading, dominant paddle at left, adjacent section at right, compact lower-left ruled data |
| Paddle prominence | 224-point circle dominates the main view; deliberately visible 132-point bore |
| Handle proportion | Upward handle extends only 35 points beyond the paddle's top; actual 10.500 label is unchanged |
| Heading | Single restrained rule and uppercase title; no corporate reference identity |
| Dimension density | Width above handle; nearby C/L-to-end dimension; no page-spanning true-length bar |
| Leaders / bore / OD | Finished-bore leader below-left; OD leader below-right; marking leader above-left |
| Section size / location | 18-point thickness for this sample, adjacent to plan and vertically aligned at tip, bore and paddle bottom |
| Flow | Immediately right of section; direction follows structured input; unspecified direction says ORIENTATION ONLY |
| Lower data block | Three unboxed ruled rows: quantity, thickness and material; optional order fields occupy reserved rows |
| Whitespace | View, data and short notes have separate compact regions; secondary footer retains traceability |
| Typography | Uppercase compact sans-serif; bold marking/bore/flow; small HOLD text remains secondary |
| Line weights | Strong 1.15-point plan outline; .7 section outline; .25 hatch; .35 centerlines; .4 dimensions/data rules |
| Engineering character | Conventional leaders, arrows, centerlines, hatching and ruled fields replace the earlier long proportional view |

The side-by-side now reads as the same type of engineering data sheet. It intentionally differs in font, unsupported reference fields and corporate identity. The sample has no invented chamfer ring, bevel, tolerance, marking text or upstream instruction. Its section has actual open bore space; the complete chamfer configuration is demonstrated separately. Reference process fields are omitted. The Letter sheet includes a compact O-Plates prototype footer.

## Exact geometry versus NTS presentation

`PlateSpec` → `build_plate_geometry` and `build_section_geometry` remain the exact sources for dimensional facts. No changes were made to those builders or to the DXF/SVG/JSON exporters.

`manufacturing_drawing.Presentation` contains **paper points only**: view location, visual paddle/bore radii, handle-tip height and section thickness. It cannot feed back into the manufacturing specification. The plan rotates the existing canonical arcs upward. The paddle and neck arcs retain their canonical parameters; tip arcs translate, and their connecting straight sides shorten for display. The bore has an independent visual radius. All dimensional labels still come from `PlateSpec` or exact derived section data.

For the sample, the literal plan-scale handle length would be 470.4 points; its NTS center-to-tip display is 147 points. The actual label stays **10.500**. Literal plan-scale thickness would be 5.6 points; the section displays 18 points while labeling **0.125**. The drawing and detail explicitly say NTS; the controlled note says DO NOT SCALE DRAWING.

The section maps exact polygon vertices into NTS paper coordinates. Bore-adjacent bevels use the same local x/y scale so the configured angle remains correct, while overall plate/handle lengths are schematic. Extremely large bevels cap that local scale to fit the radial band. The separate cropped bore-edge detail uses a uniform enlargement and a conventional broken edge.

Illustrative configuration only: radial width **0.040**, angle from face **45°**, downstream face, left-to-right flow. Exact calculation:

- axial depth = radial width × tan(angle from face) = **0.0400**;
- cylindrical land = thickness − axial depth = **0.0850**;
- right-hand face is downstream for this flow direction.

Opposite side/flow combinations mirror the section. No-chamfer yields rectangles and NONE. Missing required chamfer parameters yield rectangles and INCOMPLETE - HOLD; no fictitious bevel is shown. There is no automatic release mechanism; every output remains marked not released for manufacture.

## Regression results

Python 3.12.14, ReportLab 5.0.1, ezdxf 1.4.3. Full suite: **197 passed**, zero failures, two existing Starlette/httpx and AnyIO deprecation warnings.

| Suite | Passed |
|---|---:|
| Existing application tests | 102 |
| Manufacturing geometry / file tests | 48 |
| Existing PDF drawing tests | 12 |
| Exact section / chamfer tests | 16 |
| New NTS presentation / visual fixture tests | 19 |
| **Total** | **197** |

The counts include determinism checks, not additional duplicated runs: repeat generation in-process, subprocess hash seeds 1/2/17, and a locked golden PDF hash. All existing tests were retained without weakening geometry tolerances. New tests verify exact labels under changed presentation settings, unchanged manufacturing JSON/DXF/SVG, upward rotation and shortened handles, section exaggeration, all side/flow combinations at 30/45/60 degrees, none/incomplete states and the golden fixture.

DXF audit, both sample packages: **0 errors, 0 fixes**, inches (`$INSUNITS=1`), exactly one closed CUT_OUTER polyline and one CUT_BORE circle. Sample DXF is byte-identical to both the Phase 3B baseline and Phase 2 commit `dacdbbc675d4db5c2ddd2624995ba3f24306a033`.

DXF SHA-256: `704abfa62d0bef0b3ac91d97a58bc0dfa7f093418d87f12ae3763d12118ecfb8`.

Regenerated sample JSON and SVG are also byte-identical to Phase 3B. JSON contains `straight-handle-r03125-v2-prototype`, four R0.03125 corner arcs, finished bore 1.548, rough bore 1.423 and radial stock 0.0625. Regeneration yielding identical bytes is expected: NTS coordinates are deliberately absent from the manufacturing record. No obsolete sharp-tip v1 inputs were used.

## Visual regression and reproduction

`tests/fixtures/phase3c-golden-layout.sha256` locks the complete deterministic PDF bytes for the canonical sample. This catches vector geometry, labels, fonts and layout changes together. The tracked PDF and PNG are reviewable companions. It is a development-only assertion; production generation never runs image comparison. Dependency upgrades may legitimately change bytes and require an explicit visual review and fixture refresh; pixel similarity alone is not an acceptance test.

From the repository root:

```bash
.venv/bin/python scripts/review_phase3c.py --reference /path/to/owner-crop.png
.venv/bin/python -m pytest -q
```

Only after reviewing intentional changes, append `--update-fixture` to refresh the development hash. The owner source file remains external; the comparison includes it for review only. Output names are stable under `prototype_output/`.

## Files and artifacts

- `manufacturing_drawing.py`: isolated NTS presentation, compact template and enlarged section/detail.
- `prototype_manufacturing.py`: reusable exact sample specification for CLI and fixture tests.
- `scripts/review_phase3c.py`: development regeneration, Poppler renders, side-by-side comparison and explicit fixture refresh.
- `tests/test_drawing_presentation.py`, `tests/fixtures/phase3c-golden-layout.sha256`: 19 targeted cases and golden lock.
- `PHASE3C_REVIEW.md`: this current report; `MANUFACTURING_PROTOTYPE.md` now points here while preserving historical Phase 2 notes.
- `prototype_output/phase3c-golden-layout.pdf` and `.png`: golden sheet.
- `prototype_output/phase3c-comparison.png`: owner crop / golden side-by-side.
- `prototype_output/phase3c-chamfer-review.pdf` and `.png`: illustrative, non-default configuration.
- `prototype_output/phase3c-chamfer-detail.png`: enlarged detail render.
- Existing sample and chamfer review packages regenerated; PDF/PNG changed, exact DXF/JSON/SVG stayed identical. `reference-comparison.png` now shows the current comparison.

## Remaining owner decisions

Visual template acceptance; bore tolerance; chamfer selection and size convention/angle/side/flow; marking text, method and placement; edge/bore/surface finish; general tolerances and inspection requirements. None have been inferred from the reference. Arbitrary configurations and long optional annotations will need additional layout review before production adoption; this phase intentionally locks the representative sample first.

The prototype demonstrates deterministic DXF and NTS manufacturing-print generation without Fusion or an LLM runtime. Eventual integration should freeze a validated order-line specification, version/hash the geometry and renderer, retain generated package bytes, and require release review until manufacturing requirements and shop CAM acceptance are resolved. No integration or release automation is implemented here.
