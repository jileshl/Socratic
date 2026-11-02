# Socratic Tutor app image (also used by the eval container). CPU only.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    HOST=0.0.0.0 PORT=8000 DOCUMENT_PATH=/app/data/ncert RESULTS_DIR=/app/results

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

# eval_heldout/ is excluded by .dockerignore: the app image can never read held-out cases.
COPY . .
RUN pip install --no-deps -e .

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=4)"
ENTRYPOINT ["/app/scripts/docker-entrypoint.sh"]
CMD ["python", "-m", "socratic_tutor.app"]
