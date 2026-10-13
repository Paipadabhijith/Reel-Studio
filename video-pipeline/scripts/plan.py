"""The plan: scenes.json as an editable storyboard, plus the lock that gates fetching and building.

All edits go through ScenesFile validation, so a bad edit is rejected instead of corrupting the file.
Every save keeps a timestamped copy in build/history/ (the last 30).
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from pydantic import ValidationError

from . import animation
from .lib import india
from .lib.schema import Direction, Scene, ScenesFile, dump_json, load_scenes

VISUAL_TYPES = ("photo", "video", "auto", "animation", "title3d", "chart", "stat", "blender", "manual", "text_card")
MOTIONS = ("slow-zoom-in", "slow-zoom-out", "pan-left", "pan-right")
CAMERAS = ("top_down_tilt", "top_down", "orbit")
CHART_KINDS = ("bar", "line", "pie")
KEEP_HISTORY = 30


class PlanError(ValueError):
    """A user-facing reason an edit was refused."""


def _csv(text: str) -> list[str]:
    return [p.strip() for p in (text or "").replace("\n", ",").split(",") if p.strip()]


def scenes_path(project: Path) -> Path:
    return project / "script" / "scenes.json"


def load(project: Path) -> ScenesFile:
    return load_scenes(scenes_path(project))


def save(project: Path, sf: ScenesFile) -> None:
    try:
        sf = ScenesFile.model_validate(sf.model_dump())  # re-check references (reels, chapters, hooks)
    except ValidationError as e:
        raise PlanError(_first_error(e))
    path = scenes_path(project)
    if path.exists():
        hist = project / "build" / "history"
        hist.mkdir(parents=True, exist_ok=True)
        (hist / f"scenes-{time.strftime('%Y%m%d-%H%M%S')}.json").write_text(path.read_text())
        for old in sorted(hist.glob("scenes-*.json"))[:-KEEP_HISTORY]:
            old.unlink(missing_ok=True)
    dump_json(sf, path)


def _first_error(e: ValidationError) -> str:
    err = e.errors()[0]
    where = ".".join(str(x) for x in err["loc"] if x not in ("scenes",))
    return f"{where}: {err['msg']}" if where else err["msg"]


# ---------------------------------------------------------------- editing one scene


def apply_form(sf: ScenesFile, sid: int, form) -> Scene:
    """Update scene `sid` from submitted form fields. Raises PlanError with a plain-language reason."""
    old = next((s for s in sf.scenes if s.id == sid), None)
    if old is None:
        raise PlanError(f"scene {sid} does not exist")
    text = " ".join((form.get("text") or "").split())
    if not text:
        raise PlanError("the narration text can't be empty")
    current = "title3d" if old.visual.type == "blender" and old.visual.template == animation.TITLE3D else old.visual.type
    vtype = form.get("type") or current
    if vtype not in VISUAL_TYPES:
        raise PlanError(f"unknown visual type {vtype!r}")

    if vtype == "auto":
        # let the rule pick the engine and form from this scene's own text
        base = old.model_copy(deep=True, update={"text": text, "emphasis": _csv(form.get("emphasis", ""))})
        missing = [e for e in base.emphasis if e.lower() not in text.lower()]
        if missing:
            raise PlanError(f"emphasis words must appear in the text: {', '.join(missing)}")
        animation.to_animation(base, "auto", sf)
        sf.scenes[sf.scenes.index(old)] = base
        return base
    v = old.visual.model_dump()
    v["type"] = "blender" if vtype == "title3d" else vtype
    v["downgraded_from"] = None
    v["on_missing"] = form.get("on_missing") if form.get("on_missing") in ("animate", "manual") else None
    for key in ("query", "prompt"):
        v[key] = (form.get(key) or "").strip() or None
    v["source"] = form.get("source") if form.get("source") in ("stock", "wikimedia") else None
    v["orientation"] = form.get("orientation") if form.get("orientation") in ("portrait", "landscape", "square") else None
    v["motion"] = form.get("motion") if form.get("motion") in MOTIONS else None
    params: dict = {}

    if vtype in ("photo", "video") and not v["query"] and not v.get("file"):
        raise PlanError("a photo or video scene needs search words (or your own file)")
    if vtype == "manual" and not v["prompt"]:
        raise PlanError("a manual scene needs a note telling you what file to add")

    if vtype == "chart":
        labels, raw = _csv(form.get("chart_labels", "")), _csv(form.get("chart_values", ""))
        try:
            values = [float(x) for x in raw]
        except ValueError:
            raise PlanError("chart values must be numbers, separated by commas")
        if len(labels) < 2 or len(labels) != len(values):
            raise PlanError(f"a chart needs matching labels and values (got {len(labels)} labels, {len(values)} values)")
        values = [int(x) if float(x).is_integer() else x for x in values]
        kind = form.get("chart_kind") if form.get("chart_kind") in CHART_KINDS else "bar"
        params = {"kind": kind, "title": (form.get("chart_title") or "").strip(), "unit": (form.get("chart_unit") or "").strip(),
                  "labels": labels, "values": values}
    elif vtype == "blender":
        codes, bad = india.resolve_states(_csv(form.get("states", "")))
        if bad:
            raise PlanError(f"unknown state(s): {', '.join(bad)}")
        if not codes:
            raise PlanError("pick at least one state to highlight")
        cam = form.get("camera") if form.get("camera") in CAMERAS else "top_down_tilt"
        params = {"highlight_states": codes, "camera": cam}
        v["template"] = "india_map"
    elif vtype in ("animation", "title3d"):
        headline = " ".join((form.get("headline") or "").split()) or animation.headline_for(old.model_copy(update={"text": text}))
        subline = " ".join((form.get("subline") or "").split())
        if vtype == "title3d":
            params = {"headline": headline, "subline": subline}
            v["template"] = animation.TITLE3D
        else:
            style = form.get("anim_style") if form.get("anim_style") in animation.STYLES else animation.STYLES[sid % len(animation.STYLES)]
            tpl = form.get("template") if form.get("template") in animation.GRAPHIC_TEMPLATES else "headline"
            raw = {"template": tpl, "style": style, "headline": headline, "subline": subline,
                   "kicker": " ".join((form.get("kicker") or "").split()),
                   "items": parse_items(form.get("items", "")),
                   "quote": " ".join((form.get("quote") or "").split()),
                   "attribution": " ".join((form.get("attribution") or "").split()),
                   "keywords": _csv(form.get("keywords", ""))[:5]}
            params = animation.clean_graphic(raw)
            if params["template"] != tpl:
                lo = animation.ITEM_LIMITS.get(tpl, (0, 0))[0]
                need = "a quote" if tpl == "quote" else f"at least {lo} items, one per line"
                raise PlanError(f"a {animation.TEMPLATE_LABELS[tpl].lower()} graphic needs {need}")
    if vtype not in ("blender", "title3d"):
        v["template"] = None
    v["params"] = params

    overlay = None
    ov_value = (form.get("overlay_value") or "").strip()
    if vtype == "stat" and not ov_value:
        raise PlanError("a stat scene needs a value, like 76% or 1,20,000")
    if ov_value:
        overlay = {"type": "stat", "value": ov_value, "label": (form.get("overlay_label") or "").strip() or None}

    emphasis = _csv(form.get("emphasis", ""))
    missing = [e for e in emphasis if e.lower() not in text.lower()]
    if missing:
        raise PlanError(f"emphasis words must appear in the text: {', '.join(missing)}")

    try:
        new = Scene.model_validate({"id": sid, "text": text, "emphasis": emphasis, "visual": v, "overlay": overlay})
    except ValidationError as e:
        raise PlanError(_first_error(e))
    sf.scenes[sf.scenes.index(old)] = new
    return new


# ---------------------------------------------------------------- structure: insert, delete, move


def _lists(sf: ScenesFile) -> list[list[int]]:
    out = [r.scene_ids for r in sf.reels]
    if sf.long_form:
        out += [c.scene_ids for c in sf.long_form.chapters]
    return out


def insert_after(sf: ScenesFile, after_id: int | None) -> Scene:
    """A new text-card scene right after `after_id`, in every reel and chapter that contains it."""
    new_id = max((s.id for s in sf.scenes), default=0) + 1
    scene = Scene.model_validate({"id": new_id, "text": "New scene: write the narration here.",
                                  "visual": {"type": "text_card"}})
    if after_id is None or not any(s.id == after_id for s in sf.scenes):
        sf.scenes.append(scene)
        return scene
    sf.scenes.insert(next(i for i, s in enumerate(sf.scenes) if s.id == after_id) + 1, scene)
    for ids in _lists(sf):
        if after_id in ids:
            ids.insert(ids.index(after_id) + 1, new_id)
    return scene


def delete_scene(sf: ScenesFile, sid: int) -> None:
    if len(sf.scenes) <= 1:
        raise PlanError("a project needs at least one scene")
    sf.scenes = [s for s in sf.scenes if s.id != sid]
    for ids in _lists(sf):
        if sid in ids:
            ids.remove(sid)
    for r in list(sf.reels):
        if not r.scene_ids:
            sf.reels.remove(r)
        elif r.hook_scene == sid:
            r.hook_scene = r.scene_ids[0]
    if sf.long_form:
        sf.long_form.chapters = [c for c in sf.long_form.chapters if c.scene_ids]
        if not sf.long_form.chapters:
            sf.long_form = None


def move_scene(sf: ScenesFile, sid: int, direction: int) -> bool:
    """Swap with the neighbour (-1 up, +1 down) in the scene list and in each reel/chapter it belongs to."""
    moved = False
    idx = next((i for i, s in enumerate(sf.scenes) if s.id == sid), None)
    if idx is None:
        return False
    j = idx + direction
    if 0 <= j < len(sf.scenes):
        sf.scenes[idx], sf.scenes[j] = sf.scenes[j], sf.scenes[idx]
        moved = True
    for ids in _lists(sf):
        if sid in ids:
            a = ids.index(sid)
            b = a + direction
            if 0 <= b < len(ids):
                ids[a], ids[b] = ids[b], ids[a]
                moved = True
    return moved


def membership(sf: ScenesFile) -> dict[int, list[str]]:
    """scene id -> labels of the videos/chapters it appears in, for the plan table."""
    out: dict[int, list[str]] = {s.id: [] for s in sf.scenes}
    for r in sf.reels:
        for i in r.scene_ids:
            out.setdefault(i, []).append(r.id)
    if sf.long_form:
        for c in sf.long_form.chapters:
            for i in c.scene_ids:
                out.setdefault(i, []).append(f"long · {c.title}")
    return out


# ---------------------------------------------------------------- lock


def qc_path(project: Path) -> Path:
    return project / "build" / "qc.json"


def read_qc(project: Path) -> dict:
    try:
        return json.loads(qc_path(project).read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def write_qc(project: Path, data: dict) -> None:
    p = qc_path(project)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1))
    tmp.replace(p)


def is_locked(project: Path) -> bool:
    """Locked explicitly, or a project that already has fetched/recorded/rendered work (made before locking existed)."""
    if read_qc(project).get("plan_locked"):
        return True
    return any([(project / "build" / "cache" / "fetch.json").exists(), (project / "audio" / "narration.m4a").exists(),
                any((project / "out").glob("*.mp4")) if (project / "out").exists() else False])


def set_locked(project: Path, locked: bool) -> None:
    qc = read_qc(project)
    qc["plan_locked"] = locked
    qc["locked_at"] = time.time() if locked else None
    write_qc(project, qc)


# ---------------------------------------------------------------- direction and rhythm


def parse_items(text: str) -> list[dict]:
    """One item per line, "label | value" (the value is optional): "1983 | India win at Lord's"."""
    out = []
    for line in (text or "").splitlines():
        label, _, value = line.partition("|")
        if label.strip():
            out.append({"label": label.strip(), "value": value.strip() or None})
    return out


def items_text(items: list[dict] | None) -> str:
    return "\n".join(f"{i['label']} | {i['value']}" if i.get("value") else i["label"] for i in items or [])


def apply_direction(sf: ScenesFile, form) -> Direction:
    """The direction card on the plan page: pack, energy, grade, colours and the words that describe the look."""
    try:
        d = Direction.model_validate({
            "pack": form.get("pack") or "editorial",
            "vibe": " ".join((form.get("vibe") or "").split()),
            "energy": form.get("energy") or "steady",
            "grade": form.get("grade") or "neutral",
            "accent": form.get("accent") if form.get("use_accent") else None,
            "accent2": form.get("accent2") if form.get("use_accent") else None,
            "motifs": _csv(form.get("motifs", ""))[:6],
            "avoid": _csv(form.get("avoid", ""))[:6],
        })
    except ValidationError as e:
        raise PlanError(_first_error(e))
    sf.direction = d
    return d


def _kind(scene) -> str:
    v = scene.visual
    if v.type == "animation":
        return f"graphic:{v.params.get('template') or 'headline'}"
    if v.type in ("photo", "video", "manual"):
        return "footage"
    return v.type


def rhythm_warnings(sf: ScenesFile) -> list[str]:
    """What makes a video feel like a template: the same graphic back to back, or a long run of graphics."""
    out = []
    orders = [(r.id, r.scene_ids) for r in sf.reels] + ([("long-form", [i for c in sf.long_form.chapters for i in c.scene_ids])] if sf.long_form else [])
    for name, ids in orders:
        kinds = [_kind(sf.scene(i)) for i in ids]
        for a, b, ka, kb in zip(ids, ids[1:], kinds, kinds[1:]):
            if ka == kb and ka != "footage":
                out.append(f"{name}: scenes {a} and {b} are both {ka.replace('graphic:', '')} graphics in a row")
        run = 0
        for i, k in zip(ids, kinds):
            run = run + 1 if k != "footage" else 0
            if run == 3:
                out.append(f"{name}: three graphic scenes in a row ending at scene {i}; put a photo or clip between them")
        if len(ids) >= 5 and len(set(kinds)) < 3:
            out.append(f"{name}: only {len(set(kinds))} kinds of visual in {len(ids)} scenes")
    return out[:8]
