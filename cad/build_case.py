#!/usr/bin/env python3
"""
GOTCHI V1 Printable Enclosure — Revision 5 (Dual Upper-Right Side Buttons & Full Switch Collision Verification)
===============================================================================================================
Outer envelope: 36.4 x 60.2 x 20.8 mm (45.6 cm^3 — 42.5% smaller volume than Rev 1's
38.0 x 72.0 x 29.0 mm / 79.3 cm^3 box, 8.2 mm thinner in Z, 11.8 mm shorter in Y,
with slim 4.2 mm side bezels around the 28.0 x 28.0 mm active screen window).

Key Architectural & Packaging Improvements:
1. Forward-Firing Screen & Camera (+Z Front Face):
   - Waveshare 1.54" E-Paper V2 active area (27.6 x 27.6 mm) sits behind a 28.0 x 28.0 mm
     front bezel window (centered at x = 0, y = +3.0 mm) with 4.2 mm side bezels.
   - Camera module (8.5 x 8.5 x 4.8 mm, OV2640 / OV3660 / OV5640) sits in the upper-right
     Front Crown (x = +10.2, y = +26.9 mm) and fires straight FORWARD (+Z) through a
     dia 7.6 mm lens aperture above the display.
   - Its 6 mm wide orange 24-pin FPC flex ribbon exits the right end of the horizontal
     Sense daughterboard (x = +4.5 mm) and makes a gentle 90-deg curve forward into the
     camera pocket — adding zero Z thickness and zero Y height penalty.

2. Upward-Pointing Digital PDM Microphone (+Y Top Wall):
   - Seeed Studio XIAO ESP32S3 + Sense expansion daughterboard (21.0 x 17.5 x 7.8 mm B2B
     stack) mounts horizontally in the Top Crown (x = -16.5..+4.5 mm, y = +22.8..+30.6 mm)
     with the Sense PCB top face oriented UPWARD (+Y).
   - The onboard MSM261D3526H1CPM PDM MEMS microphone (soldered on the top face of the
     Sense board at x = -2.5, z = -11.2 mm) fires straight UPWARD (+Y) through a short
     1.5 mm acoustic waveguide (dia 2.2 mm) in the top wall.
   - The XIAO USB-C port exits cleanly through the left side wall (-X at y = +24.8 mm).

3. Dual Upper-Right Side Buttons (+X Right Wall):
   - Both tactile buttons (`BTN_TOP` for Voice/Live at `y = +20.5 mm`, `BTN_BOT` for Camera/Burst
     at `y = +10.5 mm`) sit on the upper-right side wall (`+X`) at `z = -15.2 mm` (behind the
     battery plane `z = -6.2..-14.2 mm` and in the open right-side corridor beside the left-shifted
     `MAX98357A` amp), leaving the top wall completely clean except for the microphone port.
   - Both `6x6x5mm` tactile switches (`btn_top_tactile`, `btn_bot_tactile`) and the `Mini SPDT`
     power slide switch (`spdt_slide_switch`) are modeled as explicit 3D meshes in
     `build_internal_3d_components()` and verified for `0.00 mm^3` collision against all components
     and enclosure shells.

Usage:
    python3 cad/build_case.py --out cad
"""

import argparse
import math
import os
import sys
import numpy as np
import trimesh
from trimesh.creation import box, cylinder

P = dict(
    W_out=36.4,
    H_out=60.2,
    D_out=20.8,
    y_min=-27.2,
    y_max=33.0,
    wall=1.5,
    front_wall=1.4,
    back_wall=1.5,
    split_z=-8.8,  # Front shell: 0.0 to -8.8 mm (8.8 mm); Back shell: -8.8 to -20.8 mm (12.0 mm)

    # 1. Waveshare 1.54" E-Paper Module V2 (33.0 x 48.0 mm PCB, y = -25.5 to +22.5 mm)
    disp_w=33.0,
    disp_h=48.0,
    disp_cy=-1.5,
    disp_y0=-25.5,
    disp_y1=22.5,
    disp_glass_w=31.8,
    disp_glass_h=37.3,
    disp_glass_y0=-16.0,
    disp_glass_y1=21.3,
    disp_glass_z0=-1.45,
    disp_glass_z1=-2.5,
    disp_pcb_z0=-2.5,
    disp_pcb_z1=-4.1,
    disp_smd_z1=-5.5,
    # Active screen window (27.6 x 27.6 mm active; 28.0 x 28.0 mm bezel aperture)
    win_w=28.0,
    win_h=28.0,
    win_cy=3.0,  # y = -11.0 to +17.0 mm
    # Display top 24-pin FPC ribbon fold & rear ZIF connector (y = +18.0 to +22.4 mm)
    disp_fpc_w=16.5,
    disp_fpc_y0=18.0,
    disp_fpc_y1=22.4,
    disp_zif_z1=-5.9,
    # Display bottom 8-pin PH2.0 right-angle connector (y = -25.4 to -19.0 mm, below the 40mm battery)
    ph20_w=18.5,
    ph20_y0=-25.4,
    ph20_y1=-19.0,
    ph20_z1=-8.7,

    # 2. 803040 LiPo Battery (30.0 x 40.0 x 8.0 mm) nestled behind flat upper/middle display PCB
    bat_w=30.0,
    bat_h=40.0,
    bat_d=8.0,
    bat_cy=1.8,
    bat_y0=-18.2,
    bat_y1=21.8,
    bat_z0=-6.2,
    bat_z1=-14.2,

    # 3. Top Crown (y = +22.8 to +31.4 mm):
    #    Left side (x = -16.5 to +4.5 mm): Horizontal XIAO ESP32S3 + Sense Stack (Sense PCB + PDM Mic facing UP +Y)
    #    Right-front (x = +6.0 to +14.5 mm): Forward-firing Camera (+Z) fed by 90-deg FPC flex ribbon from Sense x=+4.5mm
    xiao_x0=-16.5,
    xiao_x1=4.5,    # 21.0 mm length along X (USB-C at left wall x=-16.5; camera FPC header at x=+4.5)
    xiao_y0=22.8,
    xiao_y1=30.6,   # 7.8 mm B2B stack height along Y (+ 0.8 mm MEMS mic on top = 31.4 mm < 31.5 mm top inner wall)
    xiao_z0=-2.0,
    xiao_z1=-19.2,  # 17.2 mm width along Z
    # Upward-pointing PDM MEMS microphone on top face of Sense PCB (y = +31.4, firing straight UP +Y in back half)
    mic_cx=-2.5,
    mic_cz=-11.2,
    mic_d=2.2,
    # Left-wall USB-C port (-X wall at y = 24.8, z = -11.2)
    usb_cy=24.8,
    usb_cz=-11.2,
    usb_w=9.4,   # along Z
    usb_h=3.8,   # along Y

    # 4. Forward-firing Camera (OV2640/OV3660/OV5640) on 90-deg curved FPC flex ribbon
    cam_w=8.5,
    cam_h=8.5,
    cam_cx=10.2,    # Upper-right front crown beside XIAO (x = +5.95 to +14.45 mm)
    cam_cy=26.9,    # Above display PCB (y = +22.65 to +31.15 mm)
    cam_lens_d=7.6,
    cam_z0=-1.0,
    cam_z1=-5.8,

    # 5. Rear Slim Audio Layer (z = -15.2 to -19.2 mm, behind battery & PH2.0 zone)
    amp_w=19.0,
    amp_h=17.8,
    amp_d=3.0,
    amp_cx=-5.5,
    amp_cy=-1.5,    # y = -10.4 to +7.4 mm
    amp_z0=-15.2,
    amp_z1=-18.2,

    spk_w=15.0,
    spk_h=10.0,
    spk_d=3.5,
    spk_cx=7.5,
    spk_cy=-19.0,   # y = -24.0 to -14.0 mm
    spk_z0=-15.7,
    spk_z1=-19.2,

    # 6. Controls:
    # Both BTN_TOP (PTT/Voice) and BTN_BOT (Camera/Burst) stacked on the Upper-Right Side Wall (+X wall)
    # at z = -15.2 mm (behind battery plane z = -6.2..-14.2 mm, in the clear right-rear corridor x = +11.7..+16.7 mm)
    ptt_cy=20.5,    # Upper-right side button (BTN_TOP — Voice / Live)
    ptt_cz=-15.2,
    snap_cy=10.5,   # Lower-right side button (BTN_BOT — Camera / 5-Photo Burst, 10.0 mm below BTN_TOP)
    snap_cz=-15.2,
    btn_hole_d=3.9,
    # Mini SPDT Slide Switch: Lower-left side wall (-X wall)
    sw_cy=-20.5,
    sw_cz=-13.5,
    sw_slot_y=2.2,
    sw_slot_z=4.8,

    # 7. 4x M2 Corner Fasteners:
    #    Bottom pair at (x = +-14.0, y = -23.0) indexes through Waveshare PCB's bottom M2 mounting holes
    #    Top pair at (-15.0, +30.8) and (+14.4, +29.5) in Top Crown corners
    boss_x_bot=14.0,
    boss_y_bot=-23.0,
    boss_x_top=14.4,
    boss_y_top=29.5,
    boss_d=4.2,
    pilot_d=1.75,
    clear_d=2.3,
    cbore_d=3.8,
    cbore_depth=1.3,

    # 8. Rear Slide-In Accessory Groove (Twin-Rail Undercut Receiver for Spring Clip / Kickstand):
    #    - Outer slot neck width: 12.0 mm (x = -6.0..+6.0 mm, z = -20.8..-20.0 mm)
    #    - Undercut rail width:   16.4 mm (x = -8.2..+8.2 mm, z = -20.0..-19.3 mm; 2.2 mm rails per side)
    #    - Engaged rail Y span:   y = -0.5 to +19.5 mm (20.0 mm locked track; closed top stop at y = +19.5 mm)
    #    - Drop-in entry bay:     y = -11.5 to -0.5 mm (11.0 mm open entry above speaker grille)
    #    - Internal sealed spine: z = -19.3 to -18.35 mm (maintains 0.95 mm sealed inner wall, 0 collision)
    slot_neck_w=12.0,
    slot_base_w=16.4,
    slot_y_entry=-11.5,
    slot_y_rail=-0.5,
    slot_y_top=19.5,
    slot_z_neck=-20.0,
    slot_z_base=-19.3,
    slot_spine_z=-18.35,
)


def make_box(x0, x1, y0, y1, z0, z1):
    ext = [x1 - x0, y1 - y0, z1 - z0]
    c = [(x0 + x1) / 2.0, (y0 + y1) / 2.0, (z0 + z1) / 2.0]
    m = box(extents=ext)
    m.apply_translation(c)
    return m


def make_cyl_z(r, z0, z1, cx=0.0, cy=0.0, sections=48):
    h = z1 - z0
    m = cylinder(radius=r, height=h, sections=sections)
    m.apply_translation([cx, cy, (z0 + z1) / 2.0])
    return m


def make_cyl_y(r, y0, y1, cx=0.0, cz=0.0, sections=48):
    h = y1 - y0
    m = cylinder(radius=r, height=h, sections=sections)
    rot = trimesh.transformations.rotation_matrix(math.pi / 2.0, [1, 0, 0])
    m.apply_transform(rot)
    m.apply_translation([cx, (y0 + y1) / 2.0, cz])
    return m


def make_cyl_x(r, x0, x1, cy=0.0, cz=0.0, sections=48):
    h = x1 - x0
    m = cylinder(radius=r, height=h, sections=sections)
    rot = trimesh.transformations.rotation_matrix(math.pi / 2.0, [0, 1, 0])
    m.apply_transform(rot)
    m.apply_translation([(x0 + x1) / 2.0, cy, cz])
    return m


def make_rounded_shell_block(w, y0, y1, z0, z1, r_xy=2.8, chamfer_z=1.2, chamfer_top=True, chamfer_bot=True):
    hw = w / 2.0
    pts = []
    z_slices = []
    if chamfer_bot:
        z_slices.append((z0, r_xy - chamfer_z, chamfer_z))
        z_slices.append((z0 + chamfer_z, r_xy, 0.0))
    else:
        z_slices.append((z0, r_xy, 0.0))

    if chamfer_top:
        z_slices.append((z1 - chamfer_z, r_xy, 0.0))
        z_slices.append((z1, r_xy - chamfer_z, chamfer_z))
    else:
        z_slices.append((z1, r_xy, 0.0))

    angles = np.linspace(0, 2 * math.pi, 48, endpoint=False)
    for z_val, rad, inset in z_slices:
        c_list = [
            (-hw + r_xy + inset, y0 + r_xy + inset),
            (hw - r_xy - inset, y0 + r_xy + inset),
            (hw - r_xy - inset, y1 - r_xy - inset),
            (-hw + r_xy + inset, y1 - r_xy - inset),
        ]
        for cx, cy in c_list:
            for a in angles:
                pts.append([cx + rad * math.cos(a), cy + rad * math.sin(a), z_val])
    cloud = trimesh.PointCloud(pts)
    return cloud.convex_hull


def build_front_shell():
    p = P
    outer = make_rounded_shell_block(
        p['W_out'], p['y_min'], p['y_max'], p['split_z'], 0.0,
        r_xy=2.8, chamfer_z=1.2, chamfer_top=True, chamfer_bot=False
    )
    iw = p['W_out'] - 2 * p['wall']  # 33.4 mm
    cavity = make_box(
        -iw / 2.0, iw / 2.0,
        p['y_min'] + p['wall'], p['y_max'] - p['wall'],
        p['split_z'] - 0.5, -p['front_wall']
    )
    cutters = [cavity]

    # 1. Forward-firing e-paper display viewing window (28.0 x 28.0 mm at y = win_cy)
    wy0 = p['win_cy'] - p['win_h'] / 2.0
    wy1 = p['win_cy'] + p['win_h'] / 2.0
    cutters.append(make_box(-p['win_w'] / 2.0, p['win_w'] / 2.0, wy0, wy1, -3.0, 1.0))

    # 2. Display FPC ribbon relief pocket on underside of front bezel (y = +17.8..+22.6, z = -2.6..-0.8)
    cutters.append(make_box(
        -p['disp_fpc_w'] / 2.0, p['disp_fpc_w'] / 2.0,
        p['disp_fpc_y0'] - 0.2, p['disp_fpc_y1'] + 0.2,
        -2.6, -0.8
    ))

    # 3. Forward-firing Camera Lens Aperture (+Z front face, at x=cam_cx, y=cam_cy)
    cutters.append(make_cyl_z(p['cam_lens_d'] / 2.0, -3.0, 1.0, cx=p['cam_cx'], cy=p['cam_cy']))

    # 4. Internal camera cradle & 4 corner M2 bosses
    adds = []
    cw = p['cam_w'] + 0.4
    ch = p['cam_h'] + 0.4
    cx, cy = p['cam_cx'], p['cam_cy']
    adds.append(make_box(cx - cw/2, cx + cw/2 + 0.8, cy + ch/2, cy + ch/2 + 0.8, -6.0, -p['front_wall']))
    adds.append(make_box(cx + cw/2, cx + cw/2 + 0.8, cy - ch/2, cy + ch/2 + 0.8, -6.0, -p['front_wall']))

    # Bottom pair of M2 bosses: step around display PCB with dia 1.9mm indexing sleeve through PCB corner M2 hole
    for sx in (-1, 1):
        bx, by = sx * p['boss_x_bot'], p['boss_y_bot']
        adds.append(make_cyl_z(p['boss_d'] / 2.0, -2.45, -p['front_wall'] + 0.1, cx=bx, cy=by))
        adds.append(make_cyl_z(p['boss_d'] / 2.0, p['split_z'], -4.15, cx=bx, cy=by))
        adds.append(make_cyl_z(0.95, -4.2, -2.4, cx=bx, cy=by))
        cutters.append(make_cyl_z(p['pilot_d'] / 2.0, p['split_z'] - 0.5, -2.0, cx=bx, cy=by))

    # Top pair of M2 bosses in Crown corners
    for sx in (-1, 1):
        bx, by = sx * p['boss_x_top'], p['boss_y_top']
        r_top = 1.8 if sx == -1 else p['boss_d'] / 2.0
        by_top = 30.8 if sx == -1 else by
        bx_top = sx * 15.0 if sx == -1 else bx
        adds.append(make_cyl_z(r_top, p['split_z'], -p['front_wall'] + 0.1, cx=bx_top, cy=by_top))
        cutters.append(make_cyl_z(p['pilot_d'] / 2.0, p['split_z'] - 0.5, -2.2, cx=bx_top, cy=by_top))

    part = trimesh.boolean.union([outer] + adds, engine='manifold')
    part = trimesh.boolean.difference([part] + cutters, engine='manifold')
    return part


def build_back_shell():
    p = P
    outer = make_rounded_shell_block(
        p['W_out'], p['y_min'], p['y_max'], -p['D_out'], p['split_z'],
        r_xy=2.8, chamfer_z=1.2, chamfer_top=False, chamfer_bot=True
    )
    iw = p['W_out'] - 2 * p['wall']  # 33.4 mm
    cavity = make_box(
        -iw / 2.0, iw / 2.0,
        p['y_min'] + p['wall'], p['y_max'] - p['wall'],
        -p['D_out'] + p['back_wall'], p['split_z'] + 0.5
    )

    adds = []
    cutters = [cavity]

    # 1. 4x M2 back screw pillars + counterbores
    boss_coords = [
        (-p['boss_x_bot'], p['boss_y_bot'], p['boss_d'] / 2.0),
        (p['boss_x_bot'], p['boss_y_bot'], p['boss_d'] / 2.0),
        (-15.0, 30.8, 1.8),
        (p['boss_x_top'], p['boss_y_top'], p['boss_d'] / 2.0),
    ]
    for bx, by, rad in boss_coords:
        adds.append(make_cyl_z(rad, -p['D_out'] + p['back_wall'] - 0.1, p['split_z'], cx=bx, cy=by))
        cutters.append(make_cyl_z(p['clear_d'] / 2.0, -p['D_out'] - 0.5, p['split_z'] + 0.5, cx=bx, cy=by))
        cutters.append(make_cyl_z(p['cbore_d'] / 2.0, -p['D_out'] - 0.5, -p['D_out'] + p['cbore_depth'], cx=bx, cy=by))

    # 2. Horizontal XIAO + Sense support shelf in Top Crown (y = +21.9 to +22.7)
    adds.append(make_box(-iw / 2.0, 5.0, 21.9, 22.7, -p['D_out'] + p['back_wall'], p['split_z']))

    # 3. Battery retention side rails & rear standoffs
    adds.append(make_box(-16.2, -15.1, p['bat_y0'], p['bat_y1'], -14.5, p['split_z']))
    adds.append(make_box(15.1, 16.2, p['bat_y0'], p['bat_y1'], -14.5, p['split_z']))
    adds.append(make_box(-14.0, 11.4, 10.0, 12.0, -15.1, -14.3))
    adds.append(make_box(-14.0, 11.4, 18.0, 20.0, -15.1, -14.3))

    # 4. Speaker pocket frame on inside of back wall (15.0 x 10.0 x 3.5 mm speaker)
    sx0, sx1 = p['spk_cx'] - p['spk_w']/2 - 0.3, p['spk_cx'] + p['spk_w']/2 + 0.3
    sy0, sy1 = p['spk_cy'] - p['spk_h']/2 - 0.3, p['spk_cy'] + p['spk_h']/2 + 0.3
    spk_outer = make_box(sx0 - 1.0, sx1 + 1.0, sy0 - 1.0, sy1 + 1.0, -p['D_out'] + p['back_wall'] - 0.1, -15.8)
    spk_inner = make_box(sx0, sx1, sy0, sy1, -p['D_out'] + p['back_wall'], -15.0)
    adds.append(trimesh.boolean.difference([spk_outer, spk_inner], engine='manifold'))

    # 5. Upper-Right Side BTN_TOP (PTT / Voice) cradle (+X right wall at y = ptt_cy, z = ptt_cz)
    py, pz = p['ptt_cy'], p['ptt_cz']
    ptt_outer = make_box(iw / 2.0 - 5.0, iw / 2.0 + 0.1, py - 4.0, py + 4.0, pz - 3.1, pz + 0.9)
    ptt_inner = make_box(iw / 2.0 - 4.0, iw / 2.0 + 0.5, py - 3.1, py + 3.1, pz - 3.2, pz + 1.0)
    adds.append(trimesh.boolean.difference([ptt_outer, ptt_inner], engine='manifold'))
    cutters.append(make_cyl_x(p['btn_hole_d'] / 2.0, iw / 2.0 - 1.0, p['W_out'] / 2.0 + 1.0, cy=py, cz=pz))

    # 6. Upper-Right Side BTN_BOT (Camera / Burst) cradle (+X right wall at y = snap_cy, z = snap_cz)
    sy, sz = p['snap_cy'], p['snap_cz']
    snap_outer = make_box(iw / 2.0 - 5.0, iw / 2.0 + 0.1, sy - 4.0, sy + 4.0, sz - 3.1, sz + 0.9)
    snap_inner = make_box(iw / 2.0 - 4.0, iw / 2.0 + 0.5, sy - 3.1, sy + 3.1, sz - 3.2, sz + 1.0)
    adds.append(trimesh.boolean.difference([snap_outer, snap_inner], engine='manifold'))
    cutters.append(make_cyl_x(p['btn_hole_d'] / 2.0, iw / 2.0 - 1.0, p['W_out'] / 2.0 + 1.0, cy=sy, cz=sz))

    # 7. UPWARD-POINTING PDM MICROPHONE PORT (+Y top wall at x = mic_cx, z = mic_cz)
    cutters.append(make_cyl_y(p['mic_d'] / 2.0, p['y_max'] - 4.0, p['y_max'] + 1.0, cx=p['mic_cx'], cz=p['mic_cz']))

    # 8. Left-wall USB-C opening (-X left wall at y = usb_cy, z = usb_cz)
    cutters.append(make_box(
        -p['W_out'] / 2.0 - 1.0, -iw / 2.0 + 1.0,
        p['usb_cy'] - p['usb_h'] / 2.0, p['usb_cy'] + p['usb_h'] / 2.0,
        p['usb_cz'] - p['usb_w'] / 2.0, p['usb_cz'] + p['usb_w'] / 2.0
    ))

    # 9. Lower-left SPDT slide switch slot (-X left wall at y = sw_cy, z = sw_cz)
    cutters.append(make_box(
        -p['W_out'] / 2.0 - 1.0, -iw / 2.0 + 1.0,
        p['sw_cy'] - p['sw_slot_y'] / 2.0, p['sw_cy'] + p['sw_slot_y'] / 2.0,
        p['sw_cz'] - p['sw_slot_z'] / 2.0, p['sw_cz'] + p['sw_slot_z'] / 2.0
    ))

    # 10. Speaker acoustic slot grille in back wall
    for ix in range(-2, 3):
        gx = p['spk_cx'] + ix * 2.6
        cutters.append(make_box(gx - 0.6, gx + 0.6, p['spk_cy'] - 3.2, p['spk_cy'] + 3.2, -p['D_out'] - 0.5, -p['D_out'] + p['back_wall'] + 0.5))

    part = trimesh.boolean.union([outer] + adds, engine='manifold')
    part = trimesh.boolean.difference([part] + cutters, engine='manifold')

    # 11. Rear Slide-In Accessory Groove (Twin-Rail Undercut Receiver for Clip / Kickstand)
    #     Internal sealed reinforcement pad (z = -19.5 to -18.35 mm) keeps wall 100% sealed behind groove
    spine_pad = make_box(
        -p['slot_base_w'] / 2.0 - 1.5, p['slot_base_w'] / 2.0 + 1.5,
        p['slot_y_entry'] - 1.2, p['slot_y_top'] + 1.5,
        -p['D_out'] + p['back_wall'] - 0.3, p['slot_spine_z']
    )
    groove_cuts = [
        # Center neck opening along full track (x = -6.0..+6.0 mm, y = -11.5..+19.5 mm, z = -20.8..-19.3 mm)
        make_box(
            -p['slot_neck_w'] / 2.0, p['slot_neck_w'] / 2.0,
            p['slot_y_entry'], p['slot_y_top'],
            -p['D_out'] - 0.5, p['slot_z_base']
        ),
        # Twin undercut side grooves in upper locked zone (x = -8.2..+8.2 mm, y = -0.5..+19.5 mm, z = -20.0..-19.3 mm)
        make_box(
            -p['slot_base_w'] / 2.0, p['slot_base_w'] / 2.0,
            p['slot_y_rail'], p['slot_y_top'],
            p['slot_z_neck'], p['slot_z_base']
        ),
        # Lower drop-in entry cutout (x = -8.2..+8.2 mm, y = -11.5..-0.5 mm, full depth z = -20.8..-19.3 mm)
        make_box(
            -p['slot_base_w'] / 2.0, p['slot_base_w'] / 2.0,
            p['slot_y_entry'], p['slot_y_rail'],
            -p['D_out'] - 0.5, p['slot_z_base']
        ),
    ]
    detent_bump = make_box(
        -3.5, 3.5,
        0.0, 1.2,
        p['slot_z_base'] - 0.35, p['slot_z_base'] + 0.1
    )
    part = trimesh.boolean.union([part, spine_pad], engine='manifold')
    part = trimesh.boolean.difference([part] + groove_cuts, engine='manifold')
    part = trimesh.boolean.union([part, detent_bump], engine='manifold')
    return part


def build_button_cap():
    flange = make_cyl_z(5.5 / 2.0, 0.0, 1.0)
    stem = make_cyl_z(3.4 / 2.0, 0.95, 3.8)
    return trimesh.boolean.union([flange, stem], engine='manifold')


def build_spring_clip():
    """
    Buildable slide-in compliant spring lapel/pocket clip that locks into the rear twin-rail grooves.
    Positioned in assembled coordinates (behind z = -20.8 mm).
    """
    p = P
    # T-tongue (0.2 mm clearance per side: 16.0 mm flange width, 11.6 mm neck width, 18.5 mm tall in Y: y = +0.8..+19.3)
    flange = make_box(-8.0, 8.0, 0.8, 19.3, -19.95, -19.40)
    neck = make_box(-5.8, 5.8, 0.8, 19.3, -21.0, -19.35)
    # Detent notch in tongue face for snap-fit bump
    notch = make_box(-3.8, 3.8, -0.2, 1.5, -19.55, -19.20)
    # Top C-loop spring arch (y = +16.5..+20.5, curving back to z = -25.6 mm)
    arch_top = make_box(-6.5, 6.5, 16.8, 19.8, -25.6, -20.8)
    arch_hollow = make_box(-7.0, 7.0, 15.0, 17.6, -23.8, -21.0)
    # Spring arm extending downward to y = -18.0 mm (2.0 mm thick beam, clamping gap to z = -21.4 mm at tip)
    arm = make_box(-6.5, 6.5, -18.0, 18.0, -25.6, -23.6)
    pinch_jaw = make_box(-6.5, 6.5, -14.5, -11.0, -23.8, -21.5)
    flare_tip = make_box(-6.5, 6.5, -19.5, -17.5, -26.4, -24.2)
    clip = trimesh.boolean.union([flange, neck, arch_top, arm, pinch_jaw, flare_tip], engine='manifold')
    clip = trimesh.boolean.difference([clip, notch, arch_hollow], engine='manifold')
    return clip


def build_kickstand():
    """
    Buildable slide-in 20-degree desk kickstand that locks into the same rear twin-rail grooves
    and props the enclosure at an ergonomic desk viewing angle down to y = y_min (-27.2 mm).
    """
    p = P
    flange = make_box(-8.0, 8.0, 0.8, 19.3, -19.95, -19.40)
    neck = make_box(-5.8, 5.8, 0.8, 19.3, -21.2, -19.35)
    notch = make_box(-3.8, 3.8, -0.2, 1.5, -19.55, -19.20)
    # Angled A-frame kickstand leg extending from (y = +16.0, z = -21.0) down to desk level (y = -27.2, z = -36.5)
    # Built as a hull of top hinge bar and wide bottom desk foot, with a center weight-relief cutout
    top_bar = make_box(-7.0, 7.0, 13.0, 18.5, -23.2, -20.8)
    foot_bar = make_box(-11.0, 11.0, p['y_min'], p['y_min'] + 3.2, -36.5, -33.5)
    leg_hull = trimesh.convex.convex_hull(np.vstack([top_bar.vertices, foot_bar.vertices]))
    window_cut = make_box(-4.2, 4.2, -21.0, 9.0, -40.0, -21.3)
    stand = trimesh.boolean.union([flange, neck, leg_hull], engine='manifold')
    stand = trimesh.boolean.difference([stand, notch, window_cut], engine='manifold')
    return stand


def build_internal_3d_components():
    """Build true multi-feature 3D component meshes (including switches) and verify zero collisions."""
    p = P
    iw = p['W_out'] - 2 * p['wall']  # 33.4 mm
    comps = {}

    # 1. Waveshare 1.54" V2 Composite Module (PCB with 4 corner M2 holes + front glass + top FPC fold + rear ZIF + bottom PH2.0)
    ws_pcb = make_box(-p['disp_w']/2, p['disp_w']/2, p['disp_y0'], p['disp_y1'], p['disp_pcb_z1'], p['disp_pcb_z0'])
    holes = [make_cyl_z(1.05, p['disp_pcb_z1'] - 0.5, p['disp_pcb_z0'] + 0.5, cx=sx*p['boss_x_bot'], cy=by)
             for sx in (-1, 1) for by in (p['boss_y_bot'], p['disp_y1'] - 2.5)]
    ws_pcb = trimesh.boolean.difference([ws_pcb] + holes, engine='manifold')
    ws_glass = make_box(-p['disp_glass_w']/2, p['disp_glass_w']/2, p['disp_glass_y0'], p['disp_glass_y1'], p['disp_glass_z1'], p['disp_glass_z0'])
    ws_fpc = make_box(-p['disp_fpc_w']/2, p['disp_fpc_w']/2, p['disp_fpc_y0'], p['disp_fpc_y1'], p['disp_zif_z1'], -0.9)
    ws_ph20 = make_box(-p['ph20_w']/2, p['ph20_w']/2, p['disp_y0'] + 0.1, p['ph20_y1'], p['ph20_z1'], p['disp_pcb_z1'])
    comps['display_composite'] = trimesh.boolean.union([ws_pcb, ws_glass, ws_fpc, ws_ph20], engine='manifold')

    # 2. 803040 LiPo Battery (30 x 40 x 8 mm behind flat upper 40mm of display PCB)
    comps['battery_803040'] = make_box(-p['bat_w']/2, p['bat_w']/2, p['bat_y0'], p['bat_y1'], p['bat_z1'], p['bat_z0'])

    # 3. XIAO ESP32S3 + Sense Daughterboard (Horizontal in Top Crown, Sense + Mic facing UP +Y)
    xiao_base = make_box(p['xiao_x0'], p['xiao_x1'], p['xiao_y0'], p['xiao_y0'] + 4.0, p['xiao_z1'], p['xiao_z0'])
    sense_pcb = make_box(p['xiao_x0'] + 6.5, p['xiao_x1'], p['xiao_y0'] + 4.0, p['xiao_y1'], p['xiao_z1'], p['xiao_z0'])
    pdm_mic = make_box(p['mic_cx'] - 1.75, p['mic_cx'] + 1.75, p['xiao_y1'] - 0.1, p['xiao_y1'] + 0.8, p['mic_cz'] - 1.3, p['mic_cz'] + 1.3)
    comps['xiao_sense_upward_mic'] = trimesh.boolean.union([xiao_base, sense_pcb, pdm_mic], engine='manifold')

    # 4. Forward-firing Camera Head (+Z) + 90-deg Curved FPC Flex Ribbon
    cam_base = make_box(p['cam_cx'] - p['cam_w']/2, p['cam_cx'] + p['cam_w']/2, p['cam_cy'] - p['cam_h']/2, p['cam_cy'] + p['cam_h']/2, p['cam_z1'], -2.8)
    cam_lens = make_cyl_z(p['cam_lens_d']/2 - 0.3, -2.9, p['cam_z0'], cx=p['cam_cx'], cy=p['cam_cy'])
    cam_flex = make_box(p['xiao_x1'] + 0.1, p['cam_cx'] - p['cam_w']/2 + 0.2, p['cam_cy'] - 3.0, p['cam_cy'] + 3.0, -5.6, -3.6)
    comps['camera_forward_flex'] = trimesh.boolean.union([cam_base, cam_lens, cam_flex], engine='manifold')

    # 5. Speaker (15 x 10 x 3.5 mm)
    comps['speaker_1510'] = make_box(p['spk_cx'] - p['spk_w']/2, p['spk_cx'] + p['spk_w']/2, p['spk_cy'] - p['spk_h']/2, p['spk_cy'] + p['spk_h']/2, p['spk_z1'], p['spk_z0'])

    # 6. MAX98357A Amp (19 x 17.8 x 3.0 mm)
    comps['amp_max98357a'] = make_box(p['amp_cx'] - p['amp_w']/2, p['amp_cx'] + p['amp_w']/2, p['amp_cy'] - p['amp_h']/2, p['amp_cy'] + p['amp_h']/2, p['amp_z1'], p['amp_z0'])

    # 7. Upper-Right Side BTN_TOP 6x6x5mm Tactile Switch (+X wall at y = ptt_cy, z = ptt_cz)
    ptt_body = make_box(iw / 2.0 - 3.6, iw / 2.0 - 0.1, p['ptt_cy'] - 3.0, p['ptt_cy'] + 3.0, p['ptt_cz'] - 3.0, p['ptt_cz'] + 0.8)
    ptt_stem = make_cyl_x(1.6, iw / 2.0 - 0.2, iw / 2.0 + 1.3, cy=p['ptt_cy'], cz=p['ptt_cz'])
    comps['btn_top_tactile'] = trimesh.boolean.union([ptt_body, ptt_stem], engine='manifold')

    # 8. Upper-Right Side BTN_BOT 6x6x5mm Tactile Switch (+X wall at y = snap_cy, z = snap_cz)
    snap_body = make_box(iw / 2.0 - 3.6, iw / 2.0 - 0.1, p['snap_cy'] - 3.0, p['snap_cy'] + 3.0, p['snap_cz'] - 3.0, p['snap_cz'] + 0.8)
    snap_stem = make_cyl_x(1.6, iw / 2.0 - 0.2, iw / 2.0 + 1.3, cy=p['snap_cy'], cz=p['snap_cz'])
    comps['btn_bot_tactile'] = trimesh.boolean.union([snap_body, snap_stem], engine='manifold')

    # 9. Lower-Left Mini SPDT Slide Switch (-X wall at y = sw_cy, z = sw_cz)
    sw_body = make_box(-iw / 2.0 + 0.1, -iw / 2.0 + 3.6, p['sw_cy'] - 1.75, p['sw_cy'] + 1.75, p['sw_cz'] - 4.25, p['sw_cz'] + 4.25)
    sw_knob = make_box(-iw / 2.0 - 1.3, -iw / 2.0 + 0.2, p['sw_cy'] - 0.8, p['sw_cy'] + 0.8, p['sw_cz'] - 1.0, p['sw_cz'] + 1.0)
    comps['spdt_slide_switch'] = trimesh.boolean.union([sw_body, sw_knob], engine='manifold')

    return comps


def export_stls(out_dir, front, back, cap, clip=None, kickstand=None):
    stl_dir = os.path.join(out_dir, "stl")
    os.makedirs(stl_dir, exist_ok=True)

    # Orient front shell print-ready: flip 180 deg around X so flat front face rests on Z=0 bed
    front_print = front.copy()
    rot_x180 = trimesh.transformations.rotation_matrix(math.pi, [1, 0, 0])
    front_print.apply_transform(rot_x180)
    front_print.apply_translation([0, 0, -front_print.bounds[0][2]])
    front_print.export(os.path.join(stl_dir, "gotchi_front.stl"))

    # Orient back shell print-ready: flat rear face rests on Z=0 bed
    back_print = back.copy()
    back_print.apply_translation([0, 0, -back_print.bounds[0][2]])
    back_print.export(os.path.join(stl_dir, "gotchi_back.stl"))

    # Button cap: flange on Z=0 bed
    cap_print = cap.copy()
    cap_print.apply_translation([0, 0, -cap_print.bounds[0][2]])
    cap_print.export(os.path.join(stl_dir, "gotchi_button_cap.stl"))

    if clip is not None:
        # Orient spring clip on its side (+X/-X profile flat on Z=0 bed) for maximum layer strength along spring loop
        clip_print = clip.copy()
        rot_y90 = trimesh.transformations.rotation_matrix(math.pi / 2.0, [0, 1, 0])
        clip_print.apply_transform(rot_y90)
        clip_print.apply_translation([0, 0, -clip_print.bounds[0][2]])
        clip_print.export(os.path.join(stl_dir, "gotchi_clip.stl"))

    if kickstand is not None:
        stand_print = kickstand.copy()
        rot_y90 = trimesh.transformations.rotation_matrix(math.pi / 2.0, [0, 1, 0])
        stand_print.apply_transform(rot_y90)
        stand_print.apply_translation([0, 0, -stand_print.bounds[0][2]])
        stand_print.export(os.path.join(stl_dir, "gotchi_kickstand.stl"))

    print(f"Exported watertight print-oriented STLs to {stl_dir}/")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=os.path.dirname(os.path.abspath(__file__)))
    args, _ = parser.parse_known_args()

    front = build_front_shell()
    back = build_back_shell()
    cap = build_button_cap()
    clip = build_spring_clip()
    kickstand = build_kickstand()
    comps = build_internal_3d_components()

    for name, m in [("front", front), ("back", back), ("button_cap", cap), ("spring_clip", clip), ("kickstand", kickstand)]:
        print(f"{name}: verts={len(m.vertices)} faces={len(m.faces)} watertight={m.is_watertight} extents={np.round(m.extents, 2)}")
        if not m.is_watertight:
            raise RuntimeError(f"Mesh {name} is not watertight!")

    names = list(comps.keys())
    hits = 0
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            inter = trimesh.boolean.intersection([comps[names[i]], comps[names[j]]], engine='manifold')
            vol = inter.volume if not inter.is_empty else 0.0
            if vol > 0.01:
                print(f"COLLISION: {names[i]} vs {names[j]} = {vol:.2f} mm^3")
                hits += 1
    for sname, sh in [("front_shell", front), ("back_shell", back)]:
        for cname, cm in comps.items():
            inter = trimesh.boolean.intersection([sh, cm], engine='manifold')
            vol = inter.volume if not inter.is_empty else 0.0
            if vol > 0.05:
                print(f"SHELL OVERLAP: {sname} vs {cname} = {vol:.2f} mm^3")
                hits += 1
    if hits > 0:
        raise RuntimeError(f"Detected {hits} collision(s)!")
    print("ALL 3D COMPONENT & SHELL CLEARANCES VERIFIED: 0 COLLISIONS (0.00 mm^3)")

    export_stls(args.out, front, back, cap, clip, kickstand)


if __name__ == "__main__":
    main()
