# Phase 1I: owner-test pricing handoff

The existing `pages/1_Quote.py` form owns both manual and drawing-assisted
entries. It loads `/config/active`, builds the same twelve-field canonical
request, and displays the response from the existing API `POST /quote`.
`api_app.QuoteRequest` validates that request, constructs `QuoteInputs`, and
uses the active pricing configuration. The UI never calculates a sell price.

Phase 1H stopped a confirmed drawing session at
`accept_pricing_boundary_without_invocation`. Phase 1I replaces that preview
in the owner-test UI with `confirmed_drawing_quote_inputs`. This gate requires:

- a selected, quote-specific plate or schedule row;
- complete, valid canonical fields under the loaded active configuration;
- a current purchaser confirmation fingerprint;
- exact agreement between the confirmed `QuoteInputs` snapshot and the visible
  form payload.

The returned payload contains only `QuoteInputs` fields. The same page function
`request_authoritative_price` posts both manual and drawing-assisted payloads
to `/quote`. Drawing evidence, filenames, source locations, confidence, and
confirmation state remain outside that request. Recognition does not set
chamfer, chamfer width, or lead time; unsupported asymmetric tolerance remains
unresolved until the buyer makes an explicit supported selection or seeks RFQ.
Handle length is the bore-center-to-tip field directly.

Drawing-assisted pricing additionally requires owner acceptance mode and the
existing server-verified access check. The UI never enables drawing-assisted
checkout or cart actions, even when a price is shown. Ordinary manual pricing
and the API are unchanged. A form edit clears the confirmation fingerprint;
on the next Streamlit run, no request is made and the old price is absent.
Pricing errors leave form state intact and show a distinct pricing error.

Local acceptance compares SYN-W1-01 and partially populated SYN-W1-06
canonical payloads against ordinary manual payloads at the same `/quote`
endpoint. A corrected OD reaches pricing after reconfirmation. Response IDs and
timestamps naturally differ between requests; all substantive price, shipping,
validation, and normalized configuration fields must agree. Existing drawing
tests retain the AVCO reference and Andritz multi-candidate safeguards.

This branch is local only. Owner browser timing from upload through buyer
completion and quote response cannot be measured until isolated deployment;
human entry time must be reported separately from recognition/API latency.
