"""Reading source links: YouTube captions, Jina fallback for empty pages, re-reading old thin files, warnings."""
import sys
import types

import httpx

from scripts import generate_script as G
from scripts.lib import sources as S
from scripts.lib.state import project_state, thin_sources

ARTICLE = "<html><body><article>" + "<p>" + " ".join(["The monsoon reached Kerala late this year."] * 20) + "</p></article></body></html>"
MENU = "<html><body><nav>News Videos Matches</nav><div id=app></div></body></html>"


def transport(calls, page=MENU, jina="Rendered text " + "word " * 120):
    def handler(req):
        calls.append(str(req.url))
        if req.url.host == "r.jina.ai":
            return httpx.Response(200, text=jina)
        if req.url.host == "captions.example":
            return httpx.Response(200, json={"events": [{"segs": [{"utf8": "Jatin Sapru "}, {"utf8": "commentary"}]},
                                                        {"segs": [{"utf8": "Jatin Sapru commentary"}]},
                                                        {"segs": [{"utf8": "RCB jeet gayi"}]}]})
        return httpx.Response(200, text=page)
    return httpx.Client(transport=httpx.MockTransport(handler))


def fake_ytdlp(monkeypatch, info):
    class YDL:
        def __init__(self, opts): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def extract_info(self, url, download=False): return info
    monkeypatch.setitem(sys.modules, "yt_dlp", types.SimpleNamespace(YoutubeDL=YDL))


def test_youtube_short_reads_title_and_original_language_captions(monkeypatch):
    fake_ytdlp(monkeypatch, {"title": "IPL Final 2026", "channel": "SJ", "upload_date": "20260531", "description": "",
                             "subtitles": {}, "automatic_captions": {
                                 "en": [{"ext": "json3", "url": "https://captions.example/en"}],
                                 "hi-orig": [{"ext": "json3", "url": "https://captions.example/hi"}]}})
    calls = []
    text, via = S.fetch_source("https://www.youtube.com/shorts/qkP1jZVdkIM", transport(calls), G._extract, log=lambda *_: None)
    assert via == "youtube" and "TITLE: IPL Final 2026" in text and "PUBLISHED: 2026-05-31" in text
    assert "auto-captions, hi-orig" in text, "the video's own language beats a machine translation"
    assert "Jatin Sapru commentary RCB jeet gayi" in text, "repeated caption lines are dropped"
    assert calls == ["https://captions.example/hi"]


def test_thin_page_falls_back_to_jina_and_a_good_page_does_not(monkeypatch):
    calls = []
    text, via = S.fetch_source("https://www.iplt20.com/videos/final", transport(calls), G._extract, log=lambda *_: None)
    assert via == "jina" and "Rendered text" in text and any("r.jina.ai" in c for c in calls)
    calls = []
    text, via = S.fetch_source("https://news.example/monsoon", transport(calls, page=ARTICLE), G._extract, log=lambda *_: None)
    assert via == "page" and "Kerala" in text and not any("r.jina.ai" in c for c in calls)
    monkeypatch.setenv("JINA_READER", "0")
    calls = []
    S.fetch_source("https://www.iplt20.com/videos/final", transport(calls), G._extract, log=lambda *_: None)
    assert not any("r.jina.ai" in c for c in calls), "JINA_READER=0 keeps URLs away from Jina"


def test_old_thin_downloads_are_read_again_and_marked(project_factory):
    proj = project_factory([{"id": 1, "text": "x", "visual": {"type": "text_card"}}])
    url = "https://www.iplt20.com/videos/final"
    G.load_articles(proj, [url], http=transport([]), log=lambda *_: None)
    saved = next((proj / "input/articles").glob("_url_*"))
    saved.write_text(f"SOURCE: {url}\n\nNews\nVideos\nMatches")  # what the old code saved
    calls = []
    arts = G.load_articles(proj, [url], http=transport(calls), log=lambda *_: None)
    assert "Rendered text" in arts[0]["text"] and saved.read_text().startswith(f"SOURCE: {url}\nVIA: jina")
    calls.clear()
    G.load_articles(proj, [url], http=transport(calls), log=lambda *_: None)
    assert calls == [], "a source read with the new code is not fetched again"


def test_studio_warns_when_every_link_is_thin(project_factory):
    proj = project_factory([{"id": 1, "text": "x", "visual": {"type": "text_card"}}])
    (proj / "input/brief.md").write_text("- topic: IPL final\n")
    (proj / "input/articles/_url_abc.txt").write_text("SOURCE: https://x.example/a\nVIA: page\n\nAbout Press Copyright")
    usable, warn = thin_sources(proj)
    assert usable == 0 and "https://x.example/a gave only 3 words" in warn[0]
    brief = next(s for s in project_state(proj) if s.key == "brief")
    assert brief.status == "todo" and any("gave only 3 words" in t for t in brief.todos)
    (proj / "input/articles/pasted_1.txt").write_text("IMD said the monsoon was late.")
    assert next(s for s in project_state(proj) if s.key == "brief").status == "done", "your own short note counts"
