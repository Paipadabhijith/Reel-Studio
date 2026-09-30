"""Manual assets: drop `sceneNN.jpg|png|mp4` into inbox/ and they are moved into assets/."""
from __future__ import annotations

import json
import re
import shutil
import time
from pathlib import Path
from typing import Callable

from .lib.assets import find_asset, image_path, remove_scene_assets, upsert_credit, video_path
from .lib.schema import Credit, Scene, ScenesFile, dump_json, load_scenes

INBOX_NAME = re.compile(r"^scene_?(\d+)\.(jpe?g|png|webp|mp4|mov)$", re.IGNORECASE)
RIGHTS = ("own", "licensed", "press-kit", "commentary")

# (scene, filename) -> (rights, source_text)
RightsPrompt = Callable[[Scene, str], tuple[str, str]]


def pending(project: Path, sf: ScenesFile) -> list[Scene]:
    return [s for s in sf.scenes if s.visual.type == "manual" and not find_asset(project, s)]


def write_readme(project: Path, sf: ScenesFile) -> list[Scene]:
    todo = pending(project, sf)
    lines = []
    if not todo:
        lines.append("No manual scenes pending.")
    else:
        lines += [
            f"{len(todo)} scene(s) need an asset you provide.",
            "Drop files here named sceneNN.jpg / .png / .mp4 (e.g. scene05.jpg), then run:",
            f"    reel inbox {project.name}        (or: reel draft {project.name} --continue)",
            "You'll be asked once per file for its source and rights: " + " / ".join(RIGHTS) + ".",
            "",
        ]
        for s in todo:
            v = s.visual
            lines += [
                f"scene{s.id:02d}  [{v.orientation or 'any orientation'}]",
                f"  says:   {s.text}",
                f"  needs:  {v.prompt or v.query or '(no prompt)'}",
                "",
            ]
    (project / "inbox").mkdir(parents=True, exist_ok=True)
    (project / "inbox" / "README.txt").write_text("\n".join(lines).rstrip() + "\n")
    return todo


def attach(
    project: Path, sf: ScenesFile, scene: Scene, src: Path, rights: str, source_text: str, move: bool = True,
) -> str:
    """Put `src` in place as the scene's asset and record its credit. Returns the relative path."""
    if rights not in RIGHTS:
        raise ValueError(f"rights must be one of {RIGHTS}")
    ext = src.suffix.lower().lstrip(".")
    ext = "jpg" if ext == "jpeg" else ext
    rel = video_path(scene.id, ext) if ext in ("mp4", "mov") else image_path(scene.id, ext)
    remove_scene_assets(project, scene.id)
    dest = project / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    (shutil.move if move else shutil.copy2)(str(src), str(dest))
    scene.visual.file = rel
    upsert_credit(project, Credit(
        scene_id=scene.id, source=source_text or "user supplied", license=rights,
        url="", attribution_text=source_text or "", added_by="manual",
    ))
    # a hand-supplied asset is final: stop fetch from replacing it later
    state_file = project / "build" / "cache" / "fetch.json"
    if state_file.exists():
        state = json.loads(state_file.read_text())
        state.pop(str(scene.id), None)
        state_file.write_text(json.dumps(state, indent=2))
    return rel


def ingest(project: Path, ask: RightsPrompt, log=print) -> list[int]:
    """Move every recognised inbox file into assets/. Returns the scene ids filled."""
    scenes_path = project / "script" / "scenes.json"
    sf = load_scenes(scenes_path)
    by_id = {s.id: s for s in sf.scenes}
    done: list[int] = []
    for f in sorted((project / "inbox").iterdir()):
        m = INBOX_NAME.match(f.name)
        if not m:
            continue
        sid = int(m.group(1))
        scene = by_id.get(sid)
        if not scene:
            log(f"inbox: {f.name} does not match any scene id; left in place")
            continue
        rights, source_text = ask(scene, f.name)
        rel = attach(project, sf, scene, f, rights, source_text)
        log(f"inbox: {f.name} -> {rel} ({rights})")
        done.append(sid)
    if done:
        dump_json(sf, scenes_path)
    write_readme(project, sf)
    return done


def watch(project: Path, ask: RightsPrompt, interval: float = 2.0, log=print) -> None:
    """Poll inbox/ until nothing is pending. Ctrl-C to stop early."""
    while True:
        ingest(project, ask, log)
        todo = pending(project, load_scenes(project / "script" / "scenes.json"))
        if not todo:
            log("inbox: all manual scenes filled")
            return
        time.sleep(interval)
