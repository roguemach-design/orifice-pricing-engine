# O-PLATES — THE FINAL 4 HANDOFF

Date: 2026-10-15. Status: implemented software and isolated staging; physical validation required.
Branch: `work/final-4-manufacturing-automation`.
Engineering/staging source SHA: `114707970d5c0a2105a24973944924f1d23155d8`.
This handoff/evidence commit follows that source without changing runtime behavior.
Final branch SHA is supplied with delivery and in Git history; this file cannot contain
its own commit hash without changing it.

## Source reconciliation and isolation

Live GitHub branches and PRs were inspected before editing. `main` remains
`94731f295fd842cdac8dbbbea44cc0e54f1832e8`, behind accepted customer features.
Accepted public integration/production UI serves
`fa354e5d80175b58b156937cda188bd74d05d49d` on
`work/landing-configurator-convergence`; Render deploy
`dep-db7s2i67bikc73ccoil0` confirmed that base.

The prior Haas source `35188c1f62c6b1dfee24c7bcefff404cc6cf8258` is retained as
an additional parent of Final 4 integration commit `1ebad8820de497d07f813131a70efc897271f4ef`.
No rewrite of accepted geometry or existing generator was performed.

The separate active `work/manufacturing-control` branch was observed at
`6fa0d856e544f789128e54739023c458a32336c2`; its API/UI staging services are both
attached to that branch. They were not changed or redeployed. No active portal,
customer UI, pricing, Stripe, SendGrid, approval, original Frozen Plate module,
steel DXF/PDF generator or production deployment file was edited by Final 4.
Original .125-inch diametral rough-bore allowance remains unchanged.

Published work-package commits:

| Package | Commit | Actual result |
|---|---|---|
| Reuse accepted Haas | `1ebad8820de497d07f813131a70efc897271f4ef` | Accepted review generator brought into live integration base |
| Haas engineering | `836d115a4f957b4a8a06f5e3256cbe95fd1f1908` | Versioned strategy, independent geometry checks, guarded review and controlled offline candidate post |
| Packaging | `c0c7f110138d0b8857a7f95ca683826c28e3cdae` | Parametric tri-fold shell and variable-depth center frames |
| Backend | `348861c14747aa89a7185be310bd0a2542417fd6` | Append-only derived bundles, exact parent checks and owner router |
| Validation/staging | `26ac3d5489d35ad8801f777c36139ad40f76561b` | Tests, reproducible samples and isolated staging harness |
| CNC review findings | `c3992229075268750efa211ce486a84837f480cd` | Explicit chamfer face orientation and candidate program-number gate |
| Staging constraints | `114707970d5c0a2105a24973944924f1d23155d8` | Tested dependency constraints and repeatable HTTP verifier |

## Evidence-based acceptance matrix

| Work package | Implementation | Software tested | Staging | Physical verification | Manufacturing release |
|---|---|---|---|---|---|
| Haas | IMPLEMENTED: review/candidate engineering architecture | SOFTWARE TESTED | Synthetic backend verified | PHYSICAL VALIDATION REQUIRED | BLOCKED pending actual machine/profile/programmer/prove-out evidence; disabled |
| Packaging | IMPLEMENTED: prototype cut files and assembly schedule | SOFTWARE TESTED | Synthetic backend verified | PHYSICAL VALIDATION REQUIRED | BLOCKED pending board/closure/shipping acceptance; disabled |
| Frozen Plate derived integration | IMPLEMENTED in opt-in service/router and isolated SQLite/private storage | SOFTWARE TESTED | Synthetic Frozen Plate workflow | Production PostgreSQL adapter/migration and portal integration remain pending | Disabled |
| Validation/handoff | IMPLEMENTED: regressions, independent reader checks, examples and worksheets | SOFTWARE TESTED | Isolated service only | Shop acceptance records blank | No automatic release |

No PHYSICALLY VERIFIED or MANUFACTURING RELEASE APPROVED claim is made.

## Haas deliverables and limits

`haas_generator/engineering.py` adds bounded/versioned rough radial pitch, finish
stock and chord tolerance. Existing machine profile supplies material-specific
feeds/RPM, tools, probe clearances, work/fixture bounds and wear constraints. Every
complete input set, profile, parameters, setup context and parent revision contributes
to the engineering fingerprint; revisions/parameters never overwrite an old bundle.

Guarded review program, setup sheet, inspection form, paths.svg, simulation.json,
inputs.json, independent verification.json, readiness.json and manifest.json are
implemented. Full-depth bore machining retains the existing strategy, followed by
optional supported top chamfer and measurement-only final probing. The installed
machine/control/macros and compensation transitions still need independent review.

The old guarded NC output remains non-executable. `post_candidate` is a distinct
versioned offline trusted-adapter path: verified machine/setup profile, independent
programmer evidence bound to exact input/profile/post fingerprint, explicit
nonreserved program number and resolved numeric/setup holds are required. Its
output is a PROVE OUT CANDIDATE with a deliberate M00, never manufacturing-approved.
There is no candidate-post HTTP endpoint, machine transfer or release operation.
No real executable candidate was generated because real shop evidence is absent.

State vocabulary retains DRAFT, ENGINEERING REVIEW, SETUP VERIFICATION REQUIRED,
SIMULATION VERIFIED, MACHINE PROVE-OUT REQUIRED and APPROVED FOR MANUFACTURING.
Numerical geometry tests never award SIMULATION VERIFIED. Independent exact-bundle
evidence may record engineering review and simulation; physical and release states
are intentionally unavailable until a separately reviewed evidence/release adapter.
Generated files immediately enter review/setup hold, rather than awarding all gates.

See [Haas worksheet](docs/final4/HAAS-MACHINE-VERIFICATION.md) for machine serial,
controller, probe/macros/calibration, tools/H/D/stickout, G54/datum, fixture/clamps,
retract/toolchange/travel, material parameters, programmer review and first-piece
acceptance. Unknown values remain UNVERIFIED.

## Packaging deliverables and recommendations

Implemented: finished-outline negative-cut nests with configured XY clearance,
kerf adjustment, solid bore/face backing, support for the handle, dynamic nesting
layers from caliper/compression/thickness/clearance, two wrapping spines and distinct
CUT, SCORE, reserved PERF, REGISTRATION/ASSEMBLY references and CLOSURE guide layers.
Actual outline includes the accepted tangent corner geometry; optional handle holes
do not alter the external nest. The folded assembly is the package itself.

Preferred flexible prototype: tri-fold shell plus separate stacked center frames.
The continuous folded-multilayer alternative is evaluated but not implemented.
Primary closure is chain-stitch coupon development; mechanical staples are the
fallback. Neither closure is physically qualified. The board/example caliper and
compression are synthetic inputs, not purchasing specifications or validated defaults.
Measure and version actual board/kerf/score/fold/pad/closure values before a real cut.

Each bundle contains packaging.dxf, assembly.md, schedule.json, layout.svg, separate
fixture-reference.svg, inputs.json and SHA-256 manifest. Schedule includes flat and
folded envelope estimates, net/gross board area, layer count and axial pad targets.
Mass stays null without validated material data. One part per package; quantity Q
requires Q packages. Combined layouts exceeding the configured sheet are rejected;
a multi-sheet optimizer, tabs and wet-weather protection remain future development.

See [packaging acceptance](docs/final4/PACKAGING-ACCEPTANCE.md) for comparison,
flute/score/kerf coupons, fixture concept, closure investigation, fit and shipping tests.

Representative outputs regenerate with `python -m final4.samples` after installing
`requirements-final4.txt`. Five packaging cases: small/short, canonical .125, canonical
.500, long handle and wide handle. Two Haas examples: thin chamfered and .500 unchamfered.
They are synthetic fixtures, not real customer revisions. The separate review ZIP
contains these files, assembly/setup documents, worksheets, manifest/hash evidence
and inspected overview images. No unguarded production program is included.

## Frozen Plate integration and portal handoff

`final4.service.DerivedService` attaches HAAS/PACKAGING to exact
Order -> Line -> Plate -> Immutable Revision. Current exact customer approval is
required for generation. Order/line/plate/revision/spec/source hashes and compatible
machining inputs are verified under the parent workflow transaction. New parameters
create a distinct bundle; SQL triggers prevent update/delete in the isolated store.
New files are privately published and verified before metadata commit. Ordinary
GET fetches exact stored bytes and checks size and SHA-256; it never regenerates.
Historical downloads remain audit-only; superseded parents cannot generate or gain
new evidence. All release eligibility remains false.

Implemented owner API: POST bundles, POST bundles/query, GET bundle metadata and
GET bundle/file bytes under `/admin/manufacturing`. Router accepts the existing
owner auth/rate-limit dependency; public customers have no generation/download route.
Statuses separately report existence, byte verification on download, parent currency,
customer approval, engineering review, simulation, physical validation and release.

Exact endpoint/request/response schemas, error codes, UI labels, filename standards,
authorization and compatibility requirements are in
[Manufacturing Control API handoff](docs/final4/MANUFACTURING-CONTROL-API.md).
Existing steel naming is preserved. New names explicitly contain HAAS-REVIEW or
PACKAGING-PROTOTYPE plus order/line/revision/bundle identity.

Persistence limitation: explicit isolated SQLite installer is implemented. An unapplied additive PostgreSQL migration proposal with restricted-role RLS,
immutability triggers and a revision lookup index is provided in
`docs/final4/postgres-additive-PROPOSAL.sql`. It has not been executed or verified
against PostgreSQL. Remote migration and adapter verification have NOT been performed. Service reuses accepted private-storage hooks, but no
production DB or customer record was accessed/migrated. Complete and test the additive
private PostgreSQL migration against the existing adapter before portal production use.
The frontend mount remains the other session's coordinated follow-up, not a hidden
replacement admin page delivered here.

## Validation and staging evidence

Final local regression: **764 passed, 5 skipped, 2 existing framework warnings**, Python
3.12.14. Focused new/accepted Haas suite: **95 passed**. Compilation, dependency
compatibility (`uv pip check`) and whitespace checks pass. The five skips concern
existing optional/private fixtures; none are new Final 4 failures.

Tests cover deterministic bytes, independent DXF reopening/audit/units/closed cuts,
score separation, analytic contour containment/clearance, variable nesting depth,
sheet/layer/material-parameter limits, handle-hole invariance, cutter-center geometry,
probe contact, wear/chamfer, changed-input fingerprints, exact parent/spec mismatches,
unapproved/superseded parents, append-only concurrency, storage size/hash tampering,
owner authorization, profile override rejection, request size and absent release paths.
Existing production source files and original manufacturing generators have no diff.

Inspected rendered paths.svg and thick packaging layout. The observed circles/spiral
match bore machining scope; the packaging shows shell/spines and five separate .500
plate nest layers for the illustrative .125 board/.10 compression configuration.
Visual inspection is not collision or shipping certification.

Isolated free Render service: `srv-db8bphqvcj2c738ub54g`.
URL: https://oplates-final4-engineering-staging.onrender.com/health
No frontend is served at `/`; HTTP 404 there is intentional.
Auto-deploy is off. Only synthetic ephemeral records are created at startup.
No production DB/storage/payment/email key is installed.

Initial source `c3992229075268750efa211ce486a84837f480cd`, deploy
`dep-db8bpi2vcj2c738ub6gg`: LIVE; 12 HTTP checks passed, all **16 files** downloaded
and independently size/hash verified. Fresh HAAS and PACKAGING bundles were created;
wrong/anonymous credentials, wrong parent, profile override, oversized body and absent
release route behaved as expected. Original synthetic PDF/DXF/spec remained immutable.

Final pinned-dependency deployment `dep-db8br3uq1p3s73aab5p0` at source
`114707970d5c0a2105a24973944924f1d23155d8` is LIVE. All 12 HTTP checks and
16 exact-byte downloads passed again. Evidence is recorded in
`docs/final4/staging-evidence.json`. No error-level Render logs were returned.
GitHub CI run 38729964765 completed successfully for this source. The harness uses real Frozen
Plate repository/approval/integrity code with synthetic data, not the remote production
adapter. Authenticated staging is an engineering API, not the active owner UI.

## Owner-controlled decisions and next sequence

1. Review this isolated branch and samples with the portal session. Recheck accepted
   branch heads; integrate through a reviewed PR. Do not merge portal WIP into Final 4
   or overwrite its environment. Re-run conflicts/regressions if accepted base advances.
2. Complete the additive private PostgreSQL schema/authorization/immutability adapter
   work and test it on synthetic staging records. Mount the documented router using
   existing owner auth and wire the other session's five-file UI labels/downloads.
3. Select actual board/flute/lot and cutting/score equipment; measure caliper/kerf and
   closure coupons. Select chain stitching or staple fallback from evidence. Tune
   clearances/margins/pads/folds, cut representative prototypes and test shipping damage.
4. Complete machine worksheet using installed VF-YT model/serial/controller/macros,
   calibrated tools/probe, verified physical blank/fixture, approved cutting values and
   program slot. Obtain independent programmer backplot/control review and authorization.
5. Through a future explicitly authorized shop procedure, create an exact executable
   prove-out candidate and perform controlled sacrificial first-piece inspection.
   This task did not operate/connect/transmit to the machine.
6. Preserve signed revision-specific physical results and approvals. Build/review the
   final evidence-to-release adapter separately. Customer approval alone cannot release
   machine work or qualify packaging; no current boolean/API can bypass those gates.
7. Obtain separate owner production deployment approval, then deploy additive backend
   and coordinated portal UI. Existing frozen bytes/hashes stay unchanged. No vendor
   submission, customer payment/email action or manufacturing release is authorized here.

Outstanding owner inputs are physical machine/setup evidence, independent programmer,
actual board/cutting/closure/pad choices and signed physical acceptance. No additional
software planning decision prevented the completed independent work above.
