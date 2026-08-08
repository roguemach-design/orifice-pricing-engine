from html import escape
from math import sqrt


_MATERIAL_PALETTES = {
    "304": ("#f8fafc", "#aebac8", "#dce3ea"),
    "316": ("#f7fbff", "#9eb2c8", "#d5e2ee"),
    "carbon steel": ("#d8dee5", "#687787", "#aeb8c2"),
}


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def _material_palette(material: str) -> tuple[str, str, str]:
    return _MATERIAL_PALETTES.get(
        str(material).strip().lower(),
        ("#f8fafc", "#aebac8", "#dce3ea"),
    )


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
    """Return a responsive, illustrative handled-orifice-plate SVG.

    Proportions follow the customer's configuration, with guarded visual
    minimums so small features remain legible. It is intentionally not an
    engineering or manufacturing drawing.
    """
    od = max(float(paddle_dia), 0.001)
    bore = _clamp(float(bore_dia), od * 0.005, od * 0.98)
    handle = max(float(handle_width), od * 0.005)
    length = max(float(handle_length_from_bore), od / 2)
    nominal_thickness = max(float(thickness), 0.0)

    # The paddle remains prominent while the handle extension, bore, and
    # handle width respond to physical ratios. Minimums preserve usefulness at
    # the 48-inch OD / short-handle boundary without claiming drawing scale.
    radius_px = 108.0
    cx, cy = 220.0, 225.0
    bore_px = _clamp(radius_px * bore / od, 6.0, radius_px * 0.94)
    handle_px = _clamp((2 * radius_px) * handle / od, 18.0, 88.0)
    physical_extension = max(length - (od / 2), 0.0)
    extension_px = _clamp(radius_px * physical_extension / (od / 2), 62.0, 205.0)
    handle_end = cx + radius_px + extension_px

    # Start the neck inside the paddle so its fill masks the circle stroke and
    # reads as a continuous cut profile instead of an attached rectangle.
    neck_half_height = min(handle_px * 0.72, radius_px * 0.72)
    neck_x = cx + sqrt(max(radius_px**2 - neck_half_height**2, 0.0)) - 7.0
    body_top = cy - handle_px / 2
    body_bottom = cy + handle_px / 2
    neck_top = cy - neck_half_height
    neck_bottom = cy + neck_half_height

    material_text = escape(str(material))
    unit_text = escape(str(units))
    highlight, shadow, midtone = _material_palette(material)

    return f"""<svg viewBox="0 0 620 460" role="img"
  aria-label="Illustrative handled orifice plate preview"
  xmlns="http://www.w3.org/2000/svg"
  style="width:100%;height:auto;display:block;background:#ffffff">
  <defs>
    <marker id="preview-arrow" markerWidth="7" markerHeight="7" refX="3.5" refY="3.5" orient="auto-start-reverse">
      <path d="M0,0 L7,3.5 L0,7 z" fill="#315f93"/>
    </marker>
    <linearGradient id="preview-metal" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="{highlight}"/>
      <stop offset="0.48" stop-color="{midtone}"/>
      <stop offset="1" stop-color="{shadow}"/>
    </linearGradient>
    <filter id="preview-shadow" x="-20%" y="-20%" width="150%" height="150%">
      <feDropShadow dx="0" dy="5" stdDeviation="5" flood-color="#172033" flood-opacity="0.16"/>
    </filter>
  </defs>

  <rect x="1" y="1" width="618" height="458" rx="18" fill="#f7f9fc" stroke="#d9e1ea"/>
  <text x="25" y="34" font-family="Arial,sans-serif" font-size="18" font-weight="700" fill="#172033">Handled Orifice Plate</text>
  <text x="25" y="57" font-family="Arial,sans-serif" font-size="13" fill="#526174">{material_text} &#183; {nominal_thickness:.3f} {unit_text} nominal thickness</text>
  <rect x="480" y="20" width="112" height="27" rx="13.5" fill="#e8f1fb"/>
  <text x="536" y="38" text-anchor="middle" font-family="Arial,sans-serif" font-size="12" font-weight="700" fill="#315f93">LIVE PREVIEW</text>

  <g filter="url(#preview-shadow)">
    <circle cx="{cx:.1f}" cy="{cy:.1f}" r="{radius_px:.1f}" fill="url(#preview-metal)" stroke="#3f4e61" stroke-width="2.5"/>
    <path d="M {neck_x:.1f},{neck_top:.1f}
             C {neck_x + 13:.1f},{neck_top:.1f} {neck_x + 19:.1f},{body_top:.1f} {neck_x + 33:.1f},{body_top:.1f}
             L {handle_end:.1f},{body_top:.1f}
             L {handle_end:.1f},{body_bottom:.1f}
             L {neck_x + 33:.1f},{body_bottom:.1f}
             C {neck_x + 19:.1f},{body_bottom:.1f} {neck_x + 13:.1f},{neck_bottom:.1f} {neck_x:.1f},{neck_bottom:.1f}
             Z"
          fill="url(#preview-metal)" stroke="#3f4e61" stroke-width="2.5" stroke-linejoin="round"/>
  </g>

  <circle cx="{cx:.1f}" cy="{cy:.1f}" r="{bore_px:.1f}" fill="#f7f9fc" stroke="#3f4e61" stroke-width="2.5"/>
  <line x1="{cx-radius_px:.1f}" y1="{cy:.1f}" x2="{cx+radius_px:.1f}" y2="{cy:.1f}" stroke="#8795a6" stroke-width="1" stroke-dasharray="5 5"/>
  <line x1="{cx:.1f}" y1="{cy-radius_px:.1f}" x2="{cx:.1f}" y2="{cy+radius_px:.1f}" stroke="#8795a6" stroke-width="1" stroke-dasharray="5 5"/>
  <circle cx="{cx:.1f}" cy="{cy:.1f}" r="2.5" fill="#315f93"/>

  <line x1="{cx-radius_px:.1f}" y1="365" x2="{cx+radius_px:.1f}" y2="365" stroke="#315f93" marker-start="url(#preview-arrow)" marker-end="url(#preview-arrow)"/>
  <line x1="{cx-radius_px:.1f}" y1="{cy+radius_px+4:.1f}" x2="{cx-radius_px:.1f}" y2="374" stroke="#8795a6"/>
  <line x1="{cx+radius_px:.1f}" y1="{cy+radius_px+4:.1f}" x2="{cx+radius_px:.1f}" y2="374" stroke="#8795a6"/>
  <rect x="{cx-72:.1f}" y="347" width="144" height="22" rx="11" fill="#f7f9fc"/>
  <text x="{cx:.1f}" y="362" text-anchor="middle" font-family="Arial,sans-serif" font-size="13" font-weight="700" fill="#26364d">OD &#8960; {od:.3f} {unit_text}</text>

  <line x1="{cx-bore_px:.1f}" y1="{cy:.1f}" x2="{cx+bore_px:.1f}" y2="{cy:.1f}" stroke="#315f93" marker-start="url(#preview-arrow)" marker-end="url(#preview-arrow)"/>
  <rect x="{cx-67:.1f}" y="{cy-29:.1f}" width="134" height="20" rx="10" fill="#f7f9fc" fill-opacity="0.94"/>
  <text x="{cx:.1f}" y="{cy-15:.1f}" text-anchor="middle" font-family="Arial,sans-serif" font-size="12" font-weight="700" fill="#26364d">Bore &#8960; {bore:.3f}</text>

  <line x1="{handle_end+17:.1f}" y1="{body_top:.1f}" x2="{handle_end+17:.1f}" y2="{body_bottom:.1f}" stroke="#315f93" marker-start="url(#preview-arrow)" marker-end="url(#preview-arrow)"/>
  <text x="{handle_end+31:.1f}" y="{cy:.1f}" text-anchor="middle" font-family="Arial,sans-serif" font-size="12" fill="#26364d" transform="rotate(90 {handle_end+31:.1f} {cy:.1f})">{handle:.3f} {unit_text} handle</text>

  <line x1="{cx:.1f}" y1="86" x2="{handle_end:.1f}" y2="86" stroke="#315f93" marker-start="url(#preview-arrow)" marker-end="url(#preview-arrow)"/>
  <line x1="{cx:.1f}" y1="96" x2="{cx:.1f}" y2="76" stroke="#8795a6"/>
  <line x1="{handle_end:.1f}" y1="96" x2="{handle_end:.1f}" y2="76" stroke="#8795a6"/>
  <rect x="{(cx+handle_end)/2-94:.1f}" y="67" width="188" height="22" rx="11" fill="#f7f9fc"/>
  <text x="{(cx+handle_end)/2:.1f}" y="82" text-anchor="middle" font-family="Arial,sans-serif" font-size="12" fill="#26364d">Center to handle end {length:.3f} {unit_text}</text>

  <rect x="24" y="405" width="572" height="34" rx="8" fill="#fff3cd" stroke="#e4c461"/>
  <text x="310" y="427" text-anchor="middle" font-family="Arial,sans-serif" font-size="12.5" font-weight="700" fill="#604b00">Illustrative only &#8212; not an approval or manufacturing drawing.</text>
</svg>"""
