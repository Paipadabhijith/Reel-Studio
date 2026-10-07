"""Pydantic models for scenes.json, timeline.json and credits.json."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, model_validator

VisualType = Literal["photo", "video", "chart", "text_card", "stat", "manual", "blender"]
Orientation = Literal["portrait", "landscape", "square"]


class Visual(BaseModel):
    type: VisualType
    query: str | None = None
    orientation: Orientation | None = None
    motion: str | None = None
    prompt: str | None = None
    fallback: str | None = None
    template: str | None = None
    params: dict = Field(default_factory=dict)
    file: str | None = None  # explicit asset path relative to the project dir
    source: Literal["stock", "wikimedia"] | None = None  # where fetch looks first
    downgraded_from: VisualType | None = None  # set when fetch found nothing and fell back to manual


class Overlay(BaseModel):
    type: Literal["stat", "text"]
    value: str | None = None
    label: str | None = None


class Scene(BaseModel):
    id: int
    text: str
    emphasis: list[str] = Field(default_factory=list)
    visual: Visual
    overlay: Overlay | None = None


class Chapter(BaseModel):
    title: str
    scene_ids: list[int]


class LongForm(BaseModel):
    chapters: list[Chapter]


class Reel(BaseModel):
    id: str
    scene_ids: list[int]
    hook_scene: int


class ScenesFile(BaseModel):
    project: str
    format: Literal["reel", "long", "both"] = "both"
    brand: str = "default"
    language: Literal["en", "hi", "hinglish"] = "hinglish"
    long_form: LongForm | None = None
    reels: list[Reel] = Field(default_factory=list)
    scenes: list[Scene]

    @model_validator(mode="after")
    def _check_refs(self) -> "ScenesFile":
        ids = [s.id for s in self.scenes]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate scene ids")
        known = set(ids)
        for r in self.reels:
            missing = [i for i in r.scene_ids if i not in known]
            if missing:
                raise ValueError(f"reel {r.id} references unknown scenes {missing}")
            if r.hook_scene not in r.scene_ids:
                raise ValueError(f"reel {r.id} hook_scene not in its scene_ids")
        if self.long_form:
            for c in self.long_form.chapters:
                missing = [i for i in c.scene_ids if i not in known]
                if missing:
                    raise ValueError(f"chapter {c.title!r} references unknown scenes {missing}")
        return self

    def scene(self, sid: int) -> Scene:
        return next(s for s in self.scenes if s.id == sid)


class Word(BaseModel):
    w: str
    t: float
    end: float | None = None


class TimelineScene(BaseModel):
    id: int
    start_s: float
    end_s: float
    words: list[Word] = Field(default_factory=list)
    match: float | None = None  # share of this scene's words found in the recording (None: not measured)


class EmphasisMark(BaseModel):
    scene_id: int
    word_index: int
    kind: Literal["loudness_peak", "pause_after"]


class Timeline(BaseModel):
    audio_file: str
    duration_s: float
    scenes: list[TimelineScene]
    emphasis_marks: list[EmphasisMark] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_order(self) -> "Timeline":
        prev_end = 0.0
        for s in self.scenes:
            if s.end_s < s.start_s:
                raise ValueError(f"scene {s.id}: end before start")
            if s.start_s < prev_end - 1e-6:
                raise ValueError(f"scene {s.id}: overlaps previous scene")
            prev_end = s.end_s
        return self


class Credit(BaseModel):
    scene_id: int
    source: str
    license: str
    url: str
    attribution_text: str
    added_by: str


def load_scenes(path: Path) -> ScenesFile:
    return ScenesFile.model_validate_json(Path(path).read_text())


def load_timeline(path: Path) -> Timeline:
    return Timeline.model_validate_json(Path(path).read_text())


def dump_json(model: BaseModel, path: Path) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(model.model_dump(mode="json"), indent=2, ensure_ascii=False))
