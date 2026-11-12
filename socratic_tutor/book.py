"""The student's NCERT book, shown next to the tutor's question: a real excerpt, the section's formulas and its figure.

Everything here is worked out by code from the textbook itself, with no model call:

- excerpts: sentences copied from the indexed NCERT section (.index/chunks.json, built from the PDFs in data/),
  with the PDF's split words joined again ("for mation" -> "formation");
- figures: the numbered figures cropped from the same PDFs (data/book/figures/, made by scripts/extract_figures.py);
- formulas: the key equations of each section with their NCERT equation numbers (data/book/formulas.json),
  written out by hand because the PDF text breaks fractions apart.

Two uses:
- book_card(): the "From your NCERT book" card under a tutor reply, for the section the tutor cited;
- lesson(): "Learn this topic from the start". What it shows depends on the student's mastery of the topic:
  the basics and the main figure for a new topic, the formulas and a worked step for a topic in progress, and
  the next topic once this one is mastered.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from functools import lru_cache
from typing import Any

from socratic_tutor import config

BOOK_DIR = config.DATA_DIR / "book"
FIGURE_URL = "/book/figures/"

# The NCERT sections that teach each topic in the concept graph, the main one first.
CONCEPT_SECTIONS: dict[str, list[str]] = {
    "concept_reflection_laws": ["9.1"],
    "concept_spherical_mirrors": ["9.2"],
    "concept_concave_ray_diagrams": ["9.2.1", "9.2.2"],
    "concept_convex_ray_diagrams": ["9.2.2", "9.2.1"],
    "concept_sign_convention": ["9.2.3"],
    "concept_mirror_formula": ["9.2.4"],
    "concept_refraction_laws": ["9.3", "9.3.1"],
    "concept_refractive_index": ["9.3.2"],
    "concept_lens_image_formation": ["9.3.3", "9.3.5"],
    "concept_lens_formula": ["9.3.7"],
    "concept_lens_power": ["9.3.8"],
    "concept_human_eye_structure": ["10.1"],
    "concept_accommodation": ["10.1.1"],
    "concept_myopia": ["10.2"],
    "concept_hypermetropia": ["10.2"],
    "concept_presbyopia": ["10.2"],
    "concept_prism_refraction": ["10.3"],
    "concept_dispersion": ["10.4"],
    "concept_rainbow_formation": ["10.4"],
    "concept_atmospheric_refraction": ["10.5"],
    "concept_scattering": ["10.6.2", "10.6", "10.6.1"],
    "concept_electric_current": ["11.1"],
    "concept_potential_difference": ["11.2"],
    "concept_ohms_law": ["11.4"],
    "concept_factors_resistance": ["11.5"],
    "concept_series_combination": ["11.6.1"],
    "concept_parallel_combination": ["11.6.2"],
    "concept_resistors_combination": ["11.6", "11.6.1", "11.6.2"],
    "concept_joules_heating": ["11.7"],
    "concept_electric_power": ["11.8"],
}

# The figure that best shows each topic (most topics have one; scattering and power have none in the book).
CONCEPT_FIGURES: dict[str, list[str]] = {
    "concept_reflection_laws": [],
    "concept_spherical_mirrors": ["9.2"],
    "concept_concave_ray_diagrams": ["9.7"],
    "concept_convex_ray_diagrams": ["9.8"],
    "concept_sign_convention": ["9.9"],
    "concept_mirror_formula": ["9.9"],
    "concept_refraction_laws": ["9.10"],
    "concept_refractive_index": ["9.11"],
    "concept_lens_image_formation": ["9.12", "9.16"],
    "concept_lens_formula": ["9.16"],
    "concept_lens_power": ["9.12"],
    "concept_human_eye_structure": ["10.1"],
    "concept_accommodation": ["10.1"],
    "concept_myopia": ["10.2"],
    "concept_hypermetropia": ["10.3"],
    "concept_presbyopia": [],
    "concept_prism_refraction": ["10.4"],
    "concept_dispersion": ["10.5"],
    "concept_rainbow_formation": ["10.8", "10.7"],
    "concept_atmospheric_refraction": ["10.9", "10.10"],
    "concept_scattering": [],
    "concept_electric_current": ["11.1"],
    "concept_potential_difference": ["11.1"],
    "concept_ohms_law": ["11.2", "11.3"],
    "concept_factors_resistance": ["11.4"],
    "concept_series_combination": ["11.6"],
    "concept_parallel_combination": ["11.7"],
    "concept_resistors_combination": ["11.12"],
    "concept_joules_heating": ["11.13"],
    "concept_electric_power": [],
}

# Where "Start here" begins in the book for each topic: the first words of the sentence to start from.
# (The opening of a section is often an activity or a recap, so these were chosen by reading the book.)
START_AT: dict[str, tuple[str, str]] = {
    "concept_reflection_laws": ("9.1", "You are already familiar with the laws of reflection"),
    "concept_spherical_mirrors": ("9.2", "The reflecting surface of a spherical mirror may be curved"),
    "concept_concave_ray_diagrams": ("9.2.1", "The image formed is real for some positions"),
    "concept_convex_ray_diagrams": ("9.2.2", "Now we shall study the formation of image by a convex mirror"),
    "concept_sign_convention": ("9.2.3", "While dealing with the reflection of light"),
    "concept_mirror_formula": ("9.2.4", "In a spherical mirror, the distance of the object"),
    "concept_refraction_laws": ("9.3", "Light seems to travel along straight-line paths"),
    "concept_refractive_index": ("9.3.2", "The refractive index can be linked"),
    "concept_lens_image_formation": ("9.3.3", "A transparent material bound by two surfaces"),
    "concept_lens_formula": ("9.3.7", "As we have a formula for spherical mirrors"),
    "concept_lens_power": ("9.3.8", "The degree of convergence or divergence"),
    "concept_human_eye_structure": ("10.1", "The human eye is one of the most valuable"),
    "concept_accommodation": ("10.1.1", "The ability of the eye lens to adjust"),
    "concept_myopia": ("10.2", "A person with myopia can see nearby objects"),
    "concept_hypermetropia": ("10.2", "Hypermetropia is also known as"),
    "concept_presbyopia": ("10.2", "The power of accommodation"),
    "concept_prism_refraction": ("10.3", "How would light get refracted through a transparent prism"),
    "concept_dispersion": ("10.4", "The band of the coloured components"),
    "concept_rainbow_formation": ("10.4", "A rainbow is"),
    "concept_atmospheric_refraction": ("10.5", "The twinkling of a star is due to"),
    "concept_scattering": ("10.6.2", "The molecules of air and other fine particles"),
    "concept_electric_current": ("11.1", "Similarly, if the electric charge flows"),
    "concept_potential_difference": ("11.2", "What makes the electric charge to flow"),
    "concept_ohms_law": ("11.4", "In 1827, a German physicist"),
    "concept_factors_resistance": ("11.5", "Precise measurements have shown"),
    "concept_series_combination": ("11.6.1", "You will observe that the potential difference V is equal"),
    "concept_parallel_combination": ("11.6.2", "It is observed that the total current"),
    "concept_resistors_combination": ("11.6", "We have noticed how the current"),
    "concept_joules_heating": ("11.7", "On the other hand, if the electric circuit is purely resistive"),
    "concept_electric_power": ("11.8", "You have studied in your earlier Class that the rate of doing work"),
}

_SKIP = re.compile(r"activity|/square|table \d|fig(ure|\.) ?\d|questions?\s*$|\?\s*$|^\s*\(?[ivx]+\)|example \d|^s\. ?no|calculate|\bfind\b|did you|think it over|\[fig|=\s*\d|developing world|^solution", re.IGNORECASE)
_STOP = set("the a an of to in is are and or for on at by be it this that as with from into its can you we your what why how which does do".split())


@lru_cache(maxsize=1)
def _chunks() -> dict[str, dict[str, Any]]:
    path = config.INDEX_DIR / "chunks.json"
    try:
        rows = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        sid = str(row.get("section_id") or "")
        if sid and sid not in out:  # the first chunk of a section starts at its beginning
            out[sid] = row
        elif sid:
            out[sid] = {**out[sid], "content": out[sid].get("content", "") + "\n" + row.get("content", "")}
    return out


@lru_cache(maxsize=1)
def _vocab() -> Counter:
    words: Counter = Counter()
    for row in _chunks().values():
        words.update(re.findall(r"[a-z]+", row.get("content", "").lower()))
    return words


def _join_split_words(text: str) -> str:
    """The PDF text splits some words ("for mation", "mirr ors"); join a pair when the joined word is in the book
    and one half is rare on its own. Also tidy spaces before punctuation ("mirror ," -> "mirror,")."""
    vocab = _vocab()
    tokens = text.split(" ")
    out: list[str] = []
    i = 0
    while i < len(tokens):
        a = tokens[i]
        b = tokens[i + 1] if i + 1 < len(tokens) else ""
        ma, mb = re.fullmatch(r"([^A-Za-z]*)([A-Za-z]+)", a), re.fullmatch(r"([a-z]+)([^A-Za-z]*)", b)
        if ma and mb:
            joined = (ma.group(2) + mb.group(1)).lower()
            rare = min(vocab.get(ma.group(2).lower(), 0), vocab.get(mb.group(1), 0))
            if (vocab.get(joined, 0) >= 2 and rare <= 3) or (vocab.get(joined, 0) >= 1 and rare <= 1):
                out.append(a + b)
                i += 2
                continue
        out.append(a)
        i += 1
    text = " ".join(out)
    text = re.sub(r"\s+([,.;:)])", r"\1", text)
    text = re.sub(r"(\w)\s*-\s+(\w)|(\w)\s+-(\w)", lambda m: (m.group(1) or m.group(3)) + "-" + (m.group(2) or m.group(4)), text)
    return re.sub(r"\(\s+", "(", text)


def _sentences(section_id: str, with_breaks: bool = False) -> list[str]:
    row = _chunks().get(section_id)
    if not row:
        return []
    text = row.get("content", "")
    text = re.sub(r"(Activity \d+\.\d+)+", " ", text)
    text = text.replace("\n", " ")
    text = re.sub(r"\s+", " ", text)
    text = _join_split_words(text)
    parts = re.split(r"(?<=[.!])\s+(?=[A-Z])", text)
    good = []
    for s in parts:
        s = s.strip()
        letters = sum(ch.isalpha() for ch in s)
        bad = len(s) < 40 or len(s) > 320 or letters < 0.7 * len(s) or _SKIP.search(s)
        bad = bad or re.search(r"[′∝ρΩ]|\b[a-z]\s[a-z]\s[a-z]\b|\b[A-Z]{3,}\b", s)  # broken formula text, running heads
        if not bad:
            good.append(s)
        elif with_breaks and good and good[-1] != "":
            good.append("")  # marks a gap, so an excerpt never joins sentences that were apart in the book
    return good


def excerpt_from(section_id: str, phrase: str, max_chars: int = 380) -> str:
    """Real text from the section, starting at the sentence (or the part of it) that begins with the phrase."""
    sents = _sentences(section_id, with_breaks=True)
    i = next((k for k, x in enumerate(sents) if phrase.lower() in x.lower()), None)
    if i is None:
        return ""
    first = sents[i]
    first = first[first.lower().index(phrase.lower()):]
    out = first
    for x in sents[i + 1:i + 3]:
        if not x or len(out) + len(x) + 1 > max_chars:
            break
        out += " " + x
    return out


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z]+", (text or "").lower()) if w not in _STOP and len(w) > 2}


def excerpt(section_id: str, query: str = "", max_chars: int = 380, start: bool = False) -> str:
    """Up to ~380 characters of real text from the section: the opening, or the part closest to the question."""
    sents = _sentences(section_id)
    if not sents:
        return ""
    if start or not query:
        topic = _words(query)
        scores = [len(topic & _words(x)) for x in sents[:12]]
        first = max(range(len(scores)), key=lambda i: (scores[i], -i)) if topic and any(scores) else 0
        picked = sents[first:first + 3]
    else:
        q = _words(query)
        scores = [len(q & _words(s)) for s in sents]
        best = max(range(len(sents)), key=lambda i: (scores[i], -i))
        picked = sents[best:best + 3] if scores[best] else sents[:3]
    out = ""
    for s in picked:
        if len(out) + len(s) + 1 > max_chars and out:
            break
        out = (out + " " + s).strip()
    return out


@lru_cache(maxsize=1)
def _figures() -> dict[str, dict[str, Any]]:
    try:
        rows = json.loads((BOOK_DIR / "figures.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {r["figure"]: r for r in rows if (BOOK_DIR / "figures" / r["file"]).exists()}


@lru_cache(maxsize=1)
def _formulas() -> dict[str, list[dict[str, str]]]:
    try:
        return json.loads((BOOK_DIR / "formulas.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def figure(num: str) -> dict[str, Any] | None:
    f = _figures().get(num)
    if not f:
        return None
    return {"figure": num, "caption": f.get("caption", ""), "url": FIGURE_URL + f["file"], "page": f.get("page")}


def figures_in_section(section_id: str) -> list[str]:
    """Figures the section's own text refers to ("Fig. 9.7"), in order, that were cropped from the book."""
    row = _chunks().get(section_id) or {}
    seen: list[str] = []
    for num in re.findall(r"Fig(?:ure|\.)\s*(\d+\.\d+)", row.get("content", "")):
        if num not in seen and num in _figures():
            seen.append(num)
    return seen


def section_title(section_id: str) -> str:
    row = _chunks().get(section_id) or {}
    return _join_split_words(str(row.get("section_title") or ""))


def _stem(w: str) -> str:
    for suf in ("ing", "ed", "es", "s"):
        if w.endswith(suf) and len(w) - len(suf) >= 4:
            return w[: -len(suf)]
    return w


def _stems(text: str) -> set[str]:
    return {_stem(w) for w in _words(text)}


@lru_cache(maxsize=1)
def _figure_index() -> tuple[dict[str, set[str]], dict[str, float]]:
    """Each figure's words (caption + its "about" list in figures.json), and how rare each word is across
    figures: a word only one figure has ("blackboard", "twinkle") counts for much more than "lens" or "ray"."""
    import math

    words = {n: _stems(f.get("caption", "") + " " + f.get("about", "")) for n, f in _figures().items()}
    df: Counter = Counter(w for ws in words.values() for w in ws)
    total = len(words) or 1
    return words, {w: math.log((total + 1) / (c + 0.5)) for w, c in df.items()}


def pick_figure(query: str, concept_id: str | None, section_ids: list[str]) -> dict[str, Any] | None:
    """The figure that fits the question best, or none (an unrelated figure is worse than no figure).

    Every figure in the book is a candidate. Its score is the rarity-weighted overlap between the question's
    words and the figure's words (caption + "about" in figures.json), plus a little for being the topic's own
    figure or a figure the cited section refers to. Below the bar, no figure is shown.
    """
    words, idf = _figure_index()
    if not words:
        return None
    q = _stems(query)
    own = set(CONCEPT_FIGURES.get(concept_id or "", []))
    cited = {n for sid in section_ids[:2] for n in figures_in_section(sid)}

    def overlap(n: str) -> float:
        return sum(idf.get(w, 0.0) for w in q & words[n])

    best = max(words, key=lambda n: (overlap(n), n in cited))
    mine = max(own, key=overlap) if own else None
    # The topic's own figure, when the question touches it at all and nothing else fits clearly better.
    if mine and overlap(mine) > 0 and overlap(best) < overlap(mine) + 2.0:
        return figure(mine)
    # Otherwise the best match must be clear: a topic with no figure in the book (why the sky is blue)
    # needs a much stronger match before a figure from elsewhere is shown.
    bar = 2.2 if (own or best in cited) else 4.0
    return figure(best) if overlap(best) >= bar else None


def book_card(section_ids: list[str], query: str = "", concept_id: str | None = None) -> dict[str, Any] | None:
    """The "From your NCERT book" card for a tutor reply: the first cited section that the index has,
    the part of it closest to the question, its formulas, and the figure that fits the question (if any)."""
    sid = next((s for s in section_ids if s in _chunks()), None)
    if sid is None:
        return None
    return {
        "section_id": sid,
        "title": section_title(sid),
        "excerpt": excerpt(sid, query),
        "formulas": _formulas().get(sid, [])[:2],
        "figure": pick_figure(query, concept_id, [s for s in section_ids if s in _chunks()]),
        "source": "NCERT Class 10 Science",
    }


def lesson(concept_id: str, mastery: float | None, title: str = "", next_concept: str | None = None, next_title: str = "") -> dict[str, Any]:
    """"Learn this topic from the start", matched to where the student is (code only, no model)."""
    passing = config.PASSING_MASTERY_THRESHOLD
    sections = [s for s in CONCEPT_SECTIONS.get(concept_id, []) if s in _chunks()]
    main = sections[0] if sections else None
    level = "new" if not mastery else ("mastered" if mastery >= passing else "in_progress")
    formulas = [f for s in sections for f in _formulas().get(s, [])]
    figs = [figure(n) for n in CONCEPT_FIGURES.get(concept_id, [])]
    figs = [f for f in figs if f]
    steps: list[dict[str, Any]] = []
    if main and level == "new":
        start_sid, phrase = START_AT.get(concept_id, (main, ""))
        text = excerpt_from(start_sid, phrase) if phrase else ""
        steps.append({"kind": "read", "title": "Start here", "section_id": start_sid if text else main,
                      "section_title": section_title(start_sid if text else main), "text": text or excerpt(main, title, start=True)})
        if figs:
            steps.append({"kind": "figure", "title": "Look at the figure", **figs[0]})
        if formulas:
            steps.append({"kind": "formula", "title": "The rule to remember", "items": formulas[:1]})
    elif main and level == "in_progress":
        extra = sections[1] if len(sections) > 1 else main
        steps.append({"kind": "read", "title": "A quick reminder", "section_id": main, "section_title": section_title(main), "text": excerpt(main, title, max_chars=260)})
        if formulas:
            steps.append({"kind": "formula", "title": "The formulas you need", "items": formulas[:3]})
        if figs:
            steps.append({"kind": "figure", "title": "Use the figure", **figs[-1]})
        if extra != main:
            steps.append({"kind": "read", "title": "One step further", "section_id": extra, "section_title": section_title(extra), "text": excerpt(extra, title, start=True, max_chars=260)})
    return {
        "concept_id": concept_id,
        "title": title or concept_id,
        "level": level,
        "mastery": round(float(mastery or 0.0), 2),
        "passing": passing,
        "sections": sections,
        "steps": steps,
        "next": {"concept_id": next_concept, "title": next_title} if level == "mastered" and next_concept else None,
        "how": "Built by code from your NCERT book (text, figures and equations); no model was used.",
    }
