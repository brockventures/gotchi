# GOTCHI V1 case (`cad/`)

Parametric Blender script for the V1 two-part pocket case plus button cap.
One script generates everything: STL files in print orientation, a `.blend` of the assembled
design, and five PNG renders (`front_iso`, `front_straight`, `back_iso`, `back_layout`, `exploded`).

## Run

```bash
blender -b --python cad/build_case.py -- --out cad
ls -la cad/stl cad/renders
```

Blender 4.0.2, headless only. Exits 0 when every part has `nonmanifold=0`; exits 1 on any
Python error or non-manifold edge. Re-running leaves `cad/gotchi_case.blend1` (Blender's backup);
delete it before committing.

Units: 1 Blender unit = 1 mm. X = width, Y = height (+Y top), Z = depth. Front face z=0,
back face z=-29. XY origin at the centre of the case outline.

## Files

| Path | What |
|---|---|
| `build_case.py` | Generator. All dimensions in the `P` dict at the top. |
| `stl/gotchi_front.stl` | Front half, print orientation (front face down). 38 x 72 x 11. |
| `stl/gotchi_back.stl` | Back half, print orientation (back face down). 38 x 72 x 18. |
| `stl/gotchi_button_cap.stl` | Button cap, flange down. 5.5 x 5.5 x 4.0. |
| `gotchi_case.blend` | Assembled design geometry (front, back, cap offset to x=50). |
| `renders/front_iso.png`, `back_iso.png` | Cycles CPU, 32 samples, 900x900, white background, sun lamp. |
| `renders/exploded.png` | Back half moved -35 Z; placeholders at assembled coordinates (render only, never in STLs). The display placeholder sits inside the front shell and shows only as a sliver from this camera. |

## Print settings

- Material: PLA or PETG
- Layer height: 0.2 mm
- Walls: 3
- Infill: 20%
- Supports: none (per spec). Not verified by slicing; check the overhang preview in the slicer before
  printing. The halves print on their outer faces.

## Hardware

- 4x M2 x 20 screws (through the back clearance holes into the front pilot holes).
- **Not yet in `docs/BOM.md`.** Add them to the BOM before ordering.

## Parameters

Generated from the `P` dict in `build_case.py`. Change values there, then re-run.

| Parameter | Value | Parameter | Value |
|---|---|---|---|
| `wall` | 2.0 | `usb_h` | 4.5 |
| `W_out` | 38.0 | `usb_cz` | -13.6 |
| `H_out` | 72.0 | `cam_hole_d` | 9.0 |
| `D_out` | 29.0 | `cam_cx` | 0.0 |
| `W_in` | 34.0 | `cam_cy` | -24.0 |
| `H_in` | 68.0 | `boss_d` | 5.0 |
| `split_z` | -11.0 | `boss_x` | 14.5 |
| `edge_bevel` | 2.0 | `boss_y` | 31.0 |
| `bevel_segments` | 6 | `pilot_d` | 1.7 |
| `disp_w` | 33.0 | `clear_d` | 2.4 |
| `disp_h` | 48.0 | `cbore_d` | 4.2 |
| `disp_d` | 9.0 | `cbore_depth` | 1.5 |
| `disp_cy` | 4.0 | `btn_x` | 8.0 |
| `win_w` | 28.4 | `btn_cz` | -18.0 |
| `win_h` | 28.4 | `btn_hole_d` | 3.8 |
| `win_off_x` | 0.0 | `sw_cy` | -24.0 |
| `win_off_y` | 0.0 | `sw_cz` | -18.0 |
| `plate_t` | 1.2 | `sw_slot_z` | 5.0 |
| `plate_y_top` | 28.0 | `sw_slot_y` | 2.0 |
| `plate_y_bot` | -14.0 | `spk_cx` | 9.0 |
| `bat_w` | 30.0 | `spk_cy` | 20.0 |
| `bat_h` | 40.0 | `spk_w` | 15.4 |
| `bat_d` | 7.8 | `spk_h` | 10.4 |
| `bat_cy` | 7.0 | `spk_d` | 3.5 |
| `xiao_w` | 21.0 | `grille_d` | 1.5 |
| `xiao_h` | 17.8 | `grille_nx` | 4 |
| `xiao_d` | 15.0 | `grille_ny` | 3 |
| `xiao_cy` | -24.1 | `grille_pitch` | 3.0 |
| `xiao_z_front` | -12.0 | `amp_cx` | -6.0 |
| `usb_w` | 10.0 | `amp_cy` | 5.0 |
| `mic_d` | 2.0 | | |
| `mic_cx` | 6.0 | | |
| `mic_cy` | -24.0 | | |

## Solver notes (geometry choices that do not change any parameter)

- **Cylinder tessellation (applied pre-emptively, not shown necessary).** Every cylinder (48 segments)
  is rotated half a segment about its axis, so no vertex sits on the tangent line where the r=2.5
  bosses meet the wall at x=±17 and the XIAO rib faces at x=±12. Whether an unrotated cylinder fails
  was not tested. The defect that was observed is the coplanar boss top (next bullet). Vertices stay on r=2.5, but the polygon's axis-aligned
  extent is 4.99 mm (2.5 x cos 3.75 deg) instead of 5.00. The cap bbox reads 5.49 for the same reason.
- **Boss top embedded 0.01 mm into the front wall** (z=-1.99, spec says -2.0). An exactly coplanar
  face against the wall underside gave one non-manifold edge per boss under EXACT union.
- **Holes are one boolean each** (window, pilots, USB, back holes). With all front cutters in one
  operand, the front came out at 1146 verts with 8 non-manifold edges and a 73 mm Y extent. Splitting
  them cleared it. Each cutter alone was clean. The exact mechanism was not isolated.
- **Stem overlaps flange by 0.01 mm** on the button cap (stem starts z=0.99). Avoids a coplanar union.
- **Denoising off, Standard view transform.** This Blender build has no OpenImageDenoiser, and
  AgX would tint the white background grey.
- **STL export** uses `export_mesh.stl` on Blender 4.0.2 (no `wm.stl_export` in 4.0). The script
  tries `wm.stl_export` first and falls back on AttributeError.

## Collisions and assumptions (spec numbers kept as written)

1. **Split-face rim (fixed in rev 3).** The split-face edges are no longer bevelled, so both
   halves meet on a full 2 mm wall.
2. **XIAO collision (fixed in rev 3).** The XIAO now sits behind the display plane,
   z -12..-27, in the back half's bottom bay. The USB-C slot moved to the back half's bottom
   wall at `usb_cz=-13.6`. The script prints an envelope overlap check; rev 3 reports
   `collisions: none`.
3. **Switch placeholder 4.0 mm in Y vs frame inner 3.9 mm.** 0.1 mm interference. The real switch
   body dimensions are unknown; the placeholder is 3.5 x 4.0 x 8.6.
4. **Speaker frame outer edge at x=17.7** runs 0.7 mm into the side wall (x 17..19). Benign: it merges.
5. **Button cap stem** starts 0.01 mm inside the flange (see solver notes).
6. **Amp placement** is not specified. The placeholder sits at z -20..-24, behind the battery.
7. **Battery placeholder** z -12.2..-20 is an assumption from the plate and `bat_d`.
8. **Exploded view.** Front half and placeholders in place, back half moved -45 Z.

## Fit-test checklist

- [ ] **Display window offset.** The panel position on the module PCB is unconfirmed. Adjust
      `win_off_x` / `win_off_y`.
- [ ] **Display module depth.** `disp_d` is assumed 9.0 mm (rev 2; was 7.0).
- [ ] **Display bay depth 9.0 mm**: confirm the PH2.0 rear header clears the XIAO side ribs and the back-half display plate.
- [ ] **PDM mic port**: confirm the microphone's acoustic port lines up with (mic_cx, mic_cy) and that a 2.0 mm port is not blocked by the camera or by foam tape. Position assumed, not measured.
- [ ] **USB-C slot height.** `usb_cz` is assumed -13.6 (XIAO front face at -12.0 plus 1.6).
- [ ] **Camera lens position.** `cam_cx` / `cam_cy` are assumed (0, -24).
- [ ] **XIAO** is held by the side ribs plus foam tape. Confirm the ribs clear the board (see collision 2).
- [ ] **Amp** is held by foam tape.
- [ ] **Button caps** slide freely in the 6.4 mm sockets.
- [ ] **Slide switch** sits in the 9.0 x 3.9 frame (see collision 3).
