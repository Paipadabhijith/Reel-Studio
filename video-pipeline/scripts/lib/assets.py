"""Where a scene's asset lives on disk, and credits.json upkeep."""
from __future__ import annotations

import json
from pathlib import Path

from .schema import Credit, Scene

IMG_EXTS = ("jpg", "jpeg", "png", "webp")
VID_EXTS = ("mp4", "mov")


def image_path(scene_id: int, ext: str = "jpg") -> str:
    return f"assets/images/scene_{scene_id:02d}.{ext}"


def video_path(scene_id: int, ext: str = "mp4") -> str:
    return f"assets/videos/scene_{scene_id:02d}.{ext}"


def chart_path(scene_id: int) -> str:
    return f"assets/images/scene_{scene_id:02d}_chart.png"


def find_asset(project: Path, scene: Scene) -> tuple[str, str] | None:
    """Return (kind, relative path) for the scene's asset, kind in {photo, video}."""
    declared = scene.visual.file
    if declared and (project / declared).exists():
        return ("video" if declared.rsplit(".", 1)[-1].lower() in VID_EXTS else "photo", declared)
    if scene.visual.type == "chart" and (project / chart_path(scene.id)).exists():
        return ("photo", chart_path(scene.id))
    for ext in VID_EXTS:
        if (project / video_path(scene.id, ext)).exists():
            return ("video", video_path(scene.id, ext))
    for ext in IMG_EXTS:
        if (project / image_path(scene.id, ext)).exists():
            return ("photo", image_path(scene.id, ext))
    return None


def remove_scene_assets(project: Path, scene_id: int) -> None:
    for ext in IMG_EXTS:
        (project / image_path(scene_id, ext)).unlink(missing_ok=True)
    for ext in VID_EXTS:
        (project / video_path(scene_id, ext)).unlink(missing_ok=True)


def load_credits(project: Path) -> list[Credit]:
    p = project / "assets" / "credits.json"
    if not p.exists() or not p.read_text().strip():
        return []
    return [Credit.model_validate(c) for c in json.loads(p.read_text())]


def upsert_credit(project: Path, credit: Credit) -> None:
    """One credit per scene: a new asset for a scene replaces its old credit."""
    credits = [c for c in load_credits(project) if c.scene_id != credit.scene_id]
    credits.append(credit)
    credits.sort(key=lambda c: c.scene_id)
    p = project / "assets" / "credits.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps([c.model_dump() for c in credits], indent=2, ensure_ascii=False))


def drop_credit(project: Path, scene_id: int) -> None:
    credits = [c for c in load_credits(project) if c.scene_id != scene_id]
    (project / "assets" / "credits.json").write_text(
        json.dumps([c.model_dump() for c in credits], indent=2, ensure_ascii=False)
    )
