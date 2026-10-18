# Packaging v3: analytic arcs and side finger access

`corrugated-trifold-3-arcs-side-access` replaces the sampled Shapely offset/export
with an analytic parallel contour of `plate_geometry.build_plate_geometry`.
No finished steel, bore, handle-hole, PDF, steel DXF or Haas geometry changes.
The DXF uses one closed 12-vertex LWPOLYLINE per nesting layer, with seven
nonzero bulges: paddle, four canonical tangent corners, and two reliefs.

## Geometry and limits

For clearance c and kerf k, cutter-center offset is c-k/2. Convex radii grow by
that amount; concave neck radii shrink; straight edges shift along the outward
normal. Original arc centers, sweeps and tangent directions remain exact.
Configured clearance must be below the canonical 0.03125-inch neck radius.
At or above that value the concave parallel curve collapses; generation fails
with an engineering explanation rather than fitting guessed arcs or changing
the plate. Sampling is inspection-only (maximum chord deviation 0.00001 inch),
never the DXF or SVG cut geometry. SVG decimal serialization is 10 places.

Both reliefs are on the canonical +Y handle side, LEFT (-X) after the layout's
90-degree rotation. They replace intervals of the long straight edge, with
positive 180-degree circular sweeps, and open into the main pocket. They do not
intersect the steel or cross the tangent transition. Each target diameter is
capped by 0.750 inch, handle width, straight length after three intact bridges,
and the remaining closure/fold margin. Minimum diameter is 0.250 inch. The
bridge minimum is max(0.125 inch, twice nominal board caliper). These are bounded
prototype geometry criteria, not verified strength/ergonomic specifications.
Unsupported two-relief layouts fail safely.

The cutter-center relief radius is target diameter/2 minus k/2. It is a true
semicircle in the DXF. The physical kerf envelope has the target circle diameter;
its intersection with the kerf-expanded handle mouth is rounded rather than a
mathematical semicircle. Do not apply CAM kerf compensation again. For the
standard 5-inch OD / 2-inch handle / 10.5-inch center-to-tip sample, c=.025 and
k=.010: paddle cutter radius 2.520, neck radius .01125, tip radius .05125,
relief cutter diameter .740 and envelope diameter .750 inch. Relief centers
in bore-origin canonical coordinates are (9.84375,1.020) near the tip and
(2.936655251113366,1.020) near the paddle. No notch touches the short end.

The bore center remains fixed relative to each panel. All layers translate the
same analytic contour; no notch-induced recentering. Panel dimensions, folds,
layer-depth logic, protective pads and closure parameters are unchanged.
Net board area uses the exact cutter-center boundary area, including circular
segments, as an estimate excluding physical kerf loss.

## Prospective deployment and preservation

Automatic PACKAGING generation for approvals before 2026-10-18T11:45:31Z (the
owner assignment) retains existing automatic bundles. If none exists, it reports
that explicit owner generation is required. A new generator fingerprint cannot
cause historical regeneration merely by deploying or starting the worker.
Explicit authenticated generation can still create a NEW separately identified
bundle for a current approved parent; it cannot overwrite prior files.
Later approvals use v3 automatically. HAAS staging behavior is unchanged.

The owner download panel retains the latest existing automatic packaging bundle
when no new-profile bundle exists, and explicitly labels its stored generator
version. This narrow compatibility change does not accept older HAAS profiles,
change authorization, or regenerate files on view/download. Old packaging
remains auditable and downloadable under its original hashes. A v3 sample is
not a retroactive replacement for any customer artifact.

## Reproduce and verify

Run `python -m packaging_generator.sample <output-directory>` for a synthetic
5-inch OD, 2-inch handle, 0.500-inch plate bundle (five nesting layers: center
shell plus four frames). It generates the immutable-style manifest, geometry
report, assembly instructions and an independent serialized-DXF audit.
`center-nest.svg` is drawn by decoding the ACTUAL DXF bulges, with a nominal
steel overlay; `layout.svg` shows the complete cutting layout. No production
record is used or created by this command.

`packaging_generator.audit` independently decodes saved DXF vertices/bulges,
checks inch units, closed simple loops, no intersecting/duplicate cuts, seven
arcs/two semicircles per nest and translation-identical layer contours. Tests
also check canonical tangency, compensated radii, clearance, steel exclusion,
reduced narrow-handle reliefs, limits, deterministic bytes, prospective worker
behavior and immutable stored downloads.

All files remain PROTOTYPE / ENGINEERING REVIEW. Physical cutting, actual kerf,
board caliper/compression, folding, finger access, retention, sharp-edge handling,
closure strength and shipping/drop qualification remain outstanding. No
manufacturing release is granted by generation or software inspection.
