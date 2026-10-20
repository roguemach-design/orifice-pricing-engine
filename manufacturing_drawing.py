"""Original O-Plates Letter drawing template; deterministic ReportLab only.

Exact canonical geometry is consumed through an isolated NTS presentation map.
Display coordinates never supply manufacturing values or dimension labels.
"""

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
GENERATOR_VERSION = "op-drawing-v3e"
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


def text(c, x, y, value, size=8, bold=False):
    c.setFont("PlateSansBold" if bold else "PlateSans", size)
    c.drawString(x, y, str(value))


def fitted_text(c, x, y, value, width, size=8, bold=False):
    font = "PlateSansBold" if bold else "PlateSans"
    measured = pdfmetrics.stringWidth(str(value), font, size)
    if measured > width:
        size = max(6.5, size * width / measured)
    if pdfmetrics.stringWidth(str(value), font, size) > width:
        raise ValueError("drawing text exceeds its allocated field")
    text(c, x, y, value, size, bold)


def arrow(c, x, y, dx, dy):
    p = c.beginPath()
    p.moveTo(x, y)
    p.lineTo(x + dx * 5 - dy * 1.7, y + dy * 5 + dx * 1.7)
    p.lineTo(x + dx * 5 + dy * 1.7, y + dy * 5 - dx * 1.7)
    p.close()
    c.drawPath(p, fill=1)


def dim(c, x1, y1, x2, y2, label, vertical=False):
    c.setLineWidth(0.4)
    c.line(x1, y1, x2, y2)
    if vertical:
        if y2 - y1 < 15:
            c.line(x1, y1 - 8, x2, y2 + 8)
            arrow(c, x1, y1, 0, -1)
            arrow(c, x2, y2, 0, 1)
        else:
            arrow(c, x1, y1, 0, 1)
            arrow(c, x2, y2, 0, -1)
        c.saveState()
        c.translate(x1 - 8, (y1 + y2) / 2)
        c.rotate(90)
        c.setFont("PlateSans", 8)
        c.drawCentredString(0, 0, label)
        c.restoreState()
    else:
        arrow(c, x1, y1, 1, 0)
        arrow(c, x2, y2, -1, 0)
        c.setFont("PlateSans", 8)
        c.drawCentredString((x1 + x2) / 2, y1 + 7, label)


@dataclass(frozen=True)
class Presentation:
    """Points on paper only. Never used by the specification, DXF or JSON."""

    cx: float = 238
    cy: float = 488
    paddle_radius: float = 112
    handle_tip: float = 635
    bore_radius: float = 66
    section_center: float = 478
    section_thickness: float = 18

    def scale(self, g):
        return self.paddle_radius / g.radius

    def tip_offset(self, g):
        return (self.handle_tip - self.cy) / self.scale(
            g
        ) - g.spec.centerline_to_handle_end

    def point(self, g, point):
        x, y = point
        # Preserve the canonical paddle/neck arcs; translate the two tip arcs.
        # Only straight handle sides change display length.
        if x >= g.spec.centerline_to_handle_end - g.corner_radius:
            x += self.tip_offset(g)
        return self.cx - y * self.scale(g), self.cy + x * self.scale(g)


GOLDEN_PRESENTATION = Presentation()


def normalized_material(value):
    return {
        "304": "304 STAINLESS STEEL",
        "316": "316 STAINLESS STEEL",
        "Carbon Steel": "CARBON STEEL",
    }.get(value, value.upper())


def draw_plan(c, g, view=GOLDEN_PRESENTATION):
    s = g.spec
    scale = view.scale(g)
    cx, cy = view.cx, view.cy
    c.setLineWidth(1.15)
    for seg in g.segments:
        if seg.kind == "line":
            c.line(*view.point(g, seg.start), *view.point(g, seg.end))
        else:
            c.saveState()
            c.translate(cx, cy)
            c.rotate(90)
            c.scale(scale, scale)
            if seg.center[0] >= s.centerline_to_handle_end - g.corner_radius:
                c.translate(view.tip_offset(g), 0)
            c.setLineWidth(1.15 / scale)
            p = c.beginPath()
            p.moveTo(*seg.start)
            x, y = seg.center
            r = seg.radius
            p.arcTo(x - r, y - r, x + r, y + r, seg.start_degrees, seg.sweep_degrees)
            c.drawPath(p)
            c.restoreState()
    c.circle(cx, cy, view.bore_radius)
    if s.handle_hole_enabled:
        # NTS handle is shortened on paper; locate the hole relative to the physical tip.
        hy = view.handle_tip - s.handle_hole_center_from_handle_end * scale
        hr = s.handle_hole_diameter * scale / 2
        c.circle(cx, hy, hr)
        c.line(cx + hr, hy, cx + 65, hy + 30)
        text(c, cx + 65, hy + 33, f"HANDLE HOLE Ø{s.handle_hole_diameter:.4f}", 7, True)
        hx = cx + g.half_handle_width * scale + 24
        c.line(cx + hr + 3, hy, hx + 4, hy)
        c.line(cx + g.half_handle_width * scale + 3, view.handle_tip, hx + 4, view.handle_tip)
        dim(c, hx, hy, hx, view.handle_tip, f"{s.handle_hole_center_from_handle_end:.4f}", True)
        text(c, cx + 65, hy + 19, f"{s.handle_hole_center_from_handle_end:.4f} HANDLE END TO HOLE C/L", 6)
    c.setLineWidth(0.35)
    c.setDash([12, 3, 2, 3])
    c.line(cx - view.paddle_radius - 15, cy, view.section_center + 30, cy)
    c.line(cx, cy - view.paddle_radius - 15, cx, view.handle_tip + 15)
    c.setDash()
    # Section cutting-plane end arrows; A is a section identifier, not a datum.
    for yy in (cy - view.paddle_radius - 12, view.handle_tip + 14):
        c.setLineWidth(0.7)
        c.line(cx - 19, yy, cx, yy)
        arrow(c, cx, yy, -1, 0)
        text(c, cx - 29, yy - 3, "A", 8, True)
    left = cx - g.half_handle_width * scale
    right = cx + g.half_handle_width * scale
    for x in (left, right):
        c.line(x, view.handle_tip + 3, x, view.handle_tip + 34)
    dim(
        c,
        left,
        view.handle_tip + 27,
        right,
        view.handle_tip + 27,
        f"{s.handle_width:.3f}",
    )
    xdim = cx + view.paddle_radius + 24
    c.line(right + 3, view.handle_tip, xdim + 5, view.handle_tip)
    c.line(cx + 5, cy, xdim + 5, cy)
    dim(
        c,
        xdim,
        cy,
        xdim,
        view.handle_tip,
        f"{s.centerline_to_handle_end:.3f} C/L TO HANDLE END",
        True,
    )
    bottom = cy - view.paddle_radius
    bx, by = cx - view.bore_radius * 0.70710678, cy - view.bore_radius * 0.70710678
    c.line(bx, by, 124, bottom + 18)
    c.line(124, bottom + 18, 43, bottom + 18)
    arrow(c, bx, by, -0.70710678, -0.70710678)
    text(c, 43, bottom + 24, f"Ø{s.finished_bore_diameter:.3f}", 9, True)
    tol = f"+/- {s.bore_tolerance:g}" if s.bore_tolerance is not None else HOLD
    text(c, 43, bottom + 6, f"BORE TOLERANCE: {tol}", 6.5)
    ox, oy = cx + view.paddle_radius * 0.70710678, cy - view.paddle_radius * 0.70710678
    c.line(ox, oy, 333, bottom + 1)
    c.line(333, bottom + 1, 398, bottom + 1)
    arrow(c, ox, oy, 0.70710678, -0.70710678)
    text(c, 337, bottom + 6, f"Ø{s.finished_od:.3f}", 9)
    text(c, 146, bottom - 24, f"4X R {g.corner_radius:.5f}", 7)
    text(c, 226, bottom - 40, "PLAN - NTS", 6.5)
    text(c, 44, 649, "MARKING: " + ("HOLD" if s.marking is None else ""), 9, True)
    if s.marking is not None:
        fitted_text(c, 44, 637, s.marking, 138, 7)

    c.setLineWidth(0.4)
    marking_y = view.handle_tip - (60 if s.handle_hole_enabled else 14)
    c.line(142, 640, left + 10, marking_y)
    arrow(c, left + 10, marking_y, -0.8, 0.6)
    return cy, scale


def polygon(c, points):
    p = c.beginPath()
    p.moveTo(*points[0])
    for point in points[1:]:
        p.lineTo(*point)
    p.close()
    return p


def hatched_polygon(c, points):
    p = polygon(c, points)
    xmin = min(x for x, y in points)
    xmax = max(x for x, y in points)
    ymin = min(y for x, y in points)
    ymax = max(y for x, y in points)
    c.saveState()
    c.clipPath(p, stroke=0)
    c.setLineWidth(0.25)
    for y in range(int(ymin - (xmax - xmin)) - 5, int(ymax) + 6, 5):
        c.line(xmin, y, xmax, y + xmax - xmin)
    c.restoreState()
    c.setLineWidth(0.7)
    c.drawPath(p)


def section_presentation(g, section, view=GOLDEN_PRESENTATION):
    """Map exact polygon vertices into a readable NTS longitudinal section.

    Bore-adjacent bevels use the SAME local scale in x and y, preserving angle.
    Overall radial length and handle length are schematic, aligned with plan.
    """
    scale = view.section_thickness / g.spec.thickness
    if section.chamfer_drawn:
        scale = min(
            scale,
            0.8
            * (view.paddle_radius - view.bore_radius)
            / section.chamfer_radial_width,
        )
    x0 = view.section_center - g.spec.thickness * scale / 2

    def point(x, y):
        if g.spec.handle_hole_enabled:
            yy = view.cy + y * view.scale(g)
        elif y == g.spec.centerline_to_handle_end:
            yy = view.handle_tip
        elif y == -g.radius:
            yy = view.cy - view.paddle_radius
        else:
            sign = 1 if y > 0 else -1
            yy = view.cy + sign * (
                view.bore_radius + (abs(y) - section.bore_radius) * scale
            )
        return x0 + x * scale, yy

    return tuple(tuple(point(x, y) for x, y in poly) for poly in section.polygons)


def draw_section(c, g, section, cy, scale, view=GOLDEN_PRESENTATION):
    s = g.spec
    polys = section_presentation(g, section, view)
    for points in polys:
        hatched_polygon(c, points)
    text(c, 435, 662, "SECTION A-A - NTS", 7)
    text(c, 427, 649, "THROUGH HANDLE / BORE", 6)
    if s.flow_orientation is not None:
        reverse = s.flow_orientation == "right-to-left"
        c.setLineWidth(0.6)
        c.line(504, cy + 25, 558, cy + 25)
        arrow(c, 504 if reverse else 558, cy + 25, 1 if reverse else -1, 0)
        text(c, 510, cy + 32, "FLOW", 8, True)
    elif s.chamfer is True:
        text(c, 504, cy + 25, "FLOW: HOLD", 6.5)
    bottom = cy - view.paddle_radius
    x1 = min(x for p in polys for x, y in p)
    x2 = max(x for p in polys for x, y in p)
    for x in (x1, x2):
        c.line(x, bottom - 3, x, bottom - 31)
    c.line(x1 - 14, bottom - 23, x2 + 14, bottom - 23)
    arrow(c, x1, bottom - 23, -1, 0)
    arrow(c, x2, bottom - 23, 1, 0)
    text(c, x2 + 17, bottom - 26, f"t = {s.thickness:.3f}", 8)
    text(c, 420, bottom - 48, "CHAMFER: " + section.status, 6.5)
    if section.chamfer_drawn:
        # Detail locator B, kept distinct from cutting plane / section A-A.
        edge_y = view.cy + view.bore_radius
        c.setLineWidth(0.4)
        c.circle(view.section_center, edge_y, 13)
        c.line(
            view.section_center + 10, edge_y + 9, view.section_center + 28, edge_y + 24
        )
        text(c, view.section_center + 30, edge_y + 24, "B", 8, True)
        draw_chamfer_detail(c, g, section)
    else:
        if section.missing:
            names = {
                "chamfer_width": "SIZE",
                "chamfer_angle_degrees": "ANGLE",
                "chamfer_side": "SIDE",
                "flow_orientation": "FLOW",
                "chamfer_width_definition": "SIZE CONVENTION",
            }
            words = [names[x] for x in section.missing]
            text(c, 380, 295, "MISSING: " + ", ".join(words[:3]), 6.5)
            text(c, 380, 284, ", ".join(words[3:]), 6.5)
        if s.chamfer is True:
            fitted_text(
                c,
                380,
                270,
                f"width {s.chamfer_width}; angle {s.chamfer_angle_degrees}; side {s.chamfer_side}",
                185,
                6.5,
            )


def draw_chamfer_detail(c, g, section):
    # Uniform local enlargement preserves the exact angle; the crop is NTS.
    s = g.spec
    t = s.thickness
    w = section.chamfer_radial_width
    d = section.chamfer_axial_depth
    height = min(g.radius - section.bore_radius, max(w * 2, t * 0.65))
    scale = min(90 / t, 68 / height)
    x0 = 390
    y0 = 196
    if section.face == "right":
        pts = ((0, 0), (t - d, 0), (t, w), (t, height), (0, height))
        slope = ((t - d, 0), (t, w))
    else:
        pts = ((0, w), (d, 0), (t, 0), (t, height), (0, height))
        slope = ((0, w), (d, 0))
    points = [(x0 + x * scale, y0 + y * scale) for x, y in pts]
    hatched_polygon(c, points)
    text(c, 380, 294, "DETAIL B - BORE EDGE - NTS", 7, True)
    text(c, 380, 282, s.chamfer_side.upper() + " / ANGLE FROM FACE", 6.5)
    # Broken upper radial edge denotes a crop rather than a manufactured surface.
    top = y0 + height * scale
    c.setStrokeColorRGB(1, 1, 1)
    c.setLineWidth(2)
    c.line(x0, top, x0 + t * scale, top)
    c.setStrokeColorRGB(0, 0, 0)
    c.setLineWidth(0.4)
    mid = x0 + t * scale / 2
    c.lines(
        [
            (x0, top, mid - 5, top),
            (mid - 5, top, mid, top + 3),
            (mid, top + 3, mid + 5, top - 3),
            (mid + 5, top - 3, mid + 10, top),
            (mid + 10, top, x0 + t * scale, top),
        ]
    )
    # Exact radial and axial dimensions, plus the remaining cylindrical land.
    xdim = x0 + t * scale + 20
    for yy in (y0, y0 + w * scale):
        c.line(x0 + t * scale + 3, yy, xdim + 4, yy)
    dim(c, xdim, y0, xdim, y0 + w * scale, f"{w:.3f} RAD", True)
    for xx in (x0, x0 + t * scale):
        c.line(xx, y0 - 4, xx, 174)
    dim(c, x0, 178, x0 + t * scale, 178, f"t {t:.3f}")
    text(c, 380, 159, f"AXIAL DEPTH {d:.4f} / LAND {section.straight_land:.4f}", 6.8)
    sx = x0 + sum(p[0] for p in slope) * 0.5 * scale
    sy = y0 + w * 0.5 * scale
    c.line(sx, sy, 526, 270)
    c.line(526, 270, 553, 270)
    text(c, 528, 275, f"{section.angle_degrees:g}°", 8)


def draw_data(c, g, metadata, section):
    s = g.spec
    if not section.chamfer_drawn:
        fitted_text(
            c, 380, 250, "BORE FINISH: " + (metadata.bore_finish or "HOLD"), 185, 6.5
        )
    if section.chamfer_drawn:
        fitted_text(
            c, 70, 315, "BORE FINISH: " + (metadata.bore_finish or "HOLD"), 277, 6.5
        )
    rows = [
        ("NO. REQ'D.", str(s.quantity)),
        ("ORIFICE PLATE", f"{s.thickness:.3f} THK."),
        ("MATERIAL", normalized_material(s.material)),
    ]
    for label, value in [
        ("TAG", metadata.customer_tag),
        ("LINE / SERVICE", metadata.line_service),
        ("ORDER", metadata.order_identifier),
    ]:
        if value is not None:
            rows.append((label, value))
    for i, (label, value) in enumerate(rows):
        yy = 273 - i * 18
        text(c, 70, yy, label, 9)
        fitted_text(c, 170, yy, value, 177, 9)
        c.setLineWidth(0.4)
        c.line(166, yy - 3, 347, yy - 3)
    fitted_text(c, 44, 625, "METHOD: " + (metadata.marking_method or "HOLD"), 140, 6.5)
    fitted_text(
        c, 44, 614, "LOCATION: " + (metadata.marking_location or "HOLD"), 140, 6.5
    )
    fitted_text(
        c, 70, 163, "EDGE / FINISH: " + (metadata.edge_finish or "HOLD"), 280, 6.5
    )
    fitted_text(
        c, 70, 152, "SURFACE FINISH: " + (metadata.surface_finish or "HOLD"), 280, 6.5
    )
    fitted_text(c, 70, 141, "INSPECTION: " + (metadata.inspection or "HOLD"), 280, 6.5)


def draw_title(c, g, metadata):
    s = g.spec
    c.setLineWidth(0.5)
    c.rect(36, 24, 540, 112)
    c.line(36, 110, 576, 110)
    c.line(186, 24, 186, 110)
    for yy in (46, 66, 86):
        c.line(186, yy, 576, yy)
    c.line(360, 86, 360, 110)
    text(c, 43, 121, "ROGUE MACHINE / O-PLATES", 9, True)
    text(c, 390, 120, "ORIFICE PLATE", 12, True)
    text(c, 43, 99, "UNLESS OTHERWISE SPECIFIED:", 6.4)
    for yy, label, value in [
        (86, ".X", metadata.tolerance_x),
        (74, ".XX", metadata.tolerance_xx),
        (62, ".XXX", metadata.tolerance_xxx),
        (50, "ANGLES", metadata.tolerance_angles),
    ]:
        text(c, 43, yy, label, 7)
        fitted_text(c, 91, yy, value or "HOLD", 87, 7)
    text(c, 43, 34, "DO NOT SCALE DRAWING", 7, True)
    text(c, 193, 102, "PART NO.", 5.5)
    fitted_text(c, 193, 91, s.part_identifier, 160, 8)
    text(c, 367, 102, "DWG NO.", 5.5)
    fitted_text(c, 367, 91, "OP-" + s.part_identifier, 201, 8)
    text(c, 193, 79, "MATERIAL", 5.5)
    fitted_text(c, 193, 69, normalized_material(s.material), 230, 7)
    text(c, 437, 79, "THICKNESS", 5.5)
    text(c, 437, 69, f"{s.thickness:.3f}", 7)
    text(c, 523, 79, "QUANTITY", 5.5)
    text(c, 523, 69, str(s.quantity), 7)
    for x, label, value in [
        (193, "REV", metadata.revision),
        (265, "UNITS", "INCHES"),
        (326, "SCALE", "NTS"),
        (385, "SHEET", "1 OF 1"),
        (461, "DRAFTING BASIS", "ASME Y14.5-2018"),
    ]:
        text(c, x, 59, label, 5.3)
        text(c, x, 49, value, 7)
    text(c, 193, 37, "GEN: " + GENERATOR_VERSION, 5.5)
    fitted_text(
        c, 350, 37, "SPEC REV: " + (metadata.specification_revision or "HOLD"), 220, 5.5
    )
    text(c, 193, 27, "GEOMETRY: " + GEOMETRY_VERSION, 5.5)
    c.setFont("PlateSansBold", 7)
    c.drawCentredString(306, 12, STATUS_LABELS[metadata.state])
    if metadata.order_line_revision:
        text(c, 70, 177, "ORDER/LINE REV: " + metadata.order_line_revision, 6.5)


def render_pdf(
    g: PlateGeometry,
    metadata: DrawingMetadata | None = None,
    *,
    presentation: Presentation = GOLDEN_PRESENTATION,
):
    from dataclasses import replace
    from section_geometry import build_section_geometry

    metadata = metadata or DrawingMetadata()
    if metadata.state == DrawingState.RELEASED:
        raise ValueError(
            "manufacturing release is not implemented; prototype/confirmation only"
        )
    # Compatibility inputs are reconciled once into the spec; one section builder
    # drives both geometry and labels. Conflicting sources fail explicitly.
    updates = {}
    for field in ("flow_orientation", "chamfer_width_definition"):
        value = getattr(metadata, field)
        if value is not None:
            if getattr(g.spec, field) not in (None, value):
                raise ValueError("conflicting section metadata")
            updates[field] = value
    spec = replace(g.spec, **updates)
    section = build_section_geometry(spec)
    if updates:
        g = replace(g, spec=spec)
    out = BytesIO()
    c = canvas.Canvas(out, pagesize=PAGE_SIZE, invariant=1, pageCompression=1)
    c.setTitle(f"{spec.part_identifier} - prototype manufacturing drawing")
    c.setAuthor("O-Plates deterministic generator")
    c.setFont("PlateSans", 18)
    c.drawCentredString(306, 745, "ORIFICE PLATE")
    c.setLineWidth(0.8)
    c.line(76, 737, 536, 737)
    c.setFont("PlateSans", 7)
    c.drawCentredString(
        306,
        724,
        "APPLICATION: "
        + (
            "RESTRICTION / GENERAL"
            if spec.application == PlateApplication.RESTRICTION_GENERAL
            else "METERING - VALIDATION NOT IMPLEMENTED"
        ),
    )
    if spec.part_identifier.startswith("EXAMPLE-"):
        text(c, 140, 708, "ILLUSTRATIVE CHAMFER VALUES - NOT DEFAULTS", 7)
    if spec.handle_hole_enabled:
        # Fit the whole true-proportion plan in the existing NTS plan area.
        fit_scale = min(presentation.scale(g), (presentation.handle_tip - presentation.cy) / spec.centerline_to_handle_end)
        presentation = replace(presentation, paddle_radius=g.radius * fit_scale,
                               bore_radius=spec.finished_bore_diameter * fit_scale / 2,
                               handle_tip=presentation.cy + spec.centerline_to_handle_end * fit_scale)
    cy, scale = draw_plan(c, g, presentation)
    draw_section(c, g, section, cy, scale, presentation)
    draw_data(c, g, metadata, section)
    draw_title(c, g, metadata)
    c.showPage()
    c.save()
    return out.getvalue()
