# OP-IMP-011 — finished-part shipping weight

Development proposal only. No production rates, configuration, orders, approvals,
Frozen Plates or stored artifacts are changed. Baseline: customer release
`48f6446820ef653c58819606eccd088fde8f3766` (API pricing logic matches deployed
`2b0a72187c7769e7895b19eb7828f372a9b369b7`). Excludes deferred worker PR #52.

## Calculation

`shipping_weight_lb = quantity × (finished_part_volume_in3 × configured_density + 1.0)`

`shipping_mass.py` integrates the existing `build_plate_geometry` contour using
Green's theorem: each line contributes its cross product; each arc also contributes
`radius² × (sweep_radians − sin(sweep_radians))`. This includes the canonical
straight handle, its overlap with the circular plate, neck fillets and rounded tip
exactly once. Subtract the finished bore and enabled handle-hole cylinders.
For a fully specified chamfer, reuse `build_section_geometry` radial width `w` and
axial depth `d`: subtract `π × d × (bore_radius × w + w²/3)`.
Incomplete quote-only chamfers retain that small material volume conservatively;
existing server checkout completeness/feasibility validation remains authoritative.
No manufacturing-critical geometry is assumed or backfilled.

`estimated_unit_weight_lb` is finished metal mass; `estimated_total_weight_lb` is
packed shipping mass including 1 lb **per plate**, not per order or cart. Carrier
rating uses unrounded mass; presentation rounds to two decimals. Use existing
configured material density directly; the existing unused stainless weight
multiplier is not newly applied. No independent outline, geometry version,
material density change or manufacturing serialization change is introduced.

The rectangular purchasing area, laser length/rate, machining time/allowances,
loading, inspection, lead-time multipliers and quantity discounts are untouched.
Package dimensions and rule-based carrier pricing remain untouched, including
dimensional-weight max and whole-pound ceiling. These are estimator amounts,
not live UPS quotes. Cart shipping continues the existing sum of line estimates.

A shipping-model version is included in the existing opaque quote/checkout
version token so an open pre-correction quote is rejected by the existing stale
version guard and must be repriced before payment. The machining pricing-model
version stays unchanged. No schema migration or configuration write is needed.

## OP-0019 reproduction

Read-only order snapshot: 304 stainless, OD 14.25 in, bore 8.5 in, thickness .25 in,
handle width 1 in, centerline-to-end 13.125 in, enabled .375 in handle hole with
center .625 in from tip, quantity 1, no chamfer, 14-day service.

| Output | Previous | Proposed |
|---|---:|---:|
| Weight used for shipping | 20.85 lb | 8.85 lb |
| Finished-part metal | not distinguished | 7.85 lb |
| Packaging allowance | none | 1.00 lb |
| Package | 24.25 × 18.25 × 1 in | unchanged |
| Billable weight | 21 lb | 9 lb |
| Ground | $31.95 | $20.55 |
| 2-Day | $59.11 | $38.02 |
| Next Day | $91.06 | $58.57 |
| Manufacturing unit selling price | $685.35 | $685.35 |
| Rectangular purchasing area | 288.5625 sq in | unchanged |

Owner-measured packed weight: **8.6 lb**. Proposed estimate is approximately
**0.25 lb / 2.9% higher**, within the fixed owner-directed packaging allowance;
no density or allowance is tuned to force an exact match. Historical OP-0019
shipping remains $31.95; no order is rewritten.

## Regression comparisons

[Exact 289-row shipping comparison](shipping-weight-comparison.csv): OP-0019 plus
288 cases: 304/316/Carbon Steel; .125/.25/.375/.5 in; small 3/1 in, reference
14.25/8.5 in, large-bore 24/19 in plates; quantities 1/5/10/25; standard chamfer on/off.
All non-shipping outputs, including package dimensions and every commercial cost,
match the baseline exactly across the matrix (canonical result SHA-256
`040d797a93aab95d2a950d6be0480a581f32909b5a92a013521067059c34e09e`).
Ground is lower in 264 cases, unchanged in 6 and higher in 18. The increases are
small/light configurations where the newly required 1 lb packaging allowance
exceeds the removed envelope material, subject to existing billable-weight rounding.

Tests independently compare the exact contour integral with a dense tessellated
outline, check bore/hole/chamfer removal, reject invalid density and infeasible
chamfers, and exercise real local API quote, single-item checkout and cart checkout
with synthetic Stripe sessions. Both checkout paths reject pre-correction version
tokens before calling Stripe, then use exactly the quoted authoritative shipping.
The old convergence fixture is retained: only the three approved shipping fields
are overridden from a separate fixture; payload, pricing, PDF, DXF, SVG and spec
fingerprints remain asserted against their original accepted baselines.

## Release considerations

Leave this PR unmerged pending owner review. If later approved, deploy the exact
integrated release to the production API first; the customer UI already reads the
API shipping outputs and needs no product change. Do not deploy a default branch
containing unrelated worker changes. Reprice open quotes/carts after rollout;
existing completed orders and in-flight Stripe sessions retain their recorded
amounts. Rollback would pin the API to its pre-release commit, without changing
records or settings. No pricing controls, carrier constants, checkout mode,
staging status or automation enablement changes are required.
