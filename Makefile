VENV_PY := $(shell if [ -x ./.venv/bin/python ]; then echo ./.venv/bin/python; elif [ -x ./venv/bin/python ]; then echo ./venv/bin/python; else echo python; fi)
PY ?= $(VENV_PY)

.PHONY: help check setup index run dev test app reflexion clean eval eval-list report gate up seed-demo

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
eval:    ## run one experiment: make eval E=e1_c2 SPLIT=dev REPEATS=1
	PYTHONPATH=. $(PY) -m evalkit.runner $(E) --split $(or $(SPLIT),dev) --repeats $(or $(REPEATS),1)

eval-list: ## list the evaluation experiments (evalkit/experiments.py)
	PYTHONPATH=. $(PY) -m evalkit.runner --list

report:  ## build the evaluation tables from evalkit/results/experiment_log.csv
	PYTHONPATH=. $(PY) -m evalkit.report

gate:    ## CI eval gate: fail if dev Recall@5 drops below CI_MIN_RECALL_AT_5 (config.py)
	PYTHONPATH=. $(PY) scripts/check_threshold.py

up:      ## start everything with Docker (app, Prometheus, Grafana)
	docker compose -f docker/docker-compose.yml up --build

seed-demo: ## add three [DEMO] questions waiting for teacher approval
	PYTHONPATH=. $(PY) scripts/seed_demo.py
