# Corrugated package prototype and acceptance

Status: PHYSICAL VALIDATION REQUIRED. The assembly itself is the shipping package.
No dimension, board grade, pad thickness or shipping durability is certified.

## Architecture decision

| Construction | Material/assembly implications | Decision |
|---|---|---|
| Continuous folded multilayer | Fewer loose pieces; additional score/gusset locations and cumulative flute/fold error; larger irregular blank; depth-specific fold recipe | Documented alternative, not implemented |
| Tri-fold shell + stacked center frames | One shell and N identical frame cuts; count/alignment and pad fit must be controlled; simple variable-depth schedule; separately replaceable tooling/coupons | Implemented prototype |

A solid center backing, left protective panel and right closing panel form the
shell. Four score axes form two wrapping spines. Frame openings use only the
finished external contour. The bore and handle hole do not remove backing material.
Single-part packaging is implemented: an order quantity Q requires Q separate
packages. Multi-part shipping packs are outside this construction.

N = ceil((plate thickness + protective depth clearance) /
(board caliper * (1 - compression fraction))). Nominal spine heights derive from
N * caliper; the second spine also accommodates the first closing panel thickness.
Fold allowance is explicit. Measured fold coupons must establish real score widths,
board crush and the required allowance; nominal caliper is not a bend model.

Profile sampling bounds deviation at .0001 inch. The nest cutter-center contour
is expanded by clearance minus half the measured kerf plus the sampling allowance.
The CAM must not add a second nest kerf correction. Outer shell/frame outlines are
nominal; verify the small loss of outside margin from the cut. Shapely/GEOS and
DXF versions are pinned through requirements-final4.txt for reproducibility.

## Closure assessment

Primary prototype: single-thread chain stitching. Qualify a real machine using
coupons of the entire folded stack at its thickest seam. Verify presser-foot lift,
needle/thread suitability, throat access, feed grip, tear-out, compression,
start/end chain retention and deliberate tear-open direction. Keep the release
end secured against accidental unravelling. The guide in the DXF is a projected
perimeter reference, not a stitch machine program. Start with a clear seam away
from the plate; use removable fixture stops so the sewing head can traverse all
sides. Closure settings and stitch pitch remain unqualified.

Secondary prototype: staples with the correct crown/leg/clinching process for
measured folded thickness. Check anvil access, full clinch, exposed ends, edge
tear-out and contact exclusion from the nest. Stapling may simplify straight seams
but creates hard points; do not adopt it without face/edge damage checks.

Manufacturer literature reviewed 2026-10-15: [nVenia/Fischbein F-series](https://www.nvenia.com/blog/fischbein-f-series-portable-bag-closer-no-one-else-comes-close-in-quality-and-durability/)
describes sewing paper and other bag materials. It does not qualify this thick
corrugated assembly. Sewing feasibility remains an inference requiring coupons.
No machine purchase, supplier contact or equipment capability is assumed.

## Fixture concept

Separate `fixture-reference.svg`: flat platen, square side/end stops locating the
center backing, removable stops for frame placement, two folding shoes registered
to spine score pairs, and an open perimeter for closure. Use a clean sacrificial
surface. Keep stops outside metal/needle/staple paths and verify insertion/removal.
This is reference geometry only, not a fabrication drawing. Record prototype cycle
time separately for shell/frame loading, part insertion, folds, closure, inspection.

## Prototype selection matrix

| Sample | Purpose | Required checks |
|---|---|---|
| Small, short handle | Minimum outline and frame ligament | Fit, handling, scoring access |
| 5 inch OD, 10.5 inch centerline-to-tip, .125 thick | Canonical thin plate | Two-layer count with synthetic board, axial pads, clean bore protection |
| Same, .500 thick | Maximum thickness | Variable layer count, wrap depth, thickest seam, closure access |
| 30 inch handle | Long unsupported lever | Handle restraint, end drop, bending/puncture |
| 4.8 inch wide handle / 5 inch OD | Wide neck envelope | Contour offset and registration |
| Optional handle hole | External-nest invariance | Same cut shape, no closure through handle hole |
| 24 inch OD / 36 inch centerline-to-tip | Cutting-sheet limit | Correctly held when combined layout exceeds 120 x 120; split-sheet layout is future work |

## Physical acceptance procedure

1. Identify board supplier/grade/flute, lot, humidity/conditioning, measured caliper
   distribution, liner strength and contamination. Record actual cutting equipment,
   kerf and score method. Select machine-approved cutting settings with ventilation,
   fire control and material handling procedures; no laser settings are generated.
2. Cut kerf/score/closure coupons first. Adjust versioned configuration from evidence;
   do not silently change an existing bundle. Record flat and folded dimensions.
3. Count frames; align on stops. Measure nested depth under closure compression.
   Fit measured clean nonabrasive pads to occupy excess cavity; preserve precise
   surfaces and the target depth gap. Pad values in schedule are unvalidated targets.
4. Check insertion force, support at body/handle, XY gap, axial free play, panel
   registration and fit after reopening. Reject force-fit, loose sliding, liner
   abrasion, bore marking, exposed steel and edge punch-through.
5. Qualify both closures where practical. Evaluate maximum thickness and repeatable
   access, crush, exposed hard points, chain unravel/tear-open behavior and reclosure.
6. With representative part mass and center of gravity, conduct a documented
   handling/shipping protocol appropriate to the intended carrier/service: face,
   edge and corner impacts, vibration, stack/compression, abrasion, humidity/wet
   exposure and closure snags. Shop/packaging reviewer selects protocol and limits;
   software provides no certified drop heights or carrier approval.
7. Inspect plate dimensions/finish and every seam after testing. Record movement,
   puncture, crushed liner, corrosion exposure and damage. Increase protective margin,
   add engineered tabs/barriers, change board or closure and re-test on a NEW version
   when failure occurs. Tabs and water resistance are not implemented/certified.
8. Record measured package dimensions/mass for shipping decisions only after
   validation. No packaging mass is estimated without validated material density.

Acceptance record: order/line/revision ______ bundle/manifest SHA ______ config ____
Board/lot/caliper/kerf ______ closure/equipment/settings ______ pads ____________
Fit results ______ test protocol/results ______ damage/hold ___________________
Cycle time ______ independent reviewer/date ______ physical approval __________
Owner release (separate): ______  Current state: PHYSICAL VALIDATION REQUIRED.
