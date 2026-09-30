"""Script generation (mocked Claude), inbox, draft timing, review server."""
import io
import json

import pytest

from scripts import draft as D
from scripts import generate_script as G
from scripts import manual_inbox as M
from scripts.lib.schema import load_scenes

BRIEF = """# Brief

- topic: South India voter turnout
- angle: why turnout rose
- target_audience: first-time voters
- formats: both        # reel / long / both
- reel_count: 1
- tone: curious
- language: hinglish  # en / hi / hinglish
- source_urls:
"""

MODEL_OUTPUT = {
    "title": "Turnout ka record",
    "hooks": ["76% turnout? Haan, sach mein."],
    "facts": [{"claim": "Turnout was 76%", "figure": "76%", "date": "2024", "source": "a.txt",
               "verified_in_sources": True},
              {"claim": "Highest ever", "figure": None, "date": None, "source": None, "verified_in_sources": False}],
    "chapters": [{"title": "Background", "scene_ids": [1, 2]}],
    "reels": [{"id": "reel_01", "scene_ids": [1, 3], "hook_scene": 1}],
    "scenes": [
        {"id": 1, "text": "2024 mein turnout 76% tak pahunch gaya.", "emphasis": ["76%"],
         "visual": {"type": "photo", "query": "voters queue polling booth", "source": "stock",
                    "orientation": "portrait", "motion": "slow-zoom-in", "prompt": None, "chart": None,
                    "blender": None},
         "overlay": {"type": "stat", "value": "76%", "label": "turnout"}},
        {"id": 2, "text": "Pichhle chunav se yeh kaafi zyada hai.", "emphasis": [],
         "visual": {"type": "chart", "query": None, "source": None, "orientation": "landscape", "motion": None,
                    "prompt": None, "chart": {"kind": "bar", "title": "Turnout", "unit": "%",
                                              "labels": ["2019", "2024"], "values": [68, 76]}, "blender": None},
         "overlay": None},
        {"id": 3, "text": "Press release ka screenshot dekho.", "emphasis": [],
         "visual": {"type": "manual", "query": None, "source": None, "orientation": "portrait", "motion": None,
                    "prompt": "Screenshot of the EC press release", "chart": None, "blender": None},
         "overlay": None},
    ],
}


@pytest.fixture
def script_project(project_factory):
    proj = project_factory([{"id": 1, "text": "x", "visual": {"type": "text_card"}}])
    (proj / "input/brief.md").write_text(BRIEF)
    (proj / "input/articles/a.txt").write_text("Turnout in 2024 was 76 percent.")
    return proj


def test_parse_brief():
    b = G.parse_brief(BRIEF + "  - https://example.com/a\n")
    assert b["formats"] == "both" and b["reel_count"] == 1 and b["language"] == "hinglish"
    assert b["source_urls"] == ["https://example.com/a"]


def test_output_schema_objects_are_closed():
    def walk(s):
        if isinstance(s, dict):
            if s.get("type") == "object":
                assert s["additionalProperties"] is False and set(s["required"]) == set(s["properties"])
            for v in s.values():
                walk(v)
        elif isinstance(s, list):
            for v in s:
                walk(v)
    walk(G.OUTPUT_SCHEMA)


def test_generate_writes_outputs_and_caches(script_project):
    calls = []

    def fake_llm(system, user, log):
        calls.append(user)
        assert "Roman (Latin) script" in user and "Turnout in 2024 was 76 percent." in user
        return json.dumps(MODEL_OUTPUT)

    sf = G.generate(script_project, llm=fake_llm, log=lambda *_: None)
    assert [s.id for s in sf.scenes] == [1, 2, 3] and sf.language == "hinglish"
    assert sf.scene(2).visual.params["values"] == [68, 76]
    assert sf.scene(3).visual.fallback == "text_card"
    assert (script_project / "script/scenes.json.bak").exists()
    facts = (script_project / "script/facts.md").read_text()
    assert "- [ ] Turnout was 76%" in facts and "NOT in the supplied sources" in facts
    assert "[1] 2024 mein turnout" in (script_project / "script/script.md").read_text()

    G.generate(script_project, llm=fake_llm, log=lambda *_: None)
    assert len(calls) == 1, "unchanged brief + articles must not call Claude again"


def test_generate_rejects_bad_references(script_project):
    bad = json.loads(json.dumps(MODEL_OUTPUT))
    bad["reels"][0]["scene_ids"] = [1, 99]
    with pytest.raises(G.ScriptError):
        G.generate(script_project, llm=lambda *a: json.dumps(bad), log=lambda *_: None)


def test_inbox_ingest_moves_file_and_records_rights(project_factory):
    proj = project_factory([
        {"id": 5, "text": "the announcement", "visual": {"type": "manual", "prompt": "press release"}},
        {"id": 6, "text": "other", "visual": {"type": "manual", "prompt": "a map"}},
    ])
    sf = load_scenes(proj / "script/scenes.json")
    assert len(M.write_readme(proj, sf)) == 2
    (proj / "inbox/scene05.JPG").write_bytes(b"img")
    (proj / "inbox/scene99.jpg").write_bytes(b"stray")
    done = M.ingest(proj, lambda scene, name: ("press-kit", "EC press kit"), log=lambda *_: None)
    assert done == [5]
    assert (proj / "assets/images/scene_05.jpg").read_bytes() == b"img"
    assert (proj / "inbox/scene99.jpg").exists(), "unknown scene ids stay in the inbox"
    credit = json.loads((proj / "assets/credits.json").read_text())[0]
    assert credit == {"scene_id": 5, "source": "EC press kit", "license": "press-kit", "url": "",
                      "attribution_text": "EC press kit", "added_by": "manual"}
    readme = (proj / "inbox/README.txt").read_text()
    assert "scene06  [" in readme and "scene05  [" not in readme


def test_estimated_timeline_150wpm(project_factory):
    proj = project_factory([
        {"id": 1, "text": " ".join(["word"] * 10), "visual": {"type": "text_card"}},  # 4.0 s
        {"id": 2, "text": "short", "visual": {"type": "text_card"}},                  # floor 2.0 s
    ])
    tl = D.estimate_timeline(load_scenes(proj / "script/scenes.json"), "reel_01")
    assert tl.scenes[0].end_s == 4.0 and tl.scenes[1].start_s == 4.0 and tl.duration_s == 6.0
    assert tl.scenes[0].words[1].t == 0.4


def test_draft_props_label_missing_manual(project_factory):
    from scripts.render_final import build_props

    proj = project_factory([{"id": 1, "text": "hello there", "visual": {"type": "manual", "prompt": "a map"}}])
    sf = load_scenes(proj / "script/scenes.json")
    props = build_props(proj, sf, D.estimate_timeline(sf, "reel_01"), "reel_01", "draft", log=lambda *_: None)
    assert props["audioSrc"] is None and props["draft"] is True
    assert props["scenes"][0]["visual"]["placeholder"] == "MANUAL: a map"


def test_review_keep_replace(project_factory):
    from scripts.review_server import create_app

    proj = project_factory([{"id": 1, "text": "hello", "visual": {"type": "manual", "prompt": "a map"}}])
    client = create_app(proj).test_client()
    page = client.get("/").get_data(as_text=True)
    assert "hello" in page and "1 manual pending" in page

    r = client.post("/scene/1/replace", data={"rights": "own", "source": "my photo",
                                              "file": (io.BytesIO(b"png"), "map.png")},
                    content_type="multipart/form-data")
    assert r.status_code == 302
    assert (proj / "assets/images/scene_01.png").read_bytes() == b"png"
    assert client.get("/asset/assets/images/scene_01.png").data == b"png"
    assert client.get("/asset/script/scenes.json").status_code == 404, "only assets/ is served"

    client.post("/scene/1/keep")
    assert json.loads((proj / "build/review.json").read_text()) == {"1": "keep"}
    assert "0 manual pending" in client.get("/").get_data(as_text=True)


def test_cli_inbox_prompts_for_rights(project_factory, monkeypatch):
    from typer.testing import CliRunner

    from scripts import cli

    proj = project_factory([{"id": 2, "text": "t", "visual": {"type": "manual", "prompt": "p"}}])
    monkeypatch.setattr(cli, "project_dir", lambda slug: proj)
    (proj / "inbox/scene2.png").write_bytes(b"x")
    res = CliRunner().invoke(cli.app, ["inbox", "proj"], input="nonsense\nlicensed\nGetty via employer\n")
    assert res.exit_code == 0, res.output
    assert "1 added, 0 still needed" in res.output
    assert json.loads((proj / "assets/credits.json").read_text())[0]["license"] == "licensed"


def test_manual_mode_prompt_then_import(script_project, monkeypatch):
    monkeypatch.setattr(G, "_copy_to_clipboard", lambda text: True)
    log = []
    assert G.generate_manual(script_project, log=log.append) is None
    prompt = (script_project / "script/prompt.md").read_text()
    assert "Turnout in 2024 was 76 percent." in prompt and '"additionalProperties": false' in prompt

    # claude.ai replies are often wrapped in prose and a code fence
    reply = "Here is the script:\n```json\n" + json.dumps(MODEL_OUTPUT) + "\n```\nLet me know!"
    (script_project / "script/response.json").write_text(reply)
    sf = G.generate_manual(script_project, log=log.append)
    assert [s.id for s in sf.scenes] == [1, 2, 3]
    assert not (script_project / "script/response.json").exists()
    assert not (script_project / "script/prompt.md").exists()
    assert "- [ ] Turnout was 76%" in (script_project / "script/facts.md").read_text()
    # unchanged brief: nothing to do
    assert G.generate_manual(script_project, log=log.append).scenes == sf.scenes


def test_manual_mode_stale_reply_is_set_aside(script_project, monkeypatch):
    monkeypatch.setattr(G, "_copy_to_clipboard", lambda text: False)
    G.generate_manual(script_project, log=lambda *_: None)
    (script_project / "script/response.json").write_text(json.dumps(MODEL_OUTPUT))
    (script_project / "input/articles/b.txt").write_text("A new article arrived.")
    assert G.generate_manual(script_project, log=lambda *_: None) is None
    assert (script_project / "script/response.old.json").exists()
    assert "A new article arrived." in (script_project / "script/prompt.md").read_text()


def test_manual_mode_bad_reply_errors(script_project, monkeypatch):
    monkeypatch.setattr(G, "_copy_to_clipboard", lambda text: True)
    G.generate_manual(script_project, log=lambda *_: None)
    (script_project / "script/response.json").write_text('{"title": "x"}')
    with pytest.raises(G.ScriptError, match="did not validate"):
        G.generate_manual(script_project, log=lambda *_: None)
    assert (script_project / "script/response.json").exists(), "a bad reply stays put so it can be fixed"
