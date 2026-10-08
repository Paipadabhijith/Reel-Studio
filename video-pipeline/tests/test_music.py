"""Optional background music: licence rules, the real ffmpeg mix (including ducking), and the Studio routes."""
import io
import json
import subprocess
from pathlib import Path

import pytest

from scripts import music as M
from scripts.jobs import Runner
from scripts.lib.schema import load_scenes
from scripts.lib.targets import get_target
from scripts.studio import create_app


def ff(*args):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *args], check=True)


def level_db(path: Path, start: float, dur: float, band: tuple[int, int] | None = None) -> float:
    """Mean volume of a stretch of audio, optionally only within a frequency band."""
    flt = f"atrim={start}:{start + dur}"
    if band:
        flt += f",highpass=f={band[0]},lowpass=f={band[1]}"
    r = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(path), "-af", flt + ",volumedetect", "-f", "null", "-"],
                       capture_output=True, text=True)
    return float(r.stderr.split("mean_volume:")[1].split("dB")[0])


@pytest.fixture
def media(tmp_path):
    # voice: a 1000 Hz tone for 2 s then 2 s of silence; music: a steady 200 Hz tone
    ff("-f", "lavfi", "-i", "sine=frequency=1000:duration=2", "-f", "lavfi", "-i", "anullsrc=r=48000:cl=mono",
       "-filter_complex", "[0:a]aformat=sample_rates=48000[a];[1:a]atrim=0:2[b];[a][b]concat=n=2:v=0:a=1", str(tmp_path / "voice.wav"))
    ff("-f", "lavfi", "-i", "sine=frequency=200:duration=5", str(tmp_path / "music.mp3"))
    return tmp_path / "voice.wav", tmp_path / "music.mp3"


@pytest.fixture
def target(project_factory):
    proj = project_factory([{"id": 1, "text": "hello there friend", "visual": {"type": "text_card"}}])
    return proj, get_target(load_scenes(proj / "script/scenes.json"), None)


def test_a_track_needs_a_source_and_a_licence(target, media):
    proj, t = target
    _, music = media
    with pytest.raises(M.MusicError, match="licence"):
        M.set_track(proj, t, music, title="x", source="Pixabay", license="")
    with pytest.raises(M.MusicError, match="licence"):
        M.set_track(proj, t, music, title="x", source="Pixabay", license="copyright-trust-me")
    with pytest.raises(M.MusicError, match="where the track came from"):
        M.set_track(proj, t, music, title="x", source="  ", license="royalty-free")
    assert M.get(proj, t) is None and not (proj / "audio/music").exists() or not list((proj / "audio/music").glob("*"))
    bad = proj / "notes.txt"
    bad.write_text("hi")
    with pytest.raises(M.MusicError, match="unsupported"):
        M.set_track(proj, t, bad, title="x", source="me", license="own")


def test_add_replace_update_and_clear(target, media):
    proj, t = target
    _, music = media
    track = M.set_track(proj, t, music, title="Calm", source="Pixabay Music", license="royalty-free", volume_db=-60)
    assert track.volume_db == M.MIN_DB, "volume is kept in a sane range"
    assert (proj / track.file).exists() and track.duration_s == 5.0
    assert "Calm from Pixabay Music" in track.credit and "Royalty-free" in track.credit
    fp1 = M.fingerprint(proj, t)
    M.update_settings(proj, t, volume_db=-18, duck=False, fade_s=99, clean_copy=False)
    got = M.get(proj, t)
    assert (got.volume_db, got.duck, got.fade_s, got.clean_copy) == (-18, False, M.MAX_FADE, False)
    assert M.fingerprint(proj, t) != fp1, "any change makes the render stale"
    old_file = proj / got.file
    M.set_track(proj, t, music, title="Other", source="me", license="own")
    assert M.get(proj, t).title == "Other"
    assert M.clear(proj, t) and M.get(proj, t) is None and M.fingerprint(proj, t) is None
    assert M.clear(proj, t) is False and not list((proj / "audio/music").glob("*"))
    with pytest.raises(M.MusicError):
        M.update_settings(proj, t, volume_db=-20, duck=True, fade_s=1, clean_copy=True)


def test_mix_has_the_narrations_length_and_music_under_it(target, media, tmp_path):
    proj, t = target
    voice, music = media
    track = M.set_track(proj, t, music, title="x", source="me", license="own", volume_db=-20, duck=False, fade_s=0)
    out = M.mix(voice, proj / track.file, track, tmp_path / "mix.wav")
    assert abs(M.probe_duration(out) - 4.0) < 0.05, "a 5 s track is trimmed to the 4 s narration"
    # both tones start at the same level, so inside the mix the voice should sit about 20 dB above the music
    voice_in_mix = level_db(out, 0.2, 1.5, (800, 1200))
    music_in_mix = level_db(out, 2.5, 1.2, (150, 250))
    assert 17 < voice_in_mix - music_in_mix < 23, f"music should sit ~20 dB under the voice, got {voice_in_mix - music_in_mix:.1f}"


def test_ducking_lowers_the_music_only_while_the_voice_speaks(target, media, tmp_path):
    proj, t = target
    voice, music = media
    steady = M.set_track(proj, t, music, title="x", source="me", license="own", volume_db=-12, duck=False, fade_s=0)
    flat = M.mix(voice, proj / steady.file, steady, tmp_path / "flat.wav")
    ducked_track = M.update_settings(proj, t, volume_db=-12, duck=True, fade_s=0, clean_copy=True)
    ducked = M.mix(voice, proj / ducked_track.file, ducked_track, tmp_path / "ducked.wav")
    band = (150, 250)
    flat_speaking = level_db(flat, 0.4, 1.2, band)
    ducked_speaking = level_db(ducked, 0.4, 1.2, band)
    ducked_silent = level_db(ducked, 2.6, 1.2, band)
    assert ducked_speaking < flat_speaking - 4, "music dips while the voice is speaking"
    assert abs(ducked_silent - level_db(flat, 2.6, 1.2, band)) < 2, "and comes back in the pauses"


def test_mixed_audio_is_the_narration_itself_without_music(target, media, tmp_path):
    proj, t = target
    voice, _ = media
    assert M.mixed_audio(proj, t, voice) == voice
    with pytest.raises(M.MusicError, match="no music"):
        M.preview(proj, t)


def test_preview_is_a_short_sample(target, media):
    proj, t = target
    voice, music = media
    (proj / "audio").mkdir(exist_ok=True)
    (proj / t.audio).write_bytes(voice.read_bytes())
    M.set_track(proj, t, music, title="x", source="me", license="own")
    out = M.preview(proj, t)
    assert out.suffix == ".m4a" and 3.8 < M.probe_duration(out) < 4.3


# ---------------------------------------------------------------- Studio


def test_studio_music_routes(target, media):
    proj, t = target
    _, music = media
    app = create_app(proj.parent, Runner(notify_done=False))
    app.testing = True
    c = app.test_client()
    page = c.get("/p/proj").get_data(as_text=True)
    assert "Music" in page and "voice only" in page and "Add a music track" in page

    r = c.post("/p/proj/music", data={"video": t.id, "source": "Pixabay", "license": "", "title": "x",
                                      "file": (io.BytesIO(music.read_bytes()), "calm.mp3")}, content_type="multipart/form-data")
    assert "err=1" in r.location and M.get(proj, t) is None
    r = c.post("/p/proj/music", data={"video": t.id, "source": "Pixabay Music", "license": "royalty-free", "title": "Calm",
                                      "volume_db": "-20", "duck": "1", "fade_s": "2",
                                      "file": (io.BytesIO(music.read_bytes()), "calm.mp3")}, content_type="multipart/form-data")
    assert "err=1" not in r.location
    got = M.get(proj, t)
    assert got.title == "Calm" and got.volume_db == -20 and got.duck and got.fade_s == 2
    page = c.get("/p/proj").get_data(as_text=True)
    assert "music on" in page and "Credit for the description: Music: Calm from Pixabay Music" in page
    c.post("/p/proj/music/settings", data={"video": t.id, "volume_db": "-15"})
    got = M.get(proj, t)
    assert got.volume_db == -15 and got.duck is False, "an unticked box means off"
    c.post("/p/proj/music/clear", data={"video": t.id})
    assert M.get(proj, t) is None
