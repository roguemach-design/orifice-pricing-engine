"""Responsive configuration image using the same paper geometry as the PDF."""

from html import escape
from drawing_presentation import build_presentation, PAGE_SIZE
from drawing_standards import inch, dimension
from plate_geometry import PlateSpec, build_plate_geometry


def _path(chains, close=False):
    parts = []
    for chain in chains:
        parts.append(f"M {chain[0].start[0]:.6f},{chain[0].start[1]:.6f}")
        for seg in chain:
            x, y = seg.end
            if seg.kind == "line":
                parts.append(f"L {x:.6f},{y:.6f}")
            else:
                parts.append(
                    f"A {seg.radius:.6f},{seg.radius:.6f} 0 {int(abs(seg.sweep_degrees)>180)} {int(seg.sweep_degrees>0)} {x:.6f},{y:.6f}"
                )
        if close:
            parts.append("Z")
    return " ".join(parts)


def render_plate_svg(
    *,
    paddle_dia,
    bore_dia,
    handle_width,
    handle_length_from_bore,
    thickness,
    material,
    bore_tolerance=None,
    handle_label="No label",
    chamfer=False,
    chamfer_width=None,
    handle_hole_enabled=False,
    handle_hole_diameter=None,
    handle_hole_center_from_handle_end=None,
    units="in.",
):
    # Raw customer strings remain escaped display text; geometry uses numeric fields.
    spec = PlateSpec(
        finished_od=float(paddle_dia),
        finished_bore_diameter=float(bore_dia),
        handle_width=float(handle_width),
        centerline_to_handle_end=float(handle_length_from_bore),
        thickness=float(thickness),
        material="preview",
        handle_hole_enabled=handle_hole_enabled,
        handle_hole_diameter=handle_hole_diameter,
        handle_hole_center_from_handle_end=handle_hole_center_from_handle_end,
    )
    g = build_plate_geometry(spec)
    v = build_presentation(g)
    chains = []
    for seg in v.visible_segments():
        if not chains or chains[-1][-1].end != seg.start:
            chains.append([])
        chains[-1].append(seg)
    if len(chains) > 1 and chains[-1][-1].end == chains[0][0].start:
        chains[0] = chains.pop() + chains[0]
    cx, cy, r, h = v.cx, v.cy, g.radius * v.scale, g.half_handle_width * v.scale
    b = spec.finished_bore_diameter * v.scale / 2
    parts = [
        f"""<svg viewBox="0 0 792 612" role="img" xmlns="http://www.w3.org/2000/svg"
 aria-label="Handled orifice plate configuration drawing" data-scale="{v.scale_label}"
 style="width:100%;height:auto;display:block;background:#ffffff">
 <title>Handled orifice plate configuration drawing</title>
 <desc>True-proportion preview at sheet scale {v.scale_label}. Long handles use a broken view; dimension values are actual inches.</desc>
 <defs><marker id="drawing-arrow" markerWidth="7" markerHeight="7" refX="3.5" refY="3.5" orient="auto-start-reverse"><path d="M0,0 L7,3.5 L0,7 z" fill="#1d4f7a"/></marker></defs>
 <rect x="18" y="18" width="756" height="576" fill="white" stroke="#172033"/>
 <g id="geometry" transform="translate(0 612) scale(1 -1)" fill="none" stroke="#172033" stroke-width="1.15">
 <path d="{_path(chains,True)}" fill="#f8fafc" stroke="none"/>
 <path id="plate-outline" d="{_path(chains)}"/>
 <circle id="bore" cx="{cx:.6f}" cy="{cy:.6f}" r="{b:.6f}" fill="white"/>
 <rect id="edge-view" x="{v.layout.edge_x}" y="{cy-r}" width="{spec.thickness*v.scale}" height="{2*r}" fill="#f8fafc"/>
"""
    ]
    for x in v.break_xs:
        points = " ".join(f"{xx:.6f},{yy:.6f}" for xx, yy in v.long_break(x))
        parts.append(
            f'<polyline class="long-break" points="{points}" stroke-width=".35"/>'
        )

    def line(x1, y1, x2, y2, cls="", dash=False, arrows=False):
        parts.append(
            f'<line class="{cls}" x1="{x1:.6f}" y1="{y1:.6f}" x2="{x2:.6f}" y2="{y2:.6f}" stroke="#637386" stroke-width=".5"'
            + (' stroke-dasharray="12 3 2 3"' if dash else "")
            + (
                ' marker-start="url(#drawing-arrow)" marker-end="url(#drawing-arrow)"'
                if arrows
                else ""
            )
            + "/>"
        )

    if v.broken:
        x1, x2 = v.break_xs
        line(cx - r - 12, cy, x1 - 7, cy, "centerline", True)
        line(x2 + 7, cy, v.tip_x + 12, cy, "centerline", True)
    else:
        line(cx - r - 12, cy, v.tip_x + 12, cy, "centerline", True)
    line(cx, cy - r - 12, cx, cy + r + 12, "centerline", True)
    top = cy + r + 24
    line(cx, top, v.tip_x, top, "handle-length", arrows=True)
    line(cx, cy + r + 14, cx, top + 4)
    line(v.tip_x, cy + h + 3, v.tip_x, top + 4)
    line(v.tip_x + 28, cy - h, v.tip_x + 28, cy + h, "handle-width", arrows=True)
    for y in (cy - h, cy + h):
        line(v.tip_x + 3, y, v.tip_x + 32, y)
    line(cx - r, cy - r - 25, cx + r, cy - r - 25, "outside-diameter", arrows=True)
    line(cx - r, cy - r - 4, cx - r, cy - r - 30)
    line(cx + r, cy - r - 4, cx + r, cy - r - 30)
    line(cx + b * 0.7, cy - b * 0.7, cx + b + 30, cy - r - 45, "bore-leader")
    if handle_hole_enabled:
        hx, hy = v.point(
            (spec.centerline_to_handle_end - handle_hole_center_from_handle_end, 0)
        )
        hr = handle_hole_diameter * v.scale / 2
        parts.append(
            f'<circle id="handle-hole" cx="{hx:.6f}" cy="{hy:.6f}" r="{hr:.6f}" fill="white"/>'
        )
        line(hx, hy - hr - 8, hx, hy + hr + 8, "hole-centerline", True)
        yl = cy - h - 24
        line(hx, yl, v.tip_x, yl, "hole-location", arrows=True)
        line(hx, hy - hr - 8, hx, yl - 4)
        line(v.tip_x, cy - h - 3, v.tip_x, yl - 4)
        line(hx - hr * 0.5, hy + hr * 0.866, hx + 18, cy + h + 28, "hole-leader")
    parts.append('</g><g font-family="Arial,sans-serif" fill="#172033">')

    def label(x, y, value, size=9, anchor="start", bold=False):
        parts.append(
            f'<text x="{x:.6f}" y="{612-y:.6f}" font-size="{size}" text-anchor="{anchor}"'
            + (' font-weight="700"' if bold else "")
            + ">"
            + escape(str(value))
            + "</text>"
        )

    label(
        (cx + v.tip_x) / 2,
        top + 7,
        "C/L TO END "
        + dimension(spec.centerline_to_handle_end, "length")
        + " "
        + units,
        anchor="middle",
        bold=True,
    )
    label(v.tip_x + 38, cy, "HANDLE " + dimension(spec.handle_width, "width"), 8)
    label(
        cx,
        cy - r - 19,
        "OD Ø" + dimension(spec.finished_od, "od") + " " + units,
        anchor="middle",
        bold=True,
    )
    tol = " ±" + inch(float(bore_tolerance)) if bore_tolerance is not None else ""
    label(
        cx + b + 33,
        cy - r - 45,
        "BORE Ø" + dimension(spec.finished_bore_diameter, "bore") + tol,
        9,
        bold=True,
    )
    label(
        v.layout.edge_x - 16,
        cy - r - 22,
        "t = " + inch(spec.thickness) + " " + units,
        9,
    )
    if handle_hole_enabled:
        label(
            hx + 22,
            cy + h + 33,
            "Ø" + dimension(handle_hole_diameter, "hole_diameter") + " THRU",
            8,
            "start",
        )
        label(
            (hx + v.tip_x) / 2,
            yl - 13,
            dimension(handle_hole_center_from_handle_end, "hole_location"),
            8,
            "middle",
        )
    chamfer_text = (
        (
            "YES — " + inch(float(chamfer_width)) + " " + units
            if chamfer_width is not None
            else "YES — WIDTH NOT ENTERED"
        )
        if chamfer
        else "NO"
    )
    parts.append(
        '<rect x="34" y="440" width="724" height="130" fill="white" stroke="#172033"/>'
    )
    label(46, 155, "HANDLED ORIFICE PLATE", 12, bold=True)
    label(744, 155, "CONFIGURATION DRAWING · SCALE " + v.scale_label, 10, "end", True)
    for yy, field, value in (
        (132, "MATERIAL", material),
        (112, "THICKNESS", inch(spec.thickness) + " " + units),
        (92, "CHAMFER", chamfer_text),
        (72, "MARKING", str(handle_label or "No label")[:40]),
    ):
        label(46, yy, field, 9, bold=True)
        label(150, yy, value, 10)
    label(
        420,
        132,
        "OD Ø"
        + dimension(spec.finished_od, "od")
        + " / BORE Ø"
        + dimension(spec.finished_bore_diameter, "bore"),
        10,
    )
    label(
        420,
        112,
        "BORE TOL. "
        + (
            "±" + inch(float(bore_tolerance)) + " " + units
            if bore_tolerance is not None
            else "Not specified"
        ),
        10,
    )
    label(420, 92, "DIMENSIONS IN INCHES", 9)
    label(
        420,
        72,
        (
            "HANDLE END TO HOLE C/L "
            + dimension(handle_hole_center_from_handle_end, "hole_location")
            if handle_hole_enabled
            else "DO NOT SCALE DRAWING"
        ),
        9,
    )
    label(
        396,
        25,
        "Configuration preview — Not an approved manufacturing drawing.",
        10,
        "middle",
        True,
    )
    parts.append("</g></svg>")
    return "\n".join(parts)
