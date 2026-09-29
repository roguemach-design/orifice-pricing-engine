# Base O-Plates parameter / rule matrix

Scope: restriction/general plates. Each row has exactly one classification. Optional customer overrides are described in notes; no metering-only field is required. “Release” describes the future requirement, not an implemented release workflow. An owner may explicitly decide a requirement is not applicable; absence is not silently treated as approval.

| Field | Classification | Current source | Validation / limits | Drawing location | Required for release | Notes |
|---|---|---|---|---|---|---|
| Application | CUSTOMER INPUT | PlateSpec.application; base fallback restriction-general | restriction-general or metering | Below heading; JSON | Yes | Metering is a placeholder; no rule sets active |
| Plate OD | CUSTOMER INPUT | finished_od | Finite positive; bore/handle width smaller | OD leader | Yes | 5.000; not pipe ID, sealing diameter or compatibility claim |
| Finished bore | CUSTOMER INPUT | finished_bore_diameter | Positive; smaller than OD; valid rough bore | Bore leader | Yes | 1.548 |
| Handle width | CUSTOMER INPUT | handle_width | Positive; smaller than OD; rounds fit | Above handle | Yes | 2.000 |
| C/L to handle end | CUSTOMER INPUT | centerline_to_handle_end | Greater than OD/2; rounds fit | Vertical dimension | Yes | 10.500; explicit C/L label |
| Total physical envelope | DERIVED RULE | C/L-to-tip + OD/2 | Derived from exact specification | Not additionally dimensioned | No duplicate needed | 13.000 for sample |
| Material grade | CUSTOMER INPUT | material | Printable nonempty ASCII, max 40 | Data and title block | Yes | 304 STAINLESS STEEL; no inferred 304L or certificate |
| Thickness | CUSTOMER INPUT | thickness | Finite positive | Section, data, title block | Yes | 0.125; no pipe-ID formula |
| Quantity | CUSTOMER INPUT | quantity | Positive integer | Data and title block | Yes | 1 |
| Corner radius | ROGUE DEFAULT | CORNER_RADIUS | Exactly .03125; builder checks fit | 4X radius note | Yes | Approved contour treatment, not a general edge break |
| Bore diameter allowance | ROGUE DEFAULT | ROUGH_BORE_DIAMETER_ALLOWANCE | Exactly .125 on diameter | Internal JSON / DXF process | Yes | Not a finished-PDF note |
| Rough bore | DERIVED RULE | Finished bore minus allowance | Positive; below minimum bore when tolerance supplied | DXF CUT_BORE; JSON | Yes | 1.423 |
| Radial stock | DERIVED RULE | Allowance / 2 | .0625 | Internal JSON | Yes | No external stock allowance |
| Outer cutting contour | DERIVED RULE | Canonical arcs/lines | Closed; connected; nominal dimensions | DXF CUT_OUTER | Yes | CAM owns kerf; PDF NTS never feeds this contour |
| Chamfer selection | CUSTOMER INPUT | chamfer | True/False; None is unresolved | Section state | Yes | None is not an implicit no-chamfer selection |
| Chamfer size | CUSTOMER INPUT | chamfer_width | Positive finite; selected chamfer must fit | Detail | If selected | No default |
| Chamfer size convention | CUSTOMER INPUT | chamfer_width_definition | radial-angle-from-face or axial-depth-angle-from-face | Detail / JSON | If selected | Must be explicit |
| Chamfer angle | CUSTOMER INPUT | chamfer_angle_degrees | 0 < angle < 90; fit check | Detail angle | If selected | No universal 45-degree default |
| Chamfer side | CUSTOMER INPUT | chamfer_side | upstream or downstream | Detail | If selected | Requires unambiguous flow orientation |
| Flow direction | CUSTOMER INPUT | flow_orientation | left-to-right or right-to-left | Adjacent to section when supplied | Conditional | Required for relative chamfer side; not forced on plain plate |
| Chamfer depth / radial extent | DERIVED RULE | Exact section builder | Trigonometric conversion; positive; fits plate | Section/detail | If selected | No metering rule |
| Remaining land | DERIVED RULE | Thickness minus axial depth | Strictly positive for configured chamfer | Detail | If selected | No API/ISO land default |
| Bore tolerance | OWNER DECISION REQUIRED | Optional explicit PlateSpec.bore_tolerance; no default | Positive; tolerance envelope inside plate; rough stock remains | Bore callout | Yes, policy or explicit value | Never borrowed from reference drawing |
| General .X tolerance | OWNER DECISION REQUIRED | DrawingMetadata.tolerance_x | Approved text; no numerical default | Tolerance block | Policy decision | Specific feature requirement overrides general policy |
| General .XX tolerance | OWNER DECISION REQUIRED | DrawingMetadata.tolerance_xx | Approved text; no numerical default | Tolerance block | Policy decision | Same |
| General .XXX tolerance | OWNER DECISION REQUIRED | DrawingMetadata.tolerance_xxx | Approved text; no numerical default | Tolerance block | Policy decision | Same |
| General angle tolerance | OWNER DECISION REQUIRED | DrawingMetadata.tolerance_angles | Approved text; no numerical default | Tolerance block | Policy decision | No ASME-derived shop value |
| Bore finish | OWNER DECISION REQUIRED | DrawingMetadata.bore_finish | Approved requirement or explicit no additional requirement | Note beside/below views | Policy decision | Available for both plain and chamfered plates |
| Surface finish | OWNER DECISION REQUIRED | DrawingMetadata.surface_finish | Approved requirement; no implicit metering finish | Short note | Policy decision | No invented Ra/RMS |
| Edge/deburr treatment | OWNER DECISION REQUIRED | DrawingMetadata.edge_finish | Approved note; no default break-edge size | Short note | Policy decision | Separate from .03125 contour radii |
| Flatness policy | OWNER DECISION REQUIRED | No base default or active rule | Decide whether a requirement is needed | No unapproved callout | Policy decision only | No datum/FCF or metering formula added |
| Marking content / explicit none | CUSTOMER INPUT | PlateSpec.marking from handle_label | Printable ASCII, max 40; unresolved when absent | Upper-left | Resolved selection needed | Current text field; richer marking policy deferred |
| Marking method | OWNER DECISION REQUIRED | DrawingMetadata.marking_method | Approved text; max 40; must fit | Upper-left | If marking required | No stamp/vibro-etch default |
| Marking location | OWNER DECISION REQUIRED | DrawingMetadata.marking_location | Approved text; max 40; must fit | Upper-left | If marking required | No guessed face/offset |
| Customer tag | CUSTOMER INPUT | DrawingMetadata.customer_tag | Printable nonempty ASCII, max 40 if supplied | Optional data row | Only if ordered | Not forced on base plate |
| Line/service description | CUSTOMER INPUT | DrawingMetadata.line_service | Printable nonempty ASCII, max 40 if supplied | Optional data row | Only if ordered | Not a line-size or fluid-model requirement |
| Order identifier | INTERNAL TRACEABILITY | DrawingMetadata.order_identifier | Printable nonempty ASCII, max 40 | Optional data row | Per future order policy | No live order integration |
| Part number | INTERNAL TRACEABILITY | PlateSpec.part_identifier | Max 40; job basename letters/digits/underscore/hyphen | Title block; paired filenames | Yes | PROTOTYPE-001 until numbering approved |
| Drawing number | DERIVED RULE | OP- plus part identifier | Same frozen specification basename | Title block | Yes | Prototype convention only |
| Production numbering policy | OWNER DECISION REQUIRED | Not established | Owner policy | Future identifiers | Before production integration | Current prototype naming is safe |
| Drawing revision | INTERNAL TRACEABILITY | DrawingMetadata.revision | Printable ASCII, max 40; immutable input | Title block | Yes | P3E |
| Specification revision | INTERNAL TRACEABILITY | DrawingMetadata.specification_revision | Explicit value; no timestamps inferred | Small trace field | Yes | Sample unresolved |
| Order/line revision | INTERNAL TRACEABILITY | DrawingMetadata.order_line_revision | Printable ASCII, max 40 if supplied | Secondary note | Per future order policy | Optional prototype metadata |
| Generator / geometry versions | INTERNAL TRACEABILITY | Code constants | Versioned deterministic code | Small trace field; JSON | Yes | op-drawing-v3e / r03125-v2-prototype |
| Drawing state | INTERNAL TRACEABILITY | DrawingMetadata.state | Enum; no automatic transitions | Bottom status band; JSON | Yes | Prototype and confirmation supported; released state reserved and blocked |
| Customer approval evidence | INTERNAL TRACEABILITY | Future app approval record | Bind exact specification/revision | Future controlled status | Before manufacture per policy | No signature or automatic approval invented |
| Inspection policy | OWNER DECISION REQUIRED | DrawingMetadata.inspection | Approved requirement / method text | Short note | Policy decision | No unsupported acceptance criteria |
| Material-spec / certification policy | OWNER DECISION REQUIRED | Grade remains customer-selected | Verify actual material documents before claiming ASTM/dual certification | Future material note / records | Procurement decision | Grade selection does not prove certification |
| Units | ROGUE DEFAULT | Inches | Uniform values; DXF INSUNITS=1 | Title block; DXF | Yes | No silent unit conversion |
| Scale | ROGUE DEFAULT | NTS presentation policy | Dimension labels from exact spec only | Views/title block | Yes | Do not scale drawing |
| Dimension precision | ROGUE DEFAULT | Existing renderer formatting | .3f nominal; exact .03125 corner note; derived detail precision | Dimension callouts | Policy confirmation before release | Extra radius digits intentionally preserve approved nominal |
| Drawing-practice basis | ROGUE DEFAULT | Owner instruction | ASME Y14.5-2018 label; no unsupported compliance claim | Title block | Yes | No datums or decorative GD&T |
| Third-angle symbol | OWNER DECISION REQUIRED | Not verified/implemented | Decide after appropriate guidance is available | Not emitted | Not a core-generation blocker | No broad standards research repeated |
| Company / title | ROGUE DEFAULT | Owner instruction | Fixed ROGUE MACHINE / O-PLATES and ORIFICE PLATE | Title block and heading | Yes | No reference corporate identity |
| Sheet numbering | DERIVED RULE | Renderer page count | 1 OF 1 for current print | Title block | Yes | Single controlled format |

Metering-only inputs and standard-derived rule profiles are deliberately absent from the base requirements. The metering enum reserves future attachment of separately approved rules; it does not establish metering compliance.
