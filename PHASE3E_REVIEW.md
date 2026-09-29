# Phase 3E — Base product scope and drawing refinement

Branch: `work/deterministic-manufacturing-prototype`.
Starting HEAD: `08147181c6c4664007ca694da2453289206060e4`.
The resulting local commit is the commit containing this report (`git log -1`). Production remains frozen; no push, PR, deployment or provider changes.

## Corrected scope

The base product is a customer-configured restriction/general plate. It does not require line size, pipe ID/schedule, flange class, tap arrangement, service conditions or beta ratio to generate its geometry and paired files. The preceding standards review is retained as historical future-metering research, not a base-product release checklist.

`PlateSpec.application` is a validated enum with `restriction-general` as the base fallback and `metering` as an explicit future mode. The configuration adapter preserves it. Both modes activate **zero metering rule sets**. JSON distinguishes NOT APPLICABLE from NOT IMPLEMENTED; metering drawings explicitly identify validation as unimplemented. No API/AGA/ISO calculator or table was added. No UI was changed.

`manufacturing_context.py` centralizes application/state labels. DrawingMetadata accepts prototype or customer-confirmation states explicitly and the PDF/JSON agree. There is no automatic transition. Both retain NOT RELEASED FOR MANUFACTURE. The released enum and label are prepared, but actual release output is rejected until a controlled release path exists. This is deliberately not a production release workflow, and changing a status cannot disguise this prototype as released documentation.

## Geometry and files

Before edits, the branch contained `straight-handle-r03125-v2-prototype`: one OD arc and four .03125 corner arcs. Canonical contour calculations and section math were not changed. PlateSpec gained application metadata; JSON schema is now 4 and package records include drawing metadata/state.

Old Phase 3D current/chamfer/debug outputs and its golden hash were moved under `prototype_output/archive/phase3d/`. Phase 3C remains separately archived. Current packages regenerate from code; no uploaded/stale JSON is a generation input. Existing canonical equality/version checks, directory contamination checks and stale-PNG invalidation remain. Current JSON was checked for r03125 and absence of sharp-tip v1 assumptions.

Normal external pair:

- `prototype_output/current/OP-PROTOTYPE-001.pdf`
- `prototype_output/current/OP-PROTOTYPE-001.dxf`

Internal audit: matching `.json`. Review derivative: matching `.png`.

`sample-plate.pdf` remains historical only. There is one active renderer. No SVG is emitted or required by the job-package path. The optional low-level SVG helper remains for internal tests/debugging.

## Drawing refinement and visual review

The Phase 3C composition is retained: 224-point dominant paddle, short upward handle, nearby bore/OD leaders, enlarged right section, ruled lower data and compact title block. ASME Y14.5-2018 is now explicit in the title block. No datums, reference frames or unapproved FCFs are emitted. Section A-A and Detail B are view identifiers only. Third-angle projection remains an unverified drawing-practice decision, not a generation blocker.

The 10.500 dimension now explicitly says **C/L TO HANDLE END**. It is not overall length; the physical envelope is 13.000. The .03125 radius retains five digits intentionally rather than silently changing the nominal to .031. NTS and DO NOT SCALE DRAWING remain intentional.

Flow is shown only when explicitly supplied. Missing flow is marked HOLD only for a selected chamfer requiring relative orientation. Plain/unselected configurations do not gain a fictitious upstream/flow requirement. An explicit bore-finish note field is supported for both ordinary and chamfered plates. Material remains 304 STAINLESS STEEL without inferred ASTM, dual certification or MTR status.

Rendered sample, configured chamfer and side-by-side comparison were visually reviewed. The added application subtitle initially crowded the illustrative caption; the caption was moved down and re-rendered. Final sheets have separated captions, readable section/detail dimensions and no observed overlapping labels. `debug/phase3e-comparison.png` compares the owner reference; `debug/phase3e-golden-comparison.png` compares the accepted Phase 3C composition. The new golden PDF hash deliberately protects Phase 3E in the pinned environment.

## Dimensional / audit results

PDF text independently reopened: Ø5.000 OD, Ø1.548 finished bore, 2.000 width, 10.500 C/L TO HANDLE END, 4X R0.03125, .125 thickness, 304 stainless steel and quantity 1. The sample chamfer selection remains explicitly unresolved; no none/configured choice was invented. Status is prototype/not released. No rough-bore or kerf instructions appear on the finished drawing face.

Saved DXF reopened: inches, one closed CUT_OUTER polyline and one CUT_BORE circle, zero audit errors and zero fixes. No dimensions/title blocks/PDF presentation entities. It remains byte-identical to validated Phase 2. Tests compare reloaded vertices/bulges to the current canonical geometry at 1e-12 absolute tolerance.

| Item | Inches |
|---|---:|
| Finished bore | 1.548 |
| Rough DXF bore | 1.423 |
| Diameter allowance | .125 |
| Radial machining stock | .0625 |
| Finished OD | 5.000 |
| Handle width | 2.000 |
| Centerline to tip | 10.500 |
| Actual end-to-end envelope | 13.000 |
| Four corner radii | .03125 |

Chamfer states remain distinct: NONE, CONFIGURED, INCOMPLETE - HOLD, and unspecified. Configured geometry consumes exact size/convention/angle/side/flow. The illustrative non-default configuration retains .040 radial width, 45 degrees from face, downstream with left-to-right flow; axial depth .0400 and land .0850. Missing parameters never create a fictitious bevel. No release can be emitted in this phase.

## Regression

**219 passed; zero failed; two existing deprecation warnings.**

| Group | Passed |
|---|---:|
| Existing application | 102 |
| Manufacturing geometry/files | 48 |
| Existing drawing | 12 |
| Section/chamfer | 16 |
| NTS presentation/fixture | 19 |
| Controlled paired package | 11 |
| New application/state/scope | 11 |
| Total | 219 |

Existing tests retained; expected revision/year/dimension-description strings and schema version updated intentionally. Geometry tolerances unchanged. New tests cover absence of mandatory metering inputs, inactive metering rules, adapter validation, identical cutting geometry across modes, explicit state consistency, blocked release output, frozen section options, conditional flow and no invented requirements. Existing tests continue to cover finished/rough separation, all chamfer states, side/flow/angle consistency, stale geometry, determinism and no datums/FCFs.

## Owner decisions — prioritized base-product items only

1. Bore tolerance and general decimal/angular tolerance policy; allow explicit customer tolerances where supported.
2. Bore/face finish, deburr/edge treatment and whether a base flatness requirement is needed. No automatic break-edge range or metering finish.
3. Marking default (including explicit none), method and location; sample chamfer choice must also be resolved as customer configuration.
4. Inspection/acceptance policy and material-spec/certification wording backed by actual supply documentation.
5. Production numbering/spec revision and digital confirmation/release authority conventions before integration.

These are deliberate unresolved decisions, not reasons to require metering-system inputs. See [PHASE3E_PARAMETERS.md](PHASE3E_PARAMETERS.md) for each field's single classification, source, validation, drawing location and release relevance.

## Changed files and reproduction

- `manufacturing_context.py`: application/state enums, status labels and inactive rule-set context.
- `plate_geometry.py`: application field/adapter/validation and JSON schema/context only; contour builder unchanged.
- `manufacturing_drawing.py`: P3E, standard year, scope subtitle, explicit C/L dimension, conditional flow, bore-finish support and deterministic status presentation.
- `manufacturing_files.py`: metadata/status audit serialization and rejection of PDF-only section overrides that are absent from the frozen spec.
- `scripts/review_phase3e.py`: current review generation; replaces Phase 3D script.
- `tests/test_application_scope.py`, updated drawing tests and `tests/fixtures/phase3e-manufacturing-print.sha256`.
- Current artifacts regenerated; previous artifacts segregated; report, matrix and historical-scope notices added.

```bash
.venv/bin/python prototype_manufacturing.py --chamfer-review
.venv/bin/python scripts/review_phase3e.py --reference /path/to/owner-crop.png
.venv/bin/python -m pytest -q
```

Manufacturing-file generation remains deterministic Python, without Fusion, CAD runtime or an LLM. No standards research was repeated this phase.
