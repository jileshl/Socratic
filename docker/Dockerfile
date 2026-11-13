# Socratic Tutor image, used by the app and the eval container. CPU only.
# Build from the repository root (docker compose does this): context "..".
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PYTHONPATH=/app \
    HOST=0.0.0.0 PORT=8000

WORKDIR /app
# OpenCV (OCR fallback in NCERT ingestion, R2) needs these system libraries.
RUN apt-get update && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
# sentence-transformers (optional reranker) needs torch. The default torch wheel
# bundles CUDA (several GB) and filled the CI runner's disk, so the small CPU
# wheel goes in first; requirements.txt then finds torch already installed.
RUN pip install --index-url https://download.pytorch.org/whl/cpu torch \
    && pip install -r requirements.txt

COPY . .

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=90s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=4)"
# Build the NCERT index from the PDFs in data/ on first start, then serve.
# First start: download any NCERT PDF that isn't here (they are not redistributed in the repository, guide p.12),
# then build the index once.
CMD ["sh", "-c", "python scripts/fetch_ncert.py || true; [ -s .index/chunks.json ] || python scripts/build_index.py --force; exec python -m socratic_tutor.app"]
