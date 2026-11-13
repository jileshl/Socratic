"""Download the NCERT PDFs the index is built from, instead of shipping them in the repository.

The capstone guide (p.12): "Use NCERT textbooks and exemplar problems from ncert.nic.in within the project, but
do not redistribute the PDFs in your repository." The Docker image runs this on first start when a PDF is
missing; it is also safe to run by hand:

    python scripts/fetch_ncert.py            # download what is missing into data/
    python scripts/fetch_ncert.py --check    # report only: is each PDF here, and is it the version we tested?

Each file has the SHA-256 of the copy the team built and tested the index and figures with. A different
version (NCERT updates its books) still downloads and works, but the script says so, because section text and
figure pages can then differ from the ones in the report.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
EXEMPLAR = "https://ncert.nic.in/pdf/publication/exemplarproblem/classX/science/"
TEXTBOOK = "https://ncert.nic.in/textbook/pdf/"

# file name in data/ -> (official URL, SHA-256 of the version the team tested)
SOURCES: dict[str, tuple[str, str]] = {
    "ch9-Light–Reflection-and-Refraction.pdf": (TEXTBOOK + "jesc109.pdf", "a647d66cd9dd9e767c1fea57baac3a7aeaf9cb7461f87dc3f619e6fee8947497"),
    "ch10-The-Human-Eye-and-the-Colourful-World .pdf": (TEXTBOOK + "jesc110.pdf", "c8ed49fa55eedeb9ee5d5fbfa6d02061adb94075e94a32ca9bd16f4caf67c423"),
    "ch11-Electricity.pdf": (TEXTBOOK + "jesc111.pdf", "640a680a24070d4add6d580d03d5377768ee5a6b4f89f9bfb66b350d457ab52f"),
    "jesc1ps.pdf": (TEXTBOOK + "jesc1ps.pdf", "cf2a2afb28bd01b4518dbd7e9517b8a9b4a85c989bf3a047cd96d1a8408fdcb0"),
    "jesc1an.pdf": (TEXTBOOK + "jesc1an.pdf", "360f3bc888a12de5e982e097febf6bd11cfa64a0015160aeb2bc05d16f6b4d17"),
    "exemplar_ch9.pdf": (EXEMPLAR + "jeep110.pdf", "ac871051fa24d1e1aec93410513e99d430b9ec48c628fe8c9dd187804a5e2d40"),
    "exemplar_ch10.pdf": (EXEMPLAR + "jeep111.pdf", "b2d5129b25bd2ffe517279752eed1030b82fb8729a8e07ea9dfd7c32ab0519b0"),
    "exemplar_ch11.pdf": (EXEMPLAR + "jeep112.pdf", "6ef23cb48549681f19271dea498f374599a3497821c3d7d2b8d2c3c9674bd24e"),
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fetch(url: str, target: Path) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Socratic Tutor capstone; one-time download)"})
    with urllib.request.urlopen(request, timeout=120) as response:
        body = response.read()
    if not body.startswith(b"%PDF"):
        raise ValueError("not a PDF")
    target.write_bytes(body)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="report only, download nothing")
    parser.add_argument("--out", type=Path, default=DATA, help="folder for the PDFs (default: data/)")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    problems = 0
    for name, (url, expected) in SOURCES.items():
        target = args.out / name
        if not target.exists() and not args.check:
            try:
                fetch(url, target)
            except Exception as error:
                print(f"MISSING  {name}: could not download {url} ({type(error).__name__}: {error})")
                problems += 1
                continue
        if not target.exists():
            print(f"MISSING  {name}  ({url})")
            problems += 1
            continue
        same = sha256(target) == expected
        print(f"{'OK      ' if same else 'DIFFERS '} {name}" + ("" if same else "  (a newer NCERT version: works, but text and figure pages may differ from the report)"))
    if problems:
        print(f"\n{problems} file(s) missing. Download them from ncert.nic.in by hand into {args.out} (names above).")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
