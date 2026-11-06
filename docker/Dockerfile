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
RUN pip install -r requirements.txt

COPY . .

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=90s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=4)"
ENTRYPOINT ["/app/docker/entrypoint.sh"]
CMD ["python", "-m", "socratic_tutor.app"]
