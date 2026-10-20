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
    WEB_TEXT_SCALE, PRINT_TEXT_SCALE,
    WEB_ARROW_SCALE, PRINT_ARROW_SCALE,
    WEB_LINE_SCALE, PRINT_LINE_SCALE,
)
from material_labels import drawing_material_name

PAGE_SIZE = (612, 792)
THIN, MED, HEAVY = 0.35, 0.7, 1.25
CHAIN, HIDDEN = (12, 3, 2, 3), (4, 2)


@dataclass(frozen=True)
class DrawingProfile:
    name: str
    text: float
    arrow: float
    line: float


PRINT = DrawingProfile("print", PRINT_TEXT_SCALE, PRINT_ARROW_SCALE, PRINT_LINE_SCALE)
WEB = DrawingProfile("web", WEB_TEXT_SCALE, WEB_ARROW_SCALE, WEB_LINE_SCALE)
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
    profile: DrawingProfile = PRINT

    @property
    def scale(self):
        return 72 / self.denominator

    @property
    def scale_label(self):
        return f"1:{self.denominator}"

    @property
    def cx(self):
        return max(259.2 if self.profile == WEB else 205.2,
                   90 + self.geometry.radius * self.scale)

    @property
    def cy(self):
        return 309.6 + self.geometry.radius * self.scale

    @property
    def section_x(self):
        if self.profile == WEB:
            return self.cx + self.geometry.radius * self.scale + 1.35 * 72
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


def build_presentation(g, profile=PRINT):
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
            return Presentation(g, denom, None, None, keep, profile)
        compressed = (g.radius + start + keep) * scale + BREAK_GAP_POINTS
        if resume > start + BREAK_GAP_POINTS / scale and compressed <= 414.4:
            return Presentation(g, denom, start, resume, keep, profile)
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
    def __init__(self, profile=PRINT):
        self.elements = []
        self.profile = profile

    def line(self, a, b, width=THIN, dash=(), key=""):
        self.elements.append(Element("line", (a, b), key, width * self.profile.line, dash))

    def path(self, commands, width=HEAVY, key="", fill=False):
        self.elements.append(Element("path", tuple(commands), key, width * self.profile.line, (), fill))

    def circle(self, center, radius, width=HEAVY, dash=(), key=""):
        self.elements.append(Element("circle", (*center, radius), key, width * self.profile.line, dash))

    def text(self, x, y, value, size=8, bold=False, anchor="l", key=""):
        self.elements.append(
            Element("text", (x, y, str(value), size * self.profile.text, bold, anchor), key)
        )

    def arrow(self, tip, angle, length=7.5, half=2.4):
        length *= self.profile.arrow
        half *= self.profile.arrow
        x, y = tip
        bx, by = x - length * cos(angle), y - length * sin(angle)
        nx, ny = -sin(angle) * half, cos(angle) * half
        self.path(
            (("M", x, y), ("L", bx + nx, by + ny), ("L", bx - nx, by - ny), ("Z",)),
            width=0,
            fill=True,
        )

    def hdim(self, x1, x2, y, label, key=""):
        fs, arrow = self.profile.text, self.profile.arrow
        m = (x1 + x2) / 2
        gap = text_width(label, 8 * fs) / 2 + 4
        if x2 - x1 > 2 * gap + 16 * arrow:
            self.line((x1, y), (m - gap, y), key=key)
            self.line((m + gap, y), (x2, y))
            self.arrow((x1, y), pi)
            self.arrow((x2, y), 0)
            self.text(m, y - 3 * fs, label, anchor="c", key=key + "-label")
        else:
            self.line((x1 - 16 * arrow, y), (x1, y), key=key)
            self.line((x2, y), (x2 + 16 * arrow, y))
            self.arrow((x1, y), 0)
            self.arrow((x2, y), pi)
            self.text(x2 + 16 * arrow + 4, y - 3 * fs, label, key=key + "-label")

    def vdim(self, x, y1, y2, label, key=""):
        m = (y1 + y2) / 2
        fs = self.profile.text
        self.line((x, y1), (x, m - 6.5 * fs), key=key)
        self.line((x, m + 6.5 * fs), (x, y2))
        self.arrow((x, y1), -pi / 2)
        self.arrow((x, y2), pi / 2)
        self.text(x, m - 3 * fs, label, anchor="c", key=key + "-label")

    def leader(self, tip, knee, lines, right=True, key=""):
        fs = self.profile.text
        self.line(tip, knee, key=key)
        self.arrow(tip, atan2(tip[1] - knee[1], tip[0] - knee[0]))
        sx = knee[0] + (12 if right else -12)
        self.line(knee, (sx, knee[1]))
        tx = sx + 4 if right else sx - 4 - max(text_width(t, 8 * fs) for t in lines)
        for i, value in enumerate(lines):
            self.text(tx, knee[1] - 3 * fs - i * 11 * fs, value, key=key + "-label")

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

    def hatch(self, polygon, key, origin=(0, 0)):
        # Clip each 45-degree line analytically to a convex material polygon.
        # PDF and SVG receive identical finite segments, no independent clip masks.
        # Anchor the hatch phase to the part, not the profile's page placement.
        polygon = [(x - origin[0], y - origin[1]) for x, y in polygon]
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
                self.line(*(tuple(v + offset for v, offset in zip(p, origin))
                            for p in (intersections[0], intersections[-1])), 0.25, key=key)
            k += 4


def text_width(value, size=8, bold=False):
    return pdfmetrics.stringWidth(
        str(value), "PlateSansBold" if bold else "PlateSans", size
    )


def text_box(element):
    x, y, value, size, bold, anchor = element.data
    width = text_width(value, size, bold)
    x -= width / 2 if anchor == "c" else width if anchor == "r" else 0
    return x, y - size * .25, x + width, y + size


def place_web_leader(scene, view, tip, knee, lines, right, key):
    """Keep enlarged labels clear without changing geometry or true dimensions.

    Prefer the reference position. Only annotation knees move when small/large
    parts leave insufficient room. The bounds are deliberately conservative.
    """
    fs = scene.profile.text
    width = max(text_width(t, 8 * fs) for t in lines)
    px, py, radius = view.cx, view.cy, view.geometry.radius * view.scale
    half = view.geometry.half_handle_width * view.scale
    sx, thickness = view.section_x, view.geometry.spec.thickness * view.scale

    def overlap(a, b):
        return a[0] <= b[2] + 2 and a[2] >= b[0] - 2 and a[1] <= b[3] + 2 and a[3] >= b[1] - 2

    occupied = [text_box(e) for e in scene.elements if e.kind == "text"]

    def clear(rect):
        nearest_x = min(max(px, rect[0]), rect[2])
        nearest_y = min(max(py, rect[1]), rect[3])
        if (nearest_x - px) ** 2 + (nearest_y - py) ** 2 <= (radius + 2) ** 2:
            return False
        if overlap(rect, (px - half, view.ordinate(view.geometry.join_x), px + half, view.tip_y)):
            return False
        if overlap(rect, (sx, py - radius, sx + thickness, view.tip_y)):
            return False
        return not any(overlap(rect, other) for other in occupied)

    preferred_x = min(knee[0], sx - width - 24) if right else knee[0]
    placements = [(preferred_x, right), (knee[0], right),
                  (sx + thickness + 8, True), (px - radius - 8, False)]
    for x, direction in placements:
        for n in (0, *[sign * i for i in range(1, 21) for sign in (1, -1)]):
            y = knee[1] + n * 13 * fs
            left = x + 16 if direction else x - 16 - width
            rect = (left, y - (5 + 11 * (len(lines) - 1)) * fs,
                    left + width, y + 5 * fs)
            if clear(rect):
                scene.leader(tip, (x, y), lines, direction, key)
                return
    raise ValueError("drawing annotation cannot fit without a collision")


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


def build_views(g, view=None, *, profile=PRINT):
    view = view or build_presentation(g, profile)
    if view.geometry != g:
        raise ValueError("presentation does not match canonical geometry")
    s, scene = g.spec, Scene(view.profile)
    fs, arrow = view.profile.text, view.profile.arrow
    leaders = []
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
    for y, d in ((py - R - 14 * fs / PRINT_TEXT_SCALE, -1),
                 (top + 14 * fs / PRINT_TEXT_SCALE, 1)):
        scene.line((px, y - d * 10), (px, y), HEAVY)
        scene.line((px, y), (px - 18 * arrow, y), MED, key="cutting-plane")
        scene.arrow((px - 18 * arrow, y), pi, 7, 2.6)
        scene.text(px - 18 * arrow - 4, y - 3.5 * fs, "A", 9, True, "r")
    length_label = dimension(s.centerline_to_handle_end, "length")
    xL = px - R - max(28, text_width(length_label, 8 * fs) / 2 + 8)
    scene.line((px - R - 12, py), (xL - 4, py))
    scene.line((px - h - 3, top), (xL - 4, top))
    scene.vdim(
        xL, py, top, length_label, "handle-length"
    )
    for x in (px - h, px + h):
        scene.line((x, top + 3), (x, top + 30 * fs + 4))
    scene.hdim(
        px - h, px + h, top + 30 * fs, dimension(s.handle_width, "width"), "handle-width"
    )
    for x in (px - R, px + R):
        scene.line((x, py - 3), (x, py - R - 26 * fs - 4))
    scene.hdim(
        px - R,
        px + R,
        py - R - 26 * fs,
        "Ø" + dimension(s.finished_od, "od"),
        "od-dimension",
    )
    junction = view.point((g.join_x, -g.half_handle_width))
    leaders.append((
        junction,
        (junction[0] + 30, junction[1] + 26),
        ["R" + dimension(g.corner_radius, "radius") + "  4X"],
        True, "radius-leader",
    ))
    bore_label = "Ø" + dimension(s.finished_bore_diameter, "bore")
    if s.bore_tolerance is not None:
        bore_label += " ±" + inch(s.bore_tolerance)
    knee = (px - R + 10 if view.profile == WEB else
            max(28 + text_width(bore_label, 8 * fs) + 16, px - R + 10), py - R * 0.62)
    leaders.append((
        (px + b * cos(radians(215)), py + b * sin(radians(215))),
        knee,
        [bore_label],
        False,
        "bore-leader",
    ))
    if s.handle_hole_enabled:
        hy = view.ordinate(
            s.centerline_to_handle_end - s.handle_hole_center_from_handle_end
        )
        hr = s.handle_hole_diameter * scale / 2
        scene.circle((px, hy), hr, key="handle-hole")
        scene.line((px - hr - 8, hy), (px + hr + 8, hy), dash=CHAIN)
        location_label = dimension(s.handle_hole_center_from_handle_end, "hole_location")
        xr = px + h + max(20, text_width(location_label, 8 * fs) / 2 + 6)
        scene.line((px + hr + 10, hy), (xr + 4, hy))
        scene.line((px + h + 3, top), (xr + 4, top))
        scene.vdim(
            xr,
            hy,
            top,
            location_label,
            "hole-location",
        )
        hole_label = "Ø" + dimension(s.handle_hole_diameter, "hole_diameter") + " THRU"
        # Small-scale/far-hole views leave less space between the handle and
        # length dimension. Move the callout right rather than crossing its text.
        left_start = px - h - 28 - text_width(hole_label, 8 * fs)
        move_right = view.profile != WEB and left_start < 28
        leaders.append((
            (px + (1 if move_right else -1) * hr * .70710678, hy - hr * .70710678),
            (px + h + 34, hy - 26) if move_right else (px - h - 12, hy - 26),
            [hole_label], move_right, "hole-leader",
        ))

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
                    [view.section_point(z, u) for z, u in piece], "section-hatch", (sx, py)
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
    scene.text(sx + t / 2, py - R - 40 * fs, "SECTION A-A", 8, True, "c")
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
        scene.line((x1 - 16 * arrow, yc), (x1, yc))
        scene.line((x2, yc), (x2 + 16 * arrow, yc))
        scene.arrow((x1, yc), 0)
        scene.arrow((x2, yc), pi)
        scene.text(
            x2 + 16 * arrow + 4,
            yc - 3 * fs,
            dimension(s.chamfer_width, "chamfer") + f" X {sec.angle_degrees:g}°",
        )
    elif s.chamfer:
        scene.text(sx + 20, py + 11, "CHAMFER SIZE REQUIRED", 6.5)
    yf = top - 14
    reverse = s.flow_orientation == "right-to-left"
    flow_start = sx - 34 * arrow - 8
    scene.line((flow_start, yf), (sx - 8, yf), MED, key="flow")
    scene.arrow((flow_start if reverse else sx - 8, yf), pi if reverse else 0)
    scene.text(flow_start, yf + 4 * fs, "FLOW", 6.5, True)
    if s.marking and s.marking != "No label":
        u = (
            (view.break_end + 0.45)
            if view.broken
            else (g.join_x + s.centerline_to_handle_end) / 2
        )
        mt = (px + h * .35, view.ordinate(u))
        leaders.append((
            mt, (px + h + (18 if view.profile == WEB else 22),
                 mt[1] + (16 if view.profile == WEB else -18)),
            ["MARKING"] if view.profile == WEB else ["MARKING", "SEE NOTE 6"],
            True, "marking"
        ))
    for tip, knee, lines, right, key in leaders:
        if view.profile == WEB:
            place_web_leader(scene, view, tip, knee, lines, right, key)
        else:
            scene.leader(tip, knee, lines, right, key)
    return scene, view, sec


def fit_web_cell_text(value, width, size, *, quoted=False):
    """Fit display text at its specified size; canonical marking limits stay intact."""
    available = width - 8
    if text_width(value, size * WEB.text) <= available:
        return value
    original = value[1:-1] if quoted else value
    for n in range(len(original), -1, -1):
        shortened = original[:n] + "…"
        if quoted:
            shortened = '"' + shortened + '"'
        if text_width(shortened, size * WEB.text) <= available:
            return shortened
    return "…"


def web_title_block(scene, view):
    """Live presentation fields; canonical spec and commercial values are read only."""
    s, fs = view.geometry.spec, scene.profile.text
    x0 = view.cx - view.geometry.radius * view.scale - 1.45 * 72
    x1 = view.section_x + s.thickness * view.scale + 1.55 * 72
    width = max(x1 - x0, 530)
    x0 -= (width - (x1 - x0)) / 2
    top = view.cy - view.geometry.radius * view.scale - 50 * fs
    heights = (20 * fs, 19 * fs, 13 * fs)

    def box(x, y, w, h):
        scene.path((("M", x, y), ("L", x + w, y),
                    ("L", x + w, y - h), ("L", x, y - h), ("Z",)), MED)

    def cell(x, y, w, h, label="", value="", size=6.6, bold=False):
        box(x, y, w, h)
        if label:
            scene.text(x + 3, y - 4.6 * fs, label, 3.9)
        if value:
            scene.text(x + 3, y - h + 3.2 * fs,
                       fit_web_cell_text(value, w, size, quoted=label == "MARKING" and value != "NONE"),
                       size, bold, key="web-" + label.lower())

    left = width * .36
    cell(x0, top, left, heights[0])
    scene.text(x0 + 4, top - 8.5 * fs, "ROGUE MACHINE LLC", 6.3, True)
    scene.text(x0 + 4, top - 16 * fs, "O-PLATES · YORKVILLE, OH", 4.3)
    cell(x0 + left, top, width - left, heights[0], "TITLE", "ORIFICE PLATE, HANDLED", 7.6, True)
    y, x = top - heights[0], x0
    marking = '"' + s.marking + '"' if s.marking and s.marking != "No label" else "NONE"
    for label, value, fraction in (
        ("MATERIAL", drawing_material_name(s.material), .42),
        ("THICKNESS", dimension(s.thickness, "thickness") + " IN", .19),
        ("MARKING", marking, .25),
        ("SCALE", view.scale_label, .14),
    ):
        cell(x, y, width * fraction, heights[1], label, value,
             6.1 if label == "MATERIAL" else 6.6)
        x += width * fraction
    y -= heights[1]
    cell(x0, y, width, heights[2])
    scene.text(x0 + width / 2, y - heights[2] + 3.6 * fs,
               "CONFIGURATION PREVIEW — NOT AN APPROVED MANUFACTURING DRAWING",
               4.4, True, "c", key="web-status")


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


def scene_bounds(scene):
    """Paper-coordinate bounds including horizontal text and arrow extents."""
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
    return (min(x for x, y in bounds), min(y for x, y in bounds),
            max(x for x, y in bounds), max(y for x, y in bounds))


def svg_scene(scene, view, description):
    xmin, ymin, xmax, ymax = scene_bounds(scene)
    xmin, ymin, xmax, ymax = xmin - 8, ymin - 8, xmax + 8, ymax + 8
    width = xmax - xmin
    output = [
        f'<svg xmlns="http://www.w3.org/2000/svg" role="img" aria-label="Handled orifice plate configuration drawing" viewBox="{xmin:.6f} {-ymax:.6f} {width:.6f} {ymax-ymin:.6f}" data-scale="{view.scale_label}" data-profile="{view.profile.name}" style="width:100%;height:auto;display:block;background:#fff">',
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
            feature = f' data-feature="{e.key}"' if e.key else ""
            output.append(
                f'<text x="{x:.6f}" y="{-y:.6f}" font-family="DejaVu Sans,Arial,sans-serif" font-size="{size}" font-weight="{700 if bold else 400}" text-anchor="{anchor_name}" textLength="{text_width(value, size, bold):.6f}" lengthAdjust="spacingAndGlyphs"{feature}>{escape(value)}</text>'
            )
    output.append("</svg>")
    return "\n".join(output)
