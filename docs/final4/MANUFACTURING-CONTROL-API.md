# Final 4 Manufacturing Control handoff — API v1

Implemented as an opt-in router/service factory; no active owner UI files changed.
Production has no automatic import, schema migration, generation or release.

Integration point after reconciliation:

```python
from final4.api import router
# service must use the SAME accepted Frozen Plate repository/private storage.
app.include_router(router(_rate_limit_admin, get_derived_service,
                          server_actor="authenticated-owner-service"))
```

Use the existing server-side admin dependency, never a customer JWT, public API
key or client boolean. Preserve existing rate limits and impose the staging
harness's 64 KiB body cap in the host API. Trusted profiles/configuration load
server-side only. No request supports profile overrides or production release.
A server actor identifies the generation service; independent review requires a
separate authenticated identity/evidence adapter, not a body-supplied username.

| Endpoint | Request | Response |
|---|---|---|
| POST `/admin/manufacturing/bundles` | `family`: HAAS/PACKAGING, `parent`: exact association, optional `reviewed_record` for HAAS | Immutable bundle metadata |
| POST `/admin/manufacturing/bundles/query` | Exact association object | Bundle metadata array for exact revision, including historical audit |
| GET `/admin/manufacturing/bundles/{id}` | No body | Metadata/statuses; verifies parent and metadata integrity |
| GET `/admin/manufacturing/bundles/{id}/files/{name}` | Exact stored file name from metadata | Exact verified bytes with size/hash enforcement; no regeneration |

Association fields (all mandatory, extras forbidden):
`order_id`, `line_id`, `plate_id`, `revision_id`, `spec_sha256`, `source_sha256`.
The SHA fields match the immutable revision columns, not user-supplied recomputed
geometry. `reviewed_record.source_sha256` specifically binds the Frozen **spec**
hash; measured as-cut bore and its uncertainty still require shop review.
HAAS record's order/part/R-number/material/thickness/bore/tolerance/chamfer must
match that spec. Only explicit no-chamfer or supported 45-degree radial chamfer
with reviewed side/orientation is eligible; missing tolerance/edge review holds.

Server returns `id`, `family`, `parent` (plus `revision` label), `generator_version`,
`input_sha256`, `manifest_sha256`, `created_at`, `files[]`, `state`, `statuses`,
`evidence[]`. Each file has `name`, `filename`, `size`, `sha256`.
No object key, storage URL or raw machine profile appears in list/metadata.
An authorized bundle download may contain its machine/setup inputs.

Statuses are separate: `file_exists`, `bytes_verified: ON_DOWNLOAD`,
`parent_current`, `customer_approved`, `engineering_review_completed`,
`simulation_verified`, `physical_validation_completed`,
`manufacturing_release_approved`, `release_eligible`.
The last three remain false in this branch. Successful numerical path checks
are recorded in verification.json and do NOT imply independent machine simulation.
A verified GET returns `X-Artifact-Verified: true`, `X-Artifact-SHA256`,
`Content-Disposition: attachment`, no-store and nosniff. Ordinary metadata reads
do not falsely attest that every derived byte was downloaded/verified.

UI labels to add in the OTHER portal session after merge:

| Existing/new artifact | Label | Action |
|---|---|---|
| Original PDF | Finished-part drawing · PDF | Existing Download PDF |
| Original steel DXF | Rough-blank steel cut file · DXF | Existing Download DXF |
| Original JSON | Frozen specification · JSON | Existing Download JSON |
| Haas guarded program | Haas bore program · REVIEW ONLY | Download review NC / bundle files |
| Packaging | Corrugated packaging · PROTOTYPE | Download packaging DXF / assembly |

Show `Superseded — audit only` when parent_current is false. Never show generic
Ready or automatically change sourcing/release/customer approval from a file GET.
One download click invokes the verified backend GET; a compact Verified message
may describe that response only. Do not offer machine-send or release controls.

Naming:

- Existing steel standard stays `OP-[MATERIAL]-[THICKNESS]-[ORDER]-[LINE]-[REVISION].dxf`.
- New guarded NC: `OP-HAAS-REVIEW-[ORDER]-[LINE]-R[n]-[bundle8]-program.NC`.
- New cardboard: `OP-PACKAGING-PROTOTYPE-[ORDER]-[LINE]-R[n]-[bundle8]-packaging.dxf`.
- Supporting files use the same family/order/line/revision/bundle prefix.
- Offline `candidate.NC` is explicitly PROVE OUT CANDIDATE, separate from review NC;
  not published by HTTP and never classified manufacturing-approved.

Error behavior: host authorization returns 401/403; validation shape/extras 422;
revision/approval/hash/spec/availability failures 409 with a generic message;
request bound 413; unsupported/missing routes 404. Do not display server exceptions,
credentials or storage details. No redirect to a public object-store URL.

## Persistence and compatibility

`final4.service.SCHEMA` defines three additive tables: manufacturing_bundles,
manufacturing_bundle_files, manufacturing_evidence. Bundles/files are append-only;
SQLite test installer adds UPDATE/DELETE rejection triggers. It deliberately
refuses non-local adapters. Bytes publish under unique private `derived/[uuid]`
keys with existing storage hooks and are verified before metadata commit.
Failure can leave unreferenced private objects; no partially committed bundle is
returned. Reconcile orphans by an audited maintenance process, never ordinary GET.

Production PostgreSQL migration is NOT applied. Before production integration,
translate/install these additive tables in the existing private schema, equivalent
immutability triggers, restricted table grants and appropriate RLS policies under
the accepted service-role boundary. Verify with the production/staging adapter and
its existing advisory transaction lock. No production-adapter integration or remote
DB migration is claimed by this branch. Current isolated staging exercises the real
SQLite Frozen Plate engine/private byte verification against synthetic records.

Evidence ingestion is currently a trusted Python adapter method `record_evidence`.
It accepts only exact-manifest independent engineering review and independent
simulation references, in order; self-review, superseded parent, mismatched manifest
and missing verified setup are rejected. It does not accept physical/release gates.
References require an authenticated evidence system and human review before use in
the portal; a typed label by itself proves nothing. New parameters produce another
bundle; gates are not inherited. Machine release remains globally disabled.

Regression coverage: exact parent fields, spec mismatch, unapproved and superseded
parents, concurrent append-only generation, storage length/hash failures, original
revision identity, owner route protection, profile override rejection, synthetic
staging startup/generation/download and absent release routes.

For a chamfered machining request, `reviewed_record.setup_context` must contain
`top_face_side` matching the frozen `chamfer_side` and a nonempty safe-ASCII
`fixture_orientation_reference`. It is included in the input fingerprint and setup
sheet. Missing/contradictory physical face orientation is rejected. Standalone
chamfer review examples without this context stay on SETUP VERIFICATION REQUIRED.
Offline candidate authorization also requires an explicit programmer-verified
`program_number` in 1–8999; protected macro-number range is excluded. Verify slot
availability on the real controller. The old guarded review O09001 is not an
executable program assignment for the shop.
