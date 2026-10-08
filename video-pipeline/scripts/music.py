"""Optional background music, per video.

Music sits under the narration and dips while you speak (ducking). Every track needs a source and a
licence, because copyrighted music must never be baked into a rendered file. The settings live in
audio/music.json; the files are copied to audio/music/.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path

from .lib.targets import Target

LICENSES = {
    "royalty-free": "Royalty-free (free to use in videos)",
    "cc-by": "Creative Commons BY (credit the artist)",
    "public-domain": "Public domain / CC0",
    "licensed": "I bought or licensed it",
    "own": "I made it / I own it",
}
AUDIO_EXTS = {"mp3", "m4a", "wav", "aac", "flac", "ogg", "aiff"}
DEFAULT_DB = -22.0
MIN_DB, MAX_DB = -40.0, -6.0
MAX_FADE = 6.0
PREVIEW_S = 25.0


class MusicError(ValueError):
    """A user-facing reason the music settings were refused."""


@dataclass
class Track:
    file: str                      # relative to the project, under audio/music/
    title: str
    source: str                    # where it came from (site or artist)
    license: str                   # a key of LICENSES
    url: str = ""
    volume_db: float = DEFAULT_DB  # relative to the narration, which is what the final loudness is set by
    duck: bool = True
    fade_s: float = 1.5
    clean_copy: bool = True        # reels: also keep a voice-only export for adding Instagram's own music
    duration_s: float = 0.0

    @property
    def credit(self) -> str:
        who = self.title + (f" from {self.source}" if self.source else "")
        return f"Music: {who} ({LICENSES.get(self.license, self.license).split(' (')[0]})"


def settings_path(project: Path) -> Path:
    return project / "audio" / "music.json"


def load_all(project: Path) -> dict[str, Track]:
    try:
        raw = json.loads(settings_path(project).read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    out = {}
    for tid, d in raw.items():
        try:
            out[tid] = Track(**d)
        except TypeError:
            continue
    return out


def get(project: Path, target: Target) -> Track | None:
    t = load_all(project).get(target.id)
    return t if t and (project / t.file).exists() else None


def _save(project: Path, tracks: dict[str, Track]) -> None:
    p = settings_path(project)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({k: asdict(v) for k, v in tracks.items()}, indent=1))


def probe_duration(path: Path) -> float:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                       capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except ValueError:
        raise MusicError("that file isn't audio I can read")


def set_track(
    project: Path, target: Target, src: Path, *, title: str, source: str, license: str, url: str = "",
    volume_db: float = DEFAULT_DB, duck: bool = True, fade_s: float = 1.5, clean_copy: bool = True,
) -> Track:
    """Add or replace a video's music. Refuses a track with no source or licence."""
    if license not in LICENSES:
        raise MusicError("say what licence the track has: " + ", ".join(LICENSES))
    if not source.strip():
        raise MusicError("say where the track came from (a site, or the artist)")
    ext = src.suffix.lower().lstrip(".")
    if ext not in AUDIO_EXTS:
        raise MusicError(f"unsupported file type .{ext}; use mp3, m4a, wav, aac, flac, ogg or aiff")
    dur = probe_duration(src)
    if dur < 3:
        raise MusicError("that track is shorter than 3 seconds")
    safe = re.sub(r"[^a-zA-Z0-9._-]+", "_", src.stem)[:60] or "track"
    dest = project / "audio" / "music" / f"{target.id}_{safe}.{ext}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    old = load_all(project)
    if target.id in old and (project / old[target.id].file) != dest:
        (project / old[target.id].file).unlink(missing_ok=True)
    if src.resolve() != dest.resolve():
        shutil.copy2(src, dest)
    track = Track(file=str(dest.relative_to(project)), title=title.strip() or src.stem, source=source.strip(),
                  license=license, url=url.strip(), volume_db=_clamp_db(volume_db), duck=bool(duck),
                  fade_s=max(0.0, min(float(fade_s), MAX_FADE)), clean_copy=bool(clean_copy), duration_s=round(dur, 1))
    old[target.id] = track
    _save(project, old)
    return track


def update_settings(project: Path, target: Target, *, volume_db: float, duck: bool, fade_s: float, clean_copy: bool) -> Track:
    tracks = load_all(project)
    if target.id not in tracks:
        raise MusicError("no music on this video yet")
    t = tracks[target.id]
    t.volume_db, t.duck, t.clean_copy = _clamp_db(volume_db), bool(duck), bool(clean_copy)
    t.fade_s = max(0.0, min(float(fade_s), MAX_FADE))
    _save(project, tracks)
    return t


def clear(project: Path, target: Target) -> bool:
    tracks = load_all(project)
    t = tracks.pop(target.id, None)
    if t is None:
        return False
    (project / t.file).unlink(missing_ok=True)
    _save(project, tracks)
    return True


def _clamp_db(v: float) -> float:
    return round(max(MIN_DB, min(float(v), MAX_DB)), 1)


def fingerprint(project: Path, target: Target) -> str | None:
    """Changes whenever the track or any setting does; None when the video has no music."""
    t = get(project, target)
    if not t:
        return None
    st = (project / t.file).stat()
    return f"{t.file}:{st.st_size}:{st.st_mtime_ns}:{t.volume_db}:{t.duck}:{t.fade_s}"


# ---------------------------------------------------------------- mixing


def mix_filter(track: Track, duration: float) -> str:
    """ffmpeg filter graph: narration is input 0, the music input 1. Output label [out]."""
    fade = min(track.fade_s, duration / 3)
    music = (f"[1:a]aformat=sample_rates=48000:channel_layouts=stereo,atrim=0:{duration:.3f},"
             f"volume={track.volume_db}dB")
    if fade > 0:
        music += f",afade=t=in:d={fade:.2f},afade=t=out:st={max(duration - fade, 0):.3f}:d={fade:.2f}"
    music += "[m]"
    voice = "[0:a]aformat=sample_rates=48000:channel_layouts=stereo"
    if track.duck:
        graph = (f"{voice},asplit=2[voice][sc];{music};"
                 "[m][sc]sidechaincompress=threshold=0.03:ratio=12:attack=15:release=450:makeup=1[ducked];"
                 "[voice][ducked]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[out]")
    else:
        graph = (f"{voice}[voice];{music};"
                 "[voice][m]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[out]")
    return graph


def mix(narration: Path, track_file: Path, track: Track, dst: Path, duration: float | None = None) -> Path:
    """Write narration + looped music to `dst` (wav), as long as the narration (or `duration`)."""
    from .align_audio import duration_s

    dur = duration or duration_s(narration)
    dst.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", str(narration), "-stream_loop", "-1", "-i", str(track_file),
           "-filter_complex", mix_filter(track, dur), "-map", "[out]", "-t", f"{dur:.3f}", "-ar", "48000", str(dst)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        tail = r.stderr.strip().splitlines()[-1] if r.stderr.strip() else "unknown error"
        raise MusicError(f"mixing the music failed: {tail}")
    return dst


def mixed_audio(project: Path, target: Target, narration: Path) -> Path:
    """The audio to put under the video: the narration itself, or narration + music in build/."""
    t = get(project, target)
    if not t:
        return narration
    return mix(narration, project / t.file, t, project / "build" / f"mix_{target.id}.wav")


def preview(project: Path, target: Target) -> Path:
    """A short sample of the mix (first seconds of the narration) so the volume can be judged by ear."""
    t = get(project, target)
    narration = project / target.audio
    if not t:
        raise MusicError("no music on this video yet")
    if not narration.exists():
        raise MusicError("record the narration first so there is a voice to hear the music under")
    from .align_audio import duration_s

    dur = min(PREVIEW_S, duration_s(narration))
    wav = mix(narration, project / t.file, t, project / "build" / "parts" / f"music_preview_{target.id}.wav", dur)
    out = wav.with_suffix(".m4a")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(wav), "-c:a", "aac", "-b:a", "128k", str(out)], check=True)
    wav.unlink(missing_ok=True)
    return out
