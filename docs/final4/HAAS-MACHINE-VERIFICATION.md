# Rogue Machine Haas verification and acceptance worksheet

Status: PHYSICAL VALIDATION REQUIRED. No machine approval or NC transfer authorized.
The example profile and all cutting values are synthetic; they do not describe the installed VF-YT.
Complete one controlled record for each machine/setup/profile/input fingerprint.

| Required item | Actual measured/installed value | Evidence reference / verifier / date |
|---|---|---|
| Exact VF model, serial number, machine asset ID | UNVERIFIED | |
| Controller family, software revision and installed options | UNVERIFIED | |
| Renishaw/Inspection Plus macro revision and cycle documentation | UNVERIFIED | |
| P9832/P9810/P9814/P9833 installed behavior | UNVERIFIED | |
| Rough P9814 S1 changes G54 XY only; preserves G54 Z | UNVERIFIED | |
| Final P9814 has no S/T and performs measurement only | UNVERIFIED | |
| Diameter output #188 meaning, timing and overwrite behavior | UNVERIFIED | |
| Probe stylus ball diameter and ball-bottom H20 datum | UNVERIFIED | |
| Probe calibration record, runout and uncertainty | UNVERIFIED | |
| T1 actual diameter, runout, flute length, stickout, holder envelope | UNVERIFIED | |
| T2 actual tip diameter, included angle, usable cone length, maximum diameter, stickout | UNVERIFIED | |
| H1/H2/H20 actual registers, lengths and independent cross-check | UNVERIFIED | |
| D register geometry zero, signed wear, actual Setting 40 | UNVERIFIED | |
| Installed compensation mode/lookahead and lead-in/out behavior | UNVERIFIED | |
| G54 XY reference, Z0 at plate bottom/fixture datum | UNVERIFIED | |
| Fixture identity, part orientation and repeatable seating | UNVERIFIED | |
| Clamp locations, maximum height and whole-plate restraint | UNVERIFIED | |
| Through-bore opening radius, below-datum clearance | UNVERIFIED | |
| Approved tool-center/swept-tool work-coordinate travel limits with each H | UNVERIFIED | |
| G53 retract position, tool-change path and full holder clearance | UNVERIFIED | |
| Material grade/condition; actual thickness | UNVERIFIED | |
| Minimum as-cut bore, taper/ovality and uncertainty including centering shift | UNVERIFIED | |
| Rough/finish/chamfer RPM, feed, plunge strategy/feed, coolant | UNVERIFIED | |
| Supported full-depth axial engagement for actual material/tool | UNVERIFIED | |
| Finished bore tolerance, chamfer side/orientation and width | UNVERIFIED | |
| Independent measurement instrument, calibration and uncertainty | UNVERIFIED | |

The v1 machine-profile contract retains the accepted nominal half-inch end mill
and nominal .080-tip 90-degree chamfer tool. Alternate cutter families, bottom
chamfers, multi-pass axial strategies and metering edges are unsupported. A new
qualified strategy/version is required; do not change geometry to evade a hold.

The strategy parameters separately version radial pitch, radial finish stock and
chord tolerance. Machine profile fields version tools, feeds, spindle speeds,
probe clearances, fixture/work travel, compensation and material selection.
Bore tolerance is bound to the customer-approved spec, never silently relaxed.
A single finish stock quantity is the allowance left by roughing and removed by
finishing; they are not two additive allowances.

## Independent review and simulation record

Order/line/plate/revision: ____________________
Frozen spec/source SHA-256: ____________________
Generator/post version, input/profile fingerprint: ____________________
Review bundle/manifest/NC SHA-256: ____________________
Generating operator: __________ Independent programmer: __________ Date: ______

- Reconcile finished part, rough nominal DXF and measured physical blank. Nominal
  rough diameter 1.423 for finished 1.548 is NOT an as-cut measurement.
- Review the exported numerical paths and full posted candidate in an independent
  backplot/control-compatible simulation. Record simulator/version, stock,
  machine/fixture/tool models, file hash, findings and resolved issues.
- Check G20, G17, G90, G94; G40/G49/G80 entry; length compensation; wear-only D;
  CCW direction; probe insertion and straight-wall band; safe retract and M30.
- Check every reposition, radial lead, holder/fixture/clamp clearance and G53/tool
  change in the installed control context. Numeric geometry does not emulate macros.
- Confirm the predicted compensated diameter remains in tolerance. No automatic
  offset correction, recutting or final-probe manufacturing approval is provided.
- Approve an exact candidate for controlled prove-out only after actual setup
  verification. `post_candidate` is an offline trusted-adapter API, never an HTTP
  action. Identity labels are attestations requiring real evidence, not proof.

## Controlled physical prove-out under shop procedure

1. Shop programmer and setup operator choose and document the installed-machine
   dry-run/graphics/single-block procedure, clearance observations, overrides and
   stop criteria from its manual and shop practice. No generic override values
   are prescribed here. Do not disable interlocks or bypass probe safeguards.
2. Verify the exact candidate hash, program number, actual offsets/tools/fixture,
   clearances and calibrated probe before any controlled machine test.
3. Evaluate approach/retract, tool changes, compensation and probe behavior using
   the approved procedure. Stop on any unexpected motion, alarm or clearance.
4. Use a documented sacrificial first piece/blank, not a live customer order.
   Inspect restraint and breakthrough. Record cut behavior and actual dimensions.
5. Record final probe output at M00 before another cycle overwrites it. Independently
   gauge bore at multiple angular and axial locations; inspect chamfer, burr,
   finish and complete through-wall cutting. Record instrument/uncertainty.
6. Reconcile the measurements to the exact revision and drawing tolerance.
   Parameter/offset changes require a new fingerprint, candidate and review.
7. Attach signed physical results, independent programmer approval, setup approval
   and owner manufacturing-release authorization to a future controlled release
   adapter. This branch deliberately has NO manufacturing release operation.

Physical results: NOT MEASURED. Pass/fail/hold: ______ Findings: _______________
Physical prove-out reference: __________ Programmer signature: _______________
Owner manufacturing release (separate, not granted here): ___________________
