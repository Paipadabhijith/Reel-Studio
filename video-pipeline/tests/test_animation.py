"""Animations that stand in for missing pictures: headlines, plan editing, the one-click switch, rendering props."""
import pytest

from scripts import animation as A
from scripts import plan as PL
from scripts import render_final as RF
from scripts.jobs import Runner
from scripts.lib.schema import Scene, ScenesFile, load_scenes
from scripts.studio import create_app


def sc(i, text, vis=None, emphasis=None):
    return Scene.model_validate({"id": i, "text": text, "emphasis": emphasis or [], "visual": vis or {"type": "photo", "query": "q"}})


def test_headline_prefers_stressed_words_then_numbers_then_strong_words():
    assert A.headline_for(sc(1, "Is saal monsoon late aaya.", emphasis=["ek hafta late"])) == "ek hafta late"
    assert A.headline_for(sc(1, "Turnout hit 76% in South India this year.")) == "76%"
    assert A.headline_for(sc(1, "June ki baarish normal se 11 percent kam rahi.")) == "11 percent"
    assert A.headline_for(sc(1, "Yeh 7 hafta pehle hua tha.")) == "7 hafta"
    assert A.headline_for(sc(1, "Dakshin ke chaar rajya sabse zyada prabhavit hue.")) == "Dakshin chaar rajya"
    assert A.headline_for(sc(1, "Ok.")) == "Ok."


def test_to_animation_remembers_what_it_was_and_both_engines_work():
    s = sc(2, "Aaj hum dekhenge pipeline kaise kaam karti hai.", {"type": "photo", "query": "pipeline", "file": "assets/images/x.jpg"})
    A.to_animation(s)
    v = s.visual
    assert v.type == "animation" and v.downgraded_from == "photo" and v.file is None and v.query == "pipeline"
    assert v.params["style"] in A.STYLES and v.params["headline"] and v.params["subline"].startswith("Aaj hum")
    A.to_animation(s, "blender")
    assert (s.visual.type, s.visual.template) == ("blender", "title3d") and s.visual.params["headline"]
    assert s.visual.downgraded_from == "photo", "still remembers the original, not 'animation'"
    assert "3D title" in A.describe(s)


def test_styles_vary_with_the_scene_id():
    styles = {A.auto_params(sc(i, "Some words here to show."))["style"] for i in range(1, 7)}
    assert styles == set(A.STYLES)


def test_render_props_for_animations_and_fallbacks(project_factory):
    proj = project_factory([{"id": 1, "text": "x", "visual": {"type": "text_card"}}])
    log = []
    own = RF.visual_props(proj, sc(1, "Dakshin ke chaar rajya.", {"type": "animation", "params": {"headline": "MY WORDS", "style": "rings"}}), "final", log.append)
    assert own["type"] == "animation" and own["params"]["headline"] == "MY WORDS" and own["params"]["style"] == "rings"
    assert own["params"]["subline"], "missing fields are filled from the sentence"
    missing = RF.visual_props(proj, sc(2, "Kerala mein baarish aayi.", {"type": "photo", "query": "kerala"}), "draft", log.append)
    assert missing["type"] == "animation" and missing["placeholder"].startswith("ANIMATION INSTEAD")
    final = RF.visual_props(proj, sc(2, "Kerala mein baarish aayi.", {"type": "photo", "query": "kerala"}), "final", log.append)
    assert final["type"] == "animation" and final["placeholder"] is None
    ask = RF.visual_props(proj, sc(3, "Dekho.", {"type": "photo", "query": "x", "on_missing": "manual"}), "draft", log.append)
    assert ask["type"] == "text_card" and "MISSING" in ask["placeholder"]


@pytest.fixture
def sf():
    return ScenesFile.model_validate({"project": "p", "scenes": [
        {"id": 1, "text": "Kerala mein baarish der se aayi.", "visual": {"type": "photo", "query": "kerala rain"}}]})


def test_plan_form_animation_title3d_and_on_missing(sf):
    PL.apply_form(sf, 1, {"text": "Kerala mein baarish der se aayi.", "type": "animation", "headline": "", "anim_style": "burst",
                          "keywords": "kerala, late, monsoon, extra", "subline": "Ek hafta der"})
    v = sf.scene(1).visual
    assert v.type == "animation" and v.params["headline"] == "Kerala baarish der", "empty headline is taken from the sentence"
    assert v.params["style"] == "burst" and v.params["keywords"] == ["kerala", "late", "monsoon", "extra"]
    PL.apply_form(sf, 1, {"text": "Kerala mein baarish der se aayi.", "type": "animation", "keywords": "a,b,c,d,e,f,g"})
    assert len(sf.scene(1).visual.params["keywords"]) == 5, "at most five tags"
    assert v.query == "kerala rain" or v.query is None
    PL.apply_form(sf, 1, {"text": "Kerala mein baarish der se aayi.", "type": "title3d", "headline": "LATE RAINS", "subline": "a week"})
    v = sf.scene(1).visual
    assert (v.type, v.template, v.params) == ("blender", "title3d", {"headline": "LATE RAINS", "subline": "a week"})
    PL.apply_form(sf, 1, {"text": "Kerala mein baarish der se aayi.", "type": "photo", "query": "kerala rain", "on_missing": "manual"})
    v = sf.scene(1).visual
    assert v.type == "photo" and v.on_missing == "manual" and v.template is None


# ---------------------------------------------------------------- Studio


@pytest.fixture
def client(project_factory):
    proj = project_factory([
        {"id": 1, "text": "Is saal monsoon late aaya.", "emphasis": ["monsoon"], "visual": {"type": "photo", "query": "monsoon"}},
        {"id": 2, "text": "Dekho screenshot.", "visual": {"type": "manual", "prompt": "a screenshot"}},
        {"id": 3, "text": "Done.", "visual": {"type": "text_card"}}])
    app = create_app(proj.parent, Runner(notify_done=False))
    app.testing = True
    return proj, app.test_client()


def test_parts_page_offers_an_animation_for_scenes_without_a_file(client):
    proj, c = client
    page = c.get("/p/proj/parts").get_data(as_text=True)
    assert page.count("Make an animation (best fit)") == 2 and page.count("Simple graphic") == 2 and page.count("3D title") >= 2
    assert "No file yet" in page


def test_one_click_switch_to_an_animation(client):
    proj, c = client
    r = c.post("/p/proj/plan/animate/1", data={"engine": "remotion", "back": "parts", "video": "reel_01"})  # forced simple graphic
    assert "/p/proj/parts" in r.location and "err=0" in r.location
    v = load_scenes(proj / "script/scenes.json").scene(1).visual
    assert v.type == "animation" and v.params["headline"] == "monsoon" and v.downgraded_from == "photo"
    page = c.get("/p/proj/parts").get_data(as_text=True)
    assert page.count("Make an animation (best fit)") == 1, "scene 1 no longer needs it"
    assert '<span class="pill">animation</span>' in page
    r = c.post("/p/proj/plan/animate/2", data={"engine": "blender"})
    v = load_scenes(proj / "script/scenes.json").scene(2).visual
    assert (v.type, v.template) == ("blender", "title3d") and "/plan" in r.location
    assert c.post("/p/proj/plan/animate/99").status_code == 404


def test_plan_page_shows_the_new_options(client):
    proj, c = client
    page = c.get("/p/proj/plan").get_data(as_text=True)
    assert "Animated graphic (fast)" in page and "3D animated title (Blender)" in page
    assert "If no picture is found" in page and "make an animation from the sentence" in page
    c.post("/p/proj/plan/animate/1", data={"engine": "remotion"})
    page = c.get("/p/proj/plan").get_data(as_text=True)
    assert "No photo was found" in page or "No photo" in page
    c.post("/p/proj/plan/scene/3", data={"text": "Done.", "type": "animation", "headline": "ALL DONE", "anim_style": "rings"})
    assert load_scenes(proj / "script/scenes.json").scene(3).visual.params["headline"] == "ALL DONE"
