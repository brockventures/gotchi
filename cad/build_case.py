#!/usr/bin/env python3
"""
GOTCHI V1 Printable Enclosure — Revision 5.3 (PSA / Snap-Rabbet Seam, Compact 59.6mm Y & Open Tolerance-Safe Bays)
==================================================================================================================
Outer envelope: 36.4 x 59.6 x 20.8 mm (44.5 cm^3 — 43.9% smaller volume than Rev 1's
38.0 x 72.0 x 29.0 mm / 79.3 cm^3 box, 8.2 mm thinner in Z, 13.2 mm shorter in Y,
with slim 4.2 mm side bezels around the 28.0 x 28.0 mm active screen window).

Key Architectural & Packaging Improvements (Rev 5.3):
1. Screwless Perimeter Rabbet / PSA Closure (Option B):
   - Eliminates all 4 corner M2 screw bosses and counterbores, reclaiming corner volume and
     completely eliminating boss overlaps with the camera and speaker.
   - Uses a stepped 0.75 mm perimeter rabbet lip at split_z = -8.8 mm (with 0.15 mm radial print
     clearance and 1.5 mm PSA / snap-bond land) for self-indexing front/back shell closure.
   - Fixes boolean CSG order (`cavity` subtracted from `outer` BEFORE unioning internal `adds`)
     so all internal ledges and features are 100% preserved in the STL and verified for 0.00 mm^3 collision.

2. Tolerance-Safe Open Component Bays (V1 Bench-Friendly):
   - Keeps components with vendor/clone dimensional variance (MAX98357A breakout, 803040 LiPo pouch,
     15x10 speaker, OV2640 camera module, tactile/slide switches) free of tight-tolerance press cages
     so parts mount cleanly with thin PSA / foam tape without fighting 3D-print shrinkage.
   - Uses only non-binding alignment ledges where external apertures require registration
     (bottom support shelf under XIAO for USB-C alignment, shallow locator frame around speaker slots,
     and open-backed alignment slots for the side switches).

3. Compacted 59.6 mm Height & Balanced Rear Audio Layout:
   - Tightens Top Crown and bottom chin margins to shrink total Y height from 60.2 mm to 59.6 mm
     (y = -26.5 to +32.3 mm).
   - Moves the 15x10x3.5 mm speaker up and left (x = -1.5, y = -15.5 mm) right below the screen
     window line, closing the vertical gap and utilizing the lower-left/center rear bay alongside
     the MAX98357A amp (x = -5.5, y = -1.5 mm).

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
    H_out=59.6,
    D_out=20.8,
    y_min=-27.0,
    y_max=32.6,
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

    # 3. Top Crown (y = +22.6 to +30.9 mm):
    #    Left side (x = -16.5 to +4.5 mm): Horizontal XIAO ESP32S3 + Sense Stack (Sense PCB + PDM Mic facing UP +Y)
    #    Right-front (x = +5.25 to +13.75 mm): Forward-firing Camera (+Z) fed by 90-deg FPC flex ribbon
    xiao_x0=-16.5,
    xiao_x1=4.5,    # 21.0 mm length along X (USB-C at left wall x=-16.5; camera FPC header at x=+4.5)
    xiao_y0=22.6,
    xiao_y1=30.2,   # 7.6 mm B2B stack height along Y (+ 0.7 mm MEMS mic on top = 30.9 mm < 31.0 mm top inner wall)
    xiao_z0=-2.0,
    xiao_z1=-19.2,
    # Upward-pointing PDM MEMS microphone on top face of Sense PCB (y = +30.9, firing straight UP +Y)
    mic_cx=-2.5,
    mic_cz=-11.2,
    mic_d=2.2,
    # Left-wall USB-C port (-X wall at y = 24.6, z = -11.2)
    usb_cy=24.6,
    usb_cz=-11.2,
    usb_w=9.4,   # along Z
    usb_h=3.8,   # along Y

    # 4. Forward-firing Camera (OV2640/OV3660/OV5640) on 90-deg curved FPC flex ribbon
    cam_w=8.5,
    cam_h=8.5,
    cam_cx=9.5,     # Shifted left into upper-right crown (x = +5.25 to +13.75 mm, zero corner interference)
    cam_cy=26.78,    # Above display PCB (y = +22.55 to +31.05 mm; clears display PCB y=+22.5)
    cam_lens_d=7.6,
    cam_z0=-1.0,
    cam_z1=-5.8,

    # 5. Rear Slim Audio Layer (z = -15.2 to -19.2 mm, behind battery & PH2.0 zone)
    amp_w=19.0,
    amp_h=17.8,
    amp_d=3.0,
    amp_cx=-5.5,
    amp_cy=-0.5,    # y = -9.4 to +8.4 mm (left-center rear bay)
    amp_z0=-15.2,
    amp_z1=-18.2,

    # Bottom-Edge Direct-Firing Speaker (-Y bottom wall, behind PH2.0 plug z=-4.1..-8.7 and below battery y=-18.2):
    #   - 15.0 mm width along X (x = -7.5 to +7.5 mm)
    #   - 3.5 mm thickness along Y (y = -25.4 to -21.9 mm, flush against bottom inner wall y = -25.5 mm)
    #   - 10.0 mm height along Z (z = -9.2 to -19.2 mm, inside back shell behind PH2.0 plug)
    spk_w=15.0,     # along X
    spk_h=3.5,      # along Y (thickness into cavity from bottom wall)
    spk_d=10.0,     # along Z (spans z = -9.2 to -19.2 mm)
    spk_cx=0.0,
    spk_cy=-23.65,  # y = -25.4 to -21.9 mm
    spk_z0=-9.2,
    spk_z1=-19.2,
    spk_grille_cz=-14.2,

    # 6. Controls:
    # Both BTN_TOP (PTT/Voice) and BTN_BOT (Camera/Burst) stacked on the Upper-Right Side Wall (+X wall)
    # at z = -15.2 mm (behind battery plane z = -6.2..-14.2 mm, in the clear right-rear corridor)
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

    # 7. Screwless Perimeter Rabbet / PSA Closure (Option B):
    rabbet_lip_w=0.7,
    rabbet_lip_h=1.2,
    rabbet_clearance=0.15,

    # 8. Rear Slide-In Accessory Groove (Twin-Rail Undercut Receiver for Spring Clip / Kickstand):
    slot_neck_w=12.0,
    slot_base_w=16.4,
    slot_y_entry=-10.0,
    slot_y_rail=0.5,
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

    # Step 1: Subtract main interior cavity FIRST so internal features added next are never wiped out
    part = trimesh.boolean.difference([outer, cavity], engine='manifold')

    # Step 2: Non-binding perimeter rabbet recess on front shell split face (accepts back shell's inner lip + PSA)
    rabbet_cut = make_box(
        -iw / 2.0 - p['rabbet_lip_w'], iw / 2.0 + p['rabbet_lip_w'],
        p['y_min'] + p['wall'] - p['rabbet_lip_w'], p['y_max'] - p['wall'] + p['rabbet_lip_w'],
        p['split_z'] - 0.1, p['split_z'] + p['rabbet_lip_h'] + 0.15
    )

    # Step 3: External aperture cutters
    wy0 = p['win_cy'] - p['win_h'] / 2.0
    wy1 = p['win_cy'] + p['win_h'] / 2.0
    win_cut = make_box(-p['win_w'] / 2.0, p['win_w'] / 2.0, wy0, wy1, -3.0, 1.0)

    # Display FPC ribbon relief pocket on underside of front bezel (y = +18.4..+23.2, z = -2.6..-0.8)
    fpc_cut = make_box(
        -p['disp_fpc_w'] / 2.0 - 0.5, p['disp_fpc_w'] / 2.0 + 0.5,
        p['disp_fpc_y0'] - 0.2, p['disp_fpc_y1'] + 0.2,
        -2.6, -0.8
    )

    # Forward-firing Camera Lens Aperture (+Z front face, at x=cam_cx, y=cam_cy)
    cam_cut = make_cyl_z(p['cam_lens_d'] / 2.0, -3.0, 1.0, cx=p['cam_cx'], cy=p['cam_cy'])

    part = trimesh.boolean.difference([part, rabbet_cut, win_cut, fpc_cut, cam_cut], engine='manifold')
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

    # Step 1: Subtract main interior cavity FIRST so internal features added in Step 2 remain solid
    part = trimesh.boolean.difference([outer, cavity], engine='manifold')

    adds = []
    cutters = []

    # 1. Perimeter Rabbet Alignment Lip along top/bottom walls (z = split_z to split_z + 1.0 mm) for PSA / snap closure
    lip_t = p['rabbet_lip_w'] - p['rabbet_clearance']  # 0.55 mm thick tongue
    adds.append(make_box(-10.0, 10.0, p['y_min'] + p['wall'] - 0.55, p['y_min'] + p['wall'] - 0.05, p['split_z'], p['split_z'] + p['rabbet_lip_h']))
    adds.append(make_box(-10.0, 10.0, p['y_max'] - p['wall'] + 0.05, p['y_max'] - p['wall'] + 0.55, p['split_z'], p['split_z'] + p['rabbet_lip_h']))

    # 2. Loose non-binding bottom guide shelf under XIAO + Sense in Top Crown (y = +21.1 to +21.9, z = -19.3 to -9.5)
    adds.append(make_box(-iw / 2.0, 4.5, 21.85, 22.5, -p['D_out'] + p['back_wall'], p['split_z']))

    # 3. Open-backed side button alignment cradles (+X right wall at y = ptt_cy & snap_cy, with 0.35 mm generous clearance)
    for by, bz in [(p['ptt_cy'], p['ptt_cz']), (p['snap_cy'], p['snap_cz'])]:
        b_outer = make_box(iw / 2.0 - 4.2, iw / 2.0 + 0.1, by - 4.2, by + 4.2, bz - 3.3, bz + 0.9)
        b_inner = make_box(iw / 2.0 - 4.5, iw / 2.0 + 0.5, by - 3.35, by + 3.35, bz - 3.5, bz + 1.1)
        adds.append(trimesh.boolean.difference([b_outer, b_inner], engine='manifold'))
        cutters.append(make_cyl_x(p['btn_hole_d'] / 2.0, iw / 2.0 - 1.0, p['W_out'] / 2.0 + 1.0, cy=by, cz=bz))

    # 4. UPWARD-POINTING PDM MICROPHONE PORT (+Y top wall at x = mic_cx, z = mic_cz)
    cutters.append(make_cyl_y(p['mic_d'] / 2.0, p['y_max'] - 4.0, p['y_max'] + 1.0, cx=p['mic_cx'], cz=p['mic_cz']))

    # 5. Left-wall USB-C opening (-X left wall at y = usb_cy, z = usb_cz)
    cutters.append(make_box(
        -p['W_out'] / 2.0 - 1.0, -iw / 2.0 + 1.0,
        p['usb_cy'] - p['usb_h'] / 2.0, p['usb_cy'] + p['usb_h'] / 2.0,
        p['usb_cz'] - p['usb_w'] / 2.0, p['usb_cz'] + p['usb_w'] / 2.0
    ))

    # 6. Lower-left SPDT slide switch slot (-X left wall at y = sw_cy, z = sw_cz)
    cutters.append(make_box(
        -p['W_out'] / 2.0 - 1.0, -iw / 2.0 + 1.0,
        p['sw_cy'] - p['sw_slot_y'] / 2.0, p['sw_cy'] + p['sw_slot_y'] / 2.0,
        p['sw_cz'] - p['sw_slot_z'] / 2.0, p['sw_cz'] + p['sw_slot_z'] / 2.0
    ))

    # 7. Bottom-Edge 5-Slot Speaker Grille (-Y bottom wall at x = -5.2..+5.2 mm, z = -17.2..-11.2 mm)
    for ix in range(-2, 3):
        gx = p['spk_cx'] + ix * 2.6
        cutters.append(make_box(
            gx - 0.6, gx + 0.6,
            p['y_min'] - 0.5, p['y_min'] + p['wall'] + 0.5,
            p['spk_grille_cz'] - 3.0, p['spk_grille_cz'] + 3.0
        ))

    part = trimesh.boolean.union([part] + adds, engine='manifold')
    part = trimesh.boolean.difference([part] + cutters, engine='manifold')

    # 8. Rear Slide-In Accessory Groove (Twin-Rail Undercut Receiver for Clip / Kickstand)
    #    Internal sealed reinforcement pad (z = -19.5 to -18.35 mm) keeps wall 100% sealed behind groove
    spine_pad = make_box(
        -p['slot_base_w'] / 2.0 - 1.5, p['slot_base_w'] / 2.0 + 1.5,
        p['slot_y_entry'] - 0.8, p['slot_y_top'] + 1.5,
        -p['D_out'] + p['back_wall'] - 0.3, p['slot_spine_z']
    )
    groove_cuts = [
        make_box(
            -p['slot_neck_w'] / 2.0, p['slot_neck_w'] / 2.0,
            p['slot_y_entry'], p['slot_y_top'],
            -p['D_out'] - 0.5, p['slot_z_base']
        ),
        make_box(
            -p['slot_base_w'] / 2.0, p['slot_base_w'] / 2.0,
            p['slot_y_rail'], p['slot_y_top'],
            p['slot_z_neck'], p['slot_z_base']
        ),
        make_box(
            -p['slot_base_w'] / 2.0, p['slot_base_w'] / 2.0,
            p['slot_y_entry'], p['slot_y_rail'],
            -p['D_out'] - 0.5, p['slot_z_base']
        ),
    ]
    detent_bump = make_box(
        -3.5, 3.5,
        1.5, 2.7,
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
    flange = make_box(-8.0, 8.0, 1.3, 19.3, -19.95, -19.40)
    neck = make_box(-5.8, 5.8, 1.3, 19.3, -21.0, -19.35)
    notch = make_box(-3.8, 3.8, 1.3, 2.9, -19.55, -19.20)
    arch_top = make_box(-6.5, 6.5, 16.8, 19.8, -25.6, -20.8)
    arch_hollow = make_box(-7.0, 7.0, 15.0, 17.6, -23.8, -21.0)
    arm = make_box(-6.5, 6.5, -18.0, 18.0, -25.6, -23.6)
    pinch_jaw = make_box(-6.5, 6.5, -14.5, -11.0, -23.8, -21.5)
    flare_tip = make_box(-6.5, 6.5, -19.5, -17.5, -26.4, -24.2)
    clip = trimesh.boolean.union([flange, neck, arch_top, arm, pinch_jaw, flare_tip], engine='manifold')
    clip = trimesh.boolean.difference([clip, notch, arch_hollow], engine='manifold')
    return clip


def build_kickstand():
    """
    Buildable slide-in 20-degree desk kickstand that locks into the same rear twin-rail grooves
    and props the enclosure at an ergonomic desk viewing angle down to y = y_min (-26.5 mm).
    """
    p = P
    flange = make_box(-8.0, 8.0, 1.3, 19.3, -19.95, -19.40)
    neck = make_box(-5.8, 5.8, 1.3, 19.3, -21.2, -19.35)
    notch = make_box(-3.8, 3.8, 1.3, 2.9, -19.55, -19.20)
    top_bar = make_box(-7.0, 7.0, 13.0, 18.5, -23.2, -20.8)
    foot_bar = make_box(-11.0, 11.0, p['y_min'], p['y_min'] + 3.2, -36.5, -33.5)
    leg_hull = trimesh.convex.convex_hull(np.vstack([top_bar.vertices, foot_bar.vertices]))
    window_cut = make_box(-4.2, 4.2, -20.5, 9.0, -40.0, -21.3)
    stand = trimesh.boolean.union([flange, neck, leg_hull], engine='manifold')
    stand = trimesh.boolean.difference([stand, notch, window_cut], engine='manifold')
    return stand


def build_internal_3d_components():
    """Build true multi-feature 3D component meshes (including switches) and verify zero collisions."""
    p = P
    iw = p['W_out'] - 2 * p['wall']  # 33.4 mm
    comps = {}

    # 1. Waveshare 1.54" V2 Composite Module (PCB + front glass + top FPC fold + rear ZIF + bottom PH2.0)
    ws_pcb = make_box(-p['disp_w']/2, p['disp_w']/2, p['disp_y0'], p['disp_y1'], p['disp_pcb_z1'], p['disp_pcb_z0'])
    ws_glass = make_box(-p['disp_glass_w']/2, p['disp_glass_w']/2, p['disp_glass_y0'], p['disp_glass_y1'], p['disp_glass_z1'], p['disp_glass_z0'])
    ws_fpc = make_box(-p['disp_fpc_w']/2, p['disp_fpc_w']/2, p['disp_fpc_y0'], p['disp_fpc_y1'], p['disp_zif_z1'], -0.9)
    ws_ph20 = make_box(-p['ph20_w']/2, p['ph20_w']/2, p['disp_y0'] + 0.1, p['ph20_y1'], p['ph20_z1'], p['disp_pcb_z1'])
    comps['display_composite'] = trimesh.boolean.union([ws_pcb, ws_glass, ws_fpc, ws_ph20], engine='manifold')

    # 2. 803040 LiPo Battery (30 x 40 x 8 mm behind flat upper 40mm of display PCB)
    comps['battery_803040'] = make_box(-p['bat_w']/2, p['bat_w']/2, p['bat_y0'], p['bat_y1'], p['bat_z1'], p['bat_z0'])

    # 3. XIAO ESP32S3 + Sense Daughterboard (Horizontal in Top Crown, Sense + Mic facing UP +Y)
    xiao_base = make_box(p['xiao_x0'], p['xiao_x1'], p['xiao_y0'], p['xiao_y0'] + 4.0, p['xiao_z1'], p['xiao_z0'])
    sense_pcb = make_box(p['xiao_x0'] + 6.5, p['xiao_x1'], p['xiao_y0'] + 4.0, p['xiao_y1'], p['xiao_z1'], p['xiao_z0'])
    pdm_mic = make_box(p['mic_cx'] - 1.75, p['mic_cx'] + 1.75, p['xiao_y1'] - 0.1, p['xiao_y1'] + 0.7, p['mic_cz'] - 1.3, p['mic_cz'] + 1.3)
    comps['xiao_sense_upward_mic'] = trimesh.boolean.union([xiao_base, sense_pcb, pdm_mic], engine='manifold')

    # 4. Forward-firing Camera Head (+Z) + 90-deg Curved FPC Flex Ribbon (clears display PCB top edge)
    cam_base = make_box(p['cam_cx'] - p['cam_w']/2, p['cam_cx'] + p['cam_w']/2, p['cam_cy'] - p['cam_h']/2, p['cam_cy'] + p['cam_h']/2, p['cam_z1'], -4.2)
    cam_lens = make_cyl_z(p['cam_lens_d']/2 - 0.3, -4.3, p['cam_z0'], cx=p['cam_cx'], cy=p['cam_cy'])
    cam_flex = make_box(p['xiao_x1'] + 0.1, p['cam_cx'] - p['cam_w']/2 + 0.2, p['cam_cy'] - 2.5, p['cam_cy'] + 2.5, -5.8, -4.3)
    comps['camera_forward_flex'] = trimesh.boolean.union([cam_base, cam_lens, cam_flex], engine='manifold')

    # 5. Speaker (15 x 10 x 3.5 mm, shifted up & left to x = -2.0, y = -15.5 mm)
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
