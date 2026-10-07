"""Progress reporting that works both in the terminal and inside a Studio job.

A job installs a sink with `use_sink`; code deep in a stage calls `report(...)`
without needing a callback threaded through every function.
"""
from __future__ import annotations

import os
import re
import signal
import subprocess
import sys
import threading
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Callable

# (fraction 0..1 or None, label) -> None
ProgressSink = Callable[[float | None, str], None]

_sink: ContextVar[ProgressSink | None] = ContextVar("progress_sink", default=None)
_cancel: ContextVar[threading.Event | None] = ContextVar("cancel_event", default=None)


class JobCancelled(Exception):
    """Raised inside a job when the user pressed Cancel."""


@contextmanager
def use_cancel(event: threading.Event):
    token = _cancel.set(event)
    try:
        yield
    finally:
        _cancel.reset(token)


def cancelled() -> bool:
    ev = _cancel.get()
    return bool(ev and ev.is_set())


def check_cancel() -> None:
    """Call between steps of a job: stops it promptly if the user cancelled."""
    if cancelled():
        raise JobCancelled()


@contextmanager
def watch_cancel(proc: subprocess.Popen):
    """While the block runs, stop `proc` (and its children) as soon as the job is cancelled, even if it is silent."""
    done = threading.Event()
    event = _cancel.get()  # a new thread does not inherit context variables, so capture the flag here

    def watcher():
        while not done.wait(0.2):
            if event is not None and event.is_set():
                kill_tree(proc)
                return

    t = threading.Thread(target=watcher, daemon=True)
    t.start()
    try:
        yield
    finally:
        done.set()
        t.join(timeout=2)


def kill_tree(proc: subprocess.Popen) -> None:
    """Stop a child process and everything it started (Remotion starts node and Chrome)."""
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass

REMOTION_PROGRESS = re.compile(r"^(Rendered|Stitched|Encoded)\s+(\d+)/(\d+)")


@contextmanager
def use_sink(sink: ProgressSink):
    token = _sink.set(sink)
    try:
        yield
    finally:
        _sink.reset(token)


def report(fraction: float | None, label: str) -> None:
    sink = _sink.get()
    if sink:
        sink(fraction, label)


def run_remotion(cmd: list[str], cwd: Path, log=print) -> None:
    """Run a Remotion CLI command, turning its 'Rendered x/y' lines into progress."""
    sink = _sink.get()
    check_cancel()
    proc = subprocess.Popen(
        cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1,
        start_new_session=True,  # own process group, so Cancel can stop the whole tree
    )
    tail: list[str] = []
    assert proc.stdout is not None
    with watch_cancel(proc):
        _read_remotion(proc, sink, tail, log)
    if cancelled():
        raise JobCancelled()
    code = proc.wait()
    if not sink:
        sys.stdout.write("\n")
    if code != 0:
        raise RuntimeError("Remotion render failed:\n" + "\n".join(tail[-12:]))


def _read_remotion(proc, sink, tail: list, log) -> None:
    for raw in proc.stdout:
        line = raw.rstrip()
        if not line:
            continue
        tail.append(line)
        del tail[:-30]
        m = REMOTION_PROGRESS.match(line)
        if m:
            done, total = int(m.group(2)), int(m.group(3))
            phase = m.group(1).lower()
            # rendering frames is most of the work; stitching/encoding is the last stretch
            frac = 0.9 * done / total if phase == "rendered" else 0.9 + 0.1 * done / total
            if sink:
                sink(frac, f"{phase} {done}/{total} frames")
            else:
                sys.stdout.write(f"\r  {phase} {done}/{total}")
                sys.stdout.flush()
            continue
        if "rror" in line:
            if not sink:
                sys.stdout.write("\n")
            log(f"  remotion: {line}")
