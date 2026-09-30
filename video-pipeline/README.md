# video-pipeline

Turns a topic and reference articles into a narration script, fetches visuals, renders a draft, then aligns your recorded voice and renders a 9:16 Reel with animated word-by-word captions. Runs locally on an M1 Mac (8 GB). Zero recurring cost: `reel script --manual` writes the script through claude.ai with no API key.

**Status: Phases 1-2.** Working: `new`, `script`, `fetch`, `inbox`, `draft`, `review`, `align`, `final`, `status`, `clean`. Long-form and Blender are Phase 3; `package` and `publish` are Phase 4.

## Setup (macOS)

```bash
brew install python@3.11 node ffmpeg
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
| `UNSPLASH_ACCESS_KEY` | `reel fetch` photos | unsplash.com/developers (free, 50 req/hour in demo mode) |

No Anthropic key? Use `reel script <slug> --manual` (below). Wikimedia Commons needs no key. Without Pexels/Unsplash keys, stock scenes go straight to the manual inbox.

## Workflow

```bash
reel new my-reel                 # scaffolds projects/my-reel/ and opens input/brief.md
# fill in the brief (topic, angle, formats, reel_count, language, source_urls)
# and/or drop articles into input/articles/ as .txt, .md or .html
reel script my-reel --manual     # writes script/prompt.md and copies it: paste into a new claude.ai chat,
                                 # save the whole reply as script/response.json, then run the same command again
                                 # (with ANTHROPIC_API_KEY set, plain `reel script my-reel` does it in one step)
# CHECK script/facts.md: every claim with its source; anything marked NOT in sources needs verifying
reel fetch my-reel               # Pexels -> Unsplash (or Wikimedia first for people/landmarks), charts via matplotlib
reel draft my-reel               # silent 540x960 preview at 150 wpm -> out/draft_reel_01.mp4
# manual scenes (screenshots, recent events) are listed in inbox/README.txt:
# drop sceneNN.jpg/png/mp4 into inbox/, then
reel draft my-reel --continue    # asks source + rights for each file, then re-renders
reel review my-reel              # http://127.0.0.1:7788 : Keep / Replace / Refetch each scene
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
