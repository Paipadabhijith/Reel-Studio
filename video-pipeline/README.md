# video-pipeline

Turns a topic and reference articles into a narration script, fetches visuals, renders a draft, then aligns your recorded voice and renders a 9:16 Reel with animated word-by-word captions. Runs locally on an M1 Mac (8 GB). Zero recurring cost: `reel script --manual` writes the script through claude.ai with no API key.

**Status: Phases 1-3.** Working: `new`, `script`, `fetch`, `inbox`, `draft`, `review`, `align`, `final`, `status`, `clean`, `studio`, for Reels (9:16, burned-in captions) and long-form (16:9, chaptered, `.srt`), with animated charts, stats and a 3D India map. `package` and `publish` are Phase 4.

## Setup (macOS)

```bash
brew install python@3.11 node ffmpeg
brew install --cask blender   # only needed for 3D map scenes
cd video-pipeline
python3.11 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"      # installs the `reel` command
npm install                   # installs Remotion (workspace: template/)
cp .env.example .env          # then fill in the keys below
```

The first `reel final` downloads the Whisper model (`mlx-community/whisper-small-mlx`) from Hugging Face; after that it is cached.

### API keys (`.env`)

| Key | Used by | Get it |
| --- | --- | --- |
| `ANTHROPIC_API_KEY` (optional) | `reel script` without `--manual` (Claude Opus 5.5) | console.anthropic.com (paid per token; each run prints its token usage, and reruns with the same brief and articles are cached for free) |
| `PEXELS_API_KEY` | `reel fetch` photos + videos | pexels.com/api (free) |
| `UNSPLASH_ACCESS_KEY` | `reel fetch` photos (tried last) | unsplash.com/developers (free, 50 req/hour in demo mode) |
| `PIXABAY_API_KEY` | `reel fetch` photos + videos | pixabay.com/api/docs, shown when logged in (free, 100 req/minute; photos up to 1280 px; AI-generated images are skipped) |

No Anthropic key? Use `reel script <slug> --manual` (below). Wikimedia Commons needs no key. Photo search order: Pexels → Pixabay → Unsplash (Wikimedia first when a scene asks for it); videos: Pexels → Pixabay. With no stock keys at all, stock scenes go straight to the manual inbox.

## Studio (web interface)

```bash
reel studio          # opens http://127.0.0.1:7788 in your browser
```

- **Home:** your projects with their current stage, and a form to start a new one (topic, angle, links, pasted article text).
- **Project page:** every pipeline step with its status (done / needs you / waiting for you / out of date / blocked / later phase), a **Next** banner, a **Needs you** list per step, buttons to run each step, and where each output is saved (with *open* and *Show in Finder*).
- **Live job panel:** the running step, a progress bar (Remotion frame count, Whisper stages) and the log. One job runs at a time to protect the 8 GB RAM; the page refreshes itself when a job finishes, and macOS notifies you.
- **Script without an API key:** press *Write via claude.ai*, copy the prompt, paste Claude's reply back, press *Import*.
- **Recording:** record narration in the browser (allow the microphone) or upload any audio file; it becomes `audio/narration.m4a`, and the previous take is kept.
- **Review:** per-scene Keep / Replace / Refetch at `/p/<slug>/review/`.
- Logs of every run are saved in `projects/<slug>/build/logs/`. The server only listens on 127.0.0.1 and rejects form posts from other websites.

The CLI below does the same steps from the terminal; both read and write the same project folders.

## Workflow (terminal)

```bash
reel new my-reel                 # scaffolds projects/my-reel/ and opens input/brief.md
# fill in the brief (topic, angle, formats, reel_count, language, source_urls)
# and/or drop articles into input/articles/ as .txt, .md or .html
reel script my-reel --manual     # writes script/prompt.md and copies it: paste into a new claude.ai chat,
                                 # save the whole reply as script/response.json, then run the same command again
                                 # (with ANTHROPIC_API_KEY set, plain `reel script my-reel` does it in one step)
# CHECK script/facts.md: every claim with its source; anything marked NOT in sources needs verifying
reel fetch my-reel               # Pexels -> Pixabay -> Unsplash (or Wikimedia first for people/landmarks), charts via matplotlib
reel draft my-reel               # silent 540x960 preview at 150 wpm -> out/draft_reel_01.mp4
# manual scenes (screenshots, recent events) are listed in inbox/README.txt:
# drop sceneNN.jpg/png/mp4 into inbox/, then
reel draft my-reel --continue    # asks source + rights for each file, then re-renders
reel review my-reel              # opens the Studio's review page: Keep / Replace / Refetch each scene
# record yourself reading the reel's scenes in order (script.md lists them) -> audio/narration.m4a
reel final my-reel               # align + render -> out/reel_01_9x16.mp4
```

You can also skip `script` and hand-write `scenes.json` (see `projects/demo/`), and place images yourself at `assets/images/scene_NN.jpg`; hand-placed files are never overwritten by `fetch`.

- **Visual types:** `photo`, `video` (stock clips, muted and looped), `chart` (from `params`: kind, labels, values, title, unit), `text_card`, `manual`. `stat` and `blender` render as text cards until Phase 3.
- **Relevance:** a fetched result must share at least a third of the query's words with its description, or the scene is downgraded to `manual`. Refetch from the review page with better words, or `reel fetch my-reel --scene 4 --force`.
- **Credits:** every asset gets a line in `assets/credits.json` (source, license, URL, attribution). Manual files record the rights you chose: own / licensed / press-kit / commentary.
- `reel inbox my-reel [--watch]` ingests inbox files without rendering.

- Narration order is the first reel's `scene_ids` (or all scenes if there are none). Use `--reel reel_02` to pick another.
- `reel align my-reel` runs only transcription and tone analysis, writing `build/timeline.json` and `build/tone.json`.
- Everything is cached by content hash under `build/cache/`. Change the audio, script text or images and only the affected stages rerun. `reel clean my-reel` resets.
- Only one heavy job (Whisper or Remotion) runs at a time (`.heavy.lock`); Remotion concurrency is capped at 2.

## Hinglish

Write scene text in Roman script ("Aaj hum dekhenge..."). Whisper is run with `language=hi` and often answers in Devanagari, so alignment transliterates both sides to a common form before fuzzy matching. Captions always show your script's own spelling. Set `WHISPER_MODEL` in `.env` to try another model.

## Tests

```bash
pytest          # schemas, alignment, fetch, script, inbox, draft, review; all network calls are mocked
```

## Layout

See the build prompt. `template/` is the Remotion project, `scripts/` the Python CLI, `projects/<slug>/` one folder per video. `projects/demo/` renders end to end with bundled placeholder images and a generated text-to-speech test voice.

## Long-form, animated scenes and 3D (Phase 3)

**Videos.** A project makes one video per Reel in `scenes.json` plus one `long` video when `long_form.chapters` is set
(`format: "both"`). Each has its own recording: the first video uses `audio/narration.m4a`, the others `audio/<id>.m4a`
(e.g. `audio/reel_02.m4a`, `audio/long.m4a`). The Studio shows a recorder per video.

```bash
reel final my-reel                 # every video that has a recording
reel final my-reel --video long    # just one (a reel id, or "long")
reel draft my-reel --video long    # silent preview, 768x432, timed at 150 wpm
```

**How long-form renders.** Chapter by chapter (each chapter is rendered on its own, so memory stays flat), joined with
FFmpeg, then your narration is added at -14 LUFS. It also writes `out/long_16x9.srt`. Expect roughly 5 frames per second
on an M1: a 10-minute video is about an hour of unattended rendering. Finished chapters are cached, so if a render is
interrupted or you change one chapter, only the missing or changed ones render again.

**Scene types**

| `visual.type` | What you get | Needs |
| --- | --- | --- |
| `photo`, `video` | Fetched or hand-placed media (photos slowly zoom or pan) | a file in `assets/` |
| `chart` | Animated bar / line / pie: `params: {kind, title, unit, labels, values}` | nothing to download |
| `stat` | One big count-up number: `overlay: {type: "stat", value: "76%", label: "turnout"}` | nothing |
| any visual + `overlay` of type `stat` | The same number as a small badge on top of the picture | nothing |
| `blender` | 3D map: `template: "india_map"`, `params: {highlight_states: ["KL","TN","KA","TS"], camera: "top_down_tilt"}` | Blender |
| `manual`, `text_card` | Your own file / a text card | |

**3D India map.** States are 2-letter codes (KA, TN, KL, TS...) or plain names ("Tamil Nadu", "Telangana"); `camera` is
`top_down_tilt` (default), `top_down` or `orbit`. The first use downloads state boundaries once (about 40 MB, from
[udit-001/india-maps-data](https://github.com/udit-001/india-maps-data), which has Telangana, Ladakh and the merged Dadra
& Nagar Haveli and Daman & Diu), merges them into clean outlines and builds `blender/templates/india_map.blend`. Both
stay on your machine (git-ignored). Blender renders with Eevee at 32 samples; expect about one second per frame, so a
5-second map scene is a few minutes, and it is cached by template, parameters, length and aspect.
**Check the boundaries before you publish a map of India**: the data's licence is not stated, and maps published in India
are expected to follow the official boundary, which this third-party data may not.
