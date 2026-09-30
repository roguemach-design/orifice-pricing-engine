# REVIEW ONLY - NOT RELEASED FOR MACHINE USE
Generator: haas-bore-review-1
Job: SYNTHETIC-001; part: SAMPLE-PLATE; drawing: R1
Record SHA256: 208e7a116879e9ddacbe92b7450833bf46743b57bcc811022ddfa12293541d2b
Profile SHA256: bd22431761e8912fddc05c530bd53d0462dbd981f69d8fb53501326b5b1dbd3e
Reviewed by: SYNTHETIC TEST REVIEWER; reference: TEST FIXTURE ONLY
Source: manual; SHA256: 0000000000000000000000000000000000000000000000000000000000000000
Machine: VF-YT EXACT MODEL UNKNOWN; control: UNKNOWN
Profile verifier: UNVERIFIED

Z0 = plate bottom / fixture datum; G54 Z must remain unchanged.
Load T20 WIPS, T1 59845W, T2 07029; verify holders, stickout, calibration and H offsets.
H offsets T1/T2/T20: 1/2/20
Setting 40: DIAMETER; D1 geometry=0; wear=0
Cut Z=-0.02; verified fixture clearance below=0.05
Probe ball center Z=0.057500; programmed physical tip Z=0.032500
Rough center endpoint=0.514000; finish center radius=0.524000
Rough spiral pitch .035 radial/revolution; cleanup circle leaves .010 radial finish stock.
Pitch is not a claim of constant instantaneous cutter engagement or validated chip load.
Expected wear-adjusted diameter=1.548000
Feeds/RPM rough: 15/3000; finish: 10/3000; chamfer: 8/2000
Final probe cycle has no S or T argument. Record #188 at M00; no automatic correction/recut.
Inspection is a blank operator form, not evidence a measurement occurred.
Top bore edge chamfer only; width is radial and angle is 45 degrees from plate face.

HOLD findings:
- machine profile has no verifier
- verify machine_identity_and_control
- verify fixture_and_clamp_clearance
- verify g54_fixture_z
- verify travel_and_toolchange
- verify tool_geometry_and_h_offsets
- verify setting40_and_d_wear
- verify material_feeds_and_spindle
- verify wips_calibration_and_macros
- verify probe_xy_only
- verify probe_measurement_only
- verify probe_result_variable
- verify rough_bore_envelope

Simulation limitations:
- Geometry preview only: not Haas control emulation or collision certification
- G41 radial lead transition depends on installed cutter-comp mode and control
- Probe internal motions, clamps, holders, toolchange and machine retract require on-machine verification

Before machine use: programmer reviews the exact hashed bundle, verifies the actual setup,
and performs a controlled prove-out under shop procedure. This generator has no release operation.
NC candidate is entirely commented after an alarm and M30. Do not strip guards to treat it as approved.
