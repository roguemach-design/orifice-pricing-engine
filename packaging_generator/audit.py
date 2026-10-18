"""Independent DXF inspection: decode serialized bulges, never generator segments."""

from io import StringIO
from math import atan, atan2, ceil, cos, sin, acos, pi, hypot
import ezdxf
from ezdxf.math import bulge_to_arc
from shapely.geometry import Polygon, LineString


def decode(polyline, error=0.00001):
    vertices = list(polyline.get_points("xyb"))
    points = []
    arcs = []
    for index, (x, y, b) in enumerate(vertices):
        end = vertices[(index + 1) % len(vertices)][:2]
        if not b:
            points.append((x, y))
            continue
        center, _, _, radius = bulge_to_arc((x, y), end, b)
        sweep = 4 * atan(b)
        start = atan2(y - center.y, x - center.x)
        count = max(2, ceil(abs(sweep) / (2 * acos(max(-1, 1 - error / radius)))))
        points.extend(
            (
                center.x + radius * cos(start + sweep * i / count),
                center.y + radius * sin(start + sweep * i / count),
            )
            for i in range(count)
        )
        arcs.append(
            dict(
                vertex=index,
                center=[center.x, center.y],
                radius=radius,
                sweep_degrees=sweep * 180 / pi,
                bulge=b,
            )
        )
    return Polygon(points), arcs


def inspect(data):
    doc = ezdxf.read(StringIO(data.decode("ascii")))
    if doc.audit().has_errors or doc.units != ezdxf.units.IN:
        raise ValueError("DXF audit/units failure")
    nests = list(doc.modelspace().query('LWPOLYLINE[layer=="CUT_NEST"]'))
    if not nests:
        raise ValueError("no nesting boundaries")
    all_cuts = []
    records = []
    relative = None
    for entity in doc.modelspace():
        if entity.dxftype() == "LWPOLYLINE":
            if not entity.closed:
                raise ValueError("open cutting contour")
            shape, arcs = decode(entity)
            if not shape.is_valid or not shape.exterior.is_simple or shape.area <= 0:
                raise ValueError("invalid cutting topology")
            all_cuts.append(shape.boundary)
            if entity.dxf.layer != "CUT_NEST":
                continue
            verts = list(entity.get_points("xyb"))
            x0, y0, _ = verts[0]
            local = [
                (round(x - x0, 8), round(y - y0, 8), round(b, 10)) for x, y, b in verts
            ]
            if relative is None:
                relative = local
            if local != relative:
                raise ValueError("nest layer geometry does not align by translation")
            semicircles = [a for a in arcs if abs(a["sweep_degrees"] - 180) < 1e-8]
            if len(semicircles) != 2 or len(arcs) != 7 or len(verts) != 12:
                raise ValueError(
                    "expected paddle, four tangent corners and two semicircular reliefs"
                )
            if abs(semicircles[0]["center"][0] - semicircles[1]["center"][0]) > 1e-8:
                raise ValueError("finger reliefs not on one long edge")
            records.append(
                dict(
                    vertices=len(verts),
                    closed=entity.closed,
                    arcs=arcs,
                    area_sampled=shape.area,
                )
            )
        elif entity.dxftype() == "LINE":
            all_cuts.append(
                LineString([tuple(entity.dxf.start)[:2], tuple(entity.dxf.end)[:2]])
            )
    for i, a in enumerate(all_cuts):
        for b in all_cuts[i + 1 :]:
            if a.intersects(b):
                raise ValueError("intersecting or duplicate cuts")
    return dict(
        units="inch",
        dxf_audit="PASS",
        nest_count=len(nests),
        all_nests_translation_identical=True,
        closed_simple_nonintersecting_cuts=True,
        inspection_chord_error_bound=0.00001,
        nests=records,
    )
