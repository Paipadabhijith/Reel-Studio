"""Final render: Remotion (concurrency 2) then two-pass loudnorm to -14 LUFS."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from .align_audio import duration_s, narration_scene_ids
from .lib import cache
from .lib.assets import find_asset
from .lib.config import BRAND_FILE, REMOTION_CONCURRENCY, TARGET_LUFS, TEMPLATE_DIR, heavy_lock
from .lib.schema import ScenesFile, Timeline

FPS = 30


def build_props(
    project: Path, sf: ScenesFile, tl: Timeline, reel_id: str, mode: str = "final", log=print,
) -> dict:
    """Remotion input props. In draft mode there is no audio and missing assets get a labelled placeholder."""
    brand = json.loads(BRAND_FILE.read_text())[sf.brand]
    tl_by_id = {s.id: s for s in tl.scenes}
    scenes = []
    for sid in narration_scene_ids(sf, reel_id):
        sc, t = sf.scene(sid), tl_by_id[sid]
        vis = sc.visual
        kind, file, placeholder = "text_card", None, None
        found = find_asset(project, sc) if vis.type != "text_card" else None
        if found:
            kind, file = found
        elif vis.type == "manual":
            placeholder = f"MANUAL: {vis.prompt or 'add an asset'}"
            log(f"scene {sid}: manual asset missing, using text card")
        elif vis.type in ("photo", "video", "chart"):
            placeholder = f"MISSING {vis.type.upper()}: {vis.query or ''}".strip()
            log(f"scene {sid}: no {vis.type} found, using text card")
        elif vis.type != "text_card":
            placeholder = f"{vis.type.upper()} (later phase)"
            log(f"scene {sid}: visual type {vis.type!r} not supported yet, using text card")
        clip_frames = None
        if kind == "video":
            clip_frames = int(duration_s(project / file) * FPS)
        scenes.append({
            "id": sid, "text": sc.text, "startS": t.start_s, "endS": t.end_s,
            "visual": {
                "type": kind, "file": file,
                "motion": "none" if vis.type == "chart" else (vis.motion or "slow-zoom-in"),
                "placeholder": placeholder if mode == "draft" else None,
                "clipFrames": clip_frames,
            },
            "emphasis": sc.emphasis,
            "words": [w.model_dump() for w in t.words],
            "overlay": sc.overlay.model_dump() if sc.overlay else None,
        })
    return {
        "reelId": reel_id, "fps": FPS, "width": 1080, "height": 1920,
        "durationInFrames": int(round(tl.duration_s * FPS)),
        "audioSrc": tl.audio_file if mode == "final" else None,
        "draft": mode == "draft",
        "brand": brand, "scenes": scenes,
        "emphasisMarks": [m.model_dump() for m in tl.emphasis_marks],
    }


def props_inputs(project: Path, props: dict) -> list[Path]:
    """Files whose content affects a render, for cache hashing."""
    files = [project / s["visual"]["file"] for s in props["scenes"] if s["visual"]["file"]]
    if props.get("audioSrc"):
        files.append(project / props["audioSrc"])
    return files


def remotion_render(project: Path, props: dict, out: Path, scale: float | None = None) -> None:
    props_path = project / "build" / f"props_{props['reelId']}{'_draft' if props.get('draft') else ''}.json"
    props_path.parent.mkdir(parents=True, exist_ok=True)
    props_path.write_text(json.dumps(props, ensure_ascii=False))
    cmd = [
        "npx", "remotion", "render", "src/Root.tsx", "Reel", str(out),
        f"--props={props_path}", f"--public-dir={project}",
        f"--concurrency={REMOTION_CONCURRENCY}", "--codec=h264",
    ]
    if scale:
        cmd.append(f"--scale={scale}")
    out.parent.mkdir(parents=True, exist_ok=True)
    with heavy_lock("remotion"):
        _run(cmd, cwd=TEMPLATE_DIR)


def _run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=True, **kw)


def loudnorm(src: Path, dst: Path) -> None:
    flt = f"loudnorm=I={TARGET_LUFS}:TP=-1.5:LRA=11"
    probe = subprocess.run(
        ["ffmpeg", "-hide_banner", "-i", str(src), "-af", flt + ":print_format=json", "-f", "null", "-"],
        capture_output=True, text=True, check=True,
    ).stderr
    stats = json.loads(probe[probe.rindex("{"): probe.rindex("}") + 1])
    second = (
        f"{flt}:measured_I={stats['input_i']}:measured_TP={stats['input_tp']}"
        f":measured_LRA={stats['input_lra']}:measured_thresh={stats['input_thresh']}"
        f":offset={stats['target_offset']}:linear=true"
    )
    _run([
        "ffmpeg", "-y", "-loglevel", "error", "-i", str(src), "-c:v", "copy",
        "-af", second, "-ar", "48000", "-c:a", "aac", "-b:a", "192k", str(dst),
    ])


def render_reel(project: Path, sf: ScenesFile, tl: Timeline, reel_id: str, log=print) -> Path:
    out = project / "out" / f"{reel_id}_9x16.mp4"
    cache_dir = project / "build" / "cache"
    props = build_props(project, sf, tl, reel_id, "final", log)
    digest = cache.hash_inputs(props, files=props_inputs(project, props))
    if cache.is_fresh(cache_dir, f"render_{reel_id}", digest, [out]):
        log(f"render {reel_id}: cached")
        return out

    raw = project / "build" / f"{reel_id}_raw.mp4"
    log(f"render {reel_id}: Remotion ({props['durationInFrames']} frames)")
    remotion_render(project, props, raw)
    log(f"render {reel_id}: normalizing loudness to {TARGET_LUFS} LUFS")
    out.parent.mkdir(parents=True, exist_ok=True)
    loudnorm(raw, out)
    raw.unlink(missing_ok=True)
    cache.mark(cache_dir, f"render_{reel_id}", digest)
    return out
