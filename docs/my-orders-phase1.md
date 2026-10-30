# OP-IMP-013 — My Orders Phase 1

Refs #65. Development/PR only; no merge, deploy, migrations, production writes,
checkout changes or staging recovery. Reorder is design-only in the separate
`my-orders-phase2-design.md`.

## Baselines and exact release dependencies

Read-only Render inventory October 30, 2026:

| Component | Running SHA | Deployment |
|---|---|---|
| Customer UI | `edee47e53ee35f47f3b4c52ccec96b279c752df5` | `dep-dbi8fafb9u1s73ddiikg` |
| API | `3ccc851d7674368a9a056b1fa417a10da7983dea` | `dep-dbi83eoae00c73bg2gng` |

This PR is based on the **customer UI** baseline. It must **never be deployed as
an entire API image**: that would lose the shipping/handle-hole recovery again.
Before an owner-approved release, integrate only these backend paths onto the
exact API baseline (or its independently verified successor): `api_app.py`
(the additive history endpoints and router callback), `customer_order_history.py`,
`frozen_plate/api.py`, `frozen_plate/customer_archive.py`. Preserve the existing
shipping and pricing model version line in the API baseline. Test that isolated
API integration before issuing an exact release SHA. Deploy API first, then the
customer UI. Manufacturing Control, landing and obsolete standalone `my-orders`
need no deployment. No #52, #41/#42 or quality-document implementation is included.

## Verified causes and existing infrastructure

Canonical route: `/My_Orders`, implemented by `pages/2_My_Orders.py` within the
existing Streamlit navigation. The legacy `my_orders_app.py`/`customer_portal.py`
redirectors remain unchanged. The old page uses an order table plus a separate
selection dropdown and a maximum of 200 records. Existing `/me/orders` and
`/me/orders/{id}` expose only completed owned orders and are retained unchanged
for compatibility.

The old UI immediately `continue`s after CUSTOMER_APPROVED/READY_FOR_RELEASE,
removing drawing actions. The old PDF endpoint requires a token, and creating a
new confirmation delivery is only allowed for the current pending revision.
An existing approved token can read a PDF until expiry/revocation; there was no
permanent authenticated archive independent of that token.

Frozen Plates and approvals are in the existing protected
`frozen_plate_production` schema; PDFs are in the existing private production
bucket. The new read routes reuse the repository and existing bearer identity.
No public Storage URLs, signed-link service, new identities, corporate access,
new role, tables, grants, migrations, geometry generators or token renewal.
Manufacturing Control's compact order/detail/revision organization is a design
reference only. Its client, admin credentials and permissions are not imported.

## Current versus proposed

| Capability | Existing | Phase 1 |
|---|---|---|
| Find orders | Table and separate dropdown | Order cards, exact order-number search, four sort orders, 20-row pagination over owned history |
| Pending records | Excluded | Clearly distinguished from payment recorded; missing totals remain unknown |
| Navigation | Choose again from dropdown | Open detail / return to retained filters and page |
| Multi-plate | Raw input tables | Separate numbered plate panels, original purchased specifications and quantity |
| Prices | Order total | Recorded subtotal/shipping/total; missing line/unit snapshots explicitly unavailable |
| Approved drawings | Controls disappear | Read-only current and historical approved PDF archive |
| Pending drawings | Token-based approval | Same deliberate confirmation/PDF/approval pathway |
| Revisions | Current lifecycle only | Number/date/current/historical/approval state and customer-safe frozen specifications |
| Preview | None | Page 1 rasterized from the exact verified stored PDF; download all original PDF bytes |
| Fulfillment | Approval could imply production | Approval never asserts manufactured, inspected, certified or shipped |
| Quality documents | No released customer document records | Honest unavailable state; #64 remains a separate integration |
| Reorder | None | Not implemented; separate Phase 2 architecture |

## Desktop/mobile proposal and implementation

Desktop: My Orders title and short purpose; Start a quote action; search and sort;
compact bordered order cards showing number/date, plate-entry count, recorded
amount, payment state and conspicuous TEST label. View order opens its detail.
Detail has Back, order summary, recorded amounts, separate plate panels, original
purchased specification table, drawing state and revision expanders. Selecting an
approved revision displays its actual stored PDF page 1, SHA-256 and exact PDF
download. Shipping/document details are secondary.

Mobile uses the same canonical route and single-column flow. Native Streamlit
columns stack; tables scroll within their own container. Actions have text
labels and no hover-only behavior. Test viewports are 1280 and 390 pixels; browser
gates check no page overflow, exact downloaded bytes, visible preview and logout.
The CI browser artifact contains list and drawing screenshots at both sizes.
No public UI displays sourcing, Haas NC, DXF, source JSON, internal notes, token
fingerprints, recipient registries or administrative prices.

## API surfaces

| Route | Purpose / authority |
|---|---|
| GET `/me/order-history` | Existing verified customer identity; owned orders only, bounded pagination, validated search/sort; safe projection |
| GET `/me/order-history/{id}` | Explicit order ownership; allowlisted purchased specifications, recorded totals and address |
| GET `/me/orders/{id}/drawing-archive` | Business-order ownership plus matching Frozen Plate customer/order; read-only revision metadata |
| GET `/me/orders/{id}/drawings/{revision}/pdf` | Recheck order/revision/customer ownership, canonical parent hashes and complete approval binding; read and SHA-256/size-check only the PDF |

Unauthorized private object access is denied before Storage reads. Only approved
revisions can use the archive PDF route; historical unapproved revisions display
metadata without download. Original approval endpoints and transition protections
remain unchanged. GETs create no deliveries, confirmation tokens, revisions or
approvals. Responses contain no private object keys. PDF responses are private,
no-store, nosniff, with exact revision/hash headers; frontend verifies both and
byte length before showing or downloading. No shared PDF/data cache is added.

## Historical records — read-only inspection

| Order | Recorded order total | Persisted drawing evidence |
|---|---:|---|
| OP-0016 | $166.11 TEST | R1 CUSTOMER_APPROVED, PDF/spec/approval binding matches; PDF hash `e08cce607ee042404247b8d0acb27333031d00f743419198d9de7ea6163cf842` |
| OP-0017 | $330.70 TEST | Two separate R1 drawings, both READY_FOR_CUSTOMER_CONFIRMATION; no approval rows at inspection |
| OP-0018 | $1,179.00 TEST | No Frozen Plate row; original width-only chamfer lacks face/angle/flow/width-definition fields |

These are persisted states, separate from earlier owner observations. No historical
repair/backfill, inferred approval, repricing or regenerated artifact is attempted.
The previously disclosed historical aggregate approval-fingerprint discrepancy is
not reconciled or forced to match by this PR.

## Gaps and decisions

* Historical line/unit accepted prices are not retained in the inspected snapshots.
  Display the recorded order amounts without dividing, reallocating or repricing.
  Persisting future accepted per-line snapshots is a separate checkout/data-scope
  decision; no migration or historical write is proposed here.
* Trustworthy customer shipment/tracking, material-cert and final-inspection
  records are not integrated. Show unavailable, never complete/pending assertions
  unsupported by records. Quality-document release is dependent on #64.
* Corporate/invited-buyer ownership and reorder provenance storage are outside
  Phase 1. Existing individual ownership is preserved.
* A PDF preview requires the existing PDFium dependency and a readable stored PDF;
  failed preview still permits a verified original PDF download. Integrity failure
  permits neither preview nor download.

## Acceptance and release gates

Automated tests cover current and historical approvals, expiry-independent archive,
identity and hash bindings, missing/ambiguous historical records, two-line orders,
unauthenticated/cross-customer access, no object read before authorization, exact
PDF bytes and no DXF downloads, unchanged repository rows, search/sort/pagination,
pending amounts, privacy-safe projections, UI navigation, tampered PDF suppression,
actual desktop/mobile routes, download SHA-256 and logout. Full regression and the
51-hash protected-output test are required.

Owner review and separate exact-commit release authorization remain required.
Production browser acceptance has not been performed. No TEST purchases are
required for historical archive acceptance; use existing owned records. Staging
stays suspended, checkout remains TEST, LIVE stays unavailable.
