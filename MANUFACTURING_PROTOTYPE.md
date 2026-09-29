> Current controlled-print implementation: [PHASE3D_REVIEW.md](PHASE3D_REVIEW.md). This document is historical; its review artifacts are now under `prototype_output/archive/phase3c/`.

> Current drawing-template review: [PHASE3C_REVIEW.md](PHASE3C_REVIEW.md). The following is the historical Phase 2 geometry report; its old drawing-layout/reference statements are superseded.

# O-Plates manufacturing prototype — Phase 3B

## Result and visual review

Recomposed the print from the owner-highlighted crop, not from the former boxed landscape template. The sheet is now US Letter portrait, one plate per sheet: centered ruled heading, upright plan, marking at upper left, adjacent longitudinal section, compact direct leaders, three-row quantity/thickness/material data, short controlled notes, and small secondary identity/revision block. No company artwork, customer data, tolerance values, stamping requirement or surface-finish standard was copied.

The missing-image message was transient: the supplied screenshot was available and visually inspected. The final sample and chamfer-review sheets were rendered and inspected. `prototype_output/reference-comparison.png` places the actual supplied crop beside the new example for owner review.

Visual acceptance answers:

- Organization/density: the upright drawing/section/data arrangement now follows the crop; the large notes box is gone.
- Marking: compact upper-left block adjacent to the handle, sourced from structured marking text. Missing method/location remain HOLD.
- Dimensions: width above handle, C/L dimension immediately beside handle, finished-bore and OD leaders beside paddle, exact four-radius note beneath it.
- Section/FLOW: immediately beside plan and vertically aligned, with generated hatching and adjacent flow arrow.
- Lower data: three compact ruled rows for quantity, thickness and normalized material; supplied optional tag/order/service fields only.
- Notes/title: short controlled requirements; compact footer occupies about 8% of page height.
- Plate proportions: deliberately not identical to the reference's schematic proportions. A true 10.500-inch center-to-tip length with a 5.000-inch OD produces a much longer-looking handle. Canonical geometry and uniform scale are preserved. Literal silhouette similarity would require an explicitly approved broken-length or NTS convention; this phase does not silently distort the contour. Owner visual acceptance remains necessary.

Portrait Letter was chosen for the vertical data-sheet module and common US shop printers. The complete view remains proportional. The actual small chamfer is also shown in a uniformly magnified local detail, with scale and crop break, so the shop can read its dimensions without artificial exaggeration.

## Parametric section and application inputs

New `build_section_geometry(spec)` in `section_geometry.py` creates an immutable longitudinal section through the handle and bore. It drives both the full section and enlarged chamfer detail/labels. The positive radial material extends to the handle tip; the negative radial material extends to the paddle edge. This replaces Phase 3's transverse section, intentionally aligning the full side view with the reference's handle/bore organization.

Existing application inspection confirmed chamfer selected and chamfer width only. The current configurator does not establish angle, side, flow direction or what dimension its width means. No existing width is silently interpreted. `PlateSpec` and its configuration adapter now preserve optional explicit angle, side, flow orientation and width convention; existing customer UI/API/pricing are unchanged.

Supported explicit dimensional conventions:

- `radial-angle-from-face`: radial width w, angle alpha from the plate face, axial depth d = w tan(alpha).
- `axial-depth-angle-from-face`: entered axial depth d, radial width w = d / tan(alpha).
- Remaining straight bore land = thickness minus d; chamfer opening diameter = finished bore + 2w.
- Upstream/downstream side and left-to-right/right-to-left flow determine the actual face. Reversing either mirrors the section through thickness.
- Positive wall and land are mandatory. Over-thickness chamfers, exhausted radial wall, nonfinite or nonpositive dimensions fail. Values within 1e-12 inches of a zero-land/wall boundary are rejected as numerically degenerate, rather than accepting floating-point remnants.

These are named opt-in input conventions, not approved O-Plates defaults. The owner must confirm the application's intended chamfer-size convention before real order integration.

Behavior:

| Input | Section result |
| --- | --- |
| Chamfer false | Rectangular nominal side profile; CHAMFER: NONE |
| Chamfer true, complete/valid | Actual configured bevel, size/angle, thickness, depth and remaining land |
| Chamfer true, incomplete | CHAMFER: INCOMPLETE - HOLD; missing inputs identified; no bevel invented |
| Chamfer unspecified | CHAMFER: NOT SPECIFIED - HOLD; nominal profile only |
| Impossible complete chamfer | Explicit error before package files are written |

No release path exists. A prototype package with missing inputs is a review artifact carrying HOLD, not a released manufacturing instruction. A missing flow field produces an explicitly orientation-only arrow, never a claimed customer requirement.

## Review artifacts and examples

Standard sample: OD 5.000, finished bore 1.548, width 2.000, center-to-tip 10.500, R0.03125 corners, 304 stainless, thickness 0.125; chamfer remains unspecified. DXF rough bore remains 1.423 (0.125 diameter reduction / 0.0625 radial stock).

`sample-plate-chamfer-review.pdf` uses explicitly illustrative values: 0.040 radial width, 45 degrees from face, downstream face, left-to-right flow, thickness 0.125. Calculated axial depth is 0.040 and remaining straight land is 0.085. The sheet says ILLUSTRATIVE CHAMFER VALUES - NOT DEFAULTS; these are not customer choices or production standards. Its JSON records the exact example specification and derived section.

Reproduce both packages:

```bash
.venv/bin/python prototype_manufacturing.py --chamfer-review
.venv/bin/python -m pytest -q
```

## Files changed

- Added `section_geometry.py`: canonical deterministic section model and validation.
- Changed `plate_geometry.py`: explicit optional chamfer/flow fields and adapter; JSON schema 3 adds derived section. Phase 2 outer contour algorithm unchanged.
- Reworked `manufacturing_drawing.py`: portrait data-sheet composition, upright canonical view, longitudinal section/detail, compact fields and notes.
- Changed `prototype_manufacturing.py`: explicit `--chamfer-review` example generation.
- Added `tests/test_section_geometry.py`: 16 additional cases.
- Updated existing PDF/record tests only for deliberate changes in layout labels, portrait paper, longitudinal extent and JSON schema; all Phase 2 DXF precision/tangency assertions retained.
- Regenerated sample PDF/JSON; DXF and SVG unchanged in bytes. Added sample/review PNGs, example package and reference comparison image.
- Updated this report. Historical prior-phase reports retained below.

## Verification

**178 passed, 0 failed, 2 existing warnings.** Breakdown: 102 application tests; 48 retained manufacturing/geometry tests; 12 retained drawing tests; 16 new section cases. Warnings: Starlette/httpx and AnyIO deprecations.

Numeric section tests verify angle from actual polygon edge vectors, thickness, extent, bore location, positive land, mirror behavior, simple nonintersecting closed polygon boundaries, explicit missing fields, invalid fits, adapter preservation, and deterministic geometry. Linear/unit-vector tolerances remain 1e-12 absolute with zero relative tolerance where used.

DXF and canonical SVG compare byte-for-byte with Phase 3 baseline `c32b0ee`. Reopened sample DXF: zero audit errors, zero fixes, inches, two cutting entities; unchanged exact four corner arcs and rough-bore rule. JSON intentionally changes to schema 3 to record new section/specification fields.

Full suite retains three-process hash-seed determinism checks. Standard and example PDFs reopened for text checks, including finished Ø1.548 and absence of substitution with rough Ø1.423. Both final raster sheets and the side-by-side reference comparison were visually inspected: no leader/text collisions remained after moving the bore callout below its leader. The section detail displays the configured chamfer rather than a generic symbol.

## Owner decisions before release

Confirm the intended customer chamfer-size/angle convention, complete actual order chamfer and flow inputs, bore tolerance/finish, marking method/location/text, general tolerance and finish requirements, and inspection requirements. The reference's smooth-edge/true-diameter wording has not been adopted; controlled EDGE / FINISH REQUIREMENT remains HOLD. Confirm visual acceptance, especially whether future sheets should use a conventional break in long handles to approach the reference's compact silhouette.

No push, PR, deployment, production/provider changes, customer configurator changes, checkout/fulfillment integration, or automatic release. Work remains on the existing local prototype branch.

---

# Historical Phase 3 report (superseded layout)

# O-Plates deterministic manufacturing prototype — Phase 3

## Outcome

One ordered plate per US Letter landscape drawing, generated directly with ReportLab. The finished plan view is paired with a hatched transverse bore section, flow indication, feature/data block, manufacturing notes, and original O-Plates / Rogue Machine title block. Drawing revision P3; generator `op-drawing-v3`. All sheets remain PROTOTYPE - NOT RELEASED FOR MANUFACTURE.

Continued from local Phase 2 commit `dacdbbc675d4db5c2ddd2624995ba3f24306a033` on the existing local branch. No push, PR, deployment, production change, or fulfillment integration.

## Reference review and adopted conventions

Inspected the actual rendered full sheet of `706928890-Model.pdf`, including its multiple compact orifice-plate data sheets and lower-right title/revision block. Adopted its useful organization: paired plan and section views, dominant finished-bore callout, independent OD/handle dimensions, axial flow arrow, section hatching, compact material/process fields, controlled marking notes, and structured drawing identity/revision information.

Not copied: corporate logo/name, drawing or project numbers, customer/service data, approval identities, copyright notice, proprietary wording, reference part dimensions, bore tolerance, chamfer values, stamping instructions, or tolerance standards. Neither ISO 2768 nor ISO 13920 is adopted. Generic engineering conventions are implemented in original O-Plates code.

## Sheet and layout

US Letter landscape, 11 x 8.5 inches (792 x 612 points), is the smallest practical normal US shop-printer format that fits the tested content legibly. A1's multi-part grid is unnecessary; 11 x 17 is not needed for the current one-part information load. Border sits inside normal printer margins. Print at 100% when assessing the stated scales; DO NOT SCALE DRAWING remains controlling.

- Top: data-sheet title and prominent prototype status.
- Upper left: canonical finished plan view, two centerlines, OD/handle/C-L dimensions with extension lines and arrows, finished-bore leader, exact four-radius callout.
- Upper right: transverse section through bore, hatch in solid material only, thickness dimension, flow arrow, explicit orientation and chamfer status.
- Middle: compact two-column material/quantity/thickness and manufacturing requirements block. Unavailable order/service fields are omitted rather than filled with invented data.
- Lower: three manufacturing notes and structured title block with brand, title, part ID, deterministic drawing number derived as `OP-<part ID>`, revision, sheet, scale, units, generator, geometry/spec revision and general-tolerance HOLD.
- Optional supplied order, line revision, tag and service appear in a reserved header row.

Plan and full-section scales are independently fitted using fixed viewport dimensions; both remain uniform/proportional. Thin sections below 1.5 points receive an additional magnified local thickness detail with radial break marks and its own scale, while the full section remains at its stated scale. Outside dimension arrows support very narrow projected handle widths.

## Geometry and section architecture

`plate_geometry.py` and the Phase 2 DXF generator were not changed. Plan PDF geometry still consumes the same ordered canonical arcs/lines; the existing test captures every PDF arc parameter against that definition. OD 5.000, bore 1.548, handle width 2.000, center-to-tip 10.500, and four R0.03125 corners are preserved.

`section_profile` derives radial material polygons from finished OD, finished bore and thickness. No chamfer is drawn for the sample. The nominal straight section is expressly not approval of a square bore edge. No flow/orientation fields were found in the existing application configuration model; FLOW is labeled ORIENTATION ONLY and the order orientation remains NOT SPECIFIED - HOLD. Upstream/downstream labels appear only with explicitly supplied supported orientation.

A future chamfer section requires all width/angle/side fields plus explicit flow orientation and an explicit dimensional convention. The supported opt-in convention is radial width with angle measured from the face; axial depth equals width × tan(angle). This convention is not assigned to the sample and is not an approved shop default. Section fit is validated; incomplete requirements keep chamfer geometry absent. Tests use synthetic values only.

`DrawingMetadata` validates optional drawing-only order/line/tag/service fields and revision. It introduces no timestamp, random ID, approval claim, database access, or application mutation. Metadata must travel with a future frozen drawing request for full reproducibility; the current sample JSON is deliberately unchanged from Phase 2. Explicit supplied metadata can be passed to `pdf_bytes(geometry, metadata)`; the sample package CLI remains unchanged.

## Files changed

- Added `manufacturing_drawing.py`: isolated original sheet template, metadata, section geometry and drawing helpers.
- Changed `manufacturing_files.py`: delegates PDF generation to the new module; DXF/SVG/JSON generation logic remains unchanged.
- Added `tests/test_manufacturing_drawing.py`: 12 focused test cases.
- Changed `tests/test_manufacturing.py`: expected displayed revision P2 -> P3 only. Phase 2 geometry assertions are unchanged.
- Regenerated `prototype_output/sample-plate.pdf`; regenerated DXF/JSON/SVG compare byte-identical and therefore have no tracked diff.
- Updated `MANUFACTURING_PROTOTYPE.md`: this report; Phase 2 engineering details retained below as historical baseline.

## Validation

Full suite on Python 3.12.14: **162 passed, 0 failed, 2 existing warnings** (Starlette/httpx and AnyIO deprecations). Breakdown: 102 original application tests, 48 prior manufacturing tests, 12 new drawing cases.

Tests cover finished dimension/feature/material/thickness/quantity labels, visible HOLDs, section geometry, absent fictitious chamfer, explicit future chamfer conventions and fit failure, flow behavior, traceability, optional order fields, proprietary/reference-content exclusion, Letter page size and repeatability at short/sample/long handle lengths. Existing canonical arc/radius/tangency, SVG, JSON, and cross-process determinism tests remain intact. Byte equality across Python hash seeds 1, 2 and 17 still passes.

Regenerated sample DXF, JSON and SVG are **byte-for-byte identical to Phase 2**. DXF reopened: **0 audit errors, 0 fixes**, exactly two model-space cutting entities. All Phase 2 precision checks remain at 1e-12 absolute and zero relative tolerance.

Final PDF reopened for text extraction; correct finished bore, radius, section, revision and HOLD fields verified, with no rough-bore dimension substitution or copied company/project/tolerance content. Final raster images visually inspected for sample 10.5-inch handle, short 2.7-inch handle, long 30-inch handle, and 48-inch OD/25-inch handle. No text clipping, header-rule crossings, dimension/leader collisions or title/data-block overlap remained. The large-OD sheet includes a magnified local thickness detail to supplement its necessarily thin true-scale section.

## Release decisions still required

Owner approval of the drawing convention/layout; finished bore tolerance and finish; general dimensional and surface-finish standards; chamfer selection and, if needed, width definition, angle and side; actual flow/orientation; marking text/method/location; inspection criteria. The prototype does not infer these from the reference and contains no automatic release workflow. Shop/CAM import and manufacturing-process acceptance remain future steps.

---

# Historical Phase 2 baseline

The following records the preceding phase. Its P2 layout/status descriptions are superseded by Phase 3 above; its canonical contour equations and rules remain current.

# O-Plates deterministic manufacturing prototype — Phase 2

## Outcome

Four mathematically tangent R0.03125-inch corners now form part of the canonical outer contour: two concave paddle/handle transitions and two convex handle-tip corners. The DXF, finished PDF, JSON and proportional SVG consume that contour. No Fusion, LLM, CAD application or network service participates in generation.

Continued locally from `a69ec89` on `work/deterministic-manufacturing-prototype`. No push, PR, deployment, production changes, payment/database changes, or order/fulfillment integration was performed.

## Exact mathematical treatment

Let R = finished OD/2, h = handle width/2, L = centerline-to-furthest-tip, and r = 0.03125. Origin is the concentric bore/paddle center, handle axis +X.

- Neck fillet centers: C± = (a, ±(h+r)), where a = sqrt((R+r)^2 - (h+r)^2) = sqrt((R-h)(R+h+2r)).
- Distance from origin to each neck center is R+r. Thus the paddle and neck circles are externally tangent.
- Paddle tangent points: T± = R/(R+r) × C±.
- Handle tangent points: H± = (a, ±h). Each fillet center is r from its straight handle side.
- With θ = atan2(h+r,a), the retained major paddle arc sweeps 2π−2θ counterclockwise. Each neck fillet sweeps θ−π/2 clockwise, joining the tangent points smoothly.
- Tip fillet centers: (L−r, ±(h−r)); each tip fillet is a counterclockwise quarter-circle of radius r, fully inside the governing handle envelope.
- The contour consists of five circular arcs (one paddle, four corners) and three straight segments in one closed loop.
- DXF bulges are tan(signed sweep/4). No tessellation or decorative spline defines manufacturing geometry.

The paddle remains a true circle of diameter 2R except where the handle joins it; the straight handle sides remain y=±h and the furthest tip remains x=L. Concave neck blends add the small tangent transition outside the sharp union; tip rounds remove the sharp corners inside the envelope. This is the specified standard radiused contour, not the former cosmetic SVG neck.

Shapes that cannot fit these features fail explicitly: h must exceed r and a must be less than L−r. No radius reduction or dimension clamping is substituted.

## Preserved sample dimensions

| Requirement | Inches |
| --- | ---: |
| Finished OD | 5.000 |
| Straight-side handle width | 2.000 |
| Centerline to furthest handle tip | 10.500 |
| Finished bore / PDF callout | 1.548 |
| DXF rough bore | 1.423 |
| Diameter allowance | 0.125 |
| Radial machining stock | 0.0625 |
| Four corner radii | 0.03125 |
| Thickness | 0.125 |

Material: 304 stainless steel; sample quantity 1. `ROUGH_BORE_DIAMETER_ALLOWANCE = 0.125` is unchanged. No external stock allowance or kerf compensation is added; downstream CAM owns kerf compensation.

## Architecture and files changed this phase

- `plate_geometry.py`: new named `CORNER_RADIUS`, immutable ordered arc/line segments, fit validation, exact fillets, JSON schema 2 and geometry version `straight-handle-r03125-v2-prototype`.
- `manufacturing_files.py`: all renderers consume canonical segments. SVG uses native circular A commands; DXF uses native bulges; ReportLab renders mathematical arc parameters into a connected vector path. PDF's native representation uses ReportLab's standard circular-arc Bezier conversion, not independently designed cosmetic curves.
- Drawing template functions are separated into `draw_sheet_header`, `draw_finished_view` (view and dimensions), `draw_manufacturing_notes`, and `draw_title_block` (part data and revision), leaving format-specific organization isolated from geometry and export orchestration. Current revision P2. Exact radius note: `4X R 0.03125`.
- `tests/test_manufacturing.py`: retained prior tests, updated sharp-contour assertions for the radiused contour, and added 11 cases.
- `prototype_output/sample-plate.dxf`, `.pdf`, `.json`, `.svg`: regenerated.
- `MANUFACTURING_PROTOTYPE.md`: this engineering report replaces the superseded sharp-contour description, which remains available in commit `a69ec89`.

Existing `plate_preview.py`, production application behavior, pricing, dependency files and CI configuration were not changed in this phase. The canonical prototype SVG remains separate from the accepted customer UI preview.

## Validation results

Python 3.12.14; complete suite: **150 passed, 0 failed, 2 warnings**.

- 102 original application tests passed.
- 48 manufacturing tests passed: 37 retained/adapted Phase 1 cases plus 11 added Phase 2 cases.
- The two warnings remain Starlette/httpx and AnyIO deprecations.
- Geometry checks retain **1e-12 absolute tolerance, zero relative tolerance** for linear values and unit tangent components.
- Reloaded DXF: **0 audit errors, 0 fixes**, exactly two model-space entities, units code 1 (inches), imperial measurement setting.
- One closed CUT_OUTER polyline contains five native arcs and three lines; one CUT_BORE circle is inherently closed. No duplicate vertices, disconnected segment endpoints, dimensions, notes or title-block entities are present in the cutting file.
- Reconstructed small DXF radii are 0.03124999999999988 and 0.03125000000000001 inches, ordinary floating-point roundoff within the unchanged tolerance.
- Tests verify directed tangent continuity at all eight joins, independent circle-center distances, side offsets, tip extents, preserved governing dimensions and rough-bore stock.
- Six additional sizes validate every radius and join, including a 48-inch OD, near-OD-width handle, and narrow handle. Separate cases reject insufficient room for the specified rounds.
- SVG arc radii, sweeps and endpoints are checked against canonical segments; PDF arc parameters and finished callouts are captured by renderer tests; JSON exposes the version, radius, corner count and segment definitions.
- Repeated output matches byte-for-byte both in-process and across subprocesses with explicit Python hash seeds 1, 2 and 17.
- This phase exposed an intermittent Phase 1 determinism defect: ezdxf discovers CLASS records using set iteration. Class records are now pre-populated and sorted before serialization, in addition to the existing fixed-date/GUID mode. Geometry is not affected by this metadata ordering fix.
- Final PDF independently reopened for text extraction: `FINISHED BORE Ø1.548`, `4X R 0.03125`, no `1.423` dimension substitution. Final PNG rendering visually inspected: continuous contour, legible dimensions/notes, no clipping or overlapping callouts. The small rounds are intentionally subtle at full-sheet scale.

## Andritz reference and open requirements

No actual Andritz reference drawing was supplied or found in the project or targeted available-file search. Proprietary formatting has not been guessed. The existing sheet organization is retained with modular sections for the next formatting pass.

Needed next: one representative Andritz shop drawing from the owner's workflow, preferably its original full-sheet PDF (or a clear full-sheet scan at readable resolution), showing the complete border, title block, revision block, dimension/leader style and notes. Include sheet size and a detail sheet if those conventions are not visible. A comparable plate drawing would be ideal; sensitive customer/part values can be redacted while leaving the layout visible.

Still unresolved and not defaulted: bore tolerance and surface finish; chamfer selection/width/angle/side; marking text/method/location; general dimensional tolerances and surface finish; inspection requirements. The PDF and JSON remain explicitly prototype/not released. Actual shop CAM import/process acceptance also remains outside this numerical prototype validation.

## Reproduce and later integration

```bash
.venv/bin/python -m pip install -r requirements.txt -r requirements-manufacturing.txt
.venv/bin/python prototype_manufacturing.py --output prototype_output
.venv/bin/python -m pytest -q
```

Preserve the established eventual workflow: frozen validated order specification -> versioned canonical geometry -> deterministic package -> manual release review before any automatic manufacturing integration. Pin generator/dependencies; retain original package bytes and revision identity. Determinism is verified within the pinned environment, not asserted across arbitrary library upgrades. No automatic release path has been implemented.
