from html import escape
from math import sqrt


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def _paddle_outline_path(
    cx: float, cy: float, radius: float, half_handle: float, handle_end: float
) -> str:
    """One outer contour with symmetric circular fillets tangent to the OD and handle.

    Each fillet center is one fillet radius above/below the handle side.
    Its distance from the plate center is R + f, so the two circles are
    externally tangent. This avoids a circle stroke under a second handle fill.
    """
    fillet = min(radius * 0.12, half_handle * 0.35)
    offset = half_handle + fillet
    fillet_x = cx + sqrt((radius + fillet) ** 2 - offset**2)
    plate_x = cx + radius * (fillet_x - cx) / (radius + fillet)
    plate_y = radius * offset / (radius + fillet)
    top = cy - half_handle
    bottom = cy + half_handle
    return (
        f"M {fillet_x:.3f},{top:.3f} "
        f"A {fillet:.3f},{fillet:.3f} 0 0 1 {plate_x:.3f},{cy - plate_y:.3f} "
        f"A {radius:.3f},{radius:.3f} 0 1 0 {plate_x:.3f},{cy + plate_y:.3f} "
        f"A {fillet:.3f},{fillet:.3f} 0 0 1 {fillet_x:.3f},{bottom:.3f} "
        f"L {handle_end:.3f},{bottom:.3f} "
        f"L {handle_end:.3f},{top:.3f} Z"
    )


def render_plate_svg(
    *,
    paddle_dia: float,
    bore_dia: float,
    handle_width: float,
    handle_length_from_bore: float,
    thickness: float,
    material: str,
    bore_tolerance: float | None = None,
    handle_label: str = "No label",
    chamfer: bool = False,
    chamfer_width: float | None = None,
    handle_hole_enabled: bool = False,
    handle_hole_diameter: float | None = None,
    handle_hole_center_from_handle_end: float | None = None,
    units: str = "in.",
) -> str:
    """Return a responsive configuration drawing for a handled orifice plate.

    The entered dimensions control the illustrated proportions. Visual
    minimums keep small features legible, so the drawing is explicitly marked
    not to scale and is not represented as a manufacturing approval drawing.
    """
    od = max(float(paddle_dia), 0.001)
    bore = _clamp(float(bore_dia), od * 0.005, od * 0.98)
    handle = max(float(handle_width), od * 0.005)
    length = max(float(handle_length_from_bore), od / 2)
    nominal_thickness = max(float(thickness), 0.0)

    radius_px = 110.0
    cx, cy = 220.0, 225.0
    bore_px = _clamp(radius_px * bore / od, 6.0, radius_px * 0.94)
    handle_px = _clamp((2 * radius_px) * handle / od, 16.0, 2 * radius_px * 0.98)
    physical_extension = max(length - (od / 2), 0.0)
    extension_px = _clamp(radius_px * physical_extension / (od / 2), 60.0, 210.0)
    handle_end = cx + radius_px + extension_px

    outline = _paddle_outline_path(cx, cy, radius_px, handle_px / 2, handle_end)
    hole_svg = ""
    if handle_hole_enabled:
        from plate_geometry import PlateSpec, build_plate_geometry
        g = build_plate_geometry(PlateSpec(
            finished_od=od, finished_bore_diameter=float(bore_dia),
            handle_width=float(handle_width), centerline_to_handle_end=float(handle_length_from_bore),
            thickness=float(thickness), material=str(material),
            handle_hole_enabled=True, handle_hole_diameter=handle_hole_diameter,
            handle_hole_center_from_handle_end=handle_hole_center_from_handle_end,
        ))
        scale = min(220 / od, 320 / length)
        radius_px, bore_px = g.radius * scale, float(bore_dia) * scale / 2
        handle_px, handle_end = float(handle_width) * scale, cx + length * scale
        commands = []
        first = g.segments[0].start
        commands.append(f"M {cx+first[0]*scale},{cy-first[1]*scale}")
        for seg in g.segments:
            x, y = seg.end
            if seg.kind == "line":
                commands.append(f"L {cx+x*scale},{cy-y*scale}")
            else:
                commands.append(f"A {seg.radius*scale} {seg.radius*scale} 0 {int(abs(seg.sweep_degrees)>180)} {int(seg.sweep_degrees<0)} {cx+x*scale} {cy-y*scale}")
        outline = " ".join(commands) + " Z"
        hx = handle_end - handle_hole_center_from_handle_end * scale
        hole_svg = (
            f'<circle id="handle-hole" cx="{hx:.4f}" cy="{cy:.4f}" r="{handle_hole_diameter*scale/2:.4f}" fill="white" stroke="#172033" stroke-width="2.2"/>'
            f'<line x1="{hx}" y1="145" x2="{handle_end}" y2="145" stroke="#1d4f7a" marker-start="url(#drawing-arrow)" marker-end="url(#drawing-arrow)"/>'
            f'<line x1="{hx}" y1="145" x2="{hx}" y2="{cy}" stroke="#637386" stroke-dasharray="4 3"/>'
            f'<line x1="{handle_end}" y1="145" x2="{handle_end}" y2="{cy}" stroke="#637386"/>'
            f'<text x="340" y="122" font-family="Arial,sans-serif" font-size="11">HANDLE HOLE &#8960; {handle_hole_diameter:.4f}</text>'
            f'<text x="340" y="136" font-family="Arial,sans-serif" font-size="11">HANDLE END TO HOLE C/L {handle_hole_center_from_handle_end:.4f}</text>'
        )
    body_top = cy - handle_px / 2
    body_bottom = cy + handle_px / 2

    material_text = escape(str(material))
    unit_text = escape(str(units))
    marking_text = escape(str(handle_label or "No label")[:40])
    tolerance_text = (
        f"&#177; {float(bore_tolerance):.3f} {unit_text}"
        if bore_tolerance is not None
        else "Not specified"
    )
    if chamfer and chamfer_width is not None:
        chamfer_text = f"YES &#8212; {float(chamfer_width):.3f} {unit_text}"
    elif chamfer:
        chamfer_text = "YES &#8212; WIDTH NOT ENTERED"
    else:
        chamfer_text = "NO"
    profile_height = _clamp(7.0 + nominal_thickness * 34.0, 8.0, 24.0)
    title_value_x = 464

    return f"""<svg viewBox="0 0 680 520" role="img"
  aria-label="Handled orifice plate configuration drawing"
  xmlns="http://www.w3.org/2000/svg"
  style="width:100%;height:auto;display:block;background:#ffffff">
  <title>Handled orifice plate configuration drawing</title>
  <desc>Not-to-scale preview of the entered plate, bore, handle, and thickness dimensions.</desc>
  <defs>
    <marker id="drawing-arrow" markerWidth="7" markerHeight="7" refX="3.5" refY="3.5" orient="auto-start-reverse">
      <path d="M0,0 L7,3.5 L0,7 z" fill="#1d4f7a"/>
    </marker>
  </defs>

  <rect x="1" y="1" width="678" height="518" fill="#ffffff" stroke="#172033" stroke-width="2"/>
  <rect x="9" y="9" width="662" height="502" fill="none" stroke="#7d8998" stroke-width="1"/>
  <text x="22" y="34" font-family="Arial,sans-serif" font-size="17" font-weight="700" fill="#172033">HANDLED ORIFICE PLATE</text>
  <text x="658" y="34" text-anchor="end" font-family="Arial,sans-serif" font-size="12" font-weight="700" fill="#1d4f7a">CONFIGURATION DRAWING &#183; NTS</text>

  <path id="plate-outline" d="{outline}" fill="#f8fafc" stroke="#172033" stroke-width="2.2" stroke-linejoin="round"/>

  <circle cx="{cx:.1f}" cy="{cy:.1f}" r="{bore_px:.1f}" fill="#ffffff" stroke="#172033" stroke-width="2.2"/>

{hole_svg}  <!-- Centerlines -->
  <g stroke="#637386" stroke-width="1" stroke-dasharray="9 4 2 4">
    <line x1="{cx-radius_px-15:.1f}" y1="{cy:.1f}" x2="{handle_end+12:.1f}" y2="{cy:.1f}"/>
    <line x1="{cx:.1f}" y1="{cy-radius_px-15:.1f}" x2="{cx:.1f}" y2="{cy+radius_px+15:.1f}"/>
  </g>
  <circle cx="{cx:.1f}" cy="{cy:.1f}" r="2.5" fill="#1d4f7a"/>

  <!-- Center-to-handle-end dimension -->
  <g fill="none" stroke="#1d4f7a" stroke-width="1.15">
    <line x1="{cx:.1f}" y1="69" x2="{handle_end:.1f}" y2="69" marker-start="url(#drawing-arrow)" marker-end="url(#drawing-arrow)"/>
    <line x1="{cx:.1f}" y1="59" x2="{cx:.1f}" y2="105" stroke="#637386"/>
    <line x1="{handle_end:.1f}" y1="59" x2="{handle_end:.1f}" y2="{body_top-7:.1f}" stroke="#637386"/>
  </g>
  <rect x="{(cx+handle_end)/2-95:.1f}" y="56" width="190" height="20" fill="#ffffff"/>
  <text x="{(cx+handle_end)/2:.1f}" y="70" text-anchor="middle" font-family="Arial,sans-serif" font-size="11.5" font-weight="700" fill="#172033">C/L TO END {length:.3f} {unit_text}</text>

  <!-- Bore diameter dimension -->
  <line x1="{cx-bore_px:.1f}" y1="{cy:.1f}" x2="{cx+bore_px:.1f}" y2="{cy:.1f}" stroke="#1d4f7a" stroke-width="1.15" marker-start="url(#drawing-arrow)" marker-end="url(#drawing-arrow)"/>
  <rect x="{cx-58:.1f}" y="{cy-27:.1f}" width="116" height="18" fill="#ffffff" fill-opacity="0.94"/>
  <text x="{cx:.1f}" y="{cy-14:.1f}" text-anchor="middle" font-family="Arial,sans-serif" font-size="11.5" font-weight="700" fill="#172033">BORE &#8960; {bore:.3f}</text>

  <!-- Outside diameter dimension -->
  <g fill="none" stroke="#1d4f7a" stroke-width="1.15">
    <line x1="{cx-radius_px:.1f}" y1="374" x2="{cx+radius_px:.1f}" y2="374" marker-start="url(#drawing-arrow)" marker-end="url(#drawing-arrow)"/>
    <line x1="{cx-radius_px:.1f}" y1="{cy+radius_px+4:.1f}" x2="{cx-radius_px:.1f}" y2="384" stroke="#637386"/>
    <line x1="{cx+radius_px:.1f}" y1="{cy+radius_px+4:.1f}" x2="{cx+radius_px:.1f}" y2="384" stroke="#637386"/>
  </g>
  <rect x="{cx-68:.1f}" y="361" width="136" height="20" fill="#ffffff"/>
  <text x="{cx:.1f}" y="375" text-anchor="middle" font-family="Arial,sans-serif" font-size="11.5" font-weight="700" fill="#172033">OD &#8960; {od:.3f} {unit_text}</text>

  <!-- Handle width dimension -->
  <line x1="{handle_end+18:.1f}" y1="{body_top:.1f}" x2="{handle_end+18:.1f}" y2="{body_bottom:.1f}" stroke="#1d4f7a" stroke-width="1.15" marker-start="url(#drawing-arrow)" marker-end="url(#drawing-arrow)"/>
  <line x1="{handle_end-6:.1f}" y1="{body_top:.1f}" x2="{handle_end+27:.1f}" y2="{body_top:.1f}" stroke="#637386"/>
  <line x1="{handle_end-6:.1f}" y1="{body_bottom:.1f}" x2="{handle_end+27:.1f}" y2="{body_bottom:.1f}" stroke="#637386"/>
  <text x="{handle_end+34:.1f}" y="{cy:.1f}" text-anchor="middle" font-family="Arial,sans-serif" font-size="11.5" font-weight="700" fill="#172033" transform="rotate(90 {handle_end+34:.1f} {cy:.1f})">HANDLE {handle:.3f} {unit_text}</text>

  <!-- Edge/profile view and thickness dimension -->
  <text x="27" y="268" font-family="Arial,sans-serif" font-size="10" font-weight="700" fill="#526174">EDGE PROFILE</text>
  <rect x="27" y="{286-profile_height/2:.1f}" width="55" height="{profile_height:.1f}" fill="#f8fafc" stroke="#172033" stroke-width="1.7"/>
  <line x1="17" y1="{286-profile_height/2:.1f}" x2="17" y2="{286+profile_height/2:.1f}" stroke="#1d4f7a" marker-start="url(#drawing-arrow)" marker-end="url(#drawing-arrow)"/>
  <text x="27" y="318" font-family="Arial,sans-serif" font-size="10.5" font-weight="700" fill="#172033">t = {nominal_thickness:.3f} {unit_text}</text>

  <!-- Configuration title block -->
  <g font-family="Arial,sans-serif" fill="#172033">
    <rect x="18" y="405" width="644" height="86" fill="#ffffff" stroke="#172033" stroke-width="1.5"/>
    <line x1="350" y1="405" x2="350" y2="491" stroke="#172033"/>
    <line x1="18" y1="428" x2="662" y2="428" stroke="#7d8998"/>
    <line x1="18" y1="449" x2="662" y2="449" stroke="#7d8998"/>
    <line x1="18" y1="470" x2="662" y2="470" stroke="#7d8998"/>
    <text x="27" y="420" font-size="9" font-weight="700" fill="#526174">PART</text>
    <text x="91" y="420" font-size="11" font-weight="700">HANDLED ORIFICE PLATE</text>
    <text x="359" y="420" font-size="9" font-weight="700" fill="#526174">MATERIAL</text>
    <text x="{title_value_x}" y="420" font-size="11" font-weight="700">{material_text}</text>

    <text x="27" y="443" font-size="9" font-weight="700" fill="#526174">OD / BORE</text>
    <text x="91" y="443" font-size="11">&#8960; {od:.3f} / &#8960; {bore:.3f} {unit_text}</text>
    <text x="359" y="443" font-size="9" font-weight="700" fill="#526174">THICKNESS</text>
    <text x="{title_value_x}" y="443" font-size="11">{nominal_thickness:.3f} {unit_text}</text>

    <text x="27" y="464" font-size="9" font-weight="700" fill="#526174">BORE TOL.</text>
    <text x="91" y="464" font-size="11">{tolerance_text}</text>
    <text x="359" y="464" font-size="9" font-weight="700" fill="#526174">CHAMFER</text>
    <text x="{title_value_x}" y="464" font-size="10.5">{chamfer_text}</text>

    <text x="27" y="485" font-size="9" font-weight="700" fill="#526174">MARKING</text>
    <text x="91" y="485" font-size="10.5">{marking_text}</text>
    <text x="359" y="485" font-size="9" font-weight="700" fill="#526174">DRAWING</text>
    <text x="{title_value_x}" y="485" font-size="10.5" font-weight="700">CUSTOMER CONFIGURATION</text>
  </g>

  <text x="340" y="507" text-anchor="middle" font-family="Arial,sans-serif" font-size="10.5" font-weight="700" fill="#754c00">Configuration preview &#8212; entered dimensions shown. Not an approved manufacturing drawing.</text>
</svg>"""
