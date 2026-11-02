"""Download the three NCERT Class 10 Science chapter PDFs into data/ncert/.

The capstone guide says to use the NCERT PDFs inside the project but not to
redistribute them in the repository. So the PDFs are git-ignored, and this
script fetches them on demand (locally, in Docker and in CI).

The URLs follow ncert.nic.in's textbook naming (jesc1 = Class 10 Science,
English; 09/10/11 = chapter). If NCERT changes them, download the chapters by
hand from https://ncert.nic.in/textbook.php and save them under the file names
below, or set NCERT_BASE_URL.

    python scripts/fetch_ncert.py            # skip files that already exist
    python scripts/fetch_ncert.py --force    # re-download
"""

from __future__ import annotations

import argparse
import os
import sys
import urllib.request
from pathlib import Path

BASE_URL = os.getenv("NCERT_BASE_URL", "https://ncert.nic.in/textbook/pdf/")

# (remote file, local file name expected by scripts/build_index.py)
CHAPTERS = (
    ("jesc109.pdf", "ch9-Light–Reflection-and-Refraction.pdf"),
    ("jesc110.pdf", "ch10-The-Human-Eye-and-the-Colourful-World .pdf"),
    ("jesc111.pdf", "ch11-Electricity.pdf"),
)


def fetch(target_dir: Path, force: bool) -> int:
    target_dir.mkdir(parents=True, exist_ok=True)
    failures = 0
    for remote, local in CHAPTERS:
        path = target_dir / local
        if path.exists() and path.stat().st_size > 0 and not force:
            print(f"ok      {local} (already present)")
            continue
        url = BASE_URL + remote
        request = urllib.request.Request(url, headers={"User-Agent": "socratic-tutor-capstone/0.2"})
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                data = response.read()
        except Exception as exc:  # network errors are reported, not raised
            print(f"FAILED  {local} from {url}: {exc}", file=sys.stderr)
            failures += 1
            continue
        if not data.startswith(b"%PDF"):
            print(f"FAILED  {local}: {url} did not return a PDF", file=sys.stderr)
            failures += 1
            continue
        path.write_bytes(data)
        print(f"fetched {local} ({len(data) // 1024} KB)")
    return failures


def main() -> None:
    from socratic_tutor import config

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--target-dir", type=Path, default=config.DOCUMENT_PATH)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    failures = fetch(args.target_dir, args.force)
    if failures:
        raise SystemExit(
            f"{failures} chapter PDF(s) missing. Download them from https://ncert.nic.in/textbook.php "
            f"into {args.target_dir} using the file names in scripts/fetch_ncert.py."
        )


if __name__ == "__main__":
    main()
