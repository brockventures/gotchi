#!/usr/bin/env python3
"""
GOTCHI V4.3 Printable Enclosure — Revision 8.4 (36.4 x 71.0 x 18.5 mm):
1. Validated Control & Speaker Cradles + Dedicated Wire-Exit Channels:
   - Right-Side Tactile Button Cradles (2x 6.0x6.0x5.0 mm switches, B07VSNN9S2):
     * Raised button bore centers to cz = -13.90 mm (3.20 mm above floor_z = -17.10 mm) so the full 6.0 mm
       vertical switch face sits cleanly on the floor inside a 6.30 (Y) x 6.45 (Z) x 3.70 (X) mm pocket.
     * Replaced the solid rear cradle wall with a 2.10 mm center back-stop post (by ± 1.05 mm) flanked by
       two 2.10 x 6.50 mm open rear wire/pin exit slots (by ± (1.05..3.15 mm)) so all 4 corner solder pins,
       30 AWG hookup wires, and 220 kOhm sense resistors route unimpeded to the XIAO headers.
   - Upper-Left Mini SPDT Slide Switch Cradle (8.5x3.5x4.0 mm 3-pin switch, B0FNK8B1YV at y = +15.5 mm):
     * Expanded pocket length from 4.20 mm to 8.90 mm (Y) x 3.85 mm (X) x 4.50 mm (Z).
     * Oriented exterior actuator slot horizontally along Y (4.6 mm Y x 2.4 mm Z at cz = -14.85 mm) for full
       2.0 mm slider throw while keeping the switch body captured.
     * Built cradle as two L-shaped end brackets with a 6.20 mm wide open rear window (y = +12.40..+18.60 mm)
       so all 3 rear solder pins + heat-shrinked BAT+ wires exit straight inward without interference.
   - Front-Chin 1510 Speaker Cradle (15.0x10.0x3.5 mm cavity speaker, B0D7S8FFKY at y = -31.70 mm):
     * Expanded pocket from 15.2 x 8.45 mm to 15.40 (X) x 10.30 (Y) mm (y = -36.85..-26.55 mm, 1.05 mm clear
       below the display PCB at y = -25.50 mm).
     * Split cradle perimeter into L-corner brackets with 3.80 mm wide full-depth wire-exit channels on the
       left (-X), right (+X), and top (+Y) sides so twisted-pair leads route cleanly around the battery to the
       MAX98357A amp without pinching.
2. Preserved V4.2 Bench Calibrations:
   - Top-wall curved stadium USB-C port at z = -14.25 mm (9.3 x 3.7 mm) matching top-mounted XIAO receptacle.
   - 25.00 mm XIAO + Sense Y-well (y = +6.10..+31.10 mm) with positive rear L-corner Y-stops (y = +4.95..+6.05 mm).
   - 4 tapered display corner locator pins (x = ±14.0 mm, y = -23.0 & +20.0 mm), front camera cradle, and
     uniform 1.40 mm front wall.
"""

import argparse
import json
import math
import os
import shutil
import subprocess
import sys
import time
import urllib.request
import numpy as np
import trimesh
from PIL import Image, ImageDraw
from trimesh.creation import box, cylinder

sys.path.insert(0, "/workspace")
sys.path.insert(0, "/workspace/tools")
sys.path.insert(0, "/workspace/gotchi/cad")

P = dict(
    W_out=36.4,
    H_out=71.0,
    D_out=18.5,
    y_min=-38.4,
    y_max=32.6,
    wall=1.5,
    front_wall=1.4,
    back_wall=1.4,
    split_z=-8.0,

    # 1. Waveshare 1.54" E-Paper Module V2 (33.0 x 48.0 mm PCB, y = -25.5 to +22.5 mm, PH2.0 shroud clipped)
    disp_w=33.0,
    disp_h=48.0,
    disp_cy=-1.5,
    disp_y0=-25.5,
    disp_y1=22.5,
    disp_glass_w=31.8,
    disp_glass_h=42.3,
    disp_glass_y0=-21.0,
    disp_glass_y1=21.3,
    disp_glass_z0=-1.45,
    disp_glass_z1=-2.5,
    disp_pcb_z0=-2.5,
    disp_pcb_z1=-4.1,
    disp_smd_z1=-5.4,
    # 4 corner M2 mounting hole centers on the 33.0 x 48.0 mm Waveshare PCB (28.0 x 43.0 mm hole spacing)
    disp_pin_x=14.0,
    disp_pin_y_bot=-23.0,
    disp_pin_y_top=20.0,
    win_w=28.0,
    win_h=28.0,
    win_cy=3.0,
    disp_fpc_w=16.5,
    disp_fpc_y0=-25.5,
    disp_fpc_y1=-20.5,
    disp_zif_z1=-5.4,
    ph20_w=18.5,
    ph20_y0=16.6,
    ph20_y1=22.4,
    ph20_z1=-4.9,

    # 2. True LP803040 LiPo Battery (30.0 x 41.0 x 7.9 mm) at y = -35.9..+5.1 mm
    bat_w=30.0,
    bat_h=41.0,
    bat_d=7.9,
    bat_cy=-15.4,
    bat_y0=-35.9,
    bat_y1=5.1,
    bat_z0=-5.5,
    bat_z1=-13.4,

    # 3. Option 1A Flat Under-Tucked XIAO + Sense (24.85 mm installed bay: y = +6.25..+31.10 mm):
    xiao_x0=-8.9,
    xiao_x1=8.9,
    xiao_y0=6.25,
    xiao_y_shield0=11.5,
    xiao_y1=31.1,
    xiao_z_back=-16.8,
    xiao_z_zif_low=-13.6,
    xiao_z_zif=-8.8,
    # Forward-facing PDM MEMS microphone port in top crown (shifted to x = -7.2 mm to clear left camera bracket)
    mic_cx=-7.2,
    mic_cy=25.2,
    mic_d=2.0,
    # Top-wall Curved Stadium USB-C Port (+Y wall at x = 0.0, z = -14.25 mm: 2.85 mm above -17.1 mm floor for top-mounted XIAO port)
    usb_cx=0.0,
    usb_cz=-14.25,
    usb_w=9.3,
    usb_h=3.7,

    # 4. Forward-firing Camera (OV2640, 8.5 x 8.5 mm square body held by front-shell sidewall cradle)
    cam_w=8.5,
    cam_h=8.5,
    cam_cx=0.0,
    cam_cy=26.78,
    cam_lens_d=7.6,
    cam_z0=-0.1,
    cam_z_shoulder=-1.45,
    cam_z1=-16.8,

    # 5. Rear Slim Audio Amp Layer (underneath battery on back floor)
    amp_w=19.0,
    amp_h=17.8,
    amp_d=3.0,
    amp_cx=-4.5,
    amp_cy=-15.5,
    amp_z0=-13.8,
    amp_z1=-16.8,

    # 6. Front-Chin Direct-Firing 1510 Cavity Speaker (15.0 x 10.0 x 3.5 mm, y = -36.70..-26.70 mm)
    spk_w=15.0,
    spk_h=10.0,
    spk_d=3.5,
    spk_cx=0.0,
    spk_cy=-31.7,
    spk_z0=-1.45,
    spk_z1=-4.95,

    # 7. Controls (all in upper XIAO zone y = +6.5..+25.5 mm, 100% clear of the 30.0 mm wide battery):
    #    6.0 x 6.0 x 5.0 mm tactile buttons (3.5 mm body + 1.5 mm plunger) centered at cz = -13.90 mm
    #    (3.20 mm above floor_z = -17.10 mm so the 6.0 mm vertical body clears the floor with 0.20 mm margin)
    ptt_cy=20.5,
    ptt_cz=-13.9,
    snap_cy=10.5,
    snap_cz=-13.9,
    btn_hole_d=3.9,
    # Mini SPDT Slide Switch (8.5 x 3.5 x 4.0 mm body, B0FNK8B1YV):
    # Upper-left side wall (-X wall at y = +15.5 mm beside XIAO, horizontal 4.6 x 2.4 mm actuator slot)
    sw_cy=15.5,
    sw_cz=-14.85,
    sw_slot_y=4.6,
    sw_slot_z=2.4,

    # 8. 360° Press-Fit / Snap-Bead Seam:
    rabbet_lip_w=0.75,
    rabbet_lip_h=1.5,
    rabbet_clearance=0.05,

    # 9. Rear Twin-Mortise Hinge Saddle Anchor (y = -1.6..+5.7 mm, z = -17.1..-15.3 mm):
    mortise_x_in=3.0,
    mortise_x_out=6.6,
    mortise_y0=-1.6,
    mortise_y1=5.7,
    mortise_z_flat=-16.6,
    mortise_z_apex=-15.8,
    hinge_pin_y=1.1,
    hinge_pin_z=-22.1,
    saddle_pin_d=2.05,
    clip_pin_d=2.20,
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


def make_cone_z(r0, r1, z0, z1, cx=0.0, cy=0.0, sections=48):
    pts = []
    angles = np.linspace(0, 2 * math.pi, sections, endpoint=False)
    for z_val, rad in [(z0, r0), (z1, r1)]:
        for a in angles:
            pts.append([cx + rad * math.cos(a), cy + rad * math.sin(a), z_val])
    return trimesh.PointCloud(pts).convex_hull


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


def make_usb_c_stadium_cutter(cx, cz, w, h, y_in, y_wall_out, sections=48):
    r = h / 2.0
    dx = max(0.1, (w / 2.0) - r)
    angles = np.linspace(0, 2 * math.pi, sections, endpoint=False)

    pts_thru = []
    for y_val in (y_in, y_wall_out + 1.0):
        for sx in (-dx, dx):
            for a in angles:
                pts_thru.append([cx + sx + r * math.cos(a), y_val, cz + r * math.sin(a)])
    thru_hull = trimesh.PointCloud(pts_thru).convex_hull

    pts_bevel = []
    r_out = r + 0.55
    dx_out = dx + 0.45
    y_bevel_start = y_wall_out - 0.65
    for sx_i, sx_o in [(-dx, -dx_out), (dx, dx_out)]:
        for a in angles:
            pts_bevel.append([cx + sx_i + r * math.cos(a), y_bevel_start, cz + r * math.sin(a)])
            pts_bevel.append([cx + sx_o + r_out * math.cos(a), y_wall_out + 0.05, cz + r_out * math.sin(a)])
            pts_bevel.append([cx + sx_o + r_out * math.cos(a), y_wall_out + 1.0, cz + r_out * math.sin(a)])
    bevel_hull = trimesh.PointCloud(pts_bevel).convex_hull
    return trimesh.boolean.union([thru_hull, bevel_hull], engine='manifold')


def make_button_bore_x(r, x0, x1, cy=0.0, cz=0.0, sections=48):
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


def make_mortise_cutter(x0, x1, y0, y1, z_bottom, z_flat, z_apex, z_bed=-18.5, entrance_chamfer=0.22):
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
    cavity = make_rounded_shell_block(
        iw,
        p['y_min'] + p['wall'], p['y_max'] - p['wall'],
        p['split_z'] - 0.5, -p['front_wall'],
        r_xy=1.30, chamfer_z=0.0, chamfer_top=False, chamfer_bot=False
    )

    part = trimesh.boolean.difference([outer, cavity], engine='manifold')

    # Internal self-retaining sub-assembly features on inside of front shell (`z = -1.40 mm` ceiling):
    front_adds = []

    # 1. Camera Sidewall Cradle Brackets (`x = ±(4.35..5.45 mm), y = 22.8..31.1 mm, z = -4.4..-1.35 mm`)
    front_adds.append(make_box(-5.45, -4.35, 22.8, 31.15, -4.4, -1.30))
    front_adds.append(make_box(4.35, 5.45, 22.8, 31.15, -4.4, -1.30))
    front_adds.append(make_box(-5.45, -3.10, 21.6, 22.42, -2.45, -1.30))
    front_adds.append(make_box(3.10, 5.45, 21.6, 22.42, -2.45, -1.30))

    # 2. Four Display Corner Locator Pins + Standoff Shoulders (`x = ±14.0 mm, y = -23.0 & +20.0 mm`)
    for px in (-p['disp_pin_x'], p['disp_pin_x']):
        for py in (p['disp_pin_y_bot'], p['disp_pin_y_top']):
            front_adds.append(make_cyl_z(1.65, -2.48, -1.30, cx=px, cy=py, sections=36))
            front_adds.append(make_cone_z(0.70, 0.90, -4.60, -2.45, cx=px, cy=py, sections=36))

    # 3. Dedicated Front-Chin 1510 Speaker Cradle (`15.40 x 10.30 mm` pocket at `x = ±7.70 mm, y = -36.85..-26.55 mm`)
    #    Built as 4 L-shaped corner brackets with 3.80 mm wide open wire-exit channels on Left (-X), Right (+X),
    #    and Top (+Y) sides so twisted-pair speaker leads exit cleanly without pinching against the battery!
    #    - Bottom-left & top-left sidewall segments (leaving 3.80 mm open wire slot at y = -33.60..-29.80 mm):
    front_adds.append(make_box(-8.80, -7.70, -36.95, -33.60, -4.6, -1.30))
    front_adds.append(make_box(-8.80, -7.70, -29.80, -25.60, -4.6, -1.30))
    #    - Bottom-right & top-right sidewall segments (leaving 3.80 mm open wire slot at y = -33.60..-29.80 mm):
    front_adds.append(make_box(7.70, 8.80, -36.95, -33.60, -4.6, -1.30))
    front_adds.append(make_box(7.70, 8.80, -29.80, -25.60, -4.6, -1.30))
    #    - Top retention tabs at y = -26.55..-25.60 mm (leaving 5.00 mm center/left wire exit channel at x = -2.50..+2.50 mm):
    front_adds.append(make_box(-8.80, -2.50, -26.55, -25.60, -4.6, -1.30))
    front_adds.append(make_box(2.50, 8.80, -26.55, -25.60, -4.6, -1.30))

    part = trimesh.boolean.union([part] + front_adds, engine='manifold')

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
        make_box(-rx - 0.16, -rx + 0.2, -18.0, 13.0, snap_z0, snap_z1),
        make_box(rx - 0.2, rx + 0.16, -18.0, 13.0, snap_z0, snap_z1),
        make_box(-9.0, 9.0, rabbet_y0 - 0.16, rabbet_y0 + 0.2, snap_z0, snap_z1),
        make_box(-9.0, 9.0, rabbet_y1 - 0.2, rabbet_y1 + 0.16, snap_z0, snap_z1),
    ]

    wy0 = p['win_cy'] - p['win_h'] / 2.0
    wy1 = p['win_cy'] + p['win_h'] / 2.0
    win_cut = make_box(-p['win_w'] / 2.0, p['win_w'] / 2.0, wy0, wy1, -3.0, 1.0)

    cam_cut = make_cyl_z(p['cam_lens_d'] / 2.0, -3.0, 1.0, cx=p['cam_cx'], cy=p['cam_cy'])
    mic_cut = make_cyl_z(p['mic_d'] / 2.0, -3.0, 1.0, cx=p['mic_cx'], cy=p['mic_cy'])

    grille_cuts = []
    for ix in (-2, -1, 0, 1, 2):
        gx = p['spk_cx'] + ix * 2.6
        slot_box = make_box(gx - 0.65, gx + 0.65, p['spk_cy'] - 1.6, p['spk_cy'] + 1.6, -3.0, 1.0)
        cap_top = make_cyl_z(0.65, -3.0, 1.0, cx=gx, cy=p['spk_cy'] + 1.6, sections=24)
        cap_bot = make_cyl_z(0.65, -3.0, 1.0, cx=gx, cy=p['spk_cy'] - 1.6, sections=24)
        grille_cuts.extend([slot_box, cap_top, cap_bot])

    part = trimesh.boolean.difference(
        [part, rabbet_cut, win_cut, cam_cut, mic_cut] + snap_cuts + grille_cuts,
        engine='manifold'
    )
    return part


def build_back_shell():
    p = P
    outer = make_rounded_shell_block(
        p['W_out'], p['y_min'], p['y_max'], -p['D_out'], p['split_z'],
        r_xy=2.8, chamfer_z=0.8, chamfer_top=False, chamfer_bot=True
    )
    iw = p['W_out'] - 2 * p['wall']  # 33.4 mm
    floor_z = -p['D_out'] + p['back_wall']  # -17.1 mm

    cavity = make_rounded_shell_block(
        iw,
        p['y_min'] + p['wall'], p['y_max'] - p['wall'],
        floor_z, p['split_z'] + 0.5,
        r_xy=1.30, chamfer_z=0.0, chamfer_top=False, chamfer_bot=False
    )

    part = trimesh.boolean.difference([outer, cavity], engine='manifold')

    adds = []
    cutters = []

    # 1. Concentric Press-Fit Tongue Lip (r_xy=1.30 inner matches r_xy=2.00 outer so corners never pinch!)
    tongue_out_w = iw + 2 * (p['rabbet_lip_w'] - p['rabbet_clearance'])  # 34.80 mm
    tongue_out_y0 = p['y_min'] + p['wall'] - (p['rabbet_lip_w'] - p['rabbet_clearance'])
    tongue_out_y1 = p['y_max'] - p['wall'] + (p['rabbet_lip_w'] - p['rabbet_clearance'])

    tongue_outer = make_rounded_shell_block(
        tongue_out_w, tongue_out_y0, tongue_out_y1,
        p['split_z'] - 0.3, p['split_z'] + p['rabbet_lip_h'],
        r_xy=2.0, chamfer_z=0.22, chamfer_top=True, chamfer_bot=False
    )
    tongue_inner = make_rounded_shell_block(
        iw, p['y_min'] + p['wall'], p['y_max'] - p['wall'],
        p['split_z'] - 0.6, p['split_z'] + p['rabbet_lip_h'] + 0.5,
        r_xy=1.30, chamfer_z=0.0, chamfer_top=False, chamfer_bot=False
    )
    tongue_ring = trimesh.boolean.difference([tongue_outer, tongue_inner], engine='manifold')
    adds.append(tongue_ring)

    tx = tongue_out_w / 2.0
    snap_z0 = p['split_z'] + 0.65
    snap_z1 = p['split_z'] + 1.15
    adds.extend([
        make_box(-tx - 0.12, -tx + 0.2, -16.0, 11.0, snap_z0, snap_z1),
        make_box(tx - 0.2, tx + 0.12, -16.0, 11.0, snap_z0, snap_z1),
        make_box(-8.0, 8.0, tongue_out_y0 - 0.12, tongue_out_y0 + 0.2, snap_z0, snap_z1),
        make_box(-8.0, 8.0, tongue_out_y1 - 0.2, tongue_out_y1 + 0.12, snap_z0, snap_z1),
    ])

    # 2. XIAO Side Guide Rails (y = +6.10..+30.20 mm) + Positive Rear Y-Stop Bumpers (y = +4.95..+6.10 mm)
    adds.append(make_box(-10.25, -9.15, 6.10, 30.2, floor_z, floor_z + 1.8))
    adds.append(make_box(9.15, 10.25, 6.10, 30.2, floor_z, floor_z + 1.8))
    adds.append(make_box(-10.25, -5.80, 4.95, 6.10, floor_z, floor_z + 2.2))
    adds.append(make_box(5.80, 10.25, 4.95, 6.10, floor_z, floor_z + 2.2))

    # 3. Validated Right-Side 6x6x5mm Tactile Button Cradles with Open Rear Wire & Pin Channels
    #    - Each pocket is 6.30 mm wide in Y (by ± 3.15 mm), 6.45 mm tall in Z (floor_z = -17.10 to -10.65 mm,
    #      open at top for vertical drop-in), and 3.70 mm deep in X (x = +13.00..+16.70 mm).
    #    - Center back-stop post (by ± 1.05 mm, x = +11.90..+13.00 mm) braces the switch body while leaving
    #      two 2.10 mm wide open rear wire/pin slots (by ± (1.05..3.15 mm)) for the 4 corner solder legs!
    z_btn_top = -10.65
    for by, bz in [(p['ptt_cy'], p['ptt_cz']), (p['snap_cy'], p['snap_cz'])]:
        # Side guide walls (1.15 mm thick in Y, x = +11.90..+16.75 mm)
        adds.append(make_box(iw / 2.0 - 4.80, iw / 2.0 + 0.05, by - 4.30, by - 3.15, floor_z, z_btn_top))
        adds.append(make_box(iw / 2.0 - 4.80, iw / 2.0 + 0.05, by + 3.15, by + 4.30, floor_z, z_btn_top))
        # Center rear back-stop post (2.10 mm wide in Y, leaves 2.10 mm open pin/wire slots at top & bottom corners!)
        adds.append(make_box(iw / 2.0 - 4.80, iw / 2.0 - 3.70, by - 1.05, by + 1.05, floor_z, z_btn_top))
        # Sidewall plunger hole (Ø 3.90 mm with self-supporting 45° top crown)
        cutters.append(make_button_bore_x(p['btn_hole_d'] / 2.0, iw / 2.0 - 0.5, p['W_out'] / 2.0 + 1.0, cy=by, cz=bz))

    # 4. Validated Upper-Left Mini SPDT Slide Switch Cradle (-X wall at y = +15.5 mm, 8.90 x 3.85 x 4.50 mm pocket)
    #    - Built as two L-shaped end brackets at y = sw_cy ± (3.10..5.55 mm), leaving a 6.20 mm wide open rear
    #      window (y = +12.40..+18.60 mm) so all 3 rear solder pins + wires exit straight inward (+X)!
    z_sw_top = -12.60
    # Bottom L-bracket (y = +9.95..+11.05 mm end wall + y = +9.95..+12.40 mm rear corner stop)
    adds.append(make_box(-iw / 2.0 - 0.05, -iw / 2.0 + 4.95, p['sw_cy'] - 5.55, p['sw_cy'] - 4.45, floor_z, z_sw_top))
    adds.append(make_box(-iw / 2.0 + 3.85, -iw / 2.0 + 4.95, p['sw_cy'] - 5.55, p['sw_cy'] - 3.10, floor_z, z_sw_top))
    # Top L-bracket (y = +19.95..+21.05 mm end wall + y = +18.60..+21.05 mm rear corner stop)
    adds.append(make_box(-iw / 2.0 - 0.05, -iw / 2.0 + 4.95, p['sw_cy'] + 4.45, p['sw_cy'] + 5.55, floor_z, z_sw_top))
    adds.append(make_box(-iw / 2.0 + 3.85, -iw / 2.0 + 4.95, p['sw_cy'] + 3.10, p['sw_cy'] + 5.55, floor_z, z_sw_top))
    # Horizontal actuator slot through -X wall (4.60 mm along Y x 2.40 mm along Z)
    cutters.append(make_box(
        -p['W_out'] / 2.0 - 1.0, -iw / 2.0 + 0.5,
        p['sw_cy'] - p['sw_slot_y'] / 2.0, p['sw_cy'] + p['sw_slot_y'] / 2.0,
        p['sw_cz'] - p['sw_slot_z'] / 2.0, p['sw_cz'] + p['sw_slot_z'] / 2.0
    ))

    # 5. Curved Stadium USB-C Opening (+Y top wall at x = 0.0, z = -14.25 mm for top-mounted XIAO receptacle)
    cutters.append(make_usb_c_stadium_cutter(
        cx=p['usb_cx'], cz=p['usb_cz'],
        w=p['usb_w'], h=p['usb_h'],
        y_in=p['y_max'] - p['wall'] - 0.8,
        y_wall_out=p['y_max']
    ))

    # 6. Shifted 1.8 mm Internal Hinge Anchor Boss (y = -2.2..+6.0 mm, z = -17.1..-15.3 mm)
    anchor_boss = make_box(-8.2, 8.2, -2.2, 6.0, floor_z - 0.3, -15.3)
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


def make_tapered_peg(x_center, y_top=5.52):
    y0_base = P['mortise_y0'] + 0.20  # -1.40 mm
    y_bed = y_top                     # 5.52 mm
    y_ch = y_top - 0.35
    z_base = -P['D_out'] - 0.05       # -18.55 mm
    z_sh = -P['D_out'] + 1.50         # -17.00 mm
    z_tip = -P['D_out'] + 1.90        # -16.60 mm
    pts = [
        [x_center - 1.44, y_bed, z_base],
        [x_center + 1.44, y_bed, z_base],
        [x_center + 1.40, y_bed, z_sh],
        [x_center - 1.40, y_bed, z_sh],
        [x_center - 1.68, y0_base, z_base],
        [x_center + 1.68, y0_base, z_base],
        [x_center + 1.68, y_ch, z_base],
        [x_center - 1.68, y_ch, z_base],
        [x_center - 1.62, y0_base + 0.08, z_sh],
        [x_center + 1.62, y0_base + 0.08, z_sh],
        [x_center + 1.62, y_ch, z_sh],
        [x_center - 1.62, y_ch, z_sh],
        [x_center - 1.35, y0_base + 0.45, z_tip],
        [x_center + 1.35, y0_base + 0.45, z_tip],
        [x_center + 1.35, y_ch - 0.30, z_tip],
        [x_center - 1.35, y_ch - 0.30, z_tip],
    ]
    return trimesh.PointCloud(pts).convex_hull


def build_hinge_saddle():
    p = P
    y_top = p['mortise_y1'] - 0.18  # 5.52 mm
    z_back = -p['D_out']            # -18.50 mm
    peg_l = make_tapered_peg(-4.80, y_top=y_top)
    peg_r = make_tapered_peg(4.80, y_top=y_top)
    center_floor = make_box(-7.6, 7.6, -2.9, y_top, z_back - 0.95, z_back)
    ear_l = make_box(-7.6, -4.0, -1.9, y_top, z_back - 5.80, z_back)
    ear_r = make_box(4.0, 7.6, -1.9, y_top, z_back - 5.80, z_back)
    stop_wall = make_box(-4.1, 4.1, 4.05, y_top, z_back - 5.80, z_back)

    saddle = trimesh.boolean.union([peg_l, peg_r, center_floor, ear_l, ear_r, stop_wall], engine='manifold')
    pin_bore = make_cyl_x(p['saddle_pin_d'] / 2.0, -8.5, 8.5, cy=p['hinge_pin_y'], cz=p['hinge_pin_z'])
    r_in = p['saddle_pin_d'] / 2.0
    r_out = r_in + 0.30
    cs1 = make_cone_x(r_out, r_in, -7.65, -7.30, cy=p['hinge_pin_y'], cz=p['hinge_pin_z'])
    cs4 = make_cone_x(r_in, r_out, 7.30, 7.65, cy=p['hinge_pin_y'], cz=p['hinge_pin_z'])
    saddle = trimesh.boolean.difference([saddle, pin_bore, cs1, cs4], engine='manifold')
    return saddle


def build_clip_stand_arm():
    p = P
    hw = 3.70
    z_back = -p['D_out']  # -18.50 mm
    knuckle = make_cyl_x(2.15, -hw, hw, cy=p['hinge_pin_y'], cz=p['hinge_pin_z'])
    stop_heel = make_box(-hw, hw, p['hinge_pin_y'], p['hinge_pin_y'] + 1.95, z_back - 5.70, p['hinge_pin_z'])
    arm_beam = make_box(-hw, hw, -33.5, p['hinge_pin_y'], z_back - 5.65, z_back - 3.05)
    pinch_jaw = make_box(-hw, hw, -30.0, -24.0, z_back - 3.25, z_back - 0.12)
    ski_tip = make_box(-hw, hw, -36.5, -32.5, z_back - 6.45, z_back - 3.45)

    arm = trimesh.boolean.union([knuckle, stop_heel, arm_beam, pinch_jaw, ski_tip], engine='manifold')
    pin_bore = make_cyl_x(p['clip_pin_d'] / 2.0, -hw - 1.0, hw + 1.0, cy=p['hinge_pin_y'], cz=p['hinge_pin_z'])
    r_in = p['clip_pin_d'] / 2.0
    r_out = r_in + 0.38
    cc1 = make_cone_x(r_out, r_in, -hw - 0.05, -hw + 0.38, cy=p['hinge_pin_y'], cz=p['hinge_pin_z'])
    cc2 = make_cone_x(r_in, r_out, hw - 0.38, hw + 0.05, cy=p['hinge_pin_y'], cz=p['hinge_pin_z'])
    arm = trimesh.boolean.difference([arm, pin_bore, cc1, cc2], engine='manifold')
    return arm


def build_internal_3d_components():
    p = P
    iw = p['W_out'] - 2 * p['wall']  # 33.4 mm
    comps = {}

    ws_pcb = make_box(-p['disp_w']/2, p['disp_w']/2, p['disp_y0'], p['disp_y1'], p['disp_pcb_z1'], p['disp_pcb_z0'])
    ws_glass = make_box(-p['disp_glass_w']/2, p['disp_glass_w']/2, p['disp_glass_y0'], p['disp_glass_y1'], p['disp_glass_z1'], p['disp_glass_z0'])
    hole_cuts_pcb = []
    hole_cuts_glass = []
    for px in (-p['disp_pin_x'], p['disp_pin_x']):
        for py in (p['disp_pin_y_bot'], p['disp_pin_y_top']):
            hole_cuts_pcb.append(make_cyl_z(1.02, -5.0, -1.0, cx=px, cy=py, sections=36))
            hole_cuts_glass.append(make_cyl_z(1.85, -3.0, -1.0, cx=px, cy=py, sections=36))
    ws_pcb = trimesh.boolean.difference([ws_pcb] + hole_cuts_pcb, engine='manifold')
    ws_glass = trimesh.boolean.difference([ws_glass] + hole_cuts_glass, engine='manifold')

    ws_fpc = make_box(-p['disp_fpc_w']/2, p['disp_fpc_w']/2, p['disp_fpc_y0'], p['disp_fpc_y1'], p['disp_zif_z1'], p['disp_glass_z0'])
    ws_pads = make_box(-p['ph20_w']/2, p['ph20_w']/2, p['ph20_y0'], p['disp_y1'] - 0.1, p['ph20_z1'], p['disp_pcb_z1'])
    comps['display_composite'] = trimesh.boolean.union([ws_pcb, ws_glass, ws_fpc, ws_pads], engine='manifold')

    assert abs((p['bat_y1'] - p['bat_y0']) - p['bat_h']) < 1e-6, "Battery Y bounds must match bat_h!"
    comps['battery_pack'] = make_box(-p['bat_w']/2, p['bat_w']/2, p['bat_y0'], p['bat_y1'], p['bat_z1'], p['bat_z0'])

    xiao_zif_tail = make_box(p['xiao_x0'], p['xiao_x1'], p['xiao_y0'], p['xiao_y_shield0'], p['xiao_z_back'], p['xiao_z_zif_low'])
    xiao_lower = make_box(p['xiao_x0'], p['xiao_x1'], p['xiao_y_shield0'] - 0.1, 22.55, p['xiao_z_back'], p['xiao_z_zif'])
    xiao_upper_pcb = make_box(p['xiao_x0'], p['xiao_x1'], 22.50, p['xiao_y1'], p['xiao_z_back'], p['xiao_z_zif'])
    cam_tower = make_box(
        p['cam_cx'] - p['cam_w']/2, p['cam_cx'] + p['cam_w']/2,
        p['cam_cy'] - p['cam_h']/2, p['cam_cy'] + p['cam_h']/2,
        p['xiao_z_zif'] - 0.2, p['cam_z_shoulder']
    )
    cam_lens = make_cyl_z(p['cam_lens_d']/2 - 0.3, p['cam_z_shoulder'] - 0.2, p['cam_z0'], cx=p['cam_cx'], cy=p['cam_cy'])
    comps['xiao_sense_camera_1a'] = trimesh.boolean.union([xiao_zif_tail, xiao_lower, xiao_upper_pcb, cam_tower, cam_lens], engine='manifold')

    comps['speaker_1510'] = make_box(
        p['spk_cx'] - p['spk_w']/2, p['spk_cx'] + p['spk_w']/2,
        p['spk_cy'] - p['spk_h']/2, p['spk_cy'] + p['spk_h']/2,
        p['spk_z1'], p['spk_z0']
    )
    comps['amp_max98357a'] = make_box(
        p['amp_cx'] - p['amp_w']/2, p['amp_cx'] + p['amp_w']/2,
        p['amp_cy'] - p['amp_h']/2, p['amp_cy'] + p['amp_h']/2,
        p['amp_z1'], p['amp_z0']
    )

    # True 6.0 x 6.0 x 5.0 mm tactile buttons (3.5 mm body + 1.5 mm Ø3.4 mm stem + rear corner pins)
    ptt_body = make_box(iw / 2.0 - 3.6, iw / 2.0 - 0.1, p['ptt_cy'] - 3.0, p['ptt_cy'] + 3.0, p['ptt_cz'] - 3.0, p['ptt_cz'] + 3.0)
    ptt_stem = make_cyl_x(1.65, iw / 2.0 - 0.2, iw / 2.0 + 1.4, cy=p['ptt_cy'], cz=p['ptt_cz'])
    comps['btn_top_tactile'] = trimesh.boolean.union([ptt_body, ptt_stem], engine='manifold')

    snap_body = make_box(iw / 2.0 - 3.6, iw / 2.0 - 0.1, p['snap_cy'] - 3.0, p['snap_cy'] + 3.0, p['snap_cz'] - 3.0, p['snap_cz'] + 3.0)
    snap_stem = make_cyl_x(1.65, iw / 2.0 - 0.2, iw / 2.0 + 1.4, cy=p['snap_cy'], cz=p['snap_cz'])
    comps['btn_bot_tactile'] = trimesh.boolean.union([snap_body, snap_stem], engine='manifold')

    # True 8.5 x 3.5 x 4.0 mm Mini SPDT 3-Pin Slide Switch (with 3 rear pins through the 6.20 mm open window)
    sw_body = make_box(-iw / 2.0 + 0.1, -iw / 2.0 + 3.6, p['sw_cy'] - 4.25, p['sw_cy'] + 4.25, p['sw_cz'] - 2.0, p['sw_cz'] + 2.0)
    sw_knob = make_box(-iw / 2.0 - 1.3, -iw / 2.0 + 0.2, p['sw_cy'] - 0.8, p['sw_cy'] + 0.8, p['sw_cz'] - 0.8, p['sw_cz'] + 0.8)
    comps['spdt_slide_switch'] = trimesh.boolean.union([sw_body, sw_knob], engine='manifold')

    return comps


def export_stls(out_dir, front, back, cap, saddle, clip_stand):
    stl_dir = os.path.join(out_dir, "stl")
    os.makedirs(stl_dir, exist_ok=True)
    os.makedirs("/workspace/data/3dprint", exist_ok=True)

    front_print = front.copy()
    rot_x180 = trimesh.transformations.rotation_matrix(math.pi, [1, 0, 0])
    front_print.apply_transform(rot_x180)
    front_print.apply_translation([-front_print.centroid[0], -front_print.centroid[1], -front_print.bounds[0][2]])
    front_print.export(os.path.join(stl_dir, "gotchi_front.stl"))
    front_print.export("/workspace/data/3dprint/gotchi_front_v4_3.stl")

    back_print = back.copy()
    back_print.apply_translation([-back_print.centroid[0], -back_print.centroid[1], -back_print.bounds[0][2]])
    back_print.export(os.path.join(stl_dir, "gotchi_back.stl"))
    back_print.export("/workspace/data/3dprint/gotchi_back_v4_3.stl")

    cap_print = cap.copy()
    cap_print.apply_translation([-cap_print.centroid[0], -cap_print.centroid[1], -cap_print.bounds[0][2]])
    cap_print.export(os.path.join(stl_dir, "gotchi_button_cap.stl"))

    saddle_print = saddle.copy()
    rot_x_neg90 = trimesh.transformations.rotation_matrix(-math.pi / 2.0, [1, 0, 0])
    saddle_print.apply_transform(rot_x_neg90)
    saddle_print.apply_translation([-saddle_print.centroid[0], -saddle_print.centroid[1], -saddle_print.bounds[0][2]])
    saddle_print.export(os.path.join(stl_dir, "gotchi_hinge_saddle.stl"))
    saddle_print.export("/workspace/data/3dprint/gotchi_saddle_v4_3.stl")

    arm_print = clip_stand.copy()
    rot_y90 = trimesh.transformations.rotation_matrix(math.pi / 2.0, [0, 1, 0])
    arm_print.apply_transform(rot_y90)
    arm_print.apply_translation([-arm_print.centroid[0], -arm_print.centroid[1], -arm_print.bounds[0][2]])
    arm_print.export(os.path.join(stl_dir, "gotchi_clip_stand.stl"))
    arm_print.export("/workspace/data/3dprint/gotchi_clip_v4_3.stl")

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
    plate_out_v4_3 = "/workspace/data/3dprint/gotchi_case_v4_3_plate.stl"
    plate.export(plate_out_v4)
    plate.export(plate_out_v4_3)

    print(f"Exported watertight print-oriented V4.3 STLs to {stl_dir}/ and {plate_out_v4_3}")


def render_v4_3_preview(out_dir, front, back, saddle, clip_stand, comps):
    import render_labeled as rl

    renders_dir = os.path.join(out_dir, "renders")
    os.makedirs(renders_dir, exist_ok=True)
    out_path = os.path.join(renders_dir, "v4_3_build_preview.png")

    stl_dir = os.path.join(out_dir, "stl")
    f_p = trimesh.load(os.path.join(stl_dir, "gotchi_front.stl"))
    b_p = trimesh.load(os.path.join(stl_dir, "gotchi_back.stl"))
    s_p = trimesh.load(os.path.join(stl_dir, "gotchi_hinge_saddle.stl"))
    a_p = trimesh.load(os.path.join(stl_dir, "gotchi_clip_stand.stl"))

    scene_front_interior = [
        (f_p, (0.85, 0.89, 0.94)),
    ]

    scene_back_interior = [
        (back, (0.28, 0.34, 0.43)),
        (comps["xiao_sense_camera_1a"], (0.18, 0.75, 0.48)),
        (comps["battery_pack"], (0.92, 0.64, 0.16)),
        (comps["spdt_slide_switch"], (0.94, 0.32, 0.32)),
        (comps["btn_top_tactile"], (0.35, 0.68, 0.95)),
        (comps["btn_bot_tactile"], (0.35, 0.68, 0.95)),
    ]

    f_plate = f_p.copy().apply_translation([-16.0, 0.0, 0.0])
    b_plate = b_p.copy().apply_translation([26.0, 0.0, 0.0])
    s_plate = s_p.copy().apply_translation([-48.0, 18.0, 0.0])
    a_plate = a_p.copy().apply_translation([-48.0, -10.0, 0.0])
    bed_pad = make_box(-64.0, 52.0, -38.0, 38.0, -0.8, -0.05)

    scene_plate = [
        (bed_pad, (0.16, 0.19, 0.24)),
        (f_plate, (0.85, 0.89, 0.94)),
        (b_plate, (0.28, 0.34, 0.43)),
        (s_plate, (0.22, 0.62, 0.92)),
        (a_plate, (0.28, 0.78, 0.52)),
    ]

    im1 = rl.rasterize_scene_zbuffer(
        scene_front_interior, elev_deg=44.0, azim_deg=-26.0,
        width=560, height=640, ssaa=2,
        fixed_span=76.0, fixed_center=[0.0, 0.0, 3.5]
    )
    im2 = rl.rasterize_scene_zbuffer(
        scene_back_interior, elev_deg=42.0, azim_deg=-24.0,
        width=560, height=640, ssaa=2,
        fixed_span=76.0, fixed_center=[0.0, -2.5, -12.5]
    )
    im3 = rl.rasterize_scene_zbuffer(
        scene_plate, elev_deg=38.0, azim_deg=-28.0,
        width=740, height=640, ssaa=2,
        fixed_span=142.0, fixed_center=[-6.0, 0.0, 4.0]
    )

    W_tot = 560 + 560 + 740
    H_tot = 96 + 640
    canvas = Image.new("RGB", (W_tot, H_tot), (15, 19, 27))
    d = ImageDraw.Draw(canvas)
    f_title, f_sub, f_lbl, f_sm = rl.load_fonts()

    d.rectangle([0, 0, W_tot, 92], fill=(22, 28, 40))
    d.text(
        (28, 14),
        "GOTCHI V4.3 (Rev 8.4) — Validated 6x6mm Button, 8.5mm Switch & 15x10mm Speaker Cradles + Wire Slots",
        fill=(244, 247, 252),
        font=f_title,
    )
    d.text(
        (28, 52),
        "36.4 x 71.0 x 18.5mm | 6.3x6.45mm Btn Pockets + Dual Rear Wire Slots | 8.9mm Switch L-Brackets | 15.4x10.3mm Spk Cradle",
        fill=(148, 185, 228),
        font=f_sub,
    )

    canvas.paste(im1, (0, 96))
    canvas.paste(im2, (560, 96))
    canvas.paste(im3, (1120, 96))

    d.line([(560, 96), (560, H_tot)], fill=(45, 55, 72), width=3)
    d.line([(1120, 96), (1120, H_tot)], fill=(45, 55, 72), width=3)

    d.rectangle([16, 110, 540, 146], fill=(20, 83, 45))
    d.text((24, 117), "1. FRONT: Cam Cradle + 4 Pins + 15x10 Spk w/ 3 Wire Slots", fill=(220, 252, 231), font=f_sm)

    d.rectangle([576, 110, 1104, 146], fill=(30, 58, 138))
    d.text((584, 117), "2. BACK: 6x6mm Btn Wire Slots + 8.9mm Switch Window + Y-Stop", fill=(219, 234, 254), font=f_sm)

    d.rectangle([1136, 110, 1840, 146], fill=(45, 55, 72))
    d.text((1144, 117), "3. V4.3 4-PART PLATE (Z=0): Zero-Zit Sequential/Aligned Profile", fill=(241, 245, 249), font=f_sm)

    canvas.save(out_path)
    print(f"Wrote {out_path} ({canvas.size[0]}x{canvas.size[1]})")
    return out_path


def slice_and_dispatch():
    import nas_config
    import requests

    with open("/workspace/data/3dprint/gotchi_v4_2_process.json") as f:
        proc = json.load(f)

    # Preserve 100% of the zero-zit V4.2 settings AND harden multi-part travel moves:
    proc["name"] = "0.20mm Gotchi V4.3 Zero-Zit & Corner-Hardened @Creality Ender3V2"
    proc["enable_support"] = "0"
    proc["elefant_foot_compensation"] = "0.18"
    proc["initial_layer_line_width"] = "0.42"
    proc["outer_wall_jerk"] = "6"
    proc["inner_wall_jerk"] = "7"
    proc["seam_position"] = "aligned"
    proc["wall_infill_order"] = "inner wall/outer wall/infill"
    proc["retract_when_changing_layer"] = "1"
    proc["wipe_before_external_loop"] = "1"
    proc["wipe"] = "1"
    proc["wipe_distance"] = "2.0"
    proc["reduce_crossing_wall"] = "1"
    proc["max_travel_detour_distance"] = "150%"
    proc["reduce_infill_retraction"] = "0"
    proc["brim_type"] = "no_brim"
    proc["brim_width"] = "0"
    proc["raft_layers"] = "0"
    proc["detect_thin_wall"] = "1"
    proc["wall_loops"] = "3"
    proc["sparse_infill_density"] = "20%"
    proc["sparse_infill_pattern"] = "gyroid"

    proc_path = "/workspace/data/3dprint/gotchi_v4_3_process.json"
    with open(proc_path, "w") as f:
        json.dump(proc, f, indent=2)

    with open("/secrets/env.json") as f:
        env = json.load(f)
    ha_url = env["HA_BASE_URL"].rstrip("/")
    ha_tok = env["HA_ACCESS_TOKEN"]

    req_on = urllib.request.Request(
        f"{ha_url}/api/services/switch/turn_on",
        data=json.dumps({"entity_id": "switch.3d_printer_power"}).encode(),
        headers={"Authorization": f"Bearer {ha_tok}", "Content-Type": "application/json"},
        method="POST",
    )
    urllib.request.urlopen(req_on, timeout=10)
    print("Turned ON switch.3d_printer_power")

    cmd = (
        "cp /volume1/docker/discord-agy-agent/workspace/data/3dprint/my_machine.json /volume1/docker/orcaslicer/prints/ && "
        "cp /volume1/docker/discord-agy-agent/workspace/data/3dprint/gotchi_case_v4_3_plate.stl /volume1/docker/orcaslicer/prints/ && "
        "cp /volume1/docker/discord-agy-agent/workspace/data/3dprint/gotchi_v4_3_process.json /volume1/docker/orcaslicer/prints/ && "
        "nice -n 19 sudo docker exec orcaslicer /opt/orcaslicer/bin/orca-slicer "
        "--load-settings \"/prints/my_machine.json;/prints/gotchi_v4_3_process.json\" "
        "--load-filaments \"/prints/my_filament.json\" "
        "--slice 0 --outputdir /prints /prints/gotchi_case_v4_3_plate.stl && "
        "cp /volume1/docker/orcaslicer/prints/plate_1.gcode /volume1/docker/discord-agy-agent/workspace/data/3dprint/gotchi_case_v4_3_plate.gcode"
    )
    rc, out, err = nas_config.run_ssh(nas_config.HOST_2_IP, cmd, timeout=60)
    print("Slice RC:", rc)
    if rc != 0:
        print("STDOUT:", out)
        print("STDERR:", err)
        sys.exit(1)

    gcode_path = "/workspace/data/3dprint/gotchi_case_v4_3_plate.gcode"
    for line in open(gcode_path):
        if any(k in line for k in ["; filament used", "; estimated printing time", "; total layers count"]):
            print(line.strip())

    octo_url = f"http://{nas_config.HOST_2_IP}:8888"
    octo_key = "8FC0C5F37CD14D4384100ED682682A80"

    for attempt in range(10):
        req = urllib.request.Request(f"{octo_url}/api/connection", headers={"X-Api-Key": octo_key})
        with urllib.request.urlopen(req, timeout=10) as r:
            conn = json.loads(r.read().decode())
        state = conn["current"]["state"]
        print(f"OctoPrint state (attempt {attempt+1}): {state}")
        if state == "Operational":
            break
        if state in ("Closed", "Error", "Offline"):
            req_c = urllib.request.Request(
                f"{octo_url}/api/connection",
                data=json.dumps({"command": "connect"}).encode(),
                headers={"X-Api-Key": octo_key, "Content-Type": "application/json"},
                method="POST",
            )
            urllib.request.urlopen(req_c, timeout=10)
        time.sleep(2.0)

    with open(gcode_path, "rb") as f:
        r = requests.post(
            f"{octo_url}/api/files/local",
            headers={"X-Api-Key": octo_key},
            files={"file": ("gotchi_case_v4_3_plate.gcode", f, "application/octet-stream")},
            data={"select": "true", "print": "true"},
            timeout=30,
        )
    print("OctoPrint upload status:", r.status_code, r.text[:250])

    subprocess.run(["python3", "/workspace/tools/webcam_control.py", "start"], check=False)
    subprocess.run(["python3", "/workspace/tools/zero_printer_watcher.py", "--restart"], check=False)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="/workspace/gotchi/cad")
    parser.add_argument("--deliver-channel", default="")
    parser.add_argument("--dispatch", action="store_true")
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

    if hits > 0:
        raise RuntimeError(f"Detected {hits} collision(s)!")
    print("ALL 3D COMPONENT, SHELL & HINGE CLEARANCES VERIFIED: 0 COLLISIONS (0.00 mm^3)")

    export_stls(args.out, front, back, cap, saddle, clip_stand)
    preview_path = render_v4_3_preview(args.out, front, back, saddle, clip_stand, comps)

    if args.deliver_channel:
        from deliver_image import deliver_image
        res = deliver_image(
            preview_path,
            channel_input=args.deliver_channel,
            caption="📐 **Gotchi V4.3 (Rev 8.4 — Validated Cradles & Wire Channels)** — `6.3×6.45 mm` Tactile Button Pockets w/ Dual Rear Wire Slots, `8.9 mm` Slide Switch L-Brackets, and `15.4×10.3 mm` `1510` Speaker Cradle w/ 3-Side Wire Channels",
        )
        print("Deliver result:", res)

    if args.dispatch:
        slice_and_dispatch()


if __name__ == "__main__":
    main()
