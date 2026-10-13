"""Voice profile, packaging from the script, the package file, dead-air check."""
import json
import subprocess

from scripts import generate_script as G
from scripts import package as P
from scripts.lib import recording_check as RC
from scripts.lib.schema import Packaging
from scripts.lib.state import project_state
from scripts.lib.targets import list_targets
from scripts.lib.voice import filled
from tests.test_phase2 import BRIEF, MODEL_OUTPUT


def test_voice_template_counts_only_when_filled_in():
    template = "# My voice\n<!-- hints -->\n\n## Who I'm talking to\n\n<!-- one person -->\n"
    assert filled(template) is None
    assert "Pune ka 22 saal ka" in filled(template + "Pune ka 22 saal ka IPL fan.\n")
    user = G.build_user_prompt(BRIEF, G.parse_brief(BRIEF), [], voice="Simple si baat hai.")
    assert "<creator_voice>\nSimple si baat hai.\n</creator_voice>" in user
    assert "<creator_voice>" not in G.build_user_prompt(BRIEF, G.parse_brief(BRIEF), [])


def test_prompt_has_hook_formulas_and_packaging():
    assert "Contrarian Flip" in G.SYSTEM and "[Statistic]" in G.SYSTEM and "thumbnail_text" in G.SYSTEM
    assert "packaging" in G.OUTPUT_SCHEMA["properties"]


def test_parser_keeps_packaging(project_factory):
    proj = project_factory([{"id": 1, "text": "x", "visual": {"type": "text_card"}}])
    (proj / "input/brief.md").write_text(BRIEF)
    (proj / "input/articles/a.txt").write_text("Turnout in 2024 was 76 percent.")
    out = json.loads(json.dumps(MODEL_OUTPUT))
    out["packaging"] = [{"video": "reel_01", "titles": ["76% turnout: South India ka record"], "thumbnail_text": "RECORD BREAK",
                         "description_lead": "South India mein 76% turnout.", "hashtags": ["#Election2024"], "search_queries": ["south india turnout"]}]
    sf = G.generate(proj, llm=lambda *a: json.dumps(out), log=lambda *_: None)
    assert sf.packaging[0].video == "reel_01" and sf.packaging[0].thumbnail_text == "RECORD BREAK"


def test_title_lint_rules():
    good = P.lint_title("66 to 1: How Kapil's Devils won Lord's", "WORLD CHAMPIONS")
    assert good["issues"] == [] and good["score"] >= 90
    bad = P.lint_title("this is the most INSANE CRAZY AMAZING moment in all of cricket history ever seen", "insane moment cricket history")
    text = " ".join(bad["issues"])
    for want in ("desktop search", "ALL-CAPS", "vague", "repeats the title", "three is the ceiling"):
        assert want in text, want
    assert bad["score"] < good["score"]


def test_package_file_for_a_reel(project_factory):
    proj = project_factory([{"id": 1, "text": "Hello there.", "visual": {"type": "text_card"}}])
    (proj / "input/brief.md").write_text("- topic: x\n- source_urls:\n  - https://news.example/a\n")
    (proj / "assets/credits.json").write_text(json.dumps([
        {"scene_id": 1, "source": "Pixabay", "license": "x", "url": "u", "attribution_text": "Video by Ravi from Pixabay", "added_by": "fetch"},
        {"scene_id": 99, "source": "Pixabay", "license": "x", "url": "u", "attribution_text": "not in this video", "added_by": "fetch"}]))
    from scripts.lib.schema import load_scenes
    sf = load_scenes(proj / "script/scenes.json")
    t = list_targets(sf)[0]
    sf.packaging = [Packaging(video=t.id, titles=["the AMAZING story", "66 to 1: India at Lord's"], thumbnail_text="UNDERDOGS",
                              description_lead="How India beat 66-to-1 odds.", hashtags=["IPL", "#viral", "#Cricket"],
                              search_queries=["india 66 to 1 odds"])]
    md = P.build(proj, sf, t, ["https://news.example/a"])
    assert md.index("66 to 1: India at Lord's") < md.index("the AMAZING story"), "titles are ranked"
    assert "#IPL #Cricket" in md and "#viral" not in md
    assert "Video by Ravi from Pixabay" in md and "not in this video" not in md
    assert "- https://news.example/a" in md and "## Instagram caption" in md
    assert "missing odds" in md or "✓" in md


def test_long_form_chapters_follow_youtube_rules(project_factory):
    from scripts.lib.schema import Timeline, load_scenes
    proj = project_factory([{"id": i, "text": f"scene {i}", "visual": {"type": "text_card"}} for i in range(1, 5)])
    sf = load_scenes(proj / "script/scenes.json")
    sf.format = "long"
    from scripts.lib.schema import LongForm
    sf.long_form = LongForm.model_validate({"chapters": [{"title": "Start", "scene_ids": [1]}, {"title": "Middle", "scene_ids": [2, 3]}, {"title": "End", "scene_ids": [4]}]})
    t = next(t for t in list_targets(sf) if t.kind == "long")
    tl = Timeline.model_validate({"audio_file": "a", "duration_s": 40, "scenes": [
        {"id": 1, "start_s": 0, "end_s": 12}, {"id": 2, "start_s": 12, "end_s": 20}, {"id": 3, "start_s": 20, "end_s": 34},
        {"id": 4, "start_s": 34, "end_s": 40}]})
    (proj / t.timeline).parent.mkdir(parents=True, exist_ok=True)
    (proj / t.timeline).write_text(tl.model_dump_json())
    lines, problems = P.chapter_lines(proj, sf, t)
    assert lines == ["0:00 Start", "0:12 Middle", "0:34 End"]
    assert problems == ['"End" is only 6 s; YouTube needs 10 s per chapter']


def test_package_step_follows_the_render(project_factory):
    proj = project_factory([{"id": 1, "text": "Hello there.", "visual": {"type": "text_card"}}])
    step = lambda: next(s for s in project_state(proj) if s.key == "publish")
    assert step().status == "blocked"
    from scripts.lib.schema import load_scenes
    t = list_targets(load_scenes(proj / "script/scenes.json"))[0]
    (proj / t.out).write_bytes(b"video")
    assert step().status == "todo"
    P.write(proj, load_scenes(proj / "script/scenes.json"), t, log=lambda *_: None)
    assert step().status == "done"


def test_dead_air_check_finds_pauses(tmp_path):
    take = tmp_path / "take.m4a"
    # 0.2 s quiet, 2 s tone, 1.4 s silence, 2 s tone, 0.3 s quiet
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                    "aevalsrc='if(between(t,0.2,2.2)+between(t,3.6,5.6),0.5*sin(2*PI*220*t),0)':d=5.9",
                    "-c:a", "aac", str(take)], check=True)
    r = RC.check(take, "reel")
    assert len(r["pauses"]) == 1 and 1.2 <= r["pauses"][0][1] <= 1.55 and "pause(s) over 1.0 s" in r["warnings"][0]
    assert RC.check(take, "long")["pauses"] == [], "long-form allows longer pauses"


def test_script_step_says_why_it_is_out_of_date(project_factory):
    proj = project_factory([{"id": 1, "text": "x", "visual": {"type": "text_card"}}])
    (proj / "input/brief.md").write_text("- topic: x\n")
    (proj / "script/script.md").write_text("# s\n")
    (proj / "build/cache/script.hash").write_text("abc")
    step = lambda: next(s for s in project_state(proj) if s.key == "script")
    assert step().status == "done", "a hand-written script is not flagged"
    (proj / "build/cache/script.version").write_text("script-v3")
    assert step().status == "stale" and "older prompt" in step().detail
    (proj / "build/cache/script.version").write_text(G.PROMPT_VERSION)
    assert step().status == "done"
