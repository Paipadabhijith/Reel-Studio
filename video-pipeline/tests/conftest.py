import json
from pathlib import Path

import pytest

from scripts.new_project import SUBDIRS


def make_project(root: Path, scenes: list[dict], reels: list[dict] | None = None, language: str = "en") -> Path:
    proj = root / "proj"
    for d in SUBDIRS:
        (proj / d).mkdir(parents=True, exist_ok=True)
    (proj / "assets" / "credits.json").write_text("[]")
    ids = [s["id"] for s in scenes]
    (proj / "script" / "scenes.json").write_text(json.dumps({
        "project": "proj", "format": "reel", "language": language,
        "reels": reels if reels is not None else [{"id": "reel_01", "scene_ids": ids, "hook_scene": ids[0]}],
        "scenes": scenes,
    }))
    return proj


@pytest.fixture
def project_factory(tmp_path):
    return lambda scenes, **kw: make_project(tmp_path, scenes, **kw)


@pytest.fixture(autouse=True)
def fake_keys(monkeypatch):
    monkeypatch.setenv("PEXELS_API_KEY", "test-pexels")
    monkeypatch.setenv("UNSPLASH_ACCESS_KEY", "test-unsplash")
    monkeypatch.setenv("COVERR_API_KEY", "test-coverr-secret")
    monkeypatch.setenv("PIXABAY_API_KEY", "test-pixabay-secret")  # never the real key from .env
    import scripts.generate_script as _G
    monkeypatch.setattr(_G, "read_voice", lambda: None)  # never your real shared/voice.md
    import scripts.lib.voice as _V
    monkeypatch.setattr(_V, "read_voice", lambda *a: None)
