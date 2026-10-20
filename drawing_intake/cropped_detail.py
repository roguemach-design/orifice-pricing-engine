"""Conservative spatial observations for horizontal raster paddle details.

Pixels establish association only; every dimension comes from printed text.
All layout-derived proposals require review. No catalog/filename/tag lookup.
"""

from __future__ import annotations
import io
import re
import numpy as np
from PIL import Image
from .engineering_text import parse_measurement, parse_material
from .handle_dimensions import _InkTopology
from .models import SourceEvidence
from .rendering import render_region_png, rotate_rendered_region
from .spatial import build_spatial_lines


def rotated_material_ocr(document, region, original, engine):
    if region.derivation_method != "single_quote_specific_raster_page_v1":
        return original, 0.0
    rendered = render_region_png(document, region, dpi=150)
    detail = engine.recognize(rendered, pass_prefix="detail.")
    result = engine.recognize(
        rotate_rendered_region(rendered, 270), pass_prefix="material.rot270."
    )
    # These observations are scoped to material only; sideways noise cannot
    # enter dimension/tolerance resolvers.
    return (
        original.model_copy(
            update={"tokens": [*original.tokens, *detail.tokens, *result.tokens]}
        ),
        result.ocr_seconds + detail.ocr_seconds,
    )


def observations(region, ocr, rendered, document=None):
    from .deterministic import FieldRecognitionResult, RecognitionEvidence

    if (
        rendered is None
        or region.derivation_method != "single_quote_specific_raster_page_v1"
    ):
        return {}
    out = {}

    def propose(
        name, value, tokens, rule, kind="printed_dimension", unit="in", confidence=0.65
    ):
        src = SourceEvidence(
            page_number=region.page_number,
            raw_text=" ".join(t.raw_text for t in tokens),
            bbox=(
                min(t.source_bbox[0] for t in tokens),
                min(t.source_bbox[1] for t in tokens),
                max(t.source_bbox[2] for t in tokens),
                max(t.source_bbox[3] for t in tokens),
            ),
            coordinate_unit=region.coordinate_unit,
            extraction_method="local_ocr+spatial_detail_v1",
            source_type=kind,
        )
        evidence = RecognitionEvidence(
            rule_id=rule,
            description="Text and selected-profile layout support a reviewable candidate; pixels are not a dimensional measurement.",
            source=src,
            token_ids=[t.token_id for t in tokens],
        )
        old = out.get(name)
        vals = sorted(set([value, *(old.candidate_values if old else [])]), key=str)
        conflict = len(vals) > 1
        out[name] = FieldRecognitionResult(
            field_name=name,
            value=None if conflict else value,
            normalized_unit=unit,
            raw_text=src.raw_text,
            confidence=None if conflict else confidence,
            status="ambiguous" if conflict else "low_confidence",
            evidence_classification=(
                "ambiguous" if conflict else "requires_confirmation"
            ),
            candidate_values=vals,
            evidence=[*(old.evidence if old else []), evidence],
            abstention_reason=(
                "conflicting_spatial_observations"
                if conflict
                else "spatial_association_requires_review"
            ),
        )

    # Targeted crops can clip the whole-number prefix off a mixed number.
    # Full detail observations establish annotation values; cropped fragments
    # must not create competing nominal bore candidates.
    lines = build_spatial_lines(
        [t for t in ocr.tokens if not t.engine_pass.startswith("target.")]
    )
    # Explicit descriptive bore text anchors units and corroborates diameter.
    units = None
    for line in lines:
        match = re.search(
            r'(\d+(?:[ -]\d+/\d+|/\d+|\.\d+)?\s*["″°])\s*BORE\b', line.normalized_text
        )
        if match:
            p = parse_measurement(match[1].replace("°", '"'))
            if p and p.unit:
                units = p.unit
                propose(
                    "bore_diameter",
                    p.value,
                    line.tokens,
                    "explicit_bore_marking",
                    kind="printed_annotation",
                    unit=p.unit,
                    confidence=0.8,
                )
                propose(
                    "global_units",
                    p.unit,
                    line.tokens,
                    "explicit_bore_inch_mark",
                    kind="printed_annotation",
                    unit=None,
                    confidence=0.8,
                )
        if line.engine_pass.startswith("material.rot270."):
            m = parse_material(line.raw_text)
            if m:
                propose(
                    "material",
                    m,
                    line.tokens,
                    "rotated_material_phrase",
                    kind="printed_annotation",
                    unit=None,
                    confidence=0.8,
                )
        match = re.search(r"\bTAG\s*:?\s*([A-Z0-9][A-Z0-9-]+)", line.normalized_text)
        if match:
            propose(
                "marking_text",
                match[1],
                line.tokens,
                "labeled_tag_text",
                kind="printed_annotation",
                unit=None,
                confidence=0.8,
            )
    if units is None:
        return out  # Do not assume inch units from an unlabeled decimal.
    x0, y0, x1, y1 = region.candidate_bbox
    cx, cy, R = (x0 + x1) / 2, (y0 + y1) / 2, (x1 - x0) / 2
    ink = _InkTopology(rendered)

    def crossed_glyph(token):
        # Inspect the original glyph before repairing OCR's leading 0/9/4.
        # A numeral without the diameter slash must not lose a leading digit.
        tx, ty, ex, ey = token.source_bbox
        x, y = ink.x(tx), ink.y(ty)
        h = max(1, ink.y(ey) - y)
        for ratio in (0.55, 0.65, 0.75, 0.85):
            xs = np.rint(np.linspace(x + 1, x + h * ratio - 1, 20)).astype(int)
            ys = np.rint(np.linspace(y + h - 2, y + 1, 20)).astype(int)
            if (
                xs.min() < 1
                or ys.min() < 1
                or xs.max() >= ink.ink.shape[1] - 1
                or ys.max() >= ink.ink.shape[0] - 1
            ):
                continue
            hits = np.zeros(20, dtype=bool)
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    hits |= ink.ink[ys + dy, xs + dx]
            if hits.mean() >= 0.9:
                return True
        return False

    tokens = [
        t
        for t in ocr.tokens
        if not t.engine_pass.startswith(("material.", "target.", "handle."))
    ]
    # Find opposing horizontal handle edges and a tip connecting both. This
    # limits unlabelled linear numbers to dimension-line witnesses.
    edge = []
    for y in np.linspace(cy - R * 0.55, cy + R * 0.55, 180):
        if ink.horizontal(y, cx - R * 3, cx - R * 1.15):
            edge.append(y)
    pairs = [
        (a, b)
        for a in edge
        for b in edge
        if a < cy < b and abs(a + b - 2 * cy) < R * 0.045 and b - a > R * 0.15
    ]
    top, bottom = (
        min(pairs, key=lambda p: abs(sum(p) - 2 * cy)) if pairs else (None, None)
    )
    tip = None
    if top is not None:
        xs = [
            x
            for x in np.linspace(
                max(region.source_bbox[0], cx - R * 5), cx - R * 1.7, 250
            )
            if ink.vertical(x, top, bottom)
        ]
        if xs:
            tip = max(xs)
    for t in tokens:
        raw = t.raw_text.upper().replace(",", ".")
        tx, ty, ex, ey = t.source_bbox
        h = max(1, ey - ty)
        mid = (ty + ey) / 2
        # Diameter OCR may consume the crossed-circle glyph as a leading
        # numeral. Strip only in an above-profile leader callout position with
        # a horizontal leader stub. Mark this repair as requiring confirmation.
        number = re.fullmatch(r"[Ø⌀∅$%]?([049]?\d+\.\d+)", raw)
        stub = any(
            ink.horizontal(y, ex + h * 0.3, ex + h * 1.0)
            or ink.horizontal(y, tx - h * 1.0, tx - h * 0.3)
            for y in np.linspace(ty, ey, 7)
        )
        if number and stub and ty < cy and crossed_glyph(t):
            text = number[1]
            if text.startswith(("0", "9")) and len(text.split(".")[0]) > 1:
                text = text[1:]
            elif text.startswith("4") and len(text.split(".")[0]) > 1:
                text = text[1:]
            value = float(text)
            if cx - R * 1.8 < tx < cx and mid < cy - R * 0.85:
                propose(
                    "outside_diameter",
                    value,
                    [t],
                    "above_outer_profile_leader",
                    unit=units,
                )
            elif cx - R * 1.8 < tx < cx and cy - R * 0.85 < mid < cy - R * 0.25:
                propose(
                    "bore_diameter",
                    value,
                    [t],
                    "inside_outer_profile_bore_leader",
                    unit=units,
                )
            elif tip is not None and tip < tx < cx - R * 1.8 and mid < top:
                propose(
                    "tag_hole_diameter",
                    value,
                    [t],
                    "handle_hole_leader_region",
                    unit=units,
                )
        radius = re.match(r"^R[O0]?(\.\d+)", raw)
        if radius and ty > cy and cx - R * 2.5 < tx < cx - R * 0.4:
            propose(
                "neck_radius",
                float("0" + radius[1]),
                [t],
                "lower_transition_radius_callout",
                unit=units,
            )
        if tip is None:
            continue
        if not re.fullmatch(r"\d+\.\d+", raw):
            continue
        value = float(raw)
        if (
            tx < tip
            and mid < top
            and any(
                ink.vertical(x, top, bottom)
                for x in np.linspace(tx - h * 1.5, tx - h * 0.5, 10)
            )
        ):
            propose(
                "handle_width",
                value,
                [t],
                "vertical_witness_between_handle_edges",
                unit=units,
            )
        # A full handle length ends at the bore centerline. A shorter dimension
        # inside the handle is a secondary-hole location only when a vertical
        # witness reaches the hole center, never merely the nearest number.
        if ey > bottom and tip < tx < cx and ink.vertical(tip, bottom, ey):
            rows = np.linspace(ty - h * 0.4, ey + h * 0.4, 14)
            if any(ink.horizontal(y, ex + h * 0.5, cx) for y in rows) and ink.vertical(
                cx, cy, ty
            ):
                propose(
                    "handle_length_from_bore",
                    value,
                    [t],
                    "tip_to_bore_center_witnesses",
                    unit=units,
                )
            elif tx < tip + R * 1.3:
                # Short dimension witness is just left of its text.
                for hx in np.linspace(tx - h * 4.5, tx - h * 0.5, 24):
                    od = out.get("outside_diameter")
                    proportional = (
                        (
                            od
                            and od.value
                            and 0.65
                            < value / float(od.value) / ((hx - tip) / (2 * R))
                            < 1.5
                        )
                        if hx > tip
                        else False
                    )
                    if (
                        proportional
                        and ink.vertical(hx, cy, ty)
                        and any(ink.horizontal(y, tip, hx) for y in rows)
                    ):
                        propose(
                            "tag_hole_position",
                            value,
                            [t],
                            "tip_to_secondary_hole_witnesses",
                            unit=units,
                        )
                        break
    # Preserve blue handwritten notes as distinct evidence even when OCR
    # cannot read the fraction. Color identifies ink, not intended thickness.
    color_image = Image.open(io.BytesIO(rendered.png_bytes)).convert("RGB")
    if document is not None and document.kind in {"png", "jpeg"}:
        from PIL import ImageOps

        original = ImageOps.exif_transpose(
            Image.open(io.BytesIO(document.source_bytes))
        ).convert("RGB")
        color_image = original.crop(region.source_bbox).resize(
            (rendered.width, rendered.height)
        )
    rgb = np.asarray(color_image).astype(int)
    blue = (rgb[:, :, 2] - rgb[:, :, 0] > 25) & (rgb[:, :, 0] < 230)
    if blue.sum() > 50:
        ys, xs = np.where(blue)
        src = SourceEvidence(
            page_number=region.page_number,
            bbox=rendered.transform.pixel_bbox_to_pdf(
                (int(xs.min()), int(ys.min()), int(xs.max() + 1), int(ys.max() + 1))
            ),
            coordinate_unit=region.coordinate_unit,
            extraction_method="colored_ink_region",
            source_type="handwritten_note",
        )
        out["thickness"] = FieldRecognitionResult(
            field_name="thickness",
            status="not_detected",
            evidence_classification="not_detected",
            abstention_reason="handwritten_note_unreadable_confirm_thickness",
            evidence=[
                RecognitionEvidence(
                    rule_id="separate_colored_ink_note",
                    description="Colored note requires human reading; no thickness inferred from its shape.",
                    source=src,
                )
            ],
        )
        for t in tokens:
            x, y, ex, ey = t.source_bbox
            bx, by, bex, bey = src.bbox
            if not (x < bex and ex > bx and y < bey and ey > by):
                continue
            px, py, pex, pey = ink.x(x), ink.y(y), ink.x(ex), ink.y(ey)
            note_pixels = blue[max(0, py) : pey, max(0, px) : pex]
            dark_pixels = rgb[max(0, py) : pey, max(0, px) : pex].min(axis=2) < 230
            if (
                note_pixels.sum() < 10
                or note_pixels.sum() / max(1, dark_pixels.sum()) < 0.5
            ):
                # A few colored scan specks do not make a black printed bore
                # annotation a handwritten thickness note.
                continue
            match = re.fullmatch(r'\s*(\d+(?:[ -]\d+/\d+|/\d+)\s*["″])\s*', t.raw_text)
            if match:
                p = parse_measurement(match[1])
                if p:
                    propose(
                        "thickness",
                        p.value,
                        [t],
                        "colored_note_explicit_fraction",
                        kind="handwritten_note",
                        unit=p.unit,
                        confidence=0.4,
                    )
    return out
