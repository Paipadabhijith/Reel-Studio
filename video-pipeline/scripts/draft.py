"""`reel draft`: preview every video before any narration exists, timed at 150 wpm."""
from __future__ import annotations

import re
from pathlib import Path

from . import manual_inbox
from .lib import cache
from .lib.progress import report
from .lib.schema import ScenesFile, Timeline, TimelineScene, Word, load_scenes
from .lib.targets import Target, draft_out, list_targets
from .render_final import concat, render_chapters

WORDS_PER_S = 150 / 60
MIN_SCENE_S = 2.0
DRAFT_SCALE = {"reel": 0.5, "long": 0.4}  # 540x960 and 768x432: quick on an 8 GB M1, enough to judge visuals


def estimate_timeline(sf: ScenesFile, target: Target | str | None) -> Timeline:
    """Timing from word count alone. `target` may be a Target, a target id, or None for the first video."""
    from .lib.targets import get_target

    if not isinstance(target, Target):
        target = get_target(sf, target)
    t = 0.0
    scenes = []
    for sid in target.scene_ids:
        toks = [w for w in sf.scene(sid).text.split() if re.search(r"\w", w)]
        dur = max(len(toks) / WORDS_PER_S, MIN_SCENE_S)
        step = dur / max(len(toks), 1)
        words = [Word(w=w, t=round(t + i * step, 3), end=round(t + (i + 1) * step, 3)) for i, w in enumerate(toks)]
        scenes.append(TimelineScene(id=sid, start_s=round(t, 3), end_s=round(t + dur, 3), words=words))
        t += dur
    return Timeline(audio_file="", duration_s=round(t, 3), scenes=scenes)


def draft(
    project: Path, cont: bool = False, ask: manual_inbox.RightsPrompt | None = None, log=print,
    only: str | None = None,
) -> tuple[list[Path], list[int]]:
    """Render every video (or just `only`) as a draft. Returns (outputs, scene ids still missing a manual asset)."""
    if cont:
        if ask is None:
            raise ValueError("--continue needs a rights prompt")
        manual_inbox.ingest(project, ask, log)
    sf = load_scenes(project / "script" / "scenes.json")
    missing = [s.id for s in manual_inbox.write_readme(project, sf)]

    outs = []
    cache_dir = project / "build" / "cache"
    targets = [t for t in list_targets(sf) if only in (None, t.id)]
    for n, target in enumerate(targets, 1):
        tl = estimate_timeline(sf, target)
        files, digest_in = render_chapters(project, sf, tl, target, "draft", DRAFT_SCALE[target.kind], log)
        out = project / draft_out(target)
        digest = cache.hash_inputs(digest_in)
        stage = f"draft_{target.id}"
        if cache.is_fresh(cache_dir, stage, digest, [out]):
            log(f"draft {target.id}: cached")
        else:
            report(None, f"joining {target.id} chapters")
            concat(files, out)
            cache.mark(cache_dir, stage, digest)
        log(f"draft {target.id}: {tl.duration_s / 60:.1f} min" if tl.duration_s >= 90 else f"draft {target.id}: {tl.duration_s:.0f}s")
        outs.append(out)
    return outs, missing
