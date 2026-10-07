"""Background jobs for the Studio: one at a time (8 GB RAM), with live log and progress."""
from __future__ import annotations

import itertools
import queue
import threading
import time
import traceback
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .lib.notify import notify
from .lib.progress import use_sink

# fn(log) -> optional result message
JobFn = Callable[[Callable[[str], None]], "str | None"]

_ids = itertools.count(1)


@dataclass
class Job:
    slug: str
    step: str
    label: str
    fn: JobFn
    log_dir: Path | None = None
    id: int = field(default_factory=lambda: next(_ids))
    status: str = "queued"  # queued | running | done | failed
    created: float = field(default_factory=time.time)
    started: float | None = None
    ended: float | None = None
    lines: deque = field(default_factory=lambda: deque(maxlen=500))
    progress: float | None = None
    progress_label: str = ""
    result: str | None = None
    error: str | None = None

    def log(self, msg: str) -> None:
        for line in str(msg).splitlines() or [""]:
            self.lines.append(f"{time.strftime('%H:%M:%S')}  {line}")

    def to_dict(self, tail: int = 200) -> dict:
        return {
            "id": self.id, "slug": self.slug, "step": self.step, "label": self.label, "status": self.status,
            "created": self.created, "started": self.started, "ended": self.ended,
            "elapsed": round((self.ended or time.time()) - self.started, 1) if self.started else 0,
            "progress": self.progress, "progress_label": self.progress_label,
            "result": self.result, "error": self.error, "lines": list(self.lines)[-tail:],
        }


class Runner:
    def __init__(self, notify_done: bool = True):
        self.jobs: dict[int, Job] = {}
        self.q: queue.Queue[Job] = queue.Queue()
        self.lock = threading.Lock()
        self.notify_done = notify_done
        self.thread = threading.Thread(target=self._work, daemon=True, name="studio-jobs")
        self.thread.start()

    def submit(self, slug: str, step: str, label: str, fn: JobFn, log_dir: Path | None = None) -> Job:
        with self.lock:
            for j in self.jobs.values():
                if j.slug == slug and j.step == step and j.status in ("queued", "running"):
                    return j  # same step already pending: don't run it twice
            job = Job(slug, step, label, fn, log_dir)
            self.jobs[job.id] = job
        job.log(f"queued: {label}")
        self.q.put(job)
        return job

    def active(self) -> list[Job]:
        return sorted((j for j in self.jobs.values() if j.status in ("queued", "running")), key=lambda j: j.id)

    def recent(self, slug: str | None = None, n: int = 10) -> list[Job]:
        js = [j for j in self.jobs.values() if slug is None or j.slug == slug]
        return sorted(js, key=lambda j: -j.id)[:n]

    def busy_with(self, slug: str) -> Job | None:
        return next((j for j in self.active() if j.slug == slug), None)

    def wait_idle(self, timeout: float = 30) -> None:
        end = time.time() + timeout
        while self.active() and time.time() < end:
            time.sleep(0.05)

    def _work(self) -> None:
        while True:
            job = self.q.get()
            job.status, job.started = "running", time.time()
            job.log(f"started: {job.label}")

            def sink(frac, label, job=job):
                job.progress = frac
                job.progress_label = label

            try:
                with use_sink(sink):
                    job.result = job.fn(job.log)
                job.status = "done"
                job.progress = 1.0
                job.log(f"done in {time.time() - job.started:.0f}s" + (f": {job.result}" if job.result else ""))
            except Exception as e:  # report every failure in the UI rather than killing the worker
                job.status = "failed"
                job.error = f"{type(e).__name__}: {e}"
                job.log(f"FAILED: {job.error}")
                job.log(traceback.format_exc(limit=6))
            finally:
                job.ended = time.time()
                self._save_log(job)
                if self.notify_done:
                    notify(f"{job.slug}: {job.label}", "done" if job.status == "done" else f"failed: {job.error}")
                self.q.task_done()

    @staticmethod
    def _save_log(job: Job) -> None:
        if not job.log_dir:
            return
        try:
            job.log_dir.mkdir(parents=True, exist_ok=True)
            stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(job.started or time.time()))
            (job.log_dir / f"{stamp}-{job.step}.log").write_text("\n".join(job.lines) + "\n")
        except OSError:
            pass
