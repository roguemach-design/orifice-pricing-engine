# Lead-time selection repair — production UI port

Prepared November 5, 2026 for owner review. No merge or deployment authorization.

## Identity and recovered evidence

Exact UI parent / rollback: `604c2e496c49f05b6f7c7f64449774c9a6f2fc8a`.
Production API stays `c0527a69fa606ba5181f80f0b7e3478e85d36e30`.
This ports PR #73 (`c43d9756f449323da19c05ab841a468007145dc7`), without
its obsolete release/boundary document or older Release A files.

PR #73 already reproduced an accepted new selection being overwritten by an
older response on desktop and embedded mobile. Its local browser gate passed,
but exact-head CI had a drawing assertion failure and a Chromium fork failure;
the passing parallel PR run did not clear that blocked release. Those are
historical results, not acceptance of this successor.

## Root cause and correction

`choice_buttons()` assigned the current session value on every rerun. In pinned
Streamlit 1.64.0, even an unchanged assignment emits `set_value=true`, allowing
an older response to replace a newer genuine browser selection. Write only
for initialization, recovery or invalidation. Keep current valid edits ahead
of committed snapshots, explicit False/None, session persistence and availability
validation.

Conditional chamfer children also shifted the following delivery block's render
path. A stable `chamfer_details` container prevents that positional remount.
Only `customer_controls.py` and `pages/1_Quote.py` change product behavior.
No drawing, pricing, cart, authentication, API, checkout, manufacturing or
My Orders Release A implementation changes.

## Acceptance scope

Reuse the ordered websocket barrier from PR #73: hold the earlier chamfer
response, capture a genuine newer lead-time click/request, deliver the older
response, require the selection to survive, then release the request and assert
the actual quote payload. Both 14-to-21 and 21-to-14 directions, chamfer off/on,
desktop and embedded mobile, before/after OTP and My Orders/Cart/Configure
navigation are covered (48 controlled transitions).

Keep current Release A browser fixtures, including PDF and bridge coverage.
Add the recovered rapid test to the existing complete browser CI command.
No assertion weakening, delay-based customer workaround or retry is introduced.
Focused gates run first. One complete exact-head CI cycle follows; any failed
focused gate or complete CI cycle blocks release and ends this repair attempt.
Final counts and workflow evidence belong in the PR description so reporting
does not change the tested source head.

Protected-output verification uses the existing 51-hash synthetic regression;
no production artifact generation, download or record changes are permitted.

## Separate deployment decision

If accepted, deploy only the final reviewed candidate SHA to the Customer UI.
Keep API c0527a69, Manufacturing Control, landing and all environment settings
unchanged. Confirm the production UI baseline still equals 604c2e49 before
deployment; otherwise stop and reassess. Keep TEST-only checkout and automatic
workers disabled. Validate representative rapid selections and displayed quote
lead time without purchasing or invoking manufacturing.

Rollback is Customer UI commit
`604c2e496c49f05b6f7c7f64449774c9a6f2fc8a` only: it restores the known lead-time
defect but does not change the contained API. Never roll back the API as part of
this UI repair. Merge/deployment needs a separate owner decision.
