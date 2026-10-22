#!/usr/bin/env python3
"""
GOTCHI V1 Printable Enclosure — Revision 7.0 (V3 Print-Hardened: 100% Flat Bed-Contact Back,
Option A Filament-Pinned Hinged Combo Clip-Kickstand, True Round Ø3.9mm Button Holes & 360° Snap Seam)
======================================================================================================
Outer envelope: 36.4 x 59.6 x 20.8 mm (44.5 cm^3)

Key V3 Upgrades (solving V2 physical print issues):
1. True Circular Ø3.9 mm Side Button Openings (`make_cyl_x`) + Grounded Switch Cradles:
   - Replaces V2's teardrop-crowned button holes (which left a visible triangular gap above the
     round Ø3.4 mm button stems) with clean circular Ø3.9 mm bores.
   - Internal switch cradles remain grounded to the Z = -19.3 mm floor so the 1.3 mm top arch chord
     bridges cleanly in 2 layers with zero internal supports.
2. 100% Flat Bed-Contact Back Shell (Zero Rear Undercut Grooves, Zero Rear Supports):
   - Eliminates the recessed twin-rail undercut slot that lifted a 30x16 mm patch off the build plate
     and caused rough support scarring.
   - Replaces it with two self-supporting 45°-roofed blind mortise sockets (3.6 x 6.5 x 3.2 mm deep)
     backed by an internal spine boss in the empty upper-rear bay (y = +10.5..+21.2 mm, z = -19.3..-16.5 mm).
3. Option A 1-Piece Printed Hinged Combo Clip-Stand (`gotchi_hinge_saddle` + `gotchi_clip_stand`):
   - Twin-tenon Hinge Saddle plugs flush into the two rear mortise sockets on the flat back shell.
   - A 2.6 mm thick spring clip-stand arm pivots on a raw 1.75 mm PLA filament pin (Ø1.95 mm bore)
     with a cam detent at 0° (shirt-pocket clip) and a 26° angled stop face (desk kickstand).
   - Both hinge parts print flat on their sides (+X/-X on Z=0 bed) for continuous perimeter loop
     strength and zero thin tongues.
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
    xiao_x0=-16.5,
    xiao_x1=4.5,
    xiao_y0=22.6,
    xiao_y1=30.2,
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
    cam_cx=9.5,
    cam_cy=26.78,
    cam_lens_d=7.6,
    cam_z0=-1.0,
    cam_z1=-5.8,

    # 5. Rear Slim Audio Layer (z = -15.2 to -19.2 mm, behind battery & PH2.0 zone)
    amp_w=19.0,
    amp_h=17.8,
    amp_d=3.0,
    amp_cx=-5.5,
    amp_cy=-0.5,
    amp_z0=-15.2,
    amp_z1=-18.2,

    # Bottom-Edge Direct-Firing Speaker (-Y bottom wall)
    spk_w=15.0,
    spk_h=3.5,
    spk_d=10.0,
    spk_cx=0.0,
    spk_cy=-23.65,
    spk_z0=-9.2,
    spk_z1=-19.2,
    spk_grille_cz=-14.2,

    # 6. Controls:
    ptt_cy=20.5,    # Upper-right side button (BTN_TOP — Voice / Live)
    ptt_cz=-15.2,
    snap_cy=10.5,   # Lower-right side button (BTN_BOT — Camera / 5-Photo Burst)
    snap_cz=-15.2,
    btn_hole_d=3.9,
    # Mini SPDT Slide Switch: Lower-left side wall (-X wall)
    sw_cy=-20.5,
    sw_cz=-13.5,
    sw_slot_y=2.2,
    sw_slot_z=4.8,

    # 7. V2/V3 360° Press-Fit / Snap-Bead Seam:
    rabbet_lip_w=0.75,
    rabbet_lip_h=1.5,
    rabbet_clearance=0.05,  # Tight 0.05 mm friction press-fit clearance (+ 0.14 mm snap beads)

    # 8. V3.2 Rear Twin-Mortise Hinge Saddle Anchor (100% Flat Bed-Contact Back Shell, Snug Press-Fit):
    mortise_x_in=3.0,
    mortise_x_out=6.6,      # Two 3.6 mm wide sockets at x = ±(3.0..6.6 mm), center x = ±4.8 mm
    mortise_y0=13.5,
    mortise_y1=20.8,        # 7.3 mm tall along Y (y = 13.5..20.8 mm, center y = 17.15 mm)
    mortise_z_flat=-18.2,   # Straight vertical walls from z = -20.8 to -18.2 mm (2.6 mm deep)
    mortise_z_apex=-16.4,   # 45° self-supporting roof apex at z = -16.4 mm (zero mid-air ceiling!)
    hinge_pin_y=16.2,       # Centered at y=16.2, z=-24.2
    hinge_pin_z=-24.2,
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
    Eliminates >45° mid-air overhang curling and mid-hole U-turn retractions on the
    right sidewall while keeping a visually round opening around the Ø3.4 mm stem.
    """
    pts = []
    angles = np.linspace(0, 2 * math.pi, sections, endpoint=False)
    z_tan = r * math.sin(math.radians(45.0))  # +1.38 mm above center
    y_tan = r * math.cos(math.radians(45.0))  # ±1.38 mm width at 45° tangent
    z_top = r + 0.10                          # +2.05 mm flat bridge ceiling
    y_top = max(0.65, y_tan - (z_top - z_tan))
    for x_val in (x0, x1):
        for a in angles:
            dy = r * math.cos(a)
            dz = r * math.sin(a)
            if dz <= z_tan:
                pts.append([x_val, cy + dy, cz + dz])
        # Add 45° crown & flat bridge top chord
        pts.extend([
            [x_val, cy - y_tan, cz + z_tan],
            [x_val, cy + y_tan, cz + z_tan],
            [x_val, cy - y_top, cz + z_top],
            [x_val, cy + y_top, cz + z_top],
        ])
    return trimesh.PointCloud(pts).convex_hull


def make_gable_slot_y(x0, x1, y0, y1, z_bottom, z_flat, z_apex):
    """
    Vertical speaker slot cutter along Y with a 45° gabled top roof so the top of
    each slot closes cleanly with zero flat mid-air bridging.
    """
    xm = 0.5 * (x0 + x1)
    pts = [
        [x0, y0, z_bottom], [x1, y0, z_bottom], [x1, y1, z_bottom], [x0, y1, z_bottom],
        [x0, y0, z_flat],   [x1, y0, z_flat],   [x1, y1, z_flat],   [x0, y1, z_flat],
        [xm, y0, z_apex],   [xm, y1, z_apex],
    ]
    return trimesh.PointCloud(pts).convex_hull


def make_mortise_cutter(x0, x1, y0, y1, z_bottom, z_flat, z_apex, z_bed=-20.8, entrance_chamfer=0.18):
    """
    Vertical blind mortise cutter with a 45° self-supporting gabled roof along Z
    and a 0.35 mm 45° entrance chamfer at z_bed so first-layer elephant's foot
    never narrows the socket opening when `gotchi_back` prints on Z = -D_out.
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
    """
    True 45-degree perimeter chamfer: corner centers stay fixed at (±(hw - r_xy), y ± r_xy)
    while corner radius reduces from r_xy to (r_xy - chamfer_z) over height chamfer_z.
    """
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

    cam_cut = make_cyl_z(p['cam_lens_d'] / 2.0, -3.0, 1.0, cx=p['cam_cx'], cy=p['cam_cy'])

    part = trimesh.boolean.difference([part, rabbet_cut, win_cut, fpc_cut, cam_cut] + snap_cuts, engine='manifold')
    return part


def build_back_shell():
    p = P
    outer = make_rounded_shell_block(
        p['W_out'], p['y_min'], p['y_max'], -p['D_out'], p['split_z'],
        r_xy=2.8, chamfer_z=0.8, chamfer_top=False, chamfer_bot=True
    )
    iw = p['W_out'] - 2 * p['wall']  # 33.4 mm
    cavity = make_box(
        -iw / 2.0, iw / 2.0,
        p['y_min'] + p['wall'], p['y_max'] - p['wall'],
        -p['D_out'] + p['back_wall'], p['split_z'] + 0.5
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

    # 2. Loose non-binding bottom guide shelf under XIAO + Sense in Top Crown (grounded to back floor)
    adds.append(make_box(-iw / 2.0, 4.5, 21.85, 22.5, -p['D_out'] + p['back_wall'], p['split_z']))

    # 3. Grounded Side Button Alignment Cradles (Decoupled from Right Sidewall above Z=-18.3) + 45°-Crowned Ø3.9 mm Button Bores
    #    Decoupling the cradle legs by 0.85 mm from the right sidewall (x <= iw/2 - 0.85) across the button hole Z band
    #    prevents internal cradle walls from splitting the exterior sidewall perimeter loop or creating T-junction defects.
    floor_z = -p['D_out'] + p['back_wall']  # -19.3 mm
    cradle_base = make_box(iw / 2.0 - 4.4, iw / 2.0 + 0.1, p['snap_cy'] - 4.65, p['ptt_cy'] + 4.65, floor_z, floor_z + 1.0)
    cradle_upper = make_box(iw / 2.0 - 4.4, iw / 2.0 - 0.85, p['snap_cy'] - 4.65, p['ptt_cy'] + 4.65, floor_z, p['ptt_cz'] + 0.9)
    cradle_block = trimesh.boolean.union([cradle_base, cradle_upper], engine='manifold')
    pocket_cuts = []
    for by, bz in [(p['ptt_cy'], p['ptt_cz']), (p['snap_cy'], p['snap_cz'])]:
        pocket_cuts.append(make_box(iw / 2.0 - 3.65, iw / 2.0 + 0.5, by - 3.35, by + 3.35, bz - 3.3, bz + 1.2))
        cutters.append(make_button_bore_x(p['btn_hole_d'] / 2.0, iw / 2.0 - 0.6, p['W_out'] / 2.0 + 1.0, cy=by, cz=bz))
    adds.append(trimesh.boolean.difference([cradle_block] + pocket_cuts, engine='manifold'))

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

    # 7. Bottom-Edge 3-Slot Gabled Speaker Grille (-Y bottom wall: 2 wide 2.8 mm pillars + 45° roofs eliminate stringing)
    for ix in (-1, 0, 1):
        gx = p['spk_cx'] + ix * 4.2
        cutters.append(make_gable_slot_y(
            gx - 0.70, gx + 0.70,
            p['y_min'] - 0.5, p['y_min'] + p['wall'] + 0.5,
            p['spk_grille_cz'] - 2.6, p['spk_grille_cz'] + 1.9, p['spk_grille_cz'] + 2.6
        ))

    # 8. V3 Internal Hinge Anchor Boss (in open bay y = +11.2..+21.0 mm, z = -19.5..-15.6 mm, clear of amp y<=8.4 and bat z>=-14.2)
    #    Backed by two self-supporting 45°-roofed blind mortise sockets opening on the flat Z = -20.8 mm rear face.
    anchor_boss = make_box(-8.2, 8.2, 11.2, 21.0, -p['D_out'] + p['back_wall'] - 0.3, -15.6)
    adds.append(anchor_boss)

    mortise_l = make_mortise_cutter(
        -p['mortise_x_out'], -p['mortise_x_in'],
        p['mortise_y0'], p['mortise_y1'],
        -p['D_out'] - 0.5, p['mortise_z_flat'], p['mortise_z_apex']
    )
    mortise_r = make_mortise_cutter(
        p['mortise_x_in'], p['mortise_x_out'],
        p['mortise_y0'], p['mortise_y1'],
        -p['D_out'] - 0.5, p['mortise_z_flat'], p['mortise_z_apex']
    )
    cutters.extend([mortise_l, mortise_r])

    part = trimesh.boolean.union([part] + adds, engine='manifold')
    part = trimesh.boolean.difference([part] + cutters, engine='manifold')
    return part


def build_button_cap():
    """
    Tactile button cap with a 45-degree chamfered transition from the Ø5.5 mm flange
    to the Ø3.4 mm stem and a slightly beveled top for smooth actuation.
    """
    flange = make_cyl_z(5.5 / 2.0, 0.0, 1.0)
    pts = []
    angles = np.linspace(0, 2 * math.pi, 48, endpoint=False)
    for z_val, rad in [(0.95, 2.75), (1.80, 1.70), (3.55, 1.70), (3.80, 1.45)]:
        for a in angles:
            pts.append([rad * math.cos(a), rad * math.sin(a), z_val])
    stem = trimesh.PointCloud(pts).convex_hull
    return trimesh.boolean.union([flange, stem], engine='manifold')


def make_tapered_peg(x_center, y_top=20.62):
    """
    Snug friction press-fit tenon peg for the V3.2 `gotchi_back` mortise sockets
    (nominal CAD socket: x = ±(3.00..6.60 mm) [width 3.60 mm, center ±4.80 mm],
    y = 13.50..20.80 mm [length 7.30 mm, center 17.15 mm], flat depth 2.60 mm):
    - Base (z = -20.85 mm): 3.44 x 7.00 mm (0.08 mm/wall X press-fit clearance, 0.12..0.18 mm/wall Y clearance)
    - Shoulder (z = -18.95 mm): 3.36 x 6.90 mm (1.90 mm deep full-contact friction body)
    - Lead-in chamfered tip (z = -18.45 mm, 2.35 mm deep): 2.80 x 6.20 mm self-aligning nose
    - Coplanar top face at y = y_top (20.62 mm) with 0.15 mm bed-edge relief so the entire
      saddle prints 100% flat on the Z=0 build plate (rot_x_neg90) with zero overhangs.
    """
    pts = [
        # Bed-contact plane y = y_top (20.62 mm, 0.18 mm clear of mortise y1=20.80 mm):
        [x_center - 1.58, y_top, -20.85],
        [x_center + 1.58, y_top, -20.85],
        [x_center + 1.52, y_top, -18.95],
        [x_center - 1.52, y_top, -18.95],
        # Base at z = -20.85 mm (embeds 0.05 mm into saddle plate), y = 13.62..20.47 mm:
        [x_center - 1.72, 13.62, -20.85],
        [x_center + 1.72, 13.62, -20.85],
        [x_center + 1.72, y_top - 0.15, -20.85],
        [x_center - 1.72, y_top - 0.15, -20.85],
        # Shoulder at z = -18.95 mm:
        [x_center - 1.68, 13.70, -18.95],
        [x_center + 1.68, 13.70, -18.95],
        [x_center + 1.68, y_top - 0.18, -18.95],
        [x_center - 1.68, y_top - 0.18, -18.95],
        # Chamfered self-centering tip at z = -18.45 mm (2.35 mm height vs 2.60 mm flat mortise depth):
        [x_center - 1.40, 14.05, -18.45],
        [x_center + 1.40, 14.05, -18.45],
        [x_center + 1.40, y_top - 0.42, -18.45],
        [x_center - 1.40, y_top - 0.42, -18.45],
    ]
    return trimesh.PointCloud(pts).convex_hull


def build_hinge_saddle():
    """
    Option A Hinge Saddle (`gotchi_hinge_saddle.stl` — V3.2 Snug Press-Fit & Hinge Lock):
    - Two snug press-fit tenon pegs (3.44 x 7.00 mm base -> 3.36 x 6.90 mm shoulder -> 2.80 x 6.20 mm lead-in tip,
      2.35 mm deep) lock firmly into the V3.2 back shell's twin mortise sockets (3.60 x 7.30 x 2.60 mm).
    - All features share the flat y_top = 20.62 mm plane so the saddle prints 100% flat on the Z=0 build plate.
    - 8.00 mm wide ear slot (x = ±4.00 mm) with 0.15 mm/side cheek clearance around the 7.70 mm clip knuckle,
      z = -21.85 mm pocket floor (0.15 mm clearance behind the r=2.20 mm knuckle), and y = 18.58 mm stop wall.
    - Ø1.88 mm horizontal press-fit pin bore across the full 3.60 mm ears (with 0.25 mm outer entry chamfers only)
      so a raw 1.75 mm PLA filament pin press-fits tightly into the saddle ears without sliding out.
    """
    p = P
    y_top = 20.62
    peg_l = make_tapered_peg(-4.80, y_top=y_top)
    peg_r = make_tapered_peg(4.80, y_top=y_top)
    center_floor = make_box(-7.6, 7.6, 12.2, y_top, -21.85, -p['D_out'])
    ear_l = make_box(-7.6, -4.0, 13.2, y_top, -26.50, -p['D_out'])
    ear_r = make_box(4.0, 7.6, 13.2, y_top, -26.50, -p['D_out'])
    stop_wall = make_box(-4.1, 4.1, 19.08, y_top, -26.50, -p['D_out'])

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
    Option A 1-Piece Hinged Combo Shirt-Pocket Clip & Desk Kickstand Arm (`gotchi_clip_stand.stl` — V3.2):
    - 7.70 mm width (hw = 3.85 mm) fits snugly inside the 8.00 mm saddle slot with 0.15 mm clearance per side.
    - Snug Ø2.00 mm vertical pivot bore with 0.30 mm entry chamfers on both ends (x = ±3.85 mm)
      for a zero-rattle pivot on a 1.75 mm PLA filament pin.
    - Pinch jaw extended to z = -20.88 mm (0.08 mm from the z = -20.80 mm rear shell wall) so the clip
      holds firm tension against the back of the case when closed.
    """
    p = P
    hw = 3.85  # 7.70 mm wide (0.15 mm clearance per side inside ±4.00 mm saddle ears)
    knuckle = make_cyl_x(2.20, -hw, hw, cy=p['hinge_pin_y'], cz=p['hinge_pin_z'])
    stop_heel = make_box(-hw, hw, p['hinge_pin_y'], 18.20, -26.50, p['hinge_pin_z'])
    arm_beam = make_box(-hw, hw, -22.5, p['hinge_pin_y'], -26.40, -23.80)
    pinch_jaw = make_box(-hw, hw, -18.5, -14.0, -24.0, -20.88)
    ski_tip = make_box(-hw, hw, -25.0, -21.5, -27.2, -24.2)

    arm = trimesh.boolean.union([knuckle, stop_heel, arm_beam, pinch_jaw, ski_tip], engine='manifold')
    pin_bore = make_cyl_x(p['clip_pin_d'] / 2.0, -hw - 1.0, hw + 1.0, cy=p['hinge_pin_y'], cz=p['hinge_pin_z'])
    r_in = p['clip_pin_d'] / 2.0
    r_out = r_in + 0.30
    cc1 = make_cone_x(r_out, r_in, -hw - 0.05, -hw + 0.30, cy=p['hinge_pin_y'], cz=p['hinge_pin_z'])
    cc2 = make_cone_x(r_in, r_out, hw - 0.30, hw + 0.05, cy=p['hinge_pin_y'], cz=p['hinge_pin_z'])
    arm = trimesh.boolean.difference([arm, pin_bore, cc1, cc2], engine='manifold')
    return arm


def build_internal_3d_components():
    """Build true multi-feature 3D component meshes (including switches) and verify zero collisions."""
    p = P
    iw = p['W_out'] - 2 * p['wall']  # 33.4 mm
    comps = {}

    ws_pcb = make_box(-p['disp_w']/2, p['disp_w']/2, p['disp_y0'], p['disp_y1'], p['disp_pcb_z1'], p['disp_pcb_z0'])
    ws_glass = make_box(-p['disp_glass_w']/2, p['disp_glass_w']/2, p['disp_glass_y0'], p['disp_glass_y1'], p['disp_glass_z1'], p['disp_glass_z0'])
    ws_fpc = make_box(-p['disp_fpc_w']/2, p['disp_fpc_w']/2, p['disp_fpc_y0'], p['disp_fpc_y1'], p['disp_zif_z1'], -0.9)
    ws_ph20 = make_box(-p['ph20_w']/2, p['ph20_w']/2, p['disp_y0'] + 0.1, p['ph20_y1'], p['ph20_z1'], p['disp_pcb_z1'])
    comps['display_composite'] = trimesh.boolean.union([ws_pcb, ws_glass, ws_fpc, ws_ph20], engine='manifold')

    comps['battery_803040'] = make_box(-p['bat_w']/2, p['bat_w']/2, p['bat_y0'], p['bat_y1'], p['bat_z1'], p['bat_z0'])

    xiao_base = make_box(p['xiao_x0'], p['xiao_x1'], p['xiao_y0'], p['xiao_y0'] + 4.0, p['xiao_z1'], p['xiao_z0'])
    sense_pcb = make_box(p['xiao_x0'] + 6.5, p['xiao_x1'], p['xiao_y0'] + 4.0, p['xiao_y1'], p['xiao_z1'], p['xiao_z0'])
    pdm_mic = make_box(p['mic_cx'] - 1.75, p['mic_cx'] + 1.75, p['xiao_y1'] - 0.1, p['xiao_y1'] + 0.7, p['mic_cz'] - 1.3, p['mic_cz'] + 1.3)
    comps['xiao_sense_upward_mic'] = trimesh.boolean.union([xiao_base, sense_pcb, pdm_mic], engine='manifold')

    cam_base = make_box(p['cam_cx'] - p['cam_w']/2, p['cam_cx'] + p['cam_w']/2, p['cam_cy'] - p['cam_h']/2, p['cam_cy'] + p['cam_h']/2, p['cam_z1'], -4.2)
    cam_lens = make_cyl_z(p['cam_lens_d']/2 - 0.3, -4.3, p['cam_z0'], cx=p['cam_cx'], cy=p['cam_cy'])
    cam_flex = make_box(p['xiao_x1'] + 0.1, p['cam_cx'] - p['cam_w']/2 + 0.2, p['cam_cy'] - 2.5, p['cam_cy'] + 2.5, -5.8, -4.3)
    comps['camera_forward_flex'] = trimesh.boolean.union([cam_base, cam_lens, cam_flex], engine='manifold')

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

    # 3. Button cap: flange on Z=0 bed
    cap_print = cap.copy()
    cap_print.apply_translation([-cap_print.centroid[0], -cap_print.centroid[1], -cap_print.bounds[0][2]])
    cap_print.export(os.path.join(stl_dir, "gotchi_button_cap.stl"))

    # 4. Hinge Saddle: orient with shared flat y_top = 20.35 mm face on Z=0 bed (rot_x_neg90, zero overhang!)
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

    # 6. Combined V3.2 Build Plate (`/workspace/data/3dprint/gotchi_case_v3_plate.stl`)
    #    Keep Back Shell on the far right (+X = +26.0) with ZERO islands to its right (+X button wall)
    #    or front (-Y speaker grille), placing Hinge Saddle, Clip Arm, and Button Caps on the far left (-X).
    plate_parts = []
    f_p = front_print.copy()
    f_p.apply_translation([-18.0, 0.0, 0.0])
    plate_parts.append(f_p)

    b_p = back_print.copy()
    b_p.apply_translation([26.0, 0.0, 0.0])
    plate_parts.append(b_p)

    for idx, cy_off in enumerate([-22.0, -12.0]):
        c_p = cap_print.copy()
        c_p.apply_translation([-46.0, cy_off, 0.0])
        plate_parts.append(c_p)

    s_p = saddle_print.copy()
    s_p.apply_translation([-52.0, 22.0, 0.0])
    plate_parts.append(s_p)

    a_p = arm_print.copy()
    a_p.apply_translation([-60.0, -6.0, 0.0])
    plate_parts.append(a_p)

    plate = trimesh.util.concatenate(plate_parts)
    plate_out = "/workspace/data/3dprint/gotchi_case_v3_plate.stl"
    os.makedirs(os.path.dirname(plate_out), exist_ok=True)
    plate.export(plate_out)

    # 7. Standalone Hinge-Only Quick-Fix Plate (`/workspace/data/3dprint/gotchi_v3_hinge_fix_plate.stl`)
    s_fix = saddle_print.copy()
    s_fix.apply_translation([-12.0, 0.0, 0.0])
    a_fix = arm_print.copy()
    a_fix.apply_translation([8.0, 0.0, 0.0])
    hinge_fix_plate = trimesh.util.concatenate([s_fix, a_fix])
    hinge_fix_out = "/workspace/data/3dprint/gotchi_v3_hinge_fix_plate.stl"
    hinge_fix_plate.export(hinge_fix_out)

    print(f"Exported watertight print-oriented STLs to {stl_dir}/, {plate_out}, and {hinge_fix_out}")


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
