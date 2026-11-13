#!/bin/bash
# The evaluation, with the real models (OPENROUTER_API_KEY in .env), in the Docker "eval" service.
# Run from the repository root:
#
#   bash scripts/run_experiments.sh dev        # development set: gold, retrieval, E1, E2, E4 (tuning allowed)
#   bash scripts/run_experiments.sh held-out   # held-out set, 3 repeats: E1 and E3. ONCE, after the code freeze,
#                                              # by someone who did not tune the agent (guide p.5). Nothing changes after.
#   bash scripts/run_experiments.sh judge      # judge agreement (Cohen's kappa) from the "Score conversations" labels
#   bash scripts/run_experiments.sh report     # rebuild evalkit/results/report_tables.md
#
# Every finished run is saved at once (evalkit/results/experiment_log.csv and runs/), so Ctrl+C is safe.
# Progress also goes to evalkit/results/run_experiments.log. A full dev pass costs well under $2 (Nov 2026 prices).
set -u
cd "$(dirname "$0")/.." || exit 1
MODE="${1:-dev}"
LOG="evalkit/results/run_experiments.log"
DC="docker compose -f docker/docker-compose.yml --profile eval"
COMMIT=$(git rev-parse --short HEAD 2>/dev/null || echo unknown)
say() { echo "[$(date '+%H:%M:%S')] $*" | tee -a "$LOG"; }
command -v caffeinate >/dev/null && { caffeinate -ims -w $$ & }   # keep a Mac awake while it runs

run() {
  say "START $*"
  out=$($DC run --rm eval "$@" --note "commit $COMMIT" 2>&1 | grep -E '^\{"run_id"|Error code: 40[12]|Traceback' | tail -3)
  echo "$out" | tee -a "$LOG"
  if echo "$out" | grep -q "Error code: 401"; then say "STOPPED: OpenRouter rejected the key in .env (401)."; exit 2; fi
  if echo "$out" | grep -q "Error code: 402"; then say "STOPPED: the key is out of credit (402). Add credit, then run this again."; exit 2; fi
  say "END   $1"
}

docker info >/dev/null 2>&1 || { echo "Start Docker Desktop first."; exit 1; }
grep -q "^OPENROUTER_API_KEY=." .env 2>/dev/null || { echo "No OPENROUTER_API_KEY in .env"; exit 1; }
say "==== $MODE, commit $COMMIT ===="
$DC build eval 2>&1 | tail -1 | tee -a "$LOG"

case "$MODE" in
  dev)
    run e1_c2 --split dev --limit 2 --workers 2            # cost check first
    for e in gold retrieval e2_off e2_on e1_c0 e1_c1 e1_c2 e4_direct e4_socratic e4_memory_off e4_memory_on e3_no_playbook e3_playbook; do
      run $e --split dev --workers 2
    done ;;
  held-out)
    echo "Held-out runs: once, after the freeze, by someone who did not tune the agent. Type yes to go on:"; read -r ok
    [ "$ok" = "yes" ] || exit 0
    run retrieval --split held_out --workers 1
    run gold --split held_out --workers 2
    for e in e1_c0 e1_c1 e1_c2 e3_no_playbook e3_playbook; do run $e --split held_out --repeats 3 --workers 2; done ;;
  judge)
    $DC run --rm --entrypoint python eval -m evalkit.calibrate score 2>&1 | tee -a "$LOG" ;;
  report)
    $DC run --rm --entrypoint python eval -m evalkit.report 2>&1 | tail -5 | tee -a "$LOG" ;;
  *) echo "usage: bash scripts/run_experiments.sh dev|held-out|judge|report"; exit 1 ;;
esac
$DC run --rm --entrypoint python eval -m evalkit.report >/dev/null 2>&1
say "==== done: evalkit/results/report_tables.md ===="
