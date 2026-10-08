"""`reel` CLI."""
from __future__ import annotations

import typer

from .lib.config import PROJECTS_DIR, heavy_lock, project_dir
from .lib.schema import load_scenes

app = typer.Typer(no_args_is_help=True, help="Automated video pipeline")


def _log(msg: str) -> None:
    typer.echo(msg)


def _not_yet(name: str, phase: int) -> None:
    typer.echo(f"`reel {name}` arrives in Phase {phase}.", err=True)
    raise typer.Exit(2)


@app.command()
def new(slug: str, language: str = typer.Option("hinglish", help="en / hi / hinglish"),
        no_edit: bool = typer.Option(False, help="Do not open brief.md in $EDITOR")):
    """Scaffold a project folder."""
    from .new_project import scaffold

    root = scaffold(slug, language, open_brief=not no_edit)
    _log(f"created {root}")


@app.command()
def final(
    slug: str,
    video: str = typer.Option(None, "--video", "-v", help="One video: a reel id (reel_01) or 'long'. Default: every video that has a recording"),
):
    """Align recorded narration, then render the final video(s)."""
    from .align_audio import align
    from .lib.targets import audio_exists, get_target, list_targets
    from .render_final import render_target

    proj = project_dir(slug)
    sf = load_scenes(proj / "script" / "scenes.json")
    try:
        targets = [get_target(sf, video)] if video else [t for t in list_targets(sf) if audio_exists(proj, t)]
        if not targets:
            raise FileNotFoundError("no narration recordings yet; record at least one video first")
        for t in targets:
            tl = align(proj, sf, t.id, _log)
            out = render_target(proj, sf, tl, t, _log)
            _log(f"done: {out}")
    except (FileNotFoundError, RuntimeError, ValueError) as e:
        typer.echo(f"error: {e}", err=True)
        raise typer.Exit(1)


@app.command()
def align(slug: str, video: str = typer.Option(None, "--video", "-v", help="reel id or 'long'")):
    """Only run audio alignment and tone analysis."""
    from .align_audio import align as run

    proj = project_dir(slug)
    try:
        tl = run(proj, load_scenes(proj / "script" / "scenes.json"), video, _log)
    except (FileNotFoundError, ValueError) as e:
        typer.echo(f"error: {e}", err=True)
        raise typer.Exit(1)
    _log(f"timeline: {len(tl.scenes)} scenes, {tl.duration_s}s")


@app.command()
def status():
    """List projects and their stage."""
    from .lib.state import project_state, stage_label

    if not PROJECTS_DIR.exists():
        return
    for p in sorted(PROJECTS_DIR.iterdir()):
        if not (p / "script").is_dir():
            continue
        typer.echo(f"{p.name:30s} {stage_label(project_state(p))}")


@app.command()
def clean(slug: str, cache_only: bool = typer.Option(False, "--cache-only")):
    """Remove build artifacts."""
    import shutil

    proj = project_dir(slug)
    target = proj / "build" / "cache" if cache_only else proj / "build"
    with heavy_lock("clean"):
        shutil.rmtree(target, ignore_errors=True)
    for d in ("build/blender", "build/chapters", "build/cache"):
        (proj / d).mkdir(parents=True, exist_ok=True)
    _log(f"cleaned {target}")


def _ask_rights(scene, filename: str) -> tuple[str, str]:
    from .manual_inbox import RIGHTS

    typer.echo(f"\n{filename} -> scene {scene.id}: {scene.text}")
    while True:
        rights = typer.prompt(f"  rights ({' / '.join(RIGHTS)})").strip().lower()
        if rights in RIGHTS:
            break
        typer.echo(f"  please type one of: {', '.join(RIGHTS)}")
    source = typer.prompt("  source / credit (e.g. 'PIB press release, 12 Sep')", default="", show_default=False)
    return rights, source


@app.command()
def script(
    slug: str,
    force: bool = typer.Option(False, help="Ignore the cache and write the script again"),
    manual: bool = typer.Option(False, help="No API key: paste the prompt into claude.ai, then import the reply"),
):
    """Brief + articles -> scenes.json, script.md, hooks.md, facts.md (Claude API, or --manual via claude.ai)."""
    from .generate_script import ScriptError, generate, generate_manual

    proj = project_dir(slug)
    try:
        if manual:
            if generate_manual(proj, force=force, log=_log) is None:
                return
        else:
            generate(proj, force=force, log=_log)
    except ScriptError as e:
        typer.echo(f"error: {e}", err=True)
        raise typer.Exit(1)
    _log(f"next: check {proj / 'script' / 'facts.md'}, then `reel fetch {slug}`")


@app.command()
def fetch(
    slug: str,
    scene: list[int] = typer.Option(None, "--scene", help="Only these scene ids (repeatable)"),
    force: bool = typer.Option(False, help="Re-download even if an asset exists"),
):
    """Auto-fetch visuals (Pexels, Pixabay, Unsplash, Wikimedia) and list manual gaps."""
    from .fetch_assets import fetch as run

    proj = project_dir(slug)
    summary = run(proj, only=scene or None, force=force, log=_log)
    _log("fetch: " + ", ".join(f"{v} {k}" for k, v in sorted(summary.items())))


@app.command()
def inbox(slug: str, watch: bool = typer.Option(False, help="Keep watching until every manual scene is filled")):
    """Move files dropped in inbox/ (sceneNN.jpg|png|mp4) into assets/."""
    from . import manual_inbox

    proj = project_dir(slug)
    if watch:
        _log(f"watching {proj / 'inbox'} (Ctrl-C to stop)")
        manual_inbox.watch(proj, _ask_rights, log=_log)
    else:
        done = manual_inbox.ingest(proj, _ask_rights, log=_log)
        left = manual_inbox.pending(proj, load_scenes(proj / "script" / "scenes.json"))
        _log(f"inbox: {len(done)} added, {len(left)} still needed")


@app.command()
def draft(
    slug: str,
    cont: bool = typer.Option(False, "--continue", help="Ingest inbox/ first, then re-render"),
    video: str = typer.Option(None, "--video", "-v", help="reel id or 'long' (default: all)"),
):
    """Render draft videos (timed at 150 wpm, no audio). Missing manual scenes show as labelled cards."""
    from .draft import draft as run

    proj = project_dir(slug)
    try:
        outs, missing = run(proj, cont=cont, ask=_ask_rights, log=_log, only=video)
    except RuntimeError as e:
        typer.echo(f"error: {e}", err=True)
        raise typer.Exit(1)
    for o in outs:
        _log(f"draft: {o}")
    if missing:
        _log(f"\npaused: {len(missing)} manual scene(s) still need assets: {', '.join(map(str, missing))}")
        _log(f"see {proj / 'inbox' / 'README.txt'}; add files there, then run `reel draft {slug} --continue`")


@app.command()
def studio(port: int = typer.Option(7788)):
    """Web UI at http://127.0.0.1:7788 : start projects, run every step, watch progress."""
    from .studio import serve

    serve(port)


@app.command()
def review(slug: str, port: int = typer.Option(7788)):
    """Open the Studio's scene review page (Keep / Replace / Refetch) for one project."""
    from .studio import serve

    project_dir(slug)
    serve(port, f"/p/{slug}/review/")


@app.command()
def music(
    slug: str,
    video: str = typer.Option(None, "--video", "-v", help="reel id or 'long' (default: the first video)"),
    file: str = typer.Option(None, "--file", help="Music file to add"),
    title: str = typer.Option("", help="Track title"),
    source: str = typer.Option("", help="Where it came from (required with --file)"),
    license: str = typer.Option("", help="royalty-free | cc-by | public-domain | licensed | own (required with --file)"),
    url: str = typer.Option("", help="Link to the track"),
    volume: float = typer.Option(-22.0, help="dB under the narration"),
    no_duck: bool = typer.Option(False, "--no-duck", help="Keep the music level while you speak"),
    clear: bool = typer.Option(False, "--clear", help="Remove the music from this video"),
):
    """Optional background music for a video (omit --file to just show what is set)."""
    from pathlib import Path

    from . import music as music_mod
    from .lib.targets import get_target

    proj = project_dir(slug)
    sf = load_scenes(proj / "script" / "scenes.json")
    try:
        target = get_target(sf, video)
        if clear:
            _log("removed" if music_mod.clear(proj, target) else "no music was set")
        elif file:
            t = music_mod.set_track(proj, target, Path(file).expanduser(), title=title, source=source, license=license,
                                    url=url, volume_db=volume, duck=not no_duck)
            _log(f"{target.id}: added “{t.title}” ({t.volume_db:g} dB, {'ducked' if t.duck else 'steady'}). {t.credit}")
        else:
            t = music_mod.get(proj, target)
            _log(f"{target.id}: " + (f"“{t.title}” · {t.source} · {t.license} · {t.volume_db:g} dB" if t else "no music (voice only)"))
    except (ValueError, music_mod.MusicError) as e:
        typer.echo(f"error: {e}", err=True)
        raise typer.Exit(1)


def _stub(name: str, phase: int) -> None:
    def cmd(slug: str = typer.Argument(None)) -> None:
        _not_yet(name, phase)

    app.command(name, help=f"(Phase {phase})")(cmd)


for _name, _phase in [("package", 4), ("publish", 4)]:
    _stub(_name, _phase)

if __name__ == "__main__":
    app()
