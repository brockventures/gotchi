"""render_labeled.py: labelled top-down and side views of the GOTCHI V1 case.

Run after build_case.py (it reads cad/gotchi_case.blend and the P dict in build_case.py):

    blender -b --python cad/render_labeled.py -- --out cad

Writes cad/renders/top_labeled.png and cad/renders/side_labeled.png.
Labels are drawn with Pillow, which must be importable by Blender's Python
(true for the Ubuntu `blender` package; a bundled Blender may need `pip install pillow`).

Top view: looking at the case from the front with the front half removed and the back half
cut just behind the display plate, so the parts in the back bay are visible. The display
and battery are drawn as dashed outlines because they would hide everything under them.

Side view: a section through x = 0, seen from the right-hand side. Front of the case is on
the left.
"""
import ast
import math
import os
import sys

import bmesh
import bpy
from mathutils import Vector

HERE = os.path.dirname(os.path.abspath(__file__))
RES = 1200


def load_params():
    src = open(os.path.join(HERE, 'build_case.py')).read()
    for node in ast.parse(src).body:
        if isinstance(node, ast.Assign) and getattr(node.targets[0], 'id', None) == 'P':
            return ast.literal_eval(node.value.args[0]) if node.value.args else {
                kw.arg: ast.literal_eval(kw.value) for kw in node.value.keywords}
    raise SystemExit('P not found in build_case.py')


P = load_params()


def box_obj(name, x0, x1, y0, y1, z0, z1, rgb=None):
    bm = bmesh.new()
    vs = [bm.verts.new((x, y, z)) for x in (x0, x1) for y in (y0, y1) for z in (z0, z1)]
    bmesh.ops.convex_hull(bm, input=vs)
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    ob = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(ob)
    if rgb:
        mat = bpy.data.materials.new(name + '_m')
        mat.use_nodes = True
        mat.node_tree.nodes['Principled BSDF'].inputs['Base Color'].default_value = (*rgb, 1)
        ob.data.materials.append(mat)
    return ob


def cut(target, x0, x1, y0, y1, z0, z1):
    """Return a copy of target with the given box removed."""
    ob = target.copy()
    ob.data = target.data.copy()
    bpy.context.scene.collection.objects.link(ob)
    cutter = box_obj('cutter', x0, x1, y0, y1, z0, z1)
    m = ob.modifiers.new('cut', 'BOOLEAN')
    m.operation = 'DIFFERENCE'
    m.solver = 'EXACT'
    m.object = cutter
    bpy.context.view_layer.objects.active = ob
    bpy.ops.object.modifier_apply(modifier=m.name)
    bpy.data.objects.remove(cutter, do_unlink=True)
    return ob


def parts():
    p = P
    out = {}
    out['xiao'] = box_obj('xiao', -10.5, 10.5, p['xiao_cy'] - 8.9, p['xiao_cy'] + 8.9,
                          p['xiao_z_front'] - p['xiao_d'], p['xiao_z_front'], (0.2, 0.75, 0.3))
    out['battery'] = box_obj('battery', -15, 15, p['bat_cy'] - 20, p['bat_cy'] + 20,
                             -12.2 - p['bat_d'], -12.2, (0.9, 0.6, 0.1))
    out['display'] = box_obj('display', -16.5, 16.5, p['disp_cy'] - 24, p['disp_cy'] + 24,
                             -2.0 - p['disp_d'], -2.0, (0.2, 0.45, 0.9))
    sx, sy = p['spk_cx'], p['spk_cy']
    out['speaker'] = box_obj('speaker', sx - 7.5, sx + 7.5, sy - 5, sy + 5, -27, -27 + p['spk_d'],
                             (0.85, 0.2, 0.2))
    ax, ay = p['amp_cx'], p['amp_cy']
    out['amp'] = box_obj('amp', ax - 9.5, ax + 9.5, ay - 8.9, ay + 8.9, -27, -23, (0.6, 0.25, 0.85))
    for i, bx in enumerate((-p['btn_x'], p['btn_x'])):
        out[f'btn{i}'] = box_obj(f'btn{i}', bx - 3, bx + 3, 28.0, 31.5,
                                 p['btn_cz'] - 3, p['btn_cz'] + 3, (0.95, 0.85, 0.2))
    out['switch'] = box_obj('switch', -17, -13, p['sw_cy'] - 1.75, p['sw_cy'] + 1.75,
                            p['sw_cz'] - 4.3, p['sw_cz'] + 4.3, (0.1, 0.85, 0.9))
    return out


def setup(cam_loc, cam_target, scale):
    scene = bpy.context.scene
    scene.render.engine = 'CYCLES'
    scene.cycles.device = 'CPU'
    scene.cycles.samples = 24
    scene.cycles.use_denoising = False
    scene.view_settings.view_transform = 'Standard'
    scene.render.resolution_x = scene.render.resolution_y = RES
    world = bpy.data.worlds.new('bg')
    world.use_nodes = False
    world.color = (0.9, 0.9, 0.92)
    scene.world = world
    if 'sun' not in bpy.data.objects:
        sd = bpy.data.lights.new('sun', 'SUN')
        sd.energy = 3.0
        sun = bpy.data.objects.new('sun', sd)
        scene.collection.objects.link(sun)
        sun.rotation_euler = (math.radians(30), math.radians(20), math.radians(30))
    cd = bpy.data.cameras.new('cam')
    cd.type = 'ORTHO'
    cd.ortho_scale = scale
    cd.clip_end = 2000
    cam = bpy.data.objects.new('cam', cd)
    scene.collection.objects.link(cam)
    cam.location = Vector(cam_loc)
    d = Vector(cam_target) - Vector(cam_loc)
    cam.rotation_euler = d.to_track_quat('-Z', 'Y').to_euler()
    scene.camera = cam
    return scene, cam


def render(scene, path, visible):
    for ob in bpy.data.objects:
        if ob.type == 'MESH':
            ob.hide_render = ob.name not in visible
    scene.render.filepath = path
    bpy.ops.render.render(write_still=True)


def annotate(path, labels, outlines, title):
    from PIL import Image, ImageDraw, ImageFont
    im = Image.open(path).convert('RGB')
    pad_l, pad_r = 330, 330
    canvas = Image.new('RGB', (im.width + pad_l + pad_r, im.height + 70), (255, 255, 255))
    canvas.paste(im, (pad_l, 70))
    d = ImageDraw.Draw(canvas)
    font = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', 24,
                              layout_engine=ImageFont.Layout.BASIC)
    bold = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf', 30,
                              layout_engine=ImageFont.Layout.BASIC)
    d.text((20, 18), title, fill=(20, 20, 20), font=bold)
    off = (pad_l, 70)
    for (x0, y0, x1, y1), rgb in outlines:
        x0, x1 = sorted((x0 + off[0], x1 + off[0]))
        y0, y1 = sorted((y0 + off[1], y1 + off[1]))
        for a, b in (((x0, y0), (x1, y0)), ((x1, y0), (x1, y1)), ((x1, y1), (x0, y1)),
                     ((x0, y1), (x0, y0))):
            n = int(max(abs(b[0] - a[0]), abs(b[1] - a[1])) // 12) or 1
            for i in range(0, n, 2):
                p0 = (a[0] + (b[0] - a[0]) * i / n, a[1] + (b[1] - a[1]) * i / n)
                p1 = (a[0] + (b[0] - a[0]) * (i + 1) / n, a[1] + (b[1] - a[1]) * (i + 1) / n)
                d.line([p0, p1], fill=rgb, width=4)
    for text, (px, py), side, ty in labels:
        ax, ay = px + off[0], py + off[1]
        ty = ty + off[1]
        if side == 'L':
            tx = 15
            w = d.textlength(text, font=font)
            end = (tx + w + 8, ty + 12)
        else:
            tx = canvas.width - pad_r + 15
            end = (tx - 8, ty + 12)
        d.line([end, (ax, ay)], fill=(60, 60, 60), width=2)
        d.ellipse([ax - 5, ay - 5, ax + 5, ay + 5], fill=(200, 30, 30))
        d.text((tx, ty), text, fill=(20, 20, 20), font=font)
    canvas.save(path)


def main():
    argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
    out = argv[argv.index('--out') + 1] if '--out' in argv else HERE
    ren = os.path.join(os.path.abspath(out), 'renders')
    os.makedirs(ren, exist_ok=True)
    bpy.ops.wm.open_mainfile(filepath=os.path.join(os.path.abspath(out), 'gotchi_case.blend'))
    p = P
    front, back = bpy.data.objects['front'], bpy.data.objects['back']
    front.location = back.location = (0, 0, 0)
    pr = parts()

    # ---------------- top view (from the front, front half off, back cut behind plate)
    S = 90.0
    k = RES / S

    def top_px(x, y):
        return (RES / 2 + x * k, RES / 2 - y * k)

    back_top = cut(back, -30, 30, -40, 40, -12.25, 1)
    scene, cam = setup((0, 0, 150), (0, 0, 0), S)
    vis = {back_top.name, 'xiao', 'speaker', 'amp', 'btn0', 'btn1', 'switch'}
    path = os.path.join(ren, 'top_labeled.png')
    render(scene, path, vis)
    dx0, dy0 = top_px(-16.5, p['disp_cy'] + 24)
    dx1, dy1 = top_px(16.5, p['disp_cy'] - 24)
    bx0, by0 = top_px(-15, p['bat_cy'] + 20)
    bx1, by1 = top_px(15, p['bat_cy'] - 20)
    labels = [
        ('Button 1: push-to-talk', top_px(-p['btn_x'], 31), 'L', 60),
        ('Display outline (front half)', top_px(-16.5, 18), 'L', 230),
        ('Battery outline 40x30', top_px(-15, 0), 'L', 420),
        ('Amp MAX98357A', top_px(p['amp_cx'] - 4, p['amp_cy']), 'L', 560),
        ('Power switch (left wall)', top_px(-18.5, p['sw_cy']), 'L', 790),
        ('USB-C (bottom wall)', top_px(-3, -35), 'L', 1000),
        ('Button 2: mode', top_px(p['btn_x'], 31), 'R', 60),
        ('Speaker (grille in back)', top_px(p['spk_cx'] + 4, p['spk_cy']), 'R', 250),
        ('M2 screw boss (x4)', top_px(p['boss_x'], p['boss_y'] - 62), 'R', 900),
        ('XIAO ESP32S3 Sense', top_px(6, p['xiao_cy'] + 4), 'R', 700),
        ('Camera + mic (back wall)', top_px(p['cam_cx'] + 2, p['cam_cy']), 'R', 800),
    ]
    annotate(path, labels, [((dx0, dy0, dx1, dy1), (40, 90, 220)),
                            ((bx0, by0, bx1, by1), (220, 140, 20))],
             'GOTCHI V1: top-down, front half removed (38 x 72 mm)')
    print('wrote', path)
    bpy.data.objects.remove(bpy.data.objects['cam'], do_unlink=True)

    # ---------------- side view (section at x = 0, seen from +X; front on the left)
    cz = -14.5
    S2 = 90.0
    k2 = RES / S2

    def side_px(y, z):
        # camera on +X looking -X: case height (Y) runs left-right, depth (Z) top-down
        return (RES / 2 + y * k2, RES / 2 - (z - cz) * k2)

    front_s = cut(front, 0, 30, -40, 40, -40, 5)
    back_s = cut(back, 0, 30, -40, 40, -40, 5)
    scene, cam = setup((150, 0, cz), (0, 0, cz), S2)
    vis = {front_s.name, back_s.name, 'xiao', 'battery', 'display', 'speaker', 'amp', 'btn0',
           'btn1'}
    path = os.path.join(ren, 'side_labeled.png')
    render(scene, path, vis)
    labels = [
        ('Front face + display window', side_px(p['disp_cy'] - 8, -1.0), 'L', 380),
        ('Front | back half split', side_px(-34.0, p['split_z']), 'L', 500),
        ('USB-C slot (bottom end)', side_px(-35.0, p['usb_cz']), 'L', 600),
        ('XIAO ESP32S3 Sense', side_px(p['xiao_cy'], -19), 'L', 700),
        ('Camera + mic (back wall)', side_px(p['cam_cy'], -28.0), 'L', 820),
        ('Display module', side_px(p['disp_cy'] + 8, -6.5), 'R', 380),
        ('Display plate', side_px(22, -11.6), 'R', 470),
        ('Battery 803040', side_px(8, -16), 'R', 560),
        ('Buttons (top end)', side_px(31, p['btn_cz']), 'R', 650),
        ('Amp', side_px(p['amp_cy'], -25), 'R', 760),
        ('Speaker + grille', side_px(p['spk_cy'], -25.5), 'R', 850),
    ]
    annotate(path, labels, [], 'GOTCHI V1: side section at centre line, front face at top (72 x 29 mm)')
    print('wrote', path)


main()
