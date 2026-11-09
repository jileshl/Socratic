VENV_PY := $(shell if [ -x ./.venv/bin/python ]; then echo ./.venv/bin/python; elif [ -x ./venv/bin/python ]; then echo ./venv/bin/python; else echo python; fi)
PY ?= $(VENV_PY)

.PHONY: help check setup index run dev test app reflexion clean eval eval-list report gate up seed-demo ci-deps ci docker-check

help:
	@grep -E '^[a-z-]+:.*?##' $(MAKEFILE_LIST) | sed 's/:.*##/\t/' | column -t -s "$$(printf '\t')"

check:   ## preflight: python version, packages, API keys, index status
	$(PY) scripts/check_env.py

setup:   ## install dependencies and build NCERT index
	$(PY) scripts/check_env.py || true
	$(PY) -m pip install -r requirements.txt
	$(PY) scripts/build_index.py --force

index:   ## rebuild the NCERT textbook hybrid index
	$(PY) scripts/build_index.py --force

run:     ## run one query: make run Q="Why is concave mirror image inverted?"
	$(PY) scripts/run_one.py "$(Q)" $(if $(S),--student $(S),)

dev:     ## run evaluation over the development student cases
	$(PY) scripts/evaluate_dev.py --workers 4 --show 5

reflexion: ## run the L12 Reflexion loop to generate misconception teaching lessons
	$(PY) scripts/run_reflexion.py --dev-only

retrieval: ## test retrieval recall@5 only (no LLM calls)
	$(PY) scripts/evaluate_dev.py --retrieval-only

app:     ## launch the Socratic Tutor web UI
	$(PY) -m socratic_tutor.app

test:    ## run contract tests, guardrails & tool validation
	$(PY) -m pytest tests -v

clean:   ## remove index artifacts, caches, and run traces
	rm -rf .index .cache dev_traces.jsonl traces.jsonl

# --- evaluation (R5) and operations (R6) ---
# Written as "python -m ..." so they also work on Windows (no PYTHONPATH or env-var prefixes).
eval:    ## run one experiment: make eval E=e1_c2 SPLIT=dev REPEATS=1
	$(PY) -m evalkit.runner $(E) --split $(or $(SPLIT),dev) --repeats $(or $(REPEATS),1)

eval-list: ## list the evaluation experiments (evalkit/experiments.py)
	$(PY) -m evalkit.runner --list

report:  ## build the evaluation tables from evalkit/results/experiment_log.csv
	$(PY) -m evalkit.report

gate:    ## CI eval gate: fail if dev Recall@5 drops below CI_MIN_RECALL_AT_5 (config.py)
	$(PY) -m scripts.check_threshold

ci-deps: ## install packages with the small CPU-only torch (CI uses this; no GPU is needed)
	$(PY) -m pip install --index-url https://download.pytorch.org/whl/cpu torch
	$(PY) -m pip install -r requirements.txt

ci:      ## everything CI runs: tests, index from data/, Recall@5 gate, offline smoke run of every eval suite
	$(PY) -m pytest -q tests
	$(PY) -m scripts.build_index --force
	$(PY) -m scripts.check_threshold
	$(PY) -m evalkit.runner smoke --split dev --limit 3 --stub

docker-check: ## validate the compose file and build the image (CI runs this too)
	docker compose -f docker/docker-compose.yml config --quiet
	docker build -f docker/Dockerfile -t socratic-tutor:ci .

up:      ## start everything with Docker (app, Prometheus, Grafana)
	docker compose -f docker/docker-compose.yml up --build

seed-demo: ## add three [DEMO] questions waiting for teacher approval
	$(PY) -m scripts.seed_demo
