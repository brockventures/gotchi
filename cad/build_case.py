#!/usr/bin/env python3
"""
GOTCHI V4 Printable Enclosure — Revision 8.0 (Option 1A Flat Under-Tucked XIAO + Top-Wall USB-C,
18.3 mm Slimmed Depth [15.5 mm Cavity], V3.2 Snug Hinged Combo Clip-Stand & 4-Part Plate)
======================================================================================================
Outer envelope: 36.4 x 59.6 x 18.3 mm (39.7 cm^3 — 2.5 mm thinner than V3's 20.8 mm)

Key V4 Upgrades:
1. Option 1A Flat Under-Tucked XIAO ESP32S3 + Sense + Camera Packaging:
   - XIAO + Sense lies flat against the rear floor (x = -8.9..+8.9 mm, y = +10.1..+31.1 mm, z = -16.5 mm)
     with its USB-C port pointing out the Top Wall (+Y at x = 0.0, z = -14.2 mm).
   - The 8.5 x 8.5 mm camera tower at the USB-C end sits in the 8.6 mm top crown above the Waveshare PCB
     (y = +22.55..+31.05 mm, centered at x = 0.0, y = 26.78 mm), with its lens shoulder at z = -1.4 mm and
     its Ø7.2 mm lens tip protruding +1.4 mm into the Ø7.6 mm front bezel bore.
   - The 8.0 mm thick lower ZIF/SD half of the XIAO (y = +10.1..+22.5 mm, z = -16.5..-8.5 mm) tucks cleanly
     behind the top of the standoff-free Waveshare display PCB (z = -1.45..-5.8 mm).
2. Slimmed 18.3 mm Total Depth (15.5 mm Internal Cavity, 1.4 mm Front & Back Walls):
   - Shaves 2.5 mm off V3's 20.8 mm thickness while leaving 0.4–0.8 mm clearance behind the camera stack.
   - Rear mortise sockets (y = +2.4..+9.7 mm) and internal anchor boss (y = +1.2..+10.0 mm) sit just below
     the XIAO's y = +10.1 mm bottom edge so the entire XIAO zone has full 15.5 mm depth to the back floor.
3. V3.2 Print-Hardened Fixes Preserved + 4-Part Buttonless Build Plate:
   - Snug tapered tenon pegs (3.44 x 7.00 mm base), 1.88 mm press-fit saddle ear bore, 2.00 mm clip pivot
     bore, 7.70 mm knuckle in 8.00 mm slot, 3-slot gabled speaker grille, and decoupled button cradles.
   - 4-part build plate (`gotchi_case_v4_plate.stl`) omits button caps since plenty are already printed.
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
    D_out=18.3,
    y_min=-27.0,
    y_max=32.6,
    wall=1.5,
    front_wall=1.4,
    back_wall=1.4,
    split_z=-7.8,  # Front shell: 0.0 to -7.8 mm (7.8 mm); Back shell: -7.8 to -18.3 mm (10.5 mm)

    # 1. Waveshare 1.54" E-Paper Module V2 (33.0 x 48.0 mm PCB, y = -25.5 to +22.5 mm, brass standoffs removed)
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
    disp_zif_z1=-5.8,
    # Display bottom 8-pin PH2.0 right-angle connector (y = -25.4 to -19.5 mm)
    ph20_w=18.5,
    ph20_y0=-25.4,
    ph20_y1=-19.5,
    ph20_z1=-8.5,

    # 2. 803040 LiPo Battery (30.0 x 40.0 x 8.0 mm) nestled behind display PCB
    bat_w=30.0,
    bat_h=40.0,
    bat_d=8.0,
    bat_cy=-9.5,
    bat_y0=-18.6,
    bat_y1=10.0,
    bat_z0=-4.2,
    bat_z1=-12.2,

    # 3. Option 1A Flat Under-Tucked XIAO + Sense (x = -8.9..+8.9 mm, y = +10.1..+31.1 mm):
    xiao_x0=-8.9,
    xiao_x1=8.9,
    xiao_y0=10.1,
    xiao_y1=31.1,
    xiao_z_back=-16.5,
    xiao_z_zif=-8.5,    # 8.0 mm thick across lower ZIF/SD half (y = +10.1..+22.5 mm)
    # Forward-facing PDM MEMS microphone on Sense PCB (pinhole in top crown beside camera lens)
    mic_cx=-6.5,
    mic_cy=25.2,
    mic_d=2.0,
    # Top-wall USB-C port (+Y wall at x = 0.0, z = -14.2 mm)
    usb_cx=0.0,
    usb_cz=-14.2,
    usb_w=9.4,   # along X
    usb_h=3.8,   # along Z

    # 4. Forward-firing Camera (OV2640) at USB-C end of Sense PCB (centered in top crown)
    cam_w=8.5,
    cam_h=8.5,
    cam_cx=0.0,
    cam_cy=26.78,
    cam_lens_d=7.6,
    cam_z0=-0.1,        # Protrudes +1.3 mm into the 1.4 mm front bezel bore!
    cam_z_shoulder=-1.45,
    cam_z1=-16.5,       # 15.05 mm from lens shoulder to back of XIAO

    # 5. Rear Slim Audio Layer (behind battery in lower bay)
    amp_w=19.0,
    amp_h=17.8,
    amp_d=3.0,
    amp_cx=-4.5,
    amp_cy=-9.8,
    amp_z0=-12.8,
    amp_z1=-15.8,

    # Bottom-Edge Direct-Firing Speaker (-Y bottom wall)
    spk_w=15.0,
    spk_h=3.5,
    spk_d=7.8,
    spk_cx=0.0,
    spk_cy=-23.65,
    spk_z0=-8.8,
    spk_z1=-16.6,
    spk_grille_cz=-12.8,

    # 6. Controls:
    ptt_cy=20.5,    # Upper-right side button (BTN_TOP — Voice / Live)
    ptt_cz=-13.2,
    snap_cy=10.5,   # Lower-right side button (BTN_BOT — Camera / 5-Photo Burst)
    snap_cz=-13.2,
    btn_hole_d=3.9,
    # Mini SPDT Slide Switch: Lower-left side wall (-X wall)
    sw_cy=-20.5,
    sw_cz=-12.2,
    sw_slot_y=2.2,
    sw_slot_z=4.8,

    # 7. 360° Press-Fit / Snap-Bead Seam:
    rabbet_lip_w=0.75,
    rabbet_lip_h=1.5,
    rabbet_clearance=0.05,

    # 8. V3.2/V4 Rear Twin-Mortise Hinge Saddle Anchor (below XIAO y=10.1mm so XIAO has full 15.5mm depth):
    mortise_x_in=3.0,
    mortise_x_out=6.6,      # Two 3.6 mm wide sockets at x = ±(3.0..6.6 mm), center x = ±4.8 mm
    mortise_y0=2.4,
    mortise_y1=9.7,         # 7.3 mm tall along Y (y = 2.4..9.7 mm, just below XIAO y = 10.1 mm)
    mortise_z_flat=-15.7,   # Straight vertical walls from z = -18.3 to -15.7 mm (2.6 mm deep)
    mortise_z_apex=-13.9,   # 45° self-supporting roof apex at z = -13.9 mm
    hinge_pin_y=5.1,        # Centered at y = 5.1, z = -21.7
    hinge_pin_z=-21.7,
    saddle_pin_d=1.88,      # Snug horizontal press-fit ear bore for 1.75 mm PLA filament pin
    clip_pin_d=2.00,        # Snug vertical pivot bore (with 0.30 mm entry chamfers) for 1.75 mm filament
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


def make_cone_x(r0, r1, x0, x1, cy=0.0, cz=0.0, sections=48):
    pts = []
    angles = np.linspace(0, 2 * math.pi, sections, endpoint=False)
    for x_val, rad in [(x0, r0), (x1, r1)]:
        for a in angles:
            pts.append([x_val, cy + rad * math.cos(a), cz + rad * math.sin(a)])
    return trimesh.PointCloud(pts).convex_hull


def make_button_bore_x(r, x0, x1, cy=0.0, cz=0.0, sections=48):
    """
    Circular button bore (radius r = 1.95 mm) with a self-supporting 45° top crown
    truncating at a 1.30 mm wide flat bridge ceiling (cz + r + 0.10 mm).
    """
    pts = []
    angles = np.linspace(0, 2 * math.pi, sections, endpoint=False)
    z_tan = r * math.sin(math.radians(45.0))
    y_tan = r * math.cos(math.radians(45.0))
    z_top = r + 0.10
    y_top = max(0.65, y_tan - (z_top - z_tan))
    for x_val in (x0, x1):
        for a in angles:
            dy = r * math.cos(a)
            dz = r * math.sin(a)
            if dz <= z_tan:
                pts.append([x_val, cy + dy, cz + dz])
        pts.extend([
            [x_val, cy - y_tan, cz + z_tan],
            [x_val, cy + y_tan, cz + z_tan],
            [x_val, cy - y_top, cz + z_top],
            [x_val, cy + y_top, cz + z_top],
        ])
    return trimesh.PointCloud(pts).convex_hull


def make_gable_slot_y(x0, x1, y0, y1, z_bottom, z_flat, z_apex):
    """
    Vertical slot cutter along Y with a 45° gabled top roof so the top of
    each slot closes cleanly with zero flat mid-air bridging.
    """
    xm = 0.5 * (x0 + x1)
    pts = [
        [x0, y0, z_bottom], [x1, y0, z_bottom], [x1, y1, z_bottom], [x0, y1, z_bottom],
        [x0, y0, z_flat],   [x1, y0, z_flat],   [x1, y1, z_flat],   [x0, y1, z_flat],
        [xm, y0, z_apex],   [xm, y1, z_apex],
    ]
    return trimesh.PointCloud(pts).convex_hull


def make_mortise_cutter(x0, x1, y0, y1, z_bottom, z_flat, z_apex, z_bed=-18.3, entrance_chamfer=0.18):
    """
    Vertical blind mortise cutter with a 45° self-supporting gabled roof along Z
    and a 0.18 mm 45° entrance chamfer at z_bed.
    """
    xm = 0.5 * (x0 + x1)
    body_pts = [
        [x0, y0, z_bottom], [x1, y0, z_bottom], [x1, y1, z_bottom], [x0, y1, z_bottom],
        [x0, y0, z_flat],   [x1, y0, z_flat],   [x1, y1, z_flat],   [x0, y1, z_flat],
        [xm, y0, z_apex],   [xm, y1, z_apex],
    ]
    body = trimesh.PointCloud(body_pts).convex_hull
    c = entrance_chamfer
    lip_pts = [
        [x0 - c, y0 - c, z_bottom], [x1 + c, y0 - c, z_bottom], [x1 + c, y1 + c, z_bottom], [x0 - c, y1 + c, z_bottom],
        [x0 - c, y0 - c, z_bed],    [x1 + c, y0 - c, z_bed],    [x1 + c, y1 + c, z_bed],    [x0 - c, y1 + c, z_bed],
        [x0, y0, z_bed + c],        [x1, y0, z_bed + c],        [x1, y1, z_bed + c],        [x0, y1, z_bed + c],
    ]
    lip = trimesh.PointCloud(lip_pts).convex_hull
    return trimesh.boolean.union([body, lip], engine='manifold')


def make_rounded_shell_block(w, y0, y1, z0, z1, r_xy=2.8, chamfer_z=0.8, chamfer_top=True, chamfer_bot=True):
    hw = w / 2.0
    pts = []
    z_slices = []
    if chamfer_bot:
        z_slices.append((z0, max(0.2, r_xy - chamfer_z)))
        z_slices.append((z0 + chamfer_z, r_xy))
    else:
        z_slices.append((z0, r_xy))

    if chamfer_top:
        z_slices.append((z1 - chamfer_z, r_xy))
        z_slices.append((z1, max(0.2, r_xy - chamfer_z)))
    else:
        z_slices.append((z1, r_xy))

    angles = np.linspace(0, 2 * math.pi, 48, endpoint=False)
    c_list = [
        (-hw + r_xy, y0 + r_xy),
        (hw - r_xy, y0 + r_xy),
        (hw - r_xy, y1 - r_xy),
        (-hw + r_xy, y1 - r_xy),
    ]
    for z_val, rad in z_slices:
        for cx, cy in c_list:
            for a in angles:
                pts.append([cx + rad * math.cos(a), cy + rad * math.sin(a), z_val])
    cloud = trimesh.PointCloud(pts)
    return cloud.convex_hull


def build_front_shell():
    p = P
    outer = make_rounded_shell_block(
        p['W_out'], p['y_min'], p['y_max'], p['split_z'], 0.0,
        r_xy=2.8, chamfer_z=0.8, chamfer_top=True, chamfer_bot=False
    )
    iw = p['W_out'] - 2 * p['wall']  # 33.4 mm
    cavity = make_box(
        -iw / 2.0, iw / 2.0,
        p['y_min'] + p['wall'], p['y_max'] - p['wall'],
        p['split_z'] - 0.5, -p['front_wall']
    )

    part = trimesh.boolean.difference([outer, cavity], engine='manifold')

    # Continuous 360° Perimeter Rabbet Female Recess at split_z
    rabbet_w = iw + 2 * p['rabbet_lip_w']
    rabbet_y0 = p['y_min'] + p['wall'] - p['rabbet_lip_w']
    rabbet_y1 = p['y_max'] - p['wall'] + p['rabbet_lip_w']
    rabbet_cut = make_rounded_shell_block(
        rabbet_w, rabbet_y0, rabbet_y1,
        p['split_z'] - 0.1, p['split_z'] + p['rabbet_lip_h'] + 0.15,
        r_xy=2.05, chamfer_z=0.0, chamfer_top=False, chamfer_bot=False
    )

    snap_z0 = p['split_z'] + 0.55
    snap_z1 = p['split_z'] + 1.25
    rx = rabbet_w / 2.0
    snap_cuts = [
        make_box(-rx - 0.16, -rx + 0.2, -15.0, 15.0, snap_z0, snap_z1),
        make_box(rx - 0.2, rx + 0.16, -15.0, 15.0, snap_z0, snap_z1),
        make_box(-11.0, 11.0, rabbet_y0 - 0.16, rabbet_y0 + 0.2, snap_z0, snap_z1),
        make_box(-11.0, 11.0, rabbet_y1 - 0.2, rabbet_y1 + 0.16, snap_z0, snap_z1),
    ]

    wy0 = p['win_cy'] - p['win_h'] / 2.0
    wy1 = p['win_cy'] + p['win_h'] / 2.0
    win_cut = make_box(-p['win_w'] / 2.0, p['win_w'] / 2.0, wy0, wy1, -3.0, 1.0)

    fpc_cut = make_box(
        -p['disp_fpc_w'] / 2.0 - 0.5, p['disp_fpc_w'] / 2.0 + 0.5,
        p['disp_fpc_y0'] - 0.2, p['disp_fpc_y1'] + 0.2,
        -2.6, -0.8
    )

    # Centered camera lens opening in top crown (x = 0.0, y = 26.78 mm) + forward PDM mic port (x = -6.5, y = 25.2 mm)
    cam_cut = make_cyl_z(p['cam_lens_d'] / 2.0, -3.0, 1.0, cx=p['cam_cx'], cy=p['cam_cy'])
    mic_cut = make_cyl_z(p['mic_d'] / 2.0, -3.0, 1.0, cx=p['mic_cx'], cy=p['mic_cy'])

    part = trimesh.boolean.difference([part, rabbet_cut, win_cut, fpc_cut, cam_cut, mic_cut] + snap_cuts, engine='manifold')
    return part


def build_back_shell():
    p = P
    outer = make_rounded_shell_block(
        p['W_out'], p['y_min'], p['y_max'], -p['D_out'], p['split_z'],
        r_xy=2.8, chamfer_z=0.8, chamfer_top=False, chamfer_bot=True
    )
    iw = p['W_out'] - 2 * p['wall']  # 33.4 mm
    floor_z = -p['D_out'] + p['back_wall']  # -16.9 mm
    cavity = make_box(
        -iw / 2.0, iw / 2.0,
        p['y_min'] + p['wall'], p['y_max'] - p['wall'],
        floor_z, p['split_z'] + 0.5
    )

    part = trimesh.boolean.difference([outer, cavity], engine='manifold')

    adds = []
    cutters = []

    # 1. Continuous 360° Press-Fit Tongue Lip around all 4 walls
    tongue_out_w = iw + 2 * (p['rabbet_lip_w'] - p['rabbet_clearance'])
    tongue_out_y0 = p['y_min'] + p['wall'] - (p['rabbet_lip_w'] - p['rabbet_clearance'])
    tongue_out_y1 = p['y_max'] - p['wall'] + (p['rabbet_lip_w'] - p['rabbet_clearance'])

    tongue_outer = make_rounded_shell_block(
        tongue_out_w, tongue_out_y0, tongue_out_y1,
        p['split_z'] - 0.2, p['split_z'] + p['rabbet_lip_h'],
        r_xy=2.0, chamfer_z=0.25, chamfer_top=True, chamfer_bot=False
    )
    tongue_inner = make_box(
        -iw / 2.0, iw / 2.0,
        p['y_min'] + p['wall'], p['y_max'] - p['wall'],
        p['split_z'] - 0.5, p['split_z'] + p['rabbet_lip_h'] + 0.5
    )
    tongue_ring = trimesh.boolean.difference([tongue_outer, tongue_inner], engine='manifold')
    adds.append(tongue_ring)

    tx = tongue_out_w / 2.0
    snap_z0 = p['split_z'] + 0.65
    snap_z1 = p['split_z'] + 1.15
    adds.extend([
        make_box(-tx - 0.14, -tx + 0.2, -14.0, 14.0, snap_z0, snap_z1),
        make_box(tx - 0.2, tx + 0.14, -14.0, 14.0, snap_z0, snap_z1),
        make_box(-10.0, 10.0, tongue_out_y0 - 0.14, tongue_out_y0 + 0.2, snap_z0, snap_z1),
        make_box(-10.0, 10.0, tongue_out_y1 - 0.2, tongue_out_y1 + 0.14, snap_z0, snap_z1),
    ])

    # 2. Option 1A Low-Profile Side Guide Rails on Back Floor (x = ±(9.15..10.25 mm), y = +10.5..+30.5 mm)
    #    Cradles the flat 17.8 mm-wide XIAO (x = -8.9..+8.9 mm) with 0.25 mm clearance per side while keeping
    #    the entire y = +10.1..+31.1 mm floor 100% open at z = -16.9 mm!
    adds.append(make_box(-10.25, -9.15, 10.5, 30.5, floor_z, floor_z + 1.8))
    adds.append(make_box(9.15, 10.25, 10.5, 30.5, floor_z, floor_z + 1.8))

    # 3. Grounded Side Button Alignment Cradles (Decoupled from Right Sidewall above Z=-15.9) + 45°-Crowned Ø3.9 mm Button Bores
    cradle_base = make_box(iw / 2.0 - 4.4, iw / 2.0 + 0.1, p['snap_cy'] - 4.65, p['ptt_cy'] + 4.65, floor_z, floor_z + 1.0)
    cradle_upper = make_box(iw / 2.0 - 4.4, iw / 2.0 - 0.85, p['snap_cy'] - 4.65, p['ptt_cy'] + 4.65, floor_z, p['ptt_cz'] + 0.9)
    cradle_block = trimesh.boolean.union([cradle_base, cradle_upper], engine='manifold')
    pocket_cuts = []
    for by, bz in [(p['ptt_cy'], p['ptt_cz']), (p['snap_cy'], p['snap_cz'])]:
        pocket_cuts.append(make_box(iw / 2.0 - 3.65, iw / 2.0 + 0.5, by - 3.35, by + 3.35, bz - 3.3, bz + 1.2))
        cutters.append(make_button_bore_x(p['btn_hole_d'] / 2.0, iw / 2.0 - 0.6, p['W_out'] / 2.0 + 1.0, cy=by, cz=bz))
    adds.append(trimesh.boolean.difference([cradle_block] + pocket_cuts, engine='manifold'))

    # 4. Option 1A Top-Wall USB-C Opening (+Y top wall at x = usb_cx, z = usb_cz)
    cutters.append(make_box(
        p['usb_cx'] - p['usb_w'] / 2.0, p['usb_cx'] + p['usb_w'] / 2.0,
        p['y_max'] - p['wall'] - 1.0, p['y_max'] + 1.0,
        p['usb_cz'] - p['usb_h'] / 2.0, p['usb_cz'] + p['usb_h'] / 2.0
    ))

    # 5. Lower-left SPDT slide switch slot (-X left wall at y = sw_cy, z = sw_cz)
    cutters.append(make_box(
        -p['W_out'] / 2.0 - 1.0, -iw / 2.0 + 1.0,
        p['sw_cy'] - p['sw_slot_y'] / 2.0, p['sw_cy'] + p['sw_slot_y'] / 2.0,
        p['sw_cz'] - p['sw_slot_z'] / 2.0, p['sw_cz'] + p['sw_slot_z'] / 2.0
    ))

    # 6. Bottom-Edge 3-Slot Gabled Speaker Grille (-Y bottom wall: 2 wide 2.8 mm pillars + 45° roofs eliminate stringing)
    for ix in (-1, 0, 1):
        gx = p['spk_cx'] + ix * 4.2
        cutters.append(make_gable_slot_y(
            gx - 0.70, gx + 0.70,
            p['y_min'] - 0.5, p['y_min'] + p['wall'] + 0.5,
            p['spk_grille_cz'] - 2.6, p['spk_grille_cz'] + 1.9, p['spk_grille_cz'] + 2.6
        ))

    # 7. V4 Internal Hinge Anchor Boss (y = +1.2..+10.0 mm, z = -16.9..-13.0 mm, right below the flat XIAO y>=10.1 mm
    #    and behind the 803040 battery z>=-12.2 mm, so it doubles as the bottom registration stop for the XIAO!)
    anchor_boss = make_box(-8.2, 8.2, 1.2, 10.0, floor_z - 0.3, -13.0)
    adds.append(anchor_boss)

    mortise_l = make_mortise_cutter(
        -p['mortise_x_out'], -p['mortise_x_in'],
        p['mortise_y0'], p['mortise_y1'],
        -p['D_out'] - 0.5, p['mortise_z_flat'], p['mortise_z_apex'],
        z_bed=-p['D_out']
    )
    mortise_r = make_mortise_cutter(
        p['mortise_x_in'], p['mortise_x_out'],
        p['mortise_y0'], p['mortise_y1'],
        -p['D_out'] - 0.5, p['mortise_z_flat'], p['mortise_z_apex'],
        z_bed=-p['D_out']
    )
    cutters.extend([mortise_l, mortise_r])

    part = trimesh.boolean.union([part] + adds, engine='manifold')
    part = trimesh.boolean.difference([part] + cutters, engine='manifold')
    return part


def build_button_cap():
    flange = make_cyl_z(5.5 / 2.0, 0.0, 1.0)
    pts = []
    angles = np.linspace(0, 2 * math.pi, 48, endpoint=False)
    for z_val, rad in [(0.95, 2.75), (1.80, 1.70), (3.55, 1.70), (3.80, 1.45)]:
        for a in angles:
            pts.append([rad * math.cos(a), rad * math.sin(a), z_val])
    stem = trimesh.PointCloud(pts).convex_hull
    return trimesh.boolean.union([flange, stem], engine='manifold')


def make_tapered_peg(x_center, y_top=9.52):
    """
    Snug friction press-fit tenon peg for the V3.2/V4 `gotchi_back` mortise sockets
    (nominal CAD socket: x = ±(3.00..6.60 mm) [width 3.60 mm, center ±4.80 mm],
    y = 2.40..9.70 mm [length 7.30 mm], flat depth 2.60 mm from z = -18.30 to -15.70 mm):
    - Base (z = -18.35 mm): 3.44 x 7.00 mm (0.08 mm/wall X press-fit clearance, 0.12..0.18 mm/wall Y clearance)
    - Shoulder (z = -16.45 mm): 3.36 x 6.90 mm (1.90 mm deep full-contact friction body)
    - Lead-in chamfered tip (z = -15.95 mm, 2.35 mm deep): 2.80 x 6.20 mm self-aligning nose
    - Coplanar top face at y = y_top (9.52 mm) so the saddle prints 100% flat on Z=0 (rot_x_neg90).
    """
    y0_base = P['mortise_y0'] + 0.12  # 2.52 mm
    z_base = -P['D_out'] - 0.05       # -18.35 mm
    z_sh = -P['D_out'] + 1.85         # -16.45 mm
    z_tip = -P['D_out'] + 2.35        # -15.95 mm
    pts = [
        [x_center - 1.58, y_top, z_base],
        [x_center + 1.58, y_top, z_base],
        [x_center + 1.52, y_top, z_sh],
        [x_center - 1.52, y_top, z_sh],
        [x_center - 1.72, y0_base, z_base],
        [x_center + 1.72, y0_base, z_base],
        [x_center + 1.72, y_top - 0.15, z_base],
        [x_center - 1.72, y0_base, z_base],
        [x_center - 1.72, y_top - 0.15, z_base],
        [x_center - 1.68, y0_base + 0.08, z_sh],
        [x_center + 1.68, y0_base + 0.08, z_sh],
        [x_center + 1.68, y_top - 0.18, z_sh],
        [x_center - 1.68, y_top - 0.18, z_sh],
        [x_center - 1.40, y0_base + 0.43, z_tip],
        [x_center + 1.40, y0_base + 0.43, z_tip],
        [x_center + 1.40, y_top - 0.42, z_tip],
        [x_center - 1.40, y_top - 0.42, z_tip],
    ]
    return trimesh.PointCloud(pts).convex_hull


def build_hinge_saddle():
    """
    V3.2/V4 Snug Press-Fit Hinge Saddle (`gotchi_hinge_saddle.stl`):
    - Two snug press-fit tenon pegs (3.44 x 7.00 mm base -> 3.36 x 6.90 mm shoulder -> 2.80 x 6.20 mm tip,
      2.35 mm deep) lock into the back shell's twin mortise sockets.
    - Shared flat y_top = 9.52 mm plane so the saddle prints 100% flat on the Z=0 build plate.
    - 8.00 mm wide ear slot (x = ±4.00 mm) around the 7.70 mm clip knuckle and Ø1.88 mm press-fit pin bore.
    """
    p = P
    y_top = p['mortise_y1'] - 0.18  # 9.52 mm
    z_back = -p['D_out']            # -18.30 mm
    peg_l = make_tapered_peg(-4.80, y_top=y_top)
    peg_r = make_tapered_peg(4.80, y_top=y_top)
    center_floor = make_box(-7.6, 7.6, 1.1, y_top, z_back - 1.05, z_back)
    ear_l = make_box(-7.6, -4.0, 2.1, y_top, z_back - 5.70, z_back)
    ear_r = make_box(4.0, 7.6, 2.1, y_top, z_back - 5.70, z_back)
    stop_wall = make_box(-4.1, 4.1, 7.98, y_top, z_back - 5.70, z_back)

    saddle = trimesh.boolean.union([peg_l, peg_r, center_floor, ear_l, ear_r, stop_wall], engine='manifold')
    pin_bore = make_cyl_x(p['saddle_pin_d'] / 2.0, -8.5, 8.5, cy=p['hinge_pin_y'], cz=p['hinge_pin_z'])
    r_in = p['saddle_pin_d'] / 2.0
    r_out = r_in + 0.25
    cs1 = make_cone_x(r_out, r_in, -7.65, -7.35, cy=p['hinge_pin_y'], cz=p['hinge_pin_z'])
    cs4 = make_cone_x(r_in, r_out, 7.35, 7.65, cy=p['hinge_pin_y'], cz=p['hinge_pin_z'])
    saddle = trimesh.boolean.difference([saddle, pin_bore, cs1, cs4], engine='manifold')
    return saddle


def build_clip_stand_arm():
    """
    V3.2/V4 1-Piece Hinged Combo Shirt-Pocket Clip & Desk Kickstand Arm (`gotchi_clip_stand.stl`):
    - 7.70 mm width (hw = 3.85 mm) fits snugly inside the 8.00 mm saddle slot (0.15 mm clearance/side).
    - Snug Ø2.00 mm vertical pivot bore with 0.30 mm entry chamfers on both ends.
    - Pinch jaw extended to 0.08 mm off the z = -18.30 mm rear shell wall for firm closed clip tension.
    """
    p = P
    hw = 3.85
    z_back = -p['D_out']  # -18.30 mm
    knuckle = make_cyl_x(2.20, -hw, hw, cy=p['hinge_pin_y'], cz=p['hinge_pin_z'])
    stop_heel = make_box(-hw, hw, p['hinge_pin_y'], p['hinge_pin_y'] + 2.00, z_back - 5.70, p['hinge_pin_z'])
    arm_beam = make_box(-hw, hw, -22.5, p['hinge_pin_y'], z_back - 5.60, z_back - 3.00)
    pinch_jaw = make_box(-hw, hw, -19.5, -15.0, z_back - 3.20, z_back - 0.08)
    ski_tip = make_box(-hw, hw, -25.0, -21.5, z_back - 6.40, z_back - 3.40)

    arm = trimesh.boolean.union([knuckle, stop_heel, arm_beam, pinch_jaw, ski_tip], engine='manifold')
    pin_bore = make_cyl_x(p['clip_pin_d'] / 2.0, -hw - 1.0, hw + 1.0, cy=p['hinge_pin_y'], cz=p['hinge_pin_z'])
    r_in = p['clip_pin_d'] / 2.0
    r_out = r_in + 0.30
    cc1 = make_cone_x(r_out, r_in, -hw - 0.05, -hw + 0.30, cy=p['hinge_pin_y'], cz=p['hinge_pin_z'])
    cc2 = make_cone_x(r_in, r_out, hw - 0.30, hw + 0.05, cy=p['hinge_pin_y'], cz=p['hinge_pin_z'])
    arm = trimesh.boolean.difference([arm, pin_bore, cc1, cc2], engine='manifold')
    return arm


def build_internal_3d_components():
    """Build true multi-feature 3D component meshes for Option 1A and verify zero collisions."""
    p = P
    iw = p['W_out'] - 2 * p['wall']  # 33.4 mm
    comps = {}

    ws_pcb = make_box(-p['disp_w']/2, p['disp_w']/2, p['disp_y0'], p['disp_y1'], p['disp_pcb_z1'], p['disp_pcb_z0'])
    ws_glass = make_box(-p['disp_glass_w']/2, p['disp_glass_w']/2, p['disp_glass_y0'], p['disp_glass_y1'], p['disp_glass_z1'], p['disp_glass_z0'])
    ws_fpc = make_box(-p['disp_fpc_w']/2, p['disp_fpc_w']/2, p['disp_fpc_y0'], p['disp_fpc_y1'], p['disp_zif_z1'], -0.9)
    ws_ph20 = make_box(-p['ph20_w']/2, p['ph20_w']/2, p['disp_y0'] + 0.1, p['ph20_y1'], p['ph20_z1'], p['disp_pcb_z1'])
    comps['display_composite'] = trimesh.boolean.union([ws_pcb, ws_glass, ws_fpc, ws_ph20], engine='manifold')

    # Battery envelope in lower/mid bay
    comps['battery_pack'] = make_box(-p['bat_w']/2, p['bat_w']/2, p['bat_y0'], p['bat_y1'], p['bat_z1'], p['bat_z0'])

    # Option 1A Stepped Flat XIAO + Sense + Camera Stack:
    # - Lower ZIF/SD half (y = +10.1..+22.55 mm): 8.0 mm thick (z = -16.5..-8.5 mm), tucked behind display PCB!
    # - Upper Camera Tower (y = +22.55..+31.05 mm): 8.5 x 8.5 mm housing from z = -16.5 to -1.45 mm + Ø7.0 mm lens barrel to z = -0.1 mm!
    xiao_lower = make_box(p['xiao_x0'], p['xiao_x1'], p['xiao_y0'], 22.55, p['xiao_z_back'], p['xiao_z_zif'])
    xiao_upper_pcb = make_box(p['xiao_x0'], p['xiao_x1'], 22.50, p['xiao_y1'], p['xiao_z_back'], p['xiao_z_zif'])
    cam_tower = make_box(
        p['cam_cx'] - p['cam_w']/2, p['cam_cx'] + p['cam_w']/2,
        p['cam_cy'] - p['cam_h']/2, p['cam_cy'] + p['cam_h']/2,
        p['xiao_z_zif'] - 0.2, p['cam_z_shoulder']
    )
    cam_lens = make_cyl_z(p['cam_lens_d']/2 - 0.3, p['cam_z_shoulder'] - 0.2, p['cam_z0'], cx=p['cam_cx'], cy=p['cam_cy'])
    comps['xiao_sense_camera_1a'] = trimesh.boolean.union([xiao_lower, xiao_upper_pcb, cam_tower, cam_lens], engine='manifold')

    comps['speaker_1510'] = make_box(p['spk_cx'] - p['spk_w']/2, p['spk_cx'] + p['spk_w']/2, p['spk_cy'] - p['spk_h']/2, p['spk_cy'] + p['spk_h']/2, p['spk_z1'], p['spk_z0'])
    comps['amp_max98357a'] = make_box(p['amp_cx'] - p['amp_w']/2, p['amp_cx'] + p['amp_w']/2, p['amp_cy'] - p['amp_h']/2, p['amp_cy'] + p['amp_h']/2, p['amp_z1'], p['amp_z0'])

    ptt_body = make_box(iw / 2.0 - 3.6, iw / 2.0 - 0.1, p['ptt_cy'] - 3.0, p['ptt_cy'] + 3.0, p['ptt_cz'] - 3.0, p['ptt_cz'] + 0.8)
    ptt_stem = make_cyl_x(1.6, iw / 2.0 - 0.2, iw / 2.0 + 1.3, cy=p['ptt_cy'], cz=p['ptt_cz'])
    comps['btn_top_tactile'] = trimesh.boolean.union([ptt_body, ptt_stem], engine='manifold')

    snap_body = make_box(iw / 2.0 - 3.6, iw / 2.0 - 0.1, p['snap_cy'] - 3.0, p['snap_cy'] + 3.0, p['snap_cz'] - 3.0, p['snap_cz'] + 0.8)
    snap_stem = make_cyl_x(1.6, iw / 2.0 - 0.2, iw / 2.0 + 1.3, cy=p['snap_cy'], cz=p['snap_cz'])
    comps['btn_bot_tactile'] = trimesh.boolean.union([snap_body, snap_stem], engine='manifold')

    sw_body = make_box(-iw / 2.0 + 0.1, -iw / 2.0 + 3.6, p['sw_cy'] - 1.75, p['sw_cy'] + 1.75, p['sw_cz'] - 4.25, p['sw_cz'] + 4.25)
    sw_knob = make_box(-iw / 2.0 - 1.3, -iw / 2.0 + 0.2, p['sw_cy'] - 0.8, p['sw_cy'] + 0.8, p['sw_cz'] - 1.0, p['sw_cz'] + 1.0)
    comps['spdt_slide_switch'] = trimesh.boolean.union([sw_body, sw_knob], engine='manifold')

    return comps


def export_stls(out_dir, front, back, cap, saddle, clip_stand):
    stl_dir = os.path.join(out_dir, "stl")
    os.makedirs(stl_dir, exist_ok=True)

    # 1. Front shell: flip 180 deg around X so flat front face rests on Z=0 bed
    front_print = front.copy()
    rot_x180 = trimesh.transformations.rotation_matrix(math.pi, [1, 0, 0])
    front_print.apply_transform(rot_x180)
    front_print.apply_translation([-front_print.centroid[0], -front_print.centroid[1], -front_print.bounds[0][2]])
    front_print.export(os.path.join(stl_dir, "gotchi_front.stl"))

    # 2. Back shell: 100% flat rear face rests on Z=0 bed
    back_print = back.copy()
    back_print.apply_translation([-back_print.centroid[0], -back_print.centroid[1], -back_print.bounds[0][2]])
    back_print.export(os.path.join(stl_dir, "gotchi_back.stl"))

    # 3. Button cap (exported to stl/ for reference, omitted from V4 build plate per Ryan's instruction)
    cap_print = cap.copy()
    cap_print.apply_translation([-cap_print.centroid[0], -cap_print.centroid[1], -cap_print.bounds[0][2]])
    cap_print.export(os.path.join(stl_dir, "gotchi_button_cap.stl"))

    # 4. Hinge Saddle: orient with shared flat y_top = 9.52 mm face on Z=0 bed (rot_x_neg90, zero overhang!)
    saddle_print = saddle.copy()
    rot_x_neg90 = trimesh.transformations.rotation_matrix(-math.pi / 2.0, [1, 0, 0])
    saddle_print.apply_transform(rot_x_neg90)
    saddle_print.apply_translation([-saddle_print.centroid[0], -saddle_print.centroid[1], -saddle_print.bounds[0][2]])
    saddle_print.export(os.path.join(stl_dir, "gotchi_hinge_saddle.stl"))

    # 5. Hinged Clip-Stand Arm: orient flat on its side (+X/-X profile on Z=0 bed, 100% flat bottom, 0 supports!)
    arm_print = clip_stand.copy()
    rot_y90 = trimesh.transformations.rotation_matrix(math.pi / 2.0, [0, 1, 0])
    arm_print.apply_transform(rot_y90)
    arm_print.apply_translation([-arm_print.centroid[0], -arm_print.centroid[1], -arm_print.bounds[0][2]])
    arm_print.export(os.path.join(stl_dir, "gotchi_clip_stand.stl"))

    # 6. Combined V4 4-Part Build Plate (`/workspace/data/3dprint/gotchi_case_v4_plate.stl` — NO Button Caps)
    #    Keep Back Shell on the far right (+X = +26.0) with ZERO islands to its right (+X button wall)
    #    or front (-Y speaker grille), placing Hinge Saddle and Clip Arm on the far left (-X).
    plate_parts = []
    f_p = front_print.copy()
    f_p.apply_translation([-16.0, 0.0, 0.0])
    plate_parts.append(f_p)

    b_p = back_print.copy()
    b_p.apply_translation([26.0, 0.0, 0.0])
    plate_parts.append(b_p)

    s_p = saddle_print.copy()
    s_p.apply_translation([-48.0, 18.0, 0.0])
    plate_parts.append(s_p)

    a_p = arm_print.copy()
    a_p.apply_translation([-48.0, -10.0, 0.0])
    plate_parts.append(a_p)

    plate = trimesh.util.concatenate(plate_parts)
    plate_out_v4 = "/workspace/data/3dprint/gotchi_case_v4_plate.stl"
    plate_out_v3 = "/workspace/data/3dprint/gotchi_case_v3_plate.stl"
    os.makedirs(os.path.dirname(plate_out_v4), exist_ok=True)
    plate.export(plate_out_v4)
    plate.export(plate_out_v3)

    print(f"Exported watertight print-oriented V4 STLs to {stl_dir}/ and {plate_out_v4}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=os.path.dirname(os.path.abspath(__file__)))
    args, _ = parser.parse_known_args()

    front = build_front_shell()
    back = build_back_shell()
    cap = build_button_cap()
    saddle = build_hinge_saddle()
    clip_stand = build_clip_stand_arm()
    comps = build_internal_3d_components()

    for name, m in [
        ("front", front),
        ("back", back),
        ("button_cap", cap),
        ("hinge_saddle", saddle),
        ("clip_stand", clip_stand),
    ]:
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

    # Verify Hinge Saddle vs Back Shell mortises & Clip-Stand vs Hinge Saddle across 0..20 deg + alignment shifts
    inter_sb = trimesh.boolean.intersection([back, saddle], engine='manifold')
    vol_sb = inter_sb.volume if not inter_sb.is_empty else 0.0
    if vol_sb > 0.01:
        print(f"SADDLE vs BACK_SHELL OVERLAP: {vol_sb:.3f} mm^3")
        hits += 1
    for deg in range(0, 22, 2):
        arm_rot = clip_stand.copy()
        T1 = trimesh.transformations.translation_matrix([0, -P['hinge_pin_y'], -P['hinge_pin_z']])
        R = trimesh.transformations.rotation_matrix(math.radians(deg), [1, 0, 0])
        T2 = trimesh.transformations.translation_matrix([0, P['hinge_pin_y'], P['hinge_pin_z']])
        arm_rot.apply_transform(T2 @ R @ T1)
        inter_sc = trimesh.boolean.intersection([saddle, arm_rot], engine='manifold')
        vol_sc = inter_sc.volume if not inter_sc.is_empty else 0.0
        if vol_sc > 0.01:
            print(f"HINGE OVERLAP at {deg} deg: {vol_sc:.3f} mm^3")
            hits += 1
    for shift_vec in [[0, 0, 0.12], [0, 0.12, 0], [0.12, 0, 0], [-0.12, 0, 0]]:
        arm_sh = clip_stand.copy()
        arm_sh.apply_translation(shift_vec)
        inter_sh = trimesh.boolean.intersection([saddle, arm_sh], engine='manifold')
        vol_sh = inter_sh.volume if not inter_sh.is_empty else 0.0
        if vol_sh > 0.01:
            print(f"HINGE SHIFT OVERLAP at {shift_vec}: {vol_sh:.3f} mm^3")
            hits += 1

    if hits > 0:
        raise RuntimeError(f"Detected {hits} collision(s)!")
    print("ALL 3D COMPONENT, SHELL & HINGE CLEARANCES VERIFIED: 0 COLLISIONS (0.00 mm^3)")

    export_stls(args.out, front, back, cap, saddle, clip_stand)


if __name__ == "__main__":
    main()
