"""Tri-fold shell + stacked center frames, units inch. No pricing/shipping authority."""

from dataclasses import asdict, dataclass
from hashlib import sha256
from io import StringIO
import json
from math import ceil, cos, sin, pi, acos, isfinite
from html import escape
import ezdxf
from shapely.geometry import Polygon
from shapely import affinity
from plate_geometry import build_plate_geometry, canonical_specification
from manufacturing_files import _DXF_LOCK
from . import VERSION

SAMPLE_ERROR = 0.0001
LAYERS = (
    "CUT_SHELL",
    "CUT_FRAME",
    "CUT_NEST",
    "SCORE_FOLD",
    "PERF_FOLD",
    "REGISTRATION_REFERENCE",
    "ASSEMBLY_REFERENCE",
    "CLOSURE_GUIDE",
)


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
    plate = sampled_outline(spec)
    cut_offset = config.clearance - config.kerf / 2 + SAMPLE_ERROR
    nest = plate.buffer(cut_offset, quad_segs=64)
    if nest.geom_type != "Polygon" or not nest.is_valid or len(nest.interiors):
        raise ValueError("nest offset topology unsupported")
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
    # Nest rotates to align the long handle with panel height.
    nest = affinity.rotate(nest, 90, origin=(0, 0))
    nest = affinity.translate(
        nest, xoff=W / 2, yoff=config.margin + spec.finished_od / 2
    )
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
        for i in range(n)
    ]
    sheet_width = max(flat_width, max(x + W for x, y in positions))
    sheet_height = max(y + H for x, y in positions)
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
        board_net_area_in2=flat_width * H + n * (W * H - nest.area),
        board_gross_area_in2=flat_width * H + n * W * H,
        nest=nest,
    )


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
            for x in (W, d["center_x"], d["center_x"] + W, d["right_x"]):
                m.add_line((x, 0), (x, H), dxfattribs={"layer": "SCORE_FOLD"})
            for i, (x, y) in enumerate(d["frame_positions"]):
                rectangle(x, y, W, H, "CUT_FRAME")
                m.add_lwpolyline(
                    [(px + x, py + y) for px, py in d["nest"].exterior.coords[:-1]],
                    close=True,
                    dxfattribs={"layer": "CUT_NEST"},
                )
                m.add_text(
                    f"NEST LAYER {i+1}",
                    dxfattribs={
                        "height": 0.12,
                        "layer": "ASSEMBLY_REFERENCE",
                        "insert": (x + 0.1, y + 0.1),
                    },
                )
            # Closed peripheral stitch/staple guide: references only, never toolpath cuts.
            e = config.closure_edge_distance
            for x in (0, d["center_x"], d["right_x"]):
                rectangle(x + e, e, W - 2 * e, H - 2 * e, "CLOSURE_GUIDE")
            m.add_line(
                (d["center_x"], 0),
                (d["center_x"] + 0.2, 0.2),
                dxfattribs={"layer": "REGISTRATION_REFERENCE"},
            )
            m.add_text(
                "PROTOTYPE - INCH - SCORE IS NOT CUT - NO CAM KERF ON NEST",
                dxfattribs={
                    "height": 0.12,
                    "layer": "ASSEMBLY_REFERENCE",
                    "insert": (0.2, H / 2),
                },
            )
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
    report = {k: v for k, v in d.items() if k != "nest"}
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
        contour_sampling_error_bound=SAMPLE_ERROR,
        nest_cut_compensation="internal cut: clearance minus half kerf plus sampling error; disable CAM kerf",
    )
    instructions = f"""# PROTOTYPE PACKAGE - PHYSICAL VALIDATION REQUIRED

Parent: {json.dumps(parent,sort_keys=True)}
Generator: {VERSION}; configuration {config.version}
Units: inch. One part per package; make {spec.quantity} separate packages.
Board: {config.board_reference}; measure caliper {config.caliper} before cutting.
Flutes run in flat-sheet X, perpendicular to vertical score axes; verify fold coupons.

1. Load the DXF in inches. CUT_SHELL, CUT_FRAME, CUT_NEST are through-cut contours.
2. SCORE_FOLD is four crease/score axes defining two wrapping spines. It is NOT a through-cut.
   PERF_FOLD is reserved and empty: do not perforate until fold/tear strength is tested.
3. All REFERENCE and GUIDE layers are non-cut setup aids. Nest cutter-center geometry includes
   configured kerf; disable extra CAM compensation on CUT_NEST. Outer contours are nominal;
   accept loss of half kerf in external protective margin. Verify kerf with a coupon.
4. Place the shell center solid backing panel in a square-stop fixture. Stack {d['nest_layers']} center
   frames with their matching openings aligned. Minimum compressed nest depth
   {d['compressed_nest_depth']:.6f}; nominal uncompressed depth {d['nominal_nest_depth']:.6f}.
5. Place finished plate into the nest; handle fully supported; bore lies over SOLID backing.
   Fit measured nonabrasive protective pads to consume excess axial cavity; target total pad
   thickness under closure load is {d["protective_pad_total_at_compressed_depth"]:.6f} inch, split across both faces.
   This is a coupon target, not a validated cushion/compression specification.
   Verify actual closed cavity and pad compression: axial free motion must not exceed
   configured depth clearance. Reject loose fit; tune caliper/layer count/pads before use.
6. Wrap left panel about BOTH first-spine scores, then right panel about BOTH second-spine scores.
   Do not force the part or crush the nest to obtain closure. Verify fold allowance on real board.
7. Use {config.closure} only after equipment coupons establish penetration, edge distance,
   compression, access and tear resistance. Guide projects onto final folded panel perimeter.
   Keep thread/staple ends outside the nest and away from all metal surfaces.
8. Inspect fit, no free sliding, no bore/face contact with closures, and no edge punch-through.
   Keep on HOLD pending acceptance tests. Do not use geometric fit as shipping certification.

Shell blank: {d['flat_shell']}; layout: {d['layout_size']}.
Estimated folded envelope: {d['folded_envelope_estimate']}; confirm by physical measurement.
Net board area {d['board_net_area_in2']:.3f} in2; gross component area {d['board_gross_area_in2']:.3f} in2.
Fixture reference is separate from the cardboard DXF and is NOT a fixture machining drawing.
"""
    # True-proportion overview; nest positions use exact exported polyline coordinates.
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
    for x in (W, d["center_x"], d["center_x"] + W, d["right_x"]):
        svg.append(
            f'<path d="M {x} 0 V {H}" stroke="#2269ad" stroke-width=".03" stroke-dasharray=".15 .1"/>'
        )
    for x, y in d["frame_positions"]:
        rect(x, y, W, H, "#5f452a")
        pts = " ".join(f"{px+x:.6f},{py+y:.6f}" for px, py in d["nest"].exterior.coords)
        svg.append(
            f'<polygon points="{pts}" fill="#eee" stroke="#b34326" stroke-width=".02"/>'
        )
    svg.append("</svg>")
    fixture = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="-1 -1 {W+2} {H+2}">
<rect x="0" y="0" width="{W}" height="{H}" fill="#eee" stroke="black" stroke-width=".03"/>
<path d="M -.2 {H} V -.2 H {W}" fill="none" stroke="#2269ad" stroke-width=".15"/>
<text x=".1" y=".5" font-size=".18">REFERENCE ONLY - SQUARE STOPS</text>
<text x=".1" y=".8" font-size=".15">Removable stops; closure access all edges</text></svg>"""
    files = {
        "packaging.dxf": dxf_bytes(spec, config, d),
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
