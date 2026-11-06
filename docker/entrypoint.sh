#!/bin/sh
# Build the NCERT index from the chapter PDFs in data/ on first start, then run the command.
set -e
if [ ! -s /app/.index/chunks.json ]; then
  echo "No NCERT index yet: building it from the PDFs in data/ ..."
  python scripts/build_index.py --force || echo "WARNING: index not built; the tutor will answer without textbook passages."
fi
exec "$@"
