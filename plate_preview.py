from html import escape


def render_plate_svg(
    *,
    paddle_dia: float,
    bore_dia: float,
    handle_width: float,
    handle_length_from_bore: float,
    thickness: float,
    material: str,
    units: str = "in.",
) -> str:
    """Return a responsive, illustrative handled-plate SVG."""
    od = max(float(paddle_dia), 0.001)
    bore = max(min(float(bore_dia), od * 0.96), od * 0.02)
    handle = max(float(handle_width), od * 0.04)
    length = max(float(handle_length_from_bore), od / 2)

    # Drawing scale is intentionally clamped for legibility, not manufacturing use.
    radius_px = 92.0
    bore_px = max(8.0, min(84.0, radius_px * bore / od))
    handle_px = max(18.0, min(92.0, radius_px * 2 * handle / od))
    handle_len_px = max(radius_px, min(255.0, radius_px * length / (od / 2)))
    cx, cy = 205.0, 205.0
    handle_x = cx + radius_px - 3
    handle_y = cy - handle_px / 2
    handle_end = min(472.0, cx + handle_len_px)
    material_text = escape(str(material))
    unit_text = escape(str(units))

    return f"""
<svg viewBox="0 0 520 420" role="img"
     aria-label="Illustrative handled orifice plate with dimensional callouts"
     xmlns="http://www.w3.org/2000/svg" style="width:100%;height:auto;display:block">
  <defs>
    <marker id="arrow" markerWidth="7" markerHeight="7" refX="3.5" refY="3.5" orient="auto-start-reverse">
      <path d="M0,0 L7,3.5 L0,7 z" fill="#4169a1"/>
    </marker>
    <linearGradient id="steel" x1="0" x2="1">
      <stop offset="0" stop-color="#e9edf2"/><stop offset="0.5" stop-color="#b8c2ce"/><stop offset="1" stop-color="#eef1f5"/>
    </linearGradient>
  </defs>
  <rect width="520" height="420" rx="18" fill="#f7f9fc"/>
  <text x="24" y="32" font-family="Arial,sans-serif" font-size="17" font-weight="700" fill="#172033">Handled Orifice Plate</text>
  <text x="24" y="54" font-family="Arial,sans-serif" font-size="13" fill="#5d6b7d">{material_text} · {thickness:.3f} {unit_text} thick</text>

  <rect x="{handle_x:.1f}" y="{handle_y:.1f}" width="{max(8.0, handle_end-handle_x):.1f}" height="{handle_px:.1f}" rx="4" fill="url(#steel)" stroke="#465468" stroke-width="2"/>
  <circle cx="{cx}" cy="{cy}" r="{radius_px}" fill="url(#steel)" stroke="#465468" stroke-width="2.5"/>
  <circle cx="{cx}" cy="{cy}" r="{bore_px}" fill="#f7f9fc" stroke="#465468" stroke-width="2.5"/>
  <line x1="{cx-radius_px}" y1="{cy}" x2="{cx+radius_px}" y2="{cy}" stroke="#8b98a9" stroke-dasharray="5 5"/>
  <line x1="{cx}" y1="{cy-radius_px}" x2="{cx}" y2="{cy+radius_px}" stroke="#8b98a9" stroke-dasharray="5 5"/>

  <line x1="{cx-radius_px}" y1="330" x2="{cx+radius_px}" y2="330" stroke="#4169a1" marker-start="url(#arrow)" marker-end="url(#arrow)"/>
  <line x1="{cx-radius_px}" y1="{cy+radius_px+5}" x2="{cx-radius_px}" y2="340" stroke="#8b98a9"/>
  <line x1="{cx+radius_px}" y1="{cy+radius_px+5}" x2="{cx+radius_px}" y2="340" stroke="#8b98a9"/>
  <text x="{cx}" y="323" text-anchor="middle" font-family="Arial,sans-serif" font-size="13" fill="#26364d">OD ⌀ {od:.3f} {unit_text}</text>

  <line x1="{cx-bore_px}" y1="{cy}" x2="{cx+bore_px}" y2="{cy}" stroke="#4169a1" marker-start="url(#arrow)" marker-end="url(#arrow)"/>
  <text x="{cx}" y="{cy-12}" text-anchor="middle" font-family="Arial,sans-serif" font-size="12" fill="#26364d">Bore ⌀ {bore:.3f}</text>

  <line x1="{handle_end+16:.1f}" y1="{handle_y:.1f}" x2="{handle_end+16:.1f}" y2="{handle_y+handle_px:.1f}" stroke="#4169a1" marker-start="url(#arrow)" marker-end="url(#arrow)"/>
  <text x="{handle_end+27:.1f}" y="{cy+4:.1f}" font-family="Arial,sans-serif" font-size="12" fill="#26364d" transform="rotate(90 {handle_end+27:.1f} {cy+4:.1f})">Handle {handle:.3f} {unit_text}</text>

  <line x1="{cx}" y1="105" x2="{handle_end:.1f}" y2="105" stroke="#4169a1" marker-start="url(#arrow)" marker-end="url(#arrow)"/>
  <line x1="{cx}" y1="115" x2="{cx}" y2="95" stroke="#8b98a9"/>
  <line x1="{handle_end:.1f}" y1="115" x2="{handle_end:.1f}" y2="95" stroke="#8b98a9"/>
  <text x="{(cx+handle_end)/2:.1f}" y="96" text-anchor="middle" font-family="Arial,sans-serif" font-size="12" fill="#26364d">From bore center {length:.3f} {unit_text}</text>

  <rect x="24" y="366" width="472" height="34" rx="8" fill="#fff3cd" stroke="#e4c461"/>
  <text x="260" y="388" text-anchor="middle" font-family="Arial,sans-serif" font-size="12.5" font-weight="700" fill="#604b00">Illustrative only — not an approval or manufacturing drawing.</text>
</svg>"""
