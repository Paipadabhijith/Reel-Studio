import pytest
from pydantic import ValidationError

from scripts.lib.schema import ScenesFile, Timeline
from scripts.new_project import starter_scenes


def test_starter_scenes_valid():
    sf = ScenesFile.model_validate(starter_scenes("demo", "hinglish"))
    assert [s.id for s in sf.scenes] == [1, 2, 3]
    assert sf.reels[0].hook_scene == 1


def test_duplicate_scene_ids_rejected():
    data = starter_scenes("demo", "en")
    data["scenes"][1]["id"] = 1
    with pytest.raises(ValidationError):
        ScenesFile.model_validate(data)


def test_reel_unknown_scene_rejected():
    data = starter_scenes("demo", "en")
    data["reels"][0]["scene_ids"] = [1, 99]
    with pytest.raises(ValidationError):
        ScenesFile.model_validate(data)


def test_bad_visual_type_rejected():
    data = starter_scenes("demo", "en")
    data["scenes"][0]["visual"]["type"] = "hologram"
    with pytest.raises(ValidationError):
        ScenesFile.model_validate(data)


def test_timeline_ok_and_overlap_rejected():
    ok = {
        "audio_file": "audio/narration.m4a", "duration_s": 5.0,
        "scenes": [
            {"id": 1, "start_s": 0, "end_s": 2, "words": [{"w": "one", "t": 0.0}]},
            {"id": 2, "start_s": 2, "end_s": 5},
        ],
    }
    Timeline.model_validate(ok)
    ok["scenes"][1]["start_s"] = 1
    with pytest.raises(ValidationError):
        Timeline.model_validate(ok)
