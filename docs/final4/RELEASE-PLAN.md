# Final integration and controlled cutover

Owner authorization: uploaded Final Integration / Production Cutover instructions, 2026-10-15.

Release branch: `work/final-integration-production-cutover`, from accepted Manufacturing
Control `6fa0d856e544f789128e54739023c458a32336c2`. Traceable merge of Final 4
`f36910693e9d479c2a8a400438c5a12d444633a9`: `f9529017c42ce9babd6b5317765089d8e2c497d7`.
Original branches are not rewritten. `main` remains behind deployed integration history;
this release is deployed explicitly, not by assuming main is the runtime source.

## Rollback targets recorded before changes

| Runtime | Source | Live deploy |
|---|---|---|
| Production API | `4ae0402335dd2f8e75b4d615e373180ca4d28aee` | `dep-db7pi3tg1s2s73bctki0` |
| Production UI | `fa354e5d80175b58b156937cda188bd74d05d49d` | `dep-db7s2i67bikc73ccoil0` |
| Staging API | `6fa0d856e544f789128e54739023c458a32336c2` | `dep-db819bs9v7es73be9f7g` |
| Staging UI | `6fa0d856e544f789128e54739023c458a32336c2` | `dep-db819bs9v7es73be9fkg` |

Production UI/API intentionally differ: UI includes the embedded checkout sender;
API remains on its accepted checkout policy build. The release tree retains both.
Docker commands remain service-specific: API uses uvicorn; UI uses Streamlit.
No landing deployment is required. Existing staging auto-deploy follows the original
Manufacturing Control branch; the separate release branch does not trigger it.

## Additive database changes

`final4.postgres.migration` renders separate allowlisted staging/production SQL files.
Three new private tables only: manufacturing_bundles, manufacturing_bundle_files,
manufacturing_evidence; parent and bundle foreign keys; revision/time index;
SHA-256 format checks; forced RLS; restricted backend SELECT/INSERT policies;
UPDATE/DELETE mutation triggers using the existing reject_frozen_mutation function.
No new login roles, broad grants, original revision updates or stored-object replacement.
The accepted owner archive implementation also adds nullable orders.owner_archived_at
if absent; existing rows remain null and older builds ignore the column.

Application rollback does not drop tables, revoke history or delete derived files.
Disable FINAL4_ENABLED, restore verified API/UI deploys, retain additive schema and
all evidence. This is backward-compatible with recorded rollback sources.

## Backup and recovery

Before production Final 4 migration, create a logical snapshot with `final4.backup`
(or equivalent reviewed inline code in the existing API runtime before deploying).
It retains Frozen Plate rows, original object identities/hashes, orders and catalog
metadata in the existing private bucket; read back exact bytes and record SHA/size.
Verify original object sizes and hashes before migration. Do not print snapshot data.
This is a logical backup, not a claim of independent PITR coverage. Immutable original
objects remain in place. A DBA can restore the snapshot into an isolated empty database,
recreate the recorded schema/ACLs, compare identities and hashes, and select a recovery
connection only after validation. Never restore over live immutable rows.

## Deployment order and gates

1. Run combined local regression and CI.
2. Apply inspected additive staging migration; deploy release API with FINAL4_ENABLED.
3. Run `python -m final4.verify_postgres` inside staging API. It exercises real restricted
   PostgreSQL transactions/concurrent generation, private publication, exact downloads,
   supersession, unchanged original rows and owner HTTP boundaries. No SQLite fallback.
4. Deploy same release UI to staging; inspect browser and authorized owner controls.
5. Record production bindings and verified logical backup. Apply production migration
   only after staging passes. Enable owner-only Final 4 routes, deploy API then UI.
6. Verify health, auth, portal order/revision displays and original/derived download
   integrity. Preserve Stripe modes and payment policy; no test payment by the agent.
7. Stop and hand manual end-to-end checkout acceptance back to the owner.

A failed critical gate stops cutover or triggers application rollback. No production
success claim can be based on synthetic SQLite staging or local tests alone.
