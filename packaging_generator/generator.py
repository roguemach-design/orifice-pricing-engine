"""Versioned perforated tri-fold with center nest. Prototype, units inch."""

from dataclasses import asdict, dataclass
from hashlib import sha256
from io import StringIO
import json
from math import ceil, cos, sin, pi, acos, isfinite
import ezdxf
from shapely.geometry import Polygon
from plate_geometry import build_plate_geometry, canonical_specification
from manufacturing_files import _DXF_LOCK
from . import VERSION
from .contour import nest_contour, transform, polygon, area, svg_path

SAMPLE_ERROR = 0.0001
LAYERS = ("CUT_SHELL", "CUT_FRAME", "CUT_NEST", "PERF_FOLD_LEFT", "PERF_FOLD_RIGHT")


@dataclass(frozen=True)
class Configuration:
    version: str
    board_reference: str
    caliper: float
    compression_fraction: float
    clearance: float
    depth_clearance: float
    margin: float
    fold_allowance: float
    kerf: float
    closure_edge_distance: float
    flute_direction: str
    closure: str
    max_sheet_width: float
    max_sheet_height: float
    max_layers: int
    stitch_length: float = 0.25
    stitch_web: float = 0.125
    fold_end_bridge: float = 0.25
    finger_diameter: float = 0.75
    finger_min_diameter: float = 0.25
    finger_min_bridge: float = 0.125
    # Mass intentionally omitted until measured material data is validated.

    def __post_init__(self):
        for name in ("version", "board_reference"):
            v = getattr(self, name)
            if (
                not isinstance(v, str)
                or not 1 <= len(v) <= 100
                or not v.isascii()
                or any(ord(c) < 32 for c in v)
            ):
                raise ValueError("printable ASCII configuration labels required")
        bounds = {
            "finger_diameter": (0.25, 0.75),
            "finger_min_diameter": (0.25, 0.75),
            "finger_min_bridge": (0.125, 0.5),
            "stitch_length": (0.05, 0.5),
            "stitch_web": (0.05, 0.5),
            "fold_end_bridge": (0.15, 0.75),
            "caliper": (0.03, 0.30),
            "compression_fraction": (0, 0.30),
            "clearance": (0.01, 0.10),
            "depth_clearance": (0.005, 0.10),
            "margin": (0.5, 3),
            "fold_allowance": (0.01, 0.25),
            "kerf": (0, 0.04),
            "closure_edge_distance": (0.15, 0.75),
            "max_sheet_width": (12, 120),
            "max_sheet_height": (12, 120),
        }
        for name, (lo, hi) in bounds.items():
            v = getattr(self, name)
            if type(v) not in (int, float) or not isfinite(v) or not lo <= v <= hi:
                raise ValueError(f"{name}: outside bounded prototype range")
        if type(self.max_layers) is not int or not 1 <= self.max_layers <= 20:
            raise ValueError("max_layers must be 1-20")
        if self.finger_min_diameter > self.finger_diameter:
            raise ValueError("minimum finger diameter exceeds target")
        if self.flute_direction != "X_PERPENDICULAR_TO_FOLD":
            raise ValueError("only qualified prototype flute orientation supported")
        if self.closure not in ("CHAIN_STITCH_REVIEW", "STAPLE_REVIEW"):
            raise ValueError("unsupported closure")
        if (
            self.margin
            <= self.clearance + self.closure_edge_distance + 2 * self.caliper
        ):
            raise ValueError("insufficient protective/closure margin")
        if self.clearance - self.kerf / 2 <= SAMPLE_ERROR:
            raise ValueError("kerf consumes nest clearance")


def sampled_outline(spec):
    g = build_plate_geometry(spec)
    points = []
    for seg in g.segments:
        if seg.kind == "line":
            points.append(seg.start)
        else:
            step = 2 * acos(max(-1, 1 - SAMPLE_ERROR / seg.radius))
            count = max(2, ceil(abs(seg.sweep_degrees * pi / 180) / step))
            for i in range(count):
                angle = (seg.start_degrees + seg.sweep_degrees * i / count) * pi / 180
                points.append(
                    (
                        seg.center[0] + seg.radius * cos(angle),
                        seg.center[1] + seg.radius * sin(angle),
                    )
                )
    poly = Polygon(points)
    if not poly.is_valid or poly.area <= 0:
        raise ValueError("invalid canonical outer contour")
    return poly


def layout(spec, config):
    if (
        not 0.125 <= spec.thickness <= 0.5
        or spec.finished_od > 24
        or spec.centerline_to_handle_end > 36
    ):
        raise ValueError("outside prototype packaging envelope")
    # The nesting cut is exterior-only. Neither bore nor handle hole is cut into backing.
    segments, geometry_report = nest_contour(spec, config)
    W = spec.finished_od + 2 * config.margin
    H = spec.centerline_to_handle_end + spec.finished_od / 2 + 2 * config.margin
    effective = config.caliper * (1 - config.compression_fraction)
    n = ceil((spec.thickness + config.depth_clearance) / effective)
    if n > config.max_layers:
        raise ValueError("required nesting depth exceeds layer limit")
    depth = n * config.caliper
    first_spine = depth + config.fold_allowance
    second_spine = depth + config.caliper + config.fold_allowance
    center_x = W + first_spine
    right_x = center_x + W + second_spine
    flat_width = right_x + W
    # Preserve the original bore-center/panel alignment; reliefs must not recenter the nest.
    xoff, yoff = W / 2, config.margin + spec.finished_od / 2
    segments = transform(segments, xoff, yoff)
    nest = polygon(segments)  # validation only; never exported as the cut geometry
    minx, miny, maxx, maxy = nest.bounds
    if (
        minx <= config.closure_edge_distance + config.caliper
        or maxx >= W - config.closure_edge_distance - config.caliper
        or miny <= config.closure_edge_distance + config.caliper
        or maxy >= H - config.closure_edge_distance - config.caliper
    ):
        raise ValueError("nest intrudes into fold/closure protection zone")
    spacing = 0.25
    cols = max(1, int((config.max_sheet_width + spacing) // (W + spacing)))
    positions = [
        ((i % cols) * (W + spacing), H + spacing + (i // cols) * (H + spacing))
        for i in range(n - 1)
    ]
    sheet_width = max([flat_width] + [x + W for x, y in positions])
    sheet_height = max([H] + [y + H for x, y in positions])
    if sheet_width > config.max_sheet_width or sheet_height > config.max_sheet_height:
        raise ValueError(
            "layout exceeds configured cutting sheet; split-sheet layout required"
        )
    return dict(
        panel_width=W,
        panel_height=H,
        center_x=center_x,
        right_x=right_x,
        flat_shell=[flat_width, H],
        layout_size=[sheet_width, sheet_height],
        nest_layers=n,
        compressed_nest_depth=n * effective,
        nominal_nest_depth=depth,
        nominal_axial_void=depth - spec.thickness,
        compressed_axial_void=n * effective - spec.thickness,
        protective_pad_total_at_compressed_depth=max(
            0, n * effective - spec.thickness - config.depth_clearance
        ),
        folded_envelope_estimate=[W, H, depth + 3 * config.caliper],
        # Shell folds double board across the closing layer; this is a prototype envelope.
        spine_widths=[first_spine, second_spine],
        frame_positions=positions,
        # The shell center is the first nesting layer, additional frames add depth.
        center_nest_position=[center_x, 0],
        perforation_axes={
            "PERF_FOLD_LEFT": [W, center_x],
            "PERF_FOLD_RIGHT": [center_x + W, right_x],
        },
        board_net_area_in2=flat_width * H
        - area(segments)
        + (n - 1) * (W * H - area(segments)),
        board_gross_area_in2=flat_width * H + (n - 1) * W * H,
        nest_transform=dict(rotation_degrees=90, xoff=xoff, yoff=yoff),
        nest=nest,
        nest_segments=segments,
        geometry_report=geometry_report,
    )


def perforations(height, config):
    """Deterministic centered stitch pattern, with intact bridges at both ends."""
    usable = height - 2 * config.fold_end_bridge
    pitch = config.stitch_length + config.stitch_web
    count = int((usable + config.stitch_web) // pitch)
    if count < 1:
        raise ValueError("fold height cannot accommodate perforations")
    span = count * config.stitch_length + (count - 1) * config.stitch_web
    start = (height - span) / 2
    return [
        (start + i * pitch, start + i * pitch + config.stitch_length)
        for i in range(count)
    ]


def dxf_bytes(spec, config, data):
    d = data
    W, H = d["panel_width"], d["panel_height"]
    with _DXF_LOCK:
        previous = ezdxf.options.write_fixed_meta_data_for_testing
        try:
            ezdxf.options.write_fixed_meta_data_for_testing = True
            doc = ezdxf.new("R2010")
            doc.units = ezdxf.units.IN
            doc.header["$MEASUREMENT"] = 0
            for i, name in enumerate(LAYERS):
                doc.layers.new(name, dxfattribs={"color": i + 1})
            m = doc.modelspace()

            def rectangle(x, y, w, h, layer):
                m.add_lwpolyline(
                    [(x, y), (x + w, y), (x + w, y + h), (x, y + h)],
                    close=True,
                    dxfattribs={"layer": layer},
                )

            rectangle(0, 0, *d["flat_shell"], "CUT_SHELL")
            # Explicit short cut segments with intact webs. Each fold region has
            # two axes for its thickness-compensated spine; no continuous cut line.
            for layer, axes in d["perforation_axes"].items():
                for x in axes:
                    for y1, y2 in perforations(H, config):
                        m.add_line((x, y1), (x, y2), dxfattribs={"layer": layer})
            for x, y in [d["center_nest_position"]] + d["frame_positions"]:
                if (x, y) != tuple(d["center_nest_position"]):
                    rectangle(x, y, W, H, "CUT_FRAME")
                m.add_lwpolyline(
                    [
                        (s.start[0] + x, s.start[1] + y, s.bulge)
                        for s in d["nest_segments"]
                    ],
                    format="xyb",
                    close=True,
                    dxfattribs={"layer": "CUT_NEST"},
                )
            # Shop file contains only useful cut/perforation geometry. Assembly,
            # fixture and closure guidance remain in the immutable audit files.
            doc.classes.add_required_classes(doc.dxfversion)
            doc.classes.classes = dict(sorted(doc.classes.classes.items()))
            stream = StringIO()
            doc.write(stream)
            return stream.getvalue().encode("ascii")
        finally:
            ezdxf.options.write_fixed_meta_data_for_testing = previous


def generate(spec, config, parent):
    d = layout(spec, config)
    W, H = d["panel_width"], d["panel_height"]
    report = {k: v for k, v in d.items() if k not in ("nest", "nest_segments")}
    report.update(
        units="inch",
        generator_version=VERSION,
        configuration=asdict(config),
        parent=parent,
        packages_required=spec.quantity,
        parts_per_package=1,
        physical_validation="REQUIRED",
        estimated_mass=None,
        mass_reason="No validated board areal mass",
        contour_sampling_error_bound=0.0,
        nest_cut_compensation="internal cut: exact clearance minus half kerf; disable CAM kerf",
    )
    instructions = f"""# PROTOTYPE PACKAGE - PHYSICAL VALIDATION REQUIRED

Parent: {json.dumps(parent,sort_keys=True)}
Generator: {VERSION}; configuration {config.version}
Units: inch. One part per package; make {spec.quantity} separate packages.
Board: {config.board_reference}; measure caliper {config.caliper} before cutting.
Flutes run in flat-sheet X, perpendicular to the vertical perforated fold regions; verify fold/tear coupons.

1. Load the DXF in inches. CUT_SHELL, CUT_FRAME, CUT_NEST are through-cut contours.
2. PERF_FOLD_LEFT / PERF_FOLD_RIGHT contain short laser-cut stitches with intact webs.
   Each region has two parallel axes defining its wrapping spine. Preserve the webs and end
   bridges. Never join these segments into continuous full-height cuts. Validate strength on coupons.
3. No notes/reference/closure geometry is included in the laser DXF. Nest cutter-center geometry includes
   configured kerf; disable extra CAM compensation on CUT_NEST. Outer contours are nominal;
   accept loss of half kerf in external protective margin. Verify kerf with a coupon.
4. Place the shell in a square-stop fixture. Its center-panel cutout is nesting layer 1.
   Add {d['nest_layers'] - 1} separate center frames with matching openings aligned.
   Fold the LEFT panel underneath as the solid back, and the RIGHT panel over as the solid front.
   The shell center must never be used as solid backing. Minimum compressed nest depth
   {d['compressed_nest_depth']:.6f}; nominal uncompressed depth {d['nominal_nest_depth']:.6f}.
5. Two side finger reliefs open from the LEFT long handle edge in the layout, one near the tip
   and one before the paddle transition. Toolpath diameter {2*d['geometry_report']['finger_reliefs'][0]['cutter_radius']:.6f} inch.
   Use them to access alongside/beneath the handle; do not pull against a sharp steel edge.
   Verify retention, finger clearance and cardboard strength by physical cutting. These reliefs
   are NOT evidence of shipping qualification; all packaging remains PROTOTYPE / ENGINEERING REVIEW.
   Place finished plate into the nest; handle fully supported; bore lies over the solid folded LEFT protective panel.
   Fit measured nonabrasive protective pads to consume excess axial cavity; target total pad
   thickness under closure load is {d["protective_pad_total_at_compressed_depth"]:.6f} inch, split across both faces.
   This is a coupon target, not a validated cushion/compression specification.
   Verify actual closed cavity and pad compression: axial free motion must not exceed
   configured depth clearance. Reject loose fit; tune caliper/layer count/pads before use.
6. Wrap left panel under about BOTH left-spine perforated axes, then right panel over about BOTH right-spine axes.
   Do not force the part or crush the nest to obtain closure. Verify fold allowance on real board.
7. Use {config.closure} only after equipment coupons establish penetration, edge distance,
   compression, access and tear resistance. Use a separate closure fixture reference; no closure toolpath is included in the DXF.
   Keep thread/staple ends outside the nest and away from all metal surfaces.
8. Inspect fit, no free sliding, no bore/face contact with closures, and no edge punch-through.
   Keep on HOLD pending acceptance tests. Do not use geometric fit as shipping certification.

Shell blank: {d['flat_shell']}; layout: {d['layout_size']}.
Estimated folded envelope: {d['folded_envelope_estimate']}; confirm by physical measurement.
Net board area {d['board_net_area_in2']:.3f} in2; gross component area {d['board_gross_area_in2']:.3f} in2.
Fixture reference is separate from the cardboard DXF and is NOT a fixture machining drawing.
"""
    # True-proportion overview; SVG uses the same analytic line/arc cut contour.
    lw, lh = d["layout_size"]
    svg = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="-.2 -.2 {lw+.4} {lh+.4}">',
        '<rect x="-.2" y="-.2" width="1000" height="1000" fill="white"/>',
    ]

    def rect(x, y, w, h, color):
        svg.append(
            f'<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="none" stroke="{color}" stroke-width=".025"/>'
        )

    rect(0, 0, *d["flat_shell"], "#5f452a")
    for layer, axes in d["perforation_axes"].items():
        for x in axes:
            for y1, y2 in perforations(H, config):
                svg.append(
                    f'<path d="M {x} {y1} V {y2}" stroke="#2269ad" stroke-width=".03"/>'
                )
    for x, y in [d["center_nest_position"]] + d["frame_positions"]:
        if (x, y) != tuple(d["center_nest_position"]):
            rect(x, y, W, H, "#5f452a")
        svg.append(
            f'<path d="{svg_path(d["nest_segments"], x, y)}" fill="#eee" stroke="#b34326" stroke-width=".02"/>'
        )
    svg.append("</svg>")
    fixture = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="-1 -1 {W+2} {H+2}">
<rect x="0" y="0" width="{W}" height="{H}" fill="#eee" stroke="black" stroke-width=".03"/>
<path d="M -.2 {H} V -.2 H {W}" fill="none" stroke="#2269ad" stroke-width=".15"/>
<text x=".1" y=".5" font-size=".18">REFERENCE ONLY - SQUARE STOPS</text>
<text x=".1" y=".8" font-size=".15">Removable stops; closure access all edges</text></svg>"""
    files = {
        "packaging.dxf": dxf_bytes(spec, config, d),
        "geometry.json": (
            json.dumps(d["geometry_report"], sort_keys=True, indent=2) + "\n"
        ).encode("ascii"),
        "assembly.md": instructions.encode("ascii"),
        "schedule.json": (json.dumps(report, sort_keys=True, indent=2) + "\n").encode(
            "ascii"
        ),
        "layout.svg": "\n".join(svg).encode("ascii"),
        "fixture-reference.svg": fixture.encode("ascii"),
        "inputs.json": (
            json.dumps(
                {
                    "spec": canonical_specification(spec),
                    "configuration": asdict(config),
                    "parent": parent,
                },
                sort_keys=True,
                indent=2,
            )
            + "\n"
        ).encode("ascii"),
    }
    manifest = {
        "generator_version": VERSION,
        "parent": parent,
        "physical_validation": "REQUIRED",
        "files": {
            k: {"sha256": sha256(v).hexdigest(), "size": len(v)}
            for k, v in sorted(files.items())
        },
    }
    files["manifest.json"] = (
        json.dumps(manifest, sort_keys=True, indent=2) + "\n"
    ).encode("ascii")
    return files
