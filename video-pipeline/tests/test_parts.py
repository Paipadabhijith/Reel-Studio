"""Parts: automatic checks, approvals that go stale, the render gate, and the Studio plan/parts pages."""
import json
import subprocess
import time

import pytest
from PIL import Image

from scripts import parts as PT
from scripts import plan as PL
from scripts.jobs import Runner
from scripts.lib.schema import Timeline, TimelineScene, Word, load_scenes
from scripts.lib.targets import get_target
from scripts.studio import create_app


def sc(i, text="some words that are spoken here", vis=None, **kw):
    return {"id": i, "text": text, "visual": vis or {"type": "text_card"}, **kw}


def png(path, w, h, color="red"):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (w, h), color).save(path)


def levels(checks):
    return [c.level for c in checks]


def check(proj, i, ts=None, dups=None):
    sf = load_scenes(proj / "script/scenes.json")
    return PT.check_scene(proj, sf, sf.scene(i), get_target(sf, None), ts, dups)


def test_image_resolution_checks(project_factory):
    proj = project_factory([sc(1, vis={"type": "photo", "query": "q"}), sc(2, vis={"type": "photo", "query": "q"}),
                            sc(3, vis={"type": "photo", "query": "q"}), sc(4, vis={"type": "photo", "query": "q"})])
    png(proj / "assets/images/scene_01.jpg", 1080, 1920)      # exact fit
    png(proj / "assets/images/scene_02.jpg", 750, 1334)       # 1.44x
    png(proj / "assets/images/scene_03.jpg", 300, 500)        # far too small
    png(proj / "assets/images/scene_04.jpg", 1920, 1080)      # wrong orientation for a reel
    assert "error" not in levels(check(proj, 1)) and any("Sharp" in c.msg for c in check(proj, 1))
    assert any(c.level == "warn" and "soft" in c.msg for c in check(proj, 2))
    assert any(c.level == "error" and "Too small" in c.msg for c in check(proj, 3))
    assert any("Wrong orientation" in c.msg for c in check(proj, 4))


def test_missing_manual_chart_stat_and_blender_checks(project_factory):
    proj = project_factory([
        sc(1, vis={"type": "manual", "prompt": "the press release"}),
        sc(2, vis={"type": "chart", "params": {"labels": ["a"], "values": [1, 2]}}),
        sc(3, vis={"type": "stat"}),
        sc(4, vis={"type": "blender", "template": "india_map", "params": {"highlight_states": ["KA", "narnia"]}}),
        sc(5, text="x", vis={"type": "text_card"}),
    ])
    assert any(c.level == "error" and "the press release" in c.msg for c in check(proj, 1))
    assert any(c.level == "error" and "Chart" in c.msg for c in check(proj, 2))
    assert any(c.level == "error" and "no number" in c.msg for c in check(proj, 3))
    assert any(c.level == "error" and "narnia" in c.msg for c in check(proj, 4))
    assert any("Very short" in c.msg for c in check(proj, 5))
    long_text = " ".join(["word"] * 60)
    proj2 = project_factory([sc(1, text=long_text)])
    assert any("Long for one picture" in c.msg for c in check(proj2, 1))


def test_duplicate_picture_and_voice_match_checks(project_factory):
    proj = project_factory([sc(1, vis={"type": "photo", "query": "q"}), sc(2, vis={"type": "photo", "query": "q"})])
    png(proj / "assets/images/scene_01.jpg", 1080, 1920)
    (proj / "assets/images/scene_02.jpg").write_bytes((proj / "assets/images/scene_01.jpg").read_bytes())
    sf = load_scenes(proj / "script/scenes.json")
    ps = PT.overview(proj, sf, get_target(sf, None), with_stills=False)
    # identical bytes but different names/mtimes are not flagged by the cheap identity; same file reused is
    (proj / "assets/images/scene_02.jpg").unlink()
    sf.scenes[1].visual.file = "assets/images/scene_01.jpg"
    from scripts.lib.schema import dump_json
    dump_json(sf, proj / "script/scenes.json")
    ps = PT.overview(proj, load_scenes(proj / "script/scenes.json"), get_target(sf, None), with_stills=False)
    assert any("Same picture as scene" in c.msg for c in ps[0].checks)
    ts_bad = TimelineScene(id=1, start_s=0, end_s=4, words=[Word(w="a", t=0)], match=0.3)
    ts_ok = TimelineScene(id=1, start_s=0, end_s=4, words=[Word(w="a", t=0)], match=0.9)
    assert any("Only 30%" in c.msg for c in check(proj, 1, ts_bad))
    assert any("Voice matches" in c.msg for c in check(proj, 1, ts_ok))


def test_approval_goes_stale_when_the_scene_or_file_changes(project_factory):
    proj = project_factory([sc(1, vis={"type": "photo", "query": "q"}), sc(2)])
    png(proj / "assets/images/scene_01.jpg", 1080, 1920)
    sf = load_scenes(proj / "script/scenes.json")
    target = get_target(sf, None)
    ps = PT.overview(proj, sf, target, with_stills=False)
    assert [p.visual for p in ps] == ["pending", "pending"]
    PT.approve(proj, target, 1, "visual", ps[0].fingerprint)
    assert PT.overview(proj, sf, target, with_stills=False)[0].visual == "approved"

    time.sleep(0.01)
    png(proj / "assets/images/scene_01.jpg", 1080, 1920, "blue")   # swapped file
    assert PT.overview(proj, sf, target, with_stills=False)[0].visual == "stale"
    ps = PT.overview(proj, sf, target, with_stills=False)
    PT.approve(proj, target, 1, "visual", ps[0].fingerprint)
    sf.scenes[0].text = "the sentence changed"
    from scripts.lib.schema import dump_json
    dump_json(sf, proj / "script/scenes.json")
    assert PT.overview(proj, load_scenes(proj / "script/scenes.json"), target, with_stills=False)[0].visual == "stale"


def test_redo_clears_approval_and_bulk_approves_only_clean_parts(project_factory):
    proj = project_factory([sc(1), sc(2, text="x"), sc(3, vis={"type": "chart", "params": {}})])
    sf = load_scenes(proj / "script/scenes.json")
    target = get_target(sf, None)
    ps = PT.overview(proj, sf, target, with_stills=False)
    assert PT.approve_all_clean(proj, ps, target, "visual") == 1, "scene 2 has a warning and scene 3 an error"
    states = {p.scene.id: p.visual for p in PT.overview(proj, sf, target, with_stills=False)}
    assert states == {1: "approved", 2: "pending", 3: "blocked"}
    PT.request_redo(proj, target, 1, "wrong mood")
    p1 = PT.overview(proj, sf, target, with_stills=False)[0]
    assert p1.visual == "redo" and p1.note == "wrong mood"


def test_gate_requires_visual_then_timing(project_factory):
    proj = project_factory([sc(1), sc(2)])
    sf = load_scenes(proj / "script/scenes.json")
    target = get_target(sf, None)
    tl = Timeline(audio_file="a", duration_s=8, scenes=[
        TimelineScene(id=1, start_s=0, end_s=4, words=[Word(w="a", t=0)], match=0.9),
        TimelineScene(id=2, start_s=4, end_s=8, words=[Word(w="b", t=4)], match=0.9)])
    g = PT.gate(PT.overview(proj, sf, target, tl, with_stills=False))
    assert not g["visual_ok"] and g["visual_todo"] == [1, 2] and g["has_timing"] and not g["timing_ok"]
    for p in PT.overview(proj, sf, target, tl, with_stills=False):
        PT.approve(proj, target, p.scene.id, "visual", p.fingerprint)
    g = PT.gate(PT.overview(proj, sf, target, tl, with_stills=False))
    assert g["visual_ok"] and not g["timing_ok"]
    for p in PT.overview(proj, sf, target, tl, with_stills=False):
        PT.approve(proj, target, p.scene.id, "timing", p.timing_fp)
    g = PT.gate(PT.overview(proj, sf, target, tl, with_stills=False))
    assert g["visual_ok"] and g["timing_ok"]
    tl.scenes[1].end_s = 12                                  # re-recorded: scene 2 now runs longer
    assert PT.gate(PT.overview(proj, sf, target, tl, with_stills=False))["timing_todo"] == [2]


# ---------------------------------------------------------------- Studio routes


@pytest.fixture
def client_for():
    def make(proj):
        app = create_app(proj.parent, Runner(notify_done=False))
        app.testing = True
        return app.test_client()
    return make


def test_plan_page_edit_lock_and_structure(project_factory, client_for):
    proj = project_factory([sc(1), sc(2)])
    c = client_for(proj)
    page = c.get("/p/proj/plan").get_data(as_text=True)
    assert "Lock plan" in page and "some words that are spoken here" in page

    r = c.post("/p/proj/plan/scene/1", data={"text": "", "type": "text_card"})
    assert "err=1" in r.location and "not+saved" in r.location
    r = c.post("/p/proj/plan/scene/1", data={"text": "A better line.", "type": "chart", "chart_labels": "a,b",
                                              "chart_values": "3,4", "chart_kind": "bar"})
    assert "err=1" not in r.location
    saved = json.loads((proj / "script/scenes.json").read_text())["scenes"][0]
    assert saved["text"] == "A better line." and saved["visual"]["params"]["values"] == [3, 4]
    assert list((proj / "build/history").glob("scenes-*.json"))

    c.post("/p/proj/plan/insert", data={"after": "1"})
    assert [s["id"] for s in json.loads((proj / "script/scenes.json").read_text())["scenes"]] == [1, 3, 2]
    c.post("/p/proj/plan/move/3/down")
    assert [s["id"] for s in json.loads((proj / "script/scenes.json").read_text())["scenes"]] == [1, 2, 3]
    c.post("/p/proj/plan/delete/3")
    assert [s["id"] for s in json.loads((proj / "script/scenes.json").read_text())["scenes"]] == [1, 2]

    assert not PL.is_locked(proj)
    r = c.post("/p/proj/plan/lock")
    assert PL.is_locked(proj) and "/p/proj" in r.location
    c.post("/p/proj/plan/lock", data={"unlock": "1"})
    assert not PL.is_locked(proj)


def test_parts_page_approve_redo_and_gating(project_factory, client_for):
    proj = project_factory([sc(1, vis={"type": "chart", "params": {"labels": ["a", "b"], "values": [1, 2]}}),
                            sc(2, vis={"type": "manual", "prompt": "a file"})])
    c = client_for(proj)
    page = c.get("/p/proj/parts").get_data(as_text=True)
    assert "0/2 approved" in page and "a file" in page
    r = c.post("/p/proj/parts/1/approve", data={"video": "reel_01", "pass": "visual"})
    assert "err=1" not in r.location
    r = c.post("/p/proj/parts/2/approve", data={"video": "reel_01", "pass": "visual"})
    assert "err=1" in r.location, "a part with a problem can't be approved"
    r = c.post("/p/proj/parts/1/redo", data={"video": "reel_01", "pass": "visual", "note": ""})
    assert "err=1" in r.location, "a redo needs a note"
    c.post("/p/proj/parts/1/redo", data={"video": "reel_01", "pass": "visual", "note": "numbers wrong"})
    assert "redo requested" in c.get("/p/proj/parts").get_data(as_text=True)
    assert c.get("/p/proj/parts?video=nope").status_code == 404


def test_assemble_is_gated_but_can_be_overridden(project_factory, client_for, monkeypatch):
    proj = project_factory([sc(1), sc(2)])
    data = json.loads((proj / "script/scenes.json").read_text())
    data["format"] = "long"
    data["reels"] = []
    data["long_form"] = {"chapters": [{"title": "All", "scene_ids": [1, 2]}]}
    (proj / "script/scenes.json").write_text(json.dumps(data))
    (proj / "audio").mkdir(exist_ok=True)
    (proj / "audio/narration.m4a").write_bytes(b"a")
    sf = load_scenes(proj / "script/scenes.json")
    target = get_target(sf, None)
    assert target.kind == "long"
    from scripts.lib.schema import dump_json
    from scripts.draft import estimate_timeline
    dump_json(estimate_timeline(sf, target), proj / target.timeline)
    c = client_for(proj)
    r = c.post("/p/proj/run/assemble", data={"video": "long"})
    assert "err=1" in r.location and "check" in r.location.lower()
    r = c.post("/p/proj/run/final", data={"video": "long"})
    assert "err=1" in r.location, "one-click long-form render needs the explicit override"
    ran = []
    import scripts.studio as S
    monkeypatch.setattr(S, "job_assemble", lambda p, t: (lambda log: ran.append(t) or "ok"))
    r = c.post("/p/proj/run/assemble", data={"video": "long", "override": "1"})
    assert "Started" in r.location
    time.sleep(0.3)
    assert ran == ["long"]


def test_cancel_endpoint(project_factory, client_for):
    proj = project_factory([sc(1)])
    app = create_app(proj.parent, Runner(notify_done=False))
    app.testing = True
    c = app.test_client()
    runner = app.config["RUNNER"]
    gate = __import__("threading").Event()
    job = runner.submit("proj", "x", "blocking", lambda log: gate.wait(5))
    queued = runner.submit("proj", "y", "waiting", lambda log: None)
    time.sleep(0.1)
    assert c.post(f"/api/jobs/{queued.id}/cancel").get_json() == {"ok": True}
    assert queued.status == "cancelled"
    assert c.post("/api/jobs/9999/cancel").get_json() == {"ok": False}
    gate.set()
    runner.wait_idle(5)
