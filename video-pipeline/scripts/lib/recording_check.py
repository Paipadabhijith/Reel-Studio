"""Dead air in a narration take: long pauses inside it, and silence before the first word or after the last.

On screen a pause is a picture that sits still with nothing new said, which is where viewers swipe away.
Uses ffmpeg's silencedetect, so it runs in about a second and needs no transcription.
(The idea of checking takes for dead air before editing is adapted from youtube-agent-skill, MIT licence.)
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

NOISE_DB = -38          # quieter than this counts as silence (room tone sits well below a voice)
MIN_SILENCE = 0.5       # shorter gaps are breaths, not pauses
PAUSE_LIMIT = {"reel": 1.0, "long": 1.6}   # a pause longer than this inside the take is flagged
EDGE_LIMIT = 0.8        # silence before the first word or after the last


def silences(audio: Path) -> tuple[list[tuple[float, float]], float]:
    """[(start, end)] of every silence, and the file's duration."""
    out = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(audio), "-af",
                          f"silencedetect=noise={NOISE_DB}dB:d={MIN_SILENCE}", "-f", "null", "-"],
                         capture_output=True, text=True).stderr
    dur = 0.0
    m = re.search(r"Duration: (\d+):(\d+):([\d.]+)", out)
    if m:
        dur = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
    starts = [float(x) for x in re.findall(r"silence_start: ([\d.]+)", out)]
    ends = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", out)]
    spans = list(zip(starts, ends + [dur] * (len(starts) - len(ends))))
    return spans, dur


def check(audio: Path, kind: str = "reel") -> dict:
    spans, dur = silences(audio)
    limit = PAUSE_LIMIT.get(kind, 1.0)
    lead = next((e - s for s, e in spans if s <= 0.05), 0.0)
    tail = next((e - s for s, e in spans if e >= dur - 0.05), 0.0)
    inner = [(round(s, 1), round(e - s, 1)) for s, e in spans if s > 0.05 and e < dur - 0.05 and e - s > limit]
    warnings = []
    if lead > EDGE_LIMIT:
        warnings.append(f"{lead:.1f} s of silence before you start: the video opens on a still picture")
    if inner:
        where = ", ".join(f"{_mmss(s)} ({n:.1f} s)" for s, n in inner[:6]) + (" …" if len(inner) > 6 else "")
        warnings.append(f"{len(inner)} pause(s) over {limit:.1f} s: {where}")
    if tail > EDGE_LIMIT + 0.7:
        warnings.append(f"{tail:.1f} s of silence after the last word")
    dead = sum(n - limit for _, n in inner) + max(0.0, lead - EDGE_LIMIT)
    return {"duration": round(dur, 1), "lead": round(lead, 1), "tail": round(tail, 1), "pauses": inner,
            "dead_air": round(dead, 1), "warnings": warnings}


def _mmss(t: float) -> str:
    return f"{int(t // 60)}:{t % 60:04.1f}"


def cached_check(project: Path, audio_rel: str, kind: str) -> dict | None:
    """The check for a take, recomputed only when the take changes. None if there is no take."""
    audio = project / audio_rel
    if not audio.exists():
        return None
    stamp = f"{audio.stat().st_mtime_ns}-{audio.stat().st_size}"
    cache = project / "build" / "cache" / f"recording_check_{Path(audio_rel).stem}.json"
    if cache.exists():
        data = json.loads(cache.read_text())
        if data.get("stamp") == stamp:
            return data
    data = {**check(audio, kind), "stamp": stamp}
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(data, indent=1))
    return data
