# Phase 4 — Frozen Plate local prototype

The local digital thread works: freeze R1, generate and verify its paired artifacts,
render an email with that exact PDF, approve R1 through one authenticated form POST,
and record three internal sourcing options against R1's exact DXF. R2 preserves R1
and requires independent approval. **264 tests pass: 219 existing + 45 new.**

One production requirement remains unresolved: ordinary email hyperlinks cannot
safely provide a scanner-resistant, one-click approval. The working one-action
prototype is an authenticated local email preview. The exported ordinary MIME
email has a read-only link and cannot approve from a conventional email client.
This is an explicit integration boundary, not a production-ready email solution.

## Baseline and scope

- Branch: `work/deterministic-manufacturing-prototype`.
- HEAD before Phase 4: `443fdbfe6c3dac120e0ba48d70dfbca38af1ec34`.
- The final local commit SHA is supplied in the handoff; `git log -1 --format=%H`
  resolves it without embedding a self-referential hash in this file.
- Accepted Phase 3E generator and production application files are unchanged.
- No push, PR, deployment, real customer email, vendor upload, quote, purchase,
  machine action, production migration, or Stripe/Render mutation occurred.
- No CAD, Fusion or LLM is involved in runtime generation or approval.

Read-only architecture inspection found `Order.id`, `customer_id` and JSON
`quote_payload` in `api_app.py`. A single-line payload stores normalized inputs;
a cart stores `cart_items`, each directly containing normalized inputs. The pure
adapter supports both. The current model has no normalized order-line table and
does not persist the optional single-checkout configuration ID. Consequently this
prototype uses explicit `L1` / configuration fixture identifiers. A production
adapter must establish stable line/configuration IDs and read authenticated,
server-owned order snapshots. No live order was read or imported here.

The connected **O-Plates Staging** project was inspected for public table metadata;
it returned no public tables. Nothing was created remotely. SQLite exercises the
local transaction model; Postgres and private Supabase Storage are the proposed
integration targets. The application already uses constant-time `x-api-key` admin
authorization and verified Supabase JWT customer subjects. This isolated app
mirrors the admin check with a separate prototype key and substitutes explicit,
signed local fixture sessions for customer JWT authentication. It never imports
`api_app.py`, avoiding its production database/provider initialization.

## Architecture and data model

`Repository.create_revision()` consumes the accepted `PlateSpec` and calls
`build_plate_geometry()` / `generate_package()`. The same canonical geometry drives
both files. `validation.py` reopens the DXF, checks units, entities, closure,
canonical vertices and the rough-bore rule, and requires zero audit errors/fixes.
It checks the JSON against the canonical record and parses the PDF to verify the
finished-bore callout, drawing identity, revision and confirmation state. Existing
generator tests continue to validate the complete drawing/geometry behavior.

| Record | Purpose and principal constraints |
|---|---|
| `frozen_plates` | Stable order/line/configuration/customer identity; unique order + line; current revision must belong to this plate; mutable lifecycle only. |
| `frozen_plate_revisions` | Immutable exact spec JSON, SHA-256, source snapshot/hash, drawing metadata, schema/generator/geometry versions, reason, actor and timestamp; unique plate + revision number. |
| `frozen_plate_artifacts` | Immutable PDF/DXF/JSON identity, private object key, paired filename, byte size/hash and generation metadata; unique revision + type. |
| `frozen_plate_tokens` | Signed-token fingerprint bound to exact revision/PDF/spec hashes and intended customer/order, creation and expiration. No raw token. |
| `frozen_plate_revocations` | Append-only explicit revocation, reason, actor and time. |
| `frozen_plate_deliveries` | Exact revision/PDF/token reference, recipient identity, template version, MIME hash and generation time. State is only `LOCAL_RENDERED`; sent time must be null. |
| `frozen_plate_approvals` | One authoritative approval per revision, exact PDF/token/spec hashes, customer/order, approval time and transition audit. |
| `frozen_plate_sourcing` | Approved revision + exact DXF, route and selection metadata; quote/reference/price/currency/lead-time fields reserved; no submission or actual release. |

Composite foreign keys prevent tokens/approvals/deliveries from attaching a PDF
from another revision. Sourcing must reference a DXF of its own approved revision.
Database triggers reject changes/deletions to frozen history, including approvals,
artifacts and routing selections. Plate identity cannot change. Routing records
are review selections, not mutually exclusive production awards. Three options
can coexist. Future quote/award/release updates need controlled append-only events;
this phase intentionally exposes no generic mutation endpoint.

`schema/sqlite.sql` is the tested local schema; the repository adds immutable-row
triggers at initialization. `schema/postgres_proposal.sql` is an **unapplied,
unexecuted Supabase staging proposal**, isolated under `frozen_plate_prototype`.
It includes the equivalent constraints/triggers, RLS on every table, and no access
for `anon` / `authenticated` / `PUBLIC`. It changes no existing tables, buckets,
roles or orders. There is no historical backfill. Before applying anything, review
it as a migration, establish the backend role/policies and order foreign keys, and
implement/test a Postgres adapter using a plate-row `SELECT ... FOR UPDATE` lock.
Do not connect the local SQLite service to production.

## Private objects, freeze and hashes

Private development layout:

- `.frozen-plate-local/frozen-plate.sqlite3`
- `.frozen-plate-local/objects/<plate UUID>/<revision UUID>/OP-PROTOTYPE-001-L1-R1.pdf`
- The same directory and filename stem for `.dxf` and `.json`.
- Local keys, fixture cookies and MIME emails also stay in this ignored directory.

Repository directories are owner-only; artifact files are written read-only.
No object directory is mounted as a web static directory. Customer attachment
access can return only the token-bound PDF after customer authentication. There
is no customer DXF endpoint. A future private bucket should retain this structure,
refuse object overwrites, and expose PDF access through an authorized backend or
short-lived, narrowly scoped access. No permanent public object URL is used.

Canonical spec serialization sorts keys, fixes separators, uses ASCII and rejects
non-finite JSON numbers. SHA-256 identifies the exact canonical spec, source
snapshot and every artifact. Drawing metadata is also frozen and included in the
hashed internal JSON. Artifact timestamps/UUIDs are audit metadata, not inputs to
the deterministic generator. Identical spec + drawing metadata in fresh repositories
produces identical artifact hashes, as tested. Integer/float JSON representations
are preserved as supplied; semantic deduplication is not claimed.

Creation holds a `BEGIN IMMEDIATE` transaction and requires `expected_current`.
It generates into a private temporary directory, validates all outputs, atomically
renames to a fresh revision directory, fsyncs files/directories, inserts metadata,
and advances the current pointer in one commit. Failure rolls back and removes
unreferenced output; an interruption after commit preserves referenced files.
A process crash before commit can leave an unreferenced directory, never a valid
approvable revision. Future storage operations need an orphan-reconciliation job;
none automatically deletes history here. Backups must preserve both DB and objects.

Approval, delivery and sourcing reread **all three actual artifact files** and
verify their lengths and hashes, plus frozen spec/source hashes. Missing or altered
bytes block the operation. These controls detect storage drift; they do not make
a compromised database owner/storage administrator cryptographically incapable
of rewriting history. Signed, off-system audit anchors would be a separate policy.

## Token, approval and lifecycle

The dedicated HMAC-SHA-256 token uses an `itsdangerous` purpose salt and a random
256-bit nonce. It contains no customer/order information. Its SHA-256 fingerprint
looks up an immutable server-side binding to the revision, PDF ID/hash, spec hash,
customer and order. Raw tokens and signing keys are excluded from audit data,
committed artifacts and rendered review exports. Local MIME fixtures necessarily
contain the delivery token; they are ignored by Git and private.

The prototype token lifetime is **30 days**, configurable at repository creation.
Expiration and explicit revocation fail closed. Re-delivery can issue a new token;
replacement does not implicitly revoke the old one unless requested. A new current
revision logically supersedes every pending old token, without rewriting token
history. An already-approved old revision returns its original success record
while the token is valid, with a note that the newer revision needs approval.
Expired/revoked tokens cannot read historical success; authenticated order history
would be the long-term production access route.

| Event | Result |
|---|---|
| Create plate | `EMPTY` |
| Successfully freeze a revision | `READY_FOR_CUSTOMER_CONFIRMATION` |
| Render local email | Delivery row only; no false “sent” status |
| Approve current exact revision | Atomic approval row + `CUSTOMER_APPROVED` |
| Record internal source option | `READY_FOR_RELEASE`; actual release remains false |
| Create R2 | Current pointer moves to R2; plate returns to confirmation pending |
| Old unapproved token | Friendly superseded response; never approves R2 |
| Old approved token | Historical success only; cannot change R2 or source old DXF |
| Repeated approval/source request | Returns existing authoritative record |

Superseded status is derived from the current pointer; immutable revision rows are
not updated. A serialized transaction decides approval versus supersession: either
R1 approval wins first and is retained historically, or R2 wins and R1 is rejected.
Unique constraints and the expected-current check resolve duplicate creation and
clicks. The failure test injects an error between approval insert and plate-state
update and proves both roll back. Postgres locking remains a Phase 5 validation.

## Customer email and one-action safety

The exact controlled sentence is:

> By clicking below, you confirm that you have reviewed the attached drawing and approve the dimensions, material, quantity, and configured options shown for manufacture.

The next control reads **VERIFY & APPROVE ATTACHED DRAWING**.

The MIME email has one attachment: the exact frozen PDF, whose bytes are checked
against its stored hash. It contains no DXF attachment or customer DXF link. The
recipient is the reserved test address `prototype-customer@example.invalid`; the
delivery row identifies the fixture customer. It is never sent.

In `/local-email/<token>`, the customer is already authenticated through a fixture
session established separately by the harness. The button submits one form POST.
The server checks the session customer, signed approval token, same-origin header,
CSRF value and current immutable binding. Success uses a 303 redirect to a read-only
page headed **YOUR ORDER IS IN PRODUCTION**, displaying order, line, drawing,
revision, quantity and approval date. There is no second approval button. This
customer phrase does not initiate physical production or vendor submission.

GET/HEAD requests never approve or consume the token. Visiting a token cannot
create an authenticated session. There is no auto-submit JavaScript, GET-to-POST
bridge, user-agent scanner guess, click-tracking assumption or “human” heuristic.
Responses are no-store, no-referrer and non-frameable. The CLI binds only loopback,
disables token-bearing access logs, and does not load production secrets.

**Email limitation:** an ordinary hyperlink issues GET, and a scanner can issue
the same request. A literal one-click state change from conventional email is not
established by this prototype. Its MIME button goes to a read-only status page;
pending status explains that the client cannot securely submit approval. No extra
approval button is added there. Production needs either an authenticated actionable
email mechanism verified for the supported clients, or an owner-approved change to
the interaction. Merely adding automatic browser POST would not solve it.

The local cookie fixture is a test substitute, not a production login system.
Production must reuse verified Supabase identity, secure HttpOnly/SameSite cookies
or an equivalent authenticated transport, HTTPS, credential rotation, rate limiting,
access-log redaction and independent authorization review. A customer approval
token alone cannot access internal endpoints. Internal controls require the separate
admin key, checked with the application's existing constant-time header pattern.
No admin key is embedded in a customer page or approval token.

## Internal rough-blank sourcing

`SOURCE ROUGH BLANK` presents `SENDCUTSEND`, `ALRO`, and `ROGUE_INTERNAL`.
The authenticated form/API records `LOCAL_SELECTION_ONLY`, the exact approved
revision DXF ID, actor and timestamp. It returns a traceability envelope containing
plate/revision, spec hash, companion PDF ID/hash, approval time and DXF hash.
It accepts no caller-supplied DXF ID or object key. The service verifies current
approval and files again; selecting a route never regenerates geometry.

All three paths were demonstrated with the same R1 DXF identity. SendCutSend and
Alro have reserved reference, price, currency, lead-time and quote-state fields,
without any assumption about vendor APIs. Rogue Internal remains `NOT_RELEASED`;
there is no machine integration. `submitted_at` must stay null. Selected/rejected
review status is represented; production award/release is not enabled. R1's old
selections remain audit history after R2, but no new R1 sourcing action is accepted.

## Evidence and outputs

`prototype_output/phase4/acceptance-manifest.json` records R1/R2 identities, specs,
versions, hashes, the exact R1 approval and all three sourcing options. R2 changes
quantity from 1 to 2. Both artifacts are regenerated: the PDF and spec hashes change;
the **DXF hash correctly stays identical**, because quantity does not alter cut
geometry. The distinct R2 artifact ID, directory and filename preserve revision
provenance. A separate test changes the bore and verifies different DXF bytes.

The R1 DXF SHA-256 still matches the owner-verified accepted blank:

`704abfa62d0bef0b3ac91d97a58bc0dfa7f093418d87f12ae3763d12118ecfb8`

| Export | Purpose |
|---|---|
| `OP-PROTOTYPE-001-L1-R1.pdf/.dxf/.json` | Accepted sample, exact R1 package |
| `OP-PROTOTYPE-001-L1-R2.pdf/.dxf/.json` | Quantity-two revision, independently pending |
| `customer-email-preview.html/.png` | Inert review of email/one-action preview |
| `customer-success.html/.png` | Exact R1 success-page content |
| `internal-sourcing-preview.html/.png` | Internal source control concept |
| `superseded-link.html/.png` | Customer-friendly supersession page |
| `acceptance-manifest.json` | Complete non-secret local evidence |

The PNGs are **static WeasyPrint HTML renders**, visually reviewed, not browser
screenshots or proof of email-client compatibility. Chromium was unavailable and
its download failed. The HTML form POST/redirect/auth flow was exercised using
FastAPI's local test client. Both PDF revisions were rasterized and visually checked;
the accepted drawing layout, dimensions and HOLDs were not redesigned.

Full command: `.venv/bin/python -m pytest -q` → **264 passed, 2 warnings**.
The two warnings predate Phase 4: Starlette/httpx test-client deprecation and
AnyIO BlockingPortal alias deprecation. The 45 new tests cover freeze/hashes,
determinism, immutable history, generation/validation/DB failures, rollback,
exact-PDF MIME delivery, tampered/expired/revoked/wrong-customer tokens, current vs
historical approval, altered/missing files, cross-revision FKs, cross-plate isolation,
CSRF/origin/session checks, passive GET/HEAD, internal authorization, all routes,
duplicate approval/revision/sourcing races, supersession conflict and order adapters.

## Files and reproduction

Added `frozen_plate/`: `repository.py`, `validation.py`, `order_adapter.py`,
`presentation.py`, `web.py`, `demo.py`, `render_previews.py`, `__init__.py`, and
`schema/{sqlite.sql,postgres_proposal.sql}`. Added `tests/test_frozen_plate.py`,
`requirements-frozen-plate.txt`, `requirements-frozen-plate-review.txt`, this report,
and Phase 4 review exports. `.gitignore` now excludes `.frozen-plate-local/`.
Production requirements, services, configs, pricing, checkout and generator code
were not modified.

```bash
.venv/bin/pip install -r requirements-frozen-plate.txt
.venv/bin/python -m pytest -q
# Choose a fresh private directory; demo refuses to overwrite one.
.venv/bin/python -m frozen_plate.demo --root .frozen-plate-local
# Optional loopback app, no email delivery:
.venv/bin/python -m frozen_plate.demo --serve --root .frozen-plate-local
# Optional static review renders (also needs Poppler pdftoppm):
.venv/bin/pip install -r requirements-frozen-plate-review.txt
.venv/bin/python -m frozen_plate.render_previews
```

The existing local fixture has already been created. To rerun, choose a fresh path
under the ignored `.frozen-plate-local/` directory, e.g. `--root .frozen-plate-local/run2`.
The loopback web app has no public login route. An authenticated test harness injects
the private fixture session cookie; do not publish these files or reuse these keys.
Static exports intentionally have inert buttons. `pypdf` is an isolated validation
dependency; WeasyPrint is optional review tooling, never a manufacturing generator.

## Owner decisions and recommended Phase 5 boundary

1. Choose supported customer email clients and a verified authenticated actionable
   email path, or approve a revised interaction. This is the material blocker to
   claiming ordinary-email one-click production readiness.
2. Confirm the 30-day expiry, re-delivery/revocation policy, forwarded-email signer
   authority, approval retention and post-approval amendment process.
3. Set final order/line/part numbering, stable configuration identity and real
   sender/reply-to contacts. Prototype `L1` and `.invalid` addresses are not defaults.
4. Decide who may award a source and release work, and how quote/rejection/release
   events are recorded. Confirm the customer “in production” phrase while work is
   only eligible for controlled release.
5. Define production release prerequisites for unresolved drawing requirements.
   Phase 3E's accepted HOLDs remain; this approval demonstration is not permission
   to manufacture an unresolved print. No metering rules are introduced here.

Phase 5 should remain staging-only: implement/test the Postgres/private-bucket
adapter, authenticated order import with stable line IDs, Supabase customer sessions,
selected email-client proof, role-based release review, backup/restore and orphan
reconciliation. Keep vendor transmissions, purchases and machine actions disabled
until the exact approved revision, permission checks and release prerequisites are
independently verified. Revisions/artifacts must remain immutable through release;
any changed drawing bytes need a new controlled artifact/revision and appropriate
approval, never an overwrite or silent watermark change.

Narrow reference checks:
[Supabase private buckets](https://supabase.com/docs/guides/storage/buckets/fundamentals)
confirm private access through authorization/RLS or bounded signed access;
[Supabase email prefetching](https://supabase.com/docs/guides/auth/auth-email-templates#email-prefetching)
documents security scanners fetching email links. No vendor API research or live
integration was performed.
