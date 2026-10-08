"""fetch_assets against a mocked network: nothing here touches the internet."""
import json

import httpx

from scripts import fetch_assets as F
from scripts.lib.schema import load_scenes

JPEG = b"\xff\xd8\xff\xe0fakejpeg"


def pexels_photo(alt, url_slug, w=2000, h=3000):
    return {"alt": alt, "url": f"https://www.pexels.com/photo/{url_slug}-1/", "width": w, "height": h,
            "photographer": "Asha", "src": {"original": f"https://images.pexels.com/{url_slug}.jpeg"}}


def make_transport(pexels=(), unsplash=(), wikimedia=None, calls=None, pixabay=(), pixabay_videos=(), pixabay_status=200):
    calls = calls if calls is not None else []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(str(req.url))
        host = req.url.host
        if host == "api.pexels.com" and req.url.path == "/v1/search":
            return httpx.Response(200, json={"photos": list(pexels)})
        if host == "api.pexels.com" and req.url.path == "/videos/search":
            return httpx.Response(200, json={"videos": []})
        if host == "api.unsplash.com" and req.url.path == "/search/photos":
            return httpx.Response(200, json={"results": list(unsplash)})
        if host == "pixabay.com" and req.url.path == "/api/":
            return httpx.Response(pixabay_status, json={"hits": list(pixabay)})
        if host == "pixabay.com" and req.url.path == "/api/videos/":
            return httpx.Response(pixabay_status, json={"hits": list(pixabay_videos)})
        if host == "commons.wikimedia.org":
            return httpx.Response(200, json=wikimedia or {})
        if host in ("images.pexels.com", "images.unsplash.com", "upload.wikimedia.org", "cdn.pixabay.com"):
            return httpx.Response(200, content=JPEG)
        if host == "api.unsplash.com" and "download" in req.url.path:
            return httpx.Response(200, json={})
        return httpx.Response(404)

    return httpx.Client(transport=httpx.MockTransport(handler)), calls


def photo_scene(i, query, **extra):
    return {"id": i, "text": f"scene {i} words here", "visual": {"type": "photo", "query": query,
            "orientation": "portrait", **extra}}


def test_relevance_scoring():
    assert F.relevance("voters queue polling booth", "Voters standing in a queue at a polling booth") == 1.0
    assert F.relevance("voters queue polling booth", "a cat on a sofa") == 0.0


def test_pexels_hit_downloads_and_credits(project_factory):
    proj = project_factory([photo_scene(1, "voters queue polling booth")])
    http, _ = make_transport(pexels=[pexels_photo("Voters in a queue at a polling booth", "voters-queue")])
    summary = F.fetch(proj, http=http, log=lambda *_: None)
    assert summary == {"fetched": 1}
    assert (proj / "assets/images/scene_01.jpg").read_bytes() == JPEG
    credits = json.loads((proj / "assets/credits.json").read_text())
    assert credits[0]["source"] == "Pexels" and credits[0]["added_by"] == "fetch"
    assert load_scenes(proj / "script/scenes.json").scenes[0].visual.file == "assets/images/scene_01.jpg"


def test_low_relevance_falls_through_to_unsplash(project_factory):
    proj = project_factory([photo_scene(1, "cricket stadium crowd night")])
    unsplash = [{"alt_description": "stadium crowd at night cricket match", "description": None, "tags": [],
                 "width": 3000, "height": 4000, "user": {"name": "Ravi"},
                 "urls": {"raw": "https://images.unsplash.com/photo-1?ixid=x"},
                 "links": {"html": "https://unsplash.com/photos/1",
                           "download_location": "https://api.unsplash.com/photos/1/download"}}]
    http, calls = make_transport(pexels=[pexels_photo("a bowl of fruit", "fruit")], unsplash=unsplash)
    F.fetch(proj, http=http, log=lambda *_: None)
    credits = json.loads((proj / "assets/credits.json").read_text())
    assert credits[0]["source"] == "Unsplash"
    assert any("/photos/1/download" in c for c in calls), "Unsplash download endpoint must be pinged"


def test_nothing_relevant_becomes_an_animation(project_factory):
    proj = project_factory([photo_scene(1, "finance minister budget speech")])
    http, _ = make_transport(pexels=[pexels_photo("a bowl of fruit", "fruit")])
    lines = []
    summary = F.fetch(proj, http=http, log=lines.append)
    assert summary == {"animated": 1}
    v = load_scenes(proj / "script/scenes.json").scenes[0].visual
    assert v.type == "animation" and v.downgraded_from == "photo" and v.query == "finance minister budget speech"
    assert v.params["headline"] and v.params["style"] in ("kinetic", "burst", "rings") and "no figures and no motion" in v.params["why"]
    assert any("made an animation instead" in l for l in lines)
    assert "No manual scenes pending" in (proj / "inbox/README.txt").read_text()
    assert F.fetch(proj, http=http, log=lambda *_: None) == {"skip": 1}, "an animation is not searched for again"


def test_scene_that_asks_for_a_file_goes_to_the_manual_inbox(project_factory):
    proj = project_factory([photo_scene(1, "finance minister budget speech", on_missing="manual")])
    http, _ = make_transport(pexels=[pexels_photo("a bowl of fruit", "fruit")])
    assert F.fetch(proj, http=http, log=lambda *_: None) == {"manual": 1}
    v = load_scenes(proj / "script/scenes.json").scenes[0].visual
    assert v.type == "manual" and v.downgraded_from == "photo" and v.fallback == "text_card"
    readme = (proj / "inbox/README.txt").read_text()
    assert "scene01" in readme and "finance minister budget speech" in readme


def test_hand_placed_image_is_never_overwritten(project_factory):
    proj = project_factory([photo_scene(1, "voters queue polling booth")])
    (proj / "assets/images/scene_01.jpg").write_bytes(b"mine")
    http, calls = make_transport(pexels=[pexels_photo("Voters in a queue at a polling booth", "v")])
    assert F.fetch(proj, http=http, log=lambda *_: None) == {"kept": 1}
    assert (proj / "assets/images/scene_01.jpg").read_bytes() == b"mine"
    assert not calls


def test_second_fetch_is_cached(project_factory):
    proj = project_factory([photo_scene(1, "voters queue polling booth")])
    http, calls = make_transport(pexels=[pexels_photo("Voters in a queue at a polling booth", "v")])
    F.fetch(proj, http=http, log=lambda *_: None)
    n = len(calls)
    assert F.fetch(proj, http=http, log=lambda *_: None) == {"cached": 1}
    assert len(calls) == n


def test_wikimedia_first_when_requested(project_factory):
    proj = project_factory([photo_scene(1, "india gate new delhi", source="wikimedia")])
    wiki = {"query": {"pages": {"1": {"title": "File:India Gate in New Delhi.jpg", "imageinfo": [{
        "mime": "image/jpeg", "url": "https://upload.wikimedia.org/a.jpg",
        "thumburl": "https://upload.wikimedia.org/thumb/a.jpg", "thumbwidth": 1440, "thumbheight": 2160,
        "width": 3000, "height": 4500, "descriptionurl": "https://commons.wikimedia.org/wiki/File:India_Gate.jpg",
        "extmetadata": {"LicenseShortName": {"value": "CC BY-SA 4.0"}, "Artist": {"value": "<a>Jane</a>"}},
    }]}}}}
    http, calls = make_transport(wikimedia=wiki)
    F.fetch(proj, http=http, log=lambda *_: None)
    credits = json.loads((proj / "assets/credits.json").read_text())
    assert credits[0]["source"] == "Wikimedia Commons"
    assert credits[0]["attribution_text"] == "Jane, CC BY-SA 4.0, via Wikimedia Commons"
    assert "commons.wikimedia.org" in calls[0]


def test_chart_rendered_without_network(project_factory):
    proj = project_factory([{"id": 1, "text": "turnout rose", "visual": {"type": "chart", "orientation": "portrait",
                            "params": {"kind": "bar", "title": "Turnout", "unit": "%",
                                       "labels": ["2019", "2024"], "values": [68, 76]}}}])
    http, calls = make_transport()
    assert F.fetch(proj, http=http, log=lambda *_: None) == {"chart": 1}
    assert (proj / "assets/images/scene_01_chart.png").stat().st_size > 1000
    assert not calls


def pixabay_hit(tags, ai=False, w=3000, h=4000):
    return {"tags": tags, "isAiGenerated": ai, "isLowQuality": False, "imageWidth": w, "imageHeight": h,
            "largeImageURL": f"https://cdn.pixabay.com/photo/{tags.split(',')[0]}.jpg",
            "pageURL": "https://pixabay.com/photos/x-1/", "user": "Meena"}


def test_pixabay_used_before_unsplash_and_skips_ai_images(project_factory):
    proj = project_factory([photo_scene(1, "monsoon rain india")])
    unsplash = [{"alt_description": "monsoon rain india", "width": 3000, "height": 4000, "user": {"name": "U"},
                 "urls": {"raw": "https://images.unsplash.com/u?x"}, "links": {"html": "https://unsplash.com/u",
                 "download_location": "https://api.unsplash.com/photos/u/download"}}]
    pixabay = [pixabay_hit("monsoon, rain, india, clouds", ai=True), pixabay_hit("monsoon, rain, india, street")]
    http, calls = make_transport(pexels=[pexels_photo("a bowl of fruit", "fruit")], pixabay=pixabay, unsplash=unsplash)
    F.fetch(proj, http=http, log=lambda *_: None)
    credit = json.loads((proj / "assets/credits.json").read_text())[0]
    assert credit["source"] == "Pixabay" and credit["attribution_text"] == "Image by Meena from Pixabay"
    assert not any("api.unsplash.com/search" in c for c in calls), "Unsplash quota is saved when Pixabay matches"
    assert any("monsoon/" not in c and "cdn.pixabay.com/photo/monsoon.jpg" in c for c in calls)


def test_only_ai_images_means_no_match(project_factory):
    proj = project_factory([photo_scene(1, "monsoon rain india")])
    http, _ = make_transport(pixabay=[pixabay_hit("monsoon, rain, india", ai=True)])
    assert F.fetch(proj, http=http, log=lambda *_: None) == {"animated": 1}


def test_pixabay_video(project_factory):
    proj = project_factory([{"id": 1, "text": "rain on a street at night here", "visual": {
        "type": "video", "query": "rain street night", "orientation": "landscape"}}])
    vid = {"tags": "rain, street, night", "duration": 20, "pageURL": "https://pixabay.com/videos/r-1/", "user": "Ravi",
           "videos": {"large": {"url": "https://cdn.pixabay.com/video/large.mp4", "width": 3840, "height": 2160},
                      "medium": {"url": "https://cdn.pixabay.com/video/medium.mp4", "width": 1920, "height": 1080}}}
    http, calls = make_transport(pixabay_videos=[vid])
    assert F.fetch(proj, http=http, log=lambda *_: None) == {"fetched": 1}
    assert any(c.endswith("medium.mp4") for c in calls), "4K is skipped to keep memory sane on 8 GB"
    assert (proj / "assets/videos/scene_01.mp4").exists()


def test_api_key_never_reaches_the_log(project_factory):
    proj = project_factory([photo_scene(1, "monsoon rain india")])
    http, _ = make_transport(pixabay_status=500)
    lines = []
    F.fetch(proj, http=http, log=lines.append)
    joined = "\n".join(lines)
    assert "pixabay" in joined.lower() and "test-pixabay-secret" not in joined and "key=***" in joined
