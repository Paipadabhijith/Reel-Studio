"""`reel fetch`: download visuals from Pexels, Pixabay, Unsplash and Wikimedia Commons only.

Anything that can't be matched above the relevance threshold is downgraded to a
manual scene and listed in inbox/README.txt.
"""
from __future__ import annotations

import html
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

import httpx

from . import animation, manual_inbox
from .lib.progress import check_cancel
from .lib import cache
from .lib.assets import chart_path, find_asset, image_path, remove_scene_assets, upsert_credit, video_path
from .lib.config import BRAND_FILE
from .lib.schema import Credit, Scene, ScenesFile, dump_json, load_scenes

RELEVANCE_MIN = 0.34
MIN_LONG_EDGE = 1080
USER_AGENT = "video-pipeline/0.1 (personal, non-commercial; local tool)"
STOPWORDS = {
    "a", "an", "the", "of", "in", "on", "at", "to", "for", "and", "or", "with", "by", "from",
    "is", "are", "photo", "image", "picture", "stock", "video", "footage", "shot", "view",
}


@dataclass
class Candidate:
    url: str             # direct download URL
    page_url: str        # human-facing page, goes into credits
    text: str            # description / tags used for relevance
    width: int
    height: int
    source: str
    license: str
    attribution: str
    ext: str = "jpg"
    duration_s: float | None = None
    download_ping: str | None = None  # Unsplash asks apps to hit this on download

    @property
    def orientation(self) -> str:
        if abs(self.width - self.height) < 0.1 * max(self.width, self.height):
            return "square"
        return "portrait" if self.height > self.width else "landscape"


def _tokens(s: str) -> set[str]:
    out = set()
    for t in re.findall(r"[a-z0-9]+", s.lower()):
        if t in STOPWORDS or len(t) < 2:
            continue
        out.add(t[:-1] if len(t) > 3 and t.endswith("s") else t)  # crude plural folding
    return out


def relevance(query: str, text: str) -> float:
    q = _tokens(query)
    return len(q & _tokens(text)) / len(q) if q else 0.0


def score(c: Candidate, query: str, orientation: str | None) -> float:
    s = relevance(query, c.text)
    if orientation and c.orientation != orientation:
        s -= 0.1
    if max(c.width, c.height) < MIN_LONG_EDGE:
        s -= 0.2
    return s


# ---------------------------------------------------------------- providers

def pexels_photos(http: httpx.Client, query: str, orientation: str | None) -> list[Candidate]:
    key = os.getenv("PEXELS_API_KEY")
    if not key:
        return []
    params = {"query": query, "per_page": 15}
    if orientation:
        params["orientation"] = orientation
    r = http.get("https://api.pexels.com/v1/search", params=params, headers={"Authorization": key})
    r.raise_for_status()
    out = []
    for p in r.json().get("photos", []):
        slug = p.get("url", "").rstrip("/").rsplit("/", 1)[-1].replace("-", " ")
        out.append(Candidate(
            url=p["src"]["original"] + "?auto=compress&w=2160",
            page_url=p["url"], text=f"{p.get('alt', '')} {slug}",
            width=p["width"], height=p["height"], source="Pexels", license="Pexels License",
            attribution=f"Photo by {p.get('photographer', 'unknown')} on Pexels",
        ))
    return out


def pexels_videos(http: httpx.Client, query: str, orientation: str | None) -> list[Candidate]:
    key = os.getenv("PEXELS_API_KEY")
    if not key:
        return []
    params = {"query": query, "per_page": 15}
    if orientation:
        params["orientation"] = orientation
    r = http.get("https://api.pexels.com/videos/search", params=params, headers={"Authorization": key})
    r.raise_for_status()
    out = []
    for v in r.json().get("videos", []):
        files = [f for f in v.get("video_files", []) if f.get("file_type") == "video/mp4" and f.get("width")]
        # biggest file that is still <= 1920 on the long edge keeps memory use sane on 8 GB
        files = [f for f in files if max(f["width"], f["height"]) <= 1920] or files
        if not files:
            continue
        best = max(files, key=lambda f: f["width"] * f["height"])
        slug = v.get("url", "").rstrip("/").rsplit("/", 1)[-1].replace("-", " ")
        tags = " ".join(v.get("tags", []) or [])
        out.append(Candidate(
            url=best["link"], page_url=v["url"], text=f"{slug} {tags}",
            width=best["width"], height=best["height"], source="Pexels", license="Pexels License",
            attribution=f"Video by {v.get('user', {}).get('name', 'unknown')} on Pexels",
            ext="mp4", duration_s=float(v.get("duration") or 0),
        ))
    return out


def unsplash_photos(http: httpx.Client, query: str, orientation: str | None) -> list[Candidate]:
    key = os.getenv("UNSPLASH_ACCESS_KEY")
    if not key:
        return []
    params = {"query": query, "per_page": 15}
    if orientation:
        params["orientation"] = "squarish" if orientation == "square" else orientation
    r = http.get(
        "https://api.unsplash.com/search/photos", params=params,
        headers={"Authorization": f"Client-ID {key}", "Accept-Version": "v1"},
    )
    r.raise_for_status()
    out = []
    for p in r.json().get("results", []):
        tags = " ".join(t.get("title", "") for t in p.get("tags", []) or [])
        user = p.get("user", {})
        out.append(Candidate(
            url=p["urls"]["raw"] + "&w=2160&fm=jpg&q=85",
            page_url=p["links"]["html"],
            text=f"{p.get('alt_description') or ''} {p.get('description') or ''} {tags}",
            width=p["width"], height=p["height"], source="Unsplash", license="Unsplash License",
            attribution=f"Photo by {user.get('name', 'unknown')} on Unsplash",
            download_ping=p["links"].get("download_location"),
        ))
    return out


PIXABAY_ORIENT = {"portrait": "vertical", "landscape": "horizontal", "square": "all"}


def pixabay_photos(http: httpx.Client, query: str, orientation: str | None) -> list[Candidate]:
    key = os.getenv("PIXABAY_API_KEY")
    if not key:
        return []
    r = http.get("https://pixabay.com/api/", params={
        "key": key, "q": query[:100], "image_type": "photo", "per_page": 20, "safesearch": "true",
        "orientation": PIXABAY_ORIENT.get(orientation or "", "all"),
    })
    r.raise_for_status()
    out = []
    for h in r.json().get("hits", []):
        if h.get("isAiGenerated") or h.get("isLowQuality"):
            continue  # no AI-made pictures in factual videos
        w, ht = h.get("imageWidth", 0), h.get("imageHeight", 0)
        scale = min(1.0, 1280 / max(w, ht, 1))  # largeImageURL is capped at 1280 px on the long edge
        out.append(Candidate(
            url=h["largeImageURL"], page_url=h["pageURL"], text=h.get("tags", "").replace(",", " "),
            width=int(w * scale), height=int(ht * scale), source="Pixabay", license="Pixabay Content License",
            attribution=f"Image by {h.get('user', 'unknown')} from Pixabay",
        ))
    return out


def pixabay_videos(http: httpx.Client, query: str, orientation: str | None) -> list[Candidate]:
    key = os.getenv("PIXABAY_API_KEY")
    if not key:
        return []
    r = http.get("https://pixabay.com/api/videos/", params={
        "key": key, "q": query[:100], "video_type": "film", "per_page": 20, "safesearch": "true",
    })
    r.raise_for_status()
    out = []
    for h in r.json().get("hits", []):
        if h.get("isAiGenerated"):
            continue
        files = [f for f in (h.get("videos") or {}).values() if f.get("url") and f.get("width")]
        small_enough = [f for f in files if max(f["width"], f["height"]) <= 1920] or files
        if not small_enough:
            continue
        best = max(small_enough, key=lambda f: f["width"] * f["height"])
        out.append(Candidate(
            url=best["url"], page_url=h["pageURL"], text=h.get("tags", "").replace(",", " "),
            width=best["width"], height=best["height"], source="Pixabay", license="Pixabay Content License",
            attribution=f"Video by {h.get('user', 'unknown')} from Pixabay", ext="mp4",
            duration_s=float(h.get("duration") or 0),
        ))
    return out


def _strip_html(s: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", s or "")).strip()


def wikimedia_photos(http: httpx.Client, query: str, orientation: str | None) -> list[Candidate]:
    r = http.get(
        "https://commons.wikimedia.org/w/api.php",
        params={
            "action": "query", "format": "json", "generator": "search", "gsrsearch": f"{query} filetype:bitmap",
            "gsrnamespace": 6, "gsrlimit": 15, "prop": "imageinfo",
            "iiprop": "url|size|extmetadata|mime", "iiurlwidth": 2160,
        },
        headers={"User-Agent": USER_AGENT},
    )
    r.raise_for_status()
    out = []
    for page in (r.json().get("query", {}).get("pages", {}) or {}).values():
        info = (page.get("imageinfo") or [{}])[0]
        if info.get("mime") not in ("image/jpeg", "image/png"):
            continue
        meta = info.get("extmetadata", {})
        lic = _strip_html(meta.get("LicenseShortName", {}).get("value", ""))
        if not lic:
            continue  # unknown rights: skip
        artist = _strip_html(meta.get("Artist", {}).get("value", "")) or "unknown"
        title = page.get("title", "").removeprefix("File:").rsplit(".", 1)[0]
        desc = _strip_html(meta.get("ImageDescription", {}).get("value", ""))
        out.append(Candidate(
            url=info.get("thumburl") or info["url"], page_url=info.get("descriptionurl", ""),
            text=f"{title} {desc}", width=info.get("thumbwidth") or info["width"],
            height=info.get("thumbheight") or info["height"], source="Wikimedia Commons",
            license=lic, attribution=f"{artist}, {lic}, via Wikimedia Commons",
            ext="png" if info.get("mime") == "image/png" else "jpg",
        ))
    return out


# Unsplash last: its free tier allows 50 requests an hour, Pixabay 100 a minute
PHOTO_ORDER = {
    "stock": [pexels_photos, pixabay_photos, unsplash_photos],
    "wikimedia": [wikimedia_photos, pexels_photos, pixabay_photos, unsplash_photos],
}
VIDEO_ORDER = [pexels_videos, pixabay_videos]
STOCK_KEYS = ("PEXELS_API_KEY", "PIXABAY_API_KEY", "UNSPLASH_ACCESS_KEY")


def _redact(msg: str) -> str:
    """Pixabay takes its key in the URL; keep it out of logs and the Studio UI."""
    return re.sub(r"(key=)[^&\s']+", r"\1***", str(msg))


def best_candidate(
    http: httpx.Client, providers, query: str, orientation: str | None, min_duration: float = 0, log=print,
) -> tuple[Candidate, float] | None:
    for provider in providers:
        try:
            cands = provider(http, query, orientation)
        except httpx.HTTPError as e:
            log(f"  {provider.__name__}: {_redact(e)}")
            continue
        if min_duration:
            cands = [c for c in cands if (c.duration_s or 0) >= min_duration] or cands
        scored = sorted(((score(c, query, orientation), c) for c in cands), key=lambda x: -x[0])
        if scored and scored[0][0] >= RELEVANCE_MIN:
            return scored[0][1], scored[0][0]
    return None


def download(http: httpx.Client, c: Candidate, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    with http.stream("GET", c.url, headers={"User-Agent": USER_AGENT}, follow_redirects=True) as r:
        r.raise_for_status()
        with tmp.open("wb") as fh:
            for chunk in r.iter_bytes(1 << 16):
                fh.write(chunk)
    tmp.replace(dest)
    if c.download_ping:
        try:
            http.get(c.download_ping, headers={"Authorization": f"Client-ID {os.getenv('UNSPLASH_ACCESS_KEY', '')}"})
        except httpx.HTTPError:
            pass


# ---------------------------------------------------------------- charts

def render_chart(project: Path, scene: Scene, brand_name: str) -> str:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    brand = json.loads(BRAND_FILE.read_text())[brand_name]
    col = brand["colors"]
    p = scene.visual.params
    labels, values = p.get("labels", []), p.get("values", [])
    if not labels or len(labels) != len(values):
        raise ValueError(f"scene {scene.id}: chart params need matching labels and values")
    kind = p.get("kind", "bar")
    portrait = (scene.visual.orientation or "portrait") == "portrait"
    fig, ax = plt.subplots(figsize=(10.8, 19.2) if portrait else (19.2, 10.8), dpi=100)
    fig.patch.set_facecolor(col["background"])
    ax.set_facecolor(col["background"])
    fs = 34 if portrait else 28
    if kind == "line":
        ax.plot(labels, values, color=col["accent"], linewidth=8, marker="o", markersize=18)
    elif kind == "pie":
        ax.pie(values, labels=labels, textprops={"color": col["text"], "fontsize": fs},
               colors=[col["accent"], "#7C8CF8", "#4FD1C5", "#F687B3", "#A0AEC0", "#F6AD55"][: len(values)])
    else:
        bars = ax.bar(labels, values, color=col["accent"])
        ax.bar_label(bars, labels=[f"{v:g}{p.get('unit') or ''}" for v in values], color=col["text"],
                     fontsize=fs, padding=8)
    if kind != "pie":
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)
        for side in ("left", "bottom"):
            ax.spines[side].set_color(col["text"])
        ax.tick_params(colors=col["text"], labelsize=fs)
        if portrait:
            plt.setp(ax.get_xticklabels(), rotation=30, ha="right")
    if p.get("title"):
        ax.set_title(p["title"], color=col["text"], fontsize=fs + 12, pad=30, weight="bold")
    # keep clear of the Reels UI (top 250 px) and of the caption band that starts ~1190 px down
    if portrait:
        fig.subplots_adjust(left=0.16, right=0.9, top=1 - 330 / 1920, bottom=1 - 1040 / 1920)
    else:
        fig.tight_layout(pad=3)
    rel = chart_path(scene.id)
    (project / rel).parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(project / rel, facecolor=fig.get_facecolor())
    plt.close(fig)
    return rel


# ---------------------------------------------------------------- main

def _est_duration(scene: Scene) -> float:
    return max(len(scene.text.split()) / 2.5, 2.0)  # 150 wpm


def _downgrade(scene: Scene, reason: str, sf=None) -> str:
    """Nothing usable was found. Make an animation from the scene's own words, or ask for a file if the scene says so.

    Returns "animated" or "manual".
    """
    v = scene.visual
    if v.on_missing == "manual":
        v.downgraded_from = v.type
        v.type = "manual"
        v.prompt = v.prompt or f"{reason}. Wanted: {v.query or scene.text}"
        v.fallback = v.fallback or "text_card"
        return "manual"
    animation.to_animation(scene, "auto", sf)
    return "animated"


def fetch_scene(
    project: Path, sf: ScenesFile, scene: Scene, http: httpx.Client, force: bool = False,
    downgrade: bool = True, log=print,
) -> str:
    """Fetch one scene's visual. Returns a status word for the summary."""
    v = scene.visual
    state_file = project / "build" / "cache" / "fetch.json"
    state = json.loads(state_file.read_text()) if state_file.exists() else {}
    digest = cache.hash_inputs(v.model_dump(exclude={"file"}), scene.text)

    if v.type == "chart":
        if not force and state.get(str(scene.id)) == digest and (project / chart_path(scene.id)).exists():
            return "cached"
        render_chart(project, scene, sf.brand)
        status = "chart"
    elif v.type in ("photo", "video"):
        existing = find_asset(project, scene)
        if not force and existing and (state.get(str(scene.id)) == digest or str(scene.id) not in state):
            return "cached" if str(scene.id) in state else "kept"  # hand-placed files are never overwritten
        if not v.query:
            return _downgrade(scene, "No search query", sf)
        if v.type == "video":
            providers = VIDEO_ORDER
        else:
            providers = PHOTO_ORDER[v.source or "stock"]
        found = best_candidate(http, providers, v.query, v.orientation, _est_duration(scene) if v.type == "video" else 0, log)
        if not found and not downgrade:
            log(f"scene {scene.id}: nothing relevant for {v.query!r}; kept the current asset")
            return "nomatch"
        if not found:
            outcome = _downgrade(scene, "Auto-fetch found nothing relevant", sf)
            log(f"scene {scene.id}: nothing relevant for {v.query!r}; "
                + ("made an animation instead: " + animation.describe(scene) if outcome == "animated"
                   else "moved to the manual inbox"))
            return outcome
        cand, s = found
        remove_scene_assets(project, scene.id)
        rel = video_path(scene.id) if v.type == "video" else image_path(scene.id, cand.ext)
        download(http, cand, project / rel)
        v.file = rel
        upsert_credit(project, Credit(
            scene_id=scene.id, source=cand.source, license=cand.license, url=cand.page_url,
            attribution_text=cand.attribution, added_by="fetch",
        ))
        log(f"scene {scene.id}: {cand.source} (relevance {s:.2f}) -> {rel}")
        status = "fetched"
    else:
        return "skip"

    state[str(scene.id)] = cache.hash_inputs(v.model_dump(exclude={"file"}), scene.text)
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(json.dumps(state, indent=2))
    return status


def fetch(
    project: Path, only: list[int] | None = None, force: bool = False,
    http: httpx.Client | None = None, downgrade: bool = True, log=print,
) -> dict[str, int]:
    scenes_path = project / "script" / "scenes.json"
    sf = load_scenes(scenes_path)
    if not any(os.getenv(k) for k in STOCK_KEYS):
        log("warning: no PEXELS_API_KEY, PIXABAY_API_KEY or UNSPLASH_ACCESS_KEY in .env; "
            "only Wikimedia and charts will work")
    own = http is None
    http = http or httpx.Client(timeout=30)
    summary: dict[str, int] = {}
    try:
        for scene in sf.scenes:
            if only and scene.id not in only:
                continue
            check_cancel()
            try:
                status = fetch_scene(project, sf, scene, http, force, downgrade, log)
            except (httpx.HTTPError, ValueError) as e:
                log(f"scene {scene.id}: error: {_redact(e)}")
                status = "error"
            summary[status] = summary.get(status, 0) + 1
    finally:
        if own:
            http.close()
    dump_json(sf, scenes_path)
    pending = manual_inbox.write_readme(project, sf)
    if pending:
        log(f"{len(pending)} scene(s) need a manual asset; see {project / 'inbox' / 'README.txt'}")
    return summary
