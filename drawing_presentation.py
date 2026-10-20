"""One immutable portrait drawing scene, serialized by both PDF and SVG.

Coordinates are paper points, Y up. Canonical +X becomes the upward handle.
Only straight handle segments may be omitted. Presentation defaults cannot
mutate PlateSpec, section_geometry, DXF, JSON or downstream machining data.
"""

from dataclasses import dataclass, replace
from html import escape
from math import sin, cos, tan, radians, pi, ceil, atan2
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from pathlib import Path
import reportlab
from drawing_standards import (
    BREAK_FROM_JUNCTION,
    MINIMUM_KEPT_TIP,
    HOLE_TIP_CLEARANCE,
    BREAK_GAP_POINTS,
    SCALE_DENOMINATORS,
    inch,
    dimension,
)

PAGE_SIZE = (612, 792)
THIN, MED, HEAVY = 0.35, 0.7, 1.25
CHAIN, HIDDEN = (12, 3, 2, 3), (4, 2)
for _name, _file in (("PlateSans", "Vera.ttf"), ("PlateSansBold", "VeraBd.ttf")):
    pdfmetrics.registerFont(
        TTFont(_name, str(Path(reportlab.__file__).parent / "fonts" / _file))
    )


@dataclass(frozen=True)
class Presentation:
    geometry: object
    denominator: int
    break_start: float | None
    break_end: float | None
    kept_tip: float

    @property
    def scale(self):
        return 72 / self.denominator

    @property
    def scale_label(self):
        return f"1:{self.denominator}"

    @property
    def cx(self):
        return max(198.0, 90 + self.geometry.radius * self.scale)

    @property
    def cy(self):
        return 291.6 + self.geometry.radius * self.scale

    @property
    def section_x(self):
        return max(399.6, self.cx + self.geometry.radius * self.scale + 90)

    @property
    def broken(self):
        return self.break_start is not None

    @property
    def removed_length(self):
        return (
            self.break_end - self.break_start - BREAK_GAP_POINTS / self.scale
            if self.broken
            else 0
        )

    def ordinate(self, u):
        if self.broken:
            if self.break_start + 1e-9 < u < self.break_end - 1e-9:
                raise ValueError("point lies inside omitted handle interval")
            if u >= self.break_end - 1e-9:
                u -= self.removed_length
        return self.cy + u * self.scale

    def point(self, p):
        u, v = p
        return self.cx - v * self.scale, self.ordinate(u)

    def section_point(self, z, u):
        return self.section_x + z * self.scale, self.ordinate(u)

    @property
    def tip_y(self):
        return self.ordinate(self.geometry.spec.centerline_to_handle_end)

    @property
    def break_ys(self):
        return (
            tuple(self.ordinate(u) for u in (self.break_start, self.break_end))
            if self.broken
            else ()
        )

    def visible_segments(self):
        for seg in self.geometry.segments:
            pieces = [seg]
            if self.broken and seg.kind == "line" and seg.start[1] == seg.end[1]:
                low, high = sorted((seg.start[0], seg.end[0]))
                if low < self.break_start < self.break_end < high:
                    a, b = (self.break_start, seg.start[1]), (
                        self.break_end,
                        seg.start[1],
                    )
                    pieces = (
                        [replace(seg, end=a), replace(seg, start=b)]
                        if seg.start[0] < seg.end[0]
                        else [replace(seg, end=b), replace(seg, start=a)]
                    )
            yield from pieces


def build_presentation(g):
    s = g.spec
    keep = max(
        MINIMUM_KEPT_TIP,
        (
            s.handle_hole_center_from_handle_end
            + s.handle_hole_diameter / 2
            + HOLE_TIP_CLEARANCE
            if s.handle_hole_enabled
            else 0
        ),
    )
    start, resume = g.join_x + BREAK_FROM_JUNCTION, s.centerline_to_handle_end - keep
    for denom in SCALE_DENOMINATORS:
        scale = 72 / denom
        if s.finished_od * scale > 290:
            continue
        full = (g.radius + s.centerline_to_handle_end) * scale
        if full <= 414.4:
            return Presentation(g, denom, None, None, keep)
        compressed = (g.radius + start + keep) * scale + BREAK_GAP_POINTS
        if resume > start + BREAK_GAP_POINTS / scale and compressed <= 414.4:
            return Presentation(g, denom, start, resume, keep)
    raise ValueError(
        "plate and retained handle features exceed ANSI A at approved scales"
    )


def presentation_section(spec):
    """Resolve the explicitly requested v6 drawing convention on a copy only.

    Preserve explicit historical conventions (including angle and face). Missing
    width is still incomplete. Canonical manufacturing status is untouched.
    """
    from section_geometry import build_section_geometry

    if not spec.chamfer or spec.chamfer_width is None:
        return build_section_geometry(spec)
    return build_section_geometry(
        replace(
            spec,
            chamfer_angle_degrees=spec.chamfer_angle_degrees or 45,
            chamfer_side=spec.chamfer_side or "downstream",
            flow_orientation=spec.flow_orientation or "left-to-right",
            chamfer_width_definition=spec.chamfer_width_definition
            or "radial-angle-from-face",
        )
    )


@dataclass(frozen=True)
class Element:
    kind: str
    data: tuple
    key: str = ""
    width: float = THIN
    dash: tuple = ()
    fill: bool = False


class Scene:
    def __init__(self):
        self.elements = []

    def line(self, a, b, width=THIN, dash=(), key=""):
        self.elements.append(Element("line", (a, b), key, width, dash))

    def path(self, commands, width=HEAVY, key="", fill=False):
        self.elements.append(Element("path", tuple(commands), key, width, (), fill))

    def circle(self, center, radius, width=HEAVY, dash=(), key=""):
        self.elements.append(Element("circle", (*center, radius), key, width, dash))

    def text(self, x, y, value, size=8, bold=False, anchor="l", key=""):
        self.elements.append(
            Element("text", (x, y, str(value), size, bold, anchor), key)
        )

    def arrow(self, tip, angle, length=7.5, half=2.4):
        x, y = tip
        bx, by = x - length * cos(angle), y - length * sin(angle)
        nx, ny = -sin(angle) * half, cos(angle) * half
        self.path(
            (("M", x, y), ("L", bx + nx, by + ny), ("L", bx - nx, by - ny), ("Z",)),
            width=0,
            fill=True,
        )

    def hdim(self, x1, x2, y, label, key=""):
        m = (x1 + x2) / 2
        gap = text_width(label) / 2 + 4
        if x2 - x1 > 2 * gap + 16:
            self.line((x1, y), (m - gap, y), key=key)
            self.line((m + gap, y), (x2, y))
            self.arrow((x1, y), pi)
            self.arrow((x2, y), 0)
            self.text(m, y - 3, label, anchor="c")
        else:
            self.line((x1 - 16, y), (x1, y), key=key)
            self.line((x2, y), (x2 + 16, y))
            self.arrow((x1, y), 0)
            self.arrow((x2, y), pi)
            self.text(x2 + 20, y - 3, label)

    def vdim(self, x, y1, y2, label, key=""):
        m = (y1 + y2) / 2
        self.line((x, y1), (x, m - 7), key=key)
        self.line((x, m + 7), (x, y2))
        self.arrow((x, y1), -pi / 2)
        self.arrow((x, y2), pi / 2)
        self.text(x, m - 3, label, anchor="c")

    def leader(self, tip, knee, lines, right=True, key=""):
        self.line(tip, knee, key=key)
        self.arrow(tip, atan2(tip[1] - knee[1], tip[0] - knee[0]))
        sx = knee[0] + (12 if right else -12)
        self.line(knee, (sx, knee[1]))
        tx = sx + 4 if right else sx - 4 - max(text_width(t) for t in lines)
        for i, value in enumerate(lines):
            self.text(tx, knee[1] - 3 - i * 11, value)

    def long_break(self, y, x1, x2, key):
        m = (x1 + x2) / 2
        z = min(5.5, max(2.5, (x2 - x1) / 4))
        points = (
            (x1 - 9, y),
            (m - 2 * z, y),
            (m - z, y + z),
            (m + z, y - z),
            (m + 2 * z, y),
            (x2 + 9, y),
        )
        self.path(
            [("M" if i == 0 else "L", *p) for i, p in enumerate(points)], THIN, key
        )

    def hatch(self, polygon, key):
        # Clip each 45-degree line analytically to a convex material polygon.
        # PDF and SVG receive identical finite segments, no independent clip masks.
        low = min(x - y for x, y in polygon)
        high = max(x - y for x, y in polygon)
        k = 4 * int(low // 4)
        while k <= high:
            intersections = []
            for a, b in zip(polygon, polygon[1:] + polygon[:1]):
                da, db = a[0] - a[1] - k, b[0] - b[1] - k
                if da * db < 0 or abs(da) < 1e-9:
                    t = da / (da - db) if abs(da - db) > 1e-9 else 0
                    intersections.append(
                        (a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1]))
                    )
            if len(intersections) >= 2:
                intersections.sort()
                self.line(intersections[0], intersections[-1], 0.25, key=key)
            k += 4


def text_width(value, size=8, bold=False):
    return pdfmetrics.stringWidth(
        str(value), "PlateSansBold" if bold else "PlateSans", size
    )


def arc_commands(seg, view):
    pieces = max(1, ceil(abs(seg.sweep_degrees) / 90))
    delta = radians(seg.sweep_degrees / pieces)
    angle = radians(seg.start_degrees)
    cx, cy = seg.center
    r = seg.radius
    commands = []
    for _ in range(pieces):
        end = angle + delta
        k = 4 / 3 * tan(delta / 4)
        a = (
            cx + r * (cos(angle) - k * sin(angle)),
            cy + r * (sin(angle) + k * cos(angle)),
        )
        b = (cx + r * (cos(end) + k * sin(end)), cy + r * (sin(end) - k * cos(end)))
        c = (cx + r * cos(end), cy + r * sin(end))
        commands.append(("C", *view.point(a), *view.point(b), *view.point(c)))
        angle = end
    return commands


def build_views(g, view=None):
    view = view or build_presentation(g)
    if view.geometry != g:
        raise ValueError("presentation does not match canonical geometry")
    s, scene = g.spec, Scene()
    sec = presentation_section(s)
    px, py, sx, scale = view.cx, view.cy, view.section_x, view.scale
    R, h, b, t = (
        g.radius * scale,
        g.half_handle_width * scale,
        s.finished_bore_diameter * scale / 2,
        s.thickness * scale,
    )
    top = view.tip_y
    # Canonical contour, including all four exact tangent corner arcs.
    commands, previous = [], None
    for seg in view.visible_segments():
        if seg.start != previous:
            commands.append(("M", *view.point(seg.start)))
        commands.extend(
            arc_commands(seg, view)
            if seg.kind == "arc"
            else [("L", *view.point(seg.end))]
        )
        previous = seg.end
    if not view.broken:
        commands.append(("Z",))
    scene.path(commands, key="plate-outline")
    scene.circle((px, py), b, key="bore")
    if sec.chamfer_drawn:
        scene.circle(
            (px, py),
            b + sec.chamfer_radial_width * scale,
            MED,
            HIDDEN,
            "chamfer-circle",
        )
    scene.line(
        (px - R - 10, py),
        (px + R + 10, py),
        dash=CHAIN,
        key="plan-horizontal-centerline",
    )
    if view.broken:
        y1, y2 = view.break_ys
        scene.line((px, py - R - 10), (px, y1 - 10), dash=CHAIN, key="plan-centerline")
        scene.line((px, y2 + 10), (px, top + 10), dash=CHAIN, key="plan-centerline")
        for i, y in enumerate(view.break_ys):
            scene.long_break(y, px - h, px + h, f"plan-break-{i}")
    else:
        scene.line((px, py - R - 10), (px, top + 10), dash=CHAIN, key="plan-centerline")
    for y, d in ((py - R - 14, -1), (top + 14, 1)):
        scene.line((px, y - d * 10), (px, y), HEAVY)
        scene.line((px, y), (px - 18, y), MED, key="cutting-plane")
        scene.arrow((px - 18, y), pi, 7, 2.6)
        scene.text(px - 31, y - 3.5, "A", 9, True)
    xL = px - R - 28
    scene.line((px - R - 12, py), (xL - 4, py))
    scene.line((px - h - 3, top), (xL - 4, top))
    scene.vdim(
        xL, py, top, dimension(s.centerline_to_handle_end, "length"), "handle-length"
    )
    for x in (px - h, px + h):
        scene.line((x, top + 3), (x, top + 38))
    scene.hdim(
        px - h, px + h, top + 34, dimension(s.handle_width, "width"), "handle-width"
    )
    for x in (px - R, px + R):
        scene.line((x, py - 3), (x, py - R - 36))
    scene.hdim(
        px - R,
        px + R,
        py - R - 32,
        "Ø" + dimension(s.finished_od, "od"),
        "od-dimension",
    )
    junction = view.point((g.join_x, -g.half_handle_width))
    scene.leader(
        junction,
        (junction[0] + 30, junction[1] + 26),
        ["R" + dimension(g.corner_radius, "radius") + "  4X"],
        key="radius-leader",
    )
    bore_label = "Ø" + dimension(s.finished_bore_diameter, "bore")
    if s.bore_tolerance is not None:
        bore_label += " ±" + inch(s.bore_tolerance)
    knee = (max(28 + text_width(bore_label) + 16, px - R + 10), py - R * 0.62)
    scene.leader(
        (px + b * cos(radians(215)), py + b * sin(radians(215))),
        knee,
        [bore_label],
        False,
        "bore-leader",
    )
    if s.handle_hole_enabled:
        hy = view.ordinate(
            s.centerline_to_handle_end - s.handle_hole_center_from_handle_end
        )
        hr = s.handle_hole_diameter * scale / 2
        scene.circle((px, hy), hr, key="handle-hole")
        scene.line((px - hr - 8, hy), (px + hr + 8, hy), dash=CHAIN)
        xr = px + h + 20
        scene.line((px + hr + 10, hy), (xr + 4, hy))
        scene.line((px + h + 3, top), (xr + 4, top))
        scene.vdim(
            xr,
            hy,
            top,
            dimension(s.handle_hole_center_from_handle_end, "hole_location"),
            "hole-location",
        )
        hole_label = "Ø" + dimension(s.handle_hole_diameter, "hole_diameter") + " THRU"
        # Small-scale/far-hole views leave less space between the handle and
        # length dimension. Move the callout right rather than crossing its text.
        left_start = px - h - 28 - text_width(hole_label)
        move_right = left_start < xL + 2
        scene.leader(
            (px + (1 if move_right else -1) * hr * .70710678, hy - hr * .70710678),
            (px + h + 34, hy - 26) if move_right else (px - h - 12, hy - 26),
            [hole_label], move_right, "hole-leader",
        )

    # Cut material polygons clipped around the longitudinal break and handle hole.
    def clip(poly, bound, lower):
        result = []
        for a, bp in zip(poly, poly[1:] + poly[:1]):
            ain = (a[1] >= bound) if lower else (a[1] <= bound)
            bin = (bp[1] >= bound) if lower else (bp[1] <= bound)
            if ain:
                result.append(a)
            if ain != bin:
                k = (bound - a[1]) / (bp[1] - a[1])
                result.append((a[0] + k * (bp[0] - a[0]), bound))
        return result

    for poly in sec.polygons:
        pieces = [poly]
        if view.broken:
            pieces = [
                clip(poly, view.break_start, False),
                clip(poly, view.break_end, True),
            ]
        for piece in pieces:
            if len(piece) >= 3:
                scene.hatch(
                    [view.section_point(z, u) for z, u in piece], "section-hatch"
                )
    for z in (0, s.thickness):
        spans = (
            (
                (-g.radius, view.break_start),
                (view.break_end, s.centerline_to_handle_end),
            )
            if view.broken
            else ((-g.radius, s.centerline_to_handle_end),)
        )
        for lo, hi in spans:
            scene.line(
                view.section_point(z, lo),
                view.section_point(z, hi),
                HEAVY,
                key="section-face",
            )
    for u in (-g.radius, s.centerline_to_handle_end):
        scene.line(
            view.section_point(0, u),
            view.section_point(s.thickness, u),
            HEAVY,
            key="section-end",
        )
    bore_radius = s.finished_bore_diameter / 2
    for sign in (-1, 1):
        z0, z1 = 0, s.thickness
        if sec.chamfer_drawn:
            if sec.face == "right":
                z1 = s.thickness - sec.chamfer_axial_depth
            else:
                z0 = sec.chamfer_axial_depth
        scene.line(
            view.section_point(z0, sign * bore_radius),
            view.section_point(z1, sign * bore_radius),
            HEAVY,
            key="bore-wall",
        )
        if sec.chamfer_drawn:
            zinner = z1 if sec.face == "right" else z0
            zface = s.thickness if sec.face == "right" else 0
            scene.line(
                view.section_point(zinner, sign * bore_radius),
                view.section_point(
                    zface, sign * (bore_radius + sec.chamfer_radial_width)
                ),
                HEAVY,
                key="chamfer-slope",
            )
    if sec.chamfer_drawn:
        scene.line(
            view.section_point(zinner, -bore_radius),
            view.section_point(zinner, bore_radius),
            MED,
            key="chamfer-bore-line",
        )
    if s.handle_hole_enabled:
        hc = s.centerline_to_handle_end - s.handle_hole_center_from_handle_end
        for u in (hc - s.handle_hole_diameter / 2, hc + s.handle_hole_diameter / 2):
            scene.line(
                view.section_point(0, u),
                view.section_point(s.thickness, u),
                HEAVY,
                key="hole-wall",
            )
        scene.line((sx - 10, hy), (sx + t + 10, hy), dash=CHAIN)
    for i, y in enumerate(view.break_ys):
        scene.long_break(y, sx, sx + t, f"section-break-{i}")
    scene.line((sx - 10, py), (sx + t + 10, py), dash=CHAIN)
    scene.text(sx + t / 2, py - R - 44, "SECTION A-A", 8, True, "c")
    for x in (sx, sx + t):
        scene.line((x, py - R - 3), (x, py - R - 26))
    scene.hdim(
        sx, sx + t, py - R - 22, dimension(s.thickness, "thickness"), "thickness"
    )
    if sec.chamfer_drawn:
        x1, x2 = sorted((sx + zinner * scale, sx + zface * scale))
        yc = py + 14
        for x in (x1, x2):
            scene.line((x, py + b * 0.2), (x, yc + 4))
        scene.line((x1 - 16, yc), (x1, yc))
        scene.line((x2, yc), (x2 + 16, yc))
        scene.arrow((x1, yc), 0)
        scene.arrow((x2, yc), pi)
        scene.text(
            x2 + 20,
            yc - 3,
            dimension(s.chamfer_width, "chamfer") + f" X {sec.angle_degrees:g}°",
        )
    elif s.chamfer:
        scene.text(sx + 20, py + 11, "CHAMFER SIZE REQUIRED", 6.5)
    yf = top - 14
    reverse = s.flow_orientation == "right-to-left"
    scene.line((sx - 44, yf), (sx - 10, yf), MED, key="flow")
    scene.arrow((sx - 44 if reverse else sx - 10, yf), pi if reverse else 0)
    scene.text(sx - 44, yf + 5, "FLOW", 6.5, True)
    if s.marking and s.marking != "No label":
        u = (
            (view.break_end + 0.45)
            if view.broken
            else s.centerline_to_handle_end * 0.65
        )
        mt = view.section_point(s.thickness if reverse else 0, u)
        scene.leader(
            mt, (sx - 34, mt[1] + 20), ["MARKING", "SEE NOTE 6"], False, "marking"
        )
    return scene, view, sec


def paint_pdf(scene, canvas):
    for e in scene.elements:
        canvas.setLineWidth(e.width)
        canvas.setDash(list(e.dash), 0)
        if e.kind == "line":
            canvas.line(*e.data[0], *e.data[1])
        elif e.kind == "circle":
            canvas.circle(*e.data, stroke=1, fill=0)
        elif e.kind == "path":
            path = canvas.beginPath()
            for command in e.data:
                op, *values = command
                {
                    "M": path.moveTo,
                    "L": path.lineTo,
                    "C": path.curveTo,
                    "Z": path.close,
                }[op](*values)
            canvas.drawPath(path, stroke=not e.fill, fill=e.fill)
        else:
            x, y, value, size, bold, anchor = e.data
            canvas.setFont("PlateSansBold" if bold else "PlateSans", size)
            {
                "l": canvas.drawString,
                "c": canvas.drawCentredString,
                "r": canvas.drawRightString,
            }[anchor](x, y, value)
    canvas.setDash()


def svg_scene(scene, view, description):
    # Bounds include text and arrow extents, with an independent caption below.
    bounds = []
    for e in scene.elements:
        if e.kind == "text":
            x, y, value, size, bold, anchor = e.data
            width = text_width(value, size, bold)
            x -= width / 2 if anchor == "c" else width if anchor == "r" else 0
            bounds.extend(((x, y - size * 0.25), (x + width, y + size)))
        elif e.kind == "circle":
            x, y, r = e.data
            bounds.extend(((x - r, y - r), (x + r, y + r)))
        elif e.kind == "line":
            bounds.extend(e.data)
        else:
            for command in e.data:
                bounds.extend(zip(command[1::2], command[2::2]))
    xmin, xmax = min(x for x, y in bounds) - 8, max(x for x, y in bounds) + 8
    ymin, ymax = min(y for x, y in bounds) - 8, max(y for x, y in bounds) + 8
    width = xmax - xmin
    caption = "Configuration preview — Not an approved manufacturing drawing."
    width = max(width, text_width(caption, 6.5) + 16)
    output = [
        f'<svg xmlns="http://www.w3.org/2000/svg" role="img" aria-label="Handled orifice plate configuration drawing" viewBox="{xmin:.6f} {-ymax:.6f} {width:.6f} {ymax-ymin+18:.6f}" data-scale="{view.scale_label}" style="width:100%;height:auto;display:block;background:#fff">',
        "<title>Handled orifice plate configuration drawing</title>",
        f"<desc>{escape(description)}</desc>",
    ]
    for i, e in enumerate(scene.elements):
        common = f' stroke="black" stroke-width="{e.width}" fill="{"black" if e.fill else "none"}"'
        if e.key:
            common += f' data-feature="{e.key}" id="{e.key}-{i}"'
        if e.dash:
            common += ' stroke-dasharray="' + " ".join(map(str, e.dash)) + '"'
        if e.kind == "line":
            a, b = e.data
            output.append(
                f'<line x1="{a[0]:.6f}" y1="{-a[1]:.6f}" x2="{b[0]:.6f}" y2="{-b[1]:.6f}"{common}/>'
            )
        elif e.kind == "circle":
            x, y, r = e.data
            output.append(f'<circle cx="{x:.6f}" cy="{-y:.6f}" r="{r:.6f}"{common}/>')
        elif e.kind == "path":
            d = []
            for command in e.data:
                op, *values = command
                d.append(
                    op
                    + " "
                    + " ".join(
                        f"{v if j%2==0 else -v:.6f}" for j, v in enumerate(values)
                    )
                )
            output.append(f'<path d="{" ".join(d)}"{common}/>')
        else:
            x, y, value, size, bold, anchor = e.data
            anchor_name = {"l": "start", "c": "middle", "r": "end"}[anchor]
            output.append(
                f'<text x="{x:.6f}" y="{-y:.6f}" font-family="DejaVu Sans,Arial,sans-serif" font-size="{size}" font-weight="{700 if bold else 400}" text-anchor="{anchor_name}">{escape(value)}</text>'
            )
    output.append(
        f'<text x="{xmin+width/2:.6f}" y="{-ymin+12:.6f}" text-anchor="middle" font-family="DejaVu Sans,Arial,sans-serif" font-size="6.5">{caption}</text></svg>'
    )
    return "\n".join(output)
