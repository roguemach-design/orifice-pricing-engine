# Pricing calibration review — development only

Baseline: `a9615a1e4d2b2013b0be7ddbf40ff409385c50ac` (deployed checkout/engineering release).
This proposal does not change production configuration, enable a service, reprice stored orders, or release manufacturing.

## Formula and parameter contract

For finished bore diameter D, the existing canonical rough-bore helper gives R = D − 0.125 inch. Two nominal rough contours use R + (D−R)/3 and R + 2(D−R)/3; one finishing contour uses D. Spring contours at D number 0, 1 and 2 for ±0.005, ±0.002 and ±0.001 inch respectively.

Bore minutes = π × sum(contour diameters) / cutting feed in inches/minute. Bore time cost = minutes × hourly rate / 60. Initial feed remains 28 IPM and rate $150/hour. Add the independent commercial allowance $32.50 × D. The allowance is a selling-price calibration input, not cycle time.

Chamfer minutes = π × (D + radial width) / chamfer feed, for one nominal contour. Time cost = minutes × hourly rate / 60; add $5.00 × D. This is a pricing estimate at the mean chamfer diameter, not a tool-center path or a verified production cycle. A chamfer requires its width; missing width is rejected, never defaulted. Chamfer NO costs zero. No second loading, setup, flip or unverified handling charge is added.

Manufacturing subtotal = existing material + existing laser blanking + bore time + bore allowance + chamfer time + chamfer allowance + existing loading + existing inspection. Apply the selected lead multiplier to the entire subtotal, then the quantity multiplier; round once at unit level and extend that rounded unit by quantity. Shipping remains separate and unchanged. No other manufacturing fees existed in the accepted engine; none are silently removed or invented.

The existing quote-version token now includes the pricing-model version as well as the configuration timestamp. A formula release invalidates stale single/cart purchase prices even when no settings row changed; the existing checkout conflict response requires a fresh price review. This does not rewrite stored quote/order snapshots or alter the owner editor's configuration-version mechanism.

The quote result preserves existing rounded cost fields and adds full-precision component reconciliation, estimated minutes, pass counts, rough diameter and separate commercial allowances. Manufacturing generators and canonical geometry remain unchanged.

## Owner controls and recovery

The existing protected app_config editor projects precision_bore_allowance_per_in=32.50, chamfer_allowance_per_in=5.00, and today_2_day_multiplier=3.3 in memory. Reading never persists them. Existing version, owner authorization, deliberate save, history, restore and reset mechanisms are reused; no migration or second settings store exists. Old active settings and old history entries project missing fields without modifying their stored bytes. A deliberate future config save records all controls normally.

The complete existing 7/14/21 multiplier catalog is projected while preserving availability flags and any stored multiplier overrides. Adding a missing 7-day catalog entry does not enable it. Checkout Control's component and endpoints are untouched.

## Lead times and future eligibility

21 Days = 1.0×, 14 Days = 1.6×, 7 Days = 2.3× under bundled defaults. Existing configured overrides and availability remain authoritative.

`today_2_day` is the single canonical future service, labeled **Today / 2-Day**, with one 3.3× multiplier. It is not an integer day value accepted by quote/checkout. Existing Coming Soon disabled UI remains unchanged. Offline simulation exposes no customer activation route.

Future readiness requires confirmed material, blank, capacity, cutoff, qualified machining method and shipment window. Even all evidence true returns unavailable and ineligible until a separately approved activation implementation. The intended window is production today or the following business day and shipment on completion, not arrival at the customer. Actual cutoff, timezone, working-day/holiday calendar, quantity/capacity limits, supply eligibility and transport pickup constraints must be approved before activation; no fabricated cutoff or delivery guarantee is implemented.

## Backtest

The reproducible script is `scripts/pricing_calibration_backtest.py`; it reads the pinned old engine through git, runs only offline, and restores its temporary hypothetical lead map in finally. It generates 13,824 cases spanning all 3 supported materials × 4 thicknesses, 3 outside diameters, 2 bore ratios, all 3 tolerances, chamfer NO plus 3 radial widths, quantities 1/5/10/25, and 21/14/hypothetical 7/hypothetical Today / 2-Day.

This is broader than the earlier 2,304-case audit, not a claim to recreate its unavailable exact input grid. Material, active legacy laser, loading, inspection, shipping and weight outputs reconcile exactly in every case. All calculations use the accepted bundled configuration, not a claim to have read protected production pricing settings.

Non-chamfered unit-price differences: -0.7018% to 0.5429%. Chamfered differences: -37.0864% to -11.9194%.

Small departures from the earlier approximate ±0.6% preservation band arise from exact π, stock-based nominal contours, tolerance-specific spring passes and final cent rounding. Prices are not forced to equal the old bug. The revised chamfer surcharge reflects one nominal contour plus its independent diameter allowance, rather than another full bore charge.

### Historical geometry reference

14.250 inch OD × 8.500 inch finished bore × 0.250 inch; handle width 1 inch; centerline to end 13.125 inches; hole Ø0.375 inch at 0.625 inch from end; ±0.005 inch bore tolerance; quantity 1; chamfer YES uses radial width 0.062 inch. These are synthetic pricing inputs, not mutations of a customer order.

| Material | Chamfer | Lead | Old subtotal | New subtotal | Old unit | New unit | Difference |
|---|---|---|---:|---:|---:|---:|---:|
| 304 | False | 21 | $430.94 | $428.34 | $430.94 | $428.34 | -0.603% |
| 304 | False | 14 | $430.94 | $428.34 | $689.50 | $685.35 | -0.602% |
| 304 | False | 7 | $430.94 | $428.34 | $991.16 | $985.19 | -0.602% |
| 304 | False | today_2_day | $430.94 | $428.34 | $1422.10 | $1413.53 | -0.603% |
| 304 | True | 21 | $716.90 | $473.24 | $716.90 | $473.24 | -33.988% |
| 304 | True | 14 | $716.90 | $473.24 | $1147.05 | $757.19 | -33.988% |
| 304 | True | 7 | $716.90 | $473.24 | $1648.88 | $1088.46 | -33.988% |
| 304 | True | today_2_day | $716.90 | $473.24 | $2365.78 | $1561.71 | -33.988% |
| 316 | False | 21 | $465.54 | $462.94 | $465.54 | $462.94 | -0.558% |
| 316 | False | 14 | $465.54 | $462.94 | $744.86 | $740.71 | -0.557% |
| 316 | False | 7 | $465.54 | $462.94 | $1070.74 | $1064.77 | -0.558% |
| 316 | False | today_2_day | $465.54 | $462.94 | $1536.28 | $1527.71 | -0.558% |
| 316 | True | 21 | $751.50 | $507.84 | $751.50 | $507.84 | -32.423% |
| 316 | True | 14 | $751.50 | $507.84 | $1202.40 | $812.55 | -32.423% |
| 316 | True | 7 | $751.50 | $507.84 | $1728.46 | $1168.04 | -32.423% |
| 316 | True | today_2_day | $751.50 | $507.84 | $2479.96 | $1675.88 | -32.423% |

`reference.csv` includes each cost component, allowances/time split, multiplier, discount, absolute and percentage difference. `summary.json` records coverage and diagnostic cut lengths. The full CSV matrix is generated separately to keep the PR focused.

## Laser geometry findings — no active laser/material change

The legacy charged length is handle width + 2 × centerline-to-end + 3.14 × outside radius. It is not the actual cut perimeter and omits rough-bore and handle-hole cutting. For the reference, it charges 49.6225 inches. Independent reading of the generated DXF (LWPOLYLINE bulges plus circles) agrees with analytical canonical contour segments: outside 56.7525587862, rough bore 26.3108384738, handle hole 1.1780972451, total **84.2414945051 inches**. The rough bore is Ø8.375 inch. No DXF is changed.

The active $0.826/in scalar and legacy charged-length formula are deliberately preserved in this bore/chamfer PR. Correcting charged length would be a separate commercial change affecting the non-chamfer calibration. Do not mistake the diagnostic total for the currently charged length. Raw material uses the existing rectangular allocation, not net finished-part area; it is unchanged. Weight multipliers stored by the editor remain inactive, as before.

The owner-supplied commercial supplier comparison is reported privately rather than publishing supplier quotations or customer details in this public repository. Compare pre-tax finished-blank subtotal separately from freight, fuel, taxes, grade/finish, nesting and tolerances. An outsourced finished-blank quote replaces the material-plus-cutting provision; never add its raw-material content a second time. One geometry and mixed commercial conditions are insufficient to infer a trustworthy material/thickness rate matrix; no new laser rates are applied.

## Manufacturing assumptions still requiring owner confirmation

- These are nominal part-contour cutting-time estimates, excluding approach, acceleration, tool changes and measured cycle overhead; existing load/inspection charges are preserved. Cutter-center geometry, tooling and actual cycles require machining evidence.
- Confirm that one pass covers each proposed chamfer width and material/thickness using the selected tool. Confirm face access: accessible-face machining, flipping, or back-chamfer tooling cannot be established from the commercial quote inputs. If a flip/second setup is required, propose a separate measured setup charge before production adoption.
- Existing chamfer-specification/Frozen Plate HOLD and engineering fixture limits remain independent. This proposal does not manufacture missing geometry, qualify a setup, bypass a HOLD, change approvals or enable sourcing/release.
- Approve any separate laser-length/rate correction only after like-for-like supplier samples and the recalculated selling-price impact are reviewed.

## Safety and acceptance

Tests cover independent units/pass arithmetic; subtotal-wide lead and quantity multiplication; width-dependent chamfer time; no second load; owner-only allowance editing, invalid values, version conflict and history restore; disabled rush despite readiness; original public Coming Soon behavior; independent DXF cut-length agreement; accepted customer payloads and protected artifact hashes.

Historical customer orders, approvals and Frozen Plate artifacts are not repriced or regenerated. Only the pricing sections of synthetic convergence fixtures were updated; their request payloads and manufacturing hashes remain unchanged. No production API/configuration writes are performed by this task.
