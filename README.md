# Reel Studio

A local pipeline that turns a topic, a few articles and your recorded voice into finished Instagram Reels (9:16, word-by-word
captions) and long-form YouTube videos (16:9, chapters, `.srt`). It runs on an M1 Mac with 8 GB of RAM and has no recurring
cost: the script can be written through claude.ai with no API key.

## What it does

1. **Brief and sources:** a topic, angle, audience and tone, plus article links, YouTube links (read through their
   captions) or pasted text.
2. **Script:** Claude writes the narration, a fact list to check, hook options, title options, and a creative direction
   for the look: a broadcast-sports, archival or editorial style pack, with energy, grade and accent colours.
3. **Visuals:** stock photos and clips from Pexels, Pixabay, Coverr, Unsplash, Openverse, NASA, the Internet Archive and
   Wikimedia Commons, plus motion graphics (headline, versus, timeline, list, quote, scorecard, charts, stats) and 3D
   scenes in Blender.
4. **Voice:** record in the browser or upload a take. It's checked for dead air, then aligned word by word with Whisper.
5. **Render:** Remotion renders the final video with captions, transitions, grade and optional music.
6. **Package:** ranked title options, thumbnail text, YouTube description, Instagram caption, chapters, sources and
   credits, ready to paste. Uploading stays manual.

Everything runs from **Reel Studio**, a local web app at http://127.0.0.1:7788. You can also use the `reel` command line.

## Get started

The setup, Studio guide, workflow and every feature are documented in
**[video-pipeline/README.md](video-pipeline/README.md)**.

Quick start on macOS:

```bash
cd video-pipeline
python3.11 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
npm install
cp .env.example .env      # add your free stock-photo API keys
reel studio               # or double-click "Start Studio.command"
```

## Repository layout

```
video-pipeline/
  scripts/      Python pipeline and the Studio web app
  template/     Remotion project (scenes, style packs, captions, fonts)
  blender/      3D scene builders
  shared/       brand settings and your voice profile (voice.md)
  projects/     one folder per video project (media is git-ignored)
  tests/        pytest suite
```
