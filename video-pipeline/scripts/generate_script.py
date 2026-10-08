"""`reel script`: brief + articles -> scenes.json, script.md, hooks.md, facts.md via Claude."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import httpx

from .lib import cache
from .lib.schema import ScenesFile, dump_json, load_scenes

MODEL = "claude-opus-5-5"
PROMPT_VERSION = "script-v3"
MAX_TOKENS = 64000
USER_AGENT = "Mozilla/5.0 (Macintosh; video-pipeline personal research tool)"

# ---------------------------------------------------------------- brief + articles


def parse_brief(text: str) -> dict:
    """Read `- key: value` lines; `source_urls` may continue on indented `- url` lines."""
    brief: dict = {"source_urls": []}
    key = None
    for raw in text.splitlines():
        line = re.sub(r"\s+#.*$", "", raw).rstrip()
        m = re.match(r"^-\s*([a-z_]+):\s*(.*)$", line)
        if m:
            key, val = m.group(1), m.group(2).strip()
            if key == "source_urls":
                brief["source_urls"] += re.findall(r"https?://\S+", val)
            else:
                brief[key] = val
            continue
        m = re.match(r"^\s+-\s*(\S+)", line)
        if m and key == "source_urls" and m.group(1).startswith("http"):
            brief["source_urls"].append(m.group(1))
    brief["formats"] = (brief.get("formats") or "both").lower()
    if brief["formats"] not in ("reel", "long", "both"):
        brief["formats"] = "both"
    try:
        brief["reel_count"] = max(1, min(3, int(brief.get("reel_count") or 2)))
    except ValueError:
        brief["reel_count"] = 2
    brief["language"] = (brief.get("language") or "hinglish").lower()
    if brief["language"] not in ("en", "hi", "hinglish"):
        brief["language"] = "hinglish"
    return brief


def _extract(html_text: str, url: str | None = None) -> str:
    import trafilatura

    return trafilatura.extract(html_text, url=url, include_comments=False, include_tables=True) or ""


def load_articles(project: Path, urls: list[str], http: httpx.Client | None = None, log=print) -> list[dict]:
    """Local files in input/articles/ plus the brief's URLs (downloaded once, saved as text)."""
    art_dir = project / "input" / "articles"
    art_dir.mkdir(parents=True, exist_ok=True)
    articles: list[dict] = []
    fetched_names = set()
    own = http is None
    http = http or httpx.Client(timeout=30, follow_redirects=True, headers={"User-Agent": USER_AGENT})
    try:
        for url in urls:
            name = f"_url_{hashlib.sha1(url.encode()).hexdigest()[:10]}.txt"
            fetched_names.add(name)
            path = art_dir / name
            if not path.exists():
                try:
                    r = http.get(url)
                    r.raise_for_status()
                    text = _extract(r.text, url)
                except httpx.HTTPError as e:
                    log(f"articles: could not download {url}: {e}")
                    continue
                if not text.strip():
                    log(f"articles: no readable text in {url}; save it as a .txt in input/articles/ instead")
                    continue
                path.write_text(f"SOURCE: {url}\n\n{text}")
                log(f"articles: saved {url} -> {name}")
            body = path.read_text().split("\n\n", 1)[-1]
            articles.append({"source": url, "text": body})
    finally:
        if own:
            http.close()
    for f in sorted(art_dir.iterdir()):
        if f.name in fetched_names or f.name.startswith("."):
            continue
        if f.suffix.lower() in (".txt", ".md"):
            articles.append({"source": f.name, "text": f.read_text()})
        elif f.suffix.lower() in (".html", ".htm"):
            articles.append({"source": f.name, "text": _extract(f.read_text())})
        elif not f.name.startswith("_url_"):
            log(f"articles: skipping {f.name} (use .txt, .md or .html)")
    return [a for a in articles if a["text"].strip()]


# ---------------------------------------------------------------- prompt

SYSTEM = """You write narration scripts and shot lists for a solo creator's Instagram Reels and YouTube videos.
Topics span current affairs, explainers, sports and Bollywood. The creator records the narration in their own voice,
then a pipeline pulls stock visuals and renders the video. Your output is machine-read, so follow the schema exactly.

Writing
- One scene = one sentence or two short ones (about 6-25 words), which is what's on screen while it is spoken.
- Reels: 30-60 seconds spoken (about 75-150 words at 150 wpm). Scene 1 of every reel is a hook that makes someone stop scrolling.
- Long-form: 8-15 minutes (about 1200-2200 words), split into 4-8 chapters.
- Only state facts that the supplied articles support. Every figure, date and claim that a viewer could check goes into `facts`,
  with the URL or filename of the article it came from. If you use something the articles don't support, set
  verified_in_sources to false so the creator checks it before recording.
- `emphasis` lists 1-3 words or short phrases from the scene text that the speaker should stress.

Visuals (be concrete; these are search queries and shot requests)
- photo/video: `query` is a short stock-photo search (3-6 plain English words describing what is visible, e.g.
  "crowd queue polling booth india"). Use `source: "wikimedia"` for landmarks, historical events and public figures
  photographed at public events; otherwise `source: "stock"`.
- For sports and Bollywood prefer charts, stats and generic stock scenes (stadium crowd, film set lights).
  Never plan scraped celebrity photos or match footage.
- Recent events, screenshots, documents, or a specific person that stock sites won't have: `type: "manual"` with a
  `prompt` telling the creator exactly what to find (e.g. "Screenshot of the ministry's press release headline").
- chart: an animated bar, line or pie chart; fill `chart` with numbers taken from the articles only (2-6 values, short labels).
- stat: one big count-up number on its own card (`value` like "76%" or "1,20,000", plus a short `label`), put in `overlay`.
  An `overlay` of type stat on a photo or video scene shows the same number as a small badge over the picture.
- blender: a 3D map of India; only for a scene about places. `template: "india_map"`, `blender.highlight_states` lists the
  states to light up in order, as 2-letter codes (e.g. KA, TN, KL, TS, MH, UP; Telangana is TS, Odisha is OD, Uttarakhand is UK),
  `camera` is one of top_down_tilt, top_down, orbit. Use at most one or two per video.
- animation: an animated headline graphic (no stock photo). Use it for abstract ideas, concepts and numbers that no photo
  shows; `animation.headline` is 1-3 strong words, `subline` the supporting phrase. Pictures that cannot be found are
  turned into animations automatically, so prefer a photo when one clearly exists.
- Never plan AI-generated likenesses of real people.
- Orientation: "portrait" for scenes used in a reel, "landscape" for long-form-only scenes.

Structure
- Scene ids are unique integers starting at 1. Reels list their scene ids in the order they are spoken and may reuse
  long-form scenes or add their own. Chapters list long-form scene ids in order. `hook_scene` must be one of the reel's scenes.
"""

LANGUAGE_RULES = {
    "hinglish": "Write all narration in Hinglish: conversational Hindi mixed with English, in Roman (Latin) script only, "
                "never Devanagari. Spell Hindi words the way people type them in chats (e.g. 'Aaj hum dekhenge ki...').",
    "hi": "Write all narration in Hindi in Devanagari script.",
    "en": "Write all narration in clear, conversational English.",
}


def build_user_prompt(brief_text: str, brief: dict, articles: list[dict]) -> str:
    fmt = brief["formats"]
    wants = {
        "reel": f"{brief['reel_count']} Reel(s), no long-form (return an empty chapters list).",
        "long": "One long-form video, no reels (return an empty reels list).",
        "both": f"One long-form video and {brief['reel_count']} Reel(s).",
    }[fmt]
    parts = [
        f"Produce: {wants}",
        LANGUAGE_RULES[brief["language"]],
        "Search queries, prompts and fact claims stay in English.",
        f"<brief>\n{brief_text.strip()}\n</brief>",
    ]
    for i, a in enumerate(articles, 1):
        parts.append(f'<article index="{i}" source="{a["source"]}">\n{a["text"].strip()}\n</article>')
    if not articles:
        parts.append("No articles were supplied: keep claims general and mark any specific figure as unverified.")
    return "\n\n".join(parts)


def _nullable(schema: dict) -> dict:
    return {"anyOf": [schema, {"type": "null"}]}


def _obj(props: dict) -> dict:
    return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}


STR, INT, NUM = {"type": "string"}, {"type": "integer"}, {"type": "number"}

OUTPUT_SCHEMA = _obj({
    "title": STR,
    "hooks": {"type": "array", "items": STR},
    "facts": {"type": "array", "items": _obj({
        "claim": STR, "figure": _nullable(STR), "date": _nullable(STR),
        "source": _nullable(STR), "verified_in_sources": {"type": "boolean"},
    })},
    "chapters": {"type": "array", "items": _obj({"title": STR, "scene_ids": {"type": "array", "items": INT}})},
    "reels": {"type": "array", "items": _obj({
        "id": STR, "scene_ids": {"type": "array", "items": INT}, "hook_scene": INT,
    })},
    "scenes": {"type": "array", "items": _obj({
        "id": INT,
        "text": STR,
        "emphasis": {"type": "array", "items": STR},
        "visual": _obj({
            "type": {"type": "string", "enum": ["photo", "video", "chart", "text_card", "stat", "manual", "blender", "animation"]},
            "query": _nullable(STR),
            "source": _nullable({"type": "string", "enum": ["stock", "wikimedia"]}),
            "orientation": _nullable({"type": "string", "enum": ["portrait", "landscape", "square"]}),
            "motion": _nullable({"type": "string", "enum": ["slow-zoom-in", "slow-zoom-out", "pan-left", "pan-right"]}),
            "prompt": _nullable(STR),
            "chart": _nullable(_obj({
                "kind": {"type": "string", "enum": ["bar", "line", "pie"]},
                "title": STR, "unit": _nullable(STR),
                "labels": {"type": "array", "items": STR}, "values": {"type": "array", "items": NUM},
            })),
            "animation": _nullable(_obj({
                "style": {"type": "string", "enum": ["kinetic", "burst", "rings"]}, "headline": STR, "subline": _nullable(STR),
            })),
            "blender": _nullable(_obj({
                "template": STR, "highlight_states": {"type": "array", "items": STR}, "camera": _nullable(STR),
            })),
        }),
        "overlay": _nullable(_obj({
            "type": {"type": "string", "enum": ["stat", "text"]}, "value": _nullable(STR), "label": _nullable(STR),
        })),
    })},
})


# ---------------------------------------------------------------- Claude call


class ScriptError(RuntimeError):
    pass


def call_claude(system: str, user: str, log=print) -> str:
    import anthropic

    client = anthropic.Anthropic()
    log(f"script: asking {MODEL} (streaming; this can take a few minutes)")
    try:
        with client.beta.messages.stream(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=system,
            messages=[{"role": "user", "content": user}],
            output_config={"effort": "high", "format": {"type": "json_schema", "schema": OUTPUT_SCHEMA}},
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",  # re-run on Anthropic's recommended model if a safety classifier declines
        ) as stream:
            msg = stream.get_final_message()
    except TypeError as e:
        if "authentication" not in str(e).lower():
            raise
        raise ScriptError("no Anthropic API credentials found. Add ANTHROPIC_API_KEY to .env, "
                          "or use `reel script <slug> --manual` to write the script in claude.ai instead")
    except anthropic.AuthenticationError:
        raise ScriptError("Anthropic API rejected the key; check ANTHROPIC_API_KEY in .env, "
                          "or use `reel script <slug> --manual`")
    except anthropic.RateLimitError:
        raise ScriptError("rate limited by the Anthropic API; try again in a minute")
    except anthropic.APIStatusError as e:
        raise ScriptError(f"Anthropic API error {e.status_code}: {e.message}")
    except anthropic.APIConnectionError:
        raise ScriptError("could not reach the Anthropic API; check your internet connection")

    if msg.stop_reason == "refusal":
        cat = getattr(msg.stop_details, "category", None) if msg.stop_details else None
        raise ScriptError(f"the model declined this brief (category: {cat}); rephrase the brief or articles")
    if msg.stop_reason == "max_tokens":
        raise ScriptError("the response hit the token limit; shorten the articles or ask for fewer reels")
    text = next((b.text for b in msg.content if b.type == "text"), "")
    if not text:
        raise ScriptError("empty response from the model")
    u = msg.usage
    log(f"script: done ({u.input_tokens} in / {u.output_tokens} out tokens, model {msg.model})")
    return text


# ---------------------------------------------------------------- outputs


def to_scenes_file(slug: str, brief: dict, data: dict) -> ScenesFile:
    scenes = []
    for s in data["scenes"]:
        v = dict(s["visual"])
        chart, blender = v.pop("chart", None), v.pop("blender", None)
        params: dict = {}
        if chart:
            params = chart
        if blender:
            v["template"] = blender.pop("template")
            params = {k: val for k, val in blender.items() if val is not None}
        anim = v.pop("animation", None)
        if anim:
            params = {k: val for k, val in anim.items() if val not in (None, "", [])}
        v["params"] = params
        scenes.append({**s, "visual": {k: val for k, val in v.items() if val is not None}})
    fmt = brief["formats"]
    return ScenesFile.model_validate({
        "project": slug,
        "format": fmt,
        "brand": "default",
        "language": brief["language"],
        "long_form": {"chapters": data["chapters"]} if data["chapters"] and fmt != "reel" else None,
        "reels": data["reels"] if fmt != "long" else [],
        "scenes": scenes,
    })


def render_script_md(title: str, sf: ScenesFile) -> str:
    out = [f"# {title}", ""]
    if sf.long_form:
        out += ["## Long-form", ""]
        for ch in sf.long_form.chapters:
            out += [f"### {ch.title}", ""]
            out += [f"[{i}] {sf.scene(i).text}" for i in ch.scene_ids]
            out.append("")
    for r in sf.reels:
        out += [f"## {r.id}", "", "Read these in order for this reel's narration:", ""]
        out += [f"[{i}] {sf.scene(i).text}" for i in r.scene_ids]
        out.append("")
    return "\n".join(out)


def render_facts_md(facts: list[dict]) -> str:
    out = ["# Facts to verify before recording", "", "Tick each one after checking it against the source.", ""]
    for f in facts:
        bits = [b for b in (f.get("figure"), f.get("date")) if b]
        flag = "" if f.get("verified_in_sources") else " **(NOT in the supplied sources)**"
        out.append(f"- [ ] {f['claim']}{' (' + ', '.join(bits) + ')' if bits else ''}{flag}")
        out.append(f"      source: {f.get('source') or 'none'}")
    return "\n".join(out) + "\n"


def _prepare(project: Path, log) -> tuple[dict, str, str]:
    """Read brief + articles and build the prompt. Returns (brief, user prompt, cache digest)."""
    brief_path = project / "input" / "brief.md"
    brief_text = brief_path.read_text()
    brief = parse_brief(brief_text)
    if not brief.get("topic"):
        raise ScriptError(f"fill in at least `topic` in {brief_path}")
    articles = load_articles(project, brief["source_urls"], log=log)
    log(f"script: {len(articles)} article(s), formats={brief['formats']}, reels={brief['reel_count']}, "
        f"language={brief['language']}")
    user = build_user_prompt(brief_text, brief, articles)
    return brief, user, cache.hash_inputs(SYSTEM, user, OUTPUT_SCHEMA, PROMPT_VERSION)


def _outputs(project: Path) -> list[Path]:
    return [project / "script" / n for n in ("scenes.json", "script.md", "hooks.md", "facts.md")]


def extract_json(text: str) -> dict:
    """Accept a bare JSON object, or one wrapped in ```json fences / surrounded by chat text."""
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("no JSON object found")
    return json.loads(text[start: end + 1])


def _write_outputs(project: Path, brief: dict, text: str, digest: str, raw_label: Path, log) -> ScenesFile:
    try:
        data = extract_json(text)
        sf = to_scenes_file(project.name, brief, data)
        title, hooks, facts = data["title"], data["hooks"], data["facts"]
    except (json.JSONDecodeError, ValueError, KeyError, TypeError) as e:
        raise ScriptError(f"script JSON did not validate ({type(e).__name__}: {e}); see {raw_label}")

    script_dir = project / "script"
    scenes_path = script_dir / "scenes.json"
    if scenes_path.exists() and scenes_path.read_text().strip():
        scenes_path.with_suffix(".json.bak").write_text(scenes_path.read_text())
    dump_json(sf, scenes_path)
    (script_dir / "script.md").write_text(render_script_md(title, sf))
    (script_dir / "hooks.md").write_text("# Alternative hooks\n\n" + "\n".join(f"- {h}" for h in hooks) + "\n")
    (script_dir / "facts.md").write_text(render_facts_md(facts))
    cache.mark(project / "build" / "cache", "script", digest)
    unverified = sum(1 for f in facts if not f.get("verified_in_sources"))
    log(f"script: {len(sf.scenes)} scenes, {len(sf.reels)} reel(s), "
        f"{len(sf.long_form.chapters) if sf.long_form else 0} chapter(s); "
        f"{len(facts)} facts to check ({unverified} not in sources)")
    return sf


def generate(project: Path, force: bool = False, llm=call_claude, log=print) -> ScenesFile:
    """API mode: one command, needs ANTHROPIC_API_KEY."""
    brief, user, digest = _prepare(project, log)
    cache_dir = project / "build" / "cache"
    raw_path = cache_dir / f"script_{digest}.json"
    if not force and cache.is_fresh(cache_dir, "script", digest, _outputs(project)):
        log("script: cached (brief and articles unchanged)")
        return load_scenes(_outputs(project)[0])
    if raw_path.exists() and not force:
        text = raw_path.read_text()  # model already answered this exact prompt; don't pay twice
    else:
        text = llm(SYSTEM, user, log)
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        raw_path.write_text(text)
    return _write_outputs(project, brief, text, digest, raw_path, log)


# ---------------------------------------------------------------- manual mode (no API key)

MANUAL_INSTRUCTIONS = """Reply with ONLY one JSON object (no prose before or after) that matches this JSON Schema.
Every property listed is required; use null where a value doesn't apply.

```json
{schema}
```"""


def manual_prompt_text(user: str) -> str:
    return "\n\n".join([
        SYSTEM.strip(),
        user,
        MANUAL_INSTRUCTIONS.format(schema=json.dumps(OUTPUT_SCHEMA, indent=1)),
    ]) + "\n"


def _copy_to_clipboard(text: str) -> bool:
    import subprocess

    try:
        subprocess.run(["pbcopy"], input=text.encode(), check=True, timeout=10)
        return True
    except (OSError, subprocess.SubprocessError):
        return False


def generate_manual(project: Path, force: bool = False, log=print) -> ScenesFile | None:
    """No-API mode, two runs.

    Run 1 writes script/prompt.md (and copies it) for you to paste into claude.ai.
    Save Claude's reply as script/response.json, then run again to import it.
    Returns the ScenesFile once imported, None while waiting for the reply.
    """
    brief, user, digest = _prepare(project, log)
    script_dir = project / "script"
    cache_dir = project / "build" / "cache"
    prompt_path, response_path = script_dir / "prompt.md", script_dir / "response.json"
    stamp = cache_dir / "manual_prompt.hash"

    if not force and cache.is_fresh(cache_dir, "script", digest, _outputs(project)):
        log("script: cached (brief and articles unchanged)")
        return load_scenes(_outputs(project)[0])

    if response_path.exists() and response_path.read_text().strip():
        written_for = stamp.read_text().strip() if stamp.exists() else None
        if written_for == digest and not force:
            sf = _write_outputs(project, brief, response_path.read_text(), digest, response_path, log)
            response_path.rename(cache_dir / f"script_{digest}.json")  # keep the raw reply, clear the slot
            prompt_path.unlink(missing_ok=True)
            return sf
        old = response_path.with_name("response.old.json")
        response_path.rename(old)
        log(f"script: the brief or articles changed after the prompt was made; moved the old reply to {old.name}")

    cache_dir.mkdir(parents=True, exist_ok=True)
    text = manual_prompt_text(user)
    prompt_path.write_text(text)
    stamp.write_text(digest)
    copied = _copy_to_clipboard(text)
    log(f"script: prompt written to {prompt_path}" + (" and copied to the clipboard" if copied else ""))
    log("  1. open claude.ai, start a new chat, paste the prompt and send")
    log("  2. Studio: paste Claude's whole reply into the box under the prompt and press Import")
    log(f"     Terminal: save the reply as {response_path}, then run `reel script {project.name} --manual` again")
    return None
