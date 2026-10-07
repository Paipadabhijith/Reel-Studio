"""Which videos a project produces, and where each one's audio, timeline and output live.

A target is a reel id ("reel_01") or "long". The first target keeps the original single-video
file names (audio/narration.m4a, build/timeline.json) so existing projects keep working;
every other target gets its own files.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .schema import ScenesFile

LONG = "long"


@dataclass(frozen=True)
class Target:
    id: str
    kind: str            # "reel" | "long"
    scene_ids: list[int]
    label: str
    primary: bool
    audio: str           # relative to the project
    timeline: str
    tone: str
    out: str

    @property
    def width(self) -> int:
        return 1080 if self.kind == "reel" else 1920

    @property
    def height(self) -> int:
        return 1920 if self.kind == "reel" else 1080


def long_scene_ids(sf: ScenesFile) -> list[int]:
    if not sf.long_form:
        return []
    return [i for ch in sf.long_form.chapters for i in ch.scene_ids]


def list_targets(sf: ScenesFile) -> list[Target]:
    raw: list[tuple[str, str, list[int], str]] = []
    if sf.format in ("reel", "both"):
        raw += [(r.id, "reel", r.scene_ids, f"Reel {r.id}") for r in sf.reels]
    if sf.format in ("long", "both") and sf.long_form and long_scene_ids(sf):
        raw.append((LONG, "long", long_scene_ids(sf), "Long-form 16:9"))
    if not raw:  # hand-written project with no reels listed: all scenes, in order
        raw = [("reel_01", "reel", [s.id for s in sf.scenes], "Reel")]
    out = []
    for n, (tid, kind, ids, label) in enumerate(raw):
        primary = n == 0
        suffix = "9x16" if kind == "reel" else "16x9"
        out.append(Target(
            id=tid, kind=kind, scene_ids=ids, label=label, primary=primary,
            audio="audio/narration.m4a" if primary else f"audio/{tid}.m4a",
            timeline="build/timeline.json" if primary else f"build/timeline_{tid}.json",
            tone="build/tone.json" if primary else f"build/tone_{tid}.json",
            out=f"out/{tid}_{suffix}.mp4",
        ))
    return out


def get_target(sf: ScenesFile, target_id: str | None) -> Target:
    targets = list_targets(sf)
    if not target_id:
        return targets[0]
    for t in targets:
        if t.id == target_id:
            return t
    raise ValueError(f"unknown video {target_id!r}; this project has: {', '.join(t.id for t in targets)}")


def chapters_for(sf: ScenesFile, target: Target) -> list[tuple[str, list[int]]]:
    """Chapters of a target. Reels (and long-form without chapters) are one chapter."""
    if target.kind == LONG and sf.long_form:
        return [(c.title, c.scene_ids) for c in sf.long_form.chapters if c.scene_ids]
    return [(target.label, target.scene_ids)]


def draft_out(target: Target) -> str:
    return f"out/draft_{target.id}.mp4"


def audio_exists(project: Path, target: Target) -> bool:
    return (project / target.audio).exists()
