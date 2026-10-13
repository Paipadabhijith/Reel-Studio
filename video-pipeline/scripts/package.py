"""`reel package`: everything that goes around a finished video, ready to paste.

Titles (ranked, with what is wrong with each), thumbnail text, a YouTube description, an Instagram caption,
chapters for long-form (from the real render timings), sources, credits and hashtags. The words come from the
script (Claude writes `packaging` alongside the scenes); this module checks them and assembles the rest.
Nothing is uploaded: you paste it.

The title rules follow title.py and the yt-seo / yt-chapters skills in youtube-agent-skill (Jake Schincariol,
MIT licence): 60 characters for desktop search, 40 for a phone feed, at most two all-caps words, a number, name or
date, no vague hype words, a thumbnail that adds words instead of repeating them, and YouTube's chapter rules.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from .lib.schema import Packaging, ScenesFile
from .lib.targets import Target

DESKTOP, MOBILE, HARD = 60, 40, 100
VAGUE = {"amazing", "incredible", "insane", "crazy", "huge", "massive", "ultimate", "best", "powerful", "secret",
         "revolutionary", "mindblowing", "epic", "perfect", "complete", "everything", "shocking", "unbelievable",
         "zabardast", "khatarnak", "dhamakedar"}
STOP = {"the", "a", "an", "of", "for", "to", "in", "on", "and", "or", "is", "are", "with", "your", "you", "my", "i",
        "this", "that", "it", "how", "what", "why", "ka", "ki", "ke", "ko", "se", "hai", "ne", "aur", "kya", "kaise"}
GENERIC_TAGS = {"#viral", "#trending", "#fyp", "#foryou", "#explore", "#reels", "#instagood", "#explorepage"}


def _words(t: str) -> list[str]:
    return re.findall(r"[a-z0-9']+", t.lower())


def lint_title(title: str, thumb: str | None = None) -> dict:
    """Score a title (and its thumbnail text) 0-100 and say what is wrong. Lower is worse, never a promise."""
    t = title.strip()
    n = len(t)
    issues, good = [], []
    if n > HARD:
        issues.append(f"{n} characters: over YouTube's {HARD} limit")
    elif n > DESKTOP:
        issues.append(f"{n} characters: desktop search cuts near {DESKTOP}")
    else:
        good.append(f"{n} characters")
    if n > MOBILE:
        issues.append(f'a phone feed shows about "{t[:MOBILE].rsplit(" ", 1)[0]}…": check the subject survives')
    caps = [w for w in t.split() if len(w) > 2 and w.isupper() and not any(c.isdigit() for c in w)]
    if len(caps) > 2:
        issues.append(f"{len(caps)} ALL-CAPS words: more than two reads as spam")
    vague = sorted({w for w in _words(t) if w in VAGUE})
    if vague:
        issues.append(f"vague: {', '.join(vague)}; swap for a number, name or date")
    if re.search(r"\d", t):
        good.append("has a number")
    elif not any(w[:1].isupper() for w in t.split()[1:]):
        issues.append("no number, date or name: the most reliable single fix")
    if not [w for w in _words(t)[:3] if w not in STOP]:
        issues.append("first three words are filler: move the subject forward")
    if thumb:
        shared = (set(_words(t)) - STOP) & (set(_words(thumb)) - STOP)
        if shared:
            issues.append(f"thumbnail repeats the title ({', '.join(sorted(shared))}): it should add, not echo")
        if len(_words(thumb)) > 3:
            issues.append(f"{len(_words(thumb))} words on the thumbnail: three is the ceiling at feed size")
    score = max(0, min(100, 100 - 14 * len(issues) + 4 * len(good)))
    return {"title": t, "chars": n, "score": score, "issues": issues}


def mmss(sec: float) -> str:
    s = int(sec)
    h, m, s = s // 3600, (s % 3600) // 60, s % 60
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def chapter_lines(project: Path, sf: ScenesFile, target: Target) -> tuple[list[str], list[str]]:
    """YouTube chapter lines from the real timings, and the rule problems (first at 0:00, 3+ chapters, 10 s each)."""
    from .lib.state import _load_timeline
    from .render_final import FPS, chapter_frames, chapters_for

    chapters = chapters_for(sf, target)
    tl = _load_timeline(project, target)
    if tl is None or len(chapters) < 2:
        return [], []
    frames = chapter_frames(tl, chapters)
    lines, problems = [], []
    for (title, _), (a, b) in zip(chapters, frames):
        if (b - a) / FPS < 10:
            problems.append(f'"{title}" is only {(b - a) / FPS:.0f} s; YouTube needs 10 s per chapter')
        lines.append(f"{mmss(a / FPS)} {title}")
    if len(lines) < 3:
        problems.append("YouTube needs at least 3 chapters to show them")
    return lines, problems


def _credits(project: Path, target: Target) -> list[str]:
    from . import music

    f = project / "assets" / "credits.json"
    rows = json.loads(f.read_text()) if f.exists() else []
    ids = set(target.scene_ids)
    seen, out = set(), []
    for c in rows:
        if c.get("scene_id") in ids and c.get("attribution_text") and c["attribution_text"] not in seen:
            seen.add(c["attribution_text"])
            out.append(c["attribution_text"])
    track = music.get(project, target)
    if track:
        out.append(track.credit)
    return out


def _hashtags(tags: list[str]) -> list[str]:
    out = []
    for t in tags:
        t = "#" + re.sub(r"[^\w]", "", t.lstrip("#"))
        if len(t) > 1 and t.lower() not in GENERIC_TAGS and t.lower() not in {x.lower() for x in out}:
            out.append(t)
    return out[:6]


def _trim(lines: list[str]) -> list[str]:
    """Drop the blank separators left at the start when an earlier part was empty."""
    while lines and not lines[0].strip():
        lines = lines[1:]
    return lines


def build(project: Path, sf: ScenesFile, target: Target, brief_urls: list[str]) -> str:
    """The package as Markdown."""
    pk = next((p for p in sf.packaging if p.video == target.id), None) or Packaging(video=target.id)
    ranked = sorted((lint_title(t, pk.thumbnail_text or None) for t in pk.titles), key=lambda r: -r["score"])
    best = ranked[0]["title"] if ranked else ""
    tags = _hashtags(pk.hashtags)
    chapters, chapter_problems = chapter_lines(project, sf, target) if target.kind == "long" else ([], [])
    credits = _credits(project, target)

    md = [f"# Package: {target.label}", "",
          f"Video: `{target.out}`. Nothing here is uploaded; copy what you need.", ""]
    md += ["## Titles", ""]
    if not ranked:
        md += ["No titles yet: this script was written before packaging existed. Regenerate the script to get them.", ""]
    for i, r in enumerate(ranked, 1):
        md.append(f"{i}. **{r['title']}** ({r['chars']} chars, score {r['score']}/100)")
        md += [f"   - {x}" for x in r["issues"]]
    md += ["", "## Thumbnail text", "", f"**{pk.thumbnail_text}**" if pk.thumbnail_text else "(none written)", ""]

    if pk.search_queries:
        md += ["## Search check", ""]
        hay = set(_words(best + " " + pk.description_lead))
        for q in pk.search_queries:
            missing = [w for w in _words(q) if w not in STOP and w not in hay]
            md.append(f"- `{q}`: " + ("✓ covered by the top title and description" if not missing
                                       else f"missing {', '.join(missing)} from the top title and description"))
        md.append("")

    desc = [pk.description_lead.strip()] if pk.description_lead.strip() else []
    if chapters:
        desc += ["", "Chapters", *chapters]
    if brief_urls:
        desc += ["", "Sources", *[f"- {u}" for u in brief_urls]]
    if credits:
        desc += ["", "Credits", *[f"- {c}" for c in credits]]
    if tags:
        desc += ["", " ".join(tags[:3])]  # YouTube shows the first three above the title
    md += ["## YouTube description", "", "```", *_trim(desc), "```", ""]
    if chapter_problems:
        md += ["Chapter problems (YouTube will not show chapters until these are fixed):", *[f"- {p}" for p in chapter_problems], ""]

    if target.kind == "reel":
        caption = [pk.description_lead.strip() or best]
        if credits:
            caption += ["", "Credits: " + "; ".join(credits)]
        if tags:
            caption += ["", " ".join(tags)]
        md += ["## Instagram caption", "", "```", *_trim(caption), "```", ""]
    return "\n".join(md).rstrip() + "\n"


def package_path(target: Target) -> str:
    return f"out/{target.id}_package.md"


def write(project: Path, sf: ScenesFile, target: Target, log=print) -> Path:
    from .generate_script import parse_brief

    brief_file = project / "input" / "brief.md"
    urls = parse_brief(brief_file.read_text()).get("source_urls", []) if brief_file.exists() else []
    out = project / package_path(target)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(build(project, sf, target, urls))
    log(f"package: {out}")
    return out
