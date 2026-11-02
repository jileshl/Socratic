# Setup guide

Two ways to run the tutor. Docker is the one the guide marks ("installation on a clean machine"); the local way is faster for development.

## A. One command with Docker

1. Install Docker Desktop (Mac/Windows) or Docker Engine with the Compose plugin (Linux). Compose 2.24 or newer is needed (`docker compose version`).
2. Get an OpenRouter key at https://openrouter.ai/settings/keys.
3. In the repo folder:
   ```bash
   cp .env.example .env        # then put your key in OPENROUTER_API_KEY and change TEACHER_PIN
   docker compose up --build
   ```
4. Open:

| URL | What |
|---|---|
| http://localhost:8000 | student view |
| http://localhost:8000/teacher | teacher view (PIN from `.env`) |
| http://localhost:3000 | Grafana, dashboard "Socratic Tutor" (anonymous view; admin / admin to edit) |
| http://localhost:9090 | Prometheus; the Alerts tab shows `AnswerLeakSpike` |

On first start the app downloads the three NCERT chapter PDFs into `data/ncert/` and builds the index. If NCERT's site is unreachable, download Chapters 9, 10 and 11 of Class 10 Science from https://ncert.nic.in/textbook.php, save them under the names in `scripts/fetch_ncert.py`, and restart.

Without a key the app still starts, but every LLM call fails. The evaluation harness switches to its offline stand-in, and those results are labelled STUB.

## B. Local Python (no Docker)

Python 3.12 is recommended (3.11 works).

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pip install --no-deps -e .               # makes `socratic_tutor` and `evalkit` importable from anywhere
cp .env.example .env                     # add your key
python scripts/fetch_ncert.py            # NCERT PDFs into data/ncert/ (git-ignored)
python scripts/build_index.py --force
python scripts/map_retrieval_chunks.py
python -m socratic_tutor.app             # http://127.0.0.1:8000
pytest -q                                # offline; no key needed
```

`make help` lists the shortcuts (`make app`, `make gate`, `make smoke`, `make eval CONFIG=… SPLIT=…`, `make report`).

## Clean-machine check (for the final review)

On a machine that has never run the project: clone, `cp .env.example .env`, add the key, `docker compose up --build`, then open the four URLs above. Record it for the backup video (docs/DEMO_SCRIPT.md, scene 1).
