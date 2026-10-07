"""The plan editor: validation, structure edits, history and the lock."""
import json

import pytest

from scripts import plan as P
from scripts.lib.schema import ScenesFile


def scene(i, text="some words here", vis=None):
    return {"id": i, "text": text, "visual": vis or {"type": "text_card"}}


@pytest.fixture
def sf():
    return ScenesFile.model_validate({
        "project": "p", "format": "both",
        "reels": [{"id": "reel_01", "scene_ids": [1, 3], "hook_scene": 1}],
        "long_form": {"chapters": [{"title": "A", "scene_ids": [1, 2]}, {"title": "B", "scene_ids": [3, 4]}]},
        "scenes": [scene(1), scene(2), scene(3), scene(4)],
    })


def test_edit_chart_and_blender_and_stat(sf):
    P.apply_form(sf, 2, {"text": "June rainfall fell.", "type": "chart", "chart_kind": "bar", "chart_title": "Rain",
                         "chart_labels": "2023, 2024", "chart_values": "148, 131.5", "chart_unit": "mm"})
    v = sf.scene(2).visual
    assert v.type == "chart" and v.params["values"] == [148, 131.5] and v.params["labels"] == ["2023", "2024"]
    P.apply_form(sf, 3, {"text": "Four states hit.", "type": "blender", "states": "kerala, TG, KA", "camera": "orbit",
                         "emphasis": "four states"})
    v = sf.scene(3).visual
    assert v.template == "india_map" and v.params == {"highlight_states": ["KL", "TS", "KA"], "camera": "orbit"}
    assert sf.scene(3).emphasis == ["four states"]
    P.apply_form(sf, 4, {"text": "Down eleven percent.", "type": "stat", "overlay_value": "-11%", "overlay_label": "vs normal"})
    assert sf.scene(4).overlay.value == "-11%" and sf.scene(4).visual.template is None


@pytest.mark.parametrize("form,msg", [
    ({"text": "  "}, "can't be empty"),
    ({"text": "x", "type": "hologram"}, "unknown visual type"),
    ({"text": "x", "type": "photo"}, "search words"),
    ({"text": "x", "type": "manual"}, "note telling you"),
    ({"text": "x", "type": "chart", "chart_labels": "a,b", "chart_values": "1"}, "matching labels and values"),
    ({"text": "x", "type": "chart", "chart_labels": "a,b", "chart_values": "1,two"}, "must be numbers"),
    ({"text": "x", "type": "blender", "states": "narnia"}, "unknown state"),
    ({"text": "x", "type": "blender", "states": ""}, "at least one state"),
    ({"text": "x", "type": "stat"}, "needs a value"),
    ({"text": "hello there", "emphasis": "goodbye"}, "must appear in the text"),
])
def test_bad_edits_are_refused_without_changing_anything(sf, form, msg):
    before = sf.model_dump()
    with pytest.raises(P.PlanError, match=msg):
        P.apply_form(sf, 1, form)
    assert sf.model_dump() == before


def test_insert_puts_the_scene_in_every_list_that_has_its_neighbour(sf):
    new = P.insert_after(sf, 1)
    assert new.id == 5 and [s.id for s in sf.scenes] == [1, 5, 2, 3, 4]
    assert sf.reels[0].scene_ids == [1, 5, 3] and sf.long_form.chapters[0].scene_ids == [1, 5, 2]
    assert sf.long_form.chapters[1].scene_ids == [3, 4]


def test_delete_cleans_up_reels_chapters_and_hook(sf):
    P.delete_scene(sf, 1)
    assert sf.reels[0].scene_ids == [3] and sf.reels[0].hook_scene == 3
    assert sf.long_form.chapters[0].scene_ids == [2]
    P.delete_scene(sf, 2)
    assert [c.title for c in sf.long_form.chapters] == ["B"], "an emptied chapter disappears"
    ScenesFile.model_validate(sf.model_dump())
    one = ScenesFile.model_validate({"project": "p", "scenes": [scene(1)], "reels": []})
    with pytest.raises(P.PlanError):
        P.delete_scene(one, 1)


def test_move_swaps_in_scene_list_and_in_each_membership(sf):
    assert P.move_scene(sf, 3, -1)
    assert [s.id for s in sf.scenes] == [1, 3, 2, 4]
    assert sf.reels[0].scene_ids == [3, 1], "reel order follows"
    assert sf.long_form.chapters[1].scene_ids == [3, 4], "already first in its chapter: stays put there"
    assert P.move_scene(sf, 4, 1) is False or sf.long_form.chapters[1].scene_ids == [3, 4]
    P.move_scene(sf, 4, -1)
    assert sf.long_form.chapters[1].scene_ids == [4, 3]


def test_save_validates_and_keeps_history(tmp_path, sf):
    proj = tmp_path
    (proj / "script").mkdir()
    P.save(proj, sf)
    sf.scenes[0].text = "changed"
    P.save(proj, sf)
    assert json.loads((proj / "script/scenes.json").read_text())["scenes"][0]["text"] == "changed"
    hist = list((proj / "build/history").glob("scenes-*.json"))
    assert len(hist) == 1 and json.loads(hist[0].read_text())["scenes"][0]["text"] == "some words here"
    sf.reels[0].scene_ids.append(99)
    with pytest.raises(P.PlanError):
        P.save(proj, sf)


def test_lock_is_explicit_or_implied_by_existing_work(tmp_path):
    (tmp_path / "build").mkdir()
    assert not P.is_locked(tmp_path)
    P.set_locked(tmp_path, True)
    assert P.is_locked(tmp_path)
    other = tmp_path.parent / "legacy"
    (other / "audio").mkdir(parents=True)
    (other / "audio/narration.m4a").write_bytes(b"x")
    assert P.is_locked(other), "projects made before locking existed are not blocked"
