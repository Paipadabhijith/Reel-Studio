"""`reel draft`: preview Reels before any narration exists, timed at 150 wpm."""
from __future__ import annotations

import re
from pathlib import Path

from . import manual_inbox
from .align_audio import narration_scene_ids
from .lib import cache
from .lib.schema import ScenesFile, Timeline, TimelineScene, Word, load_scenes
from .render_final import build_props, props_inputs, remotion_render

WORDS_PER_S = 150 / 60
MIN_SCENE_S = 2.0
DRAFT_SCALE = 0.5  # 540x960: fast on an 8 GB M1, good enough to judge visuals


def estimate_timeline(sf: ScenesFile, reel_id: str | None) -> Timeline:
    t = 0.0
    scenes = []
    for sid in narration_scene_ids(sf, reel_id):
        toks = [w for w in sf.scene(sid).text.split() if re.search(r"\w", w)]
        dur = max(len(toks) / WORDS_PER_S, MIN_SCENE_S)
        step = dur / max(len(toks), 1)
        words = [Word(w=w, t=round(t + i * step, 3), end=round(t + (i + 1) * step, 3)) for i, w in enumerate(toks)]
        scenes.append(TimelineScene(id=sid, start_s=round(t, 3), end_s=round(t + dur, 3), words=words))
        t += dur
    return Timeline(audio_file="", duration_s=round(t, 3), scenes=scenes)


def draft(
    project: Path, cont: bool = False, ask: manual_inbox.RightsPrompt | None = None, log=print,
) -> tuple[list[Path], list[int]]:
    """Render every reel as a draft. Returns (outputs, scene ids still missing a manual asset)."""
    if cont:
        if ask is None:
            raise ValueError("--continue needs a rights prompt")
        manual_inbox.ingest(project, ask, log)
    sf = load_scenes(project / "script" / "scenes.json")
    missing = [s.id for s in manual_inbox.write_readme(project, sf)]
    if sf.format in ("long", "both") and sf.long_form:
        log("draft: long-form draft arrives in Phase 3; rendering reels only")
    reel_ids = [r.id for r in sf.reels] or [None]

    outs = []
    cache_dir = project / "build" / "cache"
    for rid in reel_ids:
        tl = estimate_timeline(sf, rid)
        name = rid or "reel_01"
        props = build_props(project, sf, tl, name, "draft", log)
        out = project / "out" / f"draft_{name}.mp4"
        digest = cache.hash_inputs(props, DRAFT_SCALE, files=props_inputs(project, props))
        if cache.is_fresh(cache_dir, f"draft_{name}", digest, [out]):
            log(f"draft {name}: cached")
        else:
            log(f"draft {name}: rendering {tl.duration_s:.1f}s at {DRAFT_SCALE}x scale")
            remotion_render(project, props, out, scale=DRAFT_SCALE)
            cache.mark(cache_dir, f"draft_{name}", digest)
        outs.append(out)
    return outs, missing
