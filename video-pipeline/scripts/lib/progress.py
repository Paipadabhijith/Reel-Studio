"""Progress reporting that works both in the terminal and inside a Studio job.

A job installs a sink with `use_sink`; code deep in a stage calls `report(...)`
without needing a callback threaded through every function.
"""
from __future__ import annotations

import re
import subprocess
import sys
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Callable

# (fraction 0..1 or None, label) -> None
ProgressSink = Callable[[float | None, str], None]

_sink: ContextVar[ProgressSink | None] = ContextVar("progress_sink", default=None)

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
    proc = subprocess.Popen(
        cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1,
    )
    tail: list[str] = []
    assert proc.stdout is not None
    for raw in proc.stdout:
        line = raw.rstrip()
        if not line:
            continue
        tail = (tail + [line])[-30:]
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
    code = proc.wait()
    if not sink:
        sys.stdout.write("\n")
    if code != 0:
        raise RuntimeError("Remotion render failed:\n" + "\n".join(tail[-12:]))
