"""Indian states and union territories: 2-letter codes, names, and boundary data for the Blender map.

Boundaries are downloaded on first use (not stored in this repo) from udit-001/india-maps-data,
one GeoJSON per state/UT with Telangana, Ladakh and the merged Dadra & Nagar Haveli and Daman & Diu.
"""
from __future__ import annotations

import re
from pathlib import Path

import httpx

from .config import REPO_ROOT
from .india_codes import STATES

DATA_DIR = REPO_ROOT / "blender" / "data" / "states"
SOURCE_URL = "https://raw.githubusercontent.com/udit-001/india-maps-data/main/geojson/states/{slug}.geojson"

# other spellings people (and models) use
ALIASES = {
    "OR": "OD", "TG": "TS", "UT": "UK", "UA": "UK", "CT": "CG", "DD": "DH", "DN": "DH", "DNH": "DH",
    "JAMMUKASHMIR": "JK", "ORISSA": "OD", "UTTARANCHAL": "UK", "PONDICHERRY": "PY",
    "DADRANAGARHAVELI": "DH", "DAMANDIU": "DH", "DAMANDDIU": "DH",
    "ANDAMANNICOBAR": "AN", "ANDAMANNICOBARISLANDS": "AN", "NCTDELHI": "DL", "NEWDELHI": "DL",
}


def _key(s: str) -> str:
    return re.sub(r"[^A-Z]", "", s.upper().replace("&", "AND").replace("AND", ""))


_BY_NAME = {_key(name): code for code, (name, _) in STATES.items()}
_BY_NAME.update({_key(slug): code for code, (_, slug) in STATES.items()})


def resolve_state(value: str) -> str | None:
    """'ka', 'Karnataka', 'tamil nadu', 'TG', 'Orissa' -> canonical 2-letter code, or None."""
    raw = (value or "").strip()
    if raw.upper() in STATES:
        return raw.upper()
    if raw.upper() in ALIASES:
        return ALIASES[raw.upper()]
    k = _key(raw)
    return ALIASES.get(k) or _BY_NAME.get(k)


def resolve_states(values: list[str]) -> tuple[list[str], list[str]]:
    """(codes in order without duplicates, unrecognised inputs)."""
    codes, bad = [], []
    for v in values or []:
        c = resolve_state(str(v))
        if c is None:
            bad.append(str(v))
        elif c not in codes:
            codes.append(c)
    return codes, bad


def state_file(code: str, data_dir: Path = DATA_DIR) -> Path:
    return data_dir / f"{STATES[code][1]}.geojson"


def missing_files(data_dir: Path = DATA_DIR) -> list[str]:
    return [c for c in STATES if not state_file(c, data_dir).exists()]


def fetch_boundaries(data_dir: Path = DATA_DIR, http: httpx.Client | None = None, log=print) -> int:
    """Download any state files we don't have yet. Returns how many were fetched."""
    todo = missing_files(data_dir)
    if not todo:
        return 0
    data_dir.mkdir(parents=True, exist_ok=True)
    own = http is None
    http = http or httpx.Client(timeout=60, follow_redirects=True)
    log(f"india map: downloading {len(todo)} state boundary files (one-time, about 40 MB)")
    try:
        for code in todo:
            slug = STATES[code][1]
            r = http.get(SOURCE_URL.format(slug=slug))
            r.raise_for_status()
            if '"coordinates"' not in r.text[:200000] and '"coordinates"' not in r.text:
                raise ValueError(f"{slug}: not a GeoJSON geometry file")
            tmp = state_file(code, data_dir).with_suffix(".part")
            tmp.write_text(r.text)
            tmp.replace(state_file(code, data_dir))
    finally:
        if own:
            http.close()
    return len(todo)


SIMPLE_FILE = REPO_ROOT / "blender" / "data" / "india_states_simple.json"
GAP_DEG = 0.05      # shrink each state a little so borders show as thin dark lines
SIMPLIFY_DEG = 0.02  # about 2 km; plenty for a full-screen map


def build_simplified(data_dir: Path = DATA_DIR, out: Path = SIMPLE_FILE, log=print) -> Path:
    """Merge each state's district shapes into one clean outline and simplify it.

    The downloaded files hold many adjacent district polygons per state; filling those directly makes
    Blender render patchy surfaces. Output: {code: GeoJSON geometry} used by blender/build_india_map.py.
    """
    from shapely.geometry import mapping, shape
    from shapely.ops import unary_union
    from shapely.validation import make_valid
    import json

    result = {}
    for code in STATES:
        geo = json.loads(state_file(code, data_dir).read_text())
        feats = geo["features"] if geo.get("type") == "FeatureCollection" else [geo]
        parts = []
        for f in feats:
            g = shape(f["geometry"] if "geometry" in f else f)
            parts.append(g if g.is_valid else make_valid(g))
        merged = unary_union(parts)
        shrunk = merged.buffer(-GAP_DEG, join_style=2)
        merged = shrunk if not shrunk.is_empty and shrunk.area > merged.area * 0.5 else merged  # tiny UTs keep their size
        merged = merged.simplify(SIMPLIFY_DEG, preserve_topology=True)
        if merged.geom_type == "GeometryCollection":
            merged = unary_union([g for g in merged.geoms if g.geom_type in ("Polygon", "MultiPolygon")])
        result[code] = mapping(merged)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, separators=(",", ":")))
    log(f"india map: merged and simplified {len(result)} states -> {out.name} ({out.stat().st_size // 1024} KB)")
    return out
