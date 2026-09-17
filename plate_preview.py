from html import escape
from math import sqrt


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


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
    handle_px = _clamp((2 * radius_px) * handle / od, 16.0, 76.0)
    physical_extension = max(length - (od / 2), 0.0)
    extension_px = _clamp(radius_px * physical_extension / (od / 2), 60.0, 210.0)
    handle_end = cx + radius_px + extension_px

    # The transition begins inside the paddle and widens into the handle,
    # making the neck/handle connection visible as one continuous cut profile.
    neck_half_height = min(handle_px * 0.72, radius_px * 0.72)
    neck_x = cx + sqrt(max(radius_px**2 - neck_half_height**2, 0.0)) - 7.0
    body_top = cy - handle_px / 2
    body_bottom = cy + handle_px / 2
    neck_top = cy - neck_half_height
    neck_bottom = cy + neck_half_height

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

  <g fill="#f8fafc" stroke="#172033" stroke-width="2.2" stroke-linejoin="round">
    <circle cx="{cx:.1f}" cy="{cy:.1f}" r="{radius_px:.1f}"/>
    <path d="M {neck_x:.1f},{neck_top:.1f}
             C {neck_x + 13:.1f},{neck_top:.1f} {neck_x + 19:.1f},{body_top:.1f} {neck_x + 33:.1f},{body_top:.1f}
             L {handle_end:.1f},{body_top:.1f}
             L {handle_end:.1f},{body_bottom:.1f}
             L {neck_x + 33:.1f},{body_bottom:.1f}
             C {neck_x + 19:.1f},{body_bottom:.1f} {neck_x + 13:.1f},{neck_bottom:.1f} {neck_x:.1f},{neck_bottom:.1f}
             Z"/>
  </g>

  <circle cx="{cx:.1f}" cy="{cy:.1f}" r="{bore_px:.1f}" fill="#ffffff" stroke="#172033" stroke-width="2.2"/>

  <!-- Centerlines -->
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
