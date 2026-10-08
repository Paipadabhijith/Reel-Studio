"""Studio pages for the plan (edit + lock) and for checking parts before the final render."""
from __future__ import annotations

from pathlib import Path

from flask import Blueprint, abort, current_app, redirect, render_template, request, url_for

from . import animation, parts as parts_mod
from . import plan
from .lib.schema import Timeline, load_scenes
from .lib.state import _load_timeline, long_flow
from .lib.targets import get_target, list_targets

bp = Blueprint("qc", __name__, url_prefix="/p/<slug>")


def _project(slug: str) -> Path:
    proj = current_app.config["PROJECTS_DIR"] / slug
    if not (proj / "script" / "scenes.json").exists():
        abort(404)
    return proj


def _back_plan(slug: str, msg: str, err: bool = False, sid: int | None = None):
    return redirect(url_for("qc.plan_page", slug=slug, msg=msg, err=int(err)) + (f"#s{sid}" if sid else ""))


# ---------------------------------------------------------------- plan


@bp.get("/plan")
def plan_page(slug: str):
    proj = _project(slug)
    sf = plan.load(proj)
    member = plan.membership(sf)
    targets = list_targets(sf)
    secs = {s.id: len(s.text.split()) / parts_mod.WORDS_PER_S for s in sf.scenes}
    recorded = [t.label for t in targets if (proj / t.audio).exists()]
    return render_template(
        "plan.html", slug=slug, sf=sf, member=member, secs=secs, locked=plan.is_locked(proj), recorded=recorded,
        visual_types=plan.VISUAL_TYPES, motions=plan.MOTIONS, anim_styles=animation.STYLE_LABELS, cameras=plan.CAMERAS, chart_kinds=plan.CHART_KINDS,
        msg=request.args.get("msg"), err=request.args.get("err") == "1",
    )


@bp.post("/plan/scene/<int:sid>")
def plan_save(slug: str, sid: int):
    proj = _project(slug)
    sf = plan.load(proj)
    try:
        plan.apply_form(sf, sid, request.form)
        plan.save(proj, sf)
    except plan.PlanError as e:
        return _back_plan(slug, f"Scene {sid} not saved: {e}", True, sid)
    return _back_plan(slug, f"Scene {sid} saved.", sid=sid)


@bp.post("/plan/insert")
def plan_insert(slug: str):
    proj = _project(slug)
    sf = plan.load(proj)
    after = request.form.get("after", type=int)
    new = plan.insert_after(sf, after)
    try:
        plan.save(proj, sf)
    except plan.PlanError as e:
        return _back_plan(slug, str(e), True)
    return _back_plan(slug, f"Added scene {new.id}. Write its text and pick a picture.", sid=new.id)


@bp.post("/plan/delete/<int:sid>")
def plan_delete(slug: str, sid: int):
    proj = _project(slug)
    sf = plan.load(proj)
    try:
        plan.delete_scene(sf, sid)
        plan.save(proj, sf)
    except plan.PlanError as e:
        return _back_plan(slug, str(e), True, sid)
    return _back_plan(slug, f"Scene {sid} deleted. (The previous version is kept in build/history/.)")


@bp.post("/plan/move/<int:sid>/<direction>")
def plan_move(slug: str, sid: int, direction: str):
    proj = _project(slug)
    sf = plan.load(proj)
    if direction not in ("up", "down"):
        abort(404)
    plan.move_scene(sf, sid, -1 if direction == "up" else 1)
    try:
        plan.save(proj, sf)
    except plan.PlanError as e:
        return _back_plan(slug, str(e), True, sid)
    return _back_plan(slug, f"Moved scene {sid} {direction}.", sid=sid)


@bp.post("/plan/animate/<int:sid>")
def plan_animate(slug: str, sid: int):
    """One click: replace a scene that has no picture with an animation made from its own words."""
    from . import animation

    proj = _project(slug)
    sf = plan.load(proj)
    scene = next((x for x in sf.scenes if x.id == sid), None)
    if scene is None:
        abort(404)
    engine = request.form.get("engine") if request.form.get("engine") in ("blender", "remotion") else "auto"
    animation.to_animation(scene, engine, sf)
    try:
        plan.save(proj, sf)
    except plan.PlanError as e:
        return _back_plan(slug, str(e), True, sid)
    msg = f"Scene {sid} is now an animation: {animation.describe(scene)}. Edit the headline in the plan if you like."
    if request.form.get("back") == "parts":
        return redirect(url_for("qc.parts_page", slug=slug, video=request.form.get("video") or None,
                                **{"pass": "visual"}, msg=msg, err=0) + f"#p{sid}")
    return _back_plan(slug, msg, sid=sid)


@bp.post("/plan/lock")
def plan_lock(slug: str):
    proj = _project(slug)
    plan.set_locked(proj, request.form.get("unlock") != "1")
    if request.form.get("unlock") == "1":
        return _back_plan(slug, "Plan unlocked.")
    return redirect(url_for("project_page", slug=slug, msg="Plan locked. Next: fetch visuals.") + "#fetch")


# ---------------------------------------------------------------- parts


def _pass(value: str | None) -> str:
    return value if value in ("visual", "timing") else "visual"


def _resolve(slug: str):
    proj = _project(slug)
    sf = load_scenes(proj / "script" / "scenes.json")
    try:
        target = get_target(sf, request.values.get("video") or None)
    except ValueError:
        abort(404)
    return proj, sf, target


@bp.get("/parts")
def parts_page(slug: str):
    proj, sf, target = _resolve(slug)
    kind = _pass(request.args.get("pass"))
    tl = _load_timeline(proj, target)
    if kind == "timing" and tl is None:
        kind = "visual"
    ps = parts_mod.overview(proj, sf, target, tl)
    g = parts_mod.gate(ps)
    flow = long_flow(proj, sf, target) if target.kind == "long" else None
    previews = {}
    if kind == "timing":
        for p in ps:
            rel = f"build/parts/{target.id}/preview_{p.scene.id:02d}.mp4"
            previews[p.scene.id] = rel if (proj / rel).exists() else None
    chapters = {}
    if sf.long_form and target.kind == "long":
        for c in sf.long_form.chapters:
            for i in c.scene_ids:
                chapters[i] = c.title
    return render_template(
        "parts.html", slug=slug, target=target, targets=list_targets(sf), parts=ps, gate=g, kind=kind,
        has_timeline=tl is not None, previews=previews, flow=flow, chapters=chapters,
        missing_stills=sum(1 for p in ps if not p.still), msg=request.args.get("msg"), err=request.args.get("err") == "1",
    )


def _back_parts(slug: str, target_id: str, kind: str, msg: str, err: bool = False, sid: int | None = None):
    return redirect(url_for("qc.parts_page", slug=slug, video=target_id, **{"pass": kind}, msg=msg, err=int(err))
                    + (f"#p{sid}" if sid else ""))


@bp.post("/parts/<int:sid>/approve")
def parts_approve(slug: str, sid: int):
    proj, sf, target = _resolve(slug)
    kind = _pass(request.form.get("pass"))
    tl = _load_timeline(proj, target)
    p = next((x for x in parts_mod.overview(proj, sf, target, tl, with_stills=False) if x.scene.id == sid), None)
    if p is None:
        abort(404)
    if p.errors:
        return _back_parts(slug, target.id, kind, f"Scene {sid} has problems to fix first: {p.errors[0].msg}", True, sid)
    parts_mod.approve(proj, target, sid, kind, p.fingerprint if kind == "visual" else p.timing_fp,
                      (request.form.get("note") or "").strip())
    return _back_parts(slug, target.id, kind, f"Scene {sid} approved.", sid=sid)


@bp.post("/parts/<int:sid>/redo")
def parts_redo(slug: str, sid: int):
    proj, sf, target = _resolve(slug)
    kind = _pass(request.form.get("pass"))
    note = (request.form.get("note") or "").strip()
    if not note:
        return _back_parts(slug, target.id, kind, "Say what needs to change so you remember when you come back.", True, sid)
    parts_mod.request_redo(proj, target, sid, note)
    return _back_parts(slug, target.id, kind, f"Scene {sid} marked for redo. Fix it in the plan or on the review page.", sid=sid)


@bp.post("/parts/approve-clean")
def parts_approve_clean(slug: str):
    proj, sf, target = _resolve(slug)
    kind = _pass(request.form.get("pass"))
    tl = _load_timeline(proj, target)
    n = parts_mod.approve_all_clean(proj, parts_mod.overview(proj, sf, target, tl, with_stills=False), target, kind)
    return _back_parts(slug, target.id, kind, f"Approved {n} part(s) with no warnings. Review the rest one by one.")
