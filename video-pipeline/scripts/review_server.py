"""Per-scene review inside the Studio: Keep / Replace / Refetch each scene's visual."""
from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

from flask import Blueprint, abort, current_app, redirect, render_template, request, url_for
from werkzeug.utils import secure_filename

from . import animation, fetch_assets, manual_inbox
from .lib.assets import find_asset, load_credits
from .lib.schema import dump_json, load_scenes

ALLOWED_UPLOAD = {"jpg", "jpeg", "png", "webp", "mp4", "mov"}

bp = Blueprint("review", __name__, url_prefix="/p/<slug>/review")


def _project(slug: str) -> Path:
    proj = current_app.config["PROJECTS_DIR"] / slug
    if not (proj / "script" / "scenes.json").exists():
        abort(404)
    return proj


def _read_review(project: Path) -> dict:
    p = project / "build" / "review.json"
    return json.loads(p.read_text()) if p.exists() else {}


def _write_review(project: Path, state: dict) -> None:
    p = project / "build" / "review.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(state, indent=2))


def _back(slug: str, msg: str, err: bool = False, sid: int | None = None):
    return redirect(url_for("review.index", slug=slug, msg=msg, err=int(err)) + (f"#s{sid}" if sid else ""))


def _scene(sf, sid: int):
    scene = next((s for s in sf.scenes if s.id == sid), None)
    if not scene:
        abort(404)
    return scene


@bp.get("/")
def index(slug: str):
    project = _project(slug)
    sf = load_scenes(project / "script" / "scenes.json")
    review = _read_review(project)
    credits = {c.scene_id: c for c in load_credits(project)}
    rows = []
    for s in sf.scenes:
        found = find_asset(project, s) if s.visual.type != "text_card" else None
        kind, file = found if found else (None, None)
        c = credits.get(s.id)
        rows.append({
            "id": s.id, "text": s.text, "type": s.visual.type, "kind": kind, "file": file,
            "mtime": int((project / file).stat().st_mtime) if file else 0,
            "placeholder": animation.describe(s) or s.visual.prompt or s.visual.query or s.visual.type,
            "query": s.visual.query, "source": s.visual.source or "stock",
            "fetch_type": s.visual.downgraded_from or (s.visual.type if s.visual.type in ("photo", "video") else "photo"),
            "credit": f"{c.attribution_text or c.source} · {c.license}" if c else "",
        })
    inbox = sorted(f.name for f in (project / "inbox").glob("*") if f.suffix.lower().lstrip(".") in ALLOWED_UPLOAD)
    return render_template(
        "review.html", slug=slug, scenes=rows, inbox=inbox, rights=manual_inbox.RIGHTS,
        pending=len(manual_inbox.pending(project, sf)),
        msg=request.args.get("msg"), err=request.args.get("err") == "1",
    )


@bp.post("/scene/<int:sid>/replace")
def replace(slug: str, sid: int):
    project = _project(slug)
    scenes_path = project / "script" / "scenes.json"
    sf = load_scenes(scenes_path)
    scene = _scene(sf, sid)
    rights, source = request.form.get("rights", ""), request.form.get("source", "").strip()
    up, inbox_name = request.files.get("file"), request.form.get("inbox_file", "")
    tmpdir = None
    if up and up.filename:
        name = secure_filename(up.filename)
        if name.rsplit(".", 1)[-1].lower() not in ALLOWED_UPLOAD:
            return _back(slug, "Upload a jpg, png, webp, mp4 or mov file.", True, sid)
        tmpdir = tempfile.mkdtemp()
        src = Path(tmpdir) / name
        up.save(src)
    elif inbox_name:
        src = project / "inbox" / secure_filename(inbox_name)
        if not src.is_file():
            return _back(slug, "That inbox file is gone.", True, sid)
    else:
        return _back(slug, "Choose a file to upload or pick one from the inbox.", True, sid)
    try:
        manual_inbox.attach(project, sf, scene, src, rights, source)
    except ValueError as e:
        return _back(slug, str(e), True, sid)
    finally:
        if tmpdir:
            shutil.rmtree(tmpdir, ignore_errors=True)
    dump_json(sf, scenes_path)
    manual_inbox.write_readme(project, sf)
    state = _read_review(project)
    state.pop(str(sid), None)
    _write_review(project, state)
    return _back(slug, f"Scene {sid} replaced.", sid=sid)


@bp.post("/scene/<int:sid>/refetch")
def refetch(slug: str, sid: int):
    project = _project(slug)
    scenes_path = project / "script" / "scenes.json"
    sf = load_scenes(scenes_path)
    scene = _scene(sf, sid)
    query = request.form.get("query", "").strip()
    if not query:
        return _back(slug, "Enter search words to refetch.", True, sid)
    v = scene.visual
    v.type = request.form.get("type") if request.form.get("type") in ("photo", "video") else "photo"
    v.source = request.form.get("source") if request.form.get("source") in ("stock", "wikimedia") else "stock"
    v.query, v.downgraded_from = query, None
    dump_json(sf, scenes_path)
    summary = fetch_assets.fetch(project, only=[sid], force=True, http=current_app.config.get("HTTP"),
                                 downgrade=False, log=current_app.logger.info)
    state = _read_review(project)
    state.pop(str(sid), None)
    _write_review(project, state)
    if summary.get("fetched"):
        return _back(slug, f"Scene {sid}: new {v.type} fetched for “{query}”.", sid=sid)
    if summary.get("error"):
        return _back(slug, f"Scene {sid}: fetch failed (network or API key); see the terminal.", True, sid)
    return _back(slug, f"Scene {sid}: nothing relevant for “{query}”; kept the current visual. "
                       "Try other words or Replace.", True, sid)
