"""NCERT PDF extraction and stable section-level chunking."""

from __future__ import annotations

import io
import re
from dataclasses import asdict, dataclass


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

    def to_dict(self) -> dict:
        return asdict(self)


_SECTION_PREFIX = re.compile(r"^(\d+\.\d+(?:\.\d+)?)\s*")
_PAGE_NOISE = re.compile(
    r"^(?:Reprint\s+\d{4}-\d{2}|Science\s*\d+|"
    r"Light\s*[–-]\s*Reflection and Refraction\s*\d+|"
    r"The Human Eye and the Colourful World\s*\d+|Electricity\s*\d+)$",
    re.IGNORECASE,
)
_EQUATION = re.compile(r"[^=\n]{1,80}=[^=\n]{1,80}")


def extract_pdf_text(pdf_bytes: bytes) -> str:
    """Extract text from a PDF byte stream without persisting the source PDF."""
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover - environment-specific message
        raise RuntimeError("PDF ingestion requires pypdf; install requirements.txt") from exc

    reader = PdfReader(io.BytesIO(pdf_bytes))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def _clean_line(line: str) -> str:
    line = re.sub(r"\s+", " ", line).strip()
    return "" if _PAGE_NOISE.match(line) else line


def _chunk_id(chapter_num: str, section_id: str) -> str:
    section_slug = section_id.replace(".", "_")
    return f"ncert_c10_science_ch{int(chapter_num):02d}_sec_{section_slug}"


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
        equations = list(dict.fromkeys(match.group(0).strip() for match in _EQUATION.finditer(content)))
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
            )
        )
    return chunks


def chunk_ncert_pdf(pdf_bytes: bytes, chapter_num: str, chapter_title: str) -> list[TextChunk]:
    """Extract and chunk one NCERT chapter PDF."""
    return chunk_ncert_text(extract_pdf_text(pdf_bytes), chapter_num, chapter_title)
