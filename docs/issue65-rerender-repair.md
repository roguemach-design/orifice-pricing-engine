# Issue 65: required-control rerender repair

Review-only UI successor to `f98dee17d610f8e89aafaee302b2fbd11af8dd1d`.
The API remains `6b3c5de962c87f5ef59948c658947cddb1d92a56`.
No production deployment, configuration, migration, order, approval or artifact change is included.

## Causal trace

The shared `choice_buttons()` helper wrote its current value back to
`st.session_state[key]` on every run. In pinned Streamlit 1.64.0 that marks
the value as a new server-side assignment; button-group registration emits
`set_value=true` with the serialized old value. The frontend's
`useBasicWidgetState` applies that incoming value with `fromUser=false`.

A customer can select 21 days while an earlier No Chamfer rerun still carries
14 days. The older server update then replaces the newer browser selection.
The committed snapshot still legitimately held 14 until the newer request
was processed: this is a stale server-to-browser overwrite, not disappearance
of the persisted canonical snapshot or an OTP failure.

Conditional chamfer fields also moved the delivery block's delta path
(for example index 28 to 25) while the widget ID stayed unchanged. During the
transition Chromium exposed old and new instances. A fixed parent for chamfer
details prevents this positional remount of the delivery controls.

The regression uses ordered websocket barriers, not sleeps between clicks:

1. Buffer the earlier chamfer rerun's response without reordering messages.
2. Make a genuine new lead-time pointer click; record its DOM event and
   browser request containing the new value, holding that request briefly.
3. Deliver the older response. Assert that the newer visible selection survives.
4. Release the queued request. Assert the actual `/quote` payload, metrics,
   required selection, conditional field visibility and absence of exceptions.

The deployed baseline fails step 3 for standalone desktop and embedded mobile.
The candidate passes both directions, chamfer on/off, before authentication,
after one OTP and after My Orders/Cart/Configure navigation: four cycles per
phase, 24 controlled transitions per surface (48 total).

Artifacts contain DOM pointer/mount/unmount events, widget IDs/delta paths and
set-value flags, synthetic server values and committed snapshots, quote
payloads, and final screenshots. Diagnostics are confined to loopback tests;
no customer telemetry or product-side instrumentation is added.

An additional ungated mobile diagnostic caught a different event: pointerdown
on a card followed by pointerup outside it when focusing a tall iframe scrolls
the parent. No choice request was emitted. The controlled test focuses the
target before the pointer click and verifies that the new request exists, so
it measures loss of an accepted edit rather than conflating a missed press
with a server state change. It still fails on the original product code.

## Repair and preserved semantics

- Only initialize, recover or invalidate a required widget's value when a write
  is needed. Do not force unchanged values back onto the browser every run.
- Keep native `persist_state="session"`, committed-snapshot recovery and
  missing-key form restoration. A real remount still receives its saved value.
- Preserve explicit `False`, unresolved `None`, availability checks and current
  valid edits over older snapshots. No artificial customer click delay is added.
- Keep chamfer detail children in one stable parent. Field values, validation,
  quote/checkout payload construction and engineering geometry are unchanged.
- Authentication, pricing, shipping, handle-hole calculations, order ownership,
  stored PDF hashing and Phase 2 design-only scope are unchanged.

The previous unit tests demanding `set_value` on every unchanged rerun now
assert the absence of that stale overwrite. The lead-time recovery test now
actually hides and remounts the widget and still requires a restored value and
`set_value=true`; unresolved/invalid/False recovery assertions remain.

## Separate read-only boundary findings, November 3, 2026

- PR #52 head `ca9862d0bdd705f6fd8443ab1381d117f2be00d8` is not an ancestor of
  the running API. Its retry-control migration and worker correction are not
  part of this UI change.
- Render staging API `srv-d9ritcijobas73didpbg`, staging UI
  `srv-d9rj427avr4c739dufkg` and staging DB `dpg-d9qte9ad0e5s73b35qng-a`
  are suspended. The staging API cannot currently run its old worker.
- The static staging landing `srv-daolp8egekts73aom9ng` is active. Its public
  HTML embeds the staging UI, not production. A static site cannot start the
  Python engineering worker. This differs from a literal all-staging-suspended
  requirement but is not evidence of a production manufacturing action.
- Production API's Render environment shows `FINAL4_ENABLED=true`. In the exact
  deployed code this registers owner manufacturing routes, creates the older
  staging worker and starts it in the application lifespan. There is no separate
  automatic-staging switch in this deployed revision. Thus an assertion that
  every production worker is disabled would be false. This predates the My
  Orders delta; it must be reconciled separately by the owner.
- A metadata-only query matching that worker's parent discovery found six
  current approved parents: four excluded owner-TEST records and two eligible
  historical parents. Six manufacturing bundles existed, newest October 29,
  13:37:11 UTC; zero bundles were added after the November 3 release. No
  automatic/derivative messages appeared in the inspected API logs. This does
  not prove zero storage reads or certify runtime inactivity.

No worker, staging, checkout or production setting was modified. The UI repair
does not resolve the independent worker-boundary question.

## Release gate

Run the full suite and all browser gates against the exact successor commit,
including `tests/browser_rapid.py` and the 51 protected-output hash assertion.
Keep the API release separate. Require owner authorization before deployment
and repeat read-only production acceptance afterward. Retain TEST-only checkout.
