# My Orders Release A — engineering review

Owner-approved design: O-Plates-My-Orders-Design-Review.pdf (13 pages), Library
`libfile_00dc32ba0eb88191995ec4dea2337f61`. Issue #65. Implementation authorization
is separate from production release authorization; no merge or deployment is implied.

## A1: navigation and selected-plate workspace

Base: customer release `f98dee17d610f8e89aafaee302b2fbd11af8dd1d`.
API compatibility baseline: `6b3c5de962c87f5ef59948c658947cddb1d92a56`.
No API/schema change. PR #73, PR #52 and new configurator fixes are excluded.

History uses the existing owner-scoped search/sort/pagination endpoint. Selected
orders add a compact rail, one plate picker and a drawing-first workspace. Original
purchased specifications, order amounts, shipping and explicit unavailable document
states follow below. Native Streamlit controls retain keyboard semantics.
The rail uses scoped container queries; below 900 px of workspace width it is hidden
and the selected order fills the width with Back to Orders. History filters,
selected plate and approved revision have ordinary canonical session snapshots so
conditional widget removal on route changes does not discard navigation state.
All IDs are validated against the newly retrieved authorized inventory before reuse.

Private My Orders state is removed on logout, failed authorization and account
change. This is UI cleanup; all authorization remains in the API. No response or PDF
byte cache is introduced. Pending approval remains a deliberate token-bound action,
separate from the approved archive. No pending revision is labeled approved.

## Design fit and deviations

The approved 918 px desktop allocation is 200 + 18 + 700. Existing Streamlit padding
and the actual embedded document determine available width; the rail/workspace
ratio scales above the breakpoint. A native accessible plate picker replaces the
mockup's plate tabs, avoiding cramped labels on narrow screens. Below the drawing,
expanders replace eagerly evaluated tabs. No host widening, new portal, PO data,
tracking infrastructure, certificate backend, invented line prices or reorder UI.
The existing auth, site navigation and TEST warnings remain visible.

## Acceptance

Browser tests exercise 320, 375, 390, 768 and 1080 px, both standalone and in the
repository's actual landing HTML/CSS/layout bridge. Only origins/URLs are redirected
to isolated loopback fixtures. No real OTP, Supabase, Stripe or order writes occur.
The plate picker is exercised by keyboard, verifying the resulting plate heading,
historical missing-state context and the correct drawing/download after switching
back. Browser artifacts include synthetic desktop/mobile screenshots.

App tests cover filters, multi-plate separation, Unicode input, missing historical
fields, service failures, forbidden-read cleanup, artifact mismatch and TEST wording.
Existing real repository/API tests verify ownership before storage, approved versus
unapproved/superseded revisions and exact PDF/hash/size bindings.

A1 deliberately retains the existing PDF renderer. A2 separately replaces approved
PDF media/download delivery, adds full-screen/zoom/pan and verifies browser URL
privacy. Review A1 independently; release the combined customer candidate only after
A2 acceptance. Existing pending-approval document delivery is not changed in A1.

## Release and rollback preparation

Do not deploy from a customer branch to the API service. The API stays at its verified
baseline; validate its health and exact running SHA before any owner-authorized UI
release. A1 then A2 are the review order. The final A2 tree is the combined UI
candidate; preserve a separate static landing change if iframe fullscreen delegation
is needed. Verify exact deployment commits, owner-only reads, approved drawing bytes,
TEST restrictions and quote/cart return behavior after any later authorized release.
Rollback UI target: `f98dee17d610f8e89aafaee302b2fbd11af8dd1d`; API is unchanged.
Never roll back data or regenerate historical artifacts. Staging stays suspended.
