# Curated prototype review evidence

These files document accepted reviews; they are not production order files.

- **current/**: Phase 3E sample PDF, rough-blank DXF and internal JSON.
- **chamfer-review/**: explicitly illustrative, non-default chamfer package.
- **phase4/**: R1/R2 packages, exact approval/routing manifest, and two customer UI
  previews. The previews are inert, contain no usable tokens, and are not browser
  compatibility evidence.
- **archive/phase3c/**: historical golden PDF/checksum retained as layout review
  evidence only. It is superseded, not current geometry or a generation input.
- **../tests/fixtures/phase3e-manufacturing-print.sha256**: required current byte
  regression fixture. It remains unchanged.

Disposable screenshots, comparison images, duplicated historical packages, debug
crops and obsolete SVG outputs are intentionally excluded from publication.
The original local accepted branch/commit retains the complete phase history.
Earlier phase reports describe their historical output inventories; not every
historical export is included here.

Regenerate locally with `prototype_manufacturing.py --chamfer-review`,
`scripts/review_phase3e.py`, or `python -m frozen_plate.demo` as documented in
`PHASE4_REVIEW.md`. Generated output is ignored unless intentionally added as
review evidence. SVG is not included in the normal job package. No output here
is approved for actual production manufacture.
