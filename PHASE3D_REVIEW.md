> Superseded for base-product scope by [Phase 3E](PHASE3E_REVIEW.md). Metering research and prior release questions are not requirements for restriction/general plates.

# Phase 3D — Controlled manufacturing print

Branch: `work/deterministic-manufacturing-prototype`.
Starting HEAD: `af6af2ef3c8829fcf9b711abe1290db75a3eb30d`.
The resulting local commit is the commit containing this report (`git log -1`). Nothing was pushed, deployed, integrated into fulfillment or changed in production.

## Current package

The normal CLI produces `prototype_output/current/OP-PROTOTYPE-001.pdf` and `OP-PROTOTYPE-001.dxf`, with matching internal `OP-PROTOTYPE-001.json`. The PNG is a review derivative. The PDF is the finished-part confirmation/manufacturing reference; the DXF is the rough blank. SVG is not emitted by the job-package path and is not a manufacturing deliverable.

The single PDF renderer now implements Phase 3D. Earlier sample and Phase 3C review files were moved to `prototype_output/archive/phase3c/`, including the historical golden hash. There is no second active PDF layout. The low-level `generate_package` helper remains available for internal tests/debug exports; the CLI uses `generate_job_package`.

Stale protection: job generation checks the supplied geometry against a fresh canonical build, checks the record version, rejects unrelated files in the destination, and invalidates an old PNG when regenerating the authoritative pair. No stale JSON is read as source data. The sample and illustrative chamfer use separate folders to avoid mixed packages.

## Drawing conversion

The accepted Phase 3C paper coordinates and NTS proportions remain unchanged: dominant circular paddle, short upward handle, nearby dimensions, marking upper-left, section right and compact ruled lower data. Visual review of the rendered sample, chamfer sheet and reference comparison confirmed those relationships remain intact.

Changes:

- Heading is **ORIFICE PLATE**.
- Diameter labels are **Ø1.548** and **Ø5.000**, without redundant OD/DIA wording.
- Handle and center-to-end dimensions are **2.000** and **10.500**, without descriptive text inside the dimension.
- Canonical corner arcs and **4X R 0.03125** remain exact.
- Section cutting-plane arrows marked A correspond to **SECTION A-A**. These are section identifiers, not datum symbols.
- Configured chamfer uses **DETAIL B - BORE EDGE - NTS**, with a B locator on the section so it is distinct from Section A-A.
- Flow arrow appears only with explicit structured direction. Missing orientation is HOLD; explicit no-chamfer/no-flow omits it.
- Rough-DXF allowance and kerf language have been removed from the finished drawing face.
- No datums, datum reference frames or unapproved geometric feature-control frames were added.

ASME Y14.5 is identified as the **drafting basis**, not a claim of a fully approved or standards-certified released drawing. ASME's official [Dimensioning and Tolerancing overview](https://www.asme.org/codes-standards/find-codes-standards/dimensioning-and-tolerancing) was checked narrowly for scope. No broad standards research or adoption of unapproved default tolerances was performed.

## Title block and structured fields

The 112-point-high bottom title block contains company, title, part number, drawing number, drawing revision, material, thickness, quantity, INCHES, NTS, 1 OF 1 and ASME Y14.5. Generator and geometry version occupy small traceability fields; specification revision is explicitly HOLD until supplied. Prototype numbering is **PROTOTYPE-001 / OP-PROTOTYPE-001**, not a production numbering policy. No timestamps are inserted.

A dedicated UNLESS OTHERWISE SPECIFIED block reserves .X, .XX, .XXX and ANGLES, all HOLD. `DrawingMetadata` supports explicit approved tolerance text, surface/edge/inspection notes, marking method/location and specification revision. Existing structured bore tolerance, marking text, customer tag, order and line references remain supported. No numerical tolerance or finish was selected. Every drawing remains **PROTOTYPE - NOT RELEASED FOR MANUFACTURE**; no release automation exists.

## Exact geometry and numerical verification

The baseline was checked before edits: `straight-handle-r03125-v2-prototype`, one plate arc and four corner arcs of exactly 0.03125. `plate_geometry.py` and `section_geometry.py` were not changed.

| Requirement | Verified value, inches |
|---|---:|
| Finished OD | 5.000 |
| Finished bore on PDF | 1.548 |
| Handle width | 2.000 |
| Centerline to handle end | 10.500 |
| Corner radius, four places | 0.03125 |
| Thickness | 0.125 |
| DXF rough bore | 1.423 |
| Bore diameter allowance | 0.125 |
| Radial stock per side | 0.0625 |

Material is 304 stainless steel; quantity is 1. PDF independently reopened with `pdftotext`: all finished values are present; 1.423, DXF, undersize and kerf wording are absent.

Actual saved DXF reopened with ezdxf: inches (`$INSUNITS=1`), exactly one closed LWPOLYLINE on CUT_OUTER and one CIRCLE on CUT_BORE; **zero audit errors, zero fixes**. Reloaded vertices/bulges match the canonical external contour to 1e-12 absolute tolerance, zero relative tolerance. No dimensions, title blocks or NTS presentation entities occur in the file. The DXF remains byte-identical to Phase 2 commit `dacdbbc675d4db5c2ddd2624995ba3f24306a033`.

DXF SHA-256: `704abfa62d0bef0b3ac91d97a58bc0dfa7f093418d87f12ae3763d12118ecfb8`.

The exact formula remains **1.548 − 0.125 = 1.423** on diameter; **0.125 / 2 = 0.0625** stock per side. The current JSON contains the r03125 version and has no obsolete sharp-tip v1 assumptions.

## Chamfer review

Separate illustrative configuration, explicitly labeled not a default: radial width .040, angle from face 45 degrees, downstream, left-to-right flow. Exact section math is unchanged: axial depth = radial width × tan(angle from face) = .0400; straight land = .125 − .0400 = .0850. Section and enlarged detail preserve angle, face and topology. The PDF labels exact values independently of paper coordinates.

No chamfer: rectangular section, CHAMFER: NONE, no detail. Incomplete selection: rectangular placeholder section, INCOMPLETE - HOLD, no invented bevel. Side/flow mirror and angle tests remain intact. No automatic release is implemented.

## Visual and automated acceptance

Rendered PDFs were inspected, not merely text-extracted. The sample retains the accepted compact composition; dimensions remain adjacent to their features. The title block reads as a conventional manufacturing identity and tolerance area. Section A-A and Detail B identifiers are distinct, detail hatch/angle/land labels are legible, and missing requirements remain secondary. No clipping or overlapping labels were observed on the representative sheets. Broader arbitrary-size and long-annotation acceptance remains future work.

The Phase 3C hash was deliberately replaced by `tests/fixtures/phase3d-manufacturing-print.sha256`, now using the actual OP-PROTOTYPE-001 PDF. This locks composition, type, dimensions and title block together in the pinned environment. The tracked PNG provides a visual companion. Hash refresh is explicit and requires visual review; production generation has no image-comparison dependency.

| Suite | Passed |
|---|---:|
| Application | 102 |
| Manufacturing geometry/files | 48 |
| Existing drawing | 12 |
| Exact section/chamfer | 16 |
| NTS presentation / visual fixture | 19 |
| New controlled-package checks | 11 |
| **Total** | **208** |

Zero failures; two existing Starlette/httpx and AnyIO deprecation warnings. All prior tests retained; only intentionally changed drawing strings and the golden fixture were updated. Manufacturing geometry tolerances were not loosened. Determinism includes repeated generation, subprocess hash seeds 1/2/17, paired-package bytes and the golden PDF hash.

## Files changed

- `manufacturing_drawing.py`: conventional callouts, section/detail identification, title block and approved-note fields.
- `manufacturing_files.py`: guarded job package, optional internal SVG and raster invalidation; DXF geometry logic untouched.
- `prototype_manufacturing.py`: current paired naming and isolated illustrative package.
- `scripts/review_phase3d.py`: replaces Phase 3C review script; regenerates current pair, PNGs, optional comparison and explicit fixture refresh.
- Existing drawing/presentation test expectations updated; `tests/test_controlled_package.py` added; golden hash updated.
- Historical outputs segregated; current, chamfer-review and debug outputs generated.
- This report and current-report pointers added.

Reproduce from repository root:

```bash
.venv/bin/python prototype_manufacturing.py --chamfer-review
.venv/bin/python scripts/review_phase3d.py --reference /path/to/owner-crop.png
.venv/bin/python -m pytest -q
```

Add `--update-fixture` to the review script only for intentionally reviewed visual changes. The owner crop is optional and is never required for manufacturing file generation.

## Remaining owner decisions

Bore and general tolerances; chamfer convention and selected parameters; marking requirements or explicit none, method and location; surface/bore/edge finish; inspection criteria; production numbering and specification revision conventions; final shop/owner visual acceptance and CAD/CAM import acceptance. None were invented. The PDF and rough DXF are deterministic outputs from the same specification, with no Fusion, CAD application or LLM runtime dependency.
