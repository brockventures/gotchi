#!/usr/bin/env python3
"""
render_v3_plate.py: True Per-Pixel Barycentric Z-Buffer 3-Panel Preview for Gotchi V4
(Option 1A Top-Wall USB-C + Flat Under-Tucked XIAO + 18.3 mm Slimmed Depth + Snug Hinged Back Clip,
4-Part Print Plate without Button Caps).
"""

import math
import os
import sys
import numpy as np
import trimesh
from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import build_case as bc
import render_labeled as rl


def rotate_about_x(mesh, angle_deg, pivot_y, pivot_z):
    m = mesh.copy()
    m.apply_translation([0.0, -pivot_y, -pivot_z])
    rot = trimesh.transformations.rotation_matrix(math.radians(angle_deg), [1.0, 0.0, 0.0])
    m.apply_transform(rot)
    m.apply_translation([0.0, pivot_y, pivot_z])
    return m


def main():
    out_dir = os.path.join(HERE, "renders")
    os.makedirs(out_dir, exist_ok=True)
    out_path_v4 = os.path.join(out_dir, "v4_build_preview.png")
    out_path_v3 = os.path.join(out_dir, "v3_build_preview.png")

    p = bc.P
    front = bc.build_front_shell()
    back = bc.build_back_shell()
    saddle = bc.build_hinge_saddle()
    arm_closed = bc.build_clip_stand_arm()
    arm_open = rotate_about_x(arm_closed, 26.0, pivot_y=p["hinge_pin_y"], pivot_z=p["hinge_pin_z"])
    pin = bc.make_cyl_x(0.88, -7.8, 7.8, cy=p["hinge_pin_y"], cz=p["hinge_pin_z"])
    comps = bc.build_internal_3d_components()

    # Panel 1: Front/Top-Crown Isometric (showing centered Camera Bore, PDM Mic Port, Top USB-C & Internal XIAO/Cam)
    scene_front_iso = [
        (front, (0.84, 0.88, 0.93)),
        (back, (0.27, 0.32, 0.40)),
        (comps["xiao_sense_camera_1a"], (0.18, 0.72, 0.45)),
        (comps["display_composite"], (0.20, 0.45, 0.82)),
    ]

    # Panel 2: Rear Isometric with Snug V3.2/V4 Hinged Clip-Stand (Open 26° Kickstand + Top-Wall USB-C visible)
    scene_rear_open = [
        (front, (0.84, 0.88, 0.93)),
        (back, (0.27, 0.32, 0.40)),
        (saddle, (0.22, 0.62, 0.92)),
        (pin, (0.95, 0.35, 0.20)),
        (arm_open, (0.28, 0.78, 0.52)),
    ]

    # Panel 3: 4-Part Z=0 Print Plate Layout (Front, Back, Saddle, Clip Arm — NO Button Caps)
    stl_dir = os.path.join(HERE, "stl")
    f_p = trimesh.load(os.path.join(stl_dir, "gotchi_front.stl"))
    f_p.apply_translation([-16.0, 0.0, 0.0])

    b_p = trimesh.load(os.path.join(stl_dir, "gotchi_back.stl"))
    b_p.apply_translation([26.0, 0.0, 0.0])

    s_p = trimesh.load(os.path.join(stl_dir, "gotchi_hinge_saddle.stl"))
    s_p.apply_translation([-48.0, 18.0, 0.0])

    a_p = trimesh.load(os.path.join(stl_dir, "gotchi_clip_stand.stl"))
    a_p.apply_translation([-48.0, -10.0, 0.0])

    bed_pad = bc.make_box(-64.0, 52.0, -34.0, 34.0, -0.8, -0.05)

    scene_plate = [
        (bed_pad, (0.16, 0.19, 0.24)),
        (f_p, (0.84, 0.88, 0.93)),
        (b_p, (0.27, 0.32, 0.40)),
        (s_p, (0.22, 0.62, 0.92)),
        (a_p, (0.28, 0.78, 0.52)),
    ]

    im1 = rl.rasterize_scene_zbuffer(
        scene_front_iso, elev_deg=24.0, azim_deg=-32.0,
        width=560, height=620, ssaa=2,
        fixed_span=78.0, fixed_center=[0.0, 3.0, -9.5]
    )
    im2 = rl.rasterize_scene_zbuffer(
        scene_rear_open, elev_deg=22.0, azim_deg=138.0,
        width=560, height=620, ssaa=2,
        fixed_span=78.0, fixed_center=[0.0, 3.0, -11.5]
    )
    im3 = rl.rasterize_scene_zbuffer(
        scene_plate, elev_deg=38.0, azim_deg=-28.0,
        width=740, height=620, ssaa=2,
        fixed_span=138.0, fixed_center=[-6.0, 1.0, 4.0]
    )

    W_tot = 560 + 560 + 740
    H_tot = 96 + 620
    canvas = Image.new("RGB", (W_tot, H_tot), (15, 19, 27))
    d = ImageDraw.Draw(canvas)
    f_title, f_sub, f_lbl, f_sm = rl.load_fonts()

    d.rectangle([0, 0, W_tot, 92], fill=(22, 28, 40))
    d.text(
        (28, 14),
        "GOTCHI V4 (Rev 8.0) — Option 1A Top-Wall USB-C + 18.3mm Slim Depth + V3.2 Snug Back Clip",
        fill=(244, 247, 252),
        font=f_title,
    )
    d.text(
        (28, 52),
        "15.5mm Cavity (-2.5mm vs V3) | Centered Crown Cam + Mic | Snug Tenon/Hinge | 4-Part Plate (No Button Caps)",
        fill=(148, 185, 228),
        font=f_sub,
    )

    canvas.paste(im1, (0, 96))
    canvas.paste(im2, (560, 96))
    canvas.paste(im3, (1120, 96))

    d.line([(560, 96), (560, H_tot)], fill=(45, 55, 72), width=3)
    d.line([(1120, 96), (1120, H_tot)], fill=(45, 55, 72), width=3)

    d.rectangle([16, 110, 520, 146], fill=(20, 83, 45))
    d.text((26, 117), "1. FRONT / TOP CROWN: Centered Cam + Mic & Top USB-C", fill=(220, 252, 231), font=f_sm)

    d.rectangle([576, 110, 1104, 146], fill=(30, 58, 138))
    d.text((586, 117), "2. REAR (18.3mm Slim): Snug V3.2 Clip + Top USB-C + 3-Slot", fill=(219, 234, 254), font=f_sm)

    d.rectangle([1136, 110, 1840, 146], fill=(45, 55, 72))
    d.text((1146, 117), "3. 4-PART PLATE (Z=0): Saddle & Arm (Left), Front, Back (Right)", fill=(241, 245, 249), font=f_sm)

    canvas.save(out_path_v4)
    canvas.save(out_path_v3)
    print(f"Wrote {out_path_v4} ({canvas.size[0]}x{canvas.size[1]})")


if __name__ == "__main__":
    main()
