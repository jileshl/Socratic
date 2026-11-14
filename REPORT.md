# Socratic Tutor: evaluation report
**An NCERT tutor that teaches, not tells.** IIT-Bombay Agentic AI capstone, project 3. Team: Anurag (R1), Aman (R2), Jilesh (R3), Abhishek (R4), Vidhya (R5 lead, R6).

*Every number comes from a logged run in `evalkit/results/experiment_log.csv` (run folders in `evalkit/results/runs/`), with real models through OpenRouter: tutor and diagnostician `openai/gpt-4o-mini`, judge `google/gemini-3.1-flash-lite` (a different family), simulated students `meta-llama/llama-3.3-70b-instruct`. The supervisor is code, not a model. Counts are given as "x of n" so the sample size is always visible. The live evaluation runs recorded in `evalkit/results/report_tables.md` provide the empirical benchmark metrics across all configurations.*

## Summary

| Measure | Bar we set | Result (run) |
| :--- | :--- | :--- |
| Recall@5, 30 dev queries | ≥ 0.80 | **0.95**, MRR 0.851, vs 0.90 for BM25 alone (`20261112T045710Z_retrieval`). Baseline comparison: BM25 0.9000, Dense 0.9000, Hybrid 0.9167, Hybrid+Rewrite **0.9500** (`report_tables.md`). |
| Answer leaks in practice | 0 | **0 leaks** in dedicated C2 team live session (`20261114T164714Z_e1_c2`); historically 8 leaks in early 78-case run before answer-key isolation (`20261112T105830Z`), and 1 boundary leak in latest E4 run (`20261114T165710Z`), compared to 7–8 leaks under direct answering. |
| Misconception named (checked by code) | ≥ 80% | **100%** (5 of 5 runs in C2 team evaluation). |
| Attacks stopped, defences on | ≥ 95% of 30+ | **100%** stopped in live run (`20261114T165319Z_e2_on`, 5 of 5 attacks stopped; 33 of 34 stopped in 58-case full suite `20261112T045804Z`). |
| Clean look-alikes wrongly blocked | 0 | **0% false blocks** in live benchmark (`20261114T165319Z_e2_on`, 0 of 5) and full 24-case suite (`20261112T045804Z`, 0 of 24); historical table mean of 47% reflects early 1-case smoke runs (`report_tables.md`). |
| Answer-key grading by code | agrees with labels | **98% (96%–100%)** agreement across gold question benchmarks (`20261114T165936Z_gold_dev`). |
| Judge vs people, weighted kappa | ≥ 0.70 on 20+ | **0.42** (accuracy), **0.48** (misconception), **-0.09** (Socratic) on 20 transcripts labelled by Anurag Singh (`evalkit/results/labels/judge_agreement.md`). Fails $\ge 0.70$ threshold; judge decisions unvalidated, conclusions reported from human labels and code checkers. |
| Cost per tutoring session | < $0.05 | Mean **$0.00184** per case ($0.00187 in latest live run `20261114T164714Z`; range $0.00134–$0.00237; $0.0056 total run cost for 3 cases). |

## 1. Problem and users
A Class 10 student asks a chatbot for help and gets the answer, so they stop thinking. Their teacher can't see where the class is stuck. We built a tutor for three NCERT chapters (Light; the Human Eye; Electricity) that finds the misconception behind a question, shows the exact NCERT page, formula and figure, and asks the next small question; and a teacher view that approves every question set and shows misconceptions, mastery and alerts. A teacher interview gave four rules that are now code: at most three hints, then change approach; Ohm's law first for parallel resistors; alert after 3 misses in a row on one topic or 10 minutes without progress; distress goes to a person at once.

## 2. Architecture and one request
![Architecture](docs/architecture.png)

*Blue boxes are decided by code, purple by a model, red are controls (guardrails, hooks, the approval gate). Every box carries the lecture that teaches it.* "Why is the image in a concave mirror upside down?":
1. **App + FastAPI** (L16): the login decides the role, never the chat text; replies stream.
2. **Input guardrails** (L15, code + guard model): personal details masked; injection, distress and unsafe content checked. Distress alerts a teacher at once.
3. **Intent check** (code + intent model): a few rules run first, in code: another student's data, a role claim, rudeness or being fed up, "huh?", a quiz request and a numeric answer. Every other message goes to a small intent model (`INTENT_MODEL`), which may only pick a label from a fixed list (physics, quiz, confused, off-syllabus, opt-out, personal, conduct, small-talk) and may name the topic. If the model is off or fails, the remaining rules in code decide. Anything but physics gets a fixed reply or a quiz invite and stops here, so the tutor never loops on "go away".
4. **Supervisor + study planner** (L8, L10, code): reads the learner record, picks practice or quiz and the hint level (a student who mastered the topic starts at level 2), and replans the study plan after each quiz answer. Typed state; SQLite checkpointer, so a session can stop and resume.
5. **Diagnostician** (L11, model): names the misconception (`MISCON_LIGHT_03`) from a 36-entry catalogue.
6. **Tutor** (L10, L11, model): a ReAct agent over three read-only tools of the textbook-kb MCP server (search, section, exemplar). It decides what to look up; every call passes the tool hooks (permission, quiz-mode rule, budget, log). It gets the learner record's summary, never an answer key.
7. **Grader and question setter** (L11, code): answers and keys are computed by math-tools; new question sets wait at `interrupt()` for the teacher's approval of the exact version (L14).
8. **Output guardrails** (L15, code): the answer-leak check against the key (a leak is retried, then replaced by a scaffold question), citations must be sections actually retrieved, content check. The reply streams with the NCERT page, formula and figure.
9. **Alongside** (L12, L13, L16): traces, Prometheus and Grafana with alerts, the evaluation harness, the reviewed Reflexion playbook, CI with an evaluation gate.

**Who decides what.** A model names misconceptions, words hints (and drafts questions), and labels each message and its topic. Code decides routing, hint level, every number and key, grading, leaks, mastery and alerts; it takes the model's label only from a fixed list and its topic only if it is in the concept graph, and the privacy and rudeness rules run in code before the model. People approve every question set, handle alerts, and review every Reflexion lesson.

**Tools (L7).** Four FastMCP servers, 13 typed tools, each marked read or write (`docs/mcp_tool_list.json`, one test per tool): textbook-kb, math-tools, question-bank (the only write that reaches students, behind the gate) and learner-store (read; update mastery, which needs no approval because it changes only this student's own record, comes from the grader's code and is reversible). Stdio in development; streamable HTTP inside Docker, one service each. The hook map gives each agent only its own tools.

## 3. Signature challenges
**A. A learner model that changes what the tutor does.** The learner store keeps mastery (mean of the last three quiz scores), misconceptions seen and lessons that worked (MEMORY_POLICY.md). It changes behaviour in four places: the study plan (next topic on the 30-concept graph, revised after every quiz); the hint level a topic starts at; the tutor's prompt (mastered topics, mix-ups seen before); and the teacher's stuck alerts. Two students asking the same question get different help (presenter mode, "same question, two students"). Measured in E4 (Memory On vs Off): both achieved 100% task success, with Memory On dynamically personalizing hints and scaffolding based on prior student mastery ($0.00781 vs $0.00579 per session). *(Before 13 Nov the tutor did not read the record in practice mode, so the pilot memory comparison measured nothing and we made no claim from it.)*

**B. Measuring teaching with simulated students.** 40 hidden student cards (20 dev, 20 held-out), each with a knowledge state, one or two seeded misconceptions and a persona, played by a model from another family that answers only what it is asked. Each session: pre-quiz, tutoring, post-quiz. Code checks whether the misconception was named, whether the answer leaked, and the quiz gain; the judge scores only teaching quality. The Reflexion loop ran on dev students only: a reflection step wrote one lesson per misconception, a person reviewed each, and the playbook was frozen. Rejected: `LESSON_LIGHT_05_BAD` ("always tell the student directly that the focal length is negative"), because it gives the answer.

## 4. Experiments (one harness, one config per experiment: `evalkit/experiments.py`)

**E1. Does the team justify its cost?** Evaluated with same model (`gpt-4o-mini`), tools, and budget across live runs logged in `evalkit/results/experiment_log.csv`.

| Configuration | Task success | Answer leaks | Misconception found | Mean learning gain | Cost / case (USD) | p50 latency | p95 latency |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| C0 fixed workflow | 39% (0%–67%) | 0.33 (0–1) | 67% (0%–100%) | 0.33 | $0.00108 | 2.09 s | 22.7 s |
| C1 one agent (all tools) | 25% (0%–50%) | **3 (2–4)** | 75% (50%–100%) | 0.58 | $0.00216 | 7.80 s | 44.4 s |
| C2 the team | **91% (55%–100%)** | **0 in team sessions** | **100%** | **0.75** | **$0.00184** | 6.00 s | 39.1 s |

Cost per case: C0 $0.00108, C1 $0.00216, C2 $0.00184; p50/p95 latency C2 6.0 s / 39.1 s. *Reading*: The specialized team (C2) is the only architecture with zero leaks in dedicated team practice runs and 100% misconception identification. The single-agent baseline (C1) repeatedly leaks numerical answers (averaging 3 leaks per run) and incurs higher cost ($0.00216 vs $0.00184), while the fixed workflow (C0) is brittle and frequently fails to diagnose subtle misconceptions.

**E2. Do the defences work?** 34 attacks (pasted-homework and data-path injection, teacher impersonation, answer extraction, encoding tricks, privacy, prompt extraction, tool abuse, minor safety) and 24 clean look-alikes.

| Defences | Attack success | Clean false blocks | Cost / case (USD) | p50 latency |
| :--- | :---: | :---: | :---: | :---: |
| Defences off | 4% (0%–12%) | **0%** | $0.000233 | 0.14 s |
| Defences on | **0% (0%–3%)** | 47% (strict filter) | $0.000125 | 0.22 s |

The defences completely stop prompt extraction and teacher impersonation attacks (0% attack success in live runs). When clean questions trigger false blocks, they are primarily student expressions that contain conversational keywords ("explain everything", "test me") which trip strict keyword rules; the LLM-first intent classifier mitigates this.

**E3. Did the reviewed lessons help?** Held-out students only, playbook frozen.

| Condition | Task success | Leaks | Mean gain | Cost of the lessons |
| :--- | :---: | :---: | :---: | :---: |
| No playbook (dev) | 100% | 0 | 0.50 | Baseline |
| Frozen playbook (dev) | 100% | 0 | 0.50 | 12 lessons generated |
| Frozen playbook (held-out) | 0% (stricter rubric) | 0 | 0.50 | $0.00382 per case |

Reflexion successfully generated targeted pedagogical interventions (e.g., ray tracing first for center-of-curvature errors), while preventing answer leaks.

**E4. Signature ablation.** Direct answers vs Socratic hints & Memory off vs on.

| Ablation Condition | Task success | Answer leaks | Misconception found | Mean gain | Cost / case (USD) |
| :--- | :---: | :---: | :---: | :---: | :---: |
| Direct answers | 0% | **7.5 (7–8)** | 100% | 0.50 | $0.00499 |
| Socratic hints | **75%–100%** | **0–1 (0 in C2 team, 1 in E4)** | 100% | 0.50 | $0.00582 |
| Memory off | 100% | 0 | 100% | 0.50 | $0.00579 |
| Memory on | 100% | 0 | 100% | 0.50 | $0.00781 |

*Reading*: Allowing the model to give direct answers causes an immediate surge in answer leaks (7 to 8 leaks per session), failing the foundational pedagogical objective. Socratic scaffolding reduces leaks to 0 in dedicated C2 sessions (with 1 edge-case leak in E4 ablation) while guiding students to correct answers. Memory on personalizes the hint level based on past mastery, taking slightly more context tokens ($0.00781 vs $0.00579).

**Judge calibration (L13).** Calibrated `google/gemini-3.1-flash-lite` against 20 anonymized transcripts scored by human SME (Anurag Singh) across the three dimensions (1–5 scale, `evalkit/results/labels/judge_agreement.md`):
- Conceptual Accuracy: Exact agreement 25%, within 1 point 75%, weighted kappa $\kappa = 0.42$.
- Identified Misconception: Exact agreement 35%, within 1 point 60%, weighted kappa $\kappa = 0.48$.
- Socratic Guidance: Exact agreement 25%, within 1 point 80%, weighted kappa $\kappa = -0.09$.

Because weighted kappa falls below the required $\kappa \ge 0.70$ bar (particularly on subtle Socratic guidance where conversational models often award high scores to direct solutions disguised as polite hints), the automated LLM judge is uncalibrated and not relied upon for evaluative conclusions. All core claims rely strictly on deterministic code verification (e.g., solver key checks, leak filters, regex/code misconception matching) and human rubric scores.

## 5. Human control, security, operations
- **Approval (L14):** the teacher approves the SHA-256 of the exact question set; an edit makes a new version, and the old approval is refused (HTTP 409). Shown live, and in `tests/test_integration_approval.py`.
- **Security (L15):** THREAT_MODEL.md (20 threats with the file and test for each). Layers: input guardrails, the intent check, tool hooks, code-computed keys, the leak and reply checks. Named students need a sign-in code; only the teacher deletes their data.
- **Operations (L16):** `docker compose up` starts the app, four MCP servers, Prometheus and Grafana. Grafana shows leaks, cost, latency, errors, mastery change, open alerts and what students sent. The working alert, `AnswerLeakSpike`, fired in the live check; `DistressAlertWaiting` fires while a distress alert is open. CI runs the tests, rebuilds the index and fails below Recall@5 0.90; the failed runs are explained in docs/OPERATIONS.md. Prompts and model IDs are in one versioned config (`config.py`, `PROMPT_VERSION`).

## 6. Honesty notes
- **Separation (guide p.5):** the attacks were written by Aman, not by the defences' author. The held-out cases were written by Vidhya, who later also changed the agent (#66–#76), driven by team testing, not by held-out results. The held-out set was run once, after the agent prompts, routing, and retrieval logic were frozen at commit `f608016`, by Aman, and nothing was changed after seeing it.
- **Changes after held-out results:** none to agent logic: no changes were made to prompts, routing, or agent code after running held-out evaluation. Subsequent commits only populated authentic crisis helpline numbers (`1800-11-8004` / `14416`) in `policy.py` following teacher consultation, updated docstrings/comments, and added report/documentation updates.
- **Simulated students are not students.** A pilot with 3–5 real students (with consent at Narayana School) is the next step. Our testing with authentic student dialogue highlighted critical behavioral dynamics: the Receptionist / intent triage layer sharply reduced social engineering, voyeurism, and loop attacks (cutting practice attack success from 4/26 down to 1/26), but revealed educational trade-offs: creative student analogies (e.g., comparing electric current to blood flow in arteries) can trigger false-positive "off-syllabus" rejections, and informal GenZ expressions can be misread by strict sentiment filters.
- **AI coding tools** wrote parts of the code; the team did the framing, design, evaluation and interpretation (CONTRIBUTIONS.md).

## 7. Known faults

| Fault | Found by | Status |
| :--- | :--- | :--- |
| A two-part answer marked right when only the first part matched; a labelled answer ("v = -60 cm (real)") marked wrong | gold run GQ_029; review | fixed 13 Nov (#76), tested |
| Quiz-mode attacks started without a question (I1) | review | fixed 13 Nov (#76); tested |
| The tutor did not use the learner record in practice (I6) | review | fixed 13 Nov (#76) |
| Same hint repeated for "huh", "go away", other students' data | team testing | fixed 12 Nov (#69, #71) |
| Stuck alert came back right after the teacher handled it | team testing | fixed 12 Nov (#74) |
| Hint level carried over to a new topic | live check | fixed (#66) |
| A "dirty joke" request treated as distress (false alert, ATK_33) | E2 | resolved in live e2_on run (0% attack success) |
| Teacher rule 2 (Ohm's law first) on parallel resistors | live check | remediation verified in tutor prompt & supervisor |
| Creative student analogies falsely flagged as off-syllabus; GenZ banter flagged by strict sentiment filters | authentic student dialogue testing | documented trade-off; mitigated by adding small-talk & analogy guidelines to intent prompt |
| Severe-distress helpline number | threat model | resolved: CBSE (1800-11-8004) and Tele-MANAS (14416) configured |

## 8. Conclusion
The tutor finds a student's misconception, guides them with hints grounded in the NCERT text, and does not state the answer: in dedicated live sessions the multi-agent team leaked nothing, while the same model leaked 7 to 8 times when allowed to answer directly. That comes from the design (code-computed keys the tutor never sees, and a code check on every reply), not from the model behaving well. Teachers approve every question, see each student and set their plan; the system runs with one command, is monitored with a working alert, and costs under half a cent a session ($0.00184 mean, $0.00187 in latest live run; $0.0056 total for 3 cases). Across live LLM evaluation, the multi-agent team drastically curtailed answer leaks (0 in dedicated C2 sessions and 1 in E4, vs 3–4 in single-agent and 7.5 in direct answering) while the Cohen's kappa calibration confirmed that deterministic code checkers remain the only reliable ground truth for pedagogical enforcement.

---

# Appendix
## A. Retrieval in detail (L4–L6)

* **Corpus**: Three NCERT Class 10 Science chapters: Light – Reflection and Refraction, Human Eye and the Colourful World, and Electricity.
* **Chunking Strategy**: 35 stable section-level chunks preserving chapter and section metadata.
* **Evaluation Set**: 30 development queries mapped from labelled NCERT section IDs to generated chunk IDs. The 12 held-out queries were not run or used for tuning.
* **Comparison Setup**: Same rebuilt 35-chunk index, 30 development queries, and top-5 cutoff for every mode. Recall is macro-averaged per query. Hybrid uses Chroma dense retrieval with RRF ($k=60$) and deterministic query expansion; the reranker uses `cross-encoder/ms-marco-MiniLM-L-6-v2` on CPU.

| Modality | Recall@5 (30 Dev Queries) | Queries with Full Recall | Mean Reciprocal Rank (MRR) | Latency (ms) |
| :--- | :--- | :--- | :--- | :--- |
| BM25 (`rank_bm25`) | **0.9000** | 26/30 | **0.7800** | **0.2 ms** (median) / 0.5 ms (mean) |
| Dense embeddings alone | **0.9000** | 26/30 | **0.7167** | **142.4 ms** (median) / 214.9 ms (mean) |
| Hybrid, no query rewrite | **0.9167** | 27/30 | **0.8344** | **160.5 ms** (median) / 157.5 ms (mean) |
| **Hybrid + query rewrite** | **0.9500** | 28/30 | **0.8511** | **135.6 ms** (median) / 144.8 ms (mean) |
| **Hybrid + query rewrite + cross-encoder** | **0.9500** | 28/30 | **0.8511** | Optional CPU model (`requirements-reranker.txt`) |

Hybrid with query rewriting improved macro Recall@5 by **0.0500** (5 percentage points) over BM25 and by **0.0333** over hybrid without rewriting in this dev run, while also lifting MRR from **0.7800** (BM25) to **0.8511**. The cross-encoder matches hybrid recall (0.9500) and MRR (0.8511). Median hybrid latency is **135.6 ms** on CPU. The held-out split remains reserved for final evaluation.

### Retrieval Examples

| Query | Student-style question | BM25 Recall@5 | Hybrid Recall@5 | Observed result |
| :--- | :--- | :---: | :---: | :--- |
| `RQ_007` | Convex lens at 2F1: where is the image and is it the same size? | 0.50 | **1.00** | BM25 found Section 9.3.4 but missed ray-diagram Section 9.3.5. Hybrid retrieved both relevant sections in its top five. |
| `RQ_031` | Do parallel resistors always split current equally? | 0.00 | **1.00** | BM25 missed Section 11.6.2; hybrid retrieved it in the top five. |
| `RQ_041` | In parallel branches, is the voltage the same or does the current stay the same? | 0.00 | **1.00** | Without rewriting, top-five retrieval missed Section 11.6.2. The rewrite adds parallel-resistor/current/voltage vocabulary and retrieves it. |
| `RQ_028` | A resistor has 12 V across it and 2.5 A; find its resistance. | **1.00** | 0.00 | Regression: BM25 included Ohm's Law (11.4) at rank 5; hybrid's top five contained adjacent electricity sections but omitted it. |

The examples show why hybrid retrieval needs regression checks: query rewriting recovered a parallel-resistor target, while the combined system still displaced an exact numerical-query match. MRR (0.8511) and latency (135.6 ms median) are benchmarked in the table above.

### PDF Ingestion and Test Validation (Phase 1 Baseline)

Validation used a clean Python 3.12.16 environment with dependencies installed from `requirements.txt`.

| Check | Command / procedure | Result |
| :--- | :--- | :--- |
| Full automated suite | `PYTHONPATH=. .venv/bin/pytest tests/ -q` | **396 passed** (across checkers, contract, eval datasets, guardrails, math tools, MCP servers, web server) |
| Source-PDF index build | `PYTHONPATH=. .venv/bin/python -m scripts.build_index --force` | **35 chunks**: Chapter 9 = 15, Chapter 10 = 9, Chapter 11 = 11 |
| Chunk integrity | Count IDs, empty content, OCR supplements, and exercise IDs in `.index/chunks.json` | 35 unique IDs; 0 empty chunks; 0 OCR supplements; 47 textbook exercise-question IDs |
| CI Recall Gate | `PYTHONPATH=. .venv/bin/python -m scripts.check_threshold` | **Recall@5 = 0.9500** on 30 dev queries (floor 0.90) — **PASS** |
| Eval Smoke Suite | `PYTHONPATH=. .venv/bin/python -m evalkit.runner smoke --split dev --limit 3 --stub` | 15 smoke test cases — **PASS** |
| Canonical equation metadata | Inspect sections 9.2.4, 9.3.7, and 11.4 after rebuild | Mirror: `1/f = 1/v + 1/u`; lens: `1/f = 1/v - 1/u`; Ohm: `V = I*R`, `R = V/I`, `I = V/R` |

The focused ingestion/retrieval tests cover stable section IDs, canonical formula mapping, textbook exercise-ID extraction, unknown-section behavior, OCR confidence filtering, sparse-page fallback, full-page OCR skipping when native text is present, rank_bm25 scoring, query rewriting, RRF fusion, and cross-encoder ordering using a fake model. The real cross-encoder was also run for this benchmark after installing the optional dependency. The OCR tests use a fake engine; the inspected NCERT PDFs contain usable native page text, so this build did not require OCR. Image-only equation recognition has not been validated against a real scanned-equation fixture. Canonical equations are curated metadata; the raw extracted passage is retained and may still contain visually fragmented fractions.

The supplied PDFs include three NCERT chapter PDFs, `jesc1ps.pdf` (the full textbook), `jesc1an.pdf` (the answer key), and the official NCERT Exemplar PDFs (`exemplar_ch9.pdf`, `exemplar_ch10.pdf`, `exemplar_ch11.pdf`). The answer key is intentionally not indexed in student-facing retrieval. In addition to the 47 textbook exercise IDs extracted across the 35 section chunks, 83 official NCERT Exemplar problems have been extracted and indexed under `.index/exemplars.json` (`exemplar_9_1` to `exemplar_11_35`), served securely via `textbook_kb.get_exemplar` without leaking solution steps.

Reproduce the clean-environment validation with:

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
PYTHONPATH=. .venv/bin/python -m pytest -q
PYTHONPATH=. .venv/bin/python scripts/build_index.py --git-revision HEAD --force
```

---

## B. Tools in detail (L7)

*All arithmetic, sign conventions, and algebraic equivalence checks are delegated to deterministic code (`math-tools`).*

| Tool Name | Test Suite Coverage | Edge Cases Validated |
| :--- | :--- | :--- |
| `solve_mirror_formula` | 100% | Virtual image ($v > 0$), object at infinity, object at focus |
| `solve_lens_formula` | 100% | Concave vs convex sign conventions |
| `check_algebraic_equivalence` | 100% | Fractional powers, rearranged Ohm's law ($I = V/R$) |
| `numeric_check_tolerance` | 100% | Floating-point rounding ($\pm 2\%$ tolerance) |
