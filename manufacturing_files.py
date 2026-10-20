"""Deterministic prototype exporters; call only from offline tooling for now."""

from html import escape
from io import StringIO
import json
from dataclasses import asdict
from pathlib import Path
from threading import Lock

_DXF_LOCK = Lock()
import ezdxf
import reportlab
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

# Fonts ship with ReportLab; embed them to avoid workstation substitution.
_FONT_DIR = Path(reportlab.__file__).parent / "fonts"
pdfmetrics.registerFont(TTFont("PlateSans", str(_FONT_DIR / "Vera.ttf")))
pdfmetrics.registerFont(TTFont("PlateSansBold", str(_FONT_DIR / "VeraBd.ttf")))
from plate_geometry import PlateGeometry, manufacturing_record, rough_bore_diameter


def dxf_bytes(g: PlateGeometry) -> bytes:
    # Serialize access to ezdxf's process-global fixed metadata option.
    # Isolate this offline exporter in its own worker process upon integration.
    with _DXF_LOCK:
        previous = ezdxf.options.write_fixed_meta_data_for_testing
        try:
            ezdxf.options.write_fixed_meta_data_for_testing = True
            doc = ezdxf.new("R2010")
            doc.units = ezdxf.units.IN
            doc.header["$MEASUREMENT"] = 0
            doc.layers.new("CUT_OUTER", dxfattribs={"color": 7})
            doc.layers.new("CUT_BORE", dxfattribs={"color": 1})
            model = doc.modelspace()
            model.add_lwpolyline(
                g.outer_vertices_xyb,
                format="xyb",
                close=True,
                dxfattribs={"layer": "CUT_OUTER"},
            )
            model.add_circle(
                (0, 0),
                rough_bore_diameter(g.spec) / 2,
                dxfattribs={"layer": "CUT_BORE"},
            )
            if g.spec.handle_hole_enabled:
                doc.layers.new("CUT_HANDLE_HOLE", dxfattribs={"color": 3})
                model.add_circle(
                    (g.spec.centerline_to_handle_end - g.spec.handle_hole_center_from_handle_end, 0),
                    g.spec.handle_hole_diameter / 2,
                    dxfattribs={"layer": "CUT_HANDLE_HOLE"},
                )
            # ezdxf discovers CLASS records from a set; sort before serialization
            # so process hash randomization cannot change file bytes.
            doc.classes.add_required_classes(doc.dxfversion)
            doc.classes.classes = dict(sorted(doc.classes.classes.items()))
            stream = StringIO()
            doc.write(stream)
            return stream.getvalue().encode("ascii")
        finally:
            ezdxf.options.write_fixed_meta_data_for_testing = previous


def preview_svg(g: PlateGeometry) -> str:
    """True-proportion prototype preview, sharing the canonical contour."""
    s = g.spec
    r = g.radius
    first = g.segments[0].start
    commands = [f"M {first[0]} {-first[1]}"]
    for segment in g.segments:
        x, y = segment.end
        if segment.kind == "line":
            commands.append(f"L {x} {-y}")
        else:
            commands.append(
                f"A {segment.radius} {segment.radius} 0 {int(abs(segment.sweep_degrees)>180)} {int(segment.sweep_degrees<0)} {x} {-y}"
            )
    path = " ".join(commands) + " Z"
    hole = ""
    if s.handle_hole_enabled:
        hole = (f'<circle id="handle-hole" cx="{s.centerline_to_handle_end-s.handle_hole_center_from_handle_end}" cy="0" '
                f'r="{s.handle_hole_diameter/2}" fill="white" stroke="black" stroke-width="0.02"/>')

    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{-r-0.5} {-r-0.5} {s.centerline_to_handle_end+r+1} {2*r+1}">'
        f"<title>{escape(s.part_identifier)} - canonical finished geometry, prototype</title>"
        f'<path d="{path}" fill="#edf1f5" stroke="black" stroke-width="0.02"/>'
        f'<circle r="{s.finished_bore_diameter/2}" fill="white" stroke="black" stroke-width="0.02"/>{hole}</svg>'
    )


def drawing_callouts(g: PlateGeometry) -> dict:
    """Finished drawing data: rough-bore dimensions never substitute for these."""
    s = g.spec
    return {
        "finished_od": s.finished_od,
        "finished_bore_diameter": s.finished_bore_diameter,
        "bore_tolerance": s.bore_tolerance,
        "handle_width": s.handle_width,
        "centerline_to_handle_end": s.centerline_to_handle_end,
        "thickness": s.thickness,
    }


def pdf_bytes(g: PlateGeometry, metadata=None) -> bytes:
    from manufacturing_drawing import render_pdf

    return render_pdf(g, metadata)


def generate_package(
    g: PlateGeometry,
    directory: Path,
    stem="sample-plate",
    *,
    include_svg=True,
    metadata=None,
):
    if not stem or any(
        ch not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"
        for ch in stem
    ):
        raise ValueError(
            "stem must contain only letters, digits, underscores or hyphens"
        )
    # Validate/serialize all outputs before writing any file.
    from manufacturing_drawing import DrawingMetadata
    from manufacturing_context import STATUS_LABELS

    metadata = metadata or DrawingMetadata()
    for field in ("flow_orientation", "chamfer_width_definition"):
        if getattr(metadata, field) not in (None, getattr(g.spec, field)):
            raise ValueError(
                "freeze section options into specification before package generation"
            )
    record = manufacturing_record(g)
    record["drawing"] = asdict(metadata)
    record["status"] = STATUS_LABELS[metadata.state]
    outputs = {
        "dxf": dxf_bytes(g),
        "pdf": pdf_bytes(g, metadata),
        "json": (
            json.dumps(record, indent=2, sort_keys=True, allow_nan=False) + "\n"
        ).encode(),
    }
    if include_svg:
        outputs["svg"] = preview_svg(g).encode()
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    for suffix, content in outputs.items():
        (directory / f"{stem}.{suffix}").write_bytes(content)
    return outputs


def generate_job_package(g: PlateGeometry, directory: Path, *, metadata=None):
    """Current paired finished PDF / rough DXF; JSON is an internal audit record.

    Refuse contaminated output folders and noncanonical objects, rather than
    allowing stale files or presentation geometry into a current job package.
    """
    from plate_geometry import build_plate_geometry, GEOMETRY_VERSION

    if g != build_plate_geometry(g.spec):
        raise ValueError("job package requires current canonical geometry")
    record = manufacturing_record(g)
    if record["geometry"]["version"] != GEOMETRY_VERSION:
        raise ValueError("stale geometry version")
    stem = "OP-" + g.spec.part_identifier
    directory = Path(directory)
    expected = {stem + suffix for suffix in (".pdf", ".dxf", ".json", ".png")}
    if directory.exists() and any(p.name not in expected for p in directory.iterdir()):
        raise ValueError(
            "segregate stale or unrelated artifacts before generating job package"
        )
    outputs = generate_package(g, directory, stem, include_svg=False, metadata=metadata)
    # A raster is a review derivative, never authoritative. Invalidate an older
    # render so it cannot silently accompany newly generated specification files.
    (directory / f"{stem}.png").unlink(missing_ok=True)
    return outputs
