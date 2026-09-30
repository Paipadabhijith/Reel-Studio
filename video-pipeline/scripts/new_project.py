"""`reel new <slug>`: scaffold a project folder."""
from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

from .lib.config import PROJECTS_DIR

SUBDIRS = [
    "input/articles", "script", "assets/images", "assets/videos", "inbox",
    "audio", "build/blender", "build/chapters", "build/cache", "out",
]

BRIEF_TEMPLATE = """# Brief

- topic:
- angle:
- target_audience:
- formats: both        # reel / long / both
- reel_count: 1
- tone:
- language: {language}  # en / hi / hinglish
- source_urls:
"""


def starter_scenes(slug: str, language: str) -> dict:
    return {
        "project": slug,
        "format": "reel",
        "brand": "default",
        "language": language,
        "reels": [{"id": "reel_01", "scene_ids": [1, 2, 3], "hook_scene": 1}],
        "scenes": [
            {
                "id": 1,
                "text": "Ek second ruko, yeh baat sabko pata honi chahiye.",
                "emphasis": ["ruko"],
                "visual": {"type": "photo", "file": "assets/images/scene_01.jpg", "motion": "slow-zoom-in"},
            },
            {
                "id": 2,
                "text": "Aaj hum dekhenge ki yeh pipeline kaise kaam karti hai.",
                "emphasis": ["pipeline"],
                "visual": {"type": "photo", "file": "assets/images/scene_02.jpg", "motion": "slow-zoom-out"},
            },
            {
                "id": 3,
                "text": "Bas ek voice record karo, baaki sab automatic.",
                "emphasis": ["automatic"],
                "visual": {"type": "text_card"},
            },
        ],
    }


def scaffold(slug: str, language: str = "hinglish", open_brief: bool = True) -> Path:
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", slug):
        raise ValueError("slug must be lowercase letters, digits, '-' or '_'")
    root = PROJECTS_DIR / slug
    if root.exists():
        raise FileExistsError(f"{root} already exists")
    for d in SUBDIRS:
        (root / d).mkdir(parents=True)
    (root / "input/brief.md").write_text(BRIEF_TEMPLATE.format(language=language))
    for f in ("script.md", "hooks.md", "facts.md"):
        (root / "script" / f).write_text("")
    (root / "script/scenes.json").write_text(
        json.dumps(starter_scenes(slug, language), indent=2, ensure_ascii=False)
    )
    (root / "assets/credits.json").write_text("[]")
    (root / "inbox/README.txt").write_text("No manual scenes pending.\n")
    if open_brief and os.getenv("EDITOR"):
        subprocess.run([os.environ["EDITOR"], str(root / "input/brief.md")], check=False)
    return root
