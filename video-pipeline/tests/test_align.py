"""Alignment tests run without Whisper: the transcript is mocked."""
from scripts import align_audio as A


def test_normalize_devanagari_matches_roman():
    assert A.normalize("रुको") == A.normalize("ruko")


def test_normalize_spelling_variants():
    assert A.normalize("Pipeline,") == A.normalize("pipeline")
    assert A.normalize("hai") == A.normalize("hai.")


def test_align_tokens_skips_missing_and_extra_words():
    script = [A.normalize(w) for w in "one two three four five".split()]
    heard = [A.normalize(w) for w in "uh one two four five".split()]
    m = A.align_tokens(script, heard)
    assert m[0] == 1 and m[1] == 2 and m[2] is None and m[3] == 3 and m[4] == 4


def test_fill_times_interpolates_gap():
    times = [(0.0, 1.0), None, None, (4.0, 5.0)]
    out = A._fill_times(times, 0.0, 5.0)
    assert out[1][0] == 1.0 and out[2][1] == 4.0
    assert out[1][1] == out[2][0]


def test_align_end_to_end_with_mocked_whisper(tmp_path, monkeypatch):
    import json
    import subprocess

    proj = tmp_path / "p"
    (proj / "audio").mkdir(parents=True)
    (proj / "build" / "cache").mkdir(parents=True)
    # synthetic 5 s tone standing in for "one two three four five"
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=220:duration=5",
         str(proj / "audio" / "narration.m4a")], check=True,
    )
    heard = [{"w": w, "start": float(i), "end": i + 0.8} for i, w in enumerate("one two three four five".split())]
    monkeypatch.setattr(A, "transcribe", lambda audio, lang: heard)

    from scripts.lib.schema import ScenesFile

    sf = ScenesFile.model_validate({
        "project": "p", "language": "en",
        "scenes": [
            {"id": 1, "text": "one two", "visual": {"type": "text_card"}},
            {"id": 2, "text": "three four five", "visual": {"type": "text_card"}},
        ],
    })
    tl = A.align(proj, sf, log=lambda *_: None)
    assert tl.scenes[0].start_s == 0.0
    assert abs(tl.scenes[1].start_s - 2.0) < 1e-6
    assert abs(tl.duration_s - 5.0) < 0.2
    assert [w.w for w in tl.scenes[1].words] == ["three", "four", "five"]
    assert json.loads((proj / "build" / "timeline.json").read_text())["scenes"][1]["id"] == 2
