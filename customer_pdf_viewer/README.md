# Private approved-PDF viewer (Release A2)

This is a browser-only PDF.js canvas component inside the existing Streamlit UI.
It has no document URL endpoint, database, separate service, Node runtime or CDN.

## Technology decision

Evaluated the pinned Streamlit 1.64 `st.pdf` implementation and the official
`streamlit-pdf` 2.1.0 wheel. The optional package is not in the release lockfile.
Its raw-byte input is registered in the shared Streamlit media manager, and its
viewer lacks the required full-screen action. A data URI avoids its media manager
but would still require extra full-screen, download and privacy integration.

The narrow PDF.js alternative keeps only canvas page rendering and local controls.
Bundled upstream distribution: pdfjs-dist 6.5.438 (Apache-2.0), exact npm lockfile,
upstream license and byte manifest. The worker is deterministically gzip-compressed
for smaller delivery, then decompressed with the browser-native DecompressionStream
and checked against its upstream SHA-256 before creating a worker Blob URL. No annotation links, attachments, PDF scripting,
XFA or manufactured-file browsing is exposed. `isEvalSupported` is false. A strict
component CSP permits bundled code/worker and local Blob resources only. Standard
system fonts are permitted; a PDF that cannot render gets an explicit verified-file
download fallback, never regenerated geometry.

## Delivery and lifecycle

Every mount fetches through the existing authenticated archive endpoint. Python
checks approved state, revision header, stored size, hash header and SHA-256 of the
actual bytes. Only verified bytes enter the component through the active Streamlit
session. The browser rechecks size/SHA-256 before making a local PDF Blob. PDF.js
receives a separate byte copy because its worker may transfer/detach that array.
The original is retained only for exact-byte downloads. No st.image/st.pdf(bytes)/
st.download_button is used for the approved archive. Public component source URLs
contain only code, never the PDF, owner token, storage URL or service key.

Owner/revision/hash form the component identity. The component clears its canvas,
destroys PDF tasks, drops private byte references and revokes Blob URLs on pagehide/
unmount. Server logout/account-change/failed authorization clears My Orders state.
The pending approval flow stays token-bound and distinct; its existing renderer is
outside this approved-archive component and is not relabeled as an approved file.

A nonzero initial component height prevents zero-height initialization from being
hidden by the existing cookie component's spacing CSS. Subsequent height reporting
is deduplicated and reflects the actual toolbar/canvas. Canvas allocations are
bounded to 16 million pixels, zoom is 50–600%, and requests are coalesced. Page
navigation renders one page at a time. Every download is the full original PDF.

## Fullscreen and accessibility

Toolbar buttons are keyboard accessible with visible focus. The drawing region
supports arrow-key scrolling, +/- zoom and 0 to fit; mouse/touch dragging pans;
two-pointer touch gestures zoom. Fullscreen uses the browser API. A minimal
`allow="fullscreen"` delegation on the existing landing iframe is required for
cross-origin embedding. The existing landing layout bridge freezes host height
updates only while this PDF iframe is in native fullscreen, then resynchronizes
on fullscreen exit; temporary fullscreen viewport sizes must not feed back into
the normal embedded layout. The UI offers an honest verified-download fallback where
the browser/host denies it. This does not widen or navigate the host.

## Rebuilding vendor files

From frontend/vendor: `npm ci --ignore-scripts --omit=optional`, copy
node_modules/pdfjs-dist/build/pdf.min.mjs and LICENSE into this folder; encode
pdf.worker.min.mjs with Python gzip.compress(data, mtime=0). Regenerate and review
SHA-256 manifest.json including the uncompressed worker digest in viewer.js. Review upstream changes,
license and dependency audit before updating the pin. Never fetch runtime code
from a CDN. The supplied optional native-canvas packages are not installed or used.
