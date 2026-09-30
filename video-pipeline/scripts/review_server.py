"""`reel review`: local page to Keep / Replace / Refetch each scene's visual. Binds to 127.0.0.1 only."""
from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path

from flask import Flask, abort, redirect, render_template_string, request, send_file, url_for
from werkzeug.utils import secure_filename

from . import fetch_assets, manual_inbox
from .lib.assets import find_asset, load_credits
from .lib.schema import dump_json, load_scenes

ALLOWED_UPLOAD = {"jpg", "jpeg", "png", "webp", "mp4", "mov"}

PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Review · {{ slug }}</title>
<style>
:root { --bg:#0f1117; --card:#1a1d27; --text:#e8e8ef; --muted:#9aa0b4; --accent:#ffd23f; --ok:#34d399; --warn:#f87171; --line:#2b2f3d; }
* { box-sizing:border-box; }
body { margin:0; background:var(--bg); color:var(--text); font:15px/1.45 -apple-system, Inter, Helvetica, sans-serif; }
header { padding:16px 20px; border-bottom:1px solid var(--line); display:flex; gap:16px; align-items:baseline; flex-wrap:wrap; }
header h1 { font-size:18px; margin:0; }
header .stat { color:var(--muted); }
.flash { margin:12px 20px; padding:10px 14px; border-radius:8px; background:#243b2f; }
.flash.err { background:#4a2323; }
.grid { display:grid; grid-template-columns:repeat(auto-fill, minmax(260px, 1fr)); gap:16px; padding:20px; }
.card { background:var(--card); border:1px solid var(--line); border-radius:12px; overflow:hidden; display:flex; flex-direction:column; }
.card.kept { border-color:var(--ok); }
.thumb { aspect-ratio:9/16; max-height:360px; background:#000; display:flex; align-items:center; justify-content:center; }
.thumb img, .thumb video { width:100%; height:100%; object-fit:cover; }
.thumb .none { color:var(--muted); padding:16px; text-align:center; }
.body { padding:12px; display:flex; flex-direction:column; gap:8px; flex:1; }
.meta { display:flex; gap:6px; flex-wrap:wrap; font-size:12px; }
.tag { padding:2px 8px; border-radius:99px; background:var(--line); color:var(--muted); }
.tag.manual { background:#4a2323; color:#fecaca; }
.tag.kept { background:#1f3b2f; color:#a7f3d0; }
.text { margin:0; }
.credit { color:var(--muted); font-size:12px; }
details { border-top:1px solid var(--line); padding-top:8px; }
summary { cursor:pointer; color:var(--accent); }
form { display:flex; flex-direction:column; gap:6px; margin-top:6px; }
input, select, button { font:inherit; border-radius:8px; border:1px solid var(--line); background:#11131a; color:var(--text); padding:6px 8px; }
button { cursor:pointer; background:#2a2f40; }
button.primary { background:var(--accent); color:#111; border-color:var(--accent); font-weight:600; }
.row { display:flex; gap:6px; }
.row > * { flex:1; }
</style></head><body>
<header><h1>{{ slug }}</h1>
<span class="stat">{{ scenes|length }} scenes · {{ kept }} kept · {{ pending }} manual pending</span></header>
{% if msg %}<div class="flash {{ 'err' if err else '' }}">{{ msg }}</div>{% endif %}
<div class="grid">
{% for s in scenes %}
<div class="card {{ 'kept' if s.kept else '' }}" id="s{{ s.id }}">
  <div class="thumb">
    {% if s.kind == 'photo' %}<img src="{{ url_for('asset', rel=s.file) }}?v={{ s.mtime }}" alt="scene {{ s.id }}">
    {% elif s.kind == 'video' %}<video src="{{ url_for('asset', rel=s.file) }}?v={{ s.mtime }}" muted loop playsinline controls></video>
    {% else %}<div class="none">{{ s.placeholder }}</div>{% endif %}
  </div>
  <div class="body">
    <div class="meta"><span class="tag">#{{ s.id }}</span><span class="tag {{ 'manual' if s.type == 'manual' else '' }}">{{ s.type }}</span>
      {% if s.kept %}<span class="tag kept">kept</span>{% endif %}</div>
    <p class="text">{{ s.text }}</p>
    {% if s.credit %}<div class="credit">{{ s.credit }}</div>{% endif %}
    <form method="post" action="{{ url_for('keep', sid=s.id) }}"><button class="primary">Keep</button></form>
    <details><summary>Replace</summary>
      <form method="post" action="{{ url_for('replace', sid=s.id) }}" enctype="multipart/form-data">
        <input type="file" name="file" accept="image/*,video/mp4,video/quicktime">
        {% if inbox %}<select name="inbox_file"><option value="">…or pick from inbox/</option>
          {% for f in inbox %}<option>{{ f }}</option>{% endfor %}</select>{% endif %}
        <div class="row"><select name="rights">{% for r in rights %}<option>{{ r }}</option>{% endfor %}</select>
          <input name="source" placeholder="source / credit"></div>
        <button>Replace</button>
      </form></details>
    <details><summary>Refetch</summary>
      <form method="post" action="{{ url_for('refetch', sid=s.id) }}">
        <input name="query" value="{{ s.query or '' }}" placeholder="search words">
        <div class="row"><select name="type">{% for t in ['photo', 'video'] %}<option {{ 'selected' if t == s.fetch_type else '' }}>{{ t }}</option>{% endfor %}</select>
          <select name="source">{% for t in ['stock', 'wikimedia'] %}<option {{ 'selected' if t == s.source else '' }}>{{ t }}</option>{% endfor %}</select></div>
        <button>Refetch</button>
      </form></details>
  </div>
</div>
{% endfor %}
</div></body></html>"""


def create_app(project: Path, http=None) -> Flask:
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = 500 * 1024 * 1024
    scenes_path = project / "script" / "scenes.json"
    review_path = project / "build" / "review.json"

    def read_review() -> dict:
        return json.loads(review_path.read_text()) if review_path.exists() else {}

    def write_review(state: dict) -> None:
        review_path.parent.mkdir(parents=True, exist_ok=True)
        review_path.write_text(json.dumps(state, indent=2))

    def back(msg: str, err: bool = False, sid: int | None = None):
        return redirect(url_for("index", msg=msg, err=int(err)) + (f"#s{sid}" if sid else ""))

    @app.get("/")
    def index():
        sf = load_scenes(scenes_path)
        review = read_review()
        credits = {c.scene_id: c for c in load_credits(project)}
        rows = []
        for s in sf.scenes:
            found = find_asset(project, s) if s.visual.type != "text_card" else None
            kind, file = found if found else (None, None)
            c = credits.get(s.id)
            rows.append({
                "id": s.id, "text": s.text, "type": s.visual.type, "kind": kind, "file": file,
                "mtime": int((project / file).stat().st_mtime) if file else 0,
                "placeholder": s.visual.prompt or s.visual.query or s.visual.type,
                "query": s.visual.query, "source": s.visual.source or "stock",
                "fetch_type": s.visual.downgraded_from or (s.visual.type if s.visual.type in ("photo", "video") else "photo"),
                "kept": review.get(str(s.id)) == "keep" and bool(file),
                "credit": f"{c.attribution_text or c.source} · {c.license}" if c else "",
            })
        inbox = sorted(f.name for f in (project / "inbox").glob("*") if f.suffix.lower().lstrip(".") in ALLOWED_UPLOAD)
        return render_template_string(
            PAGE, slug=project.name, scenes=rows, inbox=inbox, rights=manual_inbox.RIGHTS,
            kept=sum(r["kept"] for r in rows), pending=len(manual_inbox.pending(project, sf)),
            msg=request.args.get("msg"), err=request.args.get("err") == "1",
        )

    @app.get("/asset/<path:rel>")
    def asset(rel: str):
        path = (project / rel).resolve()
        if not path.is_relative_to((project / "assets").resolve()) or not path.is_file():
            abort(404)
        return send_file(path)

    @app.post("/scene/<int:sid>/keep")
    def keep(sid: int):
        state = read_review()
        state[str(sid)] = "keep"
        write_review(state)
        return back(f"Scene {sid} kept.", sid=sid)

    @app.post("/scene/<int:sid>/replace")
    def replace(sid: int):
        sf = load_scenes(scenes_path)
        scene = next((s for s in sf.scenes if s.id == sid), None)
        if not scene:
            abort(404)
        rights, source = request.form.get("rights", ""), request.form.get("source", "").strip()
        up, inbox_name = request.files.get("file"), request.form.get("inbox_file", "")
        tmpdir = None
        if up and up.filename:
            name = secure_filename(up.filename)
            if name.rsplit(".", 1)[-1].lower() not in ALLOWED_UPLOAD:
                return back("Upload a jpg, png, webp, mp4 or mov file.", True, sid)
            tmpdir = tempfile.mkdtemp()
            src = Path(tmpdir) / name
            up.save(src)
        elif inbox_name:
            src = (project / "inbox" / secure_filename(inbox_name))
            if not src.is_file():
                return back("That inbox file is gone.", True, sid)
        else:
            return back("Choose a file to upload or pick one from the inbox.", True, sid)
        try:
            manual_inbox.attach(project, sf, scene, src, rights, source)
        except ValueError as e:
            return back(str(e), True, sid)
        finally:
            if tmpdir:
                shutil.rmtree(tmpdir, ignore_errors=True)
        dump_json(sf, scenes_path)
        manual_inbox.write_readme(project, sf)
        state = read_review()
        state.pop(str(sid), None)
        write_review(state)
        return back(f"Scene {sid} replaced.", sid=sid)

    @app.post("/scene/<int:sid>/refetch")
    def refetch(sid: int):
        sf = load_scenes(scenes_path)
        scene = next((s for s in sf.scenes if s.id == sid), None)
        if not scene:
            abort(404)
        query = request.form.get("query", "").strip()
        if not query:
            return back("Enter search words to refetch.", True, sid)
        v = scene.visual
        wants_stock = request.form.get("source") != "wikimedia" or request.form.get("type") == "video"
        if wants_stock and not (os.getenv("PEXELS_API_KEY") or os.getenv("UNSPLASH_ACCESS_KEY")):
            return back("No PEXELS_API_KEY or UNSPLASH_ACCESS_KEY in .env, so stock search can't run. "
                        "Add a key, or pick 'wikimedia'.", True, sid)
        v.type = request.form.get("type") if request.form.get("type") in ("photo", "video") else "photo"
        v.source = request.form.get("source") if request.form.get("source") in ("stock", "wikimedia") else "stock"
        v.query, v.downgraded_from = query, None
        dump_json(sf, scenes_path)
        summary = fetch_assets.fetch(project, only=[sid], force=True, http=http, downgrade=False, log=app.logger.info)
        state = read_review()
        state.pop(str(sid), None)
        write_review(state)
        if summary.get("fetched"):
            return back(f"Scene {sid}: new {v.type} fetched for “{query}”.", sid=sid)
        if summary.get("error"):
            return back(f"Scene {sid}: fetch failed (network or API key); see the terminal.", True, sid)
        return back(f"Scene {sid}: nothing relevant for “{query}”; kept the current visual. Try other words or Replace.", True, sid)

    return app


def serve(project: Path, port: int = 7788) -> None:
    app = create_app(project)
    print(f"review: http://127.0.0.1:{port}  (Ctrl-C to stop)")
    app.run(host="127.0.0.1", port=port, debug=False)
