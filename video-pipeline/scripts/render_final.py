"""Render videos: Remotion per chapter (video only) -> FFmpeg concat -> narration muxed at -14 LUFS.

Reels are one chapter; long-form renders chapter by chapter so memory stays flat on an 8 GB Mac.
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

from . import animation, music, render_blender
from .align_audio import duration_s
from .lib import cache
from .lib.assets import find_asset
from .lib.config import BRAND_FILE, REMOTION_CONCURRENCY, TARGET_LUFS, TEMPLATE_DIR, heavy_lock
from .lib.progress import check_cancel, report, run_remotion
from .lib.schema import Scene, ScenesFile, Timeline
from .lib.targets import Target, chapters_for

FPS = 30
COMPOSITION = {"reel": "Reel", "long": "LongForm"}
SRT_MAX_WORDS, SRT_MAX_CHARS, SRT_PAUSE_S = 11, 84, 0.7


# ---------------------------------------------------------------- props


def _valid_chart(params: dict) -> bool:
    labels, values = params.get("labels"), params.get("values")
    return bool(labels) and isinstance(values, list) and len(labels) == len(values) and len(values) > 0


def visual_props(project: Path, scene: Scene, mode: str, log=print, kind: str = "reel") -> dict:
    """What Remotion should draw for a scene, falling back to a labelled text card."""
    v = scene.visual
    out = {"type": "text_card", "file": None, "motion": v.motion or "slow-zoom-in", "placeholder": None,
           "clipFrames": None, "params": None}

    def fallback(reason: str, label: str) -> dict:
        """No usable picture: a made animation, unless the scene asked to keep a plain text card."""
        if v.on_missing != "manual" and v.fallback != "text_card" and v.type in ("photo", "video", "manual", "chart"):
            log(f"scene {scene.id}: {reason}, using an animation")
            out.update(type="animation", params=animation.auto_params(scene), motion="none")
            out["placeholder"] = f"ANIMATION INSTEAD ({label})" if mode == "draft" else None
            return out
        log(f"scene {scene.id}: {reason}, using text card")
        out["placeholder"] = label if mode == "draft" else None
        return out

    if v.type == "text_card":
        return out
    if v.type == "animation":
        params = {**animation.auto_params(scene), **{k: val for k, val in v.params.items() if val not in (None, "", [])}}
        out.update(type="animation", params=params, motion="none")
        return out
    if v.type == "chart":
        if _valid_chart(v.params):
            out.update(type="chart", params=v.params, motion="none")
            return out
        found = find_asset(project, scene)
        if found:
            out.update(type="photo", file=found[1], motion="none")
            return out
        return fallback("chart has no labels/values", "CHART: add labels and values")
    if v.type == "stat":
        value = (scene.overlay.value if scene.overlay else None) or v.params.get("value")
        if value:
            label = (scene.overlay.label if scene.overlay else None) or v.params.get("label")
            out.update(type="stat", params={"value": value, "label": label})
            return out
        return fallback("stat has no value", "STAT: add an overlay value")
    if v.type == "blender":
        clip = render_blender.clip_path(scene.id, kind)
        if (project / clip).exists():
            out.update(type="blender", file=clip, clipFrames=int(duration_s(project / clip) * FPS))
            return out
        return fallback("Blender clip not rendered yet", f"3D SCENE ({v.template or 'template'}): renders at final")
    found = find_asset(project, scene)
    if found:
        kind, file = found
        out.update(type=kind, file=file)
        if kind == "video":
            out["clipFrames"] = int(duration_s(project / file) * FPS)
        return out
    if v.type == "manual":
        return fallback("manual asset missing", f"MANUAL: {v.prompt or 'add an asset'}")
    return fallback(f"no {v.type} found", f"MISSING {v.type.upper()}: {v.query or ''}".strip())


def chapter_frames(tl: Timeline, chapters: list[tuple[str, list[int]]]) -> list[tuple[int, int]]:
    """(start_frame, end_frame) per chapter. Boundaries sit on scene starts so the chapters tile the video exactly."""
    by_id = {s.id: s for s in tl.scenes}
    total = int(round(tl.duration_s * FPS))
    starts = [0] + [int(round(by_id[ids[0]].start_s * FPS)) for _, ids in chapters[1:]]
    ends = starts[1:] + [total]
    return list(zip(starts, ends))


def scene_frames(tl: Timeline, ids: list[int]) -> dict[int, tuple[int, int]]:
    """(start_frame, end_frame) of every scene. Scenes tile the video: each ends where the next begins."""
    by_id = {s.id: s for s in tl.scenes}
    total = int(round(tl.duration_s * FPS))
    starts = [0] + [int(round(by_id[i].start_s * FPS)) for i in ids[1:]]
    ends = starts[1:] + [total]
    return {i: (a, b) for i, a, b in zip(ids, starts, ends)}


def scene_props(project: Path, sf: ScenesFile, tl: Timeline, target: Target, sid: int, mode: str = "final", log=print) -> dict:
    """Props for rendering one scene on its own (times relative to the scene)."""
    return build_props(project, sf, tl, target, mode, ids=[sid], frames=scene_frames(tl, target.scene_ids)[sid])


def build_props(
    project: Path, sf: ScenesFile, tl: Timeline, target: Target, mode: str = "final",
    chapter: int | None = None, log=print, ids: list[int] | None = None, frames: tuple[int, int] | None = None,
) -> dict:
    """Remotion props for the whole video, one chapter of it, or an explicit scene list; times relative to its start."""
    brand = json.loads(BRAND_FILE.read_text())[sf.brand]
    chapters = chapters_for(sf, target)
    if ids is not None:
        title, (f0, f1) = None, frames
    elif chapter is None:
        ids, f0, f1, title = target.scene_ids, 0, chapter_frames(tl, chapters)[-1][1], None
    else:
        title, ids = chapters[chapter]
        f0, f1 = chapter_frames(tl, chapters)[chapter]
    off = f0 / FPS
    by_id = {s.id: s for s in tl.scenes}
    scenes = []
    for sid in ids:
        sc, t = sf.scene(sid), by_id[sid]
        scenes.append({
            "id": sid, "text": sc.text,
            "startS": round(t.start_s - off, 4), "endS": round(t.end_s - off, 4),
            "visual": visual_props(project, sc, mode, log, target.kind),
            "emphasis": sc.emphasis,
            "words": [{"w": w.w, "t": round(w.t - off, 4), "end": round((w.end or w.t) - off, 4)} for w in t.words],
            "overlay": sc.overlay.model_dump() if sc.overlay else None,
        })
    return {
        "reelId": target.id, "kind": target.kind, "fps": FPS, "width": target.width, "height": target.height,
        "durationInFrames": f1 - f0, "audioSrc": None, "draft": mode == "draft",
        "captions": target.kind == "reel", "chapterTitle": title if len(chapters) > 1 else None,
        "brand": brand, "scenes": scenes,
        "emphasisMarks": [m.model_dump() for m in tl.emphasis_marks if m.scene_id in ids],
    }


def template_sources() -> list[Path]:
    """The Remotion code and brand file: a change to either must re-render cached chapters."""
    src = TEMPLATE_DIR / "src"
    return sorted(src.rglob("*.ts*")) + [BRAND_FILE]


def props_inputs(project: Path, props: dict) -> list[Path]:
    """Files whose content affects a render, for cache hashing."""
    return [project / s["visual"]["file"] for s in props["scenes"] if s["visual"]["file"]] + template_sources()


# ---------------------------------------------------------------- rendering


def _run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=True, **kw)


def remotion_render(project: Path, props: dict, out: Path, scale: float | None = None, log=print) -> None:
    props_path = project / "build" / f"props_{out.stem}.json"
    props_path.parent.mkdir(parents=True, exist_ok=True)
    props_path.write_text(json.dumps(props, ensure_ascii=False))
    cmd = [
        "npx", "remotion", "render", "src/Root.tsx", COMPOSITION[props["kind"]], str(out),
        f"--props={props_path}", f"--public-dir={project}",
        f"--concurrency={REMOTION_CONCURRENCY}", "--codec=h264",
    ]
    if scale:
        cmd.append(f"--scale={scale}")
    out.parent.mkdir(parents=True, exist_ok=True)
    with heavy_lock("remotion"):
        run_remotion(cmd, TEMPLATE_DIR, log)


def template_digest() -> str:
    """Hash of the Remotion code and brand file (memoised by newest modification time)."""
    files = template_sources()
    stamp = max(f.stat().st_mtime for f in files)
    if _TEMPLATE_MEMO.get("stamp") != stamp:
        _TEMPLATE_MEMO.update(stamp=stamp, digest=cache.hash_inputs(files=files))
    return _TEMPLATE_MEMO["digest"]


_TEMPLATE_MEMO: dict = {}


def remotion_still(project: Path, props: dict, out: Path, frame: int, scale: float | None = None) -> None:
    props_path = project / "build" / f"props_still_{props['reelId']}_{out.stem}.json"
    props_path.parent.mkdir(parents=True, exist_ok=True)
    props_path.write_text(json.dumps(props, ensure_ascii=False))
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["npx", "remotion", "still", "src/Root.tsx", COMPOSITION[props["kind"]], str(out),
           f"--props={props_path}", f"--public-dir={project}", f"--frame={frame}", "--image-format=jpeg"]
    if scale:
        cmd.append(f"--scale={scale}")
    with heavy_lock("remotion"):
        run_remotion(cmd, TEMPLATE_DIR)


def render_chapters(
    project: Path, sf: ScenesFile, tl: Timeline, target: Target, mode: str, scale: float | None, log=print,
) -> tuple[list[Path], str]:
    """Render each chapter to build/chapters/. Returns (files, digest of everything that went in)."""
    chapters = chapters_for(sf, target)
    cache_dir = project / "build" / "cache"
    ch_dir = project / "build" / "chapters"
    files, digests = [], []
    for n, (title, _) in enumerate(chapters):
        check_cancel()
        props = build_props(project, sf, tl, target, mode, n, log)
        out = ch_dir / f"{'draft_' if mode == 'draft' else ''}{target.id}_{n + 1:02d}.mp4"
        digest = cache.hash_inputs(props, scale, files=props_inputs(project, props))
        stage = f"chapter_{mode}_{target.id}_{n + 1:02d}"
        label = f"chapter {n + 1}/{len(chapters)}" + (f" “{title}”" if len(chapters) > 1 else "")
        if cache.is_fresh(cache_dir, stage, digest, [out]):
            log(f"{target.id}: {label} cached")
        else:
            log(f"{target.id}: rendering {label}, {props['durationInFrames']} frames")
            report(None, f"{label}: starting")
            remotion_render(project, props, out, scale, log)
            cache.mark(cache_dir, stage, digest)
        files.append(out)
        digests.append(digest)
    return files, cache.hash_inputs(digests)


def concat(files: list[Path], dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if len(files) == 1:
        dst.write_bytes(files[0].read_bytes())
        return
    listing = dst.with_suffix(".txt")
    listing.write_text("".join(f"file '{f.resolve()}'\n" for f in files))
    _run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(listing), "-c", "copy", str(dst)])
    listing.unlink(missing_ok=True)


def mux_audio(video: Path, audio: Path, dst: Path) -> None:
    """Add the narration, normalized to -14 LUFS (two-pass, measured on the narration itself)."""
    flt = f"loudnorm=I={TARGET_LUFS}:TP=-1.5:LRA=11"
    probe = subprocess.run(
        ["ffmpeg", "-hide_banner", "-i", str(audio), "-af", flt + ":print_format=json", "-f", "null", "-"],
        capture_output=True, text=True, check=True,
    ).stderr
    stats = json.loads(probe[probe.rindex("{"): probe.rindex("}") + 1])
    second = (
        f"{flt}:measured_I={stats['input_i']}:measured_TP={stats['input_tp']}"
        f":measured_LRA={stats['input_lra']}:measured_thresh={stats['input_thresh']}"
        f":offset={stats['target_offset']}:linear=true"
    )
    tmp = dst.with_suffix(".tmp.mp4")
    _run([
        "ffmpeg", "-y", "-loglevel", "error", "-i", str(video), "-i", str(audio),
        "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-af", second,
        "-ar", "48000", "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart", str(tmp),
    ])
    tmp.replace(dst)


def _srt_time(t: float) -> str:
    ms = int(round(max(t, 0) * 1000))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def write_srt(tl: Timeline, dst: Path) -> int:
    """Sidecar subtitles from word timings. Returns the cue count."""
    cues: list[list] = []
    for sc in tl.scenes:
        cur: list = []
        for w in sc.words:
            gap = w.t - (cur[-1].end or cur[-1].t) if cur else 0
            if cur and (len(cur) >= SRT_MAX_WORDS or gap > SRT_PAUSE_S
                        or len(" ".join(x.w for x in cur + [w])) > SRT_MAX_CHARS):
                cues.append(cur)
                cur = []
            cur.append(w)
            if re.search(r"[.!?]$", w.w):
                cues.append(cur)
                cur = []
        if cur:
            cues.append(cur)
    lines = []
    for i, c in enumerate(cues, 1):
        end = max((c[-1].end or c[-1].t) + 0.15, c[0].t + 0.4)
        if i < len(cues):
            end = min(end, cues[i][0].t)
        lines += [str(i), f"{_srt_time(c[0].t)} --> {_srt_time(end)}", " ".join(w.w for w in c), ""]
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text("\n".join(lines))
    return len(cues)


# ---------------------------------------------------------------- parts (long-form): one clip per scene


def part_file(project: Path, target: Target, sid: int) -> Path:
    return project / "build" / "parts" / target.id / f"scene_{sid:02d}.mp4"


def part_digest(project: Path, sf: ScenesFile, tl: Timeline, target: Target, sid: int) -> tuple[str, dict]:
    props = scene_props(project, sf, tl, target, sid, "final", log=lambda *_: None)
    return cache.hash_inputs(props, template_digest(), files=props_inputs(project, props)), props


def render_part(project: Path, sf: ScenesFile, tl: Timeline, target: Target, sid: int, log=print) -> Path:
    """Render one scene to its own clip (cached by everything that shows in it)."""
    out = part_file(project, target, sid)
    digest, props = part_digest(project, sf, tl, target, sid)
    stage = f"part_{target.id}_{sid}"
    cache_dir = project / "build" / "cache"
    if cache.is_fresh(cache_dir, stage, digest, [out]):
        return out
    props = scene_props(project, sf, tl, target, sid, "final", log)
    remotion_render(project, props, out, None, log)
    cache.mark(cache_dir, stage, digest)
    return out


def build_parts(project: Path, sf: ScenesFile, tl: Timeline, target: Target, log=print) -> list[Path]:
    """Make every scene's clip (3D scenes first). Scenes whose content hasn't changed are skipped."""
    render_blender.render_for_target(project, sf, tl, target, log)
    ids = target.scene_ids
    files = []
    for n, sid in enumerate(ids, 1):
        check_cancel()
        out = part_file(project, target, sid)
        digest, _ = part_digest(project, sf, tl, target, sid)
        fresh = cache.is_fresh(project / "build" / "cache", f"part_{target.id}_{sid}", digest, [out])
        report((n - 1) / len(ids), f"scene {sid} ({n}/{len(ids)})" + (" cached" if fresh else ": rendering"))
        if not fresh:
            log(f"{target.id}: rendering scene {sid} ({n}/{len(ids)})")
        files.append(render_part(project, sf, tl, target, sid, log))
    return files


def part_preview(project: Path, sf: ScenesFile, tl: Timeline, target: Target, sid: int) -> Path:
    """The scene's clip with the matching slice of your narration, for checking timing."""
    clip = part_file(project, target, sid)
    out = clip.with_name(f"preview_{sid:02d}.mp4")
    f0, f1 = scene_frames(tl, target.scene_ids)[sid]
    audio = project / target.audio
    digest = cache.hash_inputs(part_digest(project, sf, tl, target, sid)[0], f0, f1, files=[audio])
    cache_dir = project / "build" / "cache"
    stage = f"preview_{target.id}_{sid}"
    if cache.is_fresh(cache_dir, stage, digest, [out]):
        return out
    _run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(clip), "-ss", f"{f0 / FPS:.3f}", "-t", f"{(f1 - f0) / FPS:.3f}",
          "-i", str(audio), "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-c:a", "aac", "-b:a", "128k",
          "-shortest", "-movflags", "+faststart", str(out)])
    cache.mark(cache_dir, stage, digest)
    return out


def assemble(project: Path, sf: ScenesFile, tl: Timeline, target: Target, log=print) -> Path:
    """Join the scene clips, add the narration at -14 LUFS, and write subtitles."""
    out = project / target.out
    files = build_parts(project, sf, tl, target, log)  # instant when every part is current
    audio = project / target.audio
    digest = cache.hash_inputs([part_digest(project, sf, tl, target, i)[0] for i in target.scene_ids],
                               music.fingerprint(project, target), files=[audio])
    stage = f"final_{target.id}"
    cache_dir = project / "build" / "cache"
    if cache.is_fresh(cache_dir, stage, digest, [out]):
        log(f"{target.id}: final cached")
        return out
    report(None, "joining scenes")
    joined = project / "build" / f"{target.id}_joined.mp4"
    concat(files, joined)
    finish_audio(project, target, joined, out, log)
    joined.unlink(missing_ok=True)
    cache.mark(cache_dir, stage, digest)
    return out


def clean_copy_path(target: Target) -> str:
    return target.out.rsplit(".", 1)[0] + "_no_music.mp4"


def finish_audio(project: Path, target: Target, video: Path, out: Path, log=print) -> None:
    """Add the narration (with the music under it, if the video has any) at -14 LUFS."""
    narration = project / target.audio
    track = music.get(project, target)
    out.parent.mkdir(parents=True, exist_ok=True)
    clean = project / clean_copy_path(target)
    if track:
        log(f"{target.id}: mixing music “{track.title}” under the narration "
            f"({track.volume_db:g} dB{', ducked while you speak' if track.duck else ''})")
        report(None, "mixing the music")
        mixed = music.mixed_audio(project, target, narration)
        log(f"{target.id}: normalizing loudness to {TARGET_LUFS} LUFS")
        report(None, "adding audio and normalizing loudness")
        mux_audio(video, mixed, out)
        mixed.unlink(missing_ok=True)
        if track.clean_copy and target.kind == "reel":
            mux_audio(video, narration, clean)
            log(f"{target.id}: kept a voice-only copy ({clean.name}) for adding music in the Instagram app")
        else:
            clean.unlink(missing_ok=True)
    else:
        log(f"{target.id}: adding narration, normalizing loudness to {TARGET_LUFS} LUFS")
        report(None, "adding narration and normalizing loudness")
        mux_audio(video, narration, out)
        clean.unlink(missing_ok=True)
    if target.kind == "long":
        tl_path = project / target.timeline
        from .lib.schema import Timeline

        n = write_srt(Timeline.model_validate_json(tl_path.read_text()), out.with_suffix(".srt"))
        log(f"{target.id}: wrote {out.with_suffix('.srt').name} ({n} cues)")


def render_target(project: Path, sf: ScenesFile, tl: Timeline, target: Target, log=print) -> Path:
    """Final render of one video. Long-form is built as one clip per scene and assembled; a reel is one render."""
    if target.kind == "long":
        return assemble(project, sf, tl, target, log)
    out = project / target.out
    cache_dir = project / "build" / "cache"

    render_blender.render_for_target(project, sf, tl, target, log)
    files, chapters_digest = render_chapters(project, sf, tl, target, "final", None, log)

    audio = project / target.audio
    digest = cache.hash_inputs(chapters_digest, music.fingerprint(project, target), files=[audio])
    stage = f"final_{target.id}"
    if cache.is_fresh(cache_dir, stage, digest, [out]):
        log(f"{target.id}: final cached")
        return out

    report(None, "joining chapters")
    joined = project / "build" / f"{target.id}_joined.mp4"
    concat(files, joined)
    finish_audio(project, target, joined, out, log)
    joined.unlink(missing_ok=True)
    cache.mark(cache_dir, stage, digest)
    return out
