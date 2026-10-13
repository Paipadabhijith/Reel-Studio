"""Studio web UI: pages, inputs, jobs, files and the step-status logic. No network, no rendering."""
import io
import json
import subprocess
import time

import pytest

from scripts.jobs import Runner
from scripts.lib.state import next_step, project_state
from scripts.studio import create_app


@pytest.fixture
def runner():
    return Runner(notify_done=False)


@pytest.fixture
def app_for(runner):
    def make(projects_dir):
        app = create_app(projects_dir, runner)
        app.testing = True
        return app.test_client()
    return make


def status(steps, key):
    return next(s for s in steps if s.key == key).status


def test_home_and_new_project(tmp_path, app_for):
    client = app_for(tmp_path)
    assert "New project" in client.get("/").get_data(as_text=True)
    r = client.post("/new", data={
        "slug": "monsoon", "topic": "Late monsoon", "angle": "farmers", "formats": "reel", "reel_count": "2",
        "language": "hinglish", "urls": "https://a.example/x\nnot-a-url\nhttps://b.example/y",
        "article_text": "IMD said the monsoon was late.",
    })
    assert r.status_code == 302 and r.location.endswith("/p/monsoon?msg=Project+created.+Next:+generate+the+script.")
    brief = (tmp_path / "monsoon/input/brief.md").read_text()
    assert "- topic: Late monsoon" in brief and "  - https://a.example/x" in brief and "not-a-url" not in brief
    assert (tmp_path / "monsoon/input/articles/pasted_1.txt").read_text().startswith("IMD said")
    steps = project_state(tmp_path / "monsoon")
    assert status(steps, "fetch") == "blocked" and status(steps, "record") == "blocked", \
        "starter scenes must not make later steps look actionable"
    page = client.get("/p/monsoon").get_data(as_text=True)
    assert "Next: Script" in page and "pasted_1.txt" in page and "a.example/x" in page

    assert client.post("/new", data={"slug": "monsoon", "topic": "x"}).location.endswith("err=1")
    assert client.post("/new", data={"slug": "Bad Name!", "topic": "x"}).location.endswith("err=1")


def test_cross_site_post_is_rejected(tmp_path, app_for):
    client = app_for(tmp_path)
    r = client.post("/new", data={"slug": "x", "topic": "t"}, headers={"Origin": "https://evil.example"})
    assert r.status_code == 403 and not (tmp_path / "x").exists()
    r = client.post("/new", data={"slug": "x", "topic": "t"}, headers={"Origin": "http://localhost"})
    assert r.status_code == 302


def test_articles_add_and_remove(project_factory, app_for):
    proj = project_factory([{"id": 1, "text": "t", "visual": {"type": "text_card"}}])
    client = app_for(proj.parent)
    client.post("/p/proj/articles", data={"title": "IMD", "text": "Body text"})
    client.post("/p/proj/articles", data={"file": (io.BytesIO(b"<p>hi</p>"), "page.html")},
                content_type="multipart/form-data")
    names = sorted(f.name for f in (proj / "input/articles").iterdir())
    assert names == ["page.html", "pasted_1.txt"]
    r = client.post("/p/proj/articles", data={"file": (io.BytesIO(b"x"), "evil.sh")}, content_type="multipart/form-data")
    assert "err=1" in r.location
    client.post("/p/proj/articles/delete", data={"name": "../../script/scenes.json"})
    assert (proj / "script/scenes.json").exists(), "delete is confined to input/articles"
    client.post("/p/proj/articles/delete", data={"name": "page.html"})
    assert not (proj / "input/articles/page.html").exists()


def test_file_route_is_confined(project_factory, app_for):
    proj = project_factory([{"id": 1, "text": "t", "visual": {"type": "text_card"}}])
    (proj / "out/reel_01_9x16.mp4").write_bytes(b"video")
    client = app_for(proj.parent)
    assert client.get("/p/proj/file/out/reel_01_9x16.mp4").data == b"video"
    assert client.get("/p/proj/file/out/../../../etc/passwd").status_code == 404
    assert client.get("/p/proj/file/build/cache/x").status_code == 404
    assert client.get("/p/..%2F..%2Fetc/file/x").status_code == 404


def test_runner_runs_one_job_and_reports(runner):
    def ok(log):
        log("working")
        return "all good"

    def boom(log):
        raise RuntimeError("bad input")

    a = runner.submit("p", "fetch", "Fetch", ok)
    assert runner.submit("p", "fetch", "Fetch", ok) is a or a.status != "queued", "duplicate pending step is reused"
    b = runner.submit("p", "draft", "Draft", boom)
    runner.wait_idle(5)
    assert a.status == "done" and a.result == "all good" and any("working" in l for l in a.lines)
    assert b.status == "failed" and "bad input" in b.error


def test_run_step_starts_job_and_writes_log(project_factory, app_for, runner):
    proj = project_factory([{"id": 1, "text": "turnout", "visual": {"type": "chart", "orientation": "portrait",
                            "params": {"kind": "bar", "labels": ["a", "b"], "values": [1, 2]}}}])
    client = app_for(proj.parent)
    r = client.post("/p/proj/run/fetch")
    assert r.status_code == 302 and "Started" in r.location
    runner.wait_idle(30)
    job = runner.recent("proj", 1)[0]
    assert job.status == "done", job.error
    assert (proj / "assets/images/scene_01_chart.png").exists()
    assert list((proj / "build/logs").glob("*-fetch.log"))
    data = client.get("/api/jobs?slug=proj").get_json()
    assert data["recent"][0]["status"] == "done" and data["active"] == []
    assert client.post("/p/proj/run/nonsense").status_code == 404


def test_final_needs_audio(project_factory, app_for):
    proj = project_factory([{"id": 1, "text": "t", "visual": {"type": "text_card"}}])
    r = app_for(proj.parent).post("/p/proj/run/final")
    assert "err=1" in r.location and "#record" in r.location


def test_audio_upload_converts_to_m4a(project_factory, app_for, tmp_path):
    proj = project_factory([{"id": 1, "text": "t", "visual": {"type": "text_card"}}])
    wav = tmp_path / "take.wav"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=300:duration=2",
                    str(wav)], check=True)
    client = app_for(proj.parent)
    r = client.post("/p/proj/audio", data={"audio": (wav.open("rb"), "take.wav")},
                    content_type="multipart/form-data", headers={"X-Requested-With": "fetch"})
    assert r.get_json()["ok"] and 1.8 < r.get_json()["duration"] < 2.3
    assert (proj / "audio/narration.m4a").exists()
    client.post("/p/proj/audio", data={"audio": (wav.open("rb"), "take2.wav")}, content_type="multipart/form-data")
    assert (proj / "audio/narration.prev.m4a").exists(), "previous take is kept"
    r = client.post("/p/proj/audio", data={"audio": (io.BytesIO(b"x"), "x.exe")}, content_type="multipart/form-data")
    assert "err=1" in r.location


def test_visuals_step_names_manual_waits_and_charts_without_numbers(project_factory):
    from scripts import plan as plan_mod
    proj = project_factory([
        {"id": 1, "text": "hello world", "visual": {"type": "photo", "query": "q"}},
        {"id": 2, "text": "need a screenshot", "visual": {"type": "manual", "prompt": "press release"}},
        {"id": 3, "text": "india earns most", "visual": {"type": "chart", "params": {}}},
    ])
    plan_mod.set_locked(proj, True)
    (proj / "build/cache/fetch.json").write_text("{}")
    (proj / "assets/images/scene_01.jpg").write_bytes(b"x")
    fetch = next(s for s in project_state(proj) if s.key == "fetch")
    assert fetch.status == "todo", "a chart with no numbers can't be fetched, so the step isn't done"
    assert "1/3" in fetch.detail and "1 wait for your file (Manual assets)" in fetch.detail
    assert fetch.todos == ["Scene 3: the chart has no numbers. Add labels and values in the plan, "
                           "or change it to another visual."]


def test_state_walks_through_the_pipeline(project_factory):
    proj = project_factory([
        {"id": 1, "text": "hello world", "visual": {"type": "photo", "query": "q"}},
        {"id": 2, "text": "need a screenshot", "visual": {"type": "manual", "prompt": "press release"}},
    ])
    steps = project_state(proj)
    assert status(steps, "brief") == "todo" and next_step(steps).key == "brief"
    assert status(steps, "final") == "blocked"

    (proj / "input/brief.md").write_text("- topic: Test\n- source_urls:\n  - https://x.example\n")
    (proj / "script/script.md").write_text("# s\n")
    (proj / "build/cache/script.hash").write_text("abc")
    (proj / "script/facts.md").write_text("- [ ] A claim\n- [ ] Other **(NOT in the supplied sources)**\n")
    time.sleep(0.01)
    steps = project_state(proj)
    assert status(steps, "brief") == "done" and status(steps, "script") == "done"
    facts = next(s for s in steps if s.key == "facts")
    assert facts.status == "todo" and "1 not found" in facts.detail
    assert next_step(steps).key == "plan", "the plan must be read and locked before anything is fetched"
    assert status(steps, "fetch") == "blocked" and status(steps, "record") == "blocked"
    from scripts import plan as plan_mod

    plan_mod.set_locked(proj, True)
    steps = project_state(proj)
    assert status(steps, "plan") == "done" and next_step(steps).key == "facts"
    manual = next(s for s in steps if s.key == "manual")
    assert manual.status == "todo" and "press release" in manual.todos[0]

    (proj / "build/facts_checked.json").write_text(
        json.dumps({"checked_at_mtime": (proj / "script/facts.md").stat().st_mtime}))
    (proj / "build/cache/fetch.json").write_text("{}")
    (proj / "assets/images/scene_01.jpg").write_bytes(b"x")
    (proj / "assets/images/scene_02.jpg").write_bytes(b"x")
    steps = project_state(proj)
    assert status(steps, "facts") == "done" and status(steps, "manual") == "done"
    assert next_step(steps).key == "record", "draft and review are optional"

    (proj / "audio/narration.m4a").write_bytes(b"a")
    assert status(project_state(proj), "final") == "todo"
    time.sleep(0.02)
    (proj / "out/reel_01_9x16.mp4").write_bytes(b"v")
    assert status(project_state(proj), "final") == "done"
    time.sleep(0.02)
    (proj / "audio/narration.m4a").write_bytes(b"new take")
    assert status(project_state(proj), "final") == "stale"


def test_project_page_renders_every_state(project_factory, app_for):
    proj = project_factory([{"id": 1, "text": "hello", "visual": {"type": "text_card"}}])
    client = app_for(proj.parent)
    assert client.get("/p/proj").status_code == 200
    (proj / "script/prompt.md").write_text("PROMPT TEXT")
    page = client.get("/p/proj").get_data(as_text=True)
    assert "PROMPT TEXT" in page and "Import script" in page
    r = client.post("/p/proj/run/script_import", data={"reply": ""})
    assert "err=1" in r.location
    assert client.get("/p/nope").status_code == 404
    assert client.get("/api/p/proj/state").get_json()["steps"][0]["key"] == "brief"


def test_search_again_button_for_scenes_that_found_nothing(project_factory, app_for, runner, monkeypatch):
    from scripts import fetch_assets
    from scripts import plan as plan_mod
    monkeypatch.setattr(fetch_assets, "retry_missing", lambda project, log=print: {"still missing": 1})  # no network
    proj = project_factory([
        {"id": 1, "text": "steam train", "visual": {"type": "manual", "downgraded_from": "photo",
         "query": "steam train", "prompt": "Auto-fetch found nothing relevant. Wanted: steam train"}},
        {"id": 2, "text": "a screenshot", "visual": {"type": "manual", "prompt": "press release"}},
    ])
    plan_mod.set_locked(proj, True)
    client = app_for(proj.parent)
    page = client.get("/p/proj").get_data(as_text=True)
    assert "Search again (1)" in page
    r = client.post("/p/proj/run/retry_missing")
    assert r.status_code == 302 and "Started" in r.location
    runner.wait_idle(10)
    job = runner.recent("proj", 1)[0]
    assert job.step == "retry_missing" and job.status == "done" and job.result == "1 still missing"
