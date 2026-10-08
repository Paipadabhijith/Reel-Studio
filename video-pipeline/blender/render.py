"""Headless render entrypoint (runs inside Blender).

Blender -b <template>.blend -P render.py -- --params p.json --frames 90 --aspect 9:16 --out frames/

Sets the clip length, applies the scene's parameters, forces Eevee (<=32 samples, textures <=2K)
and writes frame_0001.png ... for FFmpeg to encode.
"""
import json
import math
import sys
from pathlib import Path

import bpy
from mathutils import Vector

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []


def arg(name, default=None):
    return argv[argv.index(name) + 1] if name in argv else default


PARAMS = json.loads(Path(arg("--params")).read_text()) if arg("--params") else {}
FRAMES = int(arg("--frames", "90"))
ASPECT = arg("--aspect", "9:16")
OUT = Path(arg("--out", "frames"))
FPS = 30

# brand colours are sRGB hex (#FFD23F); Blender wants linear values
ACCENT = (1.0, 0.64, 0.05)
BASE = (0.16, 0.19, 0.28)

scene = bpy.context.scene

# ---- render settings: Eevee only, light on memory
engines = [e.identifier for e in bpy.types.RenderSettings.bl_rna.properties["engine"].enum_items]
scene.render.engine = "BLENDER_EEVEE_NEXT" if "BLENDER_EEVEE_NEXT" in engines else "BLENDER_EEVEE"
for attr in ("taa_render_samples", "taa_samples"):
    if hasattr(scene.eevee, attr):
        setattr(scene.eevee, attr, 32)
res = (1080, 1920) if ASPECT == "9:16" else (1920, 1080)
scene.render.resolution_x, scene.render.resolution_y = res
scene.render.resolution_percentage = int(arg("--scale", "100"))
scene.render.fps = FPS
scene.view_settings.view_transform = "Standard"   # keep the brand colours true (no filmic desaturation)
scene.frame_start, scene.frame_end = 1, FRAMES
scene.render.image_settings.file_format = "PNG"
scene.render.image_settings.color_mode = "RGB"
scene.render.use_file_extension = True
scene.render.filepath = str(OUT / "frame_")
for img in bpy.data.images:  # clamp textures to 2K
    if img.size[0] > 2048 or img.size[1] > 2048:
        k = 2048 / max(img.size)
        img.scale(max(int(img.size[0] * k), 1), max(int(img.size[1] * k), 1))


def ease(t):
    t = max(0.0, min(1.0, t))
    return t * t * (3 - 2 * t)


def key(obj, path, frame, value, idx=-1):
    setattr(obj, path, value)
    obj.keyframe_insert(data_path=path, frame=frame, index=idx)


def set_smooth(obj):
    action = obj.animation_data.action if obj.animation_data else None
    if not action:
        return
    for fc in getattr(action, "fcurves", []):  # fcurves live on the action in 3.x/4.x; layered in 5.x
        for kp in fc.keyframe_points:
            kp.interpolation = "BEZIER"


# ---- india_map ---------------------------------------------------------------------------------
def india_map():
    codes = [str(c).upper() for c in PARAMS.get("highlight_states", [])]
    labels = PARAMS.get("labels", True)
    camera_mode = PARAMS.get("camera", "top_down_tilt")
    states = {o["state_code"]: o for o in bpy.data.objects if "state_code" in o}
    wanted = [c for c in codes if c in states]

    # highlighted states rise and light up one after another, starting at 0.4 s
    stagger = min(int(0.35 * FPS), max((FRAMES - 3 * FPS) // max(len(wanted), 1), 4))
    for n, code in enumerate(wanted):
        obj = states[code]
        mat = obj.data.materials[0].copy()
        mat.name = f"hl_{code}"
        obj.data.materials[0] = mat
        bsdf = mat.node_tree.nodes["Principled BSDF"]
        f0 = int(0.4 * FPS) + n * stagger
        f1 = f0 + int(0.6 * FPS)
        for frame, t in ((1, 0.0), (f0, 0.0), (f1, 1.0)):
            col = tuple(BASE[i] + (ACCENT[i] - BASE[i]) * ease(t) for i in range(3))
            bsdf.inputs["Base Color"].default_value = (*col, 1)
            bsdf.inputs["Emission Color"].default_value = (*ACCENT, 1)
            bsdf.inputs["Emission Strength"].default_value = 0.6 * ease(t)
            for sock in ("Base Color", "Emission Strength"):
                bsdf.inputs[sock].keyframe_insert("default_value", frame=frame)
        base_z = obj.location.z
        key(obj, "scale", 1, (1, 1, 1))
        key(obj, "scale", f0, (1, 1, 1))
        key(obj, "scale", f1, (1, 1, 3.2))
        key(obj, "location", 1, (0, 0, base_z))
        key(obj, "location", f1, (0, 0, base_z + 0.07 * 2.2))
        set_smooth(obj)

    def centre_of(obj):
        bb = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
        return Vector((sum(v.x for v in bb) / 8, sum(v.y for v in bb) / 8, 0))

    centre = Vector((0, 0, 0))
    hl_centre = sum((centre_of(states[c]) for c in wanted), Vector((0, 0, 0))) / len(wanted) if wanted else centre
    # camera: fit the whole map for this aspect, then tilt/dolly slowly
    cam_data = bpy.data.cameras.new("cam")
    cam_data.lens = 50
    cam = bpy.data.objects.new("cam", cam_data)
    scene.collection.objects.link(cam)
    scene.camera = cam
    aspect = res[0] / res[1]
    half_fov_major = math.atan(cam_data.sensor_width / 2 / cam_data.lens)
    map_w, map_h, margin = 9.0, 10.0, 1.22
    vert = max(map_h * margin, map_w * margin / aspect) if aspect < 1 else max(map_h * margin, map_w * margin / aspect)
    major = vert if aspect < 1 else vert * aspect          # world extent along the sensor's major axis
    dist = (major / 2) / math.tan(half_fov_major)

    pivot = bpy.data.objects.new("pivot", None)
    scene.collection.objects.link(pivot)
    pivot.location = centre
    cam.parent = pivot
    cam.location = (0, 0, dist)
    tilt0, tilt1, zoom1 = {
        "top_down": (0, 0, 1.0),
        "top_down_tilt": (8, 30, 0.93),
        "orbit": (30, 30, 0.95),
    }.get(camera_mode, (8, 30, 0.93))
    # portrait: the app UI and the captions use the bottom of the frame, so aim the camera below the map
    # (which moves the map up) and keep the zoom gentle
    lift = Vector((0, -2.7, 0)) if aspect < 1 else Vector((0, 0, 0))
    if wanted and camera_mode != "top_down":      # drift toward the highlighted states while zooming in a little
        key(pivot, "location", 1, tuple(centre + lift))
        key(pivot, "location", FRAMES, tuple(centre + lift + 0.5 * (hl_centre - centre)))
        zoom1 *= 0.9 if aspect < 1 else 0.84
    elif lift.length:
        pivot.location = centre + lift
    key(pivot, "rotation_euler", 1, (math.radians(tilt0), 0, 0))
    key(pivot, "rotation_euler", FRAMES, (math.radians(tilt1), 0, math.radians(14 if camera_mode == "orbit" else 0)))
    key(cam, "location", 1, (0, 0, dist))
    key(cam, "location", FRAMES, (0, 0, dist * zoom1))

    sun = next((o for o in bpy.data.objects if o.type == "LIGHT"), None)
    if sun:
        sun.data.energy = 3.4

    # name tags above the highlighted states, facing the camera
    if labels:
        placed = []
        for n, code in enumerate(wanted):
            obj = states[code]
            c = centre_of(obj)
            cx, cy = c.x, c.y
            while any(abs(cx - px) < 2.2 and abs(cy - py) < 0.4 for px, py in placed):
                cy += 0.42                        # nudge a label up until it clears its neighbours
            placed.append((cx, cy))
            txt = bpy.data.curves.new(f"label_{code}", "FONT")
            txt.body = obj["state_name"]
            txt.align_x = "CENTER"
            txt.size = 0.3
            txt.extrude = 0.02
            t = bpy.data.objects.new(f"label_{code}", txt)
            scene.collection.objects.link(t)
            t.location = (cx, cy, 1.5)
            t.visible_shadow = False
            t.visible_glossy = False
            m = t.constraints.new("TRACK_TO")
            m.target, m.track_axis, m.up_axis = cam, "TRACK_Z", "UP_Y"
            mat = bpy.data.materials.new(f"label_{code}")
            mat.use_nodes = True
            b = mat.node_tree.nodes["Principled BSDF"]
            b.inputs["Base Color"].default_value = (1, 1, 1, 1)
            b.inputs["Emission Color"].default_value = (1, 1, 1, 1)
            b.inputs["Emission Strength"].default_value = 1.0
            t.data.materials.append(mat)
            f0 = int(0.4 * FPS) + n * stagger + int(0.5 * FPS)
            key(t, "scale", 1, (0.001, 0.001, 0.001))
            key(t, "scale", f0, (0.001, 0.001, 0.001))
            key(t, "scale", f0 + 8, (1, 1, 1))


# ---- title3d -----------------------------------------------------------------------------------
def title3d():
    import random

    headline = str(PARAMS.get("headline") or "").strip().upper() or " "
    subline = str(PARAMS.get("subline") or "").strip()
    portrait = res[0] < res[1]
    rnd = random.Random(sum(map(ord, headline)))

    def lines(text, width):
        out, cur = [], ""
        for w in text.split():
            if cur and len(cur) + 1 + len(w) > width:
                out.append(cur)
                cur = w
            else:
                cur = (cur + " " + w).strip()
        return out + ([cur] if cur else [])

    def material(name, rgb, emission=0.0, rough=0.35, metal=0.0):
        m = bpy.data.materials.new(name)
        m.use_nodes = True
        b = m.node_tree.nodes["Principled BSDF"]
        b.inputs["Base Color"].default_value = (*rgb, 1)
        b.inputs["Roughness"].default_value = rough
        b.inputs["Metallic"].default_value = metal
        b.inputs["Emission Color"].default_value = (*rgb, 1)
        b.inputs["Emission Strength"].default_value = emission
        return m

    white = material("white", (0.95, 0.95, 0.97), 0.0, 0.25, 0.1)
    gold = material("gold", ACCENT, 0.5, 0.3, 0.6)
    soft = material("soft", (0.7, 0.72, 0.8), 0.2, 0.6)

    def text_obj(body, size, mat, extrude, y=0.0):
        c = bpy.data.curves.new("t", "FONT")
        c.body, c.align_x, c.align_y = body, "CENTER", "CENTER"
        c.size, c.extrude, c.bevel_depth, c.bevel_resolution = size, extrude, extrude * 0.25, 2
        o = bpy.data.objects.new("t", c)
        scene.collection.objects.link(o)
        o.data.materials.append(mat)
        o.location = (0, y, 0)
        return o

    wrap = 11 if portrait else 22
    head_lines = lines(headline, wrap) or [" "]
    head = text_obj("\n".join(head_lines), 1.0, white, 0.28)
    head.data.space_line = 0.95
    bpy.context.view_layer.update()
    # scale the headline to a width that fits the frame, whatever its length
    max_w = 8.2 if portrait else 15.0
    w, h = max(head.dimensions.x, 0.01), max(head.dimensions.y, 0.01)
    k = min(max_w / w, (6.0 if portrait else 5.0) / h, 3.2)
    head.scale = (k, k, k)
    underline = text_obj("____", 0.5, gold, 0.1, y=-(h * k) / 2 - 0.55)
    underline.scale = (k * 1.2, k * 0.6, k * 0.6)

    sub = None
    if subline:
        sub = text_obj("\n".join(lines(subline, 30 if portrait else 56)[:3]), 0.42, soft, 0.04, y=-(h * k) / 2 - 1.5)

    # a slow ring of glowing beads around the title
    ring = bpy.data.objects.new("ring", None)
    scene.collection.objects.link(ring)
    radius = (max_w / 2) * 1.18
    for i in range(36):
        ang = i / 36 * 6.2832
        bead = bpy.data.objects.new(f"b{i}", bpy.data.meshes.new(f"b{i}"))
        import bmesh

        bm = bmesh.new()
        bmesh.ops.create_uvsphere(bm, u_segments=12, v_segments=8, radius=0.07 + 0.07 * rnd.random())
        bm.to_mesh(bead.data)
        bm.free()
        bead.data.materials.append(gold if i % 3 == 0 else white)
        bead.location = (radius * math.cos(ang), radius * 0.62 * math.sin(ang), -0.3 + rnd.random() * 0.6)
        bead.parent = ring
        scene.collection.objects.link(bead)

    # lights
    sun = bpy.data.objects.new("sun", bpy.data.lights.new("sun", "SUN"))
    sun.data.energy = 3.0
    sun.rotation_euler = (math.radians(40), math.radians(-25), math.radians(20))
    scene.collection.objects.link(sun)
    glow = bpy.data.objects.new("glow", bpy.data.lights.new("glow", "POINT"))
    glow.data.energy = 900
    glow.data.color = ACCENT
    glow.location = (-3.5, -4.0, 4.0)
    scene.collection.objects.link(glow)

    # camera: fit the title, drift in, and rock the title a few degrees so the depth reads
    cam_data = bpy.data.cameras.new("cam")
    cam_data.lens = 50
    cam = bpy.data.objects.new("cam", cam_data)
    scene.collection.objects.link(cam)
    scene.camera = cam
    aspect = res[0] / res[1]
    half = math.atan(cam_data.sensor_width / 2 / cam_data.lens)
    need_w = max_w * 1.35
    need_h = (h * k + (2.6 if subline else 1.4)) * 1.5
    major = max(need_h, need_w / aspect) if aspect < 1 else max(need_w, need_h * aspect)
    dist = (major / 2) / math.tan(half)
    cam.location = (0, -0.6, dist * 1.12)
    key(cam, "location", 1, (0, -0.6, dist * 1.12))
    key(cam, "location", FRAMES, (0, -0.2, dist * 0.98))
    for obj in [head, underline] + ([sub] if sub else []):
        key(obj, "rotation_euler", 1, (math.radians(-6), math.radians(-14), 0))
        key(obj, "rotation_euler", FRAMES, (math.radians(4), math.radians(14), 0))
    key(ring, "rotation_euler", 1, (0, 0, 0))
    key(ring, "rotation_euler", FRAMES, (0, 0, math.radians(70)))
    # the title pops in over the first half second
    for obj, base in [(head, head.scale[:]), (underline, underline.scale[:])] + ([(sub, sub.scale[:])] if sub else []):
        key(obj, "scale", 1, tuple(0.001 * b for b in base))
        key(obj, "scale", int(0.5 * FPS), base)


TEMPLATES = {"india_map": india_map, "title3d": title3d}
name = Path(bpy.data.filepath).stem
if name not in TEMPLATES:
    raise SystemExit(f"no render handler for template {name!r}")
TEMPLATES[name]()
bpy.ops.render.render(animation=True)
