"""Parts: each scene of a video as a unit that is built, checked and approved before the final render.

A part is identified by (video, scene). It is approved against a fingerprint of everything that shows on
screen (the scene's plan and its asset file), so changing the scene or swapping the file makes the
approval "stale" instead of silently carrying over. Timing approvals (after recording) are fingerprinted
by the scene's real start, end and word count.
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import animation, plan
from .lib import cache, india
from .lib.assets import find_asset, load_credits
from .lib.schema import Scene, ScenesFile, Timeline, TimelineScene
from .lib.targets import Target

WORDS_PER_S = 2.5
MIN_SCENE_S, MAX_SCENE_S = 1.5, 14.0
SOFT_UPSCALE, HARD_UPSCALE = 1.4, 3.0
LOW_MATCH = 0.5


@dataclass
class Check:
    level: str   # "error" blocks approval, "warn" is shown, "ok" is a pass
    msg: str


@dataclass
class Part:
    scene: Scene
    key: str
    checks: list[Check] = field(default_factory=list)
    visual: str = "pending"      # pending | approved | stale | redo | blocked
    timing: str | None = None    # None until the video has been aligned
    note: str = ""
    can_animate: bool = False    # no file for this scene: it can be turned into an animation in one click
    fingerprint: str = ""
    timing_fp: str = ""
    still: str | None = None     # path relative to the project

    @property
    def errors(self) -> list[Check]:
        return [c for c in self.checks if c.level == "error"]

    @property
    def warnings(self) -> list[Check]:
        return [c for c in self.checks if c.level == "warn"]


def part_key(target: Target, sid: int) -> str:
    return f"{target.id}:{sid}"


# ---------------------------------------------------------------- fingerprints


def _file_hash(path: Path) -> str:
    """Cheap identity of a file (name, size, modification time); replacing the file changes it."""
    if not path.exists():
        return "missing"
    st = path.stat()
    return f"{path.name}:{st.st_size}:{st.st_mtime_ns}"


def asset_of(project: Path, scene: Scene) -> tuple[str, str] | None:
    return find_asset(project, scene) if scene.visual.type in ("photo", "video", "manual", "chart") else None


def fingerprint(project: Path, scene: Scene) -> str:
    asset = asset_of(project, scene)
    return cache.hash_inputs(scene.model_dump(mode="json"), _file_hash(project / asset[1]) if asset else None)


def timing_fingerprint(ts: TimelineScene | None) -> str:
    if ts is None:
        return ""
    return cache.hash_inputs(round(ts.start_s, 1), round(ts.end_s, 1), len(ts.words))


# ---------------------------------------------------------------- automatic checks


def _image_size(path: Path) -> tuple[int, int] | None:
    try:
        from PIL import Image

        with Image.open(path) as im:
            return im.size
    except Exception:
        return None


def _video_size(path: Path) -> tuple[int, int] | None:
    import subprocess

    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
                        "-of", "csv=p=0", str(path)], capture_output=True, text=True)
    try:
        w, h = r.stdout.strip().split(",")[:2]
        return int(w), int(h)
    except ValueError:
        return None


def est_seconds(scene: Scene) -> float:
    return len(scene.text.split()) / WORDS_PER_S


def check_scene(
    project: Path, sf: ScenesFile, scene: Scene, target: Target, ts: TimelineScene | None,
    duplicates: dict[str, list[int]] | None = None,
) -> list[Check]:
    from .render_blender import BLENDER_CANDIDATES
    from pathlib import Path as _P
    import os
    import shutil

    out: list[Check] = []
    v = scene.visual
    secs = (ts.end_s - ts.start_s) if ts else est_seconds(scene)
    label = "length" if ts else "estimated length"

    # ---- the picture itself
    if v.type in ("photo", "video", "manual"):
        found = asset_of(project, scene)
        if not found:
            out.append(Check("error", "No file yet: " + (v.prompt if v.type == "manual" and v.prompt else
                                                           "fetch visuals, or replace it with your own")))
        else:
            kind, rel = found
            size = _image_size(project / rel) if kind == "photo" else _video_size(project / rel)
            if size:
                need = max(target.width / size[0], target.height / size[1])
                if need > HARD_UPSCALE:
                    out.append(Check("error", f"Too small ({size[0]}×{size[1]}): it would be stretched {need:.1f}×"))
                elif need > SOFT_UPSCALE:
                    out.append(Check("warn", f"Low resolution ({size[0]}×{size[1]}): will look soft, stretched {need:.1f}×"))
                else:
                    out.append(Check("ok", f"Sharp enough ({size[0]}×{size[1]})"))
                portrait_file, portrait_frame = size[1] > size[0], target.height > target.width
                if portrait_file != portrait_frame and abs(size[0] - size[1]) > 0.15 * max(size):
                    out.append(Check("warn", "Wrong orientation for this video: it will be cropped heavily"))
            if not any(c.scene_id == scene.id for c in load_credits(project)):
                out.append(Check("warn", "No credit recorded (fine if it's your own file)"))
            if duplicates and len(duplicates.get(_file_hash(project / rel), [])) > 1:
                others = [i for i in duplicates[_file_hash(project / rel)] if i != scene.id]
                out.append(Check("warn", f"Same picture as scene {', '.join(map(str, others))}"))
    elif v.type == "chart":
        labels, values = v.params.get("labels") or [], v.params.get("values") or []
        if len(labels) != len(values) or len(values) < 2:
            out.append(Check("error", "Chart needs matching labels and values (at least 2)"))
        else:
            out.append(Check("ok", f"Chart data valid ({len(values)} values)"))
    elif v.type == "stat":
        value = (scene.overlay.value if scene.overlay else None) or v.params.get("value")
        if not value:
            out.append(Check("error", "Stat has no number to show"))
        elif not any(c.isdigit() for c in str(value)):
            out.append(Check("warn", f"“{value}” has no digits, so it won't count up"))
    elif v.type == "animation":
        head = (v.params.get("headline") or "").strip()
        if not head:
            out.append(Check("warn", "No headline: one will be made from the sentence"))
        else:
            out.append(Check("ok", animation.describe(scene) + (f" (instead of a {v.downgraded_from})" if v.downgraded_from else "")))
        if len(head) > 40:
            out.append(Check("warn", "Long headline: it will shrink to fit; a shorter one reads better"))
    elif v.type == "blender":
        if v.template == animation.TITLE3D:
            if not (v.params.get("headline") or "").strip():
                out.append(Check("error", "The 3D title has no headline"))
            else:
                out.append(Check("ok", animation.describe(scene)))
        else:
            codes, bad = india.resolve_states(v.params.get("highlight_states", []))
            if bad or not codes:
                out.append(Check("error", "Unknown or missing states: " + (", ".join(bad) if bad else "none chosen")))
            else:
                out.append(Check("ok", f"Highlights {', '.join(codes)}"))
    if v.type == "blender":
        if not any(_P(c).exists() for c in [os.getenv("BLENDER_BIN", ""), *BLENDER_CANDIDATES]) and not shutil.which("blender"):
            out.append(Check("error", "Blender is not installed (brew install --cask blender)"))

    if v.params.get("why") and v.type in ("stat", "chart", "animation", "blender"):
        out.append(Check("ok", "Chosen automatically: " + str(v.params["why"])))

    # ---- text on screen
    if v.type == "text_card" or (v.type in ("photo", "video", "manual") and not asset_of(project, scene)):
        fs = 84 if target.kind == "reel" else 72
        side, vert = (100, 500) if target.kind == "reel" else (100, 120)
        per_line = max((target.width - 2 * side) / (0.55 * fs), 1)
        height = math.ceil(len(scene.text) / per_line) * fs * 1.15
        if height > target.height - vert:
            out.append(Check("warn", "The text is too long to fit the screen: shorten it or split the scene"))

    # ---- script
    if not scene.text.strip():
        out.append(Check("error", "No narration text"))
    if secs < MIN_SCENE_S:
        out.append(Check("warn", f"Very short ({label} {secs:.1f}s): the picture may flash by"))
    elif secs > MAX_SCENE_S:
        out.append(Check("warn", f"Long for one picture ({label} {secs:.0f}s): consider splitting it"))
    low = [e for e in scene.emphasis if e.lower() not in scene.text.lower()]
    if low:
        out.append(Check("warn", f"Emphasis not found in the text: {', '.join(low)}"))

    # ---- after recording
    if ts is not None and ts.match is not None:
        if ts.match < LOW_MATCH:
            out.append(Check("warn", f"Only {ts.match:.0%} of this scene's words were found in your recording: "
                                     "captions may be mistimed. Re-record it or change the text to match what you said"))
        else:
            out.append(Check("ok", f"Voice matches the script ({ts.match:.0%})"))
    return out


# ---------------------------------------------------------------- approvals


def _entry(qc: dict, key: str) -> dict:
    return qc.get("approvals", {}).get(key, {})


def overview(
    project: Path, sf: ScenesFile, target: Target, tl: Timeline | None = None, with_stills: bool = True,
) -> list[Part]:
    """Every scene of a video with its checks and approval state."""
    qc = plan.read_qc(project)
    ts_by_id = {s.id: s for s in tl.scenes} if tl else {}
    dups: dict[str, list[int]] = {}
    for sid in target.scene_ids:
        a = asset_of(project, sf.scene(sid))
        if a and sf.scene(sid).visual.type in ("photo", "video"):
            dups.setdefault(_file_hash(project / a[1]), []).append(sid)
    parts = []
    for sid in target.scene_ids:
        sc, ts = sf.scene(sid), ts_by_id.get(sid)
        p = Part(scene=sc, key=part_key(target, sid), fingerprint=fingerprint(project, sc), timing_fp=timing_fingerprint(ts))
        p.checks = check_scene(project, sf, sc, target, ts, dups)
        p.can_animate = sc.visual.type in ("photo", "video", "manual") and asset_of(project, sc) is None
        entry = _entry(qc, p.key)
        p.note = (entry.get("visual") or {}).get("note", "") or qc.get("redo", {}).get(p.key, {}).get("note", "")
        p.visual = _state(qc, p.key, "visual", p.fingerprint, bool(p.errors))
        if ts is not None:
            p.timing = _state(qc, p.key, "timing", p.timing_fp, False)
        if with_stills:
            rel = still_path(target, sid)
            if cache.is_fresh(project / "build" / "cache", f"still_{target.id}_{sid}",
                              still_digest(project, target, p.fingerprint), [project / rel]):
                p.still = rel
        parts.append(p)
    return parts


def _state(qc: dict, key: str, kind: str, fp: str, blocked: bool) -> str:
    if key in qc.get("redo", {}) and kind == "visual":
        return "redo"
    e = _entry(qc, key).get(kind)
    if blocked:
        return "blocked"
    if not e:
        return "pending"
    return "approved" if e.get("hash") == fp else "stale"


def approve(project: Path, target: Target, sid: int, kind: str, fp: str, note: str = "") -> None:
    qc = plan.read_qc(project)
    key = part_key(target, sid)
    qc.setdefault("approvals", {}).setdefault(key, {})[kind] = {"hash": fp, "note": note, "at": time.time()}
    qc.get("redo", {}).pop(key, None)
    plan.write_qc(project, qc)


def request_redo(project: Path, target: Target, sid: int, note: str) -> None:
    qc = plan.read_qc(project)
    key = part_key(target, sid)
    qc.setdefault("redo", {})[key] = {"note": note, "at": time.time()}
    qc.get("approvals", {}).get(key, {}).pop("visual", None)
    plan.write_qc(project, qc)


def approve_all_clean(project: Path, parts: list[Part], target: Target, kind: str) -> int:
    """Approve every part with no errors and no warnings. Returns how many."""
    n = 0
    for p in parts:
        state = p.visual if kind == "visual" else p.timing
        clean = not p.errors and not p.warnings
        if state in ("pending", "stale") and clean:
            approve(project, target, p.scene.id, kind, p.fingerprint if kind == "visual" else p.timing_fp)
            n += 1
    return n


def gate(parts: list[Part]) -> dict:
    """How far a video is from being allowed to render."""
    vis_todo = [p.scene.id for p in parts if p.visual != "approved"]
    tim = [p for p in parts if p.timing is not None]
    tim_todo = [p.scene.id for p in tim if p.timing != "approved"]
    return {"total": len(parts), "visual_todo": vis_todo, "timing_todo": tim_todo,
            "visual_ok": not vis_todo, "timing_ok": bool(tim) and not tim_todo, "has_timing": bool(tim)}


# ---------------------------------------------------------------- stills (picture of each part before any recording)


def still_path(target: Target, sid: int) -> str:
    return f"build/parts/stills/{target.id}_{sid:02d}.jpg"


def still_digest(project: Path, target: Target, fp: str) -> str:
    from .render_final import template_digest

    return cache.hash_inputs(fp, target.kind, template_digest())


def build_stills(project: Path, sf: ScenesFile, target: Target, tl: Timeline | None = None,
                 only: list[int] | None = None, log=print) -> int:
    """Render a picture of every scene that doesn't have a current one. Returns how many were made."""
    from . import render_blender
    from .draft import estimate_timeline
    from .lib.progress import report
    from .render_final import remotion_still, scene_frames, scene_props

    tl = tl or estimate_timeline(sf, target)
    frames = scene_frames(tl, target.scene_ids)
    todo = []
    for sid in target.scene_ids:
        if only and sid not in only:
            continue
        fp = fingerprint(project, sf.scene(sid))
        digest = still_digest(project, target, fp)
        if not cache.is_fresh(project / "build" / "cache", f"still_{target.id}_{sid}", digest, [project / still_path(target, sid)]):
            todo.append((sid, digest))
    for n, (sid, digest) in enumerate(todo, 1):
        from .lib.progress import check_cancel

        check_cancel()
        sc = sf.scene(sid)
        out = project / still_path(target, sid)
        report(n / (len(todo) + 1), f"picture {n}/{len(todo)}: scene {sid}")
        if sc.visual.type == "blender" and sc.visual.template:
            png = render_blender.render_preview(project, sc.visual.template, sc.visual.params,
                                                render_blender.ASPECT[target.kind], sid, log)
            from PIL import Image

            Image.open(png).convert("RGB").save(out, quality=88)
        else:
            props = scene_props(project, sf, tl, target, sid, "draft", log)
            props["draft"] = False  # a still shows the picture, not the DRAFT labels
            n_frames = frames[sid][1] - frames[sid][0]
            remotion_still(project, props, out, min(max(n_frames - 1, 0), 54), 0.5 if target.kind == "reel" else 0.6)
        cache.mark(project / "build" / "cache", f"still_{target.id}_{sid}", digest)
        log(f"picture for scene {sid} ready")
    return len(todo)
