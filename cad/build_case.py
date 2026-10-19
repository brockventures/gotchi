"""GOTCHI V1 case: parametric two-part shell + button cap.

Headless run (from repo root):
    blender -b --python cad/build_case.py -- --out cad

Outputs under <out>/: stl/gotchi_front.stl, stl/gotchi_back.stl,
stl/gotchi_button_cap.stl, gotchi_case.blend, renders/{front_iso,back_iso,exploded}.png

Units: 1 Blender unit = 1 mm. X = width, Y = height (+Y top), Z = depth.
Front face z=0, back face z=-27. Parameters: see P below (decided values, do not tune here).
Exits non-zero on any Python error or any non-manifold edge.
"""
import math
import os
import sys

import bmesh
import bpy
from mathutils import Matrix, Vector

P = dict(
    wall=2.0,
    W_out=38.0, H_out=72.0, D_out=27.0,
    W_in=34.0, H_in=68.0,
    split_z=-9.0,
    edge_bevel=2.0, bevel_segments=6,
    disp_w=33.0, disp_h=48.0, disp_d=7.0, disp_cy=4.0,
    win_w=28.4, win_h=28.4, win_off_x=0.0, win_off_y=0.0,
    plate_t=1.2, plate_y_top=28.0, plate_y_bot=-14.0,
    bat_w=30.0, bat_h=40.0, bat_d=7.8, bat_cy=7.0,
    xiao_w=21.0, xiao_h=17.8, xiao_d=15.0, xiao_cy=-24.1, xiao_z_front=-3.0,
    usb_w=10.0, usb_h=4.5, usb_cz=-4.6,
    cam_hole_d=9.0, cam_cx=0.0, cam_cy=-24.0,
    boss_d=5.0, boss_x=14.5, boss_y=31.0, pilot_d=1.7, clear_d=2.4,
    cbore_d=4.2, cbore_depth=1.5,
    btn_x=8.0, btn_cz=-16.0, btn_hole_d=3.8,
    sw_cy=-24.0, sw_cz=-16.0, sw_slot_z=5.0, sw_slot_y=2.0,
    spk_cx=9.0, spk_cy=20.0, spk_w=15.4, spk_h=10.4, spk_d=3.5,
    grille_d=1.5, grille_nx=4, grille_ny=3, grille_pitch=3.0,
    amp_cx=-6.0, amp_cy=5.0,
)

CYL_SEG = 48
BOOL_SOLVER = 'EXACT'
CAP_FLANGE_D, CAP_FLANGE_H = 5.5, 1.0
CAP_STEM_D, CAP_STEM_H = 3.4, 3.0


# ---------------------------------------------------------------- helpers

def fail(msg):
    print("FAIL:", msg, flush=True)
    os._exit(1)


def scene_link(ob):
    bpy.context.scene.collection.objects.link(ob)
    return ob


def bm_to_obj(name, bm):
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    return scene_link(bpy.data.objects.new(name, me))


def add_box(bm, x0, x1, y0, y1, z0, z1):
    n0 = len(bm.verts)
    bmesh.ops.create_cube(bm, size=1.0)
    new = list(bm.verts)[n0:]
    mat = Matrix.Translation(((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2)) @ \
        Matrix.Diagonal((x1 - x0, y1 - y0, z1 - z0, 1.0))
    bmesh.ops.transform(bm, matrix=mat, verts=new)
    return bm


def add_cyl(bm, r, p0, p1, seg=CYL_SEG):
    """Cylinder from p0 to p1. Rotated by half a segment about its own axis so no
    tessellation vertex sits exactly on a tangent line of an adjacent wall."""
    p0, p1 = Vector(p0), Vector(p1)
    d = p1 - p0
    n0 = len(bm.verts)
    bmesh.ops.create_cone(bm, cap_ends=True, cap_tris=False, segments=seg,
                          radius1=r, radius2=r, depth=d.length)
    new = list(bm.verts)[n0:]
    half = Matrix.Rotation(math.pi / seg, 4, 'Z')
    align = Vector((0, 0, 1)).rotation_difference(d.normalized()).to_matrix().to_4x4()
    mat = Matrix.Translation((p0 + p1) / 2) @ align @ half
    bmesh.ops.transform(bm, matrix=mat, verts=new)
    return bm


def bevel_all(bm, offset, segments):
    bmesh.ops.bevel(bm, geom=list(bm.edges), offset=offset, offset_type='OFFSET',
                    segments=segments, profile=0.5, affect='EDGES', clamp_overlap=True)


def bool_op(target, operand, operation):
    mod = target.modifiers.new(name='bool', type='BOOLEAN')
    mod.operation = operation
    mod.operand_type = 'OBJECT'
    mod.object = operand
    mod.solver = BOOL_SOLVER
    bpy.context.view_layer.objects.active = target
    bpy.ops.object.modifier_apply(modifier=mod.name)
    bpy.data.objects.remove(operand, do_unlink=True)


def subtract(target, bm):
    bool_op(target, bm_to_obj(target.name + '_cut', bm), 'DIFFERENCE')


def union(target, bm):
    bool_op(target, bm_to_obj(target.name + '_add', bm), 'UNION')


def nonmanifold_count(ob):
    bm = bmesh.new()
    bm.from_mesh(ob.data)
    bm.edges.ensure_lookup_table()
    nm = sum(1 for e in bm.edges if not e.is_manifold)
    nv = len(bm.verts)
    bm.free()
    return nv, nm


def bbox_of(ob):
    xs = [v.co.x for v in ob.data.vertices]
    ys = [v.co.y for v in ob.data.vertices]
    zs = [v.co.z for v in ob.data.vertices]
    return max(xs) - min(xs), max(ys) - min(ys), max(zs) - min(zs)


def print_copy(src, name, flip_x_pi):
    """Bake print orientation into a fresh mesh at identity transform.
    flip_x_pi: rotate 180 deg about X so the z=0 face goes to the bed (front)."""
    bm = bmesh.new()
    bm.from_mesh(src.data)
    if flip_x_pi:
        bmesh.ops.transform(bm, matrix=Matrix.Rotation(math.pi, 4, 'X'), verts=list(bm.verts))
    minz = min(v.co.z for v in bm.verts)
    bmesh.ops.translate(bm, vec=(0.0, 0.0, -minz), verts=list(bm.verts))
    return bm_to_obj(name, bm)


def export_stl(ob, path):
    for o in bpy.context.scene.objects:
        o.select_set(False)
    ob.select_set(True)
    bpy.context.view_layer.objects.active = ob
    try:
        bpy.ops.wm.stl_export(filepath=path, export_selected_objects=True, global_scale=1.0)
        used = 'wm.stl_export'
    except AttributeError:
        bpy.ops.export_mesh.stl(filepath=path, use_selection=True, global_scale=1.0)
        used = 'export_mesh.stl'
    print(f"  exported {os.path.basename(path)} via {used}", flush=True)


def check_part(label, ob):
    nv, nm = nonmanifold_count(ob)
    dx, dy, dz = bbox_of(ob)
    print(f"{label}: verts={nv} nonmanifold={nm} bbox={dx:.2f},{dy:.2f},{dz:.2f}", flush=True)
    return nm


# ---------------------------------------------------------------- parts

def build_front():
    p = P
    hw, hh = p['W_out'] / 2, p['H_out'] / 2
    bm = add_box(bmesh.new(), -hw, hw, -hh, hh, p['split_z'], 0.0)
    bevel_all(bm, p['edge_bevel'], p['bevel_segments'])
    part = bm_to_obj('front', bm)

    iw, ih = p['W_in'] / 2, p['H_in'] / 2
    # shell cavity, open at split face
    subtract(part, add_box(bmesh.new(), -iw, iw, -ih, ih, -9.0001, -2.0))

    # --- unions (features) ---
    rib = bmesh.new()
    add_box(rib, -17.0, 17.0, 28.3, 29.8, -9.0, -2.0)      # display stop, top
    add_box(rib, -17.0, 17.0, -21.8, -20.3, -9.0, -2.0)    # display stop, bottom
    union(part, rib)

    # Boss top is embedded 0.01 mm into the front wall (z=-1.99, not -2.0). An exactly
    # coplanar top face against the wall underside gives one non-manifold edge per boss
    # under EXACT union. Geometrically negligible; see README "solver notes".
    bosses = bmesh.new()
    for sx in (-1, 1):
        for sy in (-1, 1):
            add_cyl(bosses, p['boss_d'] / 2,
                    (sx * p['boss_x'], sy * p['boss_y'], -1.99),
                    (sx * p['boss_x'], sy * p['boss_y'], -9.0))
    union(part, bosses)

    # --- holes last: one cutter per boolean (combined multi-shell operands gave bad results) ---
    cutters = []
    # display window through front wall
    wx = p['win_w'] / 2
    wy = 4.0 + p['win_off_y']
    cutters.append(add_box(bmesh.new(), p['win_off_x'] - wx, p['win_off_x'] + wx,
                           wy - p['win_h'] / 2, wy + p['win_h'] / 2, -2.5, 1.0))
    # pilot holes, depth 6.0 from split face toward front
    for sx in (-1, 1):
        for sy in (-1, 1):
            cutters.append(add_cyl(bmesh.new(), p['pilot_d'] / 2,
                                   (sx * p['boss_x'], sy * p['boss_y'], -9.5),
                                   (sx * p['boss_x'], sy * p['boss_y'], -3.0)))
    # USB-C slot through bottom wall
    uw, uh = p['usb_w'] / 2, p['usb_h'] / 2
    cutters.append(add_box(bmesh.new(), -uw, uw, -37.0, -33.5,
                           p['usb_cz'] - uh, p['usb_cz'] + uh))
    for c in cutters:
        subtract(part, c)
    return part


def build_back():
    p = P
    hw, hh = p['W_out'] / 2, p['H_out'] / 2
    bm = add_box(bmesh.new(), -hw, hw, -hh, hh, -27.0, p['split_z'])
    bevel_all(bm, p['edge_bevel'], p['bevel_segments'])
    part = bm_to_obj('back', bm)

    iw, ih = p['W_in'] / 2, p['H_in'] / 2
    subtract(part, add_box(bmesh.new(), -iw, iw, -ih, ih, -25.0, -8.9999))

    # display plate
    plate = add_box(bmesh.new(), -17.0, 17.0, p['plate_y_bot'], p['plate_y_top'], -10.2, -9.0)
    union(part, plate)

    # screw bosses (solid here, clearance bored at the end)
    bosses = bmesh.new()
    for sx in (-1, 1):
        for sy in (-1, 1):
            add_cyl(bosses, p['boss_d'] / 2,
                    (sx * p['boss_x'], sy * p['boss_y'], -9.0),
                    (sx * p['boss_x'], sy * p['boss_y'], -25.0))
    union(part, bosses)

    # XIAO side ribs: 1.2 thick in X, centred x = +/-11.4
    ribs = bmesh.new()
    for cx in (11.4, -11.4):
        add_box(ribs, cx - 0.6, cx + 0.6, -34.0, -14.0, -21.0, -9.0)
    union(part, ribs)

    # button sockets: square tube 6.4 x 6.4 inner, wall 1.0, y +28..+34
    for bx in (-p['btn_x'], p['btn_x']):
        cz = p['btn_cz']
        outer = add_box(bmesh.new(), bx - 4.2, bx + 4.2, 28.0, 34.0, cz - 4.2, cz + 4.2)
        tube = bm_to_obj('btn_tube', outer)
        inner = add_box(bmesh.new(), bx - 3.2, bx + 3.2, 27.0, 35.0, cz - 3.2, cz + 3.2)
        bool_op(tube, bm_to_obj('btn_tube_void', inner), 'DIFFERENCE')
        bool_op(part, tube, 'UNION')

    # slide switch frame on inside of left wall: inner 9.0 (Z) x 3.9 (Y), wall 1.0
    sy_c, sz_c = p['sw_cy'], p['sw_cz']
    outer = add_box(bmesh.new(), -17.0, -13.0, sy_c - 2.95, sy_c + 2.95,
                    sz_c - 5.5, sz_c + 5.5)
    frame = bm_to_obj('sw_frame', outer)
    inner = add_box(bmesh.new(), -18.0, -12.0, sy_c - 1.95, sy_c + 1.95,
                    sz_c - 4.5, sz_c + 4.5)
    bool_op(frame, bm_to_obj('sw_void', inner), 'DIFFERENCE')
    bool_op(part, frame, 'UNION')

    # speaker pocket frame on inside of back wall: inner 15.4 x 10.4, wall 1.0, z -25..-21.5
    scx, scy = p['spk_cx'], p['spk_cy']
    ow, oh = p['spk_w'] / 2 + 1.0, p['spk_h'] / 2 + 1.0
    outer = add_box(bmesh.new(), scx - ow, scx + ow, scy - oh, scy + oh, -25.0, -21.5)
    spk = bm_to_obj('spk_frame', outer)
    iw2, ih2 = p['spk_w'] / 2, p['spk_h'] / 2
    inner = add_box(bmesh.new(), scx - iw2, scx + iw2, scy - ih2, scy + ih2, -26.0, -21.0)
    bool_op(spk, bm_to_obj('spk_void', inner), 'DIFFERENCE')
    bool_op(part, spk, 'UNION')

    # --- holes last: one cutter per boolean ---
    cutters = []
    for sx in (-1, 1):
        for sy in (-1, 1):
            bx, by = sx * p['boss_x'], sy * p['boss_y']
            cutters.append(add_cyl(bmesh.new(), p['clear_d'] / 2, (bx, by, -27.5), (bx, by, -8.5)))
            cutters.append(add_cyl(bmesh.new(), p['cbore_d'] / 2, (bx, by, -27.5),
                                   (bx, by, -27.0 + p['cbore_depth'])))
    cutters.append(add_cyl(bmesh.new(), p['cam_hole_d'] / 2, (p['cam_cx'], p['cam_cy'], -27.5),
                           (p['cam_cx'], p['cam_cy'], -24.5)))
    for bx in (-p['btn_x'], p['btn_x']):
        cutters.append(add_cyl(bmesh.new(), p['btn_hole_d'] / 2, (bx, 33.5, p['btn_cz']),
                               (bx, 36.5, p['btn_cz'])))
    # lever slot through left wall
    cutters.append(add_box(bmesh.new(), -19.5, -16.5, sy_c - p['sw_slot_y'] / 2,
                           sy_c + p['sw_slot_y'] / 2, sz_c - p['sw_slot_z'] / 2,
                           sz_c + p['sw_slot_z'] / 2))
    # speaker grille through back wall, centred on pocket
    for i in range(p['grille_nx']):
        for j in range(p['grille_ny']):
            gx = scx + (i - (p['grille_nx'] - 1) / 2) * p['grille_pitch']
            gy = scy + (j - (p['grille_ny'] - 1) / 2) * p['grille_pitch']
            cutters.append(add_cyl(bmesh.new(), p['grille_d'] / 2, (gx, gy, -27.5), (gx, gy, -24.5)))
    for c in cutters:
        subtract(part, c)
    return part


def build_cap():
    bm = bmesh.new()
    add_cyl(bm, CAP_FLANGE_D / 2, (0, 0, 0.0), (0, 0, CAP_FLANGE_H))
    cap = bm_to_obj('button_cap', bm)
    stem = bmesh.new()
    add_cyl(stem, CAP_STEM_D / 2, (0, 0, CAP_FLANGE_H - 0.01), (0, 0, CAP_FLANGE_H + CAP_STEM_H))
    union(cap, stem)
    return cap


# ---------------------------------------------------------------- render

def make_material(name, rgb):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    mat.node_tree.nodes['Principled BSDF'].inputs['Base Color'].default_value = (*rgb, 1.0)
    return mat


def setup_scene():
    scene = bpy.context.scene
    scene.render.engine = 'CYCLES'
    scene.cycles.device = 'CPU'
    scene.cycles.samples = 32
    scene.cycles.use_denoising = False  # this Blender build has no OpenImageDenoiser
    scene.view_settings.view_transform = 'Standard'  # AgX would tone the white background grey
    scene.view_settings.look = 'None'
    scene.render.resolution_x = 900
    scene.render.resolution_y = 900
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = 'PNG'
    world = bpy.data.worlds.new('white')
    world.use_nodes = False
    world.color = (1.0, 1.0, 1.0)
    scene.world = world
    sun_data = bpy.data.lights.new('sun', 'SUN')
    sun_data.energy = 3.0
    sun = scene_link(bpy.data.objects.new('sun', sun_data))
    sun.rotation_euler = (math.radians(45), 0.0, math.radians(30))
    cam_data = bpy.data.cameras.new('cam')
    cam = scene_link(bpy.data.objects.new('cam', cam_data))
    scene.camera = cam
    return scene, cam


def look_at(cam, loc, target):
    cam.location = Vector(loc)
    d = Vector(target) - Vector(loc)
    cam.rotation_euler = d.to_track_quat('-Z', 'Y').to_euler()


def render(scene, cam, path, visible, loc, target):
    for ob in bpy.data.objects:
        if ob.type == 'MESH':
            ob.hide_render = ob.name not in visible
    look_at(cam, loc, target)
    scene.render.filepath = os.path.abspath(path)
    bpy.ops.render.render(write_still=True)
    print(f"  rendered {path}", flush=True)


def placeholder(name, center, size, rgb):
    x, y, z = center
    w, h, d = size
    bm = add_box(bmesh.new(), x - w / 2, x + w / 2, y - h / 2, y + h / 2, z - d / 2, z + d / 2)
    ob = bm_to_obj(name, bm)
    ob.data.materials.append(make_material(name + '_mat', rgb))
    return ob


# ---------------------------------------------------------------- main

def main():
    out = 'cad'
    argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
    if '--out' in argv:
        out = argv[argv.index('--out') + 1]
    out = os.path.abspath(out)
    stl_dir = os.path.join(out, 'stl')
    ren_dir = os.path.join(out, 'renders')
    os.makedirs(stl_dir, exist_ok=True)
    os.makedirs(ren_dir, exist_ok=True)

    bpy.ops.wm.read_factory_settings(use_empty=True)

    print("building front", flush=True)
    front = build_front()
    print("building back", flush=True)
    back = build_back()
    print("building cap", flush=True)
    cap = build_cap()

    bad = 0
    bad += check_part('front', front) > 0
    bad += check_part('back', back) > 0
    bad += check_part('button_cap', cap) > 0
    if bad:
        fail("non-manifold edges present; see part lines above")

    # print-orientation copies (identity transform, orientation baked into mesh)
    front_p = print_copy(front, 'gotchi_front_print', flip_x_pi=True)
    back_p = print_copy(back, 'gotchi_back_print', flip_x_pi=False)
    cap_p = print_copy(cap, 'gotchi_button_cap_print', flip_x_pi=False)
    # Print copies are rigid transforms of the checked parts: non-manifold count and bbox
    # dimensions are invariant, so the three part lines above are the report.

    print("exporting STL", flush=True)
    export_stl(front_p, os.path.join(stl_dir, 'gotchi_front.stl'))
    export_stl(back_p, os.path.join(stl_dir, 'gotchi_back.stl'))
    export_stl(cap_p, os.path.join(stl_dir, 'gotchi_button_cap.stl'))
    for ob in (front_p, back_p, cap_p):
        bpy.data.objects.remove(ob, do_unlink=True)

    # assembled design geometry for the .blend and renders
    cap.location = (50.0, 0.0, 0.0)
    front.data.materials.append(make_material('shell_front', (0.85, 0.85, 0.82)))
    back.data.materials.append(make_material('shell_back', (0.62, 0.66, 0.74)))
    cap.data.materials.append(make_material('cap', (0.92, 0.55, 0.2)))

    scene, cam = setup_scene()
    print("rendering", flush=True)
    render(scene, cam, os.path.join(ren_dir, 'front_iso.png'), {'front'},
           loc=(90, -110, 70), target=(0, 0, -4.5))
    render(scene, cam, os.path.join(ren_dir, 'back_iso.png'), {'back'},
           loc=(90, -110, -90), target=(0, 0, -18))

    # exploded: back half (and its contents) moved -35 in Z; placeholders are render-only
    ph = []
    ph.append(placeholder('ph_display', (0, P['disp_cy'], -5.5), (33, 48, 7), (0.2, 0.5, 0.9)))
    back_z = -35.0
    back.location.z = back_z
    ph.append(placeholder('ph_battery', (0, P['bat_cy'], -14.1), (30, 40, 7.8), (0.9, 0.6, 0.1)))
    ph.append(placeholder('ph_xiao', (0, P['xiao_cy'], P['xiao_z_front'] - 7.5), (21, 17.8, 15), (0.2, 0.8, 0.3)))
    ph.append(placeholder('ph_speaker', (P['spk_cx'], P['spk_cy'], -23.25), (15.4, 10.4, 3.5), (0.8, 0.2, 0.2)))
    ph.append(placeholder('ph_amp', (P['amp_cx'], P['amp_cy'], -20.0), (20, 18, 4), (0.6, 0.2, 0.8)))
    for bx in (-P['btn_x'], P['btn_x']):
        ph.append(placeholder('ph_button', (bx, 31.0, P['btn_cz']), (6, 5, 6), (0.95, 0.9, 0.2)))
    ph.append(placeholder('ph_switch', (-15.0, P['sw_cy'], P['sw_cz']), (3.5, 4.0, 8.6), (0.1, 0.9, 0.9)))
    # placeholders stay at assembled coordinates; only the back half moves. The camera sits
    # below the front rim and above the moved back so the placeholders are not occluded.
    render(scene, cam, os.path.join(ren_dir, 'exploded.png'),
           {'front', 'back'} | {o.name for o in ph},
           loc=(60, -200, -26), target=(0, 0, -20))
    back.location.z = 0.0
    for o in ph:
        bpy.data.objects.remove(o, do_unlink=True)

    blend = os.path.join(out, 'gotchi_case.blend')
    for ob in bpy.data.objects:
        if ob.type == 'MESH':
            ob.hide_render = False
    bpy.ops.wm.save_as_mainfile(filepath=blend, check_existing=False)
    print(f"saved {blend}", flush=True)
    print("OK", flush=True)


try:
    main()
except SystemExit:
    raise
except BaseException as exc:  # noqa: BLE001 - any failure must give non-zero exit
    import traceback
    traceback.print_exc()
    fail(repr(exc))
