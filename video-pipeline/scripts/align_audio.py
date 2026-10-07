"""Transcribe narration with mlx-whisper and align it to the script per scene.

Script words get the timestamps of the transcript words they match, so captions
show the script's own spelling (Roman Hinglish) even if Whisper emits Devanagari.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

import numpy as np
from rapidfuzz import fuzz, process

from . import analyze_tone
from .lib import cache
from .lib.progress import check_cancel, report
from .lib.config import WHISPER_LANG, WHISPER_MODEL, heavy_lock
from .lib.schema import ScenesFile, Timeline, TimelineScene, Word, dump_json
from .lib.targets import get_target

DEVANAGARI = re.compile(r"[ऀ-ॿ]")
GAP = -0.35
MIN_MATCH = 0.55


def narration_scene_ids(sf: ScenesFile, target_id: str | None = None) -> list[int]:
    """Scenes in the order they are narrated."""
    return get_target(sf, target_id).scene_ids


def normalize(word: str) -> str:
    if DEVANAGARI.search(word):
        from indic_transliteration.sanscript import DEVANAGARI as DEV, ITRANS, transliterate

        word = transliterate(word, DEV, ITRANS)
    word = word.lower()
    word = re.sub(r"[^a-z0-9]", "", word)
    # collapse spelling variation common in Roman Hindi (aa/a, ee/i, oo/u, doubled letters)
    word = re.sub(r"(.)\1+", r"\1", word)
    return word.replace("h", "") if len(word) > 3 else word


def to_wav(audio: Path, wav: Path) -> None:
    wav.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", str(audio), "-ac", "1", "-ar", "16000", str(wav)],
        check=True,
    )


def duration_s(audio: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(audio)],
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    return float(out)


def transcribe(audio: Path, language: str | None) -> list[dict]:
    import mlx_whisper

    with heavy_lock("transcribe"):
        result = mlx_whisper.transcribe(
            str(audio), path_or_hf_repo=WHISPER_MODEL, word_timestamps=True, language=language,
        )
    words = []
    for seg in result["segments"]:
        for w in seg.get("words", []):
            text = w["word"].strip()
            if text:
                words.append({"w": text, "start": float(w["start"]), "end": float(w["end"])})
    return words


def align_tokens(script_norm: list[str], heard_norm: list[str]) -> list[int | None]:
    """Needleman-Wunsch over token similarity. Returns heard index (or None) per script token."""
    n, m = len(script_norm), len(heard_norm)
    if n == 0 or m == 0:
        return [None] * n
    sim = process.cdist(script_norm, heard_norm, scorer=fuzz.ratio, dtype=np.float32) / 100.0
    score = np.where(sim >= MIN_MATCH, sim, -0.5)  # weak matches count as mismatches
    dp = np.zeros((n + 1, m + 1), dtype=np.float32)
    dp[:, 0] = np.arange(n + 1) * GAP
    dp[0, :] = np.arange(m + 1) * GAP
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            dp[i, j] = max(dp[i - 1, j - 1] + score[i - 1, j - 1], dp[i - 1, j] + GAP, dp[i, j - 1] + GAP)
    out: list[int | None] = [None] * n
    i, j = n, m
    while i > 0 and j > 0:
        if dp[i, j] == dp[i - 1, j - 1] + score[i - 1, j - 1]:
            if sim[i - 1, j - 1] >= MIN_MATCH:
                out[i - 1] = j - 1
            i, j = i - 1, j - 1
        elif dp[i, j] == dp[i - 1, j] + GAP:
            i -= 1
        else:
            j -= 1
    return out


def _fill_times(times: list[tuple[float, float] | None], lo: float, hi: float) -> list[tuple[float, float]]:
    """Interpolate (start, end) for unmatched tokens between their matched neighbours."""
    n = len(times)
    out: list[tuple[float, float]] = [(0.0, 0.0)] * n
    i = 0
    while i < n:
        if times[i] is not None:
            out[i] = times[i]  # type: ignore[assignment]
            i += 1
            continue
        j = i
        while j < n and times[j] is None:
            j += 1
        left = out[i - 1][1] if i > 0 else lo
        right = times[j][0] if j < n else hi  # type: ignore[index]
        right = max(right, left)
        step = (right - left) / (j - i)
        for k in range(i, j):
            out[k] = (left + (k - i) * step, left + (k - i + 1) * step)
        i = j
    return out


def align(
    project: Path, sf: ScenesFile, target_id: str | None = None, log=print,
) -> Timeline:
    """Align one video's recording (a reel id or "long") to its scenes. Default: the first video."""
    target = get_target(sf, target_id)
    audio = project / target.audio
    if not audio.exists():
        raise FileNotFoundError(f"missing {audio}; record narration for {target.label} first")
    ids = target.scene_ids
    scenes = [sf.scene(i) for i in ids]

    cache_dir = project / "build" / "cache"
    timeline_path = project / target.timeline
    tone_path = project / target.tone
    stage = f"align_{target.id}"
    digest = cache.hash_inputs(
        [s.text for s in scenes], sf.language, WHISPER_MODEL, ids, files=[audio],
    )
    if cache.is_fresh(cache_dir, stage, digest, [timeline_path, tone_path]):
        log(f"align {target.id}: cached")
        return Timeline.model_validate_json(timeline_path.read_text())

    wav = cache_dir / f"narration_{target.id}_16k.wav"
    to_wav(audio, wav)
    dur = duration_s(audio)

    lang = WHISPER_LANG[sf.language]
    log(f"align: transcribing ({WHISPER_MODEL}, language={lang})")
    report(None, "transcribing narration with Whisper")
    check_cancel()
    heard = transcribe(audio, lang)
    check_cancel()
    if not heard:
        raise RuntimeError("Whisper returned no words; is the recording silent?")
    heard_norm = [normalize(h["w"]) for h in heard]

    script_words: list[tuple[int, str]] = []  # (scene index, token)
    for si, s in enumerate(scenes):
        for tok in s.text.split():
            if re.search(r"\w", tok):
                script_words.append((si, tok))
    script_norm = [normalize(t) for _, t in script_words]

    match = align_tokens(script_norm, heard_norm)
    matched = sum(1 for m in match if m is not None)
    ratio = matched / max(len(match), 1)
    log(f"align: matched {matched}/{len(match)} script words ({ratio:.0%})")
    if ratio < 0.4:
        log("align: WARNING low match; script text may differ a lot from the recording")
    report(None, f"voice matched {ratio:.0%} of the script")

    raw = [(heard[m]["start"], heard[m]["end"]) if m is not None else None for m in match]
    times = _fill_times(raw, 0.0, dur)

    tl_scenes: list[TimelineScene] = []
    for si, s in enumerate(scenes):
        idxs = [k for k, (sj, _) in enumerate(script_words) if sj == si]
        words = [
            Word(w=script_words[k][1], t=round(times[k][0], 3), end=round(times[k][1], 3)) for k in idxs
        ]
        start = words[0].t if words else (tl_scenes[-1].end_s if tl_scenes else 0.0)
        hit = sum(1 for k in idxs if match[k] is not None)
        tl_scenes.append(TimelineScene(id=s.id, start_s=start, end_s=start, words=words,
                                       match=round(hit / len(idxs), 3) if idxs else None))
    # scenes are contiguous: each runs until the next begins, first starts at 0, last ends at audio end
    tl_scenes[0].start_s = 0.0
    for a, b in zip(tl_scenes, tl_scenes[1:]):
        a.end_s = max(b.start_s, a.start_s)
    tl_scenes[-1].end_s = max(dur, tl_scenes[-1].start_s)

    report(None, "analyzing emphasis and pauses")
    marks = analyze_tone.analyze(wav, tl_scenes, {s.id: s.emphasis for s in scenes})
    analyze_tone.write_tone(tone_path, marks)

    timeline = Timeline(
        audio_file=target.audio, duration_s=round(dur, 3), scenes=tl_scenes, emphasis_marks=marks,
    )
    dump_json(timeline, timeline_path)
    cache.mark(cache_dir, stage, digest)
    return timeline
