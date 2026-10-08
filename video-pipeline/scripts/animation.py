"""Animated stand-ins for scenes that have no picture.

Two engines: a fast Remotion graphic (type "animation") and a 3D Blender title (type "blender",
template "title3d"). Headlines are taken from the scene itself: the words you chose to stress,
else a number with its unit, else the first few meaningful words.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .lib import india
from .lib.schema import Overlay, Scene

STYLES = ("kinetic", "burst", "rings")
STYLE_LABELS = {"kinetic": "Kinetic words", "burst": "Burst", "rings": "Rings"}
TITLE3D = "title3d"
MAX_HEADLINE_WORDS = 3
SUBLINE_CHARS = 110

_SKIP = {"ek", "ki", "ka", "ke", "ko", "se", "me", "mein", "hai", "hain", "tha", "the", "thi", "ye", "yeh", "woh", "aur", "par",
         "is", "us", "to", "ab", "bhi", "hi", "na", "kya", "the", "a", "an", "of", "in", "on", "at", "and", "or", "is", "are", "was",
         "were", "this", "that", "it", "for", "with", "by", "from", "as", "be", "ne", "saal", "yaani", "sabse", "zyada", "kaafi", "bahut", "hum", "tak", "darj", "hui", "rahi", "raha", "rahe", "hua", "hue", "gaya", "gayi",
         "gaye", "pahunch", "pahuncha", "pahunchi", "aaya", "aayi", "aaye", "hota", "hoti", "rehta"}
_NUMBER = re.compile(r"(?<![\w.])(?:₹|rs\.?\s?)?\d[\d,]*(?:\.\d+)?\s?(?:%|percent|crore|cr|lakh|million|billion|days?|years?|km|mm)?", re.I)


def headline_for(scene: Scene) -> str:
    """A short headline for the scene: what it stresses, else its number, else its first strong words."""
    if scene.emphasis:
        return scene.emphasis[0].strip()
    text = " ".join(scene.text.split())
    m = _NUMBER.search(text)
    if m and any(c.isdigit() for c in m.group(0)):
        found = m.group(0).strip()
        if not found[-1].isdigit():          # already has its unit ("76%", "11 percent"): that is the headline
            return found
        tail = text[m.end():].split()
        word = next((w for w in tail[:2] if w.strip(".,;:!?").lower() not in _SKIP), "")
        return (found + (" " + word.strip(".,;:!?") if word else "")).strip()
    words = [w.strip(".,;:!?\"'()") for w in text.split()]
    strong = [w for w in words if w and w.lower() not in _SKIP and len(w) > 2]
    return " ".join(strong[:MAX_HEADLINE_WORDS]) or text[:30]


def keywords_for(scene: Scene, headline: str) -> list[str]:
    seen = {headline.lower()}
    out = []
    for e in scene.emphasis[1:]:
        if e.lower() not in seen:
            out.append(e.strip())
            seen.add(e.lower())
    return out[:3]


def subline_for(scene: Scene) -> str:
    text = " ".join(scene.text.split())
    return text if len(text) <= SUBLINE_CHARS else text[: SUBLINE_CHARS - 1].rsplit(" ", 1)[0] + "…"


def auto_params(scene: Scene, style: str | None = None) -> dict:
    """Parameters for an animation made from the scene's own words. Style varies with the scene id."""
    head = headline_for(scene)
    return {"style": style if style in STYLES else STYLES[scene.id % len(STYLES)], "headline": head,
            "subline": subline_for(scene), "keywords": keywords_for(scene, head)}


def title3d_params(scene: Scene) -> dict:
    head = headline_for(scene)
    return {"headline": head, "subline": subline_for(scene)[:70]}


# ---------------------------------------------------------------- choosing the engine
#
# The rule (deterministic, no AI call, every choice carries its reason):
#   1. Can the scene be drawn as an INFOGRAPHIC?  -> Remotion
#        one figure -> animated stat · several figures / year->value pairs -> animated chart
#        a list or a timeline -> tagged text · a comparison or trend -> animated text
#   2. Otherwise, is it GEOGRAPHY (it names an Indian state)?  -> Blender 3D map (a figure becomes a badge)
#   3. Otherwise, does it NEED MOTION (storms, floods, launches, journeys)?  -> Blender 3D title
#   4. Otherwise (no data, no motion)  -> Remotion animated text
# Blender is slow (about a second a frame), so a project gets at most MAX_3D_SCENES of them.

MAX_3D_SCENES = 3
MOTION_THRESHOLD = 2

_STRONG_MOTION = {"cyclone", "toofan", "tufan", "tsunami", "flood", "baadh", "earthquake", "bhukamp", "explosion", "dhamaka",
                  "rocket", "crash", "avalanche", "landslide", "hurricane", "storm", "volcano"}
_WEAK_MOTION = {"spread", "phail", "phaila", "phaili", "flow", "behta", "wave", "lehar", "fire", "aag", "launch", "flight", "udaan",
                "uda", "race", "daud", "collide", "takra", "journey", "safar", "yatra", "travel", "march", "rush", "surge", "burst",
                "monsoon", "baarish", "rain", "cross", "orbit", "spin", "ghoom", "fly", "chase", "sailab"}
_TREND = {"increase", "increased", "decrease", "decreased", "rise", "rose", "fall", "fell", "grow", "grew", "drop", "dropped", "badha",
          "badhi", "badhna", "ghata", "ghati", "ghatna", "kam", "zyada", "upar", "neeche", "record", "highest", "lowest", "double",
          "doguna", "half", "aadha", "compared", "mukable", "versus", "vs", "than", "se"}
_ORDINALS = {"pehla", "pehli", "doosra", "doosri", "teesra", "teesri", "chautha", "first", "second", "third", "fourth", "firstly",
             "secondly", "thirdly"}
_UNITS = r"%|percent|pratishat|crore|cr|lakh|million|billion|thousand|hazaar|rupees?|rs\.?|days?|din|years?|saal|weeks?|hafta|hours?|ghante|km|mm|cm|kg"
_NUM_WORDS = {"ek": 1, "one": 1, "do": 2, "two": 2, "teen": 3, "three": 3, "char": 4, "chaar": 4, "four": 4, "paanch": 5, "panch": 5, "five": 5,
              "chhe": 6, "che": 6, "six": 6, "saat": 7, "seven": 7, "aath": 8, "eight": 8, "nau": 9, "nine": 9, "das": 10, "ten": 10,
              "gyarah": 11, "eleven": 11, "barah": 12, "twelve": 12, "terah": 13, "thirteen": 13, "chaudah": 14, "fourteen": 14,
              "pandrah": 15, "fifteen": 15, "solah": 16, "sixteen": 16, "satrah": 17, "seventeen": 17, "atharah": 18, "eighteen": 18,
              "unnis": 19, "nineteen": 19, "bees": 20, "twenty": 20, "tees": 30, "thirty": 30, "chalis": 40, "forty": 40,
              "pachas": 50, "fifty": 50, "saath": 60, "sixty": 60, "sattar": 70, "seventy": 70, "assi": 80, "eighty": 80,
              "nabbe": 90, "ninety": 90, "sau": 100, "hundred": 100}
_PERCENT = re.compile(r"\b(" + "|".join(_NUM_WORDS) + r")\s+(?:percent|pratishat)\b", re.I)
_FIGURE = re.compile(r"(?<![\w.])(?:₹\s?)?(\d(?:[\d,]*\d)?(?:\.\d+)?)\s?(" + _UNITS + r")?(?![\w])", re.I)
_YEAR = re.compile(r"\b(19\d\d|20\d\d)\b")


@dataclass
class Figure:
    value: str          # as shown: "76%", "11%", "1,20,000 cr"
    number: float
    unit: str
    pos: int            # character position in the text
    end: int


@dataclass
class Decision:
    engine: str                     # "remotion" | "blender"
    kind: str                       # stat | chart | list | timeline | comparison | text | map | motion
    reason: str
    visual: dict = field(default_factory=dict)     # new type/template/params for the scene
    overlay: dict | None = None
    fallback_of: str | None = None  # set when Blender was wanted but the limit was reached

    @property
    def label(self) -> str:
        return f"{'Blender' if self.engine == 'blender' else 'Remotion'} · {self.kind}: {self.reason}"


def figures_in(text: str) -> list[Figure]:
    """Numbers with their units, including spelled-out percentages ("gyarah percent"). Years are not figures."""
    out: list[Figure] = []
    taken: list[tuple[int, int]] = []
    for m in _PERCENT.finditer(text):
        n = _NUM_WORDS[m.group(1).lower()]
        out.append(Figure(f"{n}%", float(n), "%", m.start(), m.end()))
        taken.append((m.start(), m.end()))
    for m in _FIGURE.finditer(text):
        if any(a <= m.start() < b for a, b in taken):
            continue
        raw, unit = m.group(1), (m.group(2) or "").strip()
        if not unit and _YEAR.fullmatch(raw):
            continue                                   # a bare year is a label, not a figure
        num = float(raw.replace(",", ""))
        if not unit and num < 10 and "," not in raw and "." not in raw:
            continue                                   # "scene 1", "2 baar": a count word, not a figure worth animating
        shown = raw + ("%" if unit.lower() in ("%", "percent", "pratishat") else (" " + unit if unit else ""))
        out.append(Figure(shown, num, "%" if unit.lower() in ("%", "percent", "pratishat") else unit, m.start(), m.end()))
    return sorted(out, key=lambda f: f.pos)


def _strong_words(chunk: str) -> list[str]:
    return [w for w in re.findall(r"[A-Za-z][A-Za-z']+", chunk) if w.lower() not in _SKIP and len(w) > 2]


def _label_near(text: str, fig: Figure) -> str:
    after = _strong_words(text[fig.end:fig.end + 40])
    before = _strong_words(text[max(0, fig.pos - 40):fig.pos])
    pick = (after[:1] or before[-1:])
    return pick[0].capitalize() if pick else ""


def _year_pairs(text: str) -> list[tuple[str, float, str]]:
    """(year, value, unit) where a number follows a year within a few words: "2019 mein 68 tha, 2024 mein 76"."""
    pairs = []
    years = list(_YEAR.finditer(text))
    for y, nxt in zip(years, years[1:] + [None]):
        stop = nxt.start() if nxt else len(text)
        for m in _FIGURE.finditer(text[y.end():stop]):
            raw = m.group(1)
            if not m.group(2) and _YEAR.fullmatch(raw):
                continue
            unit = (m.group(2) or "").strip()
            pairs.append((y.group(1), float(raw.replace(",", "")), "%" if unit.lower() in ("%", "percent", "pratishat") else unit))
            break
    return pairs


def _list_items(text: str) -> list[str]:
    """Items of a spoken list: comma-separated short phrases, or ordinal markers (pehla..., doosra...)."""
    ords = [m for m in re.finditer(r"\b(" + "|".join(_ORDINALS) + r")\b", text, re.I)]
    if len(ords) >= 2:
        parts = re.split(r"\b(?:" + "|".join(_ORDINALS) + r")\b[,:]?", text, flags=re.I)
        items = [" ".join(_strong_words(p)[:2]) for p in parts[1:]]
        return [i for i in items if i][:5]
    body = text.split(":", 1)[1] if ":" in text else text
    pieces = [p.strip(" .;:!?") for p in re.split(r",|\baur\b|\band\b", body) if p.strip(" .;:!?")]
    short = [p for p in pieces if 1 <= len(p.split()) <= 3]
    if len(pieces) >= 3 and len(short) >= 3:
        return [" ".join(p.split()[-2:]) for p in short][:5]
    return []


def _pair_with_states(text: str, figs: list[Figure]) -> list[tuple[Figure, str]]:
    """Each figure with the state named just before it ("Kerala ne 40 percent"), each state used once."""
    marks = []
    for code in india.find_states(text):
        name = india.STATES[code][0]
        for variant in {name, name.split(" &")[0], *[a for a, c in india.ALIASES.items() if c == code and len(a) > 4]}:
            i = text.lower().find(variant.lower())
            if i >= 0:
                marks.append((i, code))
                break
    out, used = [], set()
    for f in figs:
        before = [(f.pos - i, c) for i, c in marks if i < f.pos and c not in used and f.pos - i <= 45]
        if before:
            _, code = min(before)
            used.add(code)
            out.append((f, code))
    return out


def _motion_score(text: str) -> tuple[int, list[str]]:
    words = {w.lower() for w in re.findall(r"[A-Za-z]+", text)}
    strong, weak = sorted(words & _STRONG_MOTION), sorted(words & _WEAK_MOTION)
    return 2 * len(strong) + min(len(weak), 2), strong + weak


def _is_hook(scene: Scene, sf) -> bool:
    return bool(sf and any(r.hook_scene == scene.id for r in sf.reels))


def decide(scene: Scene, sf=None) -> Decision:
    """Pick the engine and the form for a scene that has no picture. See the rule above."""
    text = " ".join(scene.text.split())
    head = headline_for(scene)
    figs = figures_in(text)
    pairs = _year_pairs(text)
    years = [m.group(1) for m in _YEAR.finditer(text)]
    states = india.find_states(text)

    # 1. infographic -> Remotion ------------------------------------------------------------
    if len(pairs) >= 2:
        unit = next((u for _, _, u in pairs if u), "")
        kind = "line" if len(pairs) >= 4 else "bar"
        return Decision("remotion", "chart", f"{len(pairs)} values by year ({pairs[0][0]}–{pairs[-1][0]}): an animated {kind} chart",
                        {"type": "chart", "params": {"kind": kind, "title": head if not head[:1].isdigit() else "", "unit": unit,
                                                      "labels": [y for y, _, _ in pairs],
                                                      "values": [int(v) if v.is_integer() else v for _, v, _ in pairs]}})
    if len(figs) >= 2 and len(states) >= 2:
        by_state = _pair_with_states(text, figs)
        if len(by_state) >= 2:
            unit = next((f.unit for f, _ in by_state if f.unit), "")
            return Decision("remotion", "chart", f"{len(by_state)} states with a figure each ({', '.join(c for _, c in by_state)}): "
                            "an animated bar chart",
                            {"type": "chart", "params": {"kind": "bar", "title": "", "unit": unit,
                                                          "labels": [india.STATES[c][0].split(" &")[0] for _, c in by_state],
                                                          "values": [int(f.number) if f.number.is_integer() else f.number for f, _ in by_state]}})
    if len(figs) >= 2 and not states:
        labels = [_label_near(text, f) for f in figs]
        units = {f.unit for f in figs}
        if all(labels) and len(set(labels)) == len(labels) and len(units) == 1 and len(figs) <= 6:
            unit = next(iter(units))
            return Decision("remotion", "chart", f"{len(figs)} comparable figures ({', '.join(labels)}): an animated bar chart",
                            {"type": "chart", "params": {"kind": "bar", "title": "", "unit": unit, "labels": labels,
                                                          "values": [int(f.number) if f.number.is_integer() else f.number for f in figs]}})
    if len(figs) >= 1 and not states:
        f = figs[0]
        label = " ".join(_strong_words(text[f.end:f.end + 40])[:2]) or " ".join(_strong_words(text[:f.pos])[-2:])
        return Decision("remotion", "stat", f"one key figure ({f.value}): an animated count-up",
                        {"type": "stat", "params": {}}, {"type": "stat", "value": f.value, "label": label.strip() or None})
    items = _list_items(text)
    if len(items) >= 3:
        return Decision("remotion", "list", f"a list of {len(items)} points: tagged animated text",
                        {"type": "animation", "params": {"style": "kinetic", "headline": f"{len(items)} points" if not scene.emphasis else head,
                                                         "subline": subline_for(scene), "keywords": items}})
    if len(set(years)) >= 2:
        return Decision("remotion", "timeline", f"a timeline ({years[0]}–{years[-1]}): years shown as tags",
                        {"type": "animation", "params": {"style": "kinetic", "headline": f"{years[0]}–{years[-1]}", "subline": subline_for(scene),
                                                         "keywords": list(dict.fromkeys(years))[:5]}})
    words = {w.lower() for w in re.findall(r"[A-Za-z]+", text)}
    trend = sorted(words & (_TREND - {"se", "than", "vs"}))
    if trend and not states:
        return Decision("remotion", "comparison", f"a comparison or trend ({', '.join(trend[:2])}), no figures: animated text",
                        {"type": "animation", "params": auto_params(scene, "burst")})

    # 2. geography -> Blender map ------------------------------------------------------------
    if states:
        overlay = {"type": "stat", "value": figs[0].value, "label": _label_near(text, figs[0]) or None} if figs else None
        return Decision("blender", "map", f"names {', '.join(states)}: a 3D map (the places are the point)",
                        {"type": "blender", "template": "india_map", "params": {"highlight_states": states, "camera": "top_down_tilt"}},
                        overlay)

    # 3. needs motion -> Blender title ---------------------------------------------------------
    score, why = _motion_score(text)
    if _is_hook(scene, sf):
        score += 1 if why else 0                       # the opening scene gets the benefit of the doubt, but only with a motion cue
    if score >= MOTION_THRESHOLD:
        return Decision("blender", "motion", f"motion scene ({', '.join(why[:3])}) with nothing to chart: a 3D title",
                        {"type": "blender", "template": TITLE3D, "params": title3d_params(scene)})

    # 4. nothing to chart, nothing moving ---------------------------------------------------------
    return Decision("remotion", "text", "no figures and no motion: animated text",
                    {"type": "animation", "params": auto_params(scene)})


def _count_3d(sf, skip_id: int) -> int:
    return sum(1 for s in (sf.scenes if sf else []) if s.id != skip_id and s.visual.type == "blender")


def decide_with_limit(scene: Scene, sf=None) -> Decision:
    """`decide`, but keep the number of slow Blender scenes in the project to MAX_3D_SCENES."""
    d = decide(scene, sf)
    if d.engine == "blender" and _count_3d(sf, scene.id) >= MAX_3D_SCENES:
        plain = Decision("remotion", "text", f"{d.kind} scene, but the project already has {MAX_3D_SCENES} 3D scenes "
                         "(each takes minutes to render): animated text instead",
                         {"type": "animation", "params": auto_params(scene)}, fallback_of=d.kind)
        return plain
    return d


def apply(scene: Scene, d: Decision) -> Scene:
    """Write a decision into the scene, remembering what the scene was before."""
    v = scene.visual
    if v.type not in ("animation", "stat", "chart") and not (v.type == "blender"):
        v.downgraded_from = v.downgraded_from or v.type
    v.type = d.visual["type"]
    v.template = d.visual.get("template")
    v.params = {**d.visual.get("params", {}), "why": d.label}
    v.file = None
    if d.overlay:
        scene.overlay = Overlay(**d.overlay)
    return scene


def to_animation(scene: Scene, engine: str = "remotion", sf=None) -> Scene:
    """Turn a scene into an animation, remembering what it was so a later refetch can restore it.

    engine: "auto" lets `decide_with_limit` choose; "remotion" or "blender" force the simple graphic or 3D title.
    """
    if engine == "auto":
        return apply(scene, decide_with_limit(scene, sf))
    v = scene.visual
    if v.type not in ("animation",) and not (v.type == "blender" and v.template == TITLE3D):
        v.downgraded_from = v.downgraded_from or v.type
    if engine == "blender":
        v.type, v.template, v.params = "blender", TITLE3D, title3d_params(scene)
    else:
        v.type, v.template, v.params = "animation", None, auto_params(scene)
    v.file = None
    return scene


def describe(scene: Scene) -> str:
    v = scene.visual
    if v.params.get("why"):
        return str(v.params["why"])
    if v.type == "animation":
        return f"{STYLE_LABELS.get(v.params.get('style'), 'Animated graphic')}: “{v.params.get('headline', '')}”"
    if v.type == "blender" and v.template == TITLE3D:
        return f"3D title: “{v.params.get('headline', '')}”"
    return ""
