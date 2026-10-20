"""Shared true-scale, right-facing presentation in ANSI A landscape points.

Only straight handle sides may be interrupted. Canonical arcs and all hole
features retain one uniform scale. No values flow back into manufacturing.
"""

from dataclasses import dataclass, replace
from plate_geometry import PlateGeometry, ContourSegment
from drawing_standards import SCALE_DENOMINATORS

PAGE_SIZE = (792, 612)
BREAK_FROM_JUNCTION = 0.45
MINIMUM_KEPT_TIP = 2.4
HOLE_TIP_CLEARANCE = 0.9
BREAK_GAP_POINTS = 0.30 * 72


@dataclass(frozen=True)
class SheetLayout:
    left: float = 60
    right: float = 620
    bottom: float = 270
    top: float = 558
    edge_x: float = 700


DEFAULT_LAYOUT = SheetLayout()


@dataclass(frozen=True)
class Presentation:
    geometry: PlateGeometry
    layout: SheetLayout
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
        return self.layout.left + self.geometry.radius * self.scale

    @property
    def cy(self):
        return (self.layout.top + self.layout.bottom) / 2

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

    def point(self, point):
        x, y = point
        if self.broken:
            if self.break_start + 1e-9 < x < self.break_end - 1e-9:
                raise ValueError("point lies inside omitted handle interval")
            if x >= self.break_end - 1e-9:
                x -= self.removed_length
        return self.cx + x * self.scale, self.cy + y * self.scale

    @property
    def tip_x(self):
        return self.point((self.geometry.spec.centerline_to_handle_end, 0))[0]

    @property
    def break_xs(self):
        return (
            tuple(self.point((x, 0))[0] for x in (self.break_start, self.break_end))
            if self.broken
            else ()
        )

    def visible_segments(self):
        """Clip straight sides, then map every surviving exact segment to paper."""
        for seg in self.geometry.segments:
            pieces = [seg]
            if self.broken and seg.kind == "line" and seg.start[1] == seg.end[1]:
                low, high = sorted((seg.start[0], seg.end[0]))
                if low < self.break_start < self.break_end < high:
                    a, b = (self.break_start, seg.start[1]), (
                        self.break_end,
                        seg.start[1],
                    )
                    if seg.start[0] < seg.end[0]:
                        pieces = [replace(seg, end=a), replace(seg, start=b)]
                    else:
                        pieces = [replace(seg, end=b), replace(seg, start=a)]
            for piece in pieces:
                yield replace(
                    piece,
                    start=self.point(piece.start),
                    end=self.point(piece.end),
                    center=self.point(piece.center) if piece.center else None,
                    radius=piece.radius * self.scale if piece.radius else None,
                )

    def long_break(self, x):
        half = self.geometry.half_handle_width * self.scale
        # Thin long-break convention, one zigzag, fixed paper overrun.
        z = min(5.5, (half + 8) / 3)
        y = self.cy
        return (
            (x, y - half - 10),
            (x, y - 2 * z),
            (x + z, y - z),
            (x - z, y + z),
            (x, y + 2 * z),
            (x, y + half + 10),
        )


def build_presentation(g, layout=DEFAULT_LAYOUT):
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
    start = g.join_x + BREAK_FROM_JUNCTION
    resume = s.centerline_to_handle_end - keep
    for denominator in SCALE_DENOMINATORS:
        scale = 72 / denominator
        if s.finished_od * scale > layout.top - layout.bottom + 1e-9:
            continue
        full_width = (g.radius + s.centerline_to_handle_end) * scale
        if full_width <= layout.right - layout.left + 1e-9:
            return Presentation(g, layout, denominator, None, None, keep)
        removed = resume - start - BREAK_GAP_POINTS / scale
        short_width = (g.radius + start + keep) * scale + BREAK_GAP_POINTS
        if removed > 0 and short_width <= layout.right - layout.left + 1e-9:
            return Presentation(g, layout, denominator, start, resume, keep)
    raise ValueError(
        "plate and retained handle features exceed ANSI A at approved scales"
    )
