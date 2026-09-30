"""Paths, env loading and the global heavy-job lock."""
from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path

from dotenv import load_dotenv
from filelock import FileLock, Timeout

REPO_ROOT = Path(__file__).resolve().parents[2]
PROJECTS_DIR = REPO_ROOT / "projects"
TEMPLATE_DIR = REPO_ROOT / "template"
BRAND_FILE = REPO_ROOT / "shared" / "brand.json"

load_dotenv(REPO_ROOT / ".env")

REMOTION_CONCURRENCY = 2  # M1 8 GB cap
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "mlx-community/whisper-small-mlx")
TARGET_LUFS = -14

WHISPER_LANG = {"en": "en", "hi": "hi", "hinglish": "hi"}


def project_dir(slug: str) -> Path:
    p = PROJECTS_DIR / slug
    if not p.exists():
        raise FileNotFoundError(f"project {slug!r} not found at {p}")
    return p


@contextmanager
def heavy_lock(name: str, timeout: float = 0):
    """Only one of transcription / Blender / Remotion runs at a time (8 GB RAM)."""
    lock = FileLock(str(REPO_ROOT / ".heavy.lock"), timeout=timeout)
    try:
        lock.acquire()
    except Timeout:
        raise RuntimeError(f"another heavy job is running; cannot start {name!r}")
    try:
        yield
    finally:
        lock.release()
