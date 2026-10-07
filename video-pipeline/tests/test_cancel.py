"""Cancel must really stop work: queued jobs at once, running jobs and their child processes within a moment."""
import subprocess
import threading
import time

import pytest

from scripts.jobs import Runner
from scripts.lib import progress
from scripts.lib.progress import JobCancelled, check_cancel, run_remotion, use_cancel


def wait_for(cond, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.02)
    return False


def test_queued_job_is_cancelled_without_running():
    r = Runner(notify_done=False)
    gate = threading.Event()
    ran = []
    first = r.submit("p", "a", "blocker", lambda log: gate.wait(5) and None)
    second = r.submit("p", "b", "never runs", lambda log: ran.append(1))
    assert wait_for(lambda: first.status == "running")
    assert r.cancel(second.id) and second.status == "cancelled"
    gate.set()
    r.wait_idle(5)
    assert ran == [] and first.status == "done"
    assert r.cancel(second.id) is False, "already finished"


def test_running_job_stops_at_its_next_check():
    r = Runner(notify_done=False)
    started = threading.Event()

    def work(log):
        started.set()
        for _ in range(500):
            check_cancel()
            time.sleep(0.01)
        return "finished"

    job = r.submit("p", "w", "long work", work)
    assert started.wait(2)
    assert r.cancel(job.id)
    assert wait_for(lambda: job.status == "cancelled")
    assert any("cancelled" in l for l in job.lines)


def test_cancel_kills_a_silent_child_process_and_its_children(tmp_path):
    r = Runner(notify_done=False)
    pidfile = tmp_path / "pids"
    # a shell that starts a grandchild, prints nothing, and would run for 60 s
    cmd = ["sh", "-c", f"sleep 60 & echo $! > {pidfile}; wait"]

    def work(log):
        run_remotion(cmd, tmp_path, log)

    job = r.submit("p", "render", "silent render", work)
    assert wait_for(lambda: pidfile.exists() and pidfile.read_text().strip())
    grandchild = int(pidfile.read_text())
    t0 = time.time()
    r.cancel(job.id)
    assert wait_for(lambda: job.status == "cancelled", 6), job.lines
    assert time.time() - t0 < 6
    assert wait_for(lambda: subprocess.run(["kill", "-0", str(grandchild)], capture_output=True).returncode != 0, 3), \
        "the grandchild process must be gone too"


def test_failed_child_still_reports_its_output(tmp_path):
    with pytest.raises(RuntimeError, match="boom"):
        with use_cancel(threading.Event()):
            run_remotion(["sh", "-c", "echo 'Error: boom'; exit 3"], tmp_path, lambda *_: None)


def test_check_cancel_is_a_noop_outside_a_job():
    check_cancel()
    assert progress.cancelled() is False
