VENV_PY := $(shell if [ -x ./.venv/bin/python ]; then echo ./.venv/bin/python; elif [ -x ./venv/bin/python ]; then echo ./venv/bin/python; else echo python; fi)
PY ?= $(VENV_PY)

.PHONY: help check setup ncert index run dev test app reflexion retrieval gate smoke eval report seed-demo up clean

help:
	@grep -E '^[a-z-]+:.*?##' $(MAKEFILE_LIST) | sed 's/:.*##/\t/' | column -t -s "$$(printf '\t')"

check:   ## preflight: python version, packages, API keys, index status
	$(PY) scripts/check_env.py

setup:   ## install dependencies, fetch NCERT PDFs and build the index
	$(PY) scripts/check_env.py || true
	$(PY) -m pip install -r requirements.txt
	$(PY) -m pip install --no-deps -e .
	$(PY) scripts/fetch_ncert.py
	$(PY) scripts/build_index.py --force
	$(PY) scripts/map_retrieval_chunks.py

ncert:   ## download the three NCERT chapter PDFs into data/ncert/ (git-ignored)
	$(PY) scripts/fetch_ncert.py

index:   ## rebuild the NCERT textbook hybrid index
	$(PY) scripts/build_index.py --force

run:     ## run one query: make run Q="Why is concave mirror image inverted?"
	$(PY) scripts/run_one.py "$(Q)" $(if $(S),--student $(S),)

dev:     ## run the team (C2) on the dev simulated students, red team and clean cases
	$(PY) -m evalkit.runner --config eval/configs/e1_c2.yaml --split dev

reflexion: ## run the L12 Reflexion loop to generate misconception teaching lessons
	$(PY) scripts/run_reflexion.py --dev-only

retrieval: ## test retrieval recall@5 only (no LLM calls)
	$(PY) scripts/evaluate_dev.py --retrieval-only

app:     ## launch the web service (student view :8000/, teacher view :8000/teacher)
	$(PY) -m socratic_tutor.app

gate:    ## CI eval gate: fail if dev Recall@5 drops below config/eval_thresholds.yaml
	$(PY) scripts/check_threshold.py

smoke:   ## offline plumbing check of every eval suite (stub model, never reported)
	EVAL_STUB=1 $(PY) -m evalkit.runner --config eval/configs/smoke.yaml --split dev --limit 3

eval:    ## run one experiment: make eval CONFIG=eval/configs/e1_c2.yaml SPLIT=dev REPEATS=1
	$(PY) -m evalkit.runner --config $(CONFIG) --split $(or $(SPLIT),dev) --repeats $(or $(REPEATS),1)

report:  ## build the evaluation tables from results/experiment_log.csv
	$(PY) -m evalkit.report

seed-demo: ## add three [DEMO] questions waiting for teacher approval
	$(PY) scripts/seed_demo.py

up:      ## start everything with Docker (app, vector store, Prometheus, Grafana)
	docker compose up --build

test:    ## run contract tests, guardrails & tool validation
	$(PY) -m pytest tests -v

clean:   ## remove index artifacts, caches, and run traces
	rm -rf .index .cache dev_traces.jsonl traces.jsonl results/runs results/traces
