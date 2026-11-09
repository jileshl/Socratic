VENV_PY := $(shell if [ -x ./.venv/bin/python ]; then echo ./.venv/bin/python; elif [ -x ./venv/bin/python ]; then echo ./venv/bin/python; else echo python; fi)
PY ?= $(VENV_PY)

.PHONY: help check setup index run dev test app reflexion clean

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
