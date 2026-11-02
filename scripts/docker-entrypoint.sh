#!/bin/sh
# Make sure the NCERT index exists, then start whatever command was given.
# The PDFs are not in the repo (the guide forbids redistributing them): they are
# fetched into the mounted data/ncert volume on first start.
set -e
if [ ! -s /app/.index/chunks.json ]; then
  echo "No NCERT index yet: fetching chapter PDFs and building the index..."
  python scripts/fetch_ncert.py || echo "WARNING: could not fetch the NCERT PDFs. Put them in data/ncert/ (see docs/SETUP_GUIDE.md)."
  if python scripts/build_index.py --force; then
    python scripts/map_retrieval_chunks.py || true
  else
    echo "WARNING: index not built; the tutor will answer without textbook passages until it is."
  fi
fi
exec "$@"
