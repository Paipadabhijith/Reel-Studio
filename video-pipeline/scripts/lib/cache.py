"""Content-hash caching under <project>/build/cache/."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Iterable


def hash_inputs(*parts: object, files: Iterable[Path] = ()) -> str:
    h = hashlib.sha256()
    for p in parts:
        h.update(json.dumps(p, sort_keys=True, default=str).encode())
    for f in files:
        f = Path(f)
        h.update(f.name.encode())
        if f.exists():
            with f.open("rb") as fh:
                for chunk in iter(lambda: fh.read(1 << 20), b""):
                    h.update(chunk)
    return h.hexdigest()[:16]


def _stamp(cache_dir: Path, stage: str) -> Path:
    return cache_dir / f"{stage}.hash"


def is_fresh(cache_dir: Path, stage: str, digest: str, outputs: Iterable[Path]) -> bool:
    stamp = _stamp(cache_dir, stage)
    return (
        stamp.exists()
        and stamp.read_text().strip() == digest
        and all(Path(o).exists() for o in outputs)
    )


def mark(cache_dir: Path, stage: str, digest: str) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    _stamp(cache_dir, stage).write_text(digest)
