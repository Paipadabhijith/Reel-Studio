"""Creative direction: the prompt asks for it, the parser keeps it, the plan edits it, the renderer gets it."""
import json

import pytest

from scripts import animation as A
from scripts import generate_script as G
from scripts import plan as PL
from scripts import render_final as RF
from scripts.lib.schema import Direction, ScenesFile
from tests.test_phase2 import BRIEF, MODEL_OUTPUT


def with_direction(**extra):
    out = json.loads(json.dumps(MODEL_OUTPUT))
    out["direction"] = {"pack": "archival", "vibe": "proud nostalgia", "energy": "calm", "grade": "sepia",
                        "accent": "b23a2e", "accent2": "not a colour", "motifs": ["newsprint"], "avoid": ["modern stadiums"], **extra}
    out["scenes"].append({"id": 4, "text": "India 183, West Indies 140.", "emphasis": ["183"],
                          "visual": {"type": "animation", "query": None, "source": None, "orientation": "portrait", "motion": None,
                                     "prompt": None, "chart": None, "blender": None,
                                     "animation": {"template": "versus", "style": "burst", "headline": "The Final", "kicker": None,
                                                   "subline": None, "quote": None, "attribution": None,
                                                   "items": [{"label": "India", "value": "183"}, {"label": "West Indies", "value": "140"}]}},
                          "overlay": None})
    out["scenes"].append({"id": 5, "text": "Bas ek hi baat.", "emphasis": [],
                          "visual": {"type": "animation", "query": None, "source": None, "orientation": "portrait", "motion": None,
                                     "prompt": None, "chart": None, "blender": None,
                                     "animation": {"template": "list", "style": None, "headline": "Why", "kicker": None, "subline": None,
                                                   "quote": None, "attribution": None, "items": [{"label": "only one", "value": None}]}},
                          "overlay": None})
    out["scenes"].append({"id": 6, "text": "Kapil's Devils.", "emphasis": [],
                          "visual": {"type": "blender", "query": None, "source": None, "orientation": "portrait", "motion": None,
                                     "prompt": None, "chart": None, "animation": None,
                                     "blender": {"template": "title3d", "headline": "KAPIL'S DEVILS", "highlight_states": [], "camera": None}},
                          "overlay": None})
    return out


@pytest.fixture
def script_project(project_factory):
    proj = project_factory([{"id": 1, "text": "x", "visual": {"type": "text_card"}}])
    (proj / "input/brief.md").write_text(BRIEF)
    (proj / "input/articles/a.txt").write_text("Turnout in 2024 was 76 percent.")
    return proj


def test_prompt_asks_for_direction_first_and_passes_the_vibe():
    assert list(G.OUTPUT_SCHEMA["properties"])[0] == "direction", "the look is decided before any scene"
    assert "Creative direction" in G.SYSTEM and "archival" in G.SYSTEM and "Rhythm" in G.SYSTEM
    user = G.build_user_prompt(BRIEF, G.parse_brief(BRIEF), [])
    assert "tone: curious" in user and "target_audience: first-time voters" in user


def test_parser_keeps_direction_and_graphics(script_project):
    sf = G.generate(script_project, llm=lambda *a: json.dumps(with_direction()), log=lambda *_: None)
    d = sf.direction
    assert d.pack == "archival" and d.grade == "sepia" and d.motifs == ["newsprint"]
    assert d.accent == "#B23A2E" and d.accent2 is None, "a bad colour falls back to the pack's own"
    vs = sf.scene(4).visual.params
    assert vs["template"] == "versus" and len(vs["items"]) == 2 and "style" not in vs
    assert sf.scene(5).visual.params["template"] == "headline", "a list with one item becomes a headline"
    t3 = sf.scene(6).visual
    assert t3.template == "title3d" and t3.params["headline"] == "KAPIL'S DEVILS"


def test_old_scripts_without_direction_still_load(project_factory):
    proj = project_factory([{"id": 1, "text": "x", "visual": {"type": "text_card"}}])
    sf = PL.load(proj)
    assert sf.direction is None


def test_render_props_carry_direction(project_factory):
    from scripts.draft import estimate_timeline
    from scripts.lib.targets import list_targets
    proj = project_factory([{"id": 1, "text": "hello there", "visual": {"type": "text_card"}}])
    sf = PL.load(proj)
    tl = estimate_timeline(sf, list_targets(sf)[0])
    assert RF.build_props(proj, sf, tl, list_targets(sf)[0])["direction"]["pack"] == "editorial"
    sf.direction = Direction(pack="broadcast", energy="punchy")
    props = RF.build_props(proj, sf, tl, list_targets(sf)[0])
    assert props["direction"]["pack"] == "broadcast" and props["direction"]["energy"] == "punchy"


def test_plan_direction_form_and_graphic_editor(project_factory):
    proj = project_factory([{"id": 1, "text": "India 183, West Indies 140.", "visual": {"type": "text_card"}}])
    sf = PL.load(proj)
    PL.apply_direction(sf, {"pack": "broadcast", "energy": "punchy", "grade": "cool", "vibe": "  hype   final ",
                            "use_accent": "1", "accent": "#ff0000", "accent2": "#0000ff", "motifs": "floodlights, scoreboard"})
    assert sf.direction.pack == "broadcast" and sf.direction.vibe == "hype final" and sf.direction.accent == "#FF0000"
    PL.apply_direction(sf, {"pack": "archival", "accent": "#ff0000"})
    assert sf.direction.accent is None, "colours only count when 'own colours' is ticked"

    PL.apply_form(sf, 1, {"text": "India 183, West Indies 140.", "type": "animation", "template": "versus",
                          "headline": "The Final", "items": "India | 183\nWest Indies | 140"})
    p = sf.scene(1).visual.params
    assert p["template"] == "versus" and p["items"][1] == {"label": "West Indies", "value": "140"}
    with pytest.raises(PL.PlanError, match="at least 3 items"):
        PL.apply_form(sf, 1, {"text": "India 183, West Indies 140.", "type": "animation", "template": "list", "items": "one\ntwo"})


def test_rhythm_flags_repeats_and_runs(project_factory):
    g = lambda i, tpl: {"id": i, "text": f"scene {i}", "visual": {"type": "animation", "params": {"template": tpl, "headline": "x"}}}
    proj = project_factory([g(1, "headline"), g(2, "headline"), g(3, "list"),
                            {"id": 4, "text": "s4", "visual": {"type": "photo", "query": "q"}}, g(5, "quote")])
    warnings = PL.rhythm_warnings(PL.load(proj))
    assert any("scenes 1 and 2 are both headline graphics" in w for w in warnings)
    assert any("three graphic scenes in a row ending at scene 3" in w for w in warnings)


def test_auto_fallback_uses_list_and_timeline_templates():
    from scripts.lib.schema import Scene
    lst = A.decide(Scene.model_validate({"id": 1, "text": "Teen cheezein: paisa, TV, aur sapne.", "visual": {"type": "photo"}}))
    assert lst.visual["params"]["template"] == "list" and len(lst.visual["params"]["items"]) >= 3
    tl = A.decide(Scene.model_validate({"id": 2, "text": "1975 mein pehla World Cup, 1983 mein India jeeta.", "visual": {"type": "photo"}}))
    items = tl.visual["params"]["items"]
    assert tl.visual["params"]["template"] == "timeline" and [i["label"] for i in items] == ["1975", "1983"]
