# GOTCHI V1 Printable Enclosure (`cad/` — Revision 4)

Parametric `trimesh` + `manifold3d` CAD generator and studio/orthographic renderer for the **GOTCHI V1** two-part pocket enclosure and tactile button caps.

## Revision 4 Summary (`36.4 × 60.2 × 20.8 mm` / `45.6 cm³`)

Compared to Revision 1–3 (`38.0 × 72.0 × 29.0 mm` / `79.3 cm³`), Revision 4 replaces solid bounding-box placeholders with **true multi-feature 3D component geometry** and flex-cable clearances, achieving a **42.5% volume reduction** (`8.2 mm` thinner, `11.8 mm` shorter, `4.2 mm` slim side bezels):

1. **Forward-Firing E-Paper Display & Camera (`+Z` Front Face):**
   - **Waveshare 1.54" E-Paper Module V2 (`33.0 × 48.0 mm`):** Unscrewing the 4 removable factory brass hex standoffs reduces the upper `40.0 mm` of the module to a **`2.7 mm` flat glass+PCB laminate** (`z = -1.45..-4.1 mm`) behind a `28.0 × 28.0 mm` front viewing window (`4.2 mm` side bezels).
   - **Display Top FPC Relief Pocket:** A `16.5 × 4.8 × 1.8 mm` relief pocket on the underside of the front bezel (`y = +17.8..+22.6 mm, z = -0.8..-2.6 mm`) protects the display's folded 24-pin top FPC ribbon from clamping pressure.
   - **Forward-Firing Camera (`OV2640` / `OV3660` / `OV5640`, `8.5 × 8.5 × 4.8 mm`):** Sits in the upper-right Front Crown (`x = +10.2, y = +26.9 mm`) and fires straight forward (`+Z`) through a `Ø 7.6 mm` front aperture above the screen. Its `6 mm` orange 24-pin FPC flex ribbon exits the right end of the horizontal Sense daughterboard (`x = +4.5 mm`) and curves 90° forward into the camera cradle—adding zero `Z` thickness and zero `Y` height penalty.

2. **Upward-Pointing Digital PDM Microphone (`+Y` Top Wall):**
   - **Horizontal XIAO ESP32S3 + Sense Stack (`21.0 × 17.5 × 7.8 mm`):** Mounts horizontally in the Top Crown (`x = -16.5..+4.5 mm, y = +22.8..+30.6 mm`) with the **Sense expansion PCB surface facing UPWARD (`+Y`)**.
   - **PDM MEMS Microphone (`MSM261D3526H1CPM`):** Soldered on the top face of the Sense daughterboard (`x = -2.5, z = -11.2 mm`), firing straight **UPWARD (`+Y`)** through a `1.5 mm` acoustic waveguide (`Ø 2.2 mm`) in the top wall.
   - **Left-Wall USB-C Port (`-X`):** Exits cleanly out the upper-left side wall (`y = +24.8, z = -11.2 mm`).

3. **Stepped Multi-Tier `Z` Stack (`20.8 mm` Total Depth):**
   - Because the Waveshare PCB's `4.8 mm` tall white 8-pin `PH2.0` connector is localized to the bottom `6.4 mm` edge (`y = -25.4..-19.0 mm, z = -4.1..-8.7 mm`), the **`803040` LiPo battery (`30.0 × 40.0 × 8.0 mm`)** nestles directly behind the flat upper `40.0 mm` of the display PCB (`y = -18.2..+21.8 mm, z = -6.2..-14.2 mm`), while the tall `PH2.0` plug sits in the bottom chin strip *below* the battery—saving `~8.0 mm` of dead `Z` thickness.
   - **Rear Slim Audio Layer (`z = -15.2..-19.2 mm`):** The `MAX98357A` I2S amplifier (`19.0 × 17.8 × 3.0 mm`) and `15 × 10 × 3.5 mm` speaker sit behind the battery/PH2.0 plane with a 5-slot rear acoustic grille (`z = -20.8 mm`).

---

## Build & Render Commands

Pure Python (`trimesh`, `manifold3d`, `matplotlib`, `Pillow`) — no external Blender binary required:

```bash
python3 cad/build_case.py --out cad
python3 cad/render_labeled.py --out cad
```

`build_case.py` verifies `is_watertight == True` on every printable STL and runs pairwise 3D boolean intersection checks across all 6 multi-feature internal components and both shell halves (`0.00 mm³` interference required).

---

## Generated Files

| Path | Description |
|---|---|
| `cad/build_case.py` | Parametric CSG generator (`manifold3d`) + 3D collision verifier + print-oriented STL exporter. |
| `cad/render_labeled.py` | Studio 3-point lit 3D renderer (`ax.set_box_aspect`) + labeled orthographic top/side CAD diagram generator. |
| `cad/stl/gotchi_front.stl` | Front shell (`36.4 × 60.2 × 8.8 mm`), flipped 180° onto its flat front face (`Z = 0`) for support-free printing. |
| `cad/stl/gotchi_back.stl` | Back shell (`36.4 × 60.2 × 12.0 mm`), resting on its flat rear face (`Z = 0`) for support-free printing. |
| `cad/stl/gotchi_button_cap.stl` | Tactile actuator cap (`Ø 5.5 × 3.8 mm`, print `2x`), resting on its flat flange (`Z = 0`). |
| `cad/renders/front_iso.png` | Assembled front-top-left isometric studio render. |
| `cad/renders/back_iso.png` | Assembled back-top-right isometric studio render. |
| `cad/renders/front_straight.png` | Straight-on front orthographic render (`4.2 mm` side bezels + forward camera aperture). |
| `cad/renders/back_layout.png` | Open internal 3D multi-tier packaging render with color-coded non-cubic components. |
| `cad/renders/exploded.png` | Exploded multi-tier stack render (`Front -> Display/Cam -> XIAO/Battery -> Amp/Speaker -> Back`). |
| `cad/renders/top_labeled.png` | Annotated front/top-down internal packaging diagram (`36.4 × 60.2 mm`). |
| `cad/renders/side_labeled.png` | Annotated side cross-section diagram (`60.2 × 20.8 mm`) showing the stepped `Z` stack. |

---

## Recommended FDM Print Settings (Ender-3 V2 / Textured PEI)

- **Material:** PLA or PETG
- **Layer Height:** `0.16 mm` or `0.20 mm` (`0.4 mm` nozzle)
- **Wall Loops:** `3` (`1.2 mm` perimeters)
- **Infill:** `15%–20%` Gyroid
- **Supports:** **None (`0`)** — both shells print flat on their outer faces (`gotchi_front.stl` front-face down, `gotchi_back.stl` rear-face down) with zero unsupported spans.
- **Bed Adhesion:** **Zero brim / zero raft (`brim_width = 0`, `raft_layers = 0`)** — detached 1-loop purge skirt only (`skirt_loops = 1`).
- **Fasteners:** `4x M2 × 16 mm` screws inserted from the rear counterbores (`Ø 3.8 mm`) into the front `Ø 1.75 mm` self-tapping pilot bosses. The bottom two M2 bosses (`x = ±14.0, y = -23.0 mm`) pass directly through the Waveshare 1.54" PCB's lower M2 mounting holes to lock display alignment.
