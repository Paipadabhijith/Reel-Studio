"""Turning a source link into readable text for the script prompt.

- YouTube (videos and Shorts): title, channel, description and the subtitles or auto-captions, via yt-dlp.
  Nothing is downloaded except the caption text.
- Other pages: the HTML through trafilatura; if that yields almost nothing (pages that build themselves with
  JavaScript), Jina Reader (https://r.jina.ai) renders the page and returns its text. That sends the URL to Jina;
  set JINA_READER=0 in .env to turn the fallback off.
"""
from __future__ import annotations

import os
import re

import httpx

MIN_WORDS = 80          # below this a source is "thin": probably a menu, a cookie wall or a video page
JINA = "https://r.jina.ai/"
_YOUTUBE = re.compile(r"^https?://(?:www\.|m\.)?(?:youtube\.com/(?:watch|shorts/|live/)|youtu\.be/)", re.I)


def words(text: str) -> int:
    return len(re.findall(r"\w+", text or ""))


def is_youtube(url: str) -> bool:
    return bool(_YOUTUBE.match(url))


# ---------------------------------------------------------------- YouTube


def _pick_track(info: dict) -> tuple[str, list[dict], str] | None:
    """Best caption track: uploaded subtitles first, then the video's own-language auto captions, then en/hi."""
    lang = (info.get("language") or "").split("-")[0]
    subs = info.get("subtitles") or {}
    auto = info.get("automatic_captions") or {}
    for pool, kind in ((subs, "subtitles"), (auto, "auto-captions")):
        keys = list(pool)
        order = [k for k in keys if k.endswith("-orig")] + [k for k in (lang, "en", "hi") if k in pool]
        order += [k for k in keys if k.split("-")[0] in ("en", "hi")]
        if kind == "subtitles":
            order += keys  # any uploaded subtitles beat machine translations
        for k in order:
            if k in pool and pool[k]:
                return k, pool[k], kind
    return None


def _caption_text(http: httpx.Client, formats: list[dict]) -> str:
    """Plain text of a caption track (json3 preferred, vtt as fallback), consecutive repeats removed."""
    by_ext = {f.get("ext"): f.get("url") for f in formats}
    lines: list[str] = []
    if by_ext.get("json3"):
        data = http.get(by_ext["json3"]).raise_for_status().json()
        for ev in data.get("events", []):
            seg = "".join(s.get("utf8", "") for s in ev.get("segs") or []).strip()
            if seg:
                lines.append(seg)
    elif by_ext.get("vtt"):
        for line in http.get(by_ext["vtt"]).raise_for_status().text.splitlines():
            line = re.sub(r"<[^>]+>", "", line).strip()
            if line and "-->" not in line and line != "WEBVTT" and not line.startswith(("Kind:", "Language:", "NOTE")):
                lines.append(line)
    out: list[str] = []
    for line in lines:
        if not out or out[-1] != line:
            out.append(line)
    return " ".join(" ".join(out).split())


def youtube_text(url: str, http: httpx.Client, log=print) -> str:
    """Title, channel, description and transcript of a YouTube video or Short. Empty if yt-dlp can't read it."""
    import yt_dlp

    try:
        with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True, "skip_download": True}) as y:
            info = y.extract_info(url, download=False)
    except Exception as e:  # yt-dlp raises many kinds; a source we can't read is not fatal
        log(f"articles: yt-dlp could not read {url}: {str(e).splitlines()[0][:160]}")
        return ""
    parts = [f"TITLE: {info.get('title') or ''}", f"CHANNEL: {info.get('channel') or info.get('uploader') or ''}"]
    if info.get("upload_date"):
        d = info["upload_date"]
        parts.append(f"PUBLISHED: {d[:4]}-{d[4:6]}-{d[6:]}")
    if (info.get("description") or "").strip():
        parts.append("DESCRIPTION:\n" + info["description"].strip())
    track = _pick_track(info)
    if track:
        lang, formats, kind = track
        try:
            transcript = _caption_text(http, formats)
        except (httpx.HTTPError, ValueError) as e:
            log(f"articles: could not fetch the {kind} of {url}: {e}")
            transcript = ""
        if transcript:
            parts.append(f"TRANSCRIPT ({kind}, {lang}; machine captions can mishear names and numbers):\n{transcript}")
    else:
        log(f"articles: {url} has no subtitles or captions; only its title and description are used")
    return "\n\n".join(parts)


# ---------------------------------------------------------------- web pages


def jina_enabled() -> bool:
    return os.getenv("JINA_READER", "1").strip().lower() not in ("0", "false", "no", "off")


def jina_text(url: str, http: httpx.Client, log=print) -> str:
    try:
        r = http.get(JINA + url, headers={"Accept": "text/plain", "X-Return-Format": "text"}, timeout=60)
        r.raise_for_status()
    except httpx.HTTPError as e:
        log(f"articles: Jina Reader could not read {url}: {e}")
        return ""
    return r.text.strip()


def fetch_source(url: str, http: httpx.Client, extract, log=print) -> tuple[str, str]:
    """(text, how it was read). `extract` turns HTML into text (trafilatura). Never raises for a bad page."""
    if is_youtube(url):
        return youtube_text(url, http, log), "youtube"
    text = ""
    try:
        r = http.get(url)
        r.raise_for_status()
        text = extract(r.text, url)
    except httpx.HTTPError as e:
        log(f"articles: could not download {url}: {e}")
    if words(text) >= MIN_WORDS or not jina_enabled():
        return text, "page"
    log(f"articles: {url} gave only {words(text)} words; trying Jina Reader (renders JavaScript pages)")
    rendered = jina_text(url, http, log)
    return (rendered, "jina") if words(rendered) > words(text) else (text, "page")


def header(url: str, via: str) -> str:
    return f"SOURCE: {url}\nVIA: {via}"


def parse_cached(raw: str) -> tuple[str | None, str]:
    """(how it was read, body) of a saved _url_ file. Files saved before VIA existed return None."""
    head, _, body = raw.partition("\n\n")
    m = re.search(r"^VIA: (\S+)", head, re.M)
    return (m.group(1) if m else None), body

