"""Deterministic v6 customer confirmation; immutable stored PDFs are never rewritten."""

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

import reportlab
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from plate_geometry import GEOMETRY_VERSION, PlateGeometry
from manufacturing_context import DrawingState, STATUS_LABELS, PlateApplication

FONT_DIR = Path(reportlab.__file__).parent / "fonts"
for name, file in (("PlateSans", "Vera.ttf"), ("PlateSansBold", "VeraBd.ttf")):
    pdfmetrics.registerFont(TTFont(name, str(FONT_DIR / file)))

HOLD = "NOT SPECIFIED - HOLD"
GENERATOR_VERSION = "op-drawing-v6"
PAGE_SIZE = (612, 792)  # US Letter portrait; one line item per sheet.


@dataclass(frozen=True)
class DrawingMetadata:
    revision: str = "P3E"
    state: DrawingState = DrawingState.PROTOTYPE
    order_line_revision: str | None = None
    specification_revision: str | None = None
    # Approved note text only; no shop requirements are inferred by the renderer.
    surface_finish: str | None = None
    bore_finish: str | None = None
    edge_finish: str | None = None
    inspection: str | None = None
    marking_method: str | None = None
    marking_location: str | None = None
    tolerance_x: str | None = None
    tolerance_xx: str | None = None
    tolerance_xxx: str | None = None
    tolerance_angles: str | None = None
    order_identifier: str | None = None
    customer_tag: str | None = None
    line_service: str | None = None
    flow_orientation: str | None = None
    # Opt-in future section convention. Never inferred from a width alone.
    chamfer_width_definition: str | None = None

    def __post_init__(self):
        object.__setattr__(self, "state", DrawingState(self.state))
        for value in (
            self.revision,
            self.specification_revision,
            self.surface_finish,
            self.bore_finish,
            self.edge_finish,
            self.inspection,
            self.marking_method,
            self.marking_location,
            self.tolerance_x,
            self.tolerance_xx,
            self.tolerance_xxx,
            self.tolerance_angles,
            self.order_line_revision,
            self.order_identifier,
            self.customer_tag,
            self.line_service,
        ):
            if value is not None and (
                not isinstance(value, str)
                or not value.strip()
                or len(value) > 40
                or not value.isascii()
                or any(ord(c) < 32 for c in value)
            ):
                raise ValueError(
                    "drawing metadata must be 1-40 printable ASCII characters"
                )
        if self.flow_orientation not in (None, "left-to-right"):
            raise ValueError("supported section flow orientation is left-to-right")
        if self.chamfer_width_definition not in (None, "radial-angle-from-face"):
            raise ValueError("unsupported chamfer dimension convention")


def section_profile(g, metadata):
    from dataclasses import replace
    from section_geometry import build_section_geometry

    s = g.spec
    updates = {}
    for field in ("flow_orientation", "chamfer_width_definition"):
        value = getattr(metadata, field)
        if value is not None:
            if getattr(s, field) not in (None, value):
                raise ValueError("conflicting section metadata")
            updates[field] = value
    result = build_section_geometry(replace(s, **updates))
    return {
        **result.to_dict(),
        "chamfer_drawn": result.chamfer_drawn,
        "finished_bore_diameter": s.finished_bore_diameter,
    }


from drawing_presentation import build_views, paint_pdf, Scene, PAGE_SIZE, text_width
from drawing_standards import (
    UOS_XX,
    UOS_XXX,
    UOS_ANGLES,
    EDGE_BREAK,
    FACE_FINISH,
    MARK_HEIGHT,
)
import json
import re

# Generator release date; fixed for repeatable bytes, never wall-clock dependent.
GENERATOR_DATE = "10/20/26"


def short_identifier(value):
    value = re.sub(r"(?i)prototype", "SAMPLE", value)
    value = re.sub(
        r"(?i)(?<![a-z0-9])[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}",
        lambda m: m[0][:8].upper(),
        value,
    )
    return re.sub(r"(?i)[a-f0-9]{12,}", lambda m: m[0][:8].upper(), value)


def normalized_material(value):
    return {
        "304": "304 STAINLESS STEEL",
        "316": "316 STAINLESS STEEL",
        "Carbon Steel": "CARBON STEEL",
    }.get(value, value.upper())


def traceability(metadata):
    return " · ".join(
        v
        for v in (
            (
                "ORDER " + short_identifier(metadata.order_identifier)
                if metadata.order_identifier
                else None
            ),
            (
                "LINE " + metadata.order_line_revision
                if metadata.order_line_revision
                else None
            ),
            "SPEC " + (metadata.specification_revision or metadata.revision),
            "GEN " + GENERATOR_VERSION,
        )
        if v
    )


def sheet_annotations(g, metadata, view, section):
    s, scene = g.spec, Scene()

    def fitted(x, y, value, width, size=8, bold=False):
        value = short_identifier(str(value))
        measured = text_width(value, size, bold)
        if measured > width:
            size *= width / measured
        if size < 5:
            raise ValueError("drawing text exceeds its allocated field")
        scene.text(x, y, value, size, bold)

    def rect(x, y, w, h, width=0.7):
        scene.path(
            (
                ("M", x, y),
                ("L", x + w, y),
                ("L", x + w, y + h),
                ("L", x, y + h),
                ("Z",),
            ),
            width,
        )

    def cell(x, y, w, h, label="", value="", size=8.5, bold=False):
        rect(x, y, w, h)
        if label:
            scene.text(x + 3, y + h - 6.5, label, 5)
        if value:
            fitted(x + 3, y + 3.5, value, w - 6, size, bold)

    rect(18, 18, 576, 756, 1.25)
    if section.chamfer_drawn:
        face = (s.chamfer_side or "downstream").upper()
        bore = f"BORE CHAMFER ON {face} FACE. FREE OF BURRS."
    elif s.chamfer:
        bore = "BORE CHAMFER SPECIFIED; SIZE REQUIRED. FREE OF BURRS."
    else:
        bore = "BORE EDGES SHARP, NO CHAMFER. FREE OF BURRS."
    mark = "MARKING: NONE."
    if s.marking and s.marking != "No label":
        mark = f'MARK "{s.marking}" {MARK_HEIGHT} HIGH ON HANDLE, UPSTREAM FACE'
        mark += (
            " (OPPOSITE CHAMFER)."
            if section.chamfer_drawn
            and (s.chamfer_side or "downstream") == "downstream"
            else "."
        )
    for label, value in (
        ("METHOD", metadata.marking_method),
        ("LOCATION", metadata.marking_location),
    ):
        if value:
            mark += " / " + label + ": " + value
    notes = [
        "INTERPRET DIMENSIONS AND TOLERANCES PER ASME Y14.5-2018.",
        "THICKNESS TOLERANCE PER MATERIAL MILL STANDARD.",
        bore,
        (
            "EDGES: " + metadata.edge_finish
            if metadata.edge_finish
            else "DEBURR ALL OTHER EDGES; BREAK SHARP EDGES " + EDGE_BREAK + "."
        ),
        "FACES: " + (metadata.surface_finish or FACE_FINISH) + ".",
        mark,
    ]
    # Existing explicit requirements remain visible; no values are invented.
    extra = []
    for label, value in (
        ("BORE FINISH", metadata.bore_finish),
        ("INSPECTION", metadata.inspection),
        ("UOS .X", metadata.tolerance_x),
        ("CUSTOMER TAG", metadata.customer_tag),
        ("LINE SERVICE", metadata.line_service),
    ):
        if value:
            extra.append(label + ": " + value)
    scene.text(39.6, 228.96, "NOTES:", 8, True)
    for i, note in enumerate(notes, 1):
        scene.text(39.6, 228.96 - 12 * i, f"{i}.", 7.3)
        fitted(51.6, 228.96 - 12 * i, note, 530, 7.3)
    if extra:
        # Preserve optional metadata without expanding the six numbered notes.
        fitted(39.6, 143.5, " / ".join(extra), 540, 6)
    x, y, w, lw = 18, 136, 576, 150
    cell(x, y - 26, lw, 26)
    scene.text(x + 5, y - 12, "ROGUE MACHINE LLC", 8, True)
    scene.text(x + 5, y - 21, "O-PLATES · YORKVILLE, OH", 5.5)
    cell(
        x + lw, y - 26, w - lw - 150, 26, "TITLE", "ORIFICE PLATE, HANDLED", 10.5, True
    )
    identifier = short_identifier(s.part_identifier)
    if not identifier.upper().startswith("OP-"):
        identifier = "OP-" + identifier
    cell(x + w - 150, y - 26, 112, 26, "DWG NO.", identifier, 8.5, True)
    cell(x + w - 38, y - 26, 38, 26, "REV", metadata.revision, 10.5, True)
    y -= 26
    cell(x, y - 44, lw, 44)
    scene.text(x + 4, y - 8, "UNLESS OTHERWISE SPECIFIED:", 5, True)
    scene.text(x + 4, y - 17, "DIMENSIONS IN INCHES", 5.5)
    scene.text(
        x + 4,
        y - 28,
        ".XX ±"
        + (metadata.tolerance_xx or UOS_XX)
        + "    .XXX ±"
        + (metadata.tolerance_xxx or UOS_XXX),
        6.3,
    )
    scene.text(
        x + 4, y - 38, "ANGLES ±" + (metadata.tolerance_angles or UOS_ANGLES), 6.3
    )
    cell(
        x + lw, y - 22, w - lw - 150, 22, "MATERIAL", normalized_material(s.material), 8
    )
    for off, cw, label, value in (
        (150, 40, "QTY", str(s.quantity)),
        (110, 36, "SIZE", "A"),
        (74, 36, "SCALE", view.scale_label),
        (38, 38, "SHEET", "1/1"),
    ):
        cell(x + w - off, y - 22, cw, 22, label, value, 8)
    y -= 22
    third = (w - lw) / 3
    for i, (label, value) in enumerate(
        (
            ("DRAWN", "O-PLATES GEN  " + GENERATOR_DATE),
            ("CHECKED", ""),
            ("CUSTOMER APPROVAL", ""),
        )
    ):
        cell(x + lw + i * third, y - 22, third, 22, label, value, 6)
    y -= 22
    cell(x, y - 22, 46, 22)
    sx, sy = x + 7, y - 22 + 6
    scene.path(
        (
            ("M", sx, sy + 2),
            ("L", sx + 12, sy),
            ("L", sx + 12, sy + 9),
            ("L", sx, sy + 7),
            ("Z",),
        ),
        0.6,
    )
    scene.circle((sx + 24, sy + 4.5), 4.5, 0.6)
    scene.circle((sx + 24, sy + 4.5), 2, 0.6)
    cell(x + 46, y - 22, lw - 46, 22, "", "DO NOT SCALE DRAWING", 5.2, True)
    cell(x + lw, y - 22, w - lw, 22)
    scene.text(
        x + lw + 6,
        y - 22 + 8,
        "CUSTOMER CONFIRMATION — NOT RELEASED FOR MANUFACTURE",
        7.5,
        True,
    )
    cell(x, 18, w, 26)
    fitted(x + 6, 28, traceability(metadata), w - 12, 5.5)
    return scene


def render_pdf(
    g: PlateGeometry, metadata: DrawingMetadata | None = None, *, presentation=None
):
    from dataclasses import replace

    metadata = metadata or DrawingMetadata()
    if metadata.state == DrawingState.RELEASED:
        raise ValueError("manufacturing release is not implemented; confirmation only")
    updates = {}
    for field in ("flow_orientation", "chamfer_width_definition"):
        value = getattr(metadata, field)
        if value is not None:
            if getattr(g.spec, field) not in (None, value):
                raise ValueError("conflicting section metadata")
            updates[field] = value
    drawing_geometry = replace(g, spec=replace(g.spec, **updates)) if updates else g
    scene, view, section = build_views(drawing_geometry, presentation)
    out = BytesIO()
    c = canvas.Canvas(out, pagesize=PAGE_SIZE, invariant=1, pageCompression=1)
    c.setTitle(
        short_identifier(g.spec.part_identifier) + " - customer confirmation drawing"
    )
    c.setAuthor("O-Plates deterministic generator")
    c.setSubject(
        json.dumps(
            {
                "geometry": GEOMETRY_VERSION,
                "generator": GENERATOR_VERSION,
                "state": metadata.state,
                "order": metadata.order_identifier,
                "part": g.spec.part_identifier,
            },
            sort_keys=True,
        )
    )
    paint_pdf(scene, c)
    paint_pdf(sheet_annotations(g, metadata, view, section), c)
    c.showPage()
    c.save()
    return out.getvalue()
