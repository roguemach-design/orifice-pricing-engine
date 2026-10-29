# OP-IMP-001 — fixed handle-hole base manufacturing cost

Refs GitHub Issue #53. Development PR only: no merge, deployment, production
configuration writes, historical order changes or LIVE checkout activation.

## Formula and scope

For each plate, `handle_hole_cost = 15.06` when the existing Handle Hole option is
enabled, otherwise `0.0`. The charge appears separately as
`manufacturing_cost_components.handle_hole` and is added **once** to the existing
per-plate manufacturing subtotal before any selling-price adjustments:

`unit_price = round((existing_subtotal + handle_hole_cost) × lead_multiplier × quantity_multiplier, 2)`

`extended_total = round(unit_price × quantity, 2)`

The fixed base cost is not a fixed final customer surcharge: existing lead-time
multipliers and quantity discounts apply to it. It is not proportional to hole
diameter, thickness, quantity, circumference, pierce time or laser cut length.
There is no added setup, loading or inspection fee. Existing material purchasing
area, laser pricing, bore/chamfer costs and manufacturing calibration are untouched.

No customer UI change is required: the existing toggle already updates the quote
request immediately; the configurator and Quote Cart display server-priced results.
Single and cart checkout reprice through that same authoritative calculation.

The pricing-model identifier changes from `diameter-allowances-2026-10-v2` to
`diameter-allowances-2026-10-v3-handle-hole`, using the existing quote-version and
stale-checkout rejection mechanism. The shipping-model identifier and shipping
calculation remain unchanged. Open old quotes/carts require review/repricing; no
historical quote, order, Frozen Plate, approval or Stripe session is rewritten.
No database migration, new configuration system or Manufacturing Control change.

## Integration gate

Provisional development parent: PR #69 isolated API shipping candidate
`39efe24c3445a4a299a971afae30e9898022d403`.

Read-only Render check at the start of this work still showed production API
`2b0a72187c7769e7895b19eb7828f372a9b369b7`, deployment
`dep-dbhjnmo8v5cc738m36bg`, LIVE. The shipping candidate was **not verified live**.
This dependent development branch does not claim production integration or release.

**Before final integration:** independently confirm the actual shipping release
runtime SHA and its production acceptance. Reconcile any drift from the provisional
parent, run final integrated checks, and obtain separate owner authorization.
Do not treat owner deployment intent, a PR merge or a build start as live acceptance.
Staging remains suspended and worker PR #52 remains operationally undeployed.

## Reference comparison

Use OP-0019's geometry: 304 SS, 14.25 in OD, 8.5 in bore, .25 in thickness,
1 in handle width, 13.125 in centerline-to-end, .375 in handle hole .625 in from tip.
Compare the same enabled-hole configuration against the shipping-release pricing
baseline, before and after adding the fixed charge. Shipping remains **8.85 lb**
packed; Ground **$20.55**, 2-Day **$38.02**, Next Day **$58.57** at quantity 1.
Existing historical shipping-comparison documents describe the earlier model and
are preserved as historical calibration evidence, not overwritten by this change.

| Lead time | Quantity | Previous unit | Proposed unit | Previous total | Proposed total |
|---|---:|---:|---:|---:|---:|
| 7 days | 1 | $985.19 | $1,019.83 | $985.19 | $1,019.83 |
| 7 days | 5 | $955.63 | $989.23 | $4,778.15 | $4,946.15 |
| 7 days | 10 | $935.93 | $968.84 | $9,359.30 | $9,688.40 |
| 7 days | 25 | $906.37 | $938.24 | $22,659.25 | $23,456.00 |
| 14 days | 1 | $685.35 | $709.45 | $685.35 | $709.45 |
| 14 days | 5 | $664.79 | $688.16 | $3,323.95 | $3,440.80 |
| 14 days | 10 | $651.08 | $673.97 | $6,510.80 | $6,739.70 |
| 14 days | 25 | $630.52 | $652.69 | $15,763.00 | $16,317.25 |
| 21 days | 1 | $428.34 | $443.40 | $428.34 | $443.40 |
| 21 days | 5 | $415.49 | $430.10 | $2,077.45 | $2,150.50 |
| 21 days | 10 | $406.93 | $421.23 | $4,069.30 | $4,212.30 |
| 21 days | 25 | $394.08 | $407.93 | $9,852.00 | $10,198.25 |

7-day calculations above are simulations only where that service is unavailable;
no lead-time availability setting is changed. Today / 2-Day remains disabled.

## Verification

Focused tests cover the toggle on/off path, quantities 1/5/10/25, existing
7/14/21-day multipliers, three hole diameters with identical fixed charges,
actual Streamlit configurator repricing and mixed-hole Quote Cart totals, and real
local API quote/single/cart checkout using synthetic Stripe sessions. Old model
versions must be rejected before Stripe creation. No real payment is initiated.

An 864-case baseline fingerprint covers 304/316/Carbon Steel, four thicknesses,
three hole diameters, four quantities, three lead times and both toggle states.
Every output outside the approved price/component/version changes must match the
shipping-release baseline exactly, including shipping mass/rates, package dimensions,
material/laser/machining/loading/inspection costs and pricing multipliers.
Original geometry/artifact convergence fixtures are preserved. Separate pricing
overrides update only the approved price expectations. The old shipping regression
fingerprint remains asserted after removing the new zero-cost component and
normalizing the model label for its no-hole cases. All 51 protected manufacturing
hashes remain required by the unchanged existing integrity test.
