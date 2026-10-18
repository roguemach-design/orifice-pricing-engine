"""Analytic packaging offsets. Sampling is inspection-only, never a cut contour."""

from dataclasses import replace, asdict
from math import acos, ceil, cos, sin, pi, hypot
from shapely.geometry import Polygon
from plate_geometry import build_plate_geometry, ContourSegment

INSPECTION_ERROR = 0.00001


def point(center, radius, degrees):
    a = degrees * pi / 180
    return (center[0] + radius * cos(a), center[1] + radius * sin(a))


def polygon(segments, error=INSPECTION_ERROR):
    points = []
    for s in segments:
        if s.kind == "line":
            points.append(s.start)
        else:
            step = 2 * acos(max(-1, 1 - error / s.radius))
            n = max(2, ceil(abs(s.sweep_degrees * pi / 180) / step))
            points.extend(
                point(s.center, s.radius, s.start_degrees + s.sweep_degrees * i / n)
                for i in range(n)
            )
    return Polygon(points)


def area(segments):
    result = 0.0
    for s in segments:
        result += (s.start[0] * s.end[1] - s.end[0] * s.start[1]) / 2
        if s.kind == "arc":
            angle = s.sweep_degrees * pi / 180
            result += s.radius * s.radius * (angle - sin(angle)) / 2
    return result


def transform(segments, xoff, yoff):
    def p(v):
        return (-v[1] + xoff, v[0] + yoff)

    return tuple(
        replace(
            s,
            start=p(s.start),
            end=p(s.end),
            center=p(s.center) if s.center else None,
            start_degrees=s.start_degrees + 90 if s.kind == "arc" else 0,
        )
        for s in segments
    )


def nest_contour(spec, config):
    g = build_plate_geometry(spec)
    k = config.kerf / 2
    offset = config.clearance - k
    # A concave offset radius vanishes at its evolute. Never fit guessed arcs
    # or change the canonical neck to conceal that topology change.
    if config.clearance >= g.corner_radius - 1e-9:
        raise ValueError(
            "nest clearance collapses canonical neck radius; require clearance below 0.03125 inch"
        )
    segments = []
    for s in g.segments:
        if s.kind == "arc":
            radius = s.radius + (offset if s.sweep_degrees > 0 else -offset)
            segments.append(
                replace(
                    s,
                    radius=radius,
                    start=point(s.center, radius, s.start_degrees),
                    end=point(s.center, radius, s.start_degrees + s.sweep_degrees),
                )
            )
        else:
            dx, dy = s.end[0] - s.start[0], s.end[1] - s.start[1]
            length = hypot(dx, dy)
            shift = (offset * dy / length, -offset * dx / length)
            segments.append(
                replace(
                    s,
                    start=tuple(a + b for a, b in zip(s.start, shift)),
                    end=tuple(a + b for a, b in zip(s.end, shift)),
                )
            )
    side = segments[6]  # canonical +Y long edge, traversed from tip toward paddle
    straight = side.start[0] - side.end[0]
    bridge = max(config.finger_min_bridge, 2 * config.caliper)
    # Radius includes kerf for conservative corner and inter-relief spacing.
    lateral = (
        spec.finished_od / 2
        + config.margin
        - config.closure_edge_distance
        - config.caliper
        - spec.handle_width / 2
        - config.clearance
        - 0.01
    )
    diameter = min(
        config.finger_diameter,
        spec.handle_width,
        (straight - 3 * bridge) / 2,
        2 * (lateral + k),
    )
    if diameter < config.finger_min_diameter - 1e-9:
        raise ValueError(
            "handle cannot safely accommodate two side finger reliefs with corner, transition and cardboard bridges"
        )
    radius = diameter / 2 - k
    if radius <= 0:
        raise ValueError("kerf consumes finger relief radius")
    centers = [
        side.start[0] - bridge - diameter / 2,
        side.end[0] + bridge + diameter / 2,
    ]
    inserted = []
    cursor = side.start
    for x in centers:
        start = (x + radius, side.start[1])
        end = (x - radius, side.start[1])
        inserted.extend(
            [
                ContourSegment("line", cursor, start),
                ContourSegment("arc", start, end, (x, side.start[1]), radius, 0, 180),
            ]
        )
        cursor = end
    inserted.append(ContourSegment("line", cursor, side.end))
    segments = tuple(segments[:6] + inserted + segments[7:])
    for a, b in zip(segments, segments[1:] + segments[:1]):
        if hypot(a.end[0] - b.start[0], a.end[1] - b.start[1]) > 1e-9:
            raise ValueError("analytic nest endpoint discontinuity")
    poly = polygon(segments)
    if (
        not poly.is_valid
        or not poly.exterior.is_simple
        or poly.interiors
        or area(segments) <= 0
    ):
        raise ValueError("analytic nest topology unsupported")
    return segments, dict(
        representation="closed LWPOLYLINE with exact circular bulges",
        canonical_side="+Y long handle edge",
        layout_side="LEFT (-X) after 90 degree rotation",
        cutter_center_offset=offset,
        finished_nominal_clearance=config.clearance,
        paddle_cutter_radius=g.radius + offset,
        neck_cutter_radius=g.corner_radius - offset,
        tip_cutter_radius=g.corner_radius + offset,
        finger_reliefs=[
            dict(
                position=label,
                center_plate_coordinates=[x, side.start[1]],
                cutter_radius=radius,
                cutter_diameter=2 * radius,
                sweep_degrees=180,
                kerf_envelope_circle_diameter=diameter,
            )
            for x, label in zip(centers, ["near tip", "near paddle"])
        ],
        minimum_bridge=bridge,
        nominal_relief_target_diameter=config.finger_diameter,
        actual_relief_envelope_diameter=diameter,
        kerf_note="Relief cutter-center semicircles use target radius minus half kerf; centers lie on the compensated long edge. Physical mouth intersections are kerf-rounded, not exact semicircles.",
        inspection_chord_error_bound=INSPECTION_ERROR,
        cut_contour_sampling_error=0.0,
        net_area_basis="Exact cutter-center contour area; physical removed board also includes kerf.",
        segments=[asdict(s) for s in segments],
    )


def svg_path(segments, x=0, y=0):
    first = segments[0].start
    parts = [f"M {first[0]+x:.10f} {first[1]+y:.10f}"]
    for s in segments:
        if s.kind == "line":
            parts.append(f"L {s.end[0]+x:.10f} {s.end[1]+y:.10f}")
        else:
            parts.append(
                f"A {s.radius:.10f} {s.radius:.10f} 0 {int(abs(s.sweep_degrees)>180)} {int(s.sweep_degrees>0)} {s.end[0]+x:.10f} {s.end[1]+y:.10f}"
            )
    return " ".join(parts) + " Z"
