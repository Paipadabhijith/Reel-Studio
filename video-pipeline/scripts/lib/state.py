"""Where a project stands: one status per pipeline step, what the user must do next, and outputs.

Everything is derived from files on disk, so it is correct after restarts and
after CLI runs as well as Studio runs.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from .assets import find_asset
from .schema import ScenesFile, load_scenes
from .targets import Target, draft_out, list_targets

# done: finished · todo: needs you · waiting: started, needs your input to continue
# stale: done, but inputs changed since · blocked: an earlier step must finish first
# later: arrives in a later phase · optional: nothing required here
STATUSES = ("done", "todo", "waiting", "stale", "blocked", "later", "optional")


@dataclass
class Step:
    key: str
    title: str
    status: str
    detail: str = ""
    todos: list[str] = field(default_factory=list)
    outputs: list[str] = field(default_factory=list)  # paths relative to the project
    optional: bool = False


def _mtime(p: Path) -> float:
    return p.stat().st_mtime if p.exists() else 0.0


def _newest(paths) -> float:
    return max((_mtime(p) for p in paths), default=0.0)


def _nonempty(p: Path) -> bool:
    return p.exists() and bool(p.read_text().strip())


def read_json(p: Path, default):
    try:
        return json.loads(p.read_text()) if p.exists() else default
    except (json.JSONDecodeError, OSError):
        return default


def count_facts(facts_md: Path) -> tuple[int, int]:
    """(total facts, facts flagged as not in the supplied sources)."""
    if not facts_md.exists():
        return 0, 0
    lines = [ln for ln in facts_md.read_text().splitlines() if ln.startswith("- [")]
    return len(lines), sum("NOT in the supplied sources" in ln for ln in lines)


def article_count(project: Path, brief_urls: list[str]) -> int:
    d = project / "input" / "articles"
    local = [f for f in d.glob("*") if f.suffix.lower() in (".txt", ".md", ".html", ".htm") and not f.name.startswith("_url_")] if d.exists() else []
    return len(local) + len(brief_urls)


def env_warnings() -> list[str]:
    out = []
    if not any(os.getenv(k) for k in ("PEXELS_API_KEY", "PIXABAY_API_KEY", "UNSPLASH_ACCESS_KEY")):
        out.append("No PEXELS_API_KEY, PIXABAY_API_KEY or UNSPLASH_ACCESS_KEY in .env: stock photos and videos "
                   "can't be fetched (Wikimedia and charts still work).")
    elif not any(os.getenv(k) for k in ("PEXELS_API_KEY", "PIXABAY_API_KEY")):
        out.append("No Pexels or Pixabay key: stock video scenes can't be fetched (Unsplash is photos only).")
    return out


def project_state(project: Path) -> list[Step]:
    from ..generate_script import parse_brief  # local import: generate_script imports lib modules
    from ..manual_inbox import pending

    script_dir, build, out = project / "script", project / "build", project / "out"
    cache_dir = build / "cache"
    brief_path = project / "input" / "brief.md"
    brief = parse_brief(brief_path.read_text()) if brief_path.exists() else {"source_urls": []}
    try:
        sf: ScenesFile | None = load_scenes(script_dir / "scenes.json")
    except Exception:
        sf = None
    steps: list[Step] = []

    # 1 brief ------------------------------------------------------------
    n_art = article_count(project, brief.get("source_urls", []))
    if brief.get("topic"):
        steps.append(Step("brief", "Brief & sources", "done",
                          f"{brief.get('topic')} · {n_art} source(s) · {brief.get('formats')} · {brief.get('language')}",
                          [] if n_art else ["Add at least one link or article so facts can be checked."],
                          ["input/brief.md", "input/articles/"]))
    elif (project / "audio" / "narration.m4a").exists() or (cache_dir / "fetch.json").exists():
        steps.append(Step("brief", "Brief & sources", "optional",
                          "No brief: this project uses a hand-written scenes.json.", optional=True))
    else:
        steps.append(Step("brief", "Brief & sources", "todo", "No topic yet.", ["Fill in the topic and add links."]))

    # 2 script -----------------------------------------------------------
    script_done = (cache_dir / "script.hash").exists() and _nonempty(script_dir / "script.md")
    script_outs = ["script/scenes.json", "script/script.md", "script/hooks.md", "script/facts.md"]
    if (script_dir / "prompt.md").exists():
        st = Step("script", "Script", "waiting", "Prompt is ready for claude.ai.",
                  ["Paste the prompt into a new claude.ai chat, then paste Claude's reply back here."], script_outs)
    elif script_done:
        inputs = [brief_path, *(project / "input" / "articles").glob("*")]
        stale = _newest(inputs) > _mtime(script_dir / "script.md")
        st = Step("script", "Script", "stale" if stale else "done",
                  f"{len(sf.scenes) if sf else 0} scenes · {len(sf.reels) if sf else 0} reel(s)"
                  + (" · brief or articles changed after the script was written" if stale else ""),
                  ["Regenerate the script, or keep it if the change doesn't matter."] if stale else [], script_outs)
    elif sf and not brief.get("topic"):
        st = Step("script", "Script", "optional", "Using a hand-written scenes.json.", [], ["script/scenes.json"])
    else:
        st = Step("script", "Script", "todo" if brief.get("topic") else "blocked",
                  "Write it with Claude (API key) or via claude.ai (manual, free).",
                  ["Generate the script."] if brief.get("topic") else [], script_outs)
    steps.append(st)

    # 3 facts ------------------------------------------------------------
    total, unsourced = count_facts(script_dir / "facts.md")
    checked = read_json(build / "facts_checked.json", {}).get("checked_at_mtime") == _mtime(script_dir / "facts.md")
    if total == 0:
        steps.append(Step("facts", "Fact check", "optional", "No facts list (hand-written script).", optional=True))
    elif checked:
        steps.append(Step("facts", "Fact check", "done", f"{total} facts checked.", [], ["script/facts.md"]))
    else:
        steps.append(Step("facts", "Fact check", "todo",
                          f"{total} facts to verify, {unsourced} not found in your sources.",
                          [f"Check every claim against its source before you record."
                           + (f" {unsourced} need extra care." if unsourced else "")], ["script/facts.md"]))

    # 4 visuals -----------------------------------------------------------
    def needs_file(sc) -> bool:
        """Photos, clips and manual scenes need a file; charts with data, stats and Blender scenes draw themselves."""
        v = sc.visual
        if v.type in ("photo", "video", "manual"):
            return True
        return v.type == "chart" and not (v.params.get("labels") and v.params.get("values"))

    visual_scenes = [s for s in (sf.scenes if sf else []) if needs_file(s)]
    have = [s for s in visual_scenes if find_asset(project, s)]
    fetched = (cache_dir / "fetch.json").exists()
    if not sf:
        steps.append(Step("fetch", "Visuals", "blocked", "No valid scenes.json yet."))
    else:
        complete = fetched or (visual_scenes and len(have) == len(visual_scenes))
        steps.append(Step("fetch", "Visuals", "done" if complete else "todo",
                          f"{len(have)}/{len(visual_scenes)} scenes have a visual.",
                          ([] if complete else ["Fetch visuals."]) + (env_warnings() if not complete else []),
                          ["assets/images/", "assets/videos/", "assets/credits.json"]))

    # 5 manual assets -----------------------------------------------------
    todo_manual = pending(project, sf) if sf else []
    if not sf:
        steps.append(Step("manual", "Manual assets", "blocked"))
    elif todo_manual:
        steps.append(Step("manual", "Manual assets", "todo", f"{len(todo_manual)} scene(s) need a file from you.",
                          [f"Scene {s.id}: {s.visual.prompt or s.visual.query or 'add an image or clip'}" for s in todo_manual],
                          ["inbox/"]))
    else:
        steps.append(Step("manual", "Manual assets", "done", "Nothing missing.", optional=True))

    # 6 draft -------------------------------------------------------------
    targets = list_targets(sf) if sf else []
    asset_inputs = [script_dir / "scenes.json", *(project / "assets").rglob("*")]
    drafts = [(t, project / draft_out(t)) for t in targets if (project / draft_out(t)).exists()]
    if not sf:
        steps.append(Step("draft", "Draft preview", "blocked"))
    elif drafts:
        stale = any(_newest(asset_inputs) > _mtime(d) for _, d in drafts) or len(drafts) < len(targets)
        steps.append(Step("draft", "Draft preview", "stale" if stale else "done",
                          "Scenes or visuals changed since the draft." if stale else
                          f"Silent preview at 150 wpm ({', '.join(t.id for t, _ in drafts)}).",
                          ["Re-render the draft to see the changes."] if stale else [],
                          [draft_out(t) for t, _ in drafts], optional=True))
    else:
        steps.append(Step("draft", "Draft preview", "todo", "Silent preview at 150 wpm, reduced size.",
                          ["Render a draft to check the visuals."], optional=True))

    # 7 review ------------------------------------------------------------
    review = read_json(build / "review.json", {})
    kept = sum(1 for s in have if review.get(str(s.id)) == "keep")
    if not have:
        steps.append(Step("review", "Review visuals", "blocked" if not sf else "optional", "No visuals to review yet.", optional=True))
    else:
        steps.append(Step("review", "Review visuals", "done" if kept == len(have) else "todo",
                          f"{kept}/{len(have)} kept.",
                          [] if kept == len(have) else ["Keep, replace or refetch each scene's visual."], optional=True))

    # 8 record ------------------------------------------------------------
    rec_todo, rec_stale, rec_done = [], [], []
    for t in targets:
        audio = project / t.audio
        mins = sum(len(sf.scene(i).text.split()) for i in t.scene_ids) / 150 if sf else 0
        if not audio.exists():
            rec_todo.append(f"Record {t.label} ({len(t.scene_ids)} scenes, about {mins:.0f} min)" if mins >= 1.5
                            else f"Record {t.label} ({len(t.scene_ids)} scenes, about {mins * 60:.0f}s)")
        elif _mtime(script_dir / "scenes.json") > _mtime(audio) and _text_changed_since(project, sf, t):
            rec_stale.append(t.label)
        else:
            rec_done.append(t.label)
    if not sf:
        steps.append(Step("record", "Record narration", "blocked"))
    elif rec_todo:
        steps.append(Step("record", "Record narration", "todo",
                          f"{len(rec_done)}/{len(targets)} recorded." if len(targets) > 1 else "Read the scenes in order.",
                          rec_todo, [t.audio for t in targets if (project / t.audio).exists()]))
    elif rec_stale:
        steps.append(Step("record", "Record narration", "stale", "Scene text changed after: " + ", ".join(rec_stale),
                          [f"Re-record {x} so the voice matches the script." for x in rec_stale], [t.audio for t in targets]))
    else:
        steps.append(Step("record", "Record narration", "done",
                          "All recordings saved." if len(targets) > 1 else "Recording saved.", [], [t.audio for t in targets]))

    # 9 final -------------------------------------------------------------
    have_audio = [t for t in targets if (project / t.audio).exists()]
    finished = [t for t in targets if (project / t.out).exists()]
    stale_finals = [t for t in finished if _newest([project / t.audio, *asset_inputs]) > _mtime(project / t.out)]
    outs = [t.out for t in finished] + [t.out.rsplit(".", 1)[0] + ".srt" for t in finished
                                        if t.kind == "long" and (project / t.out).with_suffix(".srt").exists()]
    pending = [t for t in have_audio if t not in finished or t in stale_finals]
    if not have_audio:
        steps.append(Step("final", "Final render", "blocked", "Needs the narration recording."))
    elif pending:
        why = "Inputs changed since the last render." if stale_finals and not [t for t in have_audio if t not in finished] \
            else "Aligns your voice and renders the video."
        steps.append(Step("final", "Final render", "stale" if (stale_finals and len(pending) == len(stale_finals)) else "todo",
                          why, [f"Render {t.label}." for t in pending], outs))
    else:
        steps.append(Step("final", "Final render", "done",
                          "Aligned to your voice, -14 LUFS" + (", captions burned in." if any(t.kind == "reel" for t in finished) else "."),
                          [], outs))

    # with a brief but no script yet, scenes.json is still the starter template: later steps must wait
    script = next(st for st in steps if st.key == "script")
    if brief.get("topic") and script.status in ("todo", "waiting", "blocked"):
        for st in steps:
            if st.key in ("facts", "fetch", "manual", "draft", "review", "record", "final"):
                st.status, st.todos, st.outputs = "blocked", [], []
                st.detail = "Waits for the script."

    final = steps[-1]
    if final.status == "done":
        for st in steps:
            if st.key in ("draft", "review") and st.status in ("todo", "stale"):
                st.status, st.todos = "optional", []

    steps.append(Step("publish", "Package & publish", "later", "Cover, captions, YouTube and Instagram upload arrive in Phase 4."))
    return steps


def _text_changed_since(project: Path, sf: ScenesFile, target: Target) -> bool:
    """True if the narrated text differs from what the last alignment of this video used."""
    tl = read_json(project / target.timeline, None)
    if not tl:
        return False
    aligned = {s["id"]: " ".join(w["w"] for w in s.get("words", [])) for s in tl.get("scenes", [])}
    for sid, words in aligned.items():
        try:
            now = " ".join(w for w in sf.scene(sid).text.split() if re.search(r"\w", w))
        except StopIteration:
            return True
        if now != words:
            return True
    return False


def next_step(steps: list[Step]) -> Step | None:
    for s in steps:
        if s.status in ("todo", "waiting", "stale") and not s.optional:
            return s
    for s in steps:
        if s.status in ("todo", "waiting", "stale"):
            return s
    return None


def stage_label(steps: list[Step]) -> str:
    by = {s.key: s for s in steps}
    if by["final"].status == "done":
        return "rendered"
    nxt = next_step(steps)
    return f"next: {nxt.title.lower()}" if nxt else "up to date"
