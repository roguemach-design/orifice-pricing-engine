# Optional handle hole - owner review

Branch: `work/optional-handle-hole`.
Base: approved analyzer `37352e71a0eccc53b02ae07c0cca24754442bb44`, descending from the accepted integration candidate `c56f98db0e049574af83bbdd671883bf3261a470`.
No merge or deployment is part of this change.

## Manufacturing behavior

The checkbox defaults to OFF. Enabling it reveals two empty inch inputs, accepting decimal, fraction, and mixed-number notation. The hole is centered across the handle. Its location is measured from the physical handle end edge to the hole centerline.

The existing flat configuration naming is retained:

```json
{
  "handle_hole_enabled": true,
  "handle_hole_diameter": 0.375,
  "handle_hole_center_from_handle_end": 0.75
}
```

These fields are retained in reviewed configurations, server snapshots, and the canonical Frozen Plate specification. Disabled configurations omit all three fields from canonical manufacturing serialization and API payloads. Legacy specs without them mean OFF. No historical revision or artifact is rewritten.

Required checks:

- Enabled dimensions must be present, finite, numeric, and positive.
- Diameter must be at most 90% of handle width, including the exact boundary.
- The entire hole must remain inside the handle end and side edges.
- The hole must clear the actual canonical tangent neck and circular body.
- Rounded-tip containment is checked.
- Invalid inputs are rejected, never clamped. Missing/invalid dimensions remain incomplete/HOLD.

The outer profile, bore, machining allowance, tangent neck, corner radii and chamfer rules remain unchanged.

## Propagation and evidence

| Component | Result |
|---|---|
| Configurator | Checkbox, nullable fraction inputs, concise help, validation and proportional canonical SVG when enabled |
| Finished PDF | Finished hole, diameter callout, end-to-hole-center dimension, through-hole opening in section; existing title block and NTS convention |
| Rough DXF | Additional `CIRCLE` on `CUT_HANDLE_HOLE`, exact finished diameter and nominal center |
| Frozen Plate | State/dimension changes change the spec hash; existing immutable R1/R2 workflow |
| Package validation | Checks DXF entity count, finished diameter, nominal center and PDF callouts before accepting a revision |
| Analyzer | Evidence/confidence-backed editable proposals from explicit labels or accepted spatial handle-hole leader/end witnesses; mandatory user review |
| Pricing | Neutral configuration metadata interface only; identical pricing results for OFF and ON |
| Editor restoration | Optional fields belong to each restored snapshot; restoring a legacy plate clears prior hole input |

The approved analyzer's `tag_hole_diameter` and `tag_hole_position` reference observations remain available. Separate `handle_hole_*` proposals carry the manufacturing interpretation. Neck-radius reference observations remain reference-only. Conflicting annotations abstain. Dimensions without known units do not prefill manufacturing inputs.

## Review specimen

Both specimens: OD 5.0000 in, finished bore 1.5480 in, handle width 1.0000 in, bore center to handle end 10.5000 in, thickness 0.1250 in, 304 stainless steel.

| Specimen | Handle hole | DXF main bore |
|---|---|---|
| OFF | Absent | 1.4230 in |
| ON | Diameter 0.3750 in; center (9.7500, 0) in; end distance 0.7500 in | 1.4230 in |

The ON DXF hole radius is exactly 0.1875 in. No 0.125 in bore allowance, kerf offset, or machining stock is applied to that hole. The main-bore radius remains 0.7115 in.

Generated review files live in `review/handle-hole/`: finished PDFs, rough DXFs, canonical SVGs, configurator SVGs, audit JSON, rendered PNGs, hashes and compatibility evidence. Generate the authoritative sample files with:

```bash
python scripts/generate_handle_hole_review.py
```

The review drawings retain the accepted confirmation/HOLD labels for other unresolved manufacturing requirements. They do not constitute a manufacturing release.

## Validation

Local full suite: **617 passed, 5 existing skips**. Python compilation and whitespace checks pass. The feature adds 42 regression cases spanning enabled/disabled inputs, exact 90%, invalid/missing dimensions, neck containment, PDF/SVG/DXF behavior, bore stock separation, hash changes, immutable revisions, analyzer evidence, fraction inputs, restoration and unchanged pricing.

Feature-OFF outputs were generated separately from accepted commit `c56f98d` and this implementation using the same dependency environment. PDF, DXF, canonical SVG, configurator SVG, canonical spec hash and manufacturing record hash are identical. The resulting hashes are in `no-hole-compatibility-hashes.json` and covered by a golden regression.

PDF and SVG renderings were visually inspected. Enabled layouts use a fitted proportional plan so the optional hole remains correctly located inside the straight handle without overlapping the plate on an NTS sheet.

## Limits and scope

- Owner testing of the website remains pending; no environment was deployed.
- Analyzer intake remains assisted. Unlabeled callouts lacking supported spatial association, conflicting evidence, and unreadable notes require manual entry.
- No pricing adjustment, packaging change, supplier quote integration, G-code, shipping change, external email, payment action or manufacturing release was added.
- No production configuration changes, merge to main, or production deployment occurred.
