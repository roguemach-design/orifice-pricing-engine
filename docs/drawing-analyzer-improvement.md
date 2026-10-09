# Cropped paddle detail recognition

The drawing analyzer is assisted intake. Its observations are proposals; reviewed configurator values remain authoritative. Recognition never creates an order or manufacturing release.

## Supported path

- A bounded large-profile search supplements the existing raster detector. Both inner and outer concentric perimeters must pass original-pixel checks.
- A cropped single detail requires labeled tag and bore context. Catalog language and insufficient part context retain manual fallback.
- Full-page OCR and a separate material-only rotated pass preserve spatial provenance. Material-only tokens cannot become dimensions.
- Nominal mixed numbers are whole plus fraction. Clipped fractional tails without tolerance context cannot become minus tolerances.
- Diameter-glyph pixels and leader stubs gate OCR repair. Selected-profile layout and handle witness lines associate proposed fields. Pixel distances classify associations and reject inconsistent readings; they never generate dimensions.
- Competing readings remain ambiguous. Printed dimensions, printed annotations and colored-note observations carry separate provenance.
- Heuristic scores 0.65/0.80/0.40 are engineering review aids, not calibrated probabilities. New spatial and colored-note proposals require review.
- Readable explicit fractions in predominantly colored ink can become low-confidence thickness candidates. Unreadable notes remain unresolved. Colored scan specks cannot reclassify printed dimensions as notes.

Secondary-hole diameter, secondary-hole position and transition radius are reference observations only. They have no QuoteInputs mapping and do not extend canonical manufacturing geometry. The evidence expander distinguishes these from configuration proposals. Manual correction, validation and explicit confirmation remain available.

## Local review

Install the pinned repository requirements and local Tesseract, then run:

```bash
python scripts/review_drawing_analyzer.py /absolute/path/to/drawing.png
```

The command prints classification, structured field evidence and configuration-review status. It creates no order, invokes no pricing, and connects to no production service. Multiple details require `--candidate` using a listed candidate ID.

## Tests and limitations

`tests/test_drawing_cropped_detail.py` generates synthetic geometry and generic tags. It covers varied nominal fractions and material abbreviations, source provenance, dimension/text separation, conflicts, color noise, real upload/OCR/selection, and the explicit review boundary. No customer images are included.

The spatial extension supports horizontal handles to the left of the selected circle. It does not trace complete leaders or prove geometry from photographs. Other layouts retain existing recognition or manual fallback. Color-note classification currently applies to raster uploads, not colored PDF annotations or black handwriting. OCR may leave handwriting unreadable. Missing required specifications require manual entry; absence of a chamfer callout is not evidence of no chamfer.
