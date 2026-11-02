"""Get the three NCERT Class 10 Science chapter PDFs into data/ncert/.

The capstone guide says to use the NCERT PDFs inside the project but not to
redistribute them in the repository. So the PDFs are git-ignored, and this
script fetches them on demand (locally, in Docker and in CI).

Sources, tried in this order:

1. NCERT_PDF_ZIP_URL (optional): a private link to a zip holding the three PDFs
   under the file names below. CI uses this, stored as a GitHub Actions secret,
   because ncert.nic.in refuses connections from GitHub's servers and serves an
   incomplete certificate chain (see docs/CI_FAILURE.md). The link is never
   written into the repository.
2. ncert.nic.in directly (jesc1 = Class 10 Science, English; 09/10/11 = chapter),
   with retries. This works from most machines in India.

If both fail, download the chapters by hand from https://ncert.nic.in/textbook.php
and save them in data/ncert/ under the file names below.

    python scripts/fetch_ncert.py            # skip files that already exist
    python scripts/fetch_ncert.py --force    # download again
"""

from __future__ import annotations

import argparse
import io
import os
import sys
import time
import urllib.request
import zipfile
from pathlib import Path

BASE_URL = os.getenv("NCERT_BASE_URL", "https://ncert.nic.in/textbook/pdf/")
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"

# (remote file on ncert.nic.in, local file name expected by scripts/build_index.py)
CHAPTERS = (
    ("jesc109.pdf", "ch9-Light–Reflection-and-Refraction.pdf"),
    ("jesc110.pdf", "ch10-The-Human-Eye-and-the-Colourful-World .pdf"),
    ("jesc111.pdf", "ch11-Electricity.pdf"),
)


def _download(url: str, attempts: int = 3) -> bytes:
    """GET a URL with a browser-like User-Agent, retrying with back-off."""
    last: Exception | None = None
    for attempt in range(attempts):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(request, timeout=60) as response:
                return response.read()
        except Exception as exc:  # reported by the caller
            last = exc
            if attempt < attempts - 1:
                time.sleep(3 * (attempt + 1))
    raise RuntimeError(str(last))


def _missing(target_dir: Path, force: bool) -> list[tuple[str, str]]:
    out = []
    for remote, local in CHAPTERS:
        path = target_dir / local
        if path.exists() and path.stat().st_size > 0 and not force:
            print(f"ok      {local} (already present)")
        else:
            out.append((remote, local))
    return out


def _normalise(name: str) -> str:
    """Compare file names loosely: some zip tools mangle the en dash or the trailing space."""
    return "".join(ch for ch in name.lower() if ch.isascii() and ch.isalnum())


def from_zip(url: str, target_dir: Path, wanted: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """Extract the wanted PDFs from a zip at `url`. Returns what is still missing."""
    try:
        data = _download(url)
        archive = zipfile.ZipFile(io.BytesIO(data))
    except Exception as exc:
        print(f"FAILED  private zip (NCERT_PDF_ZIP_URL): {exc}", file=sys.stderr)
        return wanted
    by_name = {_normalise(Path(info.filename).name): info for info in archive.infolist() if info.filename.lower().endswith(".pdf")}
    still: list[tuple[str, str]] = []
    for remote, local in wanted:
        info = by_name.get(_normalise(local)) or by_name.get(_normalise(remote))
        content = archive.read(info) if info else b""
        if not content.startswith(b"%PDF"):
            still.append((remote, local))
            continue
        (target_dir / local).write_bytes(content)
        print(f"fetched {local} from private zip ({len(content) // 1024} KB)")
    return still


def from_ncert(target_dir: Path, wanted: list[tuple[str, str]]) -> list[tuple[str, str]]:
    still: list[tuple[str, str]] = []
    for remote, local in wanted:
        url = BASE_URL + remote
        try:
            data = _download(url)
        except Exception as exc:
            print(f"FAILED  {local} from {url}: {exc}", file=sys.stderr)
            still.append((remote, local))
            continue
        if not data.startswith(b"%PDF"):
            print(f"FAILED  {local}: {url} did not return a PDF", file=sys.stderr)
            still.append((remote, local))
            continue
        (target_dir / local).write_bytes(data)
        print(f"fetched {local} from ncert.nic.in ({len(data) // 1024} KB)")
    return still


def fetch(target_dir: Path, force: bool) -> int:
    target_dir.mkdir(parents=True, exist_ok=True)
    wanted = _missing(target_dir, force)
    zip_url = os.getenv("NCERT_PDF_ZIP_URL", "").strip()
    if wanted and zip_url:
        wanted = from_zip(zip_url, target_dir, wanted)
    if wanted:
        wanted = from_ncert(target_dir, wanted)
    return len(wanted)


def main() -> None:
    from socratic_tutor import config

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--target-dir", type=Path, default=config.DOCUMENT_PATH)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    failures = fetch(args.target_dir, args.force)
    if failures:
        hint = (
            "In CI: ask the repo owner to add the NCERT_PDF_ZIP_URL secret (docs/CI_FAILURE.md)."
            if os.getenv("GITHUB_ACTIONS")
            else f"Download them from https://ncert.nic.in/textbook.php into {args.target_dir} using the file names in scripts/fetch_ncert.py."
        )
        raise SystemExit(f"{failures} chapter PDF(s) missing. {hint}")


if __name__ == "__main__":
    main()
