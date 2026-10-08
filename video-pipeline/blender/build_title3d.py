"""Build blender/templates/title3d.blend: an empty stage. render.py creates the text, lights and camera
for each scene from its parameters (headline, subline), so one template serves every title.

Run by scripts/render_blender.py:  Blender -b --factory-startup -P build_title3d.py -- --out title3d.blend
"""
import sys
from pathlib import Path

import bpy

args = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
OUT = Path(args[args.index("--out") + 1]) if "--out" in args else Path(__file__).resolve().parent / "templates" / "title3d.blend"

bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
scene.name = "Title3D"
world = bpy.data.worlds.new("world")
world.use_nodes = True
world.node_tree.nodes["Background"].inputs["Color"].default_value = (0.043, 0.043, 0.063, 1)
scene.world = world
OUT.parent.mkdir(parents=True, exist_ok=True)
bpy.ops.wm.save_as_mainfile(filepath=str(OUT))
print(f"built {OUT}")
