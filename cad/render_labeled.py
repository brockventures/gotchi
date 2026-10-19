#!/usr/bin/env python3
"""
render_labeled.py: True Per-Pixel Z-Buffer 3D Studio Renderer, 360° Turntable GIF Generator,
and Labeled Orthographic CAD Renderer for GOTCHI V1 (Rev 4).

Why True Per-Pixel Z-Buffer instead of matplotlib Poly3DCollection:
  - Matplotlib's Poly3DCollection uses a whole-triangle Painter's Algorithm (sorting triangles
    by a single average Z coordinate with no per-pixel depth buffer).
  - Boolean CSG meshes contain long diagonal triangles on outer walls/bezels whose centroid Z
    falls behind smaller internal cavity/underside triangles, causing internal faces to bleed
    through outer surfaces as diagonal triangle artifacts.
  - This renderer implements an exact per-pixel barycentric Z-buffer with back-face culling
    and 2x supersampled anti-aliasing (SSAA), completely eliminating triangle sorting artifacts.
"""

import argparse
import math
import os
import sys
import numpy as np
import trimesh
import matplotlib
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import build_case as bc


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


def build_view_matrix(elev_deg, azim_deg, roll_deg=0.0):
    """
    Build orthonormal 3x3 view rotation matrix mapping world (X, Y, Z) to camera (X_cam, Y_cam, Z_cam)
    where +X_cam is right, +Y_cam is up on screen, and +Z_cam points toward the camera.
    """
    el = math.radians(elev_deg)
    az = math.radians(azim_deg)
    # Camera look-from direction in world coordinates (Z_world is front/depth, Y_world is height, X_world is width)
    # Using Y_world as vertical up-axis for natural turntable rotation around Y_world:
    fx = math.cos(el) * math.sin(az)
    fy = math.sin(el)
    fz = math.cos(el) * math.cos(az)
    fwd = np.array([fx, fy, fz], dtype=np.float64)
    fwd /= np.linalg.norm(fwd)

    up_world = np.array([0.0, 1.0, 0.0], dtype=np.float64)
    if abs(np.dot(fwd, up_world)) > 0.999:
        up_world = np.array([0.0, 0.0, 1.0], dtype=np.float64)

    right = np.cross(up_world, fwd)
    right /= np.linalg.norm(right)
    up = np.cross(fwd, right)
    up /= np.linalg.norm(up)

    if abs(roll_deg) > 1e-5:
        rl = math.radians(roll_deg)
        c, s = math.cos(rl), math.sin(rl)
        r_new = c * right + s * up
        u_new = -s * right + c * up
        right, up = r_new, u_new

    return np.vstack([right, up, fwd])


def rasterize_scene_zbuffer(
    meshes_with_styles,
    elev_deg,
    azim_deg,
    width=700,
    height=700,
    ssaa=2,
    bg_rgb=(20, 24, 32),
    fixed_span=None,
    fixed_center=None,
):
    """
    Render a list of (trimesh.Trimesh, base_rgb_0to1) using a true per-pixel barycentric Z-buffer
    with back-face culling, 3-point studio lighting in camera space, and 2x supersampling.
    """
    W = width * ssaa
    H = height * ssaa

    R = build_view_matrix(elev_deg, azim_deg)

    # Collect transformed vertices, faces, and shaded RGB colors
    all_v_cam = []
    all_faces = []
    all_colors = []
    v_offset = 0

    # Studio lights in camera space (+X right, +Y up, +Z toward viewer)
    key_l = np.array([-0.42, 0.55, 0.72])
    key_l /= np.linalg.norm(key_l)
    fill_l = np.array([0.65, 0.20, 0.73])
    fill_l /= np.linalg.norm(fill_l)
    rim_l = np.array([0.0, -0.75, 0.66])
    rim_l /= np.linalg.norm(rim_l)
    half_v = np.array([-0.22, 0.30, 0.93])
    half_v /= np.linalg.norm(half_v)

    world_mins = []
    world_maxs = []
    for m, _ in meshes_with_styles:
        if not m.is_empty:
            world_mins.append(m.bounds[0])
            world_maxs.append(m.bounds[1])

    if fixed_center is not None:
        center_w = np.array(fixed_center, dtype=np.float64)
    else:
        bmin = np.min(world_mins, axis=0)
        bmax = np.max(world_maxs, axis=0)
        center_w = 0.5 * (bmin + bmax)

    for m, base_rgb in meshes_with_styles:
        if m.is_empty:
            continue
        v_cam = (m.vertices - center_w) @ R.T
        n_cam = m.face_normals @ R.T

        # Back-face culling: keep only triangles facing the camera (n_cam[:, 2] > -1e-4)
        front_mask = n_cam[:, 2] > -1e-4
        if not np.any(front_mask):
            continue

        faces_kept = m.faces[front_mask]
        n_kept = n_cam[front_mask]

        k = np.clip(n_kept @ key_l, 0.0, 1.0)
        f = np.clip(n_kept @ fill_l, 0.0, 1.0)
        r = np.clip(n_kept @ rim_l, 0.0, 1.0)
        spec = np.clip(n_kept @ half_v, 0.0, 1.0) ** 24

        intensity = 0.26 + 0.54 * k + 0.20 * f + 0.10 * r
        base = np.array(base_rgb, dtype=np.float64)
        rgb = np.clip(np.outer(intensity, base) + np.outer(0.14 * spec, np.ones(3)), 0.0, 1.0)
        rgb_u8 = (rgb * 255.0).astype(np.uint8)

        all_v_cam.append(v_cam)
        all_faces.append(faces_kept + v_offset)
        all_colors.append(rgb_u8)
        v_offset += len(v_cam)

    v_cam_all = np.vstack(all_v_cam)
    faces_all = np.vstack(all_faces)
    colors_all = np.vstack(all_colors)

    if fixed_span is not None:
        span = float(fixed_span)
    else:
        max_xy = np.max(np.abs(v_cam_all[:, :2]))
        span = max_xy * 2.25

    scale = min(W, H) / span
    px = v_cam_all[:, 0] * scale + (W * 0.5)
    py = -v_cam_all[:, 1] * scale + (H * 0.5)
    pz = v_cam_all[:, 2]

    # Allocate Z-buffer and RGB frame buffer
    zbuf = np.full((H, W), -1e18, dtype=np.float64)
    fbuf = np.empty((H, W, 3), dtype=np.uint8)
    fbuf[:, :] = bg_rgb

    # Subtle radial studio vignette on background
    yy_bg, xx_bg = np.ogrid[:H, :W]
    r2 = ((xx_bg - W * 0.5) / (W * 0.55)) ** 2 + ((yy_bg - H * 0.5) / (H * 0.55)) ** 2
    vig = np.clip(1.18 - 0.28 * r2, 0.72, 1.15)
    for c in range(3):
        fbuf[:, :, c] = np.clip(bg_rgb[c] * vig, 0, 255).astype(np.uint8)

    # Extract triangle vertex coordinates
    f0 = faces_all[:, 0]
    f1 = faces_all[:, 1]
    f2 = faces_all[:, 2]

    x0, y0, z0 = px[f0], py[f0], pz[f0]
    x1, y1, z1 = px[f1], py[f1], pz[f1]
    x2, y2, z2 = px[f2], py[f2], pz[f2]

    xmin = np.maximum(0, np.floor(np.minimum(np.minimum(x0, x1), x2)).astype(np.int32))
    xmax = np.minimum(W - 1, np.ceil(np.maximum(np.maximum(x0, x1), x2)).astype(np.int32))
    ymin = np.maximum(0, np.floor(np.minimum(np.minimum(y0, y1), y2)).astype(np.int32))
    ymax = np.minimum(H - 1, np.ceil(np.maximum(np.maximum(y0, y1), y2)).astype(np.int32))

    denom = (y1 - y2) * (x0 - x2) + (x2 - x1) * (y0 - y2)

    for i in range(len(faces_all)):
        d = denom[i]
        if abs(d) < 1e-6:
            continue
        x_lo, x_hi = xmin[i], xmax[i]
        y_lo, y_hi = ymin[i], ymax[i]
        if x_lo > x_hi or y_lo > y_hi:
            continue

        inv_d = 1.0 / d
        vx0, vy0, vz0 = x0[i], y0[i], z0[i]
        vx1, vy1, vz1 = x1[i], y1[i], z1[i]
        vx2, vy2, vz2 = x2[i], y2[i], z2[i]

        xs = np.arange(x_lo, x_hi + 1, dtype=np.float64) + 0.5
        ys = (np.arange(y_lo, y_hi + 1, dtype=np.float64) + 0.5)[:, None]

        w0 = ((vy1 - vy2) * (xs - vx2) + (vx2 - vx1) * (ys - vy2)) * inv_d
        w1 = ((vy2 - vy0) * (xs - vx2) + (vx0 - vx2) * (ys - vy2)) * inv_d
        w2 = 1.0 - w0 - w1

        inside = (w0 >= -1e-5) & (w1 >= -1e-5) & (w2 >= -1e-5)
        if not np.any(inside):
            continue

        z_pix = w0 * vz0 + w1 * vz1 + w2 * vz2
        sub_z = zbuf[y_lo : y_hi + 1, x_lo : x_hi + 1]
        closer = inside & (z_pix > sub_z)
        if np.any(closer):
            sub_z[closer] = z_pix[closer]
            sub_f = fbuf[y_lo : y_hi + 1, x_lo : x_hi + 1]
            sub_f[closer] = colors_all[i]

    im_ss = Image.fromarray(fbuf, mode="RGB")
    if ssaa > 1:
        im_ss = im_ss.resize((width, height), Image.Resampling.LANCZOS)
    return im_ss


def save_titled_render(im_body, out_path, title, subtitle):
    W, H = im_body.size
    header_h = 84
    canvas = Image.new("RGB", (W, H + header_h), (16, 20, 28))
    canvas.paste(im_body, (0, header_h))
    d = ImageDraw.Draw(canvas)
    f_title, f_sub, _, _ = load_fonts()
    d.text((28, 14), title, fill=(242, 246, 250), font=f_title)
    d.text((28, 50), subtitle, fill=(150, 185, 225), font=f_sub)
    canvas.save(out_path)
    print(f"Wrote {out_path}")


def translate_mesh(m, dx=0.0, dy=0.0, dz=0.0):
    c = m.copy()
    c.apply_translation([dx, dy, dz])
    return c


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
    """Generate high-resolution annotated Top/Front Internal Packaging CAD Diagram (X-Y plane)."""
    W, H = 1800, 1300
    im = Image.new("RGB", (W, H), (248, 250, 252))
    d = ImageDraw.Draw(im)
    f_title, f_sub, f_lbl, f_sm = load_fonts()

    d.rectangle([0, 0, W, 92], fill=(20, 26, 36))
    d.text((32, 16), "GOTCHI V1 (Rev 4) — Front / Top-Down Internal Packaging View (36.4 x 60.2 mm)", fill=(242, 246, 250), font=f_title)
    d.text((32, 54), "Forward-Firing Screen & Camera (+Z)  |  Upward-Pointing PDM Mic (+Y)  |  Non-Cubic Multi-Tier Stack (20.8 mm thin)", fill=(150, 185, 225), font=f_sub)

    cx_px, cy_px = W // 2, 705
    scale = 15.6

    def pt(x, y):
        return (int(round(cx_px + x * scale)), int(round(cy_px - y * scale)))

    def rect_mm(x0, y0, x1, y1):
        px0, py0 = pt(x0, y1)
        px1, py1 = pt(x1, y0)
        return [px0, py0, px1, py1]

    hw = p["W_out"] / 2.0
    iw = hw - p["wall"]

    d.rounded_rectangle(rect_mm(-hw, p["y_min"], hw, p["y_max"]), radius=int(2.8 * scale), fill=(226, 232, 240), outline=(45, 55, 72), width=4)
    d.rectangle(rect_mm(-iw, p["y_min"] + p["wall"], iw, p["y_max"] - p["wall"]), fill=(241, 245, 249), outline=(100, 116, 139), width=2)

    ax0, ax1 = p["amp_cx"] - p["amp_w"]/2, p["amp_cx"] + p["amp_w"]/2
    ay0, ay1 = p["amp_cy"] - p["amp_h"]/2, p["amp_cy"] + p["amp_h"]/2
    d.rectangle(rect_mm(ax0, ay0, ax1, ay1), fill=(216, 190, 245), outline=(107, 33, 168), width=3)
    d.text(pt(p["amp_cx"] - 7.5, p["amp_cy"] + 1.5), "MAX98357A Amp", fill=(76, 29, 149), font=f_sm)
    d.text(pt(p["amp_cx"] - 7.5, p["amp_cy"] - 1.5), "(z=-15.2..-18.2)", fill=(76, 29, 149), font=f_sm)

    sx0, sx1 = p["spk_cx"] - p["spk_w"]/2, p["spk_cx"] + p["spk_w"]/2
    sy0, sy1 = p["spk_cy"] - p["spk_h"]/2, p["spk_cy"] + p["spk_h"]/2
    d.rectangle(rect_mm(sx0, sy0, sx1, sy1), fill=(252, 202, 202), outline=(185, 28, 28), width=3)
    for ix in range(-2, 3):
        gx = p["spk_cx"] + ix * 2.6
        d.rectangle(rect_mm(gx - 0.5, p["spk_cy"] - 3.0, gx + 0.5, p["spk_cy"] + 3.0), fill=(153, 27, 27))

    bx0, by0, bx1, by1 = rect_mm(-p["bat_w"]/2, p["bat_y0"], p["bat_w"]/2, p["bat_y1"])
    draw_dashed_rect(d, bx0, by0, bx1, by1, (217, 119, 6), width=4, dash=14)

    dx0, dy0, dx1, dy1 = rect_mm(-p["disp_w"]/2, p["disp_y0"], p["disp_w"]/2, p["disp_y1"])
    draw_dashed_rect(d, dx0, dy0, dx1, dy1, (37, 99, 235), width=3, dash=10)

    d.rectangle(rect_mm(-p["ph20_w"]/2, p["ph20_y0"], p["ph20_w"]/2, p["ph20_y1"]), fill=(219, 234, 254), outline=(29, 78, 216), width=3)
    d.text(pt(-7.8, -21.5), "8-Pin PH2.0 Plug", fill=(30, 58, 138), font=f_sm)
    d.text(pt(-7.8, -23.8), "(below battery!)", fill=(30, 58, 138), font=f_sm)

    d.rectangle(rect_mm(-p["disp_fpc_w"]/2, p["disp_fpc_y0"], p["disp_fpc_w"]/2, p["disp_fpc_y1"]), fill=(254, 215, 170), outline=(194, 65, 12), width=2)
    d.text(pt(-6.8, 20.8), "Display FPC Fold", fill=(154, 52, 18), font=f_sm)

    wx0, wy0, wx1, wy1 = rect_mm(-p["win_w"]/2, p["win_cy"] - p["win_h"]/2, p["win_w"]/2, p["win_cy"] + p["win_h"]/2)
    d.rectangle([wx0, wy0, wx1, wy1], outline=(15, 23, 42), width=4)
    d.text(pt(-9.5, 14.5), "28x28 mm E-Paper Window (+Z)", fill=(15, 23, 42), font=f_sm)

    d.rectangle(rect_mm(p["xiao_x0"], p["xiao_y0"], p["xiao_x1"], p["xiao_y0"] + 4.0), fill=(187, 247, 208), outline=(21, 128, 61), width=3)
    d.rectangle(rect_mm(p["xiao_x0"] + 6.5, p["xiao_y0"] + 4.0, p["xiao_x1"], p["xiao_y1"]), fill=(134, 239, 172), outline=(22, 101, 52), width=3)
    d.text(pt(-15.5, 25.5), "XIAO ESP32S3 + Sense", fill=(20, 83, 45), font=f_sm)

    d.rectangle(rect_mm(p["mic_cx"] - 1.75, p["xiao_y1"], p["mic_cx"] + 1.75, p["xiao_y1"] + 0.9), fill=(250, 204, 21), outline=(161, 98, 7), width=2)
    d.rectangle(rect_mm(p["mic_cx"] - 1.1, p["y_max"] - p["wall"], p["mic_cx"] + 1.1, p["y_max"]), fill=(239, 68, 68), outline=(153, 27, 27), width=2)

    d.rectangle(rect_mm(p["xiao_x1"], p["cam_cy"] - 3.0, p["cam_cx"] - p["cam_w"]/2, p["cam_cy"] + 3.0), fill=(251, 146, 60), outline=(194, 65, 12), width=2)
    cx0, cy0, cx1, cy1 = rect_mm(p["cam_cx"] - p["cam_w"]/2, p["cam_cy"] - p["cam_h"]/2, p["cam_cx"] + p["cam_w"]/2, p["cam_cy"] + p["cam_h"]/2)
    d.rectangle([cx0, cy0, cx1, cy1], fill=(51, 65, 85), outline=(15, 23, 42), width=3)
    lcx, lcy = pt(p["cam_cx"], p["cam_cy"])
    lr = int((p["cam_lens_d"] / 2.0) * scale)
    d.ellipse([lcx - lr, lcy - lr, lcx + lr, lcy + lr], fill=(30, 41, 59), outline=(56, 189, 248), width=3)

    d.rectangle(rect_mm(p["ptt_cx"] - 3.0, p["y_max"] - p["wall"] - 2.0, p["ptt_cx"] + 3.0, p["y_max"] + 0.8), fill=(253, 224, 71), outline=(161, 98, 7), width=2)
    d.rectangle(rect_mm(iw - 2.0, p["snap_cy"] - 3.0, hw + 0.8, p["snap_cy"] + 3.0), fill=(253, 224, 71), outline=(161, 98, 7), width=2)
    d.rectangle(rect_mm(-hw - 0.5, p["usb_cy"] - p["usb_h"]/2, -iw + 0.5, p["usb_cy"] + p["usb_h"]/2), fill=(56, 189, 248), outline=(2, 132, 199), width=2)
    d.rectangle(rect_mm(-hw - 0.5, p["sw_cy"] - p["sw_slot_y"]/2, -iw + 1.5, p["sw_cy"] + p["sw_slot_y"]/2), fill=(45, 212, 191), outline=(15, 118, 110), width=2)

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
    """Generate high-resolution annotated Side Cross-Section CAD Diagram (Y-Z plane, 60.2 x 20.8 mm)."""
    W, H = 1920, 1200
    im = Image.new("RGB", (W, H), (248, 250, 252))
    d = ImageDraw.Draw(im)
    f_title, f_sub, f_lbl, f_sm = load_fonts()

    d.rectangle([0, 0, W, 92], fill=(20, 26, 36))
    d.text((32, 16), "GOTCHI V1 (Rev 4) — Side Cross-Section View (60.2 mm Height x 20.8 mm Depth)", fill=(242, 246, 250), font=f_title)
    d.text((32, 54), "Stepped Z-Stack: Battery Nestles Behind Flat Upper 40mm of Display PCB; Tall PH2.0 Plug Sits Below Battery", fill=(150, 185, 225), font=f_sub)

    cy_px = 910
    cz_px = 390
    scale = 10.6

    def pt(y, z):
        return (int(round(cy_px + y * scale)), int(round(cz_px - z * scale)))

    def rect_yz(y0, z0, y1, z1):
        px0, py0 = pt(y0, z1)
        px1, py1 = pt(y1, z0)
        return [px0, py0, px1, py1]

    d.rectangle(rect_yz(p["y_min"], p["split_z"], p["y_max"], 0.0), fill=(226, 232, 240), outline=(51, 65, 85), width=3)
    d.rectangle(rect_yz(p["y_min"], -p["D_out"], p["y_max"], p["split_z"]), fill=(203, 213, 225), outline=(30, 41, 59), width=3)
    d.rectangle(rect_yz(p["y_min"] + p["wall"], -p["D_out"] + p["back_wall"], p["y_max"] - p["wall"], -p["front_wall"]), fill=(248, 250, 252), outline=(148, 163, 184), width=2)

    sx0, sy0 = pt(p["y_min"] - 2.5, p["split_z"])
    sx1, sy1 = pt(p["y_max"] + 2.5, p["split_z"])
    draw_dashed_rect(d, sx0, sy0, sx1, sy1, (220, 38, 38), width=2, dash=10)

    d.rectangle(rect_yz(p["win_cy"] - p["win_h"]/2, -p["front_wall"], p["win_cy"] + p["win_h"]/2, 0.0), fill=(248, 250, 252), outline=(56, 189, 248), width=2)
    d.rectangle(rect_yz(p["disp_fpc_y0"] - 0.2, -2.6, p["disp_fpc_y1"] + 0.2, -0.8), fill=(254, 243, 199), outline=(217, 119, 6), width=2)

    d.rectangle(rect_yz(p["disp_glass_y0"], p["disp_glass_z1"], p["disp_glass_y1"], p["disp_glass_z0"]), fill=(147, 197, 253), outline=(29, 78, 216), width=2)
    d.rectangle(rect_yz(p["disp_y0"], p["disp_pcb_z1"], p["disp_y1"], p["disp_pcb_z0"]), fill=(59, 130, 246), outline=(30, 58, 138), width=2)
    d.rectangle(rect_yz(p["disp_fpc_y0"], p["disp_zif_z1"], p["disp_fpc_y1"], -0.9), fill=(251, 146, 60), outline=(154, 52, 18), width=2)
    d.rectangle(rect_yz(p["ph20_y0"], p["ph20_z1"], p["ph20_y1"], p["disp_pcb_z1"]), fill=(219, 234, 254), outline=(29, 78, 216), width=3)

    d.rectangle(rect_yz(p["bat_y0"], p["bat_z1"], p["bat_y1"], p["bat_z0"]), fill=(253, 230, 138), outline=(180, 83, 9), width=3)
    d.text(pt(-11.0, -9.2), "803040 LiPo Battery (8.0 mm)", fill=(146, 64, 14), font=f_sm)

    d.rectangle(rect_yz(p["amp_cy"] - p["amp_h"]/2, p["amp_z1"], p["amp_cy"] + p["amp_h"]/2, p["amp_z0"]), fill=(216, 180, 254), outline=(107, 33, 168), width=3)
    d.rectangle(rect_yz(p["spk_cy"] - p["spk_h"]/2, p["spk_z1"], p["spk_cy"] + p["spk_h"]/2, p["spk_z0"]), fill=(252, 165, 165), outline=(185, 28, 28), width=3)

    d.rectangle(rect_yz(p["xiao_y0"], p["xiao_z1"], p["xiao_y0"] + 4.0, p["xiao_z0"]), fill=(187, 247, 208), outline=(21, 128, 61), width=2)
    d.rectangle(rect_yz(p["xiao_y0"] + 4.0, p["xiao_z1"], p["xiao_y1"], p["xiao_z0"]), fill=(134, 239, 172), outline=(22, 101, 52), width=2)
    d.rectangle(rect_yz(p["xiao_y1"], p["mic_cz"] - 1.3, p["xiao_y1"] + 0.8, p["mic_cz"] + 1.3), fill=(250, 204, 21), outline=(161, 98, 7), width=2)
    d.rectangle(rect_yz(p["y_max"] - p["wall"], p["mic_cz"] - 1.1, p["y_max"], p["mic_cz"] + 1.1), fill=(239, 68, 68), outline=(153, 27, 27), width=2)

    # Rear slide-in groove & internal sealed reinforcement spine on back wall
    d.rectangle(rect_yz(p["slot_y_entry"] - 1.2, -p["D_out"] + p["back_wall"], p["slot_y_top"] + 1.5, p["slot_spine_z"]), fill=(203, 213, 225), outline=(51, 65, 85), width=2)
    d.rectangle(rect_yz(p["slot_y_entry"], -p["D_out"], p["slot_y_top"], p["slot_z_base"]), fill=(241, 245, 249), outline=(14, 116, 144), width=2)
    d.rectangle(rect_yz(p["slot_y_rail"], -p["D_out"], p["slot_y_top"], p["slot_z_neck"]), fill=(103, 232, 249), outline=(14, 116, 144), width=2)

    d.rectangle(rect_yz(p["cam_cy"] - p["cam_h"]/2, p["cam_z1"], p["cam_cy"] + p["cam_h"]/2, -2.8), fill=(51, 65, 85), outline=(15, 23, 42), width=3)
    d.rectangle(rect_yz(p["cam_cy"] - p["cam_lens_d"]/2, -2.8, p["cam_cy"] + p["cam_lens_d"]/2, 0.0), fill=(56, 189, 248), outline=(2, 132, 199), width=2)

    callouts = [
        ("Front Face (Z = 0.0 mm) + 28x28 E-Paper Window", pt(2.0, -0.7), "L", 160),
        ("Waveshare Glass + PCB Laminate (z = -1.45..-4.1 mm)", pt(-10.0, -3.3), "L", 250),
        ("8-Pin PH2.0 Plug (z = -4.1..-8.7 mm, below battery!)", pt(-22.2, -6.4), "L", 350),
        ("Front / Back Shell Split Plane (z = -8.8 mm)", pt(-27.2, -8.8), "L", 450),
        ("803040 LiPo Battery (z = -6.2..-14.2 mm, 8mm thick)", pt(-5.0, -10.2), "L", 550),
        ("MAX98357A Class-D Amp (z = -15.2..-18.2 mm)", pt(-2.0, -16.7), "L", 660),
        ("15x10x3.5mm Speaker + Rear Acoustic Slots", pt(-19.0, -17.5), "L", 770),
        ("Rear Twin-Rail Undercut Groove (Clip / Kickstand Slot)", pt(9.0, -20.0), "L", 880),

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


def generate_turntable_gif(assembled_scene, open_scene, out_gif_path, n_frames=30):
    """
    Generate a smooth 360-degree dual turntable GIF (Assembled Exterior on Left,
    Open Internal 3D Multi-Tier Stack on Right) using the true per-pixel Z-buffer engine.
    """
    _, f_sub, f_lbl, f_sm = load_fonts()
    frames = []
    center_w = [0.0, 2.9, -10.4]
    span_w = 72.0

    for idx in range(n_frames):
        azim = -35.0 + (360.0 * idx / n_frames)
        im_left = rasterize_scene_zbuffer(
            assembled_scene, elev_deg=22.0, azim_deg=azim,
            width=460, height=500, ssaa=2,
            fixed_span=span_w, fixed_center=center_w,
        )
        im_right = rasterize_scene_zbuffer(
            open_scene, elev_deg=22.0, azim_deg=azim,
            width=460, height=500, ssaa=2,
            fixed_span=span_w, fixed_center=center_w,
        )

        canvas = Image.new("RGB", (920, 576), (16, 20, 28))
        canvas.paste(im_left, (0, 76))
        canvas.paste(im_right, (460, 76))
        d = ImageDraw.Draw(canvas)
        d.line([(460, 76), (460, 576)], fill=(45, 55, 72), width=2)
        d.text((22, 12), "GOTCHI V1 (Rev 4) — 36.4 x 60.2 x 20.8 mm (Per-Pixel Z-Buffer 360° Turntable)", fill=(242, 246, 250), font=f_sub)
        d.text((22, 42), "Left: Assembled Case (+Z Screen & Cam, +Y Upward Mic)   |   Right: Internal Non-Cubic 3D Stack", fill=(148, 182, 224), font=f_sm)

        # Quantize with adaptive palette for clean GIF playback
        frames.append(canvas.quantize(colors=256, method=Image.Quantize.MEDIANCUT))

    frames[0].save(
        out_gif_path,
        save_all=True,
        append_images=frames[1:],
        duration=85,
        loop=0,
        optimize=False,
    )
    print(f"Wrote 360° turntable GIF ({n_frames} frames) to {out_gif_path}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=HERE)
    parser.add_argument("--gif", default=None)
    args, _ = parser.parse_known_args()

    ren_dir = os.path.join(os.path.abspath(args.out), "renders")
    os.makedirs(ren_dir, exist_ok=True)

    p = bc.P
    front = bc.build_front_shell()
    back = bc.build_back_shell()
    cap = bc.build_button_cap()
    comps = bc.build_internal_3d_components()

    cap_ptt = cap.copy()
    cap_ptt.apply_transform(trimesh.transformations.rotation_matrix(-math.pi / 2.0, [1, 0, 0]))
    cap_ptt.apply_translation([p["ptt_cx"], p["y_max"] - 2.2, p["ptt_cz"]])

    cap_snap = cap.copy()
    cap_snap.apply_transform(trimesh.transformations.rotation_matrix(math.pi / 2.0, [0, 1, 0]))
    cap_snap.apply_translation([p["W_out"] / 2.0 - 2.2, p["snap_cy"], p["snap_cz"]])

    shell_front_rgb = (0.86, 0.89, 0.93)
    shell_back_rgb = (0.26, 0.31, 0.39)
    comp_styles = {
        "display_composite": (0.20, 0.50, 0.94),
        "battery_803040": (0.94, 0.64, 0.14),
        "xiao_sense_upward_mic": (0.18, 0.78, 0.40),
        "camera_forward_flex": (0.96, 0.44, 0.16),
        "speaker_1510": (0.90, 0.26, 0.26),
        "amp_max98357a": (0.66, 0.34, 0.90),
    }

    assembled_scene = [
        (front, shell_front_rgb),
        (back, shell_back_rgb),
        (cap_ptt, (0.95, 0.78, 0.15)),
        (cap_snap, (0.95, 0.78, 0.15)),
        (comps["display_composite"], comp_styles["display_composite"]),
        (comps["camera_forward_flex"], (0.18, 0.24, 0.32)),
    ]

    open_scene = [
        (back, shell_back_rgb),
        (cap_ptt, (0.95, 0.78, 0.15)),
        (cap_snap, (0.95, 0.78, 0.15)),
    ]
    for cname, cm in comps.items():
        open_scene.append((cm, comp_styles[cname]))

    exploded_scene = [
        (translate_mesh(front, dz=18.0), shell_front_rgb),
        (translate_mesh(comps["camera_forward_flex"], dz=9.5), comp_styles["camera_forward_flex"]),
        (translate_mesh(comps["display_composite"], dz=7.5), comp_styles["display_composite"]),
        (translate_mesh(comps["xiao_sense_upward_mic"], dz=1.5), comp_styles["xiao_sense_upward_mic"]),
        (translate_mesh(comps["battery_803040"], dz=-2.0), comp_styles["battery_803040"]),
        (translate_mesh(comps["amp_max98357a"], dz=-9.0), comp_styles["amp_max98357a"]),
        (translate_mesh(comps["speaker_1510"], dz=-9.0), comp_styles["speaker_1510"]),
        (translate_mesh(cap_ptt, dy=8.0, dz=-16.0), (0.95, 0.78, 0.15)),
        (translate_mesh(cap_snap, dx=8.0, dz=-16.0), (0.95, 0.78, 0.15)),
        (translate_mesh(back, dz=-18.0), shell_back_rgb),
    ]

    # 1. front_iso.png
    im = rasterize_scene_zbuffer(assembled_scene, elev_deg=24, azim_deg=-35, width=900, height=820, ssaa=2)
    save_titled_render(
        im, os.path.join(ren_dir, "front_iso.png"),
        "GOTCHI V1 (Rev 4) — Front Isometric",
        "36.4 x 60.2 x 20.8 mm | Forward Screen & Camera (+Z) | Upward PDM Mic (+Y) | Left USB-C (-X)"
    )

    # 2. back_iso.png
    im = rasterize_scene_zbuffer(assembled_scene, elev_deg=24, azim_deg=145, width=900, height=820, ssaa=2)
    save_titled_render(
        im, os.path.join(ren_dir, "back_iso.png"),
        "GOTCHI V1 (Rev 4) — Back Isometric",
        "Flush Twin-Rail Slide-In Groove (Clip / Kickstand) | 4x M2 Corners | 5-Slot Speaker Grille"
    )

    # 3. front_straight.png
    im = rasterize_scene_zbuffer(assembled_scene, elev_deg=0, azim_deg=0, width=900, height=820, ssaa=2)
    save_titled_render(
        im, os.path.join(ren_dir, "front_straight.png"),
        "GOTCHI V1 (Rev 4) — Front Orthographic",
        "Slim 4.2 mm Side Bezels | 28x28 mm E-Paper Window | Upper-Right Forward Camera Aperture"
    )

    # 4. back_layout.png
    im = rasterize_scene_zbuffer(open_scene, elev_deg=26, azim_deg=-35, width=900, height=820, ssaa=2)
    save_titled_render(
        im, os.path.join(ren_dir, "back_layout.png"),
        "GOTCHI V1 (Rev 4) — Internal 3D Multi-Tier Packaging",
        "Blue: Display+PH2.0 | Orange: Forward Cam+90° FPC | Green: Horizontal XIAO+Upward Mic | Gold: 803040 LiPo"
    )

    # 5. exploded.png
    im = rasterize_scene_zbuffer(exploded_scene, elev_deg=22, azim_deg=-38, width=900, height=820, ssaa=2)
    save_titled_render(
        im, os.path.join(ren_dir, "exploded.png"),
        "GOTCHI V1 (Rev 4) — Exploded Multi-Tier Stack",
        "Front Bezel -> Display + Forward Camera -> XIAO + 803040 Battery -> Amp + Speaker -> Back Shell"
    )

    # 6. top_labeled.png & 7. side_labeled.png
    generate_top_labeled(p, os.path.join(ren_dir, "top_labeled.png"))
    generate_side_labeled(p, os.path.join(ren_dir, "side_labeled.png"))

    if args.gif:
        generate_turntable_gif(assembled_scene, open_scene, args.gif, n_frames=30)

    print("All renders completed successfully.")


if __name__ == "__main__":
    main()
