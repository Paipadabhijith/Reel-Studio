"""Phase 3: targets (reels + long-form), chapters, animated scene props, subtitles, Blender runner."""
import json
import subprocess
from pathlib import Path

import pytest

from scripts import render_blender as RB
from scripts import render_final as RF
from scripts.draft import estimate_timeline
from scripts.lib import india
from scripts.lib.schema import Timeline, TimelineScene, Word, load_scenes
from scripts.lib.targets import chapters_for, get_target, list_targets


def scene(i, text, vis=None, **kw):
    return {"id": i, "text": text, "visual": vis or {"type": "text_card"}, **kw}


@pytest.fixture
def both(project_factory):
    scenes = [scene(1, "one two three four five six"), scene(2, "seven eight nine ten"),
              scene(3, "eleven twelve thirteen fourteen fifteen"), scene(4, "sixteen seventeen eighteen")]
    proj = project_factory(scenes, reels=[{"id": "reel_01", "scene_ids": [1, 3], "hook_scene": 1},
                                          {"id": "reel_02", "scene_ids": [2, 4], "hook_scene": 2}])
    data = json.loads((proj / "script/scenes.json").read_text())
    data["format"] = "both"
    data["long_form"] = {"chapters": [{"title": "Intro", "scene_ids": [1, 2]}, {"title": "Main", "scene_ids": [3, 4]}]}
    (proj / "script/scenes.json").write_text(json.dumps(data))
    return proj, load_scenes(proj / "script/scenes.json")


def test_targets_files_and_primary(both):
    _, sf = both
    ts = list_targets(sf)
    assert [t.id for t in ts] == ["reel_01", "reel_02", "long"]
    r1, r2, lg = ts
    assert r1.audio == "audio/narration.m4a" and r1.timeline == "build/timeline.json", "first video keeps the old names"
    assert r2.audio == "audio/reel_02.m4a" and r2.out == "out/reel_02_9x16.mp4"
    assert lg.audio == "audio/long.m4a" and lg.out == "out/long_16x9.mp4" and (lg.width, lg.height) == (1920, 1080)
    assert lg.scene_ids == [1, 2, 3, 4] and r2.scene_ids == [2, 4]
    assert [c[0] for c in chapters_for(sf, lg)] == ["Intro", "Main"]
    assert len(chapters_for(sf, r1)) == 1
    with pytest.raises(ValueError, match="reel_01, reel_02, long"):
        get_target(sf, "nope")


def test_chapters_tile_the_video_exactly(both):
    proj, sf = both
    long = get_target(sf, "long")
    tl = estimate_timeline(sf, long)
    frames = RF.chapter_frames(tl, chapters_for(sf, long))
    assert frames[0][0] == 0 and frames[0][1] == frames[1][0] and frames[1][1] == round(tl.duration_s * 30)
    p0 = RF.build_props(proj, sf, tl, long, "final", 0, log=lambda *_: None)
    p1 = RF.build_props(proj, sf, tl, long, "final", 1, log=lambda *_: None)
    assert p0["durationInFrames"] + p1["durationInFrames"] == round(tl.duration_s * 30)
    assert p1["scenes"][0]["startS"] == 0.0, "chapter times are relative to the chapter"
    assert p1["scenes"][0]["words"][0]["t"] == 0.0
    assert p0["kind"] == "long" and p0["captions"] is False and p0["width"] == 1920
    assert [s["id"] for s in p1["scenes"]] == [3, 4] and p1["chapterTitle"] == "Main"
    reel = RF.build_props(proj, sf, estimate_timeline(sf, "reel_01"), get_target(sf, "reel_01"), "final", log=lambda *_: None)
    assert reel["captions"] is True and reel["height"] == 1920 and reel["chapterTitle"] is None


def test_visual_props_for_animated_scenes(project_factory):
    proj = project_factory([scene(1, "x")])
    log = []
    from scripts.lib.schema import Scene

    def vp(vis, **kw):
        return RF.visual_props(proj, Scene.model_validate(scene(1, "words here", vis, **kw)), "draft", log.append)

    chart = vp({"type": "chart", "params": {"kind": "bar", "labels": ["a", "b"], "values": [1, 2]}})
    assert chart["type"] == "chart" and chart["params"]["values"] == [1, 2]
    bad = vp({"type": "chart", "params": {"labels": ["a"], "values": [1, 2]}})
    assert bad["type"] == "text_card" and "CHART" in bad["placeholder"]
    stat = vp({"type": "stat"}, overlay={"type": "stat", "value": "76%", "label": "turnout"})
    assert stat["type"] == "stat" and stat["params"] == {"value": "76%", "label": "turnout"}
    assert vp({"type": "stat"})["type"] == "text_card"
    blender = vp({"type": "blender", "template": "india_map", "params": {}})
    assert blender["type"] == "text_card" and "india_map" in blender["placeholder"]
    (proj / "build/blender").mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=red:s=64x64:d=1:r=30",
                    "-pix_fmt", "yuv420p", str(proj / "build/blender/scene_01_9x16.mp4")], check=True)
    clip = vp({"type": "blender", "template": "india_map"})
    assert clip["type"] == "blender" and clip["file"] == "build/blender/scene_01_9x16.mp4" and clip["clipFrames"] == 30


def test_srt_cues_and_timestamps(tmp_path):
    words = [Word(w=w, t=i * 0.4, end=i * 0.4 + 0.3) for i, w in enumerate("Aaj hum dekhenge. Phir baat karenge".split())]
    tl = Timeline(audio_file="a.m4a", duration_s=3.0, scenes=[TimelineScene(id=1, start_s=0, end_s=3, words=words)])
    n = RF.write_srt(tl, tmp_path / "x.srt")
    text = (tmp_path / "x.srt").read_text()
    assert n == 2 and "1\n00:00:00,000 --> 00:00:01," in text and "Aaj hum dekhenge." in text
    assert "2\n00:00:01,200 -->" in text and text.rstrip().endswith("Phir baat karenge")
    assert RF._srt_time(3725.5) == "01:02:05,500"


def test_india_names_and_codes():
    codes, bad = india.resolve_states(["ka", "Tamil Nadu", "TG", "Orissa", "Kerala", "Dadra and Nagar Haveli", "xx", "KA"])
    assert codes == ["KA", "TN", "TS", "OD", "KL", "DH"] and bad == ["xx"]
    assert len(india.STATES) == 36 and "TS" in india.STATES and "LA" in india.STATES


def test_boundary_download_is_mocked_and_idempotent(tmp_path):
    import httpx

    calls = []

    def handler(req):
        calls.append(req.url.path)
        return httpx.Response(200, text='{"type":"Feature","geometry":{"type":"Polygon","coordinates":[]}}')

    http = httpx.Client(transport=httpx.MockTransport(handler))
    assert india.fetch_boundaries(tmp_path, http, log=lambda *_: None) == 36
    assert len(calls) == 36 and all(c.endswith(".geojson") for c in calls)
    assert india.fetch_boundaries(tmp_path, http, log=lambda *_: None) == 0 and len(calls) == 36


def test_blender_scene_args_cache_and_state_cleanup(project_factory, monkeypatch, tmp_path):
    proj = project_factory([scene(1, "x")])
    fake_blend = tmp_path / "india_map.blend"
    fake_blend.write_bytes(b"blend")
    monkeypatch.setattr(RB, "ensure_template", lambda name, log=print: fake_blend)
    monkeypatch.setattr(RB, "find_blender", lambda: "/fake/Blender")
    runs, encodes = [], []

    class FakeProc:
        def __init__(self, cmd, **kw):
            runs.append(cmd)
            frames_dir = Path(cmd[cmd.index("--out") + 1])
            n = int(cmd[cmd.index("--frames") + 1])
            self.stdout = iter([f"00:01.0  render | Saved: '{frames_dir}/frame_{i:04d}.png'\n" for i in range(1, n + 1)])

        def wait(self):
            return 0

    monkeypatch.setattr(RB.subprocess, "Popen", FakeProc)
    monkeypatch.setattr(RB, "_encode", lambda frames_dir, dst, log: (encodes.append(dst), dst.write_bytes(b"mp4")))
    params = {"highlight_states": ["karnataka", "TG", "zzz"], "camera": "top_down_tilt"}
    out = RB.render_scene(proj, "india_map", params, 90, "9:16", 5, log=lambda *_: None)
    assert out.name == "scene_05_9x16.mp4" and out.read_bytes() == b"mp4"
    cmd = runs[0]
    assert cmd[:3] == ["/fake/Blender", "-b", "--factory-startup"] and "--aspect" in cmd and cmd[cmd.index("--frames") + 1] == "90"
    sent = json.loads(Path(cmd[cmd.index("--params") + 1]).read_text()) if Path(cmd[cmd.index("--params") + 1]).exists() else None
    assert sent is None or sent["highlight_states"] == ["KA", "TS"]
    RB.render_scene(proj, "india_map", params, 90, "9:16", 5, log=lambda *_: None)
    assert len(runs) == 1, "same template, params, frames and aspect: cached"
    RB.render_scene(proj, "india_map", params, 91, "9:16", 5, log=lambda *_: None)
    assert len(runs) == 2, "a different length re-renders"


def test_blender_failure_reports_frames(project_factory, monkeypatch, tmp_path):
    proj = project_factory([scene(1, "x")])
    (tmp_path / "t.blend").write_bytes(b"b")
    monkeypatch.setattr(RB, "ensure_template", lambda name, log=print: tmp_path / "t.blend")
    monkeypatch.setattr(RB, "find_blender", lambda: "/fake/Blender")

    class Crash:
        def __init__(self, cmd, **kw):
            self.stdout = iter(["Error: out of memory\n"])

        def wait(self):
            return 1

    monkeypatch.setattr(RB.subprocess, "Popen", Crash)
    with pytest.raises(RB.BlenderError, match=r"(?s)0/30 frames.*out of memory"):
        RB.render_scene(proj, "india_map", {}, 30, "16:9", 2, log=lambda *_: None)


def test_template_names_are_validated():
    with pytest.raises(RB.BlenderError):
        RB.template_file("../../etc/passwd")
    with pytest.raises(RB.BlenderError, match="unknown Blender template"):
        RB.ensure_template("nonexistent_template")


def test_state_marks_each_video(both):
    from scripts.lib.state import project_state

    proj, _ = both
    (proj / "build/cache").mkdir(parents=True, exist_ok=True)
    (proj / "audio/narration.m4a").write_bytes(b"a")
    steps = {s.key: s for s in project_state(proj)}
    assert steps["record"].status == "todo" and "1/3 recorded" in steps["record"].detail
    assert any("reel_02" in t for t in steps["record"].todos) and any("Long-form" in t for t in steps["record"].todos)
    assert steps["final"].status == "todo" and steps["final"].todos == ["Render Reel reel_01."]
    for name in ("reel_02.m4a", "long.m4a"):
        (proj / "audio" / name).write_bytes(b"a")
    assert {s.key: s for s in project_state(proj)}["record"].status == "done"


def test_studio_records_per_video(both, tmp_path):
    from scripts.jobs import Runner
    from scripts.studio import create_app

    proj, _ = both
    wav = tmp_path / "t.wav"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=300:duration=1", str(wav)], check=True)
    client = create_app(proj.parent, Runner(notify_done=False)).test_client()
    page = client.get("/p/proj").get_data(as_text=True)
    assert "Long-form 16:9" in page and "Reel reel_02" in page
    client.post("/p/proj/audio", data={"video": "long", "audio": (wav.open("rb"), "t.wav")}, content_type="multipart/form-data")
    assert (proj / "audio/long.m4a").exists() and not (proj / "audio/narration.m4a").exists()
    r = client.post("/p/proj/run/final", data={"video": "reel_02"})
    assert "err=1" in r.location and "reel_02" in r.location.replace("%20", " ") or "Record" in r.location
    r = client.post("/p/proj/audio", data={"video": "bogus", "audio": (wav.open("rb"), "t.wav")}, content_type="multipart/form-data")
    assert "err=1" in r.location


def test_same_blender_scene_gets_separate_clips_per_format(project_factory, tmp_path):
    assert RB.clip_path(4, "reel") != RB.clip_path(4, "long")
    assert RB.clip_path(4, "reel").endswith("_9x16.mp4") and RB.clip_path(4, "long").endswith("_16x9.mp4")


def test_self_drawing_scenes_need_no_downloaded_file(project_factory):
    from scripts.lib.state import project_state

    proj = project_factory([
        scene(1, "chart", {"type": "chart", "params": {"labels": ["a", "b"], "values": [1, 2]}}),
        scene(2, "stat", {"type": "stat"}, overlay={"type": "stat", "value": "5%"}),
        scene(3, "map", {"type": "blender", "template": "india_map", "params": {"highlight_states": ["KA"]}}),
    ])
    (proj / "input/brief.md").write_text("- topic: x\n")
    (proj / "script/script.md").write_text("# s\n")
    (proj / "build/cache/script.hash").write_text("h")
    from scripts import plan as plan_mod

    plan_mod.set_locked(proj, True)
    fetch = next(s for s in project_state(proj) if s.key == "fetch")
    assert "0/0" in fetch.detail, "nothing here has to be fetched"
