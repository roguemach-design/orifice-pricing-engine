# Manufacturing Control staging review

This is an owner-authorized, review-only replacement candidate for `/Internal_Sourcing`.
Production remains on its existing deployment until owner acceptance and separate release authorization.

## Data contracts and dependencies

- **B1:** `GET /admin/manufacturing-summary` joins current Frozen Plate metadata for completed orders within the latest 200 order records. The SQL join runs in the existing Frozen Plate database against a bounded order ID set. Search, material/thickness/date/mode/approval filters and ten-order pagination operate within that explicit snapshot. No all-time or database-wide search claim. Frozen Plates uses an independently labeled latest-200 inventory; it can open orphan records. Sourcing lists orders whose loaded current lines have sourcing evidence; selected revision details show every recorded route.
- **B2:** Snapshot scope/time and `partial: true` are mandatory. Counts are line records with matching approval evidence, never byte verification or manufacturing release. HOLD and email reconciliation counts are null. Email provider evidence requires a deliberate per-revision read because the accepted endpoint verifies stored files. Cross-database reads are not an atomic global snapshot.
- **B3:** No schema migration, HOLD persistence or fabricated HOLD state. Missing evidence reads “Record unavailable.”
- **B4:** Existing `orders.paid_at` exposed through admin list/detail reads. Missing dates read “Not recorded.” Historical paid dates may have been backfilled by the previously accepted system; this portal does not infer new timestamps.
- **B5:** Shared `frozen_plate.download_names.dxf_delivery_name` produces the API header and UI name. Material mappings are explicit and case-insensitive for 304/316/CS and established names; unknown inputs fail closed. Decimal formatting preserves canonical precision with at least three decimal places. At/above one inch, retain the integer part. Human order numbers, positive line indices and immutable revision numbers are required. Missing authoritative naming data blocks DXF delivery. PDF/JSON retain stored names. Nothing rewrites storage, spec, object keys, revisions or artifacts.
- **B6:** Admin-only mode classification recognizes explicit TEST/LIVE session prefixes with valid characters; malformed/missing information is UNKNOWN. Verified owner-test markers retain OWNER TEST. Customer checkout and payment logic are unchanged.
- **B7:** Existing shared key and API authorization retained. Explicit unlock, session-only credential, cleared input, Lock deletes all owner state/data. No person identity, role-management or per-person audit introduced.

## Streamlit implementation choices

Design colors, spacing, card hierarchy, status vocabulary, responsive stacking, navigation and engineering disclosures follow the approved seven-page design. Fonts use the installed sans-serif/monospace fallback; the Spy Agency/IBM Plex font files were not supplied. All CSS is injected by the owner page only. Streamlit's mobile sidebar is collapsible. “Prepare file” followed by native “Download” is a deliberate two-step alternative to the design's single file action: it permits a truthful visible integrity result and avoids automatic reads. Prepared bytes are not retained in session state; a rerun removes the download control. Every preparation calls the protected backend again. No successful byte verification label is rendered from metadata.

The accepted API combines missing evidence, supersession and integrity conflicts as 409. UI wording therefore stays generic; client-observed length/hash failures receive explicit integrity copy. Context remains selected on errors. No provider-email outcome is relabeled as inbox delivery. Captured MIME downloads are omitted because they can expose bearer approval links. The history shows capture metadata and deliberately loaded provider evidence.

## Security and read behavior

Only `GET` requests are implemented by the portal client. It refuses redirects and empty credentials; a credential never appears in markup/query strings. No global or cross-user metadata cache. Summary reads no artifact bytes. Order details load metadata, history and revisions only; PDF/DXF/JSON bytes load on Prepare. The existing API performs current-revision, exact PDF/spec approval and complete package verification before DXF delivery; the client checks SHA-256, size and DXF response filename. No approval, revision creation, retry, send/resend, sourcing mutation, vendor submission or release controls exist.

## Production release and rollback (requires separate owner authorization)

1. Owner accepts the exact staging UI/API commit and download evidence. Capture the then-current production UI/API deployment SHAs and service settings; do not assume the historical baseline is still current.
2. Deploy the accepted API commit first to production API using its existing production command/environment. Verify health, anonymous 401 and protected read/download behavior. Then deploy the same UI commit using its existing Streamlit command. Do not change Stripe, SendGrid, pricing, public configurator, storage or database bindings.
3. Verify the production portal against existing approved records, historical DXF denial and Lock. No record generation or mutation is part of verification. Verify customer route regressions without purchasing.
4. Roll back UI and API to their independently captured prior deployment SHAs if acceptance checks fail. No new schema or stored-artifact changes exist to reverse. Preserve the legacy pricing admin throughout. For staging rollback, both services were on `a97a664686ca91d8edaa42f223542ac284b78c34` before this task.

Stop at staging acceptance. No production deployment is authorized by this document.
