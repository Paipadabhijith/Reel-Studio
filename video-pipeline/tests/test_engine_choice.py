"""The rule that picks Remotion (infographics) or Blender (geography, motion) for a scene with no picture."""
import pytest

from scripts import animation as A
from scripts import plan as PL
from scripts.lib import india
from scripts.lib.schema import Scene, ScenesFile


def mk(i, text, emphasis=None, vis=None):
    return Scene.model_validate({"id": i, "text": text, "emphasis": emphasis or [], "visual": vis or {"type": "photo", "query": "x"}})


def pick(text, **kw):
    return A.decide(mk(1, text, **kw))


@pytest.mark.parametrize("text,engine,kind", [
    # infographics -> Remotion
    ("Turnout hit 76% in South India this year.", "remotion", "stat"),
    ("June ki baarish normal se gyarah percent kam rahi.", "remotion", "stat"),
    ("2019 mein 68 percent tha aur 2024 mein 76 percent.", "remotion", "chart"),
    ("Kerala ne 40 percent, Goa ne 25 percent aur Punjab ne 10 percent diya.", "remotion", "chart"),
    ("Pehla karan mehngai, doosra karan berozgari, teesra karan sarkar.", "remotion", "list"),
    ("Teen karan hain: mehngai, berozgari, aur bhrashtachar.", "remotion", "list"),
    ("1983, 2007 aur 2011 mein India ne World Cup jeeta.", "remotion", "timeline"),
    ("Is saal record mehngai rahi aur log pareshan hue.", "remotion", "comparison"),
    # geography, and motion with nothing to chart -> Blender
    ("Kerala mein baarish ek hafta late aayi.", "blender", "map"),
    ("Kerala, Tamil Nadu aur Karnataka mein 11 percent kami darj hui.", "blender", "map"),
    ("Cyclone ne tatiya ilaake mein tabahi macha di.", "blender", "motion"),
    ("Baadh ka paani gaon mein tezi se phail gaya.", "blender", "motion"),
    ("Rocket launch ke baad poora desh dekhta raha.", "blender", "motion"),
    # nothing to chart, nothing moving -> plain animated text in Remotion
    ("Aaj hum ek zaroori mudde par baat karenge.", "remotion", "text"),
])
def test_the_rule(text, engine, kind):
    d = pick(text)
    assert (d.engine, d.kind) == (engine, kind), d.label
    assert d.reason and d.label.startswith("Blender" if engine == "blender" else "Remotion")


def test_infographic_beats_motion():
    d = pick("Cyclone mein 120 km hawa chali.")
    assert (d.engine, d.kind) == ("remotion", "stat"), "a number makes it drawable, so it is not a 3D scene"


def test_stat_chart_and_map_details():
    d = pick("Turnout hit 76% in South India this year.")
    assert d.visual["type"] == "stat" and d.overlay["value"] == "76%"
    d = pick("2019 mein 68 percent tha aur 2024 mein 76 percent.")
    assert d.visual["params"]["labels"] == ["2019", "2024"] and d.visual["params"]["values"] == [68, 76] and d.visual["params"]["unit"] == "%"
    d = pick("Kerala ne 40 percent, Goa ne 25 percent aur Punjab ne 10 percent diya.")
    assert d.visual["params"]["labels"] == ["Kerala", "Goa", "Punjab"] and d.visual["params"]["values"] == [40, 25, 10]
    d = pick("Kerala, Tamil Nadu aur Karnataka mein 11 percent kami darj hui.")
    assert d.visual["template"] == "india_map" and d.visual["params"]["highlight_states"] == ["KL", "TN", "KA"]
    assert d.overlay["value"] == "11%", "the figure rides along as a badge on the map"
    d = pick("Teen karan hain: mehngai, berozgari, aur bhrashtachar.")
    assert d.visual["params"]["keywords"] == ["mehngai", "berozgari", "bhrashtachar"]
    d = pick("1983, 2007 aur 2011 mein India ne World Cup jeeta.")
    assert d.visual["params"]["keywords"] == ["1983", "2007", "2011"] and d.visual["params"]["headline"] == "1983–2011"


def test_everyday_short_words_are_never_states():
    assert india.find_states("Yeh ka kaam up or down as usual hai, la la.") == []
    d = pick("Yeh ka kaam up or down as usual hai.")
    assert d.engine == "remotion"
    assert india.find_states("Orissa ka naam Odisha hua, Dilli aur Goa mein.") == ["OD", "DL", "GA"]


def test_opening_scene_needs_a_motion_cue_to_go_3d():
    sf = ScenesFile.model_validate({"project": "p", "reels": [{"id": "r", "scene_ids": [1, 2], "hook_scene": 1}],
                                    "scenes": [{"id": 1, "text": "Monsoon aaya.", "visual": {"type": "photo", "query": "x"}},
                                               {"id": 2, "text": "Monsoon aaya.", "visual": {"type": "photo", "query": "x"}}]})
    assert A.decide(sf.scene(1), sf).engine == "blender", "weak cue + opening scene"
    assert A.decide(sf.scene(2), sf).engine == "remotion", "the same words later in the video are not enough"
    plain = ScenesFile.model_validate({"project": "p", "reels": [{"id": "r", "scene_ids": [1], "hook_scene": 1}],
                                       "scenes": [{"id": 1, "text": "Aaj hum baat karenge.", "visual": {"type": "photo", "query": "x"}}]})
    assert A.decide(plain.scene(1), plain).engine == "remotion", "an opening scene with no motion cue stays plain"


def test_blender_scenes_are_capped_per_project():
    scenes = [{"id": i, "text": "Cyclone ne tabahi macha di.", "visual": {"type": "photo", "query": "x"}} for i in range(1, 7)]
    sf = ScenesFile.model_validate({"project": "p", "scenes": scenes})
    for i in range(1, 7):
        A.to_animation(sf.scene(i), "auto", sf)
    kinds = [sf.scene(i).visual.type for i in range(1, 7)]
    assert kinds.count("blender") == A.MAX_3D_SCENES and kinds.count("animation") == 6 - A.MAX_3D_SCENES
    capped = next(sf.scene(i) for i in range(1, 7) if sf.scene(i).visual.type == "animation")
    assert "already has 3 3D scenes" in capped.visual.params["why"]


def test_apply_writes_the_scene_and_remembers_the_picture():
    s = mk(1, "Turnout hit 76% in South India this year.", vis={"type": "photo", "query": "voters", "file": "assets/images/a.jpg"})
    A.to_animation(s, "auto")
    assert s.visual.type == "stat" and s.visual.downgraded_from == "photo" and s.visual.file is None
    assert s.overlay.value == "76%" and s.visual.params["why"].startswith("Remotion · stat")
    assert A.describe(s).startswith("Remotion · stat")
    m = mk(2, "Kerala mein baarish aayi.")
    A.to_animation(m, "auto")
    assert (m.visual.type, m.visual.template) == ("blender", "india_map") and m.visual.params["highlight_states"] == ["KL"]
    A.to_animation(m, "remotion")
    assert m.visual.type == "animation" and "why" not in m.visual.params, "forcing an engine overrides the rule"


def test_plan_form_auto_type_applies_the_rule():
    sf = ScenesFile.model_validate({"project": "p", "scenes": [mk(1, "x").model_dump()]})
    PL.apply_form(sf, 1, {"text": "2019 mein 68 percent tha aur 2024 mein 76 percent.", "type": "auto"})
    assert sf.scene(1).visual.type == "chart" and sf.scene(1).text.startswith("2019")
    PL.apply_form(sf, 1, {"text": "Cyclone ne tabahi macha di.", "type": "auto", "emphasis": "cyclone"})
    assert (sf.scene(1).visual.type, sf.scene(1).visual.template) == ("blender", "title3d")
    with pytest.raises(PL.PlanError, match="emphasis"):
        PL.apply_form(sf, 1, {"text": "Cyclone aaya.", "type": "auto", "emphasis": "toofan"})


def test_lone_small_numbers_are_not_figures():
    assert pick("Scene 1 mein hum baat karenge.").kind == "text"
    assert pick("Do baar 2 log aaye.").kind == "text"
    assert pick("7 din pehle hua.").kind == "stat", "a unit makes even a small number a figure"
    assert pick("1,20,000 log aaye.").kind == "stat", "so does being a big number"


def test_stat_label_skips_filler_words():
    d = pick("Is saal voter turnout 76% tak pahunch gaya.")
    assert d.overlay["value"] == "76%" and d.overlay["label"] == "voter turnout"
    assert pick("June ki baarish 11 percent kami darj hui.").overlay["label"] == "kami"
