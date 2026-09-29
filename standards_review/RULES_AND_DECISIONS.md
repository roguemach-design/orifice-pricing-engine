> Superseded for base-product scope by [Phase 3E](../PHASE3E_REVIEW.md). Metering research and prior release questions are not requirements for restriction/general plates.

# Standards verification and confirmation-drawing prerequisites

Baseline: `14840cc75293b759e5b456177b38be7d3fb244af`, branch `work/deterministic-manufacturing-prototype`.

This is a requirements review, not a manufacturing release. No new numerical manufacturing defaults have been activated. A signable revised PDF and completed standards-driven generator are blocked by the primary-standard text, application inputs and shop decisions below. The existing sample PDF remains the previous prototype; it has not been relabeled as compliant.

## Existing dimensions resolved

The code identifies Ø5.000 as the finished **plate outside diameter**. There is no separate sealing diameter in the current specification. The 10.500 dimension is from bore/plate centerline to handle tip. Total overall length is 13.000, including the 2.500 radius below the centerline. Pipe inside diameter is a different, currently absent input.

The approved four corner radii are exactly .03125. Keeping five decimal places is intentional: printing .031 with a general three-place tolerance would change the nominal specification unless separately approved. The rough bore remains 1.423, derived from finished 1.548 minus .125 on diameter.

## Source availability and precedence

- [API official fifth-edition scope sheet](https://www.api.org/~/media/files/publications/whats%20new/14_3_2%20e5%20pa.pdf): establishes scope for concentric square-edged flange-tapped flow metering. It does **not** expose the needed manufacturing tables. Full governing AGA/API edition, amendments and relevant clauses are required. No API bore-tolerance bins, flatness values or marking requirements have been guessed.
- [ISO 5167-2:2022 preview of the actual standard](https://cdn.standards.iteh.ai/samples/79180/1029711dc5e5474f8c079fffcf5b6b3b/ISO-5167-2-2022.pdf): relevant geometry clauses are available. The conditional inventory below is secondary-reference material, not an adopted API substitute.
- [ASME Y14.5-2018 official publication](https://www.asme.org/codes-standards/find-codes-standards/y14-5-dimensioning-tolerancing/2018): edition confirmed. Available official preview is front matter, insufficient for validating a complete new datum/FCF scheme. Obtain controlled Y14.5, Y14.100 and projection/view convention references (Y14.3).
- [ASME MFC-3M official preview](https://www.asme.org/getmedia/39d2e54f-a1d3-4531-bf3c-9d32ee96ce13/mfc-3m_2004_r2017_toc.pdf): front matter, not the required rule text. Select edition/addenda and supply relevant text.
- [ASTM A240/A240M official listing](https://store.astm.org/a0240_a0240m-25a.html): material specification identified; governing edition and certification requirements still need confirmation. Dual certification is a procurement decision requiring evidence from the actual MTR, not something the renderer can infer.

## Conditional ISO rule inventory — not active manufacturing defaults

D = pipe ID; d = bore; E = plate thickness; e = bore land. These secondary rules cannot establish API compliance.

| ISO 5167-2:2022 clause | Verified requirement / implementation distinction |
|---|---|
| 5.1.3.1 | Prescribed straightedge gap < .005(D-d)/2; retain its setup, region and installation conditions. |
| 5.1.3.2 | Upstream Ra < .0001d over specified region. |
| 5.1.5.1–2 | .005D ≤ e ≤ .02D; e < .1d; land variation ≤ .001D. |
| 5.1.5.3 | e ≤ E ≤ .05D; 50–64 mm pipe exception permits E to 3.2 mm; operating deformation remains applicable. |
| 5.1.5.4 | E variation ≤ .001D for D ≥ 200 mm; otherwise ≤ .2 mm. |
| 5.1.6 | E > e requires downstream bevel; 45° ±15°. |
| 5.1.7 | Upstream burr-free edge; radius ≤ .0004d; squareness 90° ±.3°; preserve inspection conditions. |
| 5.1.8.2–3 | At least four diameter measurements; each within .05% of mean. **Not an ordered-nominal bore tolerance.** |
| 5.1.9 | Bidirectional configuration has distinct unbevelled requirements. |

No numeric rule is selected for this sample until D, service, flow configuration and primary-standard precedence are established. A required range does not uniquely choose a nominal land value.

## Proposed implementation boundary

Keep PlateSpec/canonical geometry and the rough-blank DXF independent from a versioned requirements profile. The profile must carry standard edition, clause/table ID, units, applicability predicates, inclusive/exclusive bin boundaries, input dependencies, output values and verification status. Only verified, approved profiles may supply a confirmation/release drawing. Missing values produce a structured blocking error; they must not silently become zero, an assumed tolerance or an undocumented default.

API bore tolerance must distinguish an ordered nominal tolerance from diameter variation, measurement uncertainty or acceptance of a measured mean. Implement the actual primary table only after its text is available. Test every boundary and reject uncovered ranges. Do not synthesize bins from ISO diameter-variation requirements.

States should be immutable workflow records:

- PROTOTYPE: may show a conspicuous incomplete-design watermark and a separate unresolved-items report; cannot be signed as configuration approval.
- CUSTOMER CONFIRMATION: all customer/design requirements resolved; signature/date and approved specification digest bind the exact revision. Material heat may follow an explicit procurement-stage policy rather than an invented heat number.
- RELEASED FOR MANUFACTURE: separate authorized approval with complete manufacturing requirements and applicable material traceability. A customer signature alone does not release manufacture.

The latest request supersedes the previous prohibition on datums. However, the proposed scheme still needs engineering definition. A is a plausible upstream-face datum. B must identify the actual centering feature and its simulation, rather than assuming the laser-cut interrupted OD locates the installed plate. A face and a circular centering datum leave rotation about the axis unconstrained; decide whether handle clocking has a functional requirement. Position can govern bore location/orientation, so avoid a redundant perpendicularity control unless an independently tighter requirement is intended. Numerical FCF values cannot be derived from general drafting conventions.

## Practical inspection review

Bore mics/pin gauges address size, but do not alone demonstrate bore position relative to a datum system. A locating fixture and indicator/height-gauge arrangement may be needed. A surface plate/indicator setup must match the controlled feature and specified mounting condition; a straightedge departure criterion is not automatically equivalent to GD&T flatness. Use a profilometer for explicitly stated roughness parameter and region. Edge inspection needs the governing standard's method and acceptance condition. No metrology capability or uncertainty values have been assumed.

The requested .005–.015 edge break is a proposed Rogue requirement, not a sourced universal standard value. Its exceptions need review beyond the upstream edge: indiscriminate downstream edge breaking can alter the controlled bore land. General decimal/angle tolerances likewise require Rogue process capability and approval; ASME drafting conventions do not select suitable numerical values for the shop.

## Decisions / inputs needed

1. Supply the governing AGA 3 Part 2/API 14.3.2 edition and relevant licensed clauses/tables, plus controlled drawing/material/secondary-standard extracts needed to validate the requested controls. Do not send account credentials.
2. Is this sample a metering plate or a restriction plate? Provide line size, schedule/actual pipe ID, flange class/facing, tap arrangement, single/bidirectional flow, temperature and design differential pressure/support conditions.
3. Does the plate OD actually center the assembly? Define the centering interface and whether handle clocking matters. Confirm an available inspection fixture or approve its development.
4. Approve a Rogue tolerance/finish/edge/marking policy, or supply an existing accepted shop print to use as its source. Do not adopt the earlier illustrative chamfer as a default.
5. Confirm 304 versus mandatory 304/304L dual certification, and which stage assigns heat/tag/order information. Recommend retaining Type 304 as ordered until dual-cert purchasing and MTR verification are explicitly approved.

The accompanying PARAMETERS.csv inventories drawing/workflow fields, their sources, validation conditions and sample gaps. No production, runtime geometry, DXF allowance or provider configuration was changed during this review.
