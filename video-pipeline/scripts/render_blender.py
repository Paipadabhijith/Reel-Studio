"""Headless Blender scenes (`type: blender`) -> mp4 clips that Remotion drops into the video.

Blender writes PNG frames (Eevee, <=32 samples, textures clamped to 2K); FFmpeg encodes them,
using the Mac's hardware H.264 encoder when available. Clips are cached by a hash of
(template, params, frames, aspect).
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

from .lib import cache, india
from .lib.config import REPO_ROOT, heavy_lock
from .lib.progress import JobCancelled, cancelled, check_cancel, report, watch_cancel
from .lib.schema import ScenesFile, Timeline
from .lib.targets import Target

FPS = 30
BLENDER_DIR = REPO_ROOT / "blender"
TEMPLATES = BLENDER_DIR / "templates"
RENDER_PY = BLENDER_DIR / "render.py"
BLENDER_CANDIDATES = [
    "/Applications/Blender.app/Contents/MacOS/Blender",
    str(Path.home() / "Applications/Blender.app/Contents/MacOS/Blender"),
]
ASPECT = {"reel": "9:16", "long": "16:9"}
SAVED = re.compile(r"\bSaved: '")


class BlenderError(RuntimeError):
    pass


def clip_path(scene_id: int, kind: str = "reel") -> str:
    """One clip per scene and video format: the same scene is rendered 9:16 for a reel and 16:9 for long-form."""
    return f"build/blender/scene_{scene_id:02d}_{'9x16' if kind == 'reel' else '16x9'}.mp4"


def find_blender() -> str:
    for c in [os.getenv("BLENDER_BIN", ""), *BLENDER_CANDIDATES, shutil.which("blender") or ""]:
        if c and Path(c).exists():
            return c
    raise BlenderError("Blender not found. Install it with `brew install --cask blender` "
                       "(or set BLENDER_BIN in .env).")


def template_file(name: str) -> Path:
    if not re.fullmatch(r"[a-z0-9_]+", name or ""):
        raise BlenderError(f"bad Blender template name {name!r}")
    return TEMPLATES / f"{name}.blend"


def ensure_template(name: str, log=print) -> Path:
    """Use blender/templates/<name>.blend, building it from blender/build_<name>.py the first time."""
    blend = template_file(name)
    if blend.exists():
        return blend
    builder = BLENDER_DIR / f"build_{name}.py"
    if not builder.exists():
        raise BlenderError(f"unknown Blender template {name!r}: no {blend.name} and no {builder.name}")
    log(f"blender: building template {name} (first use)")
    if name == "india_map":
        try:
            india.fetch_boundaries(log=log)
            india.build_simplified(log=log)
        except Exception as e:  # network or bad data: say what to do instead of a stack trace
            raise BlenderError(f"could not download the India state boundaries ({type(e).__name__}: {e}). "
                               f"Check your connection and try again.")
    TEMPLATES.mkdir(parents=True, exist_ok=True)
    with heavy_lock("blender"):
        r = subprocess.run([find_blender(), "-b", "--factory-startup", "-P", str(builder), "--", "--out", str(blend)],
                           capture_output=True, text=True, timeout=600)
    if r.returncode != 0 or not blend.exists():
        tail = "\n".join((r.stdout + r.stderr).strip().splitlines()[-8:])
        raise BlenderError(f"building the {name} template failed:\n{tail}")
    return blend


def frames_for(tl: Timeline, scene_id: int) -> int:
    sc = next(s for s in tl.scenes if s.id == scene_id)
    return max(int(round((sc.end_s - sc.start_s) * FPS)), FPS)


def _encode(frames_dir: Path, dst: Path, log) -> None:
    src = ["-framerate", str(FPS), "-i", str(frames_dir / "frame_%04d.png")]
    tail = ["-pix_fmt", "yuv420p", "-movflags", "+faststart", str(dst)]
    for codec in (["-c:v", "h264_videotoolbox", "-b:v", "14M"], ["-c:v", "libx264", "-crf", "18", "-preset", "medium"]):
        r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *src, *codec, *tail], capture_output=True, text=True)
        if r.returncode == 0:
            return
        log(f"blender: encoder {codec[1]} failed, trying the next one")
    raise BlenderError(f"could not encode clip: {r.stderr[-300:]}")


def render_scene(project: Path, template: str, params: dict, frames: int, aspect: str, scene_id: int, log=print) -> Path:
    """Render one scene to build/blender/scene_NN_<aspect>.mp4 (cached)."""
    kind = "reel" if aspect == "9:16" else "long"
    dst = project / clip_path(scene_id, kind)
    cache_dir = project / "build" / "cache"
    if template == "india_map":
        codes, unknown = india.resolve_states(params.get("highlight_states", []))
        if unknown:
            log(f"blender scene {scene_id}: ignoring unknown states {unknown}")
        params = {**params, "highlight_states": codes}
    blend = ensure_template(template, log)
    digest = cache.hash_inputs(template, params, frames, aspect, files=[blend, RENDER_PY])
    stage = f"blender_{scene_id:02d}_{kind}"
    if cache.is_fresh(cache_dir, stage, digest, [dst]):
        log(f"blender scene {scene_id}: cached")
        return dst

    frames_dir = project / "build" / "blender" / f"frames_{scene_id:02d}_{kind}"
    shutil.rmtree(frames_dir, ignore_errors=True)
    frames_dir.mkdir(parents=True)
    params_file = frames_dir / "params.json"
    params_file.write_text(json.dumps(params))
    cmd = [find_blender(), "-b", "--factory-startup", str(blend), "-P", str(RENDER_PY), "--",
           "--params", str(params_file), "--frames", str(frames), "--aspect", aspect, "--out", str(frames_dir)]
    log(f"blender scene {scene_id}: rendering {frames} frames ({template}, {aspect})")
    done, tail = 0, []
    with heavy_lock("blender"):
        check_cancel()
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1,
                                start_new_session=True)
        with watch_cancel(proc):
            for line in proc.stdout:  # type: ignore[union-attr]
                line = line.rstrip()
                tail = (tail + [line])[-25:]
                if SAVED.search(line):
                    done += 1
                    report(min(done / frames, 0.97), f"blender scene {scene_id}: frame {done}/{frames}")
        if cancelled():
            proc.wait()
            shutil.rmtree(frames_dir, ignore_errors=True)
            raise JobCancelled()
        code = proc.wait()
    if code != 0 or done < frames:
        raise BlenderError(f"Blender scene {scene_id} failed ({done}/{frames} frames):\n" + "\n".join(tail[-10:]))
    report(0.98, f"blender scene {scene_id}: encoding")
    dst.parent.mkdir(parents=True, exist_ok=True)
    _encode(frames_dir, dst, log)
    shutil.rmtree(frames_dir, ignore_errors=True)
    cache.mark(cache_dir, stage, digest)
    return dst


def render_for_target(project: Path, sf: ScenesFile, tl: Timeline, target: Target, log=print) -> list[Path]:
    """Render every Blender scene of a video, with durations taken from the aligned timeline."""
    out = []
    for sid in target.scene_ids:
        v = sf.scene(sid).visual
        if v.type != "blender":
            continue
        if not v.template:
            log(f"scene {sid}: blender scene has no template; skipped")
            continue
        out.append(render_scene(project, v.template, v.params, frames_for(tl, sid), ASPECT[target.kind], sid, log))
    return out


def render_preview(project: Path, template: str, params: dict, aspect: str, scene_id: int, log=print) -> Path:
    """A quick low-resolution render of the finished state of a 3D scene (last frame of a 1.5 s clip), for checking."""
    kind = "reel" if aspect == "9:16" else "long"
    dst = project / "build" / "parts" / f"blender_preview_{scene_id:02d}_{kind}.png"
    if template == "india_map":
        codes, _ = india.resolve_states(params.get("highlight_states", []))
        params = {**params, "highlight_states": codes}
    blend = ensure_template(template, log)
    digest = cache.hash_inputs(template, params, aspect, "preview", files=[blend, RENDER_PY])
    stage = f"blender_preview_{scene_id:02d}_{kind}"
    cache_dir = project / "build" / "cache"
    if cache.is_fresh(cache_dir, stage, digest, [dst]):
        return dst
    work = project / "build" / "parts" / f"_preview_{scene_id:02d}_{kind}"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    (work / "params.json").write_text(json.dumps(params))
    frames = 48
    cmd = [find_blender(), "-b", "--factory-startup", str(blend), "-P", str(RENDER_PY), "--",
           "--params", str(work / "params.json"), "--frames", str(frames), "--aspect", aspect, "--scale", "40", "--out", str(work)]
    log(f"blender scene {scene_id}: rendering a quick preview")
    with heavy_lock("blender"):
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
    last = work / f"frame_{frames:04d}.png"
    if r.returncode != 0 or not last.exists():
        raise BlenderError("Blender preview failed:\n" + "\n".join((r.stdout + r.stderr).strip().splitlines()[-8:]))
    dst.parent.mkdir(parents=True, exist_ok=True)
    last.replace(dst)
    shutil.rmtree(work, ignore_errors=True)
    cache.mark(cache_dir, stage, digest)
    return dst
