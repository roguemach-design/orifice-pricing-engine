# Changed assertion register

Base: `34707eb`. Formatting-only changes are excluded. Each changed assertion is listed, including loop assertions whose expected values changed. Historical fixtures remain unchanged; v4 has separate presentation fixtures.

## tests/test_application_scope.py: test_explicit_state_pdf_json_match_without_transition

Customer labels change; application classification and JSON state coverage stay intact.

- **Replaced:** `assert STATUS_LABELS[state] in labels` — Customer labels change; application classification and JSON state coverage stay intact.
- **Replacement/additional:** `assert 'CUSTOMER CONFIRMATION — NOT RELEASED FOR MANUFACTURE' in labels` — Customer labels change; application classification and JSON state coverage stay intact.

## tests/test_application_scope.py: test_flow_is_not_forced_on_general_plate

Customer labels change; application classification and JSON state coverage stay intact.

- **Replaced:** `assert ('FLOW: HOLD' in labels) == (enabled is True)` — Customer labels change; application classification and JSON state coverage stay intact.
- **Replacement/additional:** `assert not any(('HOLD' in label for label in labels))` — Customer labels change; application classification and JSON state coverage stay intact.
- **Replacement/additional:** `assert ('3. BORE CHAMFER SPECIFIED; DETAIL INCOMPLETE.' in labels) == (enabled is True)` — Customer labels change; application classification and JSON state coverage stay intact.

## tests/test_application_scope.py: test_centreline_description_and_no_invented_requirements

Customer labels change; application classification and JSON state coverage stay intact.

- **Replaced:** `assert '10.500 C/L TO HANDLE END' in labels` — Customer labels change; application classification and JSON state coverage stay intact.
- **Replaced:** `assert 'ASME Y14.5-2018' in labels` — Customer labels change; application classification and JSON state coverage stay intact.
- **Replaced:** `assert 'APPLICATION: RESTRICTION / GENERAL' in labels` — Customer labels change; application classification and JSON state coverage stay intact.
- **Replacement/additional:** `assert '10.50' in labels` — Customer labels change; application classification and JSON state coverage stay intact.
- **Replacement/additional:** `assert 'ASME Y14.5-2018' in joined` — Customer labels change; application classification and JSON state coverage stay intact.
- **Replacement/additional:** `assert 'APPLICATION:' not in joined` — Customer labels change; application classification and JSON state coverage stay intact.
- **Updated expected values:** `assert forbidden not in joined` — Customer labels change; application classification and JSON state coverage stay intact.

## tests/test_controlled_package.py: test_finished_print_identity_and_no_unapproved_gdt

Use requested datum/tolerance/title presentation; preserve package and metadata checks.

- **Replaced:** `assert labels.count('A') == 2 and 'SECTION A-A - NTS' in labels` — Use requested datum/tolerance/title presentation; preserve package and metadata checks.
- **Replaced:** `assert all((value in labels for value in ('.X', '.XX', '.XXX', 'ANGLES')))` — Use requested datum/tolerance/title presentation; preserve package and metadata checks.
- **Replacement/additional:** `assert labels.count('A') == 3 and labels.count('B') == 2` — Use requested datum/tolerance/title presentation; preserve package and metadata checks.
- **Replacement/additional:** `assert 'SECTION A-A' not in joined` — Use requested datum/tolerance/title presentation; preserve package and metadata checks.
- **Replacement/additional:** `assert 'ASME Y14.5-2018' in joined` — Use requested datum/tolerance/title presentation; preserve package and metadata checks.
- **Replacement/additional:** `assert 'PROTOTYPE' not in joined and 'NTS' not in joined` — Use requested datum/tolerance/title presentation; preserve package and metadata checks.
- **Replacement/additional:** `assert all((value in joined for value in ('.XX ±.01', '.XXX ±.005', 'ANGLES ±1°')))` — Use requested datum/tolerance/title presentation; preserve package and metadata checks.
- **Updated expected values:** `assert value in labels` — Use requested datum/tolerance/title presentation; preserve package and metadata checks.
- **Updated expected values:** `assert forbidden not in joined` — Use requested datum/tolerance/title presentation; preserve package and metadata checks.

## tests/test_controlled_package.py: test_none_and_incomplete_emit_no_detail_or_assumed_flow

Use requested datum/tolerance/title presentation; preserve package and metadata checks.

- **Replaced:** `assert ('CHAMFER: INCOMPLETE - HOLD' if state else 'CHAMFER: NONE') in joined` — Use requested datum/tolerance/title presentation; preserve package and metadata checks.
- **Replacement/additional:** `assert ('BORE CHAMFER SPECIFIED; DETAIL INCOMPLETE.' if state else 'BORE EDGES SHARP, NO CHAMFER, FREE OF BURRS.') in joined` — Use requested datum/tolerance/title presentation; preserve package and metadata checks.

## tests/test_controlled_package.py: test_configured_chamfer_detail_exact_values

Use requested datum/tolerance/title presentation; preserve package and metadata checks.

- **Updated expected values:** `assert value in labels` — Use requested datum/tolerance/title presentation; preserve package and metadata checks.
- Assertion expressions unchanged; expected label values or fixture path updated. Use requested datum/tolerance/title presentation; preserve package and metadata checks.

## tests/test_drawing_presentation.py: test_presentation_is_independent_and_labels_stay_exact

The right-facing model and relocated Detail B replace feature clamps and the main section.

- **Updated expected values:** `assert value in labels` — The right-facing model and relocated Detail B replace feature clamps and the main section.
- Assertion expressions unchanged; expected label values or fixture path updated. The right-facing model and relocated Detail B replace feature clamps and the main section.

## tests/test_drawing_presentation.py: test_upward_rotation_and_shortened_handle_only_affect_display

The right-facing model and relocated Detail B replace feature clamps and the main section.

- **Replaced:** `assert v.point(g, (length, 0)) == pytest.approx((v.cx, v.handle_tip), abs=1e-12, rel=0)` — The right-facing model and relocated Detail B replace feature clamps and the main section.
- **Replaced:** `assert v.point(g, (-g.radius, 0)) == (v.cx, v.cy - v.paddle_radius)` — The right-facing model and relocated Detail B replace feature clamps and the main section.
- **Replaced:** `assert v.handle_tip - v.cy < length * v.scale(g) / 2` — The right-facing model and relocated Detail B replace feature clamps and the main section.
- **Replacement/additional:** `assert v.point((length, 0)) == pytest.approx((v.tip_x, v.cy), abs=1e-12, rel=0)` — The right-facing model and relocated Detail B replace feature clamps and the main section.
- **Replacement/additional:** `assert v.point((-g.radius, 0)) == (v.layout.left, v.cy)` — The right-facing model and relocated Detail B replace feature clamps and the main section.
- **Replacement/additional:** `assert v.tip_x - v.cx == pytest.approx((length - v.removed_length) * v.scale)` — The right-facing model and relocated Detail B replace feature clamps and the main section.
- **Replacement/additional:** `assert not v.broken` — The right-facing model and relocated Detail B replace feature clamps and the main section.
- **Replacement/additional:** `assert v.broken and v.removed_length > 0` — The right-facing model and relocated Detail B replace feature clamps and the main section.

## tests/test_drawing_presentation.py: test_section_angle_side_and_flow_survive_nts

The right-facing model and relocated Detail B replace feature clamps and the main section.

- **Replaced:** `assert width > g.spec.thickness * v.scale(g)` — The right-facing model and relocated Detail B replace feature clamps and the main section.
- **Replacement/additional:** `assert len(polys) == 1` — The right-facing model and relocated Detail B replace feature clamps and the main section.
- **Replacement/additional:** `assert max((x for x, y in upper)) - min((x for x, y in upper)) > g.spec.thickness * build_presentation(g).scale` — The right-facing model and relocated Detail B replace feature clamps and the main section.

## tests/test_drawing_presentation.py: test_no_fake_bevel_when_none_or_incomplete

The right-facing model and relocated Detail B replace feature clamps and the main section.

- **Updated expected values:** `assert len(polygon) == 4` — The right-facing model and relocated Detail B replace feature clamps and the main section.
- **Updated expected values:** `assert len({x for x, y in polygon}) == 2` — The right-facing model and relocated Detail B replace feature clamps and the main section.
- **Updated expected values:** `assert len({y for x, y in polygon}) == 2` — The right-facing model and relocated Detail B replace feature clamps and the main section.
- Assertion expressions unchanged; expected label values or fixture path updated. The right-facing model and relocated Detail B replace feature clamps and the main section.

## tests/test_drawing_presentation.py: test_locked_golden_pdf_visual_fixture

The right-facing model and relocated Detail B replace feature clamps and the main section.

- Assertion expressions unchanged; expected label values or fixture path updated. The right-facing model and relocated Detail B replace feature clamps and the main section.

## tests/test_handle_hole.py: test_pdf_svg_enabled_disabled_and_determinism

Only display labels and presentation hash fixtures change; exact artifacts and hole rules stay covered.

- **Replaced:** `assert 'HANDLE HOLE Ø0.3750' in text` — Only display labels and presentation hash fixtures change; exact artifacts and hole rules stay covered.
- **Replaced:** `assert '0.7500 HANDLE END TO HOLE C/L' in text` — Only display labels and presentation hash fixtures change; exact artifacts and hole rules stay covered.
- **Replaced:** `assert 'HANDLE HOLE' not in PdfReader(BytesIO(pdf_bytes(off))).pages[0].extract_text()` — Only display labels and presentation hash fixtures change; exact artifacts and hole rules stay covered.
- **Replacement/additional:** `assert 'Ø.375 THRU' in text` — Only display labels and presentation hash fixtures change; exact artifacts and hole rules stay covered.
- **Replacement/additional:** `assert '.75' in text` — Only display labels and presentation hash fixtures change; exact artifacts and hole rules stay covered.
- **Replacement/additional:** `assert 'THRU' not in PdfReader(BytesIO(pdf_bytes(off))).pages[0].extract_text()` — Only display labels and presentation hash fixtures change; exact artifacts and hole rules stay covered.

## tests/test_handle_hole.py: test_configurator_svg

Only display labels and presentation hash fixtures change; exact artifacts and hole rules stay covered.

- **Replaced:** `assert 'HANDLE HOLE &#8960; 0.3750' in svg` — Only display labels and presentation hash fixtures change; exact artifacts and hole rules stay covered.
- **Replaced:** `assert 'HANDLE END TO HOLE C/L 0.7500' in svg` — Only display labels and presentation hash fixtures change; exact artifacts and hole rules stay covered.
- **Replacement/additional:** `assert 'Ø.375 THRU' in svg` — Only display labels and presentation hash fixtures change; exact artifacts and hole rules stay covered.
- **Replacement/additional:** `assert 'HANDLE END TO HOLE C/L .75' in svg` — Only display labels and presentation hash fixtures change; exact artifacts and hole rules stay covered.

## tests/test_handle_hole.py: test_feature_off_matches_accepted_golden_bytes

Only display labels and presentation hash fixtures change; exact artifacts and hole rules stay covered.

- **Replaced:** `assert sha256(pdf_bytes(g, metadata)).hexdigest() == expected['pdf_sha256']` — Only display labels and presentation hash fixtures change; exact artifacts and hole rules stay covered.
- **Replaced:** `assert sha256(svg.encode()).hexdigest() == expected['configurator_svg_sha256']` — Only display labels and presentation hash fixtures change; exact artifacts and hole rules stay covered.
- **Replacement/additional:** `assert sha256(pdf_bytes(g, metadata)).hexdigest() == revised['pdf_sha256']` — Only display labels and presentation hash fixtures change; exact artifacts and hole rules stay covered.
- **Replacement/additional:** `assert sha256(svg.encode()).hexdigest() == revised['configurator_svg_sha256']` — Only display labels and presentation hash fixtures change; exact artifacts and hole rules stay covered.

## tests/test_landing_convergence.py: test_choices_match_accepted_baseline

Keep original payload/price/DXF/spec checks; substitute reviewed fixtures only for PDF/SVG.

- **Replaced:** `assert fingerprints(calls[-1]) == golden['cases'][index]` — Keep original payload/price/DXF/spec checks; substitute reviewed fixtures only for PDF/SVG.
- **Replacement/additional:** `assert current[key] == (presentation[key] if key in presentation else value)` — Keep original payload/price/DXF/spec checks; substitute reviewed fixtures only for PDF/SVG.

## tests/test_manufacturing.py: test_pdf_receives_finished_values_and_discloses_missing_requirements

Keep exact geometry and supplied requirements while updating paper transforms and labels.

- **Replaced:** `assert any(('BORE TOLERANCE: NOT SPECIFIED - HOLD' in t for t in texts))` — Keep exact geometry and supplied requirements while updating paper transforms and labels.
- **Replacement/additional:** `assert any(('.XXX ±.005' in t for t in texts))` — Keep exact geometry and supplied requirements while updating paper transforms and labels.
- **Replacement/additional:** `assert not any(('HOLD' in t for t in texts))` — Keep exact geometry and supplied requirements while updating paper transforms and labels.

## tests/test_manufacturing.py: test_supplied_requirements_reach_drawing

Keep exact geometry and supplied requirements while updating paper transforms and labels.

- **Replaced:** `assert any(('BORE TOLERANCE: +/- 0.005' in t for t in texts))` — Keep exact geometry and supplied requirements while updating paper transforms and labels.
- **Replaced:** `assert any(('width 0.02; angle 45; side downstream' in t for t in texts))` — Keep exact geometry and supplied requirements while updating paper transforms and labels.
- **Replaced:** `assert 'UPSTREAM' in texts` — Keep exact geometry and supplied requirements while updating paper transforms and labels.
- **Replaced:** `assert "NO. REQ'D." in texts` — Keep exact geometry and supplied requirements while updating paper transforms and labels.
- **Replacement/additional:** `assert 'Ø1.548 ±.005' in texts` — Keep exact geometry and supplied requirements while updating paper transforms and labels.
- **Replacement/additional:** `assert any(('SIZE .020 / ANGLE 45° / SIDE DOWNSTREAM' in t for t in texts))` — Keep exact geometry and supplied requirements while updating paper transforms and labels.
- **Replacement/additional:** `assert any(('MARKING: UPSTREAM' in t for t in texts))` — Keep exact geometry and supplied requirements while updating paper transforms and labels.
- **Replacement/additional:** `assert 'QTY' in texts` — Keep exact geometry and supplied requirements while updating paper transforms and labels.

## tests/test_manufacturing.py: test_pdf_draws_canonical_arcs_and_calls_out_exact_radius

Keep exact geometry and supplied requirements while updating paper transforms and labels.

- **Replaced:** `assert any(('4X R 0.03125' in text for text in texts))` — Keep exact geometry and supplied requirements while updating paper transforms and labels.
- **Replacement/additional:** `assert any(('R.03  4X' in text for text in texts))` — Keep exact geometry and supplied requirements while updating paper transforms and labels.

## tests/test_manufacturing_drawing.py: test_drawing_fields_and_holds

Landscape sheet, proposed notes/standards, and requested inch formatting replace the legacy layout.

- **Updated expected values:** `assert expected in text` — Landscape sheet, proposed notes/standards, and requested inch formatting replace the legacy layout.
- **Updated expected values:** `assert forbidden not in text.upper()` — Landscape sheet, proposed notes/standards, and requested inch formatting replace the legacy layout.
- Assertion expressions unchanged; expected label values or fixture path updated. Landscape sheet, proposed notes/standards, and requested inch formatting replace the legacy layout.

## tests/test_manufacturing_drawing.py: test_letter_layout_and_determinism_for_handle_proportions

Landscape sheet, proposed notes/standards, and requested inch formatting replace the legacy layout.

- **Replaced:** `assert b'/MediaBox [ 0 0 612 792 ]' in first` — Landscape sheet, proposed notes/standards, and requested inch formatting replace the legacy layout.
- **Replacement/additional:** `assert b'/MediaBox [ 0 0 792 612 ]' in first` — Landscape sheet, proposed notes/standards, and requested inch formatting replace the legacy layout.

## tests/test_plate_preview.py: test_svg_contains_customer_dimensions_and_drawing_disclaimer

Measure canonical arcs/fillets at the selected scale, with explicit breaks and updated labels.

- **Replaced:** `assert 'OD &#8960; 3.000 in.' in svg` — Measure canonical arcs/fillets at the selected scale, with explicit breaks and updated labels.
- **Replaced:** `assert 'BORE &#8960; 1.000' in svg` — Measure canonical arcs/fillets at the selected scale, with explicit breaks and updated labels.
- **Replaced:** `assert 'HANDLE 1.500 in.' in svg` — Measure canonical arcs/fillets at the selected scale, with explicit breaks and updated labels.
- **Replaced:** `assert 'C/L TO END 9.000 in.' in svg` — Measure canonical arcs/fillets at the selected scale, with explicit breaks and updated labels.
- **Replaced:** `assert 't = 0.125 in.' in svg` — Measure canonical arcs/fillets at the selected scale, with explicit breaks and updated labels.
- **Replaced:** `assert '&#177; 0.005 in.' in svg` — Measure canonical arcs/fillets at the selected scale, with explicit breaks and updated labels.
- **Replaced:** `assert 'YES &#8212; WIDTH NOT ENTERED' in svg` — Measure canonical arcs/fillets at the selected scale, with explicit breaks and updated labels.
- **Replaced:** `assert 'CONFIGURATION DRAWING &#183; NTS' in svg` — Measure canonical arcs/fillets at the selected scale, with explicit breaks and updated labels.
- **Replacement/additional:** `assert 'OD Ø3.000 in.' in svg` — Measure canonical arcs/fillets at the selected scale, with explicit breaks and updated labels.
- **Replacement/additional:** `assert 'BORE Ø1.000' in svg` — Measure canonical arcs/fillets at the selected scale, with explicit breaks and updated labels.
- **Replacement/additional:** `assert 'HANDLE 1.50' in svg` — Measure canonical arcs/fillets at the selected scale, with explicit breaks and updated labels.
- **Replacement/additional:** `assert 'C/L TO END 9.00 in.' in svg` — Measure canonical arcs/fillets at the selected scale, with explicit breaks and updated labels.
- **Replacement/additional:** `assert 't = .125 in.' in svg` — Measure canonical arcs/fillets at the selected scale, with explicit breaks and updated labels.
- **Replacement/additional:** `assert '±.005 in.' in svg` — Measure canonical arcs/fillets at the selected scale, with explicit breaks and updated labels.
- **Replacement/additional:** `assert 'YES — WIDTH NOT ENTERED' in svg` — Measure canonical arcs/fillets at the selected scale, with explicit breaks and updated labels.
- **Replacement/additional:** `assert 'CONFIGURATION DRAWING · SCALE 1:1' in svg` — Measure canonical arcs/fillets at the selected scale, with explicit breaks and updated labels.

## tests/test_plate_preview.py: test_svg_is_valid_for_small_default_and_maximum_configurations

Measure canonical arcs/fillets at the selected scale, with explicit breaks and updated labels.

- **Replaced:** `assert f'{paddle_dia:.3f} in.' in svg` — Measure canonical arcs/fillets at the selected scale, with explicit breaks and updated labels.
- **Replaced:** `assert f'{bore_dia:.3f}' in svg` — Measure canonical arcs/fillets at the selected scale, with explicit breaks and updated labels.
- **Replaced:** `assert f'HANDLE {handle_width:.3f} in.' in svg` — Measure canonical arcs/fillets at the selected scale, with explicit breaks and updated labels.
- **Replaced:** `assert f'{handle_length:.3f} in.' in svg` — Measure canonical arcs/fillets at the selected scale, with explicit breaks and updated labels.
- **Replaced:** `assert '0.500 in.' in svg` — Measure canonical arcs/fillets at the selected scale, with explicit breaks and updated labels.
- **Replacement/additional:** `assert f'{inch(paddle_dia)} in.' in svg` — Measure canonical arcs/fillets at the selected scale, with explicit breaks and updated labels.
- **Replacement/additional:** `assert f'{inch(bore_dia)}' in svg` — Measure canonical arcs/fillets at the selected scale, with explicit breaks and updated labels.
- **Replacement/additional:** `assert f'HANDLE {inch(handle_width, 2)}' in svg` — Measure canonical arcs/fillets at the selected scale, with explicit breaks and updated labels.
- **Replacement/additional:** `assert f'{inch(handle_length, 2)} in.' in svg` — Measure canonical arcs/fillets at the selected scale, with explicit breaks and updated labels.
- **Replacement/additional:** `assert '.500 in.' in svg` — Measure canonical arcs/fillets at the selected scale, with explicit breaks and updated labels.

## tests/test_plate_preview.py: test_material_thickness_and_chamfer_update_title_block_with_customer_width

Measure canonical arcs/fillets at the selected scale, with explicit breaks and updated labels.

- **Replaced:** `assert '0.125 in.' in stainless` — Measure canonical arcs/fillets at the selected scale, with explicit breaks and updated labels.
- **Replaced:** `assert '0.500 in.' in carbon` — Measure canonical arcs/fillets at the selected scale, with explicit breaks and updated labels.
- **Replaced:** `assert 'YES &#8212; 0.062 in.' in carbon` — Measure canonical arcs/fillets at the selected scale, with explicit breaks and updated labels.
- **Replacement/additional:** `assert '.125 in.' in stainless` — Measure canonical arcs/fillets at the selected scale, with explicit breaks and updated labels.
- **Replacement/additional:** `assert '.500 in.' in carbon` — Measure canonical arcs/fillets at the selected scale, with explicit breaks and updated labels.
- **Replacement/additional:** `assert 'YES — .062 in.' in carbon` — Measure canonical arcs/fillets at the selected scale, with explicit breaks and updated labels.

## tests/test_plate_preview.py: test_outer_profile_has_one_tangent_symmetric_contour

Measure canonical arcs/fillets at the selected scale, with explicit breaks and updated labels.

- **Replaced:** `assert outline.attrib['fill'] != 'none'` — Measure canonical arcs/fillets at the selected scale, with explicit breaks and updated labels.
- **Replaced:** `assert len(root.findall('.//svg:circle', namespace)) == 2` — Measure canonical arcs/fillets at the selected scale, with explicit breaks and updated labels.
- **Replaced:** `assert f'OD &#8960; {od:.3f}' in svg` — Measure canonical arcs/fillets at the selected scale, with explicit breaks and updated labels.
- **Replaced:** `assert f'HANDLE {handle_width:.3f} in.' in svg` — Measure canonical arcs/fillets at the selected scale, with explicit breaks and updated labels.
- **Replaced:** `assert path.count('M ') == 1` — Measure canonical arcs/fillets at the selected scale, with explicit breaks and updated labels.
- **Replaced:** `assert path.count(' A ') == 3` — Measure canonical arcs/fillets at the selected scale, with explicit breaks and updated labels.
- **Replaced:** `assert path.count(' L ') == 2` — Measure canonical arcs/fillets at the selected scale, with explicit breaks and updated labels.
- **Replaced:** `assert path.endswith(' Z')` — Measure canonical arcs/fillets at the selected scale, with explicit breaks and updated labels.
- **Replaced:** `assert match is not None` — Measure canonical arcs/fillets at the selected scale, with explicit breaks and updated labels.
- **Replaced:** `assert fillet_x_radius == fillet_y_radius == lower_fillet_x_radius == lower_fillet_y_radius` — Measure canonical arcs/fillets at the selected scale, with explicit breaks and updated labels.
- **Replaced:** `assert outer_radius_x == outer_radius_y == 110.0` — Measure canonical arcs/fillets at the selected scale, with explicit breaks and updated labels.
- **Replaced:** `assert upper_handle_x == pytest.approx(lower_handle_x, abs=0.002)` — Measure canonical arcs/fillets at the selected scale, with explicit breaks and updated labels.
- **Replaced:** `assert upper_plate_x == pytest.approx(lower_plate_x, abs=0.002)` — Measure canonical arcs/fillets at the selected scale, with explicit breaks and updated labels.
- **Replaced:** `assert upper_plate_y + lower_plate_y == pytest.approx(450.0, abs=0.002)` — Measure canonical arcs/fillets at the selected scale, with explicit breaks and updated labels.
- **Replaced:** `assert upper_handle_y + lower_handle_y == pytest.approx(450.0, abs=0.002)` — Measure canonical arcs/fillets at the selected scale, with explicit breaks and updated labels.
- **Replaced:** `assert end_top_x == end_bottom_x > upper_handle_x > upper_plate_x > 220.0` — Measure canonical arcs/fillets at the selected scale, with explicit breaks and updated labels.
- **Replaced:** `assert end_top_y == upper_handle_y` — Measure canonical arcs/fillets at the selected scale, with explicit breaks and updated labels.
- **Replaced:** `assert end_bottom_y == lower_handle_y` — Measure canonical arcs/fillets at the selected scale, with explicit breaks and updated labels.
- **Replaced:** `assert upper_plate_y < upper_handle_y < lower_handle_y < lower_plate_y` — Measure canonical arcs/fillets at the selected scale, with explicit breaks and updated labels.
- **Replaced:** `assert hypot(upper_plate_x - 220.0, upper_plate_y - 225.0) == pytest.approx(110.0, abs=0.002)` — Measure canonical arcs/fillets at the selected scale, with explicit breaks and updated labels.
- **Replaced:** `assert hypot(upper_plate_x - upper_handle_x, upper_plate_y - fillet_center_y) == pytest.approx(fillet_x_radius, abs=0.002)` — Measure canonical arcs/fillets at the selected scale, with explicit breaks and updated labels.
- **Replaced:** `assert hypot(upper_handle_x - 220.0, fillet_center_y - 225.0) == pytest.approx(110.0 + fillet_x_radius, abs=0.002)` — Measure canonical arcs/fillets at the selected scale, with explicit breaks and updated labels.
- **Replacement/additional:** `assert outline.attrib.get('fill', 'none') == 'none'` — Measure canonical arcs/fillets at the selected scale, with explicit breaks and updated labels.
- **Replacement/additional:** `assert len(root.findall('.//svg:circle', namespace)) == 1` — Measure canonical arcs/fillets at the selected scale, with explicit breaks and updated labels.
- **Replacement/additional:** `assert f'OD Ø{inch(od)}' in svg` — Measure canonical arcs/fillets at the selected scale, with explicit breaks and updated labels.
- **Replacement/additional:** `assert f'HANDLE {inch(handle_width, 2)}' in svg` — Measure canonical arcs/fillets at the selected scale, with explicit breaks and updated labels.
- **Replacement/additional:** `assert path.count('M ') == (2 if v.broken else 1)` — Measure canonical arcs/fillets at the selected scale, with explicit breaks and updated labels.
- **Replacement/additional:** `assert len(arcs) == 5` — Measure canonical arcs/fillets at the selected scale, with explicit breaks and updated labels.
- **Replacement/additional:** `assert sum((float(a[0]) == pytest.approx(g.corner_radius * v.scale, abs=1e-06) for a in arcs)) == 4` — Measure canonical arcs/fillets at the selected scale, with explicit breaks and updated labels.
- **Replacement/additional:** `assert float(paddle[0]) == float(paddle[1]) == g.radius * v.scale` — Measure canonical arcs/fillets at the selected scale, with explicit breaks and updated labels.
- **Replacement/additional:** `assert hypot(px - v.cx, py - v.cy) == pytest.approx(g.radius * v.scale, abs=1e-06)` — Measure canonical arcs/fillets at the selected scale, with explicit breaks and updated labels.
- **Replacement/additional:** `assert hypot(px - lx, py - ly) == pytest.approx(g.corner_radius * v.scale, abs=1e-06)` — Measure canonical arcs/fillets at the selected scale, with explicit breaks and updated labels.
- **Replacement/additional:** `assert hypot(lx - v.cx, ly - v.cy) == pytest.approx((g.radius + g.corner_radius) * v.scale, abs=1e-06)` — Measure canonical arcs/fillets at the selected scale, with explicit breaks and updated labels.
- **Replacement/additional:** `assert ux == pytest.approx(lx)` — Measure canonical arcs/fillets at the selected scale, with explicit breaks and updated labels.
- **Replacement/additional:** `assert uy + ly == pytest.approx(2 * v.cy)` — Measure canonical arcs/fillets at the selected scale, with explicit breaks and updated labels.
- **Replacement/additional:** `assert v.tip_x > ux > px > v.cx` — Measure canonical arcs/fillets at the selected scale, with explicit breaks and updated labels.
- **Replacement/additional:** `assert all((float(a[0]) == float(a[1]) for a in arcs))` — Measure canonical arcs/fillets at the selected scale, with explicit breaks and updated labels.

## tests/test_section_geometry.py: test_each_missing_parameter_is_hold

Only visible incomplete/no-chamfer wording changes; internal HOLD and geometry checks remain.

- **Replaced:** `assert any(('CHAMFER: INCOMPLETE - HOLD' in t for t in labels))` — Only visible incomplete/no-chamfer wording changes; internal HOLD and geometry checks remain.
- **Replacement/additional:** `assert any(('BORE CHAMFER SPECIFIED; DETAIL INCOMPLETE.' in t for t in labels))` — Only visible incomplete/no-chamfer wording changes; internal HOLD and geometry checks remain.
- **Replacement/additional:** `assert not any(('HOLD' in t for t in labels))` — Only visible incomplete/no-chamfer wording changes; internal HOLD and geometry checks remain.

## tests/test_section_geometry.py: test_none_is_distinct_from_incomplete

Only visible incomplete/no-chamfer wording changes; internal HOLD and geometry checks remain.

- **Replaced:** `assert any(('CHAMFER: NONE' in t for t in labels))` — Only visible incomplete/no-chamfer wording changes; internal HOLD and geometry checks remain.
- **Replacement/additional:** `assert any(('BORE EDGES SHARP, NO CHAMFER, FREE OF BURRS.' in t for t in labels))` — Only visible incomplete/no-chamfer wording changes; internal HOLD and geometry checks remain.

