"""Emphasis and pause detection with librosa."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from .lib.schema import EmphasisMark, TimelineScene

PAUSE_S = 0.4
PEAK_RATIO = 1.3
HOP = 512


def _norm(w: str) -> str:
    return "".join(c for c in w.lower() if c.isalnum())


def analyze(wav_path: Path, scenes: list[TimelineScene], emphasis: dict[int, list[str]]) -> list[EmphasisMark]:
    import librosa

    y, sr = librosa.load(str(wav_path), sr=16000, mono=True)
    rms = librosa.feature.rms(y=y, hop_length=HOP)[0]
    frame_t = librosa.frames_to_time(np.arange(len(rms)), sr=sr, hop_length=HOP)

    marks: list[EmphasisMark] = []
    for sc in scenes:
        if not sc.words:
            continue
        lo, hi = sc.start_s, sc.end_s
        in_scene = rms[(frame_t >= lo) & (frame_t < hi)]
        baseline = float(np.median(in_scene)) if in_scene.size else 0.0
        targets = {_norm(e) for phrase in emphasis.get(sc.id, []) for e in phrase.split()}
        for i, w in enumerate(sc.words):
            end = w.end if w.end is not None else w.t
            if _norm(w.w) in targets and baseline > 0:
                seg = rms[(frame_t >= w.t) & (frame_t <= end)]
                if seg.size and float(seg.max()) >= PEAK_RATIO * baseline:
                    marks.append(EmphasisMark(scene_id=sc.id, word_index=i, kind="loudness_peak"))
            if i + 1 < len(sc.words) and sc.words[i + 1].t - end > PAUSE_S:
                marks.append(EmphasisMark(scene_id=sc.id, word_index=i, kind="pause_after"))
    return marks


def write_tone(path: Path, marks: list[EmphasisMark]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"emphasis_marks": [m.model_dump() for m in marks]}, indent=2))
