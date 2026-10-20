"""Deterministic customer confirmation drawing from exact canonical geometry."""

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
GENERATOR_VERSION = "op-drawing-v4-true-scale"
from drawing_presentation import PAGE_SIZE, DEFAULT_LAYOUT, build_presentation
from drawing_standards import (
    inch,
    dimension,
    UOS_XX,
    UOS_XXX,
    UOS_ANGLES,
    BORE_POSITION_DIAMETER,
    EDGE_BREAK,
    FACE_FINISH,
)
from math import cos, sin, radians, hypot
import json
import re


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
            text(c, x1 + 8, (y1 + y2) / 2 - 3, label, 8)
            return
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


def draw_chamfer_detail(c, g, section):
    # Uniform local enlargement preserves the exact angle and crop geometry.
    s = g.spec
    t = s.thickness
    w = section.chamfer_radial_width
    d = section.chamfer_axial_depth
    height = min(g.radius - section.bore_radius, max(w * 2, t * 0.65))
    scale = min(90 / t, 68 / height)
    c.saveState()
    c.translate(110, 44)
    c.scale(0.70, 0.70)
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
    text(c, 380, 294, f"DETAIL B - BORE EDGE ({scale * .70 / 72:.2f}:1)", 7, True)
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
    dim(c, xdim, y0, xdim, y0 + w * scale, f"{inch(w)} RAD", True)
    for xx in (x0, x0 + t * scale):
        c.line(xx, y0 - 4, xx, 174)
    dim(c, x0, 178, x0 + t * scale, 178, f"t {inch(t)}")
    text(
        c,
        380,
        159,
        f"AXIAL DEPTH {inch(d, 4)} / LAND {inch(section.straight_land, 4)}",
        6.8,
    )
    sx = x0 + sum(p[0] for p in slope) * 0.5 * scale
    sy = y0 + w * 0.5 * scale
    c.line(sx, sy, 526, 270)
    c.line(526, 270, 553, 270)
    text(c, 528, 275, f"{section.angle_degrees:g}°", 8)
    # Preserve the explicit flow indication alongside the relocated detail.
    reverse = s.flow_orientation == "right-to-left"
    c.line(560, 230, 600, 230)
    arrow(c, 560 if reverse else 600, 230, 1 if reverse else -1, 0)
    text(c, 563, 240, "FLOW", 7)
    c.restoreState()


def normalized_material(value):
    return {
        "304": "304 STAINLESS STEEL",
        "316": "316 STAINLESS STEEL",
        "Carbon Steel": "CARBON STEEL",
    }.get(value, value.upper())


def leader(c, tip, knee, label, *, right=True, size=8):
    c.setLineWidth(0.4)
    c.line(*tip, *knee)
    dx, dy = knee[0] - tip[0], knee[1] - tip[1]
    length = hypot(dx, dy)
    arrow(c, *tip, dx / length, dy / length)
    end = knee[0] + (14 if right else -14)
    c.line(*knee, end, knee[1])
    width = pdfmetrics.stringWidth(label, "PlateSans", size)
    x = end + 4 if right else end - 4 - width
    text(c, x, knee[1] + 3, label, size)
    return x, knee[1], width


def datum(c, x, y, letter, *, left=False):
    c.setLineWidth(0.7)
    if left:
        c.drawPath(polygon(c, [(x, y), (x - 6, y - 3), (x - 6, y + 3)]), fill=1)
        c.line(x - 6, y, x - 20, y)
        bx, by = x - 32, y - 6
    else:
        c.drawPath(polygon(c, [(x, y), (x - 3, y - 6), (x + 3, y - 6)]), fill=1)
        c.line(x, y - 6, x, y - 16)
        bx, by = x - 6, y - 28
    c.rect(bx, by, 12, 12)
    text(c, bx + 3, by + 3, letter, 8, True)


def position_frame(c, x, y):
    c.setLineWidth(0.6)
    widths = (15, 38, 14, 14)
    start = x
    for width in widths:
        c.rect(x, y, width, 14)
        x += width
    cx, cy = start + 7.5, y + 7
    c.circle(cx, cy, 3)
    c.line(cx - 5, cy, cx + 5, cy)
    c.line(cx, cy - 5, cx, cy + 5)
    text(c, start + 19, y + 4, "Ø" + BORE_POSITION_DIAMETER, 8)
    text(c, start + 57, y + 4, "A", 8)
    text(c, start + 71, y + 4, "B", 8)


def draw_plan(c, g, view):
    s, scale = g.spec, view.scale
    cx, cy = view.cx, view.cy
    r, h, b = (
        g.radius * scale,
        g.half_handle_width * scale,
        s.finished_bore_diameter * scale / 2,
    )
    c.setLineWidth(1.15)
    for seg in view.visible_segments():
        if seg.kind == "line":
            c.line(*seg.start, *seg.end)
        else:
            p = c.beginPath()
            p.moveTo(*seg.start)
            x, y = seg.center
            p.arcTo(
                x - seg.radius,
                y - seg.radius,
                x + seg.radius,
                y + seg.radius,
                seg.start_degrees,
                seg.sweep_degrees,
            )
            c.drawPath(p)
    c.circle(cx, cy, b)
    for x in view.break_xs:
        points = view.long_break(x)
        p = c.beginPath()
        p.moveTo(*points[0])
        for pt in points[1:]:
            p.lineTo(*pt)
        c.setLineWidth(0.35)
        c.drawPath(p)
    c.setLineWidth(0.35)
    c.setDash([12, 3, 2, 3])
    if view.broken:
        x1, x2 = view.break_xs
        c.line(cx - r - 12, cy, x1 - 7, cy)
        c.line(x2 + 7, cy, view.tip_x + 12, cy)
    else:
        c.line(cx - r - 12, cy, view.tip_x + 12, cy)
    c.line(cx, cy - r - 12, cx, cy + r + 12)
    c.setDash()
    top = cy + r + 24
    c.line(cx, cy + r + 14, cx, top + 4)
    c.line(view.tip_x, cy + h + 3, view.tip_x, top + 4)
    # Continuous across both break lines; true value above the line.
    dim(c, cx, top, view.tip_x, top, dimension(s.centerline_to_handle_end, "length"))
    wx = view.tip_x + 28
    for y in (cy - h, cy + h):
        c.line(view.tip_x + 3, y, wx + 4, y)
    dim(c, wx, cy - h, wx, cy + h, dimension(s.handle_width, "width"), True)
    neck = view.point((g.join_x, g.half_handle_width))
    leader(
        c,
        neck,
        (neck[0] + 24, cy + r - 3),
        "R" + dimension(g.corner_radius, "radius") + "  4X",
    )
    a = radians(235)
    tip = (cx + r * cos(a), cy + r * sin(a))
    x, y, w = leader(
        c,
        tip,
        (
            max(
                tip[0] - 16,
                52
                + pdfmetrics.stringWidth(
                    "Ø" + dimension(s.finished_od, "od"), "PlateSans", 8
                ),
            ),
            cy - r - 16,
        ),
        "Ø" + dimension(s.finished_od, "od"),
        right=False,
    )
    datum(c, x + w / 2, y - 4, "B")
    a = radians(300)
    tip = (cx + b * cos(a), cy + b * sin(a))
    label = "Ø" + dimension(s.finished_bore_diameter, "bore")
    if s.bore_tolerance is not None:
        label += " ±" + inch(s.bore_tolerance)
    x, y, _ = leader(c, tip, (cx + max(b, 35) + 25, cy - r - 20), label)
    position_frame(c, x, y - 20)
    if s.handle_hole_enabled:
        hx, hy = view.point(
            (s.centerline_to_handle_end - s.handle_hole_center_from_handle_end, 0)
        )
        hr = s.handle_hole_diameter * scale / 2
        c.setLineWidth(1.15)
        c.circle(hx, hy, hr)
        c.setLineWidth(0.35)
        c.setDash([12, 3, 2, 3])
        c.line(hx, hy - hr - 8, hx, hy + hr + 8)
        c.setDash()
        yl = cy - h - 24
        c.line(hx, hy - hr - 8, hx, yl - 4)
        c.line(view.tip_x, cy - h - 3, view.tip_x, yl - 4)
        dim(
            c,
            hx,
            yl,
            view.tip_x,
            yl,
            dimension(s.handle_hole_center_from_handle_end, "hole_location"),
        )
        leader(
            c,
            (hx - hr * 0.5, hy + hr * 0.866),
            (hx + 18, cy + h + 28),
            "Ø" + dimension(s.handle_hole_diameter, "hole_diameter") + " THRU",
            right=True,
        )


def draw_edge(c, g, section, view):
    s = g.spec
    x, y = view.layout.edge_x, view.cy
    r = g.radius * view.scale
    t = s.thickness * view.scale
    c.setLineWidth(1.15)
    c.rect(x, y - r, t, 2 * r)
    c.setLineWidth(0.35)
    c.setDash([12, 3, 2, 3])
    c.line(x - 10, y, x + t + 10, y)
    c.setDash()
    datum(c, x, y + r * 0.6, "A", left=True)
    yd = y - r - 18
    for xx in (x, x + t):
        c.line(xx, y - r - 3, xx, yd - 4)
    c.line(x - 16, yd, x, yd)
    c.line(x + t, yd, x + t + 16, yd)
    arrow(c, x, yd, -1, 0)
    arrow(c, x + t, yd, 1, 0)
    text(c, x + t + 19, yd - 3, inch(s.thickness), 8)
    if section.chamfer_drawn:
        # Detail location on the projected bore edge; no section arrows on plan.
        ey = y + s.finished_bore_diameter * view.scale / 2
        c.circle(x + t / 2, ey, 11)
        c.line(x - 8, ey - 8, x - 24, ey - 24)
        text(c, x - 33, ey - 28, "B", 8, True)
        draw_chamfer_detail(c, g, section)


def short_identifier(value):
    value = re.sub(r"(?i)prototype", "SAMPLE", value)
    value = re.sub(
        r"(?i)(?<![a-z0-9])[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}",
        lambda m: m[0][:8].upper(),
        value,
    )
    return re.sub(r"(?i)[a-f0-9]{12,}", lambda m: m[0][:8].upper(), value)


def draw_notes(c, g, metadata, section):
    s = g.spec
    if section.chamfer_drawn:
        bore = "BORE CHAMFER: SEE DETAIL B. FREE OF BURRS."
    elif s.chamfer:
        bore = "BORE CHAMFER SPECIFIED; DETAIL INCOMPLETE."
    else:
        bore = "BORE EDGES SHARP, NO CHAMFER, FREE OF BURRS."
    marking = "NONE." if not s.marking or s.marking == "No label" else s.marking
    if s.marking and metadata.marking_method:
        marking += " / " + metadata.marking_method
    notes = [
        "INTERPRET DIMENSIONS AND TOLERANCES PER ASME Y14.5-2018.",
        "THICKNESS TOLERANCE PER MATERIAL MILL STANDARD.",
        bore,
        (
            ("EDGES: " + metadata.edge_finish)
            if metadata.edge_finish
            else "DEBURR ALL OTHER EDGES; BREAK SHARP EDGES " + EDGE_BREAK + "."
        ),
        "FACES: " + (metadata.surface_finish or FACE_FINISH) + ".",
        "MARKING: " + marking,
    ]
    if s.chamfer and not section.chamfer_drawn:
        supplied = []
        if s.chamfer_width is not None:
            supplied.append("SIZE " + inch(s.chamfer_width))
        if s.chamfer_angle_degrees is not None:
            supplied.append(f"ANGLE {s.chamfer_angle_degrees:g}°")
        if s.chamfer_side:
            supplied.append("SIDE " + s.chamfer_side.upper())
        if supplied:
            notes.append("CHAMFER INPUTS: " + " / ".join(supplied))
    for label, value in (
        ("INSPECTION", metadata.inspection),
        ("BORE FINISH", metadata.bore_finish),
        ("MARKING METHOD", metadata.marking_method),
        ("MARKING LOCATION", metadata.marking_location),
        ("UOS .X", metadata.tolerance_x),
    ):
        if value:
            notes.append(label + ": " + value)
    if metadata.customer_tag or metadata.line_service:
        notes.append(
            " / ".join(v for v in (metadata.customer_tag, metadata.line_service) if v)
        )
    text(c, 34, 196, "NOTES:", 8, True)
    for i, note in enumerate(notes, 1):
        fitted_text(c, 34, 196 - 12 * i, f"{i}. {short_identifier(note)}", 365, 7.2)


def draw_title(c, g, metadata, view):
    s = g.spec
    x, y, w = 404, 18, 370

    def cell(xx, yy, ww, hh, label, value, size=8, bold=False):
        c.setLineWidth(0.6)
        c.rect(xx, yy, ww, hh)
        text(c, xx + 3, yy + hh - 7.5, label, 5.3)
        if value:
            fitted_text(
                c, xx + 3, yy + 4, short_identifier(str(value)), ww - 6, size, bold
            )

    cell(x, 120, 150, 30, "", "ROGUE MACHINE / O-PLATES", 8, True)
    cell(x + 150, 120, 220, 30, "TITLE", "ORIFICE PLATE, HANDLED", 10, True)
    cell(x, 72, 150, 48, "UNLESS OTHERWISE SPECIFIED:", "")
    text(c, x + 4, 105, "DIMENSIONS IN INCHES", 6)
    text(
        c,
        x + 4,
        94,
        ".XX ±"
        + (metadata.tolerance_xx or UOS_XX)
        + "   .XXX ±"
        + (metadata.tolerance_xxx or UOS_XXX),
        6.5,
    )
    text(c, x + 4, 82, "ANGLES ±" + (metadata.tolerance_angles or UOS_ANGLES), 6.5)
    identifier = short_identifier(s.part_identifier)
    if not identifier.upper().startswith("OP-"):
        identifier = "OP-" + identifier
    cell(x + 150, 94, 170, 26, "DWG NO.", identifier, 9, True)
    cell(x + 320, 94, 50, 26, "REV", metadata.revision, 10, True)
    cell(x + 150, 72, 170, 22, "MATERIAL", normalized_material(s.material), 7.7)
    cell(x + 320, 72, 50, 22, "QTY", s.quantity, 9)
    cell(x, 50, 50, 22, "", "")
    sx, sy = x + 8, 56
    c.drawPath(
        polygon(c, [(sx, sy + 2), (sx + 14, sy), (sx + 14, sy + 10), (sx, sy + 8)])
    )
    c.circle(sx + 27, sy + 5, 5)
    c.circle(sx + 27, sy + 5, 2.2)
    cell(x + 50, 50, 100, 22, "", "DO NOT SCALE DRAWING", 6, True)
    cell(x + 150, 50, 40, 22, "SIZE", "A", 9)
    cell(x + 190, 50, 50, 22, "SCALE", view.scale_label, 9)
    cell(x + 240, 50, 130, 22, "SHEET", "1 OF 1", 9)
    cell(x, y, w, 32, "", "")
    fitted_text(
        c,
        x + 6,
        38,
        "CUSTOMER CONFIRMATION — NOT RELEASED FOR MANUFACTURE",
        w - 12,
        7,
        True,
    )
    trace = " · ".join(
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
    fitted_text(c, x + 6, 24, trace, w - 12, 5.3)


def render_pdf(
    g: PlateGeometry, metadata: DrawingMetadata | None = None, *, presentation=None
):
    from dataclasses import replace
    from section_geometry import build_section_geometry

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
    spec = replace(g.spec, **updates)
    section = build_section_geometry(spec)
    g = replace(g, spec=spec)
    view = presentation or build_presentation(g)
    if view.geometry != g:
        raise ValueError("presentation does not match canonical geometry")
    out = BytesIO()
    c = canvas.Canvas(out, pagesize=PAGE_SIZE, invariant=1, pageCompression=1)
    c.setTitle(
        short_identifier(spec.part_identifier) + " - customer confirmation drawing"
    )
    c.setAuthor("O-Plates deterministic generator")
    c.setSubject(
        json.dumps(
            {
                "geometry": GEOMETRY_VERSION,
                "generator": GENERATOR_VERSION,
                "state": metadata.state,
                "order": metadata.order_identifier,
                "part": spec.part_identifier,
            },
            sort_keys=True,
        )
    )
    c.setLineWidth(1.1)
    c.rect(18, 18, 756, 576)
    draw_plan(c, g, view)
    draw_edge(c, g, section, view)
    draw_notes(c, g, metadata, section)
    draw_title(c, g, metadata, view)
    c.showPage()
    c.save()
    return out.getvalue()
