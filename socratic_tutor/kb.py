"""NCERT PDF extraction and stable section-level chunking."""

from __future__ import annotations

import io
import re
from dataclasses import asdict, dataclass
from functools import lru_cache

import numpy as np
from pypdf import PdfReader
from rapidocr_onnxruntime import RapidOCR


SECTION_TITLES: dict[str, str] = {
    "9.1": "Reflection of Light",
    "9.2": "Spherical Mirrors",
    "9.2.1": "Image Formation by Spherical Mirrors",
    "9.2.2": "Representation of Images Formed by Spherical Mirrors Using Ray Diagrams",
    "9.2.3": "Sign Convention for Reflection by Spherical Mirrors",
    "9.2.4": "Mirror Formula and Magnification",
    "9.3": "Refraction of Light",
    "9.3.1": "Refraction through a Rectangular Glass Slab",
    "9.3.2": "The Refractive Index",
    "9.3.3": "Refraction by Spherical Lenses",
    "9.3.4": "Image Formation by Lenses",
    "9.3.5": "Image Formation in Lenses Using Ray Diagrams",
    "9.3.6": "Sign Convention for Spherical Lenses",
    "9.3.7": "Lens Formula and Magnification",
    "9.3.8": "Power of a Lens",
    "10.1": "The Human Eye",
    "10.1.1": "Power of Accommodation",
    "10.2": "Defects of Vision and Their Correction",
    "10.3": "Refraction of Light Through a Prism",
    "10.4": "Dispersion of White Light by a Glass Prism",
    "10.5": "Atmospheric Refraction",
    "10.6": "Scattering of Light",
    "10.6.1": "Tyndall Effect",
    "10.6.2": "Why Is the Colour of the Clear Sky Blue?",
    "11.1": "Electric Current and Circuit",
    "11.2": "Electric Potential and Potential Difference",
    "11.3": "Circuit Diagram",
    "11.4": "Ohm's Law",
    "11.5": "Factors on Which the Resistance of a Conductor Depends",
    "11.6": "Resistance of a System of Resistors",
    "11.6.1": "Resistors in Series",
    "11.6.2": "Resistors in Parallel",
    "11.7": "Heating Effect of Electric Current",
    "11.7.1": "Practical Applications of Heating Effect of Electric Current",
    "11.8": "Electric Power",
}


@dataclass(frozen=True)
class TextChunk:
    chunk_id: str
    class_num: str
    subject: str
    chapter_num: str
    chapter_title: str
    section_id: str
    section_title: str
    content: str
    equations: list[str]
    exercise_ids: list[str]

    def to_dict(self) -> dict:
        return asdict(self)


_SECTION_PREFIX = re.compile(r"^(\d+\.\d+(?:\.\d+)?)\s*")
_EXERCISE_HEADING = re.compile(r"(?im)^\s*EXERCISES\s*$")
_EXERCISE_QUESTION = re.compile(r"(?m)^\s*(\d{1,2})\.\s+\S")
_PAGE_NOISE = re.compile(
    r"^(?:Reprint\s+\d{4}-\d{2}|Science\s*\d+|"
    r"Light\s*[–-]\s*Reflection and Refraction\s*\d+|"
    r"The Human Eye and the Colourful World\s*\d+|Electricity\s*\d+)$",
    re.IGNORECASE,
)
SECTION_EQUATIONS: dict[str, list[str]] = {
    "9.2.4": [
        "1/f = 1/v + 1/u",
        "m = h'/h = -v/u",
    ],
    "9.3.2": [
        "n21 = sin(i)/sin(r) = v1/v2",
        "n12 = v2/v1",
        "n = c/v",
    ],
    "9.3.7": [
        "1/f = 1/v - 1/u",
        "m = h'/h = v/u",
    ],
    "9.3.8": ["P = 1/f (f in metres)"],
    "11.1": ["I = Q/t"],
    "11.2": ["V = W/Q"],
    "11.4": ["V = I*R", "R = V/I", "I = V/R"],
    "11.5": ["R = rho*l/A"],
    "11.6.1": ["Rs = R1 + R2 + ..."],
    "11.6.2": ["1/Rp = 1/R1 + 1/R2 + ..."],
    "11.7": ["H = I^2*R*t", "H = V*I*t"],
    "11.8": ["P = V*I = I^2*R = V^2/R", "E = P*t"],
}
_MIN_IMAGE_AREA = 10_000
_PAGE_IMAGE_AREA = 1_000_000
_MIN_NATIVE_TEXT_CHARS = 80
_MIN_OCR_CONFIDENCE = 0.55
_MIN_DUPLICATE_OCR_TOKENS = 15
_DUPLICATE_OCR_OVERLAP = 0.35


@lru_cache(maxsize=1)
def _load_ocr_engine():
    return RapidOCR()


def _is_full_page_image(image: object, page: object) -> bool:
    width, height = image.size
    media_box = page.mediabox
    scale_x = width / float(media_box.width)
    scale_y = height / float(media_box.height)
    scale_delta = abs(scale_x - scale_y) / max(scale_x, scale_y)
    return width * height >= _PAGE_IMAGE_AREA and min(scale_x, scale_y) >= 2 and scale_delta <= 0.08


def _ocr_page_images(page: object, native_text: str, ocr_engine=None) -> list[str]:
    """OCR embedded figures, and full-page scans only when native text is sparse."""
    try:
        images = page.images
    except Exception:
        return []

    native_compact = re.sub(r"[^a-z0-9]+", "", native_text.lower())
    extracted: list[str] = []
    seen: set[str] = set()

    for image_file in images:
        try:
            image = image_file.image
            width, height = image.size
            if width * height < _MIN_IMAGE_AREA:
                continue
            is_page_image = _is_full_page_image(image, page)
            if is_page_image and len(native_text.strip()) >= _MIN_NATIVE_TEXT_CHARS:
                continue

            if ocr_engine is None:
                ocr_engine = _load_ocr_engine()

            image = image.convert("RGB")
            image.thumbnail((2400, 2400))
            result, _ = ocr_engine(np.array(image, dtype=np.uint8, copy=True, order="C"))
        except Exception:
            continue

        confident_lines = []
        for line in result or []:
            try:
                text = str(line[1]).strip()
                confidence = float(line[2])
            except (IndexError, TypeError, ValueError):
                continue
            normalized = re.sub(r"[^a-z0-9]+", "", text.lower())
            is_page_stamp = re.fullmatch(r"\d+[a-z]{1,6}\d+", normalized)
            if text and normalized and not is_page_stamp and confidence >= _MIN_OCR_CONFIDENCE:
                confident_lines.append(text)

        ocr_tokens = set(re.findall(r"[a-z0-9]{2,}", " ".join(confident_lines).lower()))
        native_tokens = set(re.findall(r"[a-z0-9]{2,}", native_text.lower()))
        overlap = len(ocr_tokens & native_tokens) / max(len(ocr_tokens), 1)
        if len(ocr_tokens) >= _MIN_DUPLICATE_OCR_TOKENS and overlap >= _DUPLICATE_OCR_OVERLAP:
            continue

        for text in confident_lines:
            normalized = re.sub(r"[^a-z0-9]+", "", text.lower())
            if not text or normalized in seen:
                continue
            if len(normalized) >= 4 and normalized in native_compact:
                continue
            seen.add(normalized)
            extracted.append(text)
    return extracted


def extract_pdf_text(pdf_bytes: bytes, ocr_engine=None) -> str:
    """Extract native text and targeted OCR text without persisting the source PDF."""
    reader = PdfReader(io.BytesIO(pdf_bytes))
    pages = []
    for page in reader.pages:
        native_text = page.extract_text() or ""
        ocr_text = _ocr_page_images(page, native_text, ocr_engine=ocr_engine)
        if ocr_text:
            native_text = f"{native_text}\n[Supplemental figure OCR]\n" + "\n".join(ocr_text)
        pages.append(native_text)
    return "\n".join(pages)


def _clean_line(line: str) -> str:
    line = re.sub(r"\s+", " ", line).strip()
    return "" if _PAGE_NOISE.match(line) else line


def _chunk_id(chapter_num: str, section_id: str) -> str:
    section_slug = section_id.replace(".", "_")
    return f"ncert_c10_science_ch{int(chapter_num):02d}_sec_{section_slug}"


def _extract_exercise_ids(content: str, chapter_num: str) -> list[str]:
    headings = list(_EXERCISE_HEADING.finditer(content))
    exercise_ids: list[str] = []
    chapter_slug = f"{int(chapter_num):02d}"
    for exercise_index, heading in enumerate(headings, start=1):
        end = headings[exercise_index].start() if exercise_index < len(headings) else len(content)
        exercise_text = content[heading.end():end]
        for match in _EXERCISE_QUESTION.finditer(exercise_text):
            question_number = int(match.group(1))
            exercise_ids.append(
                f"ncert_c10_science_ch{chapter_slug}_ex{exercise_index:02d}_q{question_number:02d}"
            )
    return exercise_ids


def chunk_ncert_text(text: str, chapter_num: str, chapter_title: str) -> list[TextChunk]:
    """Split extracted NCERT text into one stable chunk per printed section."""
    allowed_prefix = f"{int(chapter_num)}."
    sections: dict[str, list[str]] = {}
    current_section: str | None = None

    for raw_line in text.splitlines():
        line = _clean_line(raw_line)
        if not line:
            continue

        match = _SECTION_PREFIX.match(line)
        candidate = match.group(1) if match else None
        if candidate in SECTION_TITLES and candidate.startswith(allowed_prefix):
            current_section = candidate
            sections.setdefault(candidate, [])
            continue

        if current_section:
            sections[current_section].append(line)

    chunks: list[TextChunk] = []
    for section_id in sorted(sections, key=lambda value: tuple(map(int, value.split(".")))):
        content = "\n".join(sections[section_id]).strip()
        if not content:
            continue
        equations = SECTION_EQUATIONS.get(section_id, [])
        chunks.append(
            TextChunk(
                chunk_id=_chunk_id(chapter_num, section_id),
                class_num="10",
                subject="Science",
                chapter_num=str(int(chapter_num)),
                chapter_title=chapter_title,
                section_id=section_id,
                section_title=SECTION_TITLES[section_id],
                content=content,
                equations=equations[:20],
                exercise_ids=_extract_exercise_ids(content, chapter_num),
            )
        )
    return chunks


def chunk_ncert_pdf(pdf_bytes: bytes, chapter_num: str, chapter_title: str) -> list[TextChunk]:
    """Extract and chunk one NCERT chapter PDF."""
    return chunk_ncert_text(extract_pdf_text(pdf_bytes), chapter_num, chapter_title)


def _infer_section_for_exemplar(text: str, chapter_num: str) -> str:
    """Map an exemplar question to its closest chapter section."""
    ch = str(int(chapter_num))
    t = text.lower()
    if ch == "9":
        if "lens" in t:
            if "power" in t or "dioptre" in t or " d " in t or " d)" in t:
                return "9.3.8"
            if any(w in t for w in ["focal", "distance", "magnif", "formula"]):
                return "9.3.7"
            if "ray diagram" in t or "image formed" in t:
                return "9.3.5"
            return "9.3.4"
        if "mirror" in t:
            if any(w in t for w in ["focal", "formula", "distance", "magnif", "radius of curvature"]):
                return "9.2.4"
            if "ray" in t or "image" in t:
                return "9.2.2"
            return "9.2.1"
        if "refract" in t or "medium" in t or "glass slab" in t or "speed of light" in t:
            return "9.3.2"
        return "9.1"
    elif ch == "10":
        if any(w in t for w in ["myopia", "hypermetropia", "presbyopia", "defect", "power", "distinctly", "spectacle", "blackboard"]):
            return "10.2"
        if any(w in t for w in ["prism", "spectrum", "dispersion", "angle of prism", "rainbow"]):
            return "10.4"
        if any(w in t for w in ["twinkl", "star", "apparent position", "advance sunrise"]):
            return "10.5"
        if any(w in t for w in ["sky", "blue", "danger", "sunset", "tyndall", "scatter"]):
            return "10.6"
        return "10.1"
    elif ch == "11":
        if any(w in t for w in ["series", "parallel", "combination", "equivalent resistance", "resistor"]):
            if "parallel" in t:
                return "11.6.2"
            if "series" in t:
                return "11.6.1"
            return "11.6"
        if any(w in t for w in ["heat", "joule", "fuse", "calorie"]):
            return "11.7"
        if any(w in t for w in ["power", "watt", "kwh", "bulb", "energy"]):
            return "11.8"
        if any(w in t for w in ["ohm", "v = ir", "resistance of a conductor", "length", "cross-section", "resistivity"]):
            return "11.4"
        if any(w in t for w in ["potential difference", "volt", "battery", "voltmeter"]):
            return "11.2"
        return "11.1"
    return f"{ch}.1"


def extract_exemplar_problems(pdf_bytes: bytes, chapter_num: str) -> list[dict]:
    """Extract individual NCERT Exemplar problems from an exemplar chapter PDF."""
    text = extract_pdf_text(pdf_bytes)
    text = re.sub(r"(?i)exemplar\s+problems\s*–?\s*science", "", text)
    text = re.sub(r"(?i)\d+\s+exemplar\s+problems", "", text)

    pattern = r"(?m)^\s*(\d{1,2})\.\s+(.*?)(?=(?:^\s*\d{1,2}\.\s+)|\Z)"
    matches = list(re.finditer(pattern, text, re.DOTALL))

    ch_str = str(int(chapter_num))
    results: list[dict] = []
    for m in matches:
        q_num = m.group(1)
        q_text = re.sub(r"\s+", " ", m.group(2)).strip()
        if len(q_text) < 15:
            continue
        sec_id = _infer_section_for_exemplar(q_text, ch_str)
        q_id = f"exemplar_{ch_str}_{q_num}"
        results.append({
            "exemplar_id": q_id,
            "chapter_num": ch_str,
            "section_id": sec_id,
            "problem": q_text,
        })
    return results
