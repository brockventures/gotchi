#!/usr/bin/env python3
"""
render_labeled.py: Studio-lit 3D renders and labeled orthographic CAD views for GOTCHI V1 (Rev 4).

Generates:
  - cad/renders/front_iso.png
  - cad/renders/back_iso.png
  - cad/renders/front_straight.png
  - cad/renders/back_layout.png
  - cad/renders/exploded.png
  - cad/renders/top_labeled.png
  - cad/renders/side_labeled.png

Enforces:
  - Real-world 1:1:1 aspect ratio (`ax.set_box_aspect((x_span, y_span, z_span))`)
  - Full watertight triangle topology (zero face-stride subsampling)
  - 3-point Key/Fill/Rim directional studio shading
"""

import argparse
import math
import os
import sys
import numpy as np
import trimesh
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d.art3d import Poly3DCollection
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import build_case as bc


def compute_face_colors(mesh, base_rgb, alpha=1.0):
    """Compute 3-point Key/Fill/Rim directional studio lighting per triangle."""
    normals = mesh.face_normals
    key_dir = np.array([0.45, -0.35, 0.82])
    key_dir /= np.linalg.norm(key_dir)
    fill_dir = np.array([-0.65, 0.45, 0.60])
    fill_dir /= np.linalg.norm(fill_dir)
    rim_dir = np.array([0.10, 0.85, -0.50])
    rim_dir /= np.linalg.norm(rim_dir)

    k = np.clip(normals @ key_dir, 0.0, 1.0)
    f = np.clip(normals @ fill_dir, 0.0, 1.0)
    r = np.clip(normals @ rim_dir, 0.0, 1.0)

    intensity = 0.28 + 0.54 * k + 0.22 * f + 0.14 * r
    base = np.array(base_rgb, dtype=float)
    rgb = np.clip( np.outer(intensity, base) + np.outer(0.08 * (k ** 4), np.ones(3)), 0.0, 1.0 )
    rgba = np.column_stack([rgb, np.full(len(mesh.faces), alpha)])
    return rgba


def render_3d_scene(meshes_with_styles, elev, azim, out_path, title=None, subtitle=None, dpi=180):
    """Render a list of (trimesh.Trimesh, rgb_tuple, alpha) with true 1:1:1 aspect ratio."""
    fig = plt.figure(figsize=(8.5, 8.5), dpi=dpi, facecolor="#141820")
    ax = fig.add_subplot(111, projection="3d", facecolor="#141820")

    all_mins = []
    all_maxs = []
    for m, rgb, alpha in meshes_with_styles:
        if m.is_empty:
            continue
        all_mins.append(m.bounds[0])
        all_maxs.append(m.bounds[1])
        tris = m.vertices[m.faces]
        fcolors = compute_face_colors(m, rgb, alpha=alpha)
        poly = Poly3DCollection(
            tris,
            facecolors=fcolors,
            edgecolors="none",
            linewidths=0.0,
            zsort="average",
        )
        ax.add_collection3d(poly)

    bmin = np.min(all_mins, axis=0)
    bmax = np.max(all_maxs, axis=0)
    pad = 2.5
    ax.set_xlim(bmin[0] - pad, bmax[0] + pad)
    ax.set_ylim(bmin[1] - pad, bmax[1] + pad)
    ax.set_zlim(bmin[2] - pad, bmax[2] + pad)

    spans = (bmax - bmin) + 2 * pad
    ax.set_box_aspect((spans[0], spans[1], spans[2]))
    ax.view_init(elev=elev, azim=azim)
    ax.set_axis_off()
    plt.subplots_adjust(left=0.0, right=1.0, bottom=0.0, top=0.92 if title else 1.0)

    if title:
        fig.suptitle(title, color="#f0f4f8", fontsize=15, fontweight="bold", y=0.965)
    if subtitle:
        fig.text(0.5, 0.93, subtitle, color="#9ab0c8", fontsize=10.5, ha="center")

    fig.savefig(out_path, dpi=dpi, facecolor=fig.get_facecolor())
    plt.close(fig)


def translate_mesh(m, dx=0.0, dy=0.0, dz=0.0):
    c = m.copy()
    c.apply_translation([dx, dy, dz])
    return c


def load_fonts():
    ttf_dir = os.path.join(matplotlib.get_data_path(), "fonts", "ttf")
    bold_p = os.path.join(ttf_dir, "DejaVuSans-Bold.ttf")
    reg_p = os.path.join(ttf_dir, "DejaVuSans.ttf")
    if not os.path.exists(bold_p):
        bold_p = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
        reg_p = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    return (
        ImageFont.truetype(bold_p, 28),
        ImageFont.truetype(bold_p, 20),
        ImageFont.truetype(reg_p, 19),
        ImageFont.truetype(reg_p, 16),
    )


def draw_dashed_rect(draw, x0, y0, x1, y1, color, width=3, dash=10):
    x0, x1 = sorted((x0, x1))
    y0, y1 = sorted((y0, y1))
    edges = [((x0, y0), (x1, y0)), ((x1, y0), (x1, y1)), ((x1, y1), (x0, y1)), ((x0, y1), (x0, y0))]
    for (ax, ay), (bx, by) in edges:
        dist = math.hypot(bx - ax, by - ay)
        steps = max(1, int(dist // dash))
        for i in range(0, steps, 2):
            t0 = i / steps
            t1 = min(1.0, (i + 1) / steps)
            p0 = (ax + (bx - ax) * t0, ay + (by - ay) * t0)
            p1 = (ax + (bx - ax) * t1, ay + (by - ay) * t1)
            draw.line([p0, p1], fill=color, width=width)


def generate_top_labeled(p, out_path):
    """
    Generate high-resolution annotated Top/Front Internal Packaging CAD Diagram (X-Y plane).
    Shows the true non-cubic 3D component footprints, flex cable routing, ports, and M2 bosses.
    """
    W, H = 1800, 1300
    im = Image.new("RGB", (W, H), (248, 250, 252))
    d = ImageDraw.Draw(im)
    f_title, f_sub, f_lbl, f_sm = load_fonts()

    # Header banner
    d.rectangle([0, 0, W, 92], fill=(20, 26, 36))
    d.text((32, 16), "GOTCHI V1 (Rev 4) — Front / Top-Down Internal Packaging View (36.4 x 60.2 mm)", fill=(242, 246, 250), font=f_title)
    d.text((32, 54), "Forward-Firing Screen & Camera (+Z)  |  Upward-Pointing PDM Mic (+Y)  |  Non-Cubic Multi-Tier Stack (20.8 mm thin)", fill=(150, 185, 225), font=f_sub)

    # Coordinate mapping: X in [-22, +22], Y in [-31, +36]
    cx_px, cy_px = W // 2, 705
    scale = 15.6  # px per mm

    def pt(x, y):
        return (int(round(cx_px + x * scale)), int(round(cy_px - y * scale)))

    def rect_mm(x0, y0, x1, y1):
        px0, py0 = pt(x0, y1)
        px1, py1 = pt(x1, y0)
        return [px0, py0, px1, py1]

    hw = p["W_out"] / 2.0
    iw = hw - p["wall"]

    # 1. Outer & inner enclosure walls
    d.rounded_rectangle(rect_mm(-hw, p["y_min"], hw, p["y_max"]), radius=int(2.8 * scale), fill=(226, 232, 240), outline=(45, 55, 72), width=4)
    d.rectangle(rect_mm(-iw, p["y_min"] + p["wall"], iw, p["y_max"] - p["wall"]), fill=(241, 245, 249), outline=(100, 116, 139), width=2)

    # 2. Rear Slim Audio Bay components (drawn first as deepest layer z = -15.2..-19.2 mm)
    # MAX98357A Amp
    ax0, ax1 = p["amp_cx"] - p["amp_w"]/2, p["amp_cx"] + p["amp_w"]/2
    ay0, ay1 = p["amp_cy"] - p["amp_h"]/2, p["amp_cy"] + p["amp_h"]/2
    d.rectangle(rect_mm(ax0, ay0, ax1, ay1), fill=(216, 190, 245), outline=(107, 33, 168), width=3)
    d.text(pt(p["amp_cx"] - 7.5, p["amp_cy"] + 1.5), "MAX98357A Amp", fill=(76, 29, 149), font=f_sm)
    d.text(pt(p["amp_cx"] - 7.5, p["amp_cy"] - 1.5), "(z=-15.2..-18.2)", fill=(76, 29, 149), font=f_sm)

    # Speaker 15x10x3.5 mm + 5 rear grille slots
    sx0, sx1 = p["spk_cx"] - p["spk_w"]/2, p["spk_cx"] + p["spk_w"]/2
    sy0, sy1 = p["spk_cy"] - p["spk_h"]/2, p["spk_cy"] + p["spk_h"]/2
    d.rectangle(rect_mm(sx0, sy0, sx1, sy1), fill=(252, 202, 202), outline=(185, 28, 28), width=3)
    for ix in range(-2, 3):
        gx = p["spk_cx"] + ix * 2.6
        d.rectangle(rect_mm(gx - 0.5, p["spk_cy"] - 3.0, gx + 0.5, p["spk_cy"] + 3.0), fill=(153, 27, 27))

    # 3. 803040 LiPo Battery (30 x 40 x 8 mm at y = -18.2..+21.8, z = -6.2..-14.2 mm)
    bx0, by0, bx1, by1 = rect_mm(-p["bat_w"]/2, p["bat_y0"], p["bat_w"]/2, p["bat_y1"])
    draw_dashed_rect(d, bx0, by0, bx1, by1, (217, 119, 6), width=4, dash=14)

    # 4. Waveshare 1.54" V2 Display PCB (33 x 48 mm at y = -25.5..+22.5, z = -1.45..-4.1 mm)
    dx0, dy0, dx1, dy1 = rect_mm(-p["disp_w"]/2, p["disp_y0"], p["disp_w"]/2, p["disp_y1"])
    draw_dashed_rect(d, dx0, dy0, dx1, dy1, (37, 99, 235), width=3, dash=10)

    # Display Bottom 8-pin PH2.0 JST connector (localized to y = -25.4..-19.0 mm below battery!)
    d.rectangle(rect_mm(-p["ph20_w"]/2, p["ph20_y0"], p["ph20_w"]/2, p["ph20_y1"]), fill=(219, 234, 254), outline=(29, 78, 216), width=3)
    d.text(pt(-7.8, -21.5), "8-Pin PH2.0 Plug", fill=(30, 58, 138), font=f_sm)
    d.text(pt(-7.8, -23.8), "(below battery!)", fill=(30, 58, 138), font=f_sm)

    # Display Top 24-pin FPC Ribbon Fold & Bezel Relief Pocket (y = +18.0..+22.4 mm)
    d.rectangle(rect_mm(-p["disp_fpc_w"]/2, p["disp_fpc_y0"], p["disp_fpc_w"]/2, p["disp_fpc_y1"]), fill=(254, 215, 170), outline=(194, 65, 12), width=2)
    d.text(pt(-6.8, 20.8), "Display FPC Fold", fill=(154, 52, 18), font=f_sm)

    # Active 28.0 x 28.0 mm Forward-Firing E-Paper Window (y = -11.0..+17.0 mm)
    wx0, wy0, wx1, wy1 = rect_mm(-p["win_w"]/2, p["win_cy"] - p["win_h"]/2, p["win_w"]/2, p["win_cy"] + p["win_h"]/2)
    d.rectangle([wx0, wy0, wx1, wy1], outline=(15, 23, 42), width=4)
    d.text(pt(-9.5, 14.5), "28x28 mm E-Paper Window (+Z)", fill=(15, 23, 42), font=f_sm)

    # 5. Top Crown (y = +22.8..+31.4 mm):
    # Horizontal XIAO ESP32S3 + Sense Stack (x = -16.5..+4.5, y = +22.8..+30.6 mm)
    d.rectangle(rect_mm(p["xiao_x0"], p["xiao_y0"], p["xiao_x1"], p["xiao_y0"] + 4.0), fill=(187, 247, 208), outline=(21, 128, 61), width=3)
    d.rectangle(rect_mm(p["xiao_x0"] + 6.5, p["xiao_y0"] + 4.0, p["xiao_x1"], p["xiao_y1"]), fill=(134, 239, 172), outline=(22, 101, 52), width=3)
    d.text(pt(-15.5, 25.5), "XIAO ESP32S3 + Sense", fill=(20, 83, 45), font=f_sm)

    # Upward-Pointing PDM Microphone on top of Sense PCB (+Y wall waveguide at x = -2.5 mm)
    d.rectangle(rect_mm(p["mic_cx"] - 1.75, p["xiao_y1"], p["mic_cx"] + 1.75, p["xiao_y1"] + 0.9), fill=(250, 204, 21), outline=(161, 98, 7), width=2)
    d.rectangle(rect_mm(p["mic_cx"] - 1.1, p["y_max"] - p["wall"], p["mic_cx"] + 1.1, p["y_max"]), fill=(239, 68, 68), outline=(153, 27, 27), width=2)

    # 90-deg Curved Camera FPC Flex Ribbon (x = +4.5 to +6.0 mm) + Forward-Firing Camera (+Z at x = +10.2, y = +26.9 mm)
    d.rectangle(rect_mm(p["xiao_x1"], p["cam_cy"] - 3.0, p["cam_cx"] - p["cam_w"]/2, p["cam_cy"] + 3.0), fill=(251, 146, 60), outline=(194, 65, 12), width=2)
    cx0, cy0, cx1, cy1 = rect_mm(p["cam_cx"] - p["cam_w"]/2, p["cam_cy"] - p["cam_h"]/2, p["cam_cx"] + p["cam_w"]/2, p["cam_cy"] + p["cam_h"]/2)
    d.rectangle([cx0, cy0, cx1, cy1], fill=(51, 65, 85), outline=(15, 23, 42), width=3)
    lcx, lcy = pt(p["cam_cx"], p["cam_cy"])
    lr = int((p["cam_lens_d"] / 2.0) * scale)
    d.ellipse([lcx - lr, lcy - lr, lcx + lr, lcy + lr], fill=(30, 41, 59), outline=(56, 189, 248), width=3)

    # Top-right shoulder PTT Button (+Y wall behind camera at x = +10.2 mm)
    d.rectangle(rect_mm(p["ptt_cx"] - 3.0, p["y_max"] - p["wall"] - 2.0, p["ptt_cx"] + 3.0, p["y_max"] + 0.8), fill=(253, 224, 71), outline=(161, 98, 7), width=2)

    # Right-wall Mode/Snap Button (+X wall at y = +12.0 mm)
    d.rectangle(rect_mm(iw - 2.0, p["snap_cy"] - 3.0, hw + 0.8, p["snap_cy"] + 3.0), fill=(253, 224, 71), outline=(161, 98, 7), width=2)

    # Left-wall USB-C opening (-X wall at y = +24.8 mm)
    d.rectangle(rect_mm(-hw - 0.5, p["usb_cy"] - p["usb_h"]/2, -iw + 0.5, p["usb_cy"] + p["usb_h"]/2), fill=(56, 189, 248), outline=(2, 132, 199), width=2)

    # Left-wall Power Slide Switch (-X wall at y = -20.5 mm)
    d.rectangle(rect_mm(-hw - 0.5, p["sw_cy"] - p["sw_slot_y"]/2, -iw + 1.5, p["sw_cy"] + p["sw_slot_y"]/2), fill=(45, 212, 191), outline=(15, 118, 110), width=2)

    # 4x M2 Corner Bosses
    for bx, by, r_b in [
        (-p["boss_x_bot"], p["boss_y_bot"], 2.1),
        (p["boss_x_bot"], p["boss_y_bot"], 2.1),
        (-15.0, 30.8, 1.8),
        (p["boss_x_top"], p["boss_y_top"], 2.1),
    ]:
        px, py = pt(bx, by)
        pr = int(r_b * scale)
        d.ellipse([px - pr, py - pr, px + pr, py + pr], fill=(203, 213, 225), outline=(51, 65, 85), width=2)
        d.ellipse([px - 5, py - 5, px + 5, py + 5], fill=(71, 85, 105))

    # Callout Labels (Left & Right columns)
    callouts = [
        ("UPWARD PDM Mic Port (+Y top wall, dia 2.2mm)", pt(p["mic_cx"], p["y_max"] - 0.5), "L", 145),
        ("XIAO ESP32S3 + Sense (horizontal in Top Crown)", pt(-8.0, 27.5), "L", 235),
        ("Left-Wall USB-C Port (-X wall, y=+24.8mm)", pt(-hw, p["usb_cy"]), "L", 325),
        ("Display Top FPC Fold Relief Pocket (z=-0.8..-2.6)", pt(-4.5, 20.2), "L", 415),
        ("Forward E-Paper Window (28x28mm, 4.2mm bezels)", pt(-14.0, 8.0), "L", 515),
        ("803040 LiPo Battery (30x40x8mm behind flat PCB)", pt(-15.0, -3.0), "L", 615),
        ("MAX98357A I2S Amp (z=-15.2..-18.2mm rear bay)", pt(p["amp_cx"] - 5.0, p["amp_cy"]), "L", 715),
        ("SPDT Slide Switch (-X left wall, y=-20.5mm)", pt(-hw, p["sw_cy"]), "L", 825),
        ("Display 8-Pin PH2.0 Header (in chin below battery)", pt(-6.0, -22.2), "L", 925),
        ("Bottom M2 Screw Bosses (index through PCB holes)", pt(-p["boss_x_bot"], p["boss_y_bot"]), "L", 1025),

        ("BTN_TOP: Push-to-Talk (+Y top-right shoulder)", pt(p["ptt_cx"], p["y_max"]), "R", 155),
        ("Forward-Firing Camera (+Z lens aperture, dia 7.6mm)", pt(p["cam_cx"] + 2.0, p["cam_cy"]), "R", 265),
        ("90-deg Curved Camera FPC Ribbon (exits Sense +X)", pt(5.2, 26.9), "R", 375),
        ("BTN_BOT: Mode / Snap (+X right wall, y=+12.0mm)", pt(hw, p["snap_cy"]), "R", 495),
        ("Waveshare 1.54\" V2 PCB (33x48mm, standoffs removed)", pt(16.5, -2.0), "R", 615),
        ("Speaker 15x10x3.5mm + 5-Slot Rear Grille", pt(p["spk_cx"] + 4.0, p["spk_cy"]), "R", 785),
        ("Bottom-Right M2 Boss (x=+14.0, y=-23.0mm)", pt(p["boss_x_bot"], p["boss_y_bot"]), "R", 945),
    ]

    for text, (ax, ay), side, ty in callouts:
        if side == "L":
            tx = 36
            tw = d.textlength(text, font=f_lbl)
            lx = tx + tw + 12
        else:
            tx = 1230
            lx = tx - 12
        d.line([(lx, ty + 11), (ax, ay)], fill=(71, 85, 105), width=2)
        d.ellipse([ax - 5, ay - 5, ax + 5, ay + 5], fill=(220, 38, 38))
        d.text((tx, ty), text, fill=(15, 23, 42), font=f_lbl)

    im.save(out_path)
    print(f"Wrote {out_path}")


def generate_side_labeled(p, out_path):
    """
    Generate high-resolution annotated Side Cross-Section CAD Diagram (Y-Z plane, 60.2 x 20.8 mm).
    Clearly illustrates why the stepped Z-stack is only 20.8 mm thick (vs 29.0 mm in Rev 1).
    """
    W, H = 1920, 1200
    im = Image.new("RGB", (W, H), (248, 250, 252))
    d = ImageDraw.Draw(im)
    f_title, f_sub, f_lbl, f_sm = load_fonts()

    # Header banner
    d.rectangle([0, 0, W, 92], fill=(20, 26, 36))
    d.text((32, 16), "GOTCHI V1 (Rev 4) — Side Cross-Section View (60.2 mm Height x 20.8 mm Depth)", fill=(242, 246, 250), font=f_title)
    d.text((32, 54), "Stepped Z-Stack: Battery Nestles Behind Flat Upper 40mm of Display PCB; Tall PH2.0 Plug Sits Below Battery", fill=(150, 185, 225), font=f_sub)

    # Coordinate mapping: Y runs horizontally [-27.2..+33.0] inside x = [610..1260], Z runs vertically [-20.8..0.0]
    cy_px = 910
    cz_px = 390  # Z = 0.0 line
    scale = 10.6  # px per mm

    def pt(y, z):
        return (int(round(cy_px + y * scale)), int(round(cz_px - z * scale)))

    def rect_yz(y0, z0, y1, z1):
        px0, py0 = pt(y0, z1)
        px1, py1 = pt(y1, z0)
        return [px0, py0, px1, py1]

    # 1. Front Shell (z = -8.8 to 0.0 mm) & Back Shell (z = -20.8 to -8.8 mm)
    d.rectangle(rect_yz(p["y_min"], p["split_z"], p["y_max"], 0.0), fill=(226, 232, 240), outline=(51, 65, 85), width=3)
    d.rectangle(rect_yz(p["y_min"], -p["D_out"], p["y_max"], p["split_z"]), fill=(203, 213, 225), outline=(30, 41, 59), width=3)

    # Internal cavity (y = -25.7 to +31.5, z = -19.3 to -1.4 mm)
    d.rectangle(rect_yz(p["y_min"] + p["wall"], -p["D_out"] + p["back_wall"], p["y_max"] - p["wall"], -p["front_wall"]), fill=(248, 250, 252), outline=(148, 163, 184), width=2)

    # Split line at z = -8.8 mm
    sx0, sy0 = pt(p["y_min"] - 2.5, p["split_z"])
    sx1, sy1 = pt(p["y_max"] + 2.5, p["split_z"])
    draw_dashed_rect(d, sx0, sy0, sx1, sy1, (220, 38, 38), width=2, dash=10)

    # Front viewing window cutout (y = -11.0..+17.0, z = -1.4..0.0)
    d.rectangle(rect_yz(p["win_cy"] - p["win_h"]/2, -p["front_wall"], p["win_cy"] + p["win_h"]/2, 0.0), fill=(248, 250, 252), outline=(56, 189, 248), width=2)

    # Display FPC relief pocket on underside of front bezel (y = +17.8..+22.6, z = -2.6..-0.8)
    d.rectangle(rect_yz(p["disp_fpc_y0"] - 0.2, -2.6, p["disp_fpc_y1"] + 0.2, -0.8), fill=(254, 243, 199), outline=(217, 119, 6), width=2)

    # 2. Waveshare 1.54" V2 Composite Display:
    # Front e-paper glass laminate (y = -16.0..+21.3, z = -2.5..-1.45)
    d.rectangle(rect_yz(p["disp_glass_y0"], p["disp_glass_z1"], p["disp_glass_y1"], p["disp_glass_z0"]), fill=(147, 197, 253), outline=(29, 78, 216), width=2)
    # Display PCB (y = -25.5..+22.5, z = -4.1..-2.5)
    d.rectangle(rect_yz(p["disp_y0"], p["disp_pcb_z1"], p["disp_y1"], p["disp_pcb_z0"]), fill=(59, 130, 246), outline=(30, 58, 138), width=2)
    # Display Top FPC fold + rear ZIF (y = +18.0..+22.4, z = -5.9..-0.9)
    d.rectangle(rect_yz(p["disp_fpc_y0"], p["disp_zif_z1"], p["disp_fpc_y1"], -0.9), fill=(251, 146, 60), outline=(154, 52, 18), width=2)
    # Display Bottom 8-pin PH2.0 right-angle header (y = -25.4..-19.0, z = -8.7..-4.1)
    d.rectangle(rect_yz(p["ph20_y0"], p["ph20_z1"], p["ph20_y1"], p["disp_pcb_z1"]), fill=(219, 234, 254), outline=(29, 78, 216), width=3)

    # 3. 803040 LiPo Battery (y = -18.2..+21.8, z = -14.2..-6.2 mm — right behind flat upper display PCB!)
    d.rectangle(rect_yz(p["bat_y0"], p["bat_z1"], p["bat_y1"], p["bat_z0"]), fill=(253, 230, 138), outline=(180, 83, 9), width=3)
    d.text(pt(-11.0, -9.2), "803040 LiPo Battery (8.0 mm)", fill=(146, 64, 14), font=f_sm)

    # 4. Rear Slim Audio Bay (z = -19.2..-15.2 mm):
    # MAX98357A Amp (y = -10.4..+7.4, z = -18.2..-15.2)
    d.rectangle(rect_yz(p["amp_cy"] - p["amp_h"]/2, p["amp_z1"], p["amp_cy"] + p["amp_h"]/2, p["amp_z0"]), fill=(216, 180, 254), outline=(107, 33, 168), width=3)
    # Speaker (y = -24.0..-14.0, z = -19.2..-15.7)
    d.rectangle(rect_yz(p["spk_cy"] - p["spk_h"]/2, p["spk_z1"], p["spk_cy"] + p["spk_h"]/2, p["spk_z0"]), fill=(252, 165, 165), outline=(185, 28, 28), width=3)

    # 5. Top Crown (y = +22.8..+31.4 mm):
    # Horizontal XIAO ESP32S3 + Sense Stack (y = +22.8..+30.6, z = -19.2..-2.0 mm)
    d.rectangle(rect_yz(p["xiao_y0"], p["xiao_z1"], p["xiao_y0"] + 4.0, p["xiao_z0"]), fill=(187, 247, 208), outline=(21, 128, 61), width=2)
    d.rectangle(rect_yz(p["xiao_y0"] + 4.0, p["xiao_z1"], p["xiao_y1"], p["xiao_z0"]), fill=(134, 239, 172), outline=(22, 101, 52), width=2)
    # Upward PDM Mic on top of Sense PCB (+Y top wall acoustic port at z = -11.2 mm)
    d.rectangle(rect_yz(p["xiao_y1"], p["mic_cz"] - 1.3, p["xiao_y1"] + 0.8, p["mic_cz"] + 1.3), fill=(250, 204, 21), outline=(161, 98, 7), width=2)
    d.rectangle(rect_yz(p["y_max"] - p["wall"], p["mic_cz"] - 1.1, p["y_max"], p["mic_cz"] + 1.1), fill=(239, 68, 68), outline=(153, 27, 27), width=2)

    # Forward-Firing Camera Head (+Z aperture in front crown at y = +22.65..+31.15, z = -5.8..0.0 mm)
    d.rectangle(rect_yz(p["cam_cy"] - p["cam_h"]/2, p["cam_z1"], p["cam_cy"] + p["cam_h"]/2, -2.8), fill=(51, 65, 85), outline=(15, 23, 42), width=3)
    d.rectangle(rect_yz(p["cam_cy"] - p["cam_lens_d"]/2, -2.8, p["cam_cy"] + p["cam_lens_d"]/2, 0.0), fill=(56, 189, 248), outline=(2, 132, 199), width=2)

    # Callout Labels
    callouts = [
        ("Front Face (Z = 0.0 mm) + 28x28 E-Paper Window", pt(2.0, -0.7), "L", 160),
        ("Waveshare Glass + PCB Laminate (z = -1.45..-4.1 mm)", pt(-10.0, -3.3), "L", 250),
        ("8-Pin PH2.0 Plug (z = -4.1..-8.7 mm, below battery!)", pt(-22.2, -6.4), "L", 350),
        ("Front / Back Shell Split Plane (z = -8.8 mm)", pt(-27.2, -8.8), "L", 450),
        ("803040 LiPo Battery (z = -6.2..-14.2 mm, 8mm thick)", pt(-5.0, -10.2), "L", 550),
        ("MAX98357A Class-D Amp (z = -15.2..-18.2 mm)", pt(-2.0, -16.7), "L", 660),
        ("15x10x3.5mm Speaker + Rear Acoustic Slots", pt(-19.0, -17.5), "L", 770),
        ("Back Wall (Z = -20.8 mm — 8.2 mm thinner than Rev 1!)", pt(-12.0, -20.1), "L", 880),

        ("Forward-Firing Camera (+Z aperture in Top Crown)", pt(27.5, -1.5), "R", 160),
        ("Display Top FPC Fold Relief Pocket (z = -0.8..-2.6 mm)", pt(20.2, -1.8), "R", 265),
        ("Display Rear ZIF Connector (z = -4.1..-5.9 mm)", pt(20.2, -5.0), "R", 370),
        ("XIAO ESP32S3 + Sense Stack (horizontal in Crown)", pt(26.5, -8.5), "R", 485),
        ("UPWARD PDM Microphone + Top Acoustic Port (+Y)", pt(31.8, -11.2), "R", 605),
        ("Top-Shoulder Push-to-Talk Button (+Y at z = -13.2 mm)", pt(32.2, -13.2), "R", 725),
        ("XIAO Support Shelf (y = +21.9..+22.7 mm)", pt(22.3, -15.5), "R", 845),
    ]

    for text, (ax, ay), side, ty in callouts:
        if side == "L":
            tx = 32
            tw = d.textlength(text, font=f_lbl)
            lx = tx + tw + 12
        else:
            tx = 1310
            lx = tx - 12
        d.line([(lx, ty + 11), (ax, ay)], fill=(71, 85, 105), width=2)
        d.ellipse([ax - 5, ay - 5, ax + 5, ay + 5], fill=(220, 38, 38))
        d.text((tx, ty), text, fill=(15, 23, 42), font=f_lbl)

    im.save(out_path)
    print(f"Wrote {out_path}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=HERE)
    args, _ = parser.parse_known_args()

    ren_dir = os.path.join(os.path.abspath(args.out), "renders")
    os.makedirs(ren_dir, exist_ok=True)

    p = bc.P
    front = bc.build_front_shell()
    back = bc.build_back_shell()
    cap = bc.build_button_cap()
    comps = bc.build_internal_3d_components()

    # Position button caps on assembled model for visualization
    # 1. PTT button cap on +Y top wall (x = ptt_cx, y = y_max, z = ptt_cz)
    cap_ptt = cap.copy()
    cap_ptt.apply_transform(trimesh.transformations.rotation_matrix(-math.pi / 2.0, [1, 0, 0]))
    cap_ptt.apply_translation([p["ptt_cx"], p["y_max"] - 2.2, p["ptt_cz"]])

    # 2. Mode/Snap button cap on +X right wall (x = W_out/2, y = snap_cy, z = snap_cz)
    cap_snap = cap.copy()
    cap_snap.apply_transform(trimesh.transformations.rotation_matrix(math.pi / 2.0, [0, 1, 0]))
    cap_snap.apply_translation([p["W_out"] / 2.0 - 2.2, p["snap_cy"], p["snap_cz"]])

    shell_front_rgb = (0.86, 0.89, 0.93)
    shell_back_rgb = (0.24, 0.29, 0.36)
    comp_styles = {
        "display_composite": (0.20, 0.48, 0.92),
        "battery_803040": (0.92, 0.62, 0.14),
        "xiao_sense_upward_mic": (0.18, 0.76, 0.38),
        "camera_forward_flex": (0.95, 0.42, 0.15),
        "speaker_1510": (0.88, 0.24, 0.24),
        "amp_max98357a": (0.64, 0.32, 0.88),
    }

    assembled_scene = [
        (front, shell_front_rgb, 1.0),
        (back, shell_back_rgb, 1.0),
        (cap_ptt, (0.95, 0.78, 0.15), 1.0),
        (cap_snap, (0.95, 0.78, 0.15), 1.0),
        (comps["display_composite"], comp_styles["display_composite"], 1.0),
        (comps["camera_forward_flex"], (0.18, 0.22, 0.28), 1.0),
    ]

    # 1. front_iso.png
    render_3d_scene(
        assembled_scene, elev=26, azim=-52,
        out_path=os.path.join(ren_dir, "front_iso.png"),
        title="GOTCHI V1 (Rev 4) — Front Isometric",
        subtitle="36.4 x 60.2 x 20.8 mm | Forward Screen & Camera (+Z) | Upward PDM Mic (+Y) | Left USB-C (-X)"
    )

    # 2. back_iso.png
    render_3d_scene(
        assembled_scene, elev=28, azim=132,
        out_path=os.path.join(ren_dir, "back_iso.png"),
        title="GOTCHI V1 (Rev 4) — Back Isometric",
        subtitle="4x Counterbored M2 Corners | 5-Slot Speaker Grille | Top PTT (+Y) & Side Mode (+X) Buttons"
    )

    # 3. front_straight.png
    render_3d_scene(
        assembled_scene, elev=88, azim=-90,
        out_path=os.path.join(ren_dir, "front_straight.png"),
        title="GOTCHI V1 (Rev 4) — Front Orthographic",
        subtitle="Slim 4.2 mm Side Bezels | 28x28 mm E-Paper Window | Upper-Right Forward Camera Aperture"
    )

    # 4. back_layout.png (Open internal layout in back shell with front shell removed)
    open_scene = [(back, shell_back_rgb, 1.0), (cap_ptt, (0.95, 0.78, 0.15), 1.0), (cap_snap, (0.95, 0.78, 0.15), 1.0)]
    for cname, cm in comps.items():
        open_scene.append((cm, comp_styles[cname], 1.0))
    render_3d_scene(
        open_scene, elev=34, azim=-60,
        out_path=os.path.join(ren_dir, "back_layout.png"),
        title="GOTCHI V1 (Rev 4) — Internal 3D Multi-Tier Packaging",
        subtitle="Blue: Display+PH2.0 | Orange: Forward Cam+90° FPC | Green: Horizontal XIAO+Upward Mic | Gold: 803040 LiPo"
    )

    # 5. exploded.png
    exploded_scene = [
        (translate_mesh(front, dz=18.0), shell_front_rgb, 1.0),
        (translate_mesh(comps["camera_forward_flex"], dz=9.5), comp_styles["camera_forward_flex"], 1.0),
        (translate_mesh(comps["display_composite"], dz=7.5), comp_styles["display_composite"], 1.0),
        (translate_mesh(comps["xiao_sense_upward_mic"], dz=1.5), comp_styles["xiao_sense_upward_mic"], 1.0),
        (translate_mesh(comps["battery_803040"], dz=-2.0), comp_styles["battery_803040"], 1.0),
        (translate_mesh(comps["amp_max98357a"], dz=-9.0), comp_styles["amp_max98357a"], 1.0),
        (translate_mesh(comps["speaker_1510"], dz=-9.0), comp_styles["speaker_1510"], 1.0),
        (translate_mesh(cap_ptt, dy=8.0, dz=-16.0), (0.95, 0.78, 0.15), 1.0),
        (translate_mesh(cap_snap, dx=8.0, dz=-16.0), (0.95, 0.78, 0.15), 1.0),
        (translate_mesh(back, dz=-18.0), shell_back_rgb, 1.0),
    ]
    render_3d_scene(
        exploded_scene, elev=24, azim=-56,
        out_path=os.path.join(ren_dir, "exploded.png"),
        title="GOTCHI V1 (Rev 4) — Exploded Multi-Tier Stack",
        subtitle="Front Bezel -> Display + Forward Camera -> XIAO + 803040 Battery -> Amp + Speaker -> Back Shell"
    )

    # 6. top_labeled.png & 7. side_labeled.png
    generate_top_labeled(p, os.path.join(ren_dir, "top_labeled.png"))
    generate_side_labeled(p, os.path.join(ren_dir, "side_labeled.png"))
    print("All 7 renders completed successfully.")


if __name__ == "__main__":
    main()
