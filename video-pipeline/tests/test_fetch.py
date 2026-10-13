"""fetch_assets against a mocked network: nothing here touches the internet."""
import json

import httpx

from scripts import fetch_assets as F
from scripts.lib.schema import load_scenes

JPEG = b"\xff\xd8\xff\xe0fakejpeg"


def pexels_photo(alt, url_slug, w=2000, h=3000):
    return {"alt": alt, "url": f"https://www.pexels.com/photo/{url_slug}-1/", "width": w, "height": h,
            "photographer": "Asha", "src": {"original": f"https://images.pexels.com/{url_slug}.jpeg"}}


def make_transport(pexels=(), unsplash=(), wikimedia=None, calls=None, pixabay=(), pixabay_videos=(), pixabay_status=200, coverr=(), openverse=(), nasa=None, archive=None):
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
        if host == "api.coverr.co" and req.url.path == "/videos":
            assert req.headers["authorization"] == "Bearer test-coverr-secret"
            return httpx.Response(200, json={"hits": list(coverr)})
        if host == "api.openverse.org" and req.url.path == "/v1/images/":
            return httpx.Response(200, json={"results": list(openverse)})
        if host == "images-api.nasa.gov" and nasa:
            return httpx.Response(200, json={"collection": {"items": nasa["items"]}})
        if host == "images-assets.nasa.gov" and req.url.path.endswith("collection.json"):
            return httpx.Response(200, json=nasa["manifest"])
        if host == "images-assets.nasa.gov":
            return httpx.Response(200, content=JPEG)
        if host == "archive.org" and req.url.path == "/advancedsearch.php" and archive:
            return httpx.Response(200, json={"response": {"docs": archive["docs"]}})
        if host == "archive.org" and req.url.path.startswith("/metadata/") and archive:
            return httpx.Response(200, json={"files": archive["files"]})
        if host == "archive.org" and req.url.path.startswith("/download/"):
            return httpx.Response(200, content=JPEG)
        if host in ("live.staticflickr.com", "cdn.coverr.co"):
            return httpx.Response(200, content=JPEG)
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


def coverr_hit(title, tags, ai=False):
    slug = title.lower().replace(" ", "-")
    return {"title": title, "description": "", "tags": tags, "duration": "10.5", "max_width": 1920, "max_height": 1080,
            "is_vertical": False, "is_ai_generated": ai, "base_filename": f"coverr-{slug}",
            "urls": {"mp4": f"https://cdn.coverr.co/videos/coverr-{slug}/1080p.mp4"}}


def test_coverr_video_used_before_pixabay_and_skips_ai_clips(project_factory):
    proj = project_factory([{"id": 1, "text": "rain on a street at night here", "visual": {
        "type": "video", "query": "rain street night", "orientation": "landscape"}}])
    coverr = [coverr_hit("AI rain street night", ["rain", "street", "night"], ai=True),
              coverr_hit("Rain on a street at night", ["rain", "street", "night"])]
    http, calls = make_transport(coverr=coverr)
    assert F.fetch(proj, http=http, log=lambda *_: None) == {"fetched": 1}
    assert any(c.endswith("rain-on-a-street-at-night/1080p.mp4") for c in calls)
    assert not any("ai-rain" in c for c in calls) and not any("pixabay.com/api/videos" in c for c in calls)
    credit = json.loads((proj / "assets/credits.json").read_text())[0]
    assert credit["source"] == "Coverr" and (proj / "assets/videos/scene_01.mp4").exists()


def test_api_key_never_reaches_the_log(project_factory):
    proj = project_factory([photo_scene(1, "monsoon rain india")])
    http, _ = make_transport(pixabay_status=500)
    lines = []
    F.fetch(proj, http=http, log=lines.append)
    joined = "\n".join(lines)
    assert "pixabay" in joined.lower() and "test-pixabay-secret" not in joined and "key=***" in joined


def test_openverse_keyless_fallback_keeps_licence_and_skips_noncommercial(project_factory):
    proj = project_factory([photo_scene(1, "farmers working paddy field", orientation="landscape")])
    hit = {"title": "Farmers working paddy field", "url": "https://live.staticflickr.com/1/a.jpg",
           "foreign_landing_url": "https://www.flickr.com/photos/1/a", "creator": "Neo", "license": "by",
           "license_version": "2.0", "width": 2400, "height": 1600, "source": "flickr", "filetype": "jpg",
           "tags": [{"name": "farmers"}, {"name": "paddy"}]}
    nc = dict(hit, title="Farmers working paddy field NC", license="by-nc", url="https://live.staticflickr.com/1/nc.jpg")
    http, calls = make_transport(openverse=[nc, hit])
    assert F.fetch(proj, http=http, log=lambda *_: None) == {"fetched": 1}
    credit = json.loads((proj / "assets/credits.json").read_text())[0]
    assert credit["source"] == "Openverse" and "CC BY 2.0" in credit["attribution_text"] and "Neo" in credit["attribution_text"]
    assert not any(c.endswith("nc.jpg") for c in calls)


def _nasa(kind, nid, title, files):
    items = [{"href": f"https://images-assets.nasa.gov/{kind}/{nid}/collection.json",
              "data": [{"title": title, "description": "", "keywords": title.split(), "nasa_id": nid,
                        "photographer": "Bill"}]}]
    return {"items": items, "manifest": files}


def test_nasa_photo_picks_orig_and_credits_nasa(project_factory):
    proj = project_factory([photo_scene(1, "apollo moon landing", orientation="landscape")])
    base = "http://images-assets.nasa.gov/image/a11/a11"
    nasa = _nasa("image", "a11", "Apollo moon landing", [f"{base}~thumb.jpg", f"{base}~large.jpg", f"{base}~orig.jpg"])
    http, calls = make_transport(nasa=nasa)
    assert F.fetch(proj, http=http, log=lambda *_: None) == {"fetched": 1}
    assert any(c == "https://images-assets.nasa.gov/image/a11/a11~orig.jpg" for c in calls), "https, full resolution"
    credit = json.loads((proj / "assets/credits.json").read_text())[0]
    assert credit["source"] == "NASA" and "NASA/Bill" in credit["attribution_text"]


def test_nasa_video_uses_large_mp4(project_factory):
    proj = project_factory([{"id": 1, "text": "a rocket launch lifts off here", "visual": {
        "type": "video", "query": "rocket launch", "orientation": "landscape"}}])
    base = "http://images-assets.nasa.gov/video/r1/r1"
    nasa = _nasa("video", "r1", "Rocket launch", [f"{base}~orig.mp4", f"{base}~large.mp4", f"{base}.vtt"])
    http, calls = make_transport(nasa=nasa)
    assert F.fetch(proj, http=http, log=lambda *_: None) == {"fetched": 1}
    assert any(c.endswith("r1~large.mp4") for c in calls) and not any(c.endswith("~orig.mp4") for c in calls)
    assert (proj / "assets/videos/scene_01.mp4").exists()


def test_internet_archive_video_skips_huge_files(project_factory):
    proj = project_factory([{"id": 1, "text": "old film of a steam train here", "visual": {
        "type": "video", "query": "steam train", "orientation": "landscape"}}])
    archive = {"docs": [{"identifier": "train-1", "title": "Steam train", "subject": ["steam", "train"],
                         "creator": "Railways"}],
               "files": [{"name": "big.mp4", "format": "h.264", "size": str(900 * 1024 * 1024), "width": "1920",
                          "height": "1080", "length": "600"},
                         {"name": "small file.mp4", "format": "h.264", "size": str(40 * 1024 * 1024), "width": "1280",
                          "height": "720", "length": "600"}]}
    http, calls = make_transport(archive=archive)
    assert F.fetch(proj, http=http, log=lambda *_: None) == {"fetched": 1}
    assert any(c.endswith("/train-1/small%20file.mp4") for c in calls) and not any(c.endswith("big.mp4") for c in calls)
    credit = json.loads((proj / "assets/credits.json").read_text())[0]
    assert credit["source"] == "Internet Archive"
    assert "licenseurl:*publicdomain*" in next(c for c in calls if "advancedsearch" in c).replace("%2A", "*").replace("%3A", ":")


def test_shape_words_do_not_count_as_search_words():
    assert F.relevance("crowd cheering stadium landscape", "crowd cheering stadium") == 1.0


def test_retry_missing_only_searches_scenes_that_found_nothing(project_factory):
    proj = project_factory([
        {"id": 1, "text": "old steam train", "visual": {"type": "manual", "downgraded_from": "video",
         "query": "steam train", "orientation": "landscape", "prompt": "Auto-fetch found nothing relevant. Wanted: x"}},
        {"id": 2, "text": "a crowd", "visual": {"type": "manual", "downgraded_from": "photo",
         "query": "zzz nothing", "prompt": "Auto-fetch found nothing relevant. Wanted: zzz nothing"}},
        {"id": 3, "text": "a screenshot", "visual": {"type": "manual", "prompt": "press release"}},
        photo_scene(4, "monsoon rain india"),
    ])
    (proj / "assets/images/scene_04.jpg").write_bytes(b"mine")
    assert [s.id for s in F.retryable(load_scenes(proj / "script/scenes.json"), proj)] == [1, 2]
    archive = {"docs": [{"identifier": "train-1", "title": "Steam train", "subject": ["steam", "train"]}],
               "files": [{"name": "t.mp4", "format": "h.264", "size": "1000", "width": "1280", "height": "720",
                          "length": "60"}]}
    http, calls = make_transport(archive=archive)
    assert F.retry_missing(proj, http=http, log=lambda *_: None) == {"fetched": 1, "still missing": 1}
    sf = load_scenes(proj / "script/scenes.json")
    one, two, three = sf.scenes[0].visual, sf.scenes[1].visual, sf.scenes[2].visual
    assert one.type == "video" and one.downgraded_from is None and one.prompt is None
    assert (proj / "assets/videos/scene_01.mp4").exists()
    assert two.type == "manual" and two.downgraded_from == "photo" and two.prompt.startswith("Auto-fetch")
    assert three.type == "manual" and three.prompt == "press release", "script-asked manual scenes are left alone"
    assert (proj / "assets/images/scene_04.jpg").read_bytes() == b"mine", "existing visuals are never touched"
    readme = (proj / "inbox/README.txt").read_text()
    assert "scene02" in readme and "scene01" not in readme
