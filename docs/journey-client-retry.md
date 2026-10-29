# OP-IMP-007 — acknowledgment and bounded client retry

Refs #59. Focused implementation proposal only: no merge, deployment, collection
activation, configuration change, historical reconstruction or checkout change.

## Client repair

Both `journey/frontend/journey.js` and `o-plates landing/journey.js` remain identical.
An observation is marked delivered only after the existing API's HTTP 204 ACK.
In-flight and exhausted observations are reserved separately, so concurrent
rerenders cannot send duplicates or restart a permanent outage loop.

There are at most **two event attempts** per observation per anonymous session.
The retry retains the complete original event body, including UUID and timestamp.
Network/timeout failures, HTTP 429 and HTTP 5xx permit one retry after 250 ms.
Other non-204 responses do not retry. Existing HTTP 410 session recovery remains,
within the same two-event-attempt budget; it is not an additional retry allowance.
Existing server UUID deduplication and admission limits are unchanged. The client
still reserves at most 100 observations; failures consume reservation capacity
but are not recorded as acknowledged delivery. Exhausted observations remain
suppressed until the existing session/consent reset, avoiding rerender retry storms.
The existing 16-item pre-session queue and 1.5-second request timeout are retained.

Withdrawal immediately advances the consent generation, aborts active client
requests and cancels backoff waits. Refusal is saved/shared before waiting for the
delete request, which retains only the previous session token. A subsequent opt-in
does not cancel that previous-session deletion. Embedded parent
withdrawal does the same. Late parent context and internal tagging cannot override
a newer shared refusal or republish an identifier under a privacy restriction.
Every attempt checks consent, shared-cookie refusal, DNT and GPC. While a request
or wait is active, privacy restrictions are checked every 25 ms because browsers
provide no standard GPC/DNT change event. There is no permanent background poll.
Old responses cannot restore identifiers or acknowledge observations after a
privacy restriction or consent/session change. Re-opt-in cannot revive an old
consent generation's retry. Requests already accepted by the server cannot be
unsent; the existing withdrawal endpoint and revoked-session checks remain the
server-side deletion/exclusion mechanism.

No consent default, disclosure version, event schema, identifiers, cookies,
retention policy, rate limit, auth binding or server/storage implementation changes.
No UI placement change is included. Pricing, shipping, checkout mode, orders,
Frozen Plates, approvals and manufacturing artifacts are outside this patch.

## Regression evidence

The existing consent/origin protocol harness is retained. Its response fixture now
models the actual 200 session-start / 204 event acknowledgment contract, and its
VM exposes standard interval timers. It exports its isolated environment for the
new retry tests; no real browser session, account or network is used by that harness.

New cases cover transient failures, the actual request-abort timeout, 429/503,
identical retry UUID/body, concurrent duplicates, exhausted failures/rerender
storms, non-retryable responses, bounded 410 recovery, withdrawal during backoff
and in-flight requests, GPC/DNT/shared-cookie refusal, embedded parent withdrawal,
withdraw/re-opt-in races, a late session response after privacy restriction, and
the existing 100-observation cap. Existing backend tests retain server deduplication,
internal exclusion, reporting windows, retention and durable-storage requirements.
Full CI, browser regressions and all 51 protected manufacturing hashes remain gates.

## Production acceptance — isolated activity, not simulated evidence

Owner authorized one explicitly consented **internal** production test. The current
Work session has no exposed local Chrome browser connector. The first blocked
connection is **Work → owner-designated Chrome session**, before consent selection,
session-start HTTP 200 or landing-event HTTP 204. No cloud browser or direct API
POST is substituted. No production diagnostic session has been created by this work.
This environment limitation does not establish an O-Plates application defect.

Read-only baseline at October 29, 2026, **16:06:00 ET / 20:06:00 UTC**: all five
production journey tables contained zero rows. No qualifying internal test appeared
in the subsequent read-only check. Customer and internal counts were both zero.
Local tests are development evidence, not production browser acceptance.

When browser control is restored, or with owner-performed browser actions:

1. Use a fresh owner-designated private browser context. Do not reuse customer
   cookies. Respect DNT/GPC; if those prohibit diagnostics, stop and record that result.
2. Select **Internal test session before Allow diagnostics** on the real landing
   page. Capture request statuses, not private headers or anonymous session tokens.
3. Verify session start 200 with internal=true and landing event 204, then exactly
   one internal landing session in durable storage and the owner internal-only
   report. Ordinary customer totals must remain unchanged. Use 24-hour reporting.
4. Replay only that new session's original landing event through its browser,
   retaining the original UUID, to verify server deduplication. This must not add
   a second event row or stage reach. Do not invent or replay historical visitors.
5. Withdraw using the new session's control only; verify event/reach/link removal,
   session revocation and the corrected internal aggregate. Existing records and
   operational order data are untouched. Capture the first failing connection if
   any gate fails; do not alter production configuration to force a pass.

The published client remains unchanged until a separately approved release.
Passing a test of the old collector does not prove this new repair is deployed;
conversely, local retry tests do not establish production collection acceptance.

## Isolated release requirements

Development parent is production customer UI `48f6446820ef653c58819606eccd088fde8f3766`.
The deployed landing baseline is `45ee4dc58ac9c2556a1b891c30512fa1eb28fe04`; its
collector bytes match the customer UI baseline. No API, Manufacturing Control,
pricing/shipping release or worker #52 integration is included.

After owner review and separate integration/deployment authorization, prepare
verified exact commits for customer UI and landing independently. Apply only the
reviewed client patch to each service's verified baseline; never deploy a default
branch or the entire customer release to landing indiscriminately. Preserve the
existing production collection flags and build bindings. Run final privacy,
retry, regression, browser and protected-artifact gates. No schema migration or
API deployment is required. Keep staging suspended and LIVE checkout disabled.

## Separate consent-visibility recommendation — not implemented

Move the **one existing** `#journey-consent` control from below the footer to an
inline position immediately above the configurator. Keep the same optional text,
Privacy link and equally accessible Allow/Decline choices. Add no modal, default
opt-in or automatic event collection. Retain access to withdrawal after a choice,
and preserve DNT/GPC, choice expiry and all cookie behavior. Review desktop/mobile
and keyboard visibility before any separately authorized layout change. This
placement proposal is intentionally excluded from the retry patch.
