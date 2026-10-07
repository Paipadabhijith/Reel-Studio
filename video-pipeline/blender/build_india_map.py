"""Build blender/templates/india_map.blend from the state boundary GeoJSON files.

Run by scripts/render_blender.py:  Blender -b --factory-startup -P build_india_map.py -- --out india_map.blend
Each state is one extruded curve object named state_<CODE> (e.g. state_KA) that render.py animates.
"""
import json
import math
import sys
from pathlib import Path

import bpy

import importlib.util

HERE = Path(__file__).resolve().parent
# load the plain state table by path: Blender's Python has none of the repo's dependencies
_spec = importlib.util.spec_from_file_location("india_codes", HERE.parent / "scripts" / "lib" / "india_codes.py")
_codes = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_codes)
STATES = _codes.STATES


SIMPLE = HERE / "data" / "india_states_simple.json"


args = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
OUT = Path(args[args.index("--out") + 1]) if "--out" in args else HERE / "templates" / "india_map.blend"

MAP_HEIGHT = 10.0          # India spans this many Blender units north-south
LAT0, LON0 = 21.0, 82.5    # centre of the map
SIMPLIFY = 0.004           # extra Douglas-Peucker tolerance in Blender units (shapes are pre-simplified)
BASE_DEPTH = 0.12


def project(lon, lat):
    s = MAP_HEIGHT / 30.5
    return ((lon - LON0) * math.cos(math.radians(LAT0)) * s, (lat - LAT0) * s)


def simplify(points, tol):
    """Iterative Douglas-Peucker."""
    if len(points) < 4:
        return points
    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]
    while stack:
        a, b = stack.pop()
        (ax, ay), (bx, by) = points[a], points[b]
        dx, dy = bx - ax, by - ay
        norm = math.hypot(dx, dy) or 1e-12
        best, idx = 0.0, -1
        for i in range(a + 1, b):
            px, py = points[i]
            d = abs(dy * (px - ax) - dx * (py - ay)) / norm
            if d > best:
                best, idx = d, i
        if best > tol and idx > 0:
            keep[idx] = True
            stack += [(a, idx), (idx, b)]
    return [p for p, k in zip(points, keep) if k]


def rings_of(g):
    """Yield every ring (outer and holes) of a Polygon/MultiPolygon as projected points."""
    polys = g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]
    for poly in polys:
        for ring in poly:
            pts = simplify([project(x, y) for x, y, *_ in ring][:-1], SIMPLIFY)
            if len(pts) >= 3:
                yield pts


def material(name, rgb, rough=0.55, emission=0.0):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    bsdf = m.node_tree.nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = (*rgb, 1)
    bsdf.inputs["Roughness"].default_value = rough
    bsdf.inputs["Emission Color"].default_value = (*rgb, 1)
    bsdf.inputs["Emission Strength"].default_value = emission
    return m


bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
scene.name = "IndiaMap"
base_mat = material("state_base", (0.105, 0.125, 0.19))
small = {"CH", "DL", "PY", "GA", "DH", "LD", "AN"}

if not SIMPLE.exists():
    raise SystemExit(f"missing {SIMPLE}; run scripts.lib.india.build_simplified() first")
SHAPES = json.loads(SIMPLE.read_text())

for code in STATES:
    geo = SHAPES[code]
    curve = bpy.data.curves.new(f"state_{code}", "CURVE")
    curve.dimensions = "2D"
    curve.fill_mode = "BOTH"
    curve.extrude = BASE_DEPTH / 2   # extrudes both ways: total depth = BASE_DEPTH
    curve.resolution_u = 1
    for pts in rings_of(geo):
        spline = curve.splines.new("POLY")
        spline.points.add(len(pts) - 1)
        for p, (x, y) in zip(spline.points, pts):
            p.co = (x, y, 0, 1)
        spline.use_cyclic_u = True
    obj = bpy.data.objects.new(f"state_{code}", curve)
    obj["state_code"] = code
    obj["state_name"] = STATES[code][0]
    obj.location.z = 0.02 if code in small else 0.0   # small UTs sit just above the state around them
    obj.data.materials.append(base_mat)
    scene.collection.objects.link(obj)

# world, light and camera are placed by render.py (they depend on aspect ratio); keep simple defaults here
world = bpy.data.worlds.new("world")
world.use_nodes = True
world.node_tree.nodes["Background"].inputs["Color"].default_value = (0.043, 0.043, 0.063, 1)
scene.world = world
sun = bpy.data.objects.new("sun", bpy.data.lights.new("sun", "SUN"))
sun.data.energy = 3.0
sun.rotation_euler = (math.radians(35), math.radians(-20), math.radians(25))
scene.collection.objects.link(sun)

OUT.parent.mkdir(parents=True, exist_ok=True)
bpy.ops.wm.save_as_mainfile(filepath=str(OUT))
print(f"built {OUT} with {len(STATES)} states")
