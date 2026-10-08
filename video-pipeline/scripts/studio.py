"""`reel studio`: local web UI to start projects, run each step, and watch progress.

Binds to 127.0.0.1 only. One job runs at a time (see jobs.Runner).
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from urllib.parse import urlparse

from flask import Flask, abort, jsonify, redirect, render_template, request, send_file, url_for
from werkzeug.utils import secure_filename

from . import manual_inbox
from .jobs import Runner
from .lib.config import PROJECTS_DIR
from .lib.schema import load_scenes
from .lib.state import env_warnings, next_step, project_state, stage_label

SERVABLE_DIRS = ("out", "assets", "audio", "script", "inbox", "input", "build/parts")
AUDIO_EXTS = {"m4a", "mp3", "wav", "aac", "webm", "ogg", "mp4", "caf", "aiff"}
ARTICLE_EXTS = {"txt", "md", "html", "htm"}
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")


# ---------------------------------------------------------------- step jobs


def job_script_api(project: Path, force: bool):
    def run(log):
        from .generate_script import generate

        sf = generate(project, force=force, log=log)
        return f"{len(sf.scenes)} scenes written"
    return run


def job_script_manual(project: Path, force: bool = False):
    def run(log):
        from .generate_script import generate_manual

        sf = generate_manual(project, force=force, log=log)
        return "prompt ready: paste it into claude.ai" if sf is None else f"imported {len(sf.scenes)} scenes"
    return run


def job_fetch(project: Path, force: bool):
    def run(log):
        from .fetch_assets import fetch

        summary = fetch(project, force=force, log=log)
        return ", ".join(f"{v} {k}" for k, v in sorted(summary.items()))
    return run


def job_draft(project: Path, only: str | None = None):
    def run(log):
        from .draft import draft

        outs, missing = draft(project, log=log, only=only)
        msg = f"{len(outs)} draft(s) rendered"
        return msg + (f"; scenes {', '.join(map(str, missing))} still need manual files" if missing else "")
    return run


def _target(project: Path, target_id: str):
    from .lib.targets import get_target

    sf = load_scenes(project / "script" / "scenes.json")
    return sf, get_target(sf, target_id)


def job_stills(project: Path, target_id: str):
    def run(log):
        from .parts import build_stills

        sf, target = _target(project, target_id)
        tl = _timeline_if_any(project, target)
        n = build_stills(project, sf, target, tl, log=log)
        return f"{n} picture(s) made" if n else "all pictures were already current"
    return run


def _timeline_if_any(project: Path, target):
    from .lib.state import _load_timeline

    return _load_timeline(project, target)


def job_align(project: Path, target_id: str):
    def run(log):
        from .align_audio import align

        sf, target = _target(project, target_id)
        tl = align(project, sf, target.id, log)
        weak = [s.id for s in tl.scenes if s.match is not None and s.match < 0.5]
        return f"{len(tl.scenes)} scenes timed" + (f"; weak voice match on scene(s) {', '.join(map(str, weak))}" if weak else "")
    return run


def job_parts(project: Path, target_id: str):
    def run(log):
        from .render_final import build_parts, part_preview

        sf, target = _target(project, target_id)
        tl = _timeline_if_any(project, target)
        if tl is None:
            raise RuntimeError("align your voice first")
        files = build_parts(project, sf, tl, target, log)
        for sid in target.scene_ids:
            part_preview(project, sf, tl, target, sid)
        return f"{len(files)} scene clips ready to check"
    return run


def job_assemble(project: Path, target_id: str):
    def run(log):
        from .render_final import assemble

        sf, target = _target(project, target_id)
        tl = _timeline_if_any(project, target)
        if tl is None:
            raise RuntimeError("align your voice first")
        out = assemble(project, sf, tl, target, log)
        return f"assembled {out.name}"
    return run


def job_final(project: Path, target_id: str):
    def run(log):
        from .align_audio import align
        from .lib.targets import get_target
        from .render_final import render_target

        sf = load_scenes(project / "script" / "scenes.json")
        target = get_target(sf, target_id)
        tl = align(project, sf, target.id, log)
        out = render_target(project, sf, tl, target, log)
        return f"rendered {out.name}"
    return run


# ---------------------------------------------------------------- helpers


def _articles(project: Path) -> list[dict]:
    d = project / "input" / "articles"
    if not d.exists():
        return []
    out = []
    for f in sorted(d.iterdir()):
        if f.suffix.lower().lstrip(".") not in ARTICLE_EXTS or f.name.startswith("."):
            continue
        text = f.read_text(errors="replace")
        src = text.split("\n", 1)[0].removeprefix("SOURCE: ") if f.name.startswith("_url_") else f.name
        out.append({"name": f.name, "source": src, "words": len(text.split()),
                    "downloaded": f.name.startswith("_url_")})
    return out


def _videos(project: Path) -> list[dict]:
    """Each video this project makes, with the script to read for it and its recording state."""
    from .lib.targets import list_targets

    try:
        sf = load_scenes(project / "script" / "scenes.json")
    except Exception:
        return []
    out = []
    for t in list_targets(sf):
        audio = project / t.audio
        words = sum(len(sf.scene(i).text.split()) for i in t.scene_ids)
        flow = None
        if t.kind == "long" and audio.exists():
            from .lib.state import long_flow

            flow = long_flow(project, sf, t)
        track = None
        from . import music

        mt = music.get(project, t)
        if mt:
            from dataclasses import asdict

            track = asdict(mt)
            track["credit"] = mt.credit
        sample = f"build/parts/music_preview_{t.id}.m4a"
        out.append({
            "music": track, "music_sample": sample if (project / sample).exists() else None,
            "clean": clean_rel if (clean_rel := t.out.rsplit(".", 1)[0] + "_no_music.mp4") and (project / clean_rel).exists() else None,
            "flow": flow,
            "id": t.id, "label": t.label, "kind": t.kind, "audio": t.audio, "has_audio": audio.exists(),
            "audio_mtime": int(audio.stat().st_mtime) if audio.exists() else 0,
            "final": t.out if (project / t.out).exists() else None,
            "srt": t.out.rsplit(".", 1)[0] + ".srt" if (project / t.out).with_suffix(".srt").exists() else None,
            "draft": f"out/draft_{t.id}.mp4" if (project / f"out/draft_{t.id}.mp4").exists() else None,
            "minutes": round(words / 150, 1), "scenes": len(t.scene_ids),
            "reading": [{"id": i, "text": sf.scene(i).text} for i in t.scene_ids],
        })
    return out


def _to_m4a(src: Path, dest: Path) -> float:
    """Convert any recording to AAC m4a, keeping the previous take. Returns duration in seconds."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.stem + ".new.m4a")
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", str(src), "-vn", "-ac", "1", "-ar", "48000",
         "-c:a", "aac", "-b:a", "192k", str(tmp)], check=True, capture_output=True, timeout=600,
    )
    if dest.exists():
        dest.replace(dest.with_name(dest.stem + ".prev.m4a"))
    tmp.replace(dest)
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(dest)],
        capture_output=True, text=True,
    ).stdout.strip()
    return float(out or 0)


# ---------------------------------------------------------------- app


def create_app(projects_dir: Path = PROJECTS_DIR, runner: Runner | None = None) -> Flask:
    from . import review_server, studio_qc

    app = Flask(__name__)
    app.config["PROJECTS_DIR"] = Path(projects_dir)
    app.config["MAX_CONTENT_LENGTH"] = 1024 * 1024 * 1024
    runner = runner or Runner()
    app.config["RUNNER"] = runner
    app.register_blueprint(review_server.bp)
    app.register_blueprint(studio_qc.bp)

    def file_exists(slug: str, rel: str) -> bool:
        return (app.config["PROJECTS_DIR"] / slug / rel).is_file()

    def file_url(slug: str, rel: str) -> str:
        f = app.config["PROJECTS_DIR"] / slug / rel
        v = int(f.stat().st_mtime) if f.exists() else 0
        return url_for("file", slug=slug, rel=rel) + f"?v={v}"  # cache-bust after re-renders

    app.jinja_env.globals.update(file_exists=file_exists, file_url=file_url)

    def project(slug: str) -> Path:
        if not SLUG_RE.match(slug):
            abort(404)
        p = app.config["PROJECTS_DIR"] / slug
        if not (p / "script").is_dir():
            abort(404)
        return p

    def flash_back(slug: str, msg: str, err: bool = False, anchor: str = ""):
        return redirect(url_for("project_page", slug=slug, msg=msg, err=int(err)) + (f"#{anchor}" if anchor else ""))

    def start(slug: str, step: str, label: str, fn, anchor: str):
        busy = runner.busy_with(slug)
        if busy and busy.step != step:
            return flash_back(slug, f"Wait for “{busy.label}” to finish first.", True, anchor)
        runner.submit(slug, step, label, fn, log_dir=project(slug) / "build" / "logs")
        return flash_back(slug, f"Started: {label}", anchor="job")

    @app.before_request
    def same_origin_only():
        # a page on another site must not be able to post forms to this local server
        if request.method == "POST":
            origin = request.headers.get("Origin") or request.headers.get("Referer")
            if origin and urlparse(origin).netloc != request.host:
                abort(403)

    @app.context_processor
    def globals_():
        return {"active_jobs": runner.active()}

    # ---- pages -------------------------------------------------------

    @app.get("/")
    def home():
        rows = []
        root = app.config["PROJECTS_DIR"]
        for p in sorted(root.iterdir()) if root.exists() else []:
            if not (p / "script").is_dir():
                continue
            try:
                steps = project_state(p)
            except Exception as e:  # a broken project shouldn't take the home page down
                rows.append({"slug": p.name, "stage": f"error: {e}", "next": None, "mtime": 0})
                continue
            nxt = next_step(steps)
            rows.append({"slug": p.name, "stage": stage_label(steps), "next": nxt.title if nxt else None,
                         "mtime": max((f.stat().st_mtime for f in p.rglob("*") if f.is_file()), default=0)})
        rows.sort(key=lambda r: -r["mtime"])
        return render_template("home.html", projects=rows, warnings=env_warnings(),
                               msg=request.args.get("msg"), err=request.args.get("err") == "1")

    @app.post("/new")
    def new_project():
        from .new_project import scaffold

        slug = request.form.get("slug", "").strip().lower().replace(" ", "-")
        if not SLUG_RE.match(slug):
            return redirect(url_for("home", msg="Project name: lowercase letters, digits, - or _ only.", err=1))
        lang = request.form.get("language", "hinglish")
        try:
            root = scaffold(slug, lang if lang in ("en", "hi", "hinglish") else "hinglish", open_brief=False,
                            root=app.config["PROJECTS_DIR"])
        except FileExistsError:
            return redirect(url_for("home", msg=f"A project called {slug} already exists.", err=1))
        _save_brief(root, request.form)
        pasted = request.form.get("article_text", "").strip()
        if pasted:
            (root / "input" / "articles" / "pasted_1.txt").write_text(pasted + "\n")
        return redirect(url_for("project_page", slug=slug, msg="Project created. Next: generate the script."))

    def _save_brief(root: Path, form) -> None:
        from .new_project import BRIEF_FIELDS, render_brief

        fields = {k: form.get(k, "") for k in BRIEF_FIELDS}
        fields["formats"] = fields["formats"] if fields["formats"] in ("reel", "long", "both") else "reel"
        fields["language"] = fields["language"] if fields["language"] in ("en", "hi", "hinglish") else "hinglish"
        urls = [u.strip() for u in re.split(r"[\s,]+", form.get("urls", "")) if u.strip().startswith(("http://", "https://"))]
        (root / "input" / "brief.md").write_text(render_brief(fields, urls))

    @app.get("/p/<slug>")
    def project_page(slug: str):
        from . import music as music_mod
        from .generate_script import parse_brief

        p = project(slug)
        steps = project_state(p)
        brief = parse_brief((p / "input" / "brief.md").read_text()) if (p / "input" / "brief.md").exists() else {}
        prompt_path = p / "script" / "prompt.md"
        jobs = runner.recent(slug, 8)
        return render_template(
            "project.html", slug=slug, path=str(p), steps=steps, next=next_step(steps),
            stage=stage_label(steps), brief=brief, articles=_articles(p), videos=_videos(p),
            music_licenses=music_mod.LICENSES,
            prompt=prompt_path.read_text() if prompt_path.exists() else None,
            facts=(p / "script" / "facts.md").read_text() if (p / "script" / "facts.md").exists() else "",
            warnings=env_warnings(), jobs=[j.to_dict(tail=0) for j in jobs],
            current=runner.busy_with(slug),
            msg=request.args.get("msg"), err=request.args.get("err") == "1",
        )

    # ---- inputs ------------------------------------------------------

    @app.post("/p/<slug>/brief")
    def save_brief(slug: str):
        _save_brief(project(slug), request.form)
        return flash_back(slug, "Brief saved.", anchor="brief")

    @app.post("/p/<slug>/articles")
    def add_article(slug: str):
        d = project(slug) / "input" / "articles"
        d.mkdir(parents=True, exist_ok=True)
        up = request.files.get("file")
        if up and up.filename:
            name = secure_filename(up.filename)
            if name.rsplit(".", 1)[-1].lower() not in ARTICLE_EXTS:
                return flash_back(slug, "Articles must be .txt, .md or .html.", True, "brief")
            up.save(d / name)
            return flash_back(slug, f"Added {name}.", anchor="brief")
        text = request.form.get("text", "").strip()
        if not text:
            return flash_back(slug, "Paste some article text or choose a file.", True, "brief")
        n = 1
        while (d / f"pasted_{n}.txt").exists():
            n += 1
        title = request.form.get("title", "").strip()
        (d / f"pasted_{n}.txt").write_text((f"{title}\n\n" if title else "") + text + "\n")
        return flash_back(slug, f"Added pasted_{n}.txt.", anchor="brief")

    @app.post("/p/<slug>/articles/delete")
    def delete_article(slug: str):
        f = project(slug) / "input" / "articles" / secure_filename(request.form.get("name", ""))
        if f.is_file():
            f.unlink()
        return flash_back(slug, "Article removed.", anchor="brief")

    # ---- music (optional) --------------------------------------------

    def _music_target(slug: str):
        from .lib.targets import get_target

        p = project(slug)
        return p, get_target(load_scenes(p / "script" / "scenes.json"), request.form.get("video") or None)

    def _music_args():
        def num(key, default):
            try:
                return float(request.form.get(key, default))
            except ValueError:
                return default

        from . import music

        return dict(volume_db=num("volume_db", music.DEFAULT_DB), duck=request.form.get("duck") == "1",
                    fade_s=num("fade_s", 1.5), clean_copy=request.form.get("clean_copy") == "1")

    @app.post("/p/<slug>/music")
    def music_add(slug: str):
        from . import music

        try:
            p, target = _music_target(slug)
        except ValueError as e:
            return flash_back(slug, str(e), True, "music")
        up = request.files.get("file")
        if not up or not up.filename:
            return flash_back(slug, "Choose the music file.", True, "music")
        tmpdir = tempfile.mkdtemp()
        try:
            src = Path(tmpdir) / secure_filename(up.filename)
            up.save(src)
            track = music.set_track(p, target, src, title=request.form.get("title", "") or src.stem,
                                    source=request.form.get("source", ""), license=request.form.get("license", ""),
                                    url=request.form.get("url", ""), **_music_args())
        except music.MusicError as e:
            return flash_back(slug, f"Music not added: {e}", True, "music")
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)
        return flash_back(slug, f"Added “{track.title}” to {target.label}. Press “Hear a sample” to check the volume.", anchor="music")

    @app.post("/p/<slug>/music/settings")
    def music_settings(slug: str):
        from . import music

        try:
            p, target = _music_target(slug)
            music.update_settings(p, target, **_music_args())
        except (ValueError, music.MusicError) as e:
            return flash_back(slug, str(e), True, "music")
        return flash_back(slug, "Music settings saved.", anchor="music")

    @app.post("/p/<slug>/music/clear")
    def music_clear(slug: str):
        from . import music

        p, target = _music_target(slug)
        music.clear(p, target)
        (p / "build" / "parts" / f"music_preview_{target.id}.m4a").unlink(missing_ok=True)
        return flash_back(slug, f"Music removed from {target.label}. It will be voice only.", anchor="music")

    @app.post("/p/<slug>/music/preview")
    def music_preview(slug: str):
        from . import music

        try:
            p, target = _music_target(slug)
            music.preview(p, target)
        except (ValueError, music.MusicError) as e:
            return flash_back(slug, str(e), True, "music")
        return flash_back(slug, "Sample ready: press play under the track.", anchor="music")

    @app.post("/p/<slug>/facts/checked")
    def facts_checked(slug: str):
        p = project(slug)
        facts = p / "script" / "facts.md"
        if not facts.exists():
            abort(404)
        out = p / "build" / "facts_checked.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({"checked_at_mtime": facts.stat().st_mtime, "when": time.time()}))
        return flash_back(slug, "Facts marked as checked.", anchor="facts")

    @app.post("/p/<slug>/audio")
    def upload_audio(slug: str):
        from .lib.targets import get_target

        p = project(slug)
        try:
            target = get_target(load_scenes(p / "script" / "scenes.json"), request.form.get("video") or None)
        except ValueError as e:
            return flash_back(slug, str(e), True, "record")
        up = request.files.get("audio")
        if not up or not up.filename:
            return flash_back(slug, "Choose or record an audio file.", True, "record")
        ext = secure_filename(up.filename).rsplit(".", 1)[-1].lower()
        if ext not in AUDIO_EXTS:
            return flash_back(slug, f"Unsupported audio type .{ext}.", True, "record")
        tmpdir = tempfile.mkdtemp()
        try:
            src = Path(tmpdir) / f"take.{ext}"
            up.save(src)
            dur = _to_m4a(src, p / target.audio)
        except subprocess.CalledProcessError as e:
            return flash_back(slug, f"Couldn't read that audio: {e.stderr.decode(errors='replace')[:200]}", True, "record")
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)
        if request.headers.get("X-Requested-With") == "fetch":
            return jsonify({"ok": True, "duration": dur})
        return flash_back(slug, f"Narration for {target.label} saved ({dur:.1f}s). Next: final render.", anchor="record")

    # ---- run steps ---------------------------------------------------

    @app.post("/p/<slug>/run/<step>")
    def run_step(slug: str, step: str):
        p = project(slug)
        force = request.form.get("force") == "1"
        if step == "script_api":
            return start(slug, "script", "Generate script (Claude API)", job_script_api(p, force), "script")
        if step == "script_prompt":
            return start(slug, "script", "Prepare claude.ai prompt", job_script_manual(p, force), "script")
        if step == "script_import":
            reply = request.form.get("reply", "").strip()
            if not reply:
                return flash_back(slug, "Paste Claude's reply first.", True, "script")
            (p / "script" / "response.json").write_text(reply)
            return start(slug, "script", "Import claude.ai reply", job_script_manual(p), "script")
        if step == "fetch":
            return start(slug, "fetch", "Fetch visuals", job_fetch(p, force), "fetch")
        if step in ("stills", "align", "parts", "assemble"):
            from . import parts as parts_mod
            from .lib.state import _load_timeline

            try:
                sf, target = _target(p, request.form.get("video") or "")
            except ValueError as e:
                return flash_back(slug, str(e), True, "review")
            if step == "stills":
                return start(slug, f"stills-{target.id}", f"Make pictures: {target.label}", job_stills(p, target.id), "review")
            if not (p / target.audio).exists():
                return flash_back(slug, f"Record or upload the narration for {target.label} first.", True, "record")
            if step == "align":
                return start(slug, f"align-{target.id}", f"Align voice: {target.label}", job_align(p, target.id), "final")
            if step == "parts":
                if _load_timeline(p, target) is None:
                    return flash_back(slug, "Align your voice first.", True, "final")
                return start(slug, f"parts-{target.id}", f"Build scene clips: {target.label}", job_parts(p, target.id), "final")
            tl = _load_timeline(p, target)
            if tl is None:
                return flash_back(slug, "Align your voice first.", True, "final")
            g = parts_mod.gate(parts_mod.overview(p, sf, target, tl, with_stills=False))
            if request.form.get("override") != "1" and not (g["visual_ok"] and (g["timing_ok"] or not g["has_timing"])):
                todo = len(g["visual_todo"]) + len(g["timing_todo"])
                return flash_back(slug, f"{todo} check(s) still open for {target.label}. Approve every part, "
                                        "or use “Assemble anyway”.", True, "final")
            return start(slug, f"assemble-{target.id}", f"Assemble: {target.label}", job_assemble(p, target.id), "final")
        if step == "draft":
            return start(slug, "draft", "Render draft", job_draft(p, request.form.get("video") or None), "draft")
        if step == "final":
            from .lib.targets import get_target

            try:
                target = get_target(load_scenes(p / "script" / "scenes.json"), request.form.get("video") or None)
            except ValueError as e:
                return flash_back(slug, str(e), True, "final")
            if not (p / target.audio).exists():
                return flash_back(slug, f"Record or upload the narration for {target.label} first.", True, "record")
            if target.kind == "long" and request.form.get("override") != "1":
                return flash_back(slug, "Long-form is built in steps so you can check each scene first: align, build "
                                        "scene clips, check, assemble. Or use “Render everything now”.", True, "final")
            return start(slug, f"final-{target.id}", f"Final render: {target.label}", job_final(p, target.id), "final")
        abort(404)

    # ---- files -------------------------------------------------------

    def safe_path(slug: str, rel: str) -> Path:
        p = project(slug)
        path = (p / rel).resolve()
        if not any(path.is_relative_to((p / d).resolve()) for d in SERVABLE_DIRS) or not path.exists():
            abort(404)
        return path

    @app.get("/p/<slug>/file/<path:rel>")
    def file(slug: str, rel: str):
        path = safe_path(slug, rel)
        if not path.is_file():
            abort(404)
        return send_file(path, conditional=True)

    @app.post("/p/<slug>/reveal")
    def reveal(slug: str):
        rel = request.form.get("rel", "")
        path = safe_path(slug, rel) if rel else project(slug)
        subprocess.run(["open", "-R", str(path)], check=False)
        return ("", 204)

    # ---- api ---------------------------------------------------------

    @app.post("/api/jobs/<int:job_id>/cancel")
    def api_cancel(job_id: int):
        return jsonify({"ok": runner.cancel(job_id)})

    @app.get("/api/jobs")
    def api_jobs():
        slug = request.args.get("slug")
        tail = int(request.args.get("tail", 200))
        return jsonify({
            "active": [j.to_dict(tail) for j in runner.active()],
            "recent": [j.to_dict(tail) for j in runner.recent(slug, 5)],
        })

    @app.get("/api/p/<slug>/state")
    def api_state(slug: str):
        steps = project_state(project(slug))
        return jsonify({"stage": stage_label(steps), "steps": [s.__dict__ for s in steps]})

    return app


def serve(port: int = 7788, open_path: str = "/") -> None:
    app = create_app()
    url = f"http://127.0.0.1:{port}{open_path}"
    print(f"studio: {url}  (Ctrl-C to stop)")
    import threading

    threading.Timer(1.0, lambda: subprocess.run(["open", url], check=False)).start()
    app.run(host="127.0.0.1", port=port, debug=False, threaded=True)
