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

## Static host dependency and later deployment order

The existing landing iframe gains ONLY `allow="fullscreen"`. No host width,
navigation, authentication, JavaScript bridge or service configuration is changed.
This permission delegation is required for cross-origin browser fullscreen.

After separate owner release authorization:

1. Verify the running API is healthy at the approved isolated API SHA; no API deploy
   or migration is required for Release A.
2. Compare the one-line landing iframe permission change against the actual running
   landing commit. Prepare a landing-only commit from that verified baseline and
   deploy/verify it before enabling the final customer viewer in the embedded site.
   Do not substitute the customer-based tree for an unverified landing baseline.
3. Deploy the exact accepted A2 customer candidate (which includes A1). Verify
   exact running SHA, desktop/mobile embedded navigation, one current and one
   authorized historical approved PDF hash, logout privacy, quote/cart return and
   TEST-only restrictions. Do not create/approve orders as part of read-only checks.
4. Stop on failure. Do not redeploy repeatedly or change production data/config.

Customer rollback target: `f98dee17d610f8e89aafaee302b2fbd11af8dd1d`. API is unchanged.
Landing rollback target must be the actually verified pre-release static deploy,
not an assumed SHA. The harmless fullscreen delegation may remain with the old UI
if that is the safest rollback; obtain owner authorization for any rollback.
PR #52/staging, PR #73/configurator fixes, LIVE checkout, IMP-012, shipments and
reordering are excluded. No deploy or merge has been performed by this preparation.
