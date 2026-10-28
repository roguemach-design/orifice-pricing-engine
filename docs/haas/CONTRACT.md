# Internal Haas bore generator contract, v1

Status: **REVIEW ONLY - NOT RELEASED FOR MACHINE USE**.

## Source and boundaries

Inspected live main `94731f295fd842cdac8dbbbea44cc0e54f1832e8` (PR #9 merge),
the current branch inventory, main's PUBLICATION_REVIEW.md and manufacturing /
Frozen Plate modules, and the Library publication/business handoffs. Also inspected
the current intake branch `work/drawing-intake-phase1h-owner-acceptance` at
`24880d8`, its confirmation contract and Phase 1H/1I handoffs. Intake's customer
confirmation is a pricing gate, not a manufacturing or machine approval.

This feature starts from main, on `work/internal-haas-generator`. It does not
import or change the production API, admin dashboard, customer pages, pricing,
checkout, Frozen Plate repositories, deployment configuration or recognition
branch. No schema changes, provider calls, migrations, email, vendor submissions,
machine connections, merges or deployments occur.

Intake, print recognition and eventual DXF import are **candidate producers**.
A programmer must reconcile their proposals to the source drawing, actual blank
measurements, required tolerances, physical orientation and job/revision. Only
then may an authenticated admin submit the ReviewedRecord below. Authentication
authorizes draft generation, not manufacturing release. `reviewed_by` and source
hash are admin attestations; this offline feature does not query a review system,
download the source, or verify the source hash against external bytes.

V1 deliberately excludes recognition/OCR, DXF parsing, arbitrary contours,
metering edge rules, multi-part nesting, bottom chamfers, non-45-degree chamfers,
automatic process selection, feeds/speeds estimation, inspection-result ingestion,
recutting, offset correction, customer access and release state management.

## ReviewedRecord (exact JSON keys, no extras)

| Field | Meaning |
|---|---|
| schema_version / units | `"1"` / `"inch"`; no implicit conversion |
| job_id / part_id / drawing_revision | Stable job, part and drawing revision labels |
| source_kind | `intake`, `print-recognition`, `dxf-import` or `manual`; provenance only |
| source_sha256 | SHA256 of the reviewed source document / immutable source snapshot |
| reviewed_by / review_reference | Programmer identity and review evidence reference; cannot be empty |
| finished_bore / bore_tolerance | Nominal finished diameter and symmetric +/- diametral tolerance in inches |
| actual_blank_bore | Measured minimum inscribed WJ/laser blank diameter; never the .125 allowance computed by DXF |
| blank_radial_uncertainty | Conservative radial envelope including taper, ovality, measurement uncertainty and centering shift |
| thickness / material | Reviewed actual plate thickness and exact approved material label |
| top_chamfer_width | Radial top-edge width at 45 degrees from face; `0` explicitly means none |

The record is immutable during generation. Job labels use safe ASCII to prevent
NC/comment injection. Finite numbers, explicit units, complete review provenance,
positive dimensions, valid tolerance and a machinable stock envelope are required.
Unsupported or contradictory records fail with no output bundle.

`examples/haas/record.json` is a synthetic contract example, not a real job.
No quote price or checkout/order authority enters this contract.

## MachineProfile (trusted server file, never supplied in POST)

`examples/haas/profile.json` enumerates **every exact field**. All its operating
values are synthetic simulation inputs, including feeds/RPM, stylus, travel and
fixture values. They are not recommendations for stainless machining and are not
evidence about Rogue Machine's VF-YT. `verified_by=null`, `evidence={}` keeps them
on HOLD. A real profile must be populated from the installed machine and setup.

| Group | Required information |
|---|---|
| Identity | profile revision, exact machine/model/serial and control/macro versions |
| Evidence | Named references for all `CHECKS` in contract.py and named verifier |
| T1 | Actual diameter, flute length, H and D register, zero D geometry, small signed wear value |
| T2 | Actual tip diameter, 90-degree included angle, usable cut length, maximum cutter diameter, H2, physical-tip depth |
| T20 | H register, calibrated ball radius, physical-tip to ball-center distance, edge margin, overtravel and protected-move feed |
| G54 and fixture | Safe Z, clamp height, bottom cut Z, verified below-datum clearance and radial fixture opening, maximum centering shift |
| Cutting | Explicit material-specific rough/finish/chamfer RPM/feed, plunge feed, machine RPM/feed limits |
| Compensation | Actual Setting 40, D geometry zero, entered wear and allowed radial wear bound below .010 finish stock |
| Travel | Approved min/max work-coordinate swept-tool envelope after accounting for actual G54 and each H offset; verified G53 retract/toolchange path |

Evidence categories: machine_identity_and_control, fixture_and_clamp_clearance,
g54_fixture_z, travel_and_toolchange, tool_geometry_and_h_offsets,
setting40_and_d_wear, material_feeds_and_spindle, wips_calibration_and_macros,
probe_xy_only, probe_measurement_only, probe_result_variable, rough_bore_envelope.
References must identify genuine setup verification; entering a label is not
itself a verification procedure. Work-envelope bounds are not catalog axis
travels. Holders, clamps, plate extent and toolchange require physical review.

Profiles are checked for geometry, clearance, offset conventions and limits even
if evidence is missing. Thus numerically invalid unverified profiles also fail.
Complete evidence removes those HOLD entries but **never releases NC**.

## Correction of earlier conversation

For nominal T1 diameter .500 and finished bore 1.548:

| Quantity | Radius, inches |
|---|---:|
| Finished bore edge | .774 |
| Nominal finish tool center | .524 |
| Rough tool center leaving .010 radial stock | .514 |

The old example described bore-edge radii as cutter-center coordinates. The
nominal cutter radius must be subtracted before programming motion. V1 roughs
from a conservatively clear blank-tool radius in an outward, segmented
Archimedean spiral with .035 radial pitch per revolution. It then makes a full
rough cleanup circle. Chord error is bounded approximately at .0002; this is not
constant-engagement HEM, and actual remaining stock can include that chord error.

Finish programs the nominal cutter-center path with linear radial lead-in/out,
CCW G03 and G41 D wear-only compensation. Positive wear shifts the CCW path
inward and reduces bore diameter; negative wear increases it. Setting 40 DIAMETER
means entered wear/2 is radial correction; RADIUS uses entered wear directly.
D geometry must be zero: entering the nominal half-inch cutter again would
double-compensate a CAM-offset path. G43 H remains length compensation.
Both nominal and signed-wear-adjusted circular paths are exported. Lead
transitions depend on the installed Haas compensation mode/lookahead and must be
reviewed on that control; this geometric simulator does not emulate them.

Z0 is the plate bottom/fixture datum, not the top. The straight bore wall ends
at thickness minus chamfer radial width (45 degrees). V1 places the whole probe
ball between datum and that wall limit with explicit margins. Programmed probe
Z is the physical ball-bottom position, based on the profile's **verified H20
ball-bottom calibration**. A fixed Z+.125 lies at the top of a .125 plate and is
not a valid contact depth. A common larger stylus may leave no valid measurement
band on a thin chamfered plate; that is an error, not permission to guess a depth.
Z-.020 is allowed in a numeric draft only when the profile supplies at least .020
below-datum fixture clearance plus a sufficient radial opening. Without genuine
fixture evidence the draft remains on HOLD. Zero breakthrough also remains on
HOLD pending complete through-wall finish verification.

T2 uses its flat-tip diameter rather than an imaginary sharp point. For included
angle 90, top tool radius = tip_radius + tip_depth. Center path radius =
finished_bore/2 + chamfer_width - top_tool_radius. At top minus chamfer_width,
the cone intersects the finished cylindrical bore. The generator rejects a
cone contact outside the cutting length or maximum diameter and any chamfer
physical-tip Z below datum. It never creates a bottom chamfer.

## Probe/post boundary

Candidate calls are limited to the documented Inspection Plus family:
P9832 on, P9810 protected Z positioning, P9814 internal bore, P9833 off.
Rough P9814 uses `S1` to update G54 X/Y. It has **no Z argument** (which selects
the boss cycle in the reference manual). No Z-offset assignment is emitted.
Final P9814 has no S or T arguments and runs after chamfering at straight-wall
depth. It has an immediate M00 for manual transcription of the documented
diameter output #188 before another cycle overwrites it. No macro assignments,
automatic tolerance correction, tool updates, recut loops or work-offset writes
are emitted. The installed macro library must be verified to preserve G54 Z and
to make the final call measurement-only. A programmer may need a version-specific
post before machine prove-out; this version cannot accept arbitrary injected code.

## Deterministic outputs and service boundary

Outputs: `program.NC`, `setup.md`, `inspection.md`, `paths.svg`, `simulation.json`,
`inputs.json`, `manifest.json`. Each bundle binds the complete reviewed record and
machine profile to SHA256 hashes and a generator version. Stable formatting, file
ordering and ZIP metadata produce repeatable bytes in the pinned Python 3.12.14
environment; there are no random IDs or generation timestamps. Changing a source
revision changes the hashes and invalidates an earlier review bundle.

NC is deliberately non-executable: alarm + M30, followed by commented candidate
blocks. **No verification flag or API action removes those guards.** The setup
sheet and inspection form carry the same review-only status. The inspection
record is blank/UNMEASURED and is not a fabricated measurement certificate.

The separate FastAPI service has HTTP Basic admin authentication on its page,
profile and generation endpoint. It requires a dedicated `HAAS_ADMIN_KEY` with
at least 32 ASCII characters; it does not fall back to a customer or production
API key. Profiles are loaded server-side; client profile/release fields fail.
Request size and path complexity are bounded. Nothing is persisted server-side.
Responses are no-store, and no credentials are printed. Local CLI access trusts
the OS operator; it is not a public API.

Run offline:

```sh
python -m haas_generator --profile examples/haas/profile.json \
  --record examples/haas/record.json --output /tmp/new-haas-review
```

Run locally with a dedicated key supplied securely through the environment:

```sh
python -m haas_generator --profile /path/to/reviewed-machine-profile.json --serve
```

The service binds **127.0.0.1:8091**; use username `admin` and the dedicated key.
Do not expose Basic authentication over public plaintext HTTP. No hosting or
production deployment configuration is provided by this change.

## Verified references, not actual shop verification

- [Helical 59845W](https://www.helicaltool.com/products/tool-details-59845w):
  .500 cutter, .625 cut length, five flutes. Actual diameter, stickout and cutting
  parameters still require shop review.
- [Helical 07029](https://www.helicaltool.com/products/tool-details-07029):
  90-degree included angle, .080 tip, .210 cutting length; verify physical tool
  and usable geometry before choosing chamfer tip depth.
- [Haas Setting 40](https://www.haascnc.com/service/codes-settings.type=setting.machine=mill.value=S40.html):
  radius/diameter interpretation applies to geometry and wear.
- [Haas G41/G42](https://www.haascnc.com/service/codes-settings.type=gcode.machine=mill.value=G41.html):
  signed offset and left/right convention.
- [Renishaw Inspection Plus reference hosted by Haas](https://www.haascnc.com/content/dam/haascnc/en/service/reference/probe/renishaw-inspection-plus-programming-manual---2008.pdf):
  bore/boss P9814, S1 G54, result variables and protected moves. It is a 2008
  reference, not proof of the installed machine's macro version.

Actual VF-YT model/serial/control, installed probe calls/calibration/result
variables, Setting 40/compensation mode, T/H/D offsets, measured cutter geometry,
material feeds/speeds, G54 location, fixture clearances and safe travel remain
unverified. A programmer must review the exact bundle and then conduct controlled
machine prove-out under shop procedures. Geometry tests cannot replace that.
