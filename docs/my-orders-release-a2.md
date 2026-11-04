# My Orders Release A2 — secure approved drawing viewer

Stacked on the separately reviewed A1 branch. No API/schema/migration or business
calculation change. The API remains the isolated `6b3c5de962c87f5ef59948c658947cddb1d92a56`
release; customer repository copies of API/pricing modules are NOT an API candidate.
Never deploy a customer tree as an API release.

## Scope and architecture

The selected approved revision loads the actual stored PDF automatically above the
purchased specifications. The existing authenticated archive endpoint and its
ownership-before-storage checks are unchanged. Both Python and the browser verify
artifact integrity; approved revision ID, recorded hash and byte count must match.
Current and authorized superseded approved revisions are distinct. Pending drawings
remain in their existing explicit approval workflow, not the approved viewer.
No geometry regeneration, public storage URL or manufacturing document is used.

Technology evaluation and maintenance instructions are in
customer_pdf_viewer/README.md. The pinned PDF.js 6.5.438 assets are bundled locally.
Native Streamlit PDF's optional component was evaluated; its bytes-to-media default
and absent fullscreen control did not satisfy this scope. The chosen component
provides fit, zoom, mouse/touch pan, full-screen, page navigation, keyboard controls
and a browser-local Blob download of the exact original bytes. Canvas memory is
bounded. Failure to render offers a clearly labeled verified-file fallback.

The approved archive uses no shared Streamlit image/download/media URL. Browser
acceptance independently checks exact Blob downloads, anonymous failure to resolve
private Blob URLs, public component sources without artifact bytes, and cleanup
on logout. Existing real API tests verify anonymous/cross-owner rejection before
storage and reject tampered bindings/artifacts. UI state hints never authorize reads.

## Fit, accessibility and limitations

My Orders content is capped at the approved 918 px. The desktop rail is fixed at
200 px with an 18 px gap. Below 900 px of actual content width, the rail is hidden,
with a full-width detail view and Back to Orders. A native accessible plate picker
replaces the design's wide tab strip; supporting information uses expanders below
the drawing. Original prices are never inferred; missing documents/tracking/PO are
explicitly unavailable. Reorder actions are omitted.

Browser acceptance exercises 320/375/390/768/1080 px and a 1920 px browser containing
the actual embedded landing shell. Test-only origins point to loopback fixtures;
no production record, OTP, purchase, approval or configuration is touched. Browser
screenshots contain representative synthetic data. Real iOS/Safari hardware is not
covered by Chromium emulation; browsers denying Fullscreen API get the verified-file
fallback and require manual device acceptance before claiming that platform.

## Fit Page investigation and acceptance contract

The local 1080 px failure was a test interaction error during the host's existing
smooth scroll, not a lost accepted Fit command. Focused event capture reproduced
125% remaining for five seconds: the attempted Fit pointerdown/up/click landed on
a surrounding Streamlit DIV; no event reached the PDF iframe. In the same trace,
accepted Fit clicks reached #fit, changed status to Rendering drawing page, then
updated zoom and canvas back to the calculated fit. One recorded accepted Fit
updated zoom from 125% to 100% in approximately 6 ms. No fullscreen was active.
A diagnostic pre-seeded zoom state to isolate Fit; final acceptance uses real
pointer clicks for both zoom and fit.

The correction is test-only. click_drawing_control centers the nested control in
the host viewport and waits for the browser's actual scrollend event at that
position before normal Playwright click coordinates are calculated. The 5-second
limit is a failure timeout, not a sleep. No forced clicks, reduced-motion override,
application zoom change, or assertion weakening is used. New default-motion tests
at 390/768/1080 px assert all 24 actual button click receipts per case, rendered
125%/100%/80%/100% labels and corresponding canvas dimensions across six cycles.
A second focused trace confirmed the same wrong-target action on fullscreen
entry in a repeated cycle: the click reached the plate-picker area outside the
PDF, not #full. All embedded Fit/fullscreen entry test actions now use the same
scroll-aware helper. The existing fullscreen restoration regression remains
independent and checks host position before its unchanged immediate direct
verified-file download. Screenshot capture returns the host to the page top so
its sticky header does not cover the workspace heading; no image is retouched.

The local diagnostic/test runtime is Chromium 153 with Playwright 1.58; GitHub CI
uses Playwright 1.58's Chromium 145. Both complete suites must pass on the final
source tree. The previously reviewed 7438e023 commit completed push and PR CI with
1,344 passed / 5 skipped and all 46 browser cases passing in each run. Updated
results and exact candidate SHAs are recorded in PR #75.

The intermediate d9c45c37 push passed all 49 browser checks, while its PR run
reported an off-screen SVG scroll-stability timeout and three relative-keyboard
plate-selection setup failures. The already visible/attached SVG is now scrolled
into the capture area using the browser DOM before screenshot stability checks;
its visibility, dimensions, aspect ratio, black pixels and live updates retain
their original assertions. Route-persistence setup now scrolls its input into view after the workspace
screenshot (fill alone left it above the Streamlit viewport), then filters for
the explicit Plate 2 option before keyboard confirmation instead of assuming
relative focus.
The first two keyboard plate-switch checks and all canonical selected-plate,
route-return and logout assertions remain. No drawing-generation or configurator
application source is changed. The latest exact-head runs are required to pass;
intermediate green runs are not substituted for final acceptance.

## Verified production baselines and isolated release boundaries

Read-only Render verification on 2026-11-04 (roguemachine workspace):

| Service | Live commit | Live deploy / rollback target |
| --- | --- | --- |
| API | 6b3c5de962c87f5ef59948c658947cddb1d92a56 | dep-dbl1vqm1egvs739b1d30 |
| Customer UI | f98dee17d610f8e89aafaee302b2fbd11af8dd1d | dep-dbl200u1egvs739b1uig |
| Static landing | 5f7a2d1c817bddca4e27c023fcc35b44b56e275c | dep-dbi8fjgm7kps73c6ff50 |

All three production services have automatic deployment disabled. No service
settings are changed by this preparation. Static landing publish path remains
o-plates landing; preserve its existing journey-config build command.

The landing-only release must be a child of the verified static baseline above,
changing only o-plates landing/index.html (allow=fullscreen) and configurator.js
(the 14-line host position save/restore handler). All six other landing files are
byte-identical between the verified static baseline and A2. The isolated landing candidate is 99c04583a8a37eb378235dbc799e05c04aeb89e2
(branch work/release-a-landing-20261104). The combined customer
release descends from the verified f98 UI baseline through A1 and A2. Its Docker
runtime serves the existing customer application, not the static landing service.
The repository's API/pricing copies are not an API release and must not be deployed
to the API. Final tested commit SHAs belong in the PR handoff, not guessed here.

## Manual deployment runbook — separate owner authorization required

No deployment is authorized by this document. After engineering acceptance and
separate explicit owner authorization:

1. Recheck all three live SHAs against this table. Stop if they have changed;
   reassess the candidates rather than deploying from an outdated baseline.
2. Verify the API at its existing SHA and GET /health. Do not redeploy it, run
   migrations, change checkout mode, or touch workers/staging/manufacturing systems.
3. Static landing service srv-d5eqjn6r433s738u2jn0: Manual Deploy > Deploy a specific
   commit > the accepted landing-only SHA. Preserve build command, publish path,
   domains, headers and configuration. Wait for that exact deploy to become live.
   Verify index.html grants fullscreen only to the existing configurator iframe;
   the served configurator.js includes host scroll restoration. Recheck normal
   embedded navigation, consent/collector behavior and existing configurator fit.
4. Customer UI srv-d530k8re5dus73ahqr0g: Manual Deploy > Deploy a specific commit >
   the accepted combined UI SHA. Preserve Docker/start commands and configuration.
   Wait for that exact deploy to become live; verify /_stcore/health returns ok.
5. Read-only customer acceptance with existing authorized records: OTP persistence;
   desktop 1080 and mobile 390 list/detail/plate/revision switching; visible fit,
   zoom, pan, fullscreen exit returning to the drawing; immediate download with
   authoritative stored byte count and SHA-256; historical gaps; quote/cart return;
   anonymous/cross-owner denial and logout cleanup. Verify TEST-only restrictions
   without checkout, payment attempts, purchases or approvals.
6. Stop on any failure and report. Do not initiate repeated deploys or modify data.

## Manual rollback plan — separate owner authorization required

If the new UI fails, recommend reverting only the UI to f98dee17d610f8e89aafaee302b2fbd11af8dd1d
(deploy dep-dbl200u1egvs739b1uig), then repeat health/auth/privacy checks. The new
landing permission/scroll handler is compatible with the old UI, so leaving the
landing release in place is acceptable when it avoids an unnecessary second change.
If the host itself regresses, recommend reverting landing to 5f7a2d1c817bddca4e27c023fcc35b44b56e275c
(deploy dep-dbi8fjgm7kps73c6ff50). API remains at 6b3c5de9 throughout. Use retained
Render rollback artifacts if available; otherwise manually deploy the exact prior
SHA with unchanged current settings. Recheck automatic deployment remains off.
Rollback does not restore database/order state; this release changes neither and
requires no data rollback. Do not execute any rollback without owner authorization.

PR #52/staging, PR #73/configurator fixes, LIVE checkout, IMP-012, shipments and
reordering remain excluded. No merge, deploy, rollback or production mutation has
been performed by this release preparation.
