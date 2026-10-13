"""The creator's voice profile (shared/voice.md), included in every script prompt once it is filled in."""
from __future__ import annotations

import re
from pathlib import Path

from .config import REPO_ROOT

VOICE_FILE = REPO_ROOT / "shared" / "voice.md"
_COMMENT = re.compile(r"<!--.*?-->", re.S)


def filled(text: str) -> str | None:
    """The voice text without the template's hints, or None while nothing has been written outside them."""
    body = _COMMENT.sub("", text)
    lines = [l.rstrip() for l in body.splitlines()]
    content = [l for l in lines if l.strip() and not l.lstrip().startswith("#")]
    if not content:
        return None
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def read_voice(path: Path = VOICE_FILE) -> str | None:
    return filled(path.read_text()) if path.exists() else None
