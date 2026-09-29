# Manufacturing / Frozen Plate publication review

## Source and scope

Accepted local source: `work/deterministic-manufacturing-prototype`, clean HEAD
`8bc2559606f0e65c4d0d46392671a128ad233f98`. Publication base:
`9b648d93486a925d8b8ecab063b16e98d5cda4f6` (current main, including the four approved
landing-page commits after PR #8). Those landing-page files are unchanged by this PR.

Publication branch: `work/frozen-plate-manufacturing`. It imports the accepted final
source snapshot onto current main. The original local branch retains full Phase 3/4
history. This avoids publishing obsolete intermediate packages and reference
comparison imagery through earlier commits. No shared history was rewritten.
The PR is intended for an ordinary merge commit, consistent with PRs #7 and #8.

| Group | Included changes |
|---|---|
| Geometry / DXF | Canonical `plate_geometry.py`, deterministic exporters, rough-bore diameter allowance, R0.03125 profile, configurable section geometry. |
| Drawing | Accepted `op-drawing-v3e` PDF renderer and drawing/application state definitions; no datum/GD&T additions. |
| Frozen Plate | Immutable local repository, pure order adapter, exact artifacts/hashes and validation. |
| Approval | Signed exact-revision binding, authenticated local POST preview, supersession, idempotency, private PDF access. |
| Sourcing | Internal SendCutSend/Alro/Rogue Internal review selections bound to approved-revision DXF; no transmission. |
| Schema | Tested local SQLite schema and unapplied isolated Postgres proposal. |
| Tests | 162 manufacturing/Frozen Plate tests added to the existing 102-test application suite; current golden checksum retained. |
| Documentation / evidence | Architecture and phase decisions, curated accepted sample/chamfer and R1/R2 audit packages, two customer previews, historical golden PDF/checksum. |
| Dependencies / CI | Isolated pinned manufacturing and Frozen Plate dependency files; test workflow installs the complete prototype dependency set. Production requirements unchanged. |

Only publication corrections to the accepted snapshot: wire the Frozen Plate
requirements into CI, include manufacturing requirements transitively from that
file, curate generated artifacts, ignore disposable new exports, and document the
publication/handoff. No generator, approval, sourcing or production behavior changed.

## Review results

- Secret/sensitive-data review: no provider credentials, private keys, JWTs,
  credential-bearing URLs, real customer addresses or private database/email/key
  files found in candidate text/PDF content. The two retained PNG previews contain
  only the synthetic prototype. Test credentials are obvious fixtures. Runtime
  tokens, local keys, database and MIME emails remain ignored and unpublished.
- Live mutation review: production entry points/configuration are unchanged and
  do not import the new prototype. No sending/submission client is introduced.
  No Frozen Plate production migration runs on import/startup. Existing production
  application behavior is not activated or changed by this branch.
- Render read-only check: all seven main-tracking production services have
  auto-deploy off. Staging auto-deploy services track other branches; PR previews
  are off. No Render settings were changed and no deployment was requested.
- Schema review: proposal creates only its dedicated schema/tables, uses explicit
  transaction execution, includes immutable-row triggers and composite revision/
  artifact foreign keys, enables RLS and denies anonymous/customer role access.
  No drops, deletion or backfill. Existing PK/unique indexes support implemented
  ID, plate/revision, revision/type and revision/route lookups. Staging migration,
  backend grants, PostgreSQL locking and future history-list indexes remain Phase 5
  integration work. No database migration was applied or syntax execution claimed.
- Approval review: exact PDF/spec hashes recorded, stale R1 cannot approve R2,
  repeated approval is idempotent, bad tokens fail, GET/HEAD never approve,
  customer authority grants no internal sourcing rights, no automatic release.
- Generator review: accepted code and golden checksum are unchanged. Canonical
  sample retains finished 5.000 OD / 1.548 bore / 2.000 handle / 10.500 centerline
  dimension; 1.423 rough bore, 0.125 diametral allowance, 0.0625 radial stock;
  explicit inch units and exactly two closed cut profiles. DXF has no drawing
  annotations; the normal package has PDF/DXF/JSON and no SVG.
- Local verification: **264 passed, 0 failed, 2 existing deprecation warnings**.
  Existing suite 102; manufacturing tests 117; Frozen Plate tests 45. Tracked Python
  sources compile successfully. No formatter/linter is configured; no new
  quality toolchain was introduced. Golden regression test passes.
- Publication blocker fixed: CI previously omitted `pypdf`, and the Frozen Plate
  requirements file omitted the manufacturing dependencies needed by its imports.
  Both are corrected without changing production dependency pins.
- Remaining non-blocking limitations: ordinary-email one-click approval is not
  production-ready; Postgres/storage/auth/email adapters remain prototypes;
  accepted unresolved drawing requirements still prevent manufacturing release.

CI and the actual GitHub PR diff must be green/clean before merge. The final PR,
pushed SHA, CI result, merge SHA and main verification are recorded in the task
handoff after GitHub completes those operations, rather than predicting results here.

## Phase 5 handoff — staging integration and end-to-end order acceptance

Main will contain the deterministic finished PDF and rough DXF generators, immutable
Frozen Plate specification/revision/artifact services, exact approval architecture,
three-route sourcing state and regression tests. This publication does not connect
these modules to checkout, production orders, mail providers or vendors.

Next authorized phase must:

1. Review/apply staging-only Postgres schema and private object-storage policies;
   implement and test the storage/transaction adapter and recovery behavior.
2. Bind server-owned staging order/configuration snapshots to stable order-line
   identities and Frozen Plate creation, using existing verified customer auth.
3. Connect staging-only email delivery and prove the exact PDF attachment binding.
   Decide and test the supported safe one-action email interaction; never approve
   via passive GET or an automatic GET-to-POST bridge.
4. Connect authenticated approval to the existing customer success-page design and
   expose only the approved revision's DXF through internal sourcing controls.
5. Run staged test orders, amendments, repeated clicks, tamper/failure cases and
   authorization checks. Resolve release prerequisites for unresolved requirements.

No real vendor submissions, machine actions or production cutover. Phase 5 requires
its own explicit authorization. Do not treat “merged” as “integrated” or “deployed.”
