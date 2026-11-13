# Contribution log

Who did what on the Socratic Tutor capstone (IIT-Bombay Agentic AI, project 3), taken from the git history of `jileshl/Socratic` (20 Oct to 13 Nov 2026). The guide asks for a contribution log kept from the first day (p.4) and a record of decisions (p.17).

**How to read it.** Counts are commits that are not merges, by author name (two people sometimes committed under another's e-mail, so names decide). Commits measure activity, not effort: pair work, reviews, the teacher interview and the labelling are not in git, so each person adds those under *Not in git* below. AI coding tools wrote parts of the code; the team did the framing, design, evaluation and interpretation, and reviewed every pull request (guide p.17).

## Summary

| Person | Role | Commits | Main areas in git |
| :--- | :--- | ---: | :--- |
| Anurag | R1 Domain and product lead | 2 | Concept graph, README and index build settings, BM25 baseline; teacher interview and demo script (not in git) |
| Aman | R2 Knowledge and memory engineer (co-owner R5: attacks, held-out run) | 6 | Hybrid retrieval and query rewriting (retrieval.py, kb.py), retrieval evaluation, memory policy, report sections; red-team attacks |
| Jilesh | R3 Agents and orchestration engineer | 44 | LangGraph graph and agents, prompts, Reflexion loop, evaluation runs of 11 Nov, loop fixes (#65, #70), dynamic home question (#75) |
| Abhishek | R4 Tools, control and security engineer | 63 | math-tools, question-bank and textbook-kb MCP servers, tool hooks, approval gate and signing, guardrails, threat model |
| Vidhya | R6 Deployment and operations engineer (and R5 evaluation lead) | 39 | FastAPI service, student and teacher apps, Docker Compose, Prometheus/Grafana and alerts, CI, evaluation harness data (40 student cards, 64 gold questions), 12 Nov runs, NCERT book lessons and figures, intent check, review fixes, MCP-over-HTTP and ReAct tutor (#76) |

The guide's two separations (p.5): the attacks were written by Aman (R2/R5), not by the defences' author (Abhishek, R4). The held-out cases were written by Vidhya, who later also changed the agent (#66 to #76); the held-out set is therefore run once, after the code is frozen, by Aman, and nothing is changed after seeing it (REPORT.md, section 6).

## Not in git (each person: add yours)

- **Anurag:** [to add by Anurag: reviews, meetings, the teacher interview, labelling transcripts, testing]
- **Aman:** [to add by Aman: reviews, meetings, the teacher interview, labelling transcripts, testing]
- **Jilesh:** [to add by Jilesh: reviews, meetings, the teacher interview, labelling transcripts, testing]
- **Abhishek:** [to add by Abhishek: reviews, meetings, the teacher interview, labelling transcripts, testing]
- **Vidhya:** [to add by Vidhya: reviews, meetings, the teacher interview, labelling transcripts, testing]

## Decisions

Design decisions with their reasons are recorded where they apply: THREAT_MODEL.md (defences), MEMORY_POLICY.md (what is stored), TEAM_ROLES (roles and separations), docs/INTEGRATION_CONTRACT.md (interfaces), and the pull request descriptions (#1 to #76). The main ones:

- The supervisor is code, not a model: routing must be predictable and testable ("the model proposes; code and people decide").
- Answer keys and grading are computed by math-tools; the tutor never holds an answer key, and a code check reads every reply for leaks.
- Approval is tied to the SHA-256 of the exact question set; any edit makes a new version that needs its own approval.
- Names live only in the teacher's roster; models, traces and the learner store see a random ID. Named students sign in with a 4-digit code (13 Nov).
- An intent check in code answers off-topic, rude or other-student messages before any model runs (12 Nov, after team testing found loops).
- The tutor became a ReAct agent over its MCP tools, and the MCP servers run over HTTP in Docker (13 Nov, after checking against the guide).
- Held-out cases live in evalkit/held_out/, outside the app image (13 Nov).

## Dated log

### 2026-10-20

- Jilesh: Enhance README with project details and guidelines
- Jilesh: Add comprehensive Python .gitignore file
- Jilesh: Add BSD 2-Clause License file
- Jilesh: Add requirements.txt for project dependencies
- Jilesh: Create .env.example with API key and options
- Jilesh: Create kb
- Jilesh: Create dev_gold!.json
- Jilesh: Add initial student queries to dev_queries.json
- Jilesh: moving files

### 2026-10-21

- Jilesh: Aritecture Framework
- Jilesh: renaming todo's
- Jilesh: chapters and school outreach
- Jilesh: questionnaire

### 2026-10-24

- Abhishek: REPORT.md: redraw architecture (teacher lane, agent loop, hooks)

### 2026-10-25

- Anurag: Add validated curriculum data and retrieval baseline

### 2026-10-26

- Anurag: Address document path and data directory review

### 2026-10-29

- Abhishek: Add TEAM_ROLES.md: proposed role split and TODO ownership

### 2026-11-01

- Aman: Modifed BM25 to Hybrid Search Slight improvement in Recall
- Aman: Improve textbook equation extraction
- Aman: Modifed retrival pipeline further

### 2026-11-02

- Jilesh: Update gold_questions.jsonl
- Jilesh: Update requirements.txt

### 2026-11-03

- Abhishek: math-tools: shared result helpers, charge/current solver, Ohm's law rewrite, tests

### 2026-11-04

- Abhishek: math-tools: add V = W/Q solver (solve_voltage_work_charge), flowchart comments, tests
- Abhishek: math-tools: unit converter, wire area, resistivity solver, tests
- Abhishek: math-tools: series and parallel resistance solvers, tests
- Abhishek: math-tools: power solver P = I^2 x R, energy cost solver, tests
- Abhishek: math-tools: Joule heating, P = VI, P = V^2/R and energy solvers, tests

### 2026-11-05

- Abhishek: math-tools: mirror and lens solvers, magnification, image height and nature, tests
- Aman: Complete learner memory TODO 4
- Abhishek: math-tools: lens power, lenses in contact, refractive index solvers, speed units, tests
- Abhishek: math-tools: answer reading, numeric and equivalence checks, calculate, convert_from_si, tests
- Abhishek: grader: check numeric answers with units in code (check_numeric_answer)

### 2026-11-06

- Vidhya: R5: evaluation datasets, appended to the team's data files
- Vidhya: R5: evaluation harness in evalkit/
- Vidhya: R6: web service, teacher view, docker/ folder, metrics and tracing
- Vidhya: Docs: evaluation, operations, integration contract; README section
- Vidhya: Fewer config files: monitoring settings inline in compose, CI steps in the Makefile
- Abhishek: math-tools: SymPy imports at the top, letters from string.ascii_letters, English-only formula gate
- Abhishek: mcp: math-tools MCP server (official SDK, 7 read-only tools), tool list export, tests

### 2026-11-08

- Aman: Fixed for the comments
- Aman: added exercise IDs
- Abhishek: config: DOCS_DIR for generated documents, relative to the repository
- Abhishek: export_tool_list: output folder from config, no sys.path change (review)

### 2026-11-09

- Vidhya: Use the team's calculator for every answer key; commands that work on Windows
- Vidhya: Create ci.yml
- Vidhya: Docker: install the CPU torch wheel first so the image fits on the CI runner
- Vidhya: CI: install CPU-only torch on the runner too (make ci-deps); document the 9 Nov failures
- Vidhya: CI: install dependencies with make ci-deps (CPU-only torch)
- Vidhya: OPERATIONS.md: link the first green CI run
- Abhishek: mcp: question-bank MCP server (one write tool, propose_question), tests
- Jilesh: Updated Report.md
- Jilesh: Phase 2: LangGraph multi-agent team and pedagogical rules
- Jilesh: updaring todo
- Jilesh: Learner Memory & Reflexion Improvement Loop
- Jilesh: Centralized Prompts
- Abhishek: textbook_kb: search_textbook filters by chapter (and class), tests
- Abhishek: mcp: textbook-kb MCP server (3 read tools: search, section, exemplar), tests

### 2026-11-10

- Jilesh: SuperVisior Loop
- Jilesh: missed files
- Abhishek: question_bank: question-set functions for the approval gate, tests
- Abhishek: approval gate: teacher approval of question sets (interrupt, signed, all or nothing), tests, demo
- Abhishek: approval gate: propose_set and get_approval_graph for the question setter and the teacher view, tests
- Jilesh: addressing review feedback
- Jilesh: adding chapter
- Abhishek: question_bank: keep the set transaction short; reads outside, optimistic check in the UPDATE (review)
- Abhishek: config: APPROVAL_SIGNING_KEY, the approval gate's server-only signing key (review)
- Abhishek: approval gate: read the signing key from config.APPROVAL_SIGNING_KEY (review)
- Abhishek: .env.example: list every setting the code reads, incl. APPROVAL_SIGNING_KEY (review)
- Abhishek: config: per-turn tool budget (MAX_TOOL_CALLS_PER_TURN, MAX_IDENTICAL_TOOL_CALLS)
- Abhishek: hooks: tool_hooks.py (permission map, quiz rule, student scope, budget, log, kill switch), tests, demo

### 2026-11-11

- Abhishek: config: GUARD_MODEL and GUARD_MODELS switch for the guardrails (R4)
- Abhishek: tests: guardrail model calls are off in all tests (R4)
- Abhishek: Guardrails: input and output checks, Llama Guard 4, quarantined reader (R4 Stage 5)
- Jilesh: resolving N1, N2, N3, N4
- Jilesh: Ran check git status Ran run tests · Exited with code 2 Ran check python environment Ran run pytest with venv · Exited with code 2 Ran run pytest with PYTHONPATH Ran find files related to lessons and misconceptions Analyzed reflexion.py:L1-36 Analyzing reflexion_playbook.json:L1-100 Canceled grep for MISCON_ELEC_01 Checked task Grep for MISCON_ELEC_01 Killed task Grep for MISCON_ELEC_01 Ran grep for MISCON_ELEC_01 excluding venv Ran list data directory Ran grep for reflexion Analyzed run_reflexion.py:L1-25 Ran grep for consumed in series · Exited with code 1 Ran check git log for MISCON_ELEC_01 Ran check git log for reflexion_playbook.json Ran list all branches Ran show reflexion_playbook.json from commit 09f3bae52ced4a32d43eac6c6f651c01c27307e2 Ran check git log on current branch Ran log of data/reflexion_playbook.json on current branch Ran check branches containing commit Ran check diff between HEAD and PHASE-4 Ran check misconception IDs in misconceptions.json Ran check diff of reflexion.py Ran check diff of run_reflexion.py Ran find calls to record_quiz_result Canceled search for record_quiz_result in whole repo Killed task Search for record_quiz_result in whole repo Analyzed graph.py:L150-300 Analyzed graph.py:L380-450 Analyzed graph.py:L451-540 Analyzed graph.py:L541-600 Ran check grader.py for record_quiz_result · Exited with code 1 Ran git log for record_quiz_result Ran check recent commits to graph.py Analyzed graph.py:L530-555 Analyzed question_bank.py:L1-72 Ran grep for teacher_approval in tests Canceled grep for teacher_approval_payload Killed task Grep for teacher_approval_payload Ran check approval-gate in git log Ran log of r4/approval-gate branch Ran diff stat with r4/approval-gate Ran check hash in approval_gate.py Ran look at def payload_hash Analyzed tutor.py:L1-60 Analyzed test_contract.py:L860-920 Ran git log for hint_step in graph.py Ran check commit 5797441 on graph.py Analyzed graph.py:L95-140 Ran search for practice mode in tests Analyzed server.py:L100-160 Analyzed server.py:L161-220 Canceled grep for check_answer_leak Killed task Grep for check_answer_leak Ran grep for student_attempt excluding git and venv Ran git log for student_attempt in graph.py Ran git log for expected_answer Ran check 06a430b graph.py Ran search practice_problems Ran search current_question_id in web Ran search gold_answer Analyzed grader.py:L1-22 Ran find check_numeric_answer in math_tools.py Ran check gold answers with equals sign Ran test read_quantity with label Ran read head of gold_question_checks.jsonl Analyzed question_bank_server.py:L215-250 Analyzed test_eval_isolation.py:L1-29 Edited reflexion.py Edited run_reflexion.py Ran run scripts/run_reflexion.py Analyzed reflexion_playbook.json:L1-50 Analyzed reflexion_playbook.json:L51-66 Ran read read_quantity definition in math_tools.py Analyzed math_tools.py:L1220-1264 Ran test extract_quantities Ran search check_numeric_answer in test_math_tools.py Analyzed test_grader.py:L1-58 Edited grader.py Analyzed graph.py:L1-35 Edited graph.py Analyzed graph.py:L175-285 Edited graph.py Analyzed graph.py:L300-370 Analyzed graph.py:L215-285 Analyzed graph.py:L555-600 Edited graph.py Edited graph.py Analyzed graph.py:L210-235 Analyzed graph.py:L270-380 Edited graph.py Edited graph.py Ran run tests to verify no regressions Checked task Run tests to verify no regressions Analyzed test_grader.py:L1-58 Edited test_grader.py Analyzed test_contract.py:L910-934 Edited test_contract.py Ran run newly added tests · Exited with code 1 Analyzed test_contract.py:L1-30 Edited test_contract.py Ran re-run newly added tests Checked task Re-run newly added tests Ran run entire test suite Checked task Run entire test suite Checked task Run entire test suite Timed 5s Checked task Run entire test suite Ran wait 2 seconds Ran check git status
- Abhishek: tests: pin the MCP tool list (R4 threat model, T3)
- Abhishek: THREAT_MODEL.md: rewrite so every claim is true in code (R4 Stage 6)
- Abhishek: grader: never show the checker's detail to the student (quiz key leak)
- Abhishek: THREAT_MODEL.md: restore what the rewrite dropped from the scaffold page
- Abhishek: grader: ask the LLM for is_correct, so fail-closed doesn't mark every rubric answer wrong
- Jilesh: missed files
- Jilesh: Missing Implementation Gaps & Architecture TODOs 1.  Question Setter Solver Integration 2. NCERT Exemplar Ingestion 3. Signature Challenge A (Two-Student Comparison) 4. Automated Retention Expiry 5. Cryptographic Deletion Receipt
- Jilesh: ### 1. Moved Imports from Function Calls to Top-Level All function-level and lazy `import` statements across the codebase were moved to module-level imports at the top of their respective files: - **`socratic_tutor/web/api.py`**: Moved `SqliteSaver`, `build_graph`, `textbook_kb`, and `Command` to top-level. - **`socratic_tutor/tools/question_bank.py`**: Moved `import uuid` to top-level. - **`socratic_tutor/app.py`**: Moved `import uvicorn` to top-level. - **`socratic_tutor/trace.py`**: Moved `config` and `BaseCallbackHandler` to top-level. - **`socratic_tutor/kb.py`**: Moved `numpy as np`, `PdfReader`, and `RapidOCR` to top-level. - **`socratic_tutor/retrieval.py`**: Moved `chromadb` to top-level. - **`evalkit/runner.py`**: Moved `import os` to top-level. - **`evalkit/answer_keys.py`**: Moved `from evalkit.checkers import numbers_in` to top-level. - **`evalkit/llm_client.py`**: Moved `ChatOpenAI` and `team_llm` to top-level. - **`evalkit/systems.py`**: Moved `InMemorySaver`, `build_graph`, `textbook_kb`, `tool`, `create_react_agent`, `BaseModel`, `Field`, `LearnerStore`, `math_tools`, and `prompts` to top-level. - **`evalkit/ablations.py`**: Moved `policy`, `LearnerStore`, and `ReflexionPlaybook` to top-level. - **`evalkit/suites.py`**: Moved `grade_answer`, `textbook_kb`, `RunnableLambda`, `answer_keys`, `LearnerStore`, `question_bank`, `HybridRetriever`, and `json` to top-level. - **`tests/test_eval_datasets.py`**: Removed redundant inline `import json`.
- Jilesh: updating report
- Jilesh: Generated Reports and updated Make file. Pending vercel settings to deploy
- Vidhya: Review fixes on main: concave-lens power sign; stub runs stay out of the report
- Vidhya: Student and teacher apps for real use; demo tools in presenter mode; Grafana and alert fixes
- Vidhya: Cap model replies at LLM_MAX_TOKENS (1500) so low-credit keys work
- Vidhya: Study plans, student names and a student picker; clearer hints and approval log; tests no longer write to the app's databases

### 2026-11-12

- Jilesh: fixing
- Jilesh: Selection & Grading Compatibility
- Jilesh: updated guard system prompts
- Abhishek: graph: show the guardrail's own replies, run check_reply on every reply, pass the student's text to the leak check
- Abhishek: question_bank: list approved questions for students, without their answer keys
- Abhishek: web: the quiz page sends the question being answered; distress alerts only for distress
- Abhishek: tests and .dockerignore for R4 plumbing PR-1
- Jilesh: addressing review feedback
- Abhishek: graph: review fixes for PR-1 (leak rule, quiz feedback, one citation rule)
- Abhishek: policy: link patterns no longer eat physics text
- Abhishek: web: review fixes for PR-1 (what the student sees, quiz page races)
- Abhishek: evalkit, seed_demo: E2 also switches off the reply check; demo keys the grader can read
- Abhishek: tests and .dockerignore: PR-1 review fixes
- Jilesh: fixing test
- Abhishek: solver_key: the solver computes every answer key from the setter's structured draft
- Abhishek: approval_gate: waiting_sets lists every question set waiting for the teacher
- Abhishek: graph: the question setter proposes one solver-keyed set through the approval gate; the graph's own gate is retired
- Abhishek: graph: the tutor's search and the grader's check go through R4's tool hooks
- Abhishek: grader: numeric checks through R4's tool hooks when the graph's state is given; blocked = fail closed
- Abhishek: tests: R4 plumbing PR-3, the tool hooks in the real graph
- Abhishek: grader: ONE hooked check per grade (review fix); blocked grade says 'can't check'
- Abhishek: graph: a check blocked by the tool hooks raises no teacher alert (review fix)
- Abhishek: tests/conftest: fresh tool-hook counts for every test (review fix)
- Abhishek: tests: PR-3 review fixes (private learner store, the two budget regressions)
- Abhishek: web: teachers propose question sets and decide them through the approval gate, signed on the server
- Abhishek: tests for R4 plumbing PR-2: approval wiring and the solver key, end to end
- Abhishek: README: the approval signing key in the setup line; the graph without its old gate node
- Abhishek: THREAT_MODEL: the approval gate is wired in by PR-2; keys come from the solver
- Abhishek: solver_key, approval_gate: review fixes for PR-2 (units, give-aways, stale edits, the set list)
- Abhishek: graph, question_setter: review fixes for PR-2 (the teacher is told about fallback questions)
- Abhishek: web: review fixes for PR-2 (stale edits, unsaved edits, a broken list)
- Abhishek: tests for PR-2 review fixes: a stale edit from a second tab, a broken list, fallback questions
- Vidhya: Flashcards, points, levels, badges and streaks for students; class highlights and shout-outs for teachers
- Vidhya: Evaluation results from logged runs, limits and conclusion (R5/R6)
- Vidhya: REPORT.md: apply Aman's review findings I1, I3/I4 and I6 to E2, E3 and E4
- Vidhya: Fixes from team testing: student picker always shown, flashcards turn over in every browser, empty class list explains what to do
- Vidhya: Calm handling of study frustration; tutor changes approach  after the last hint; real transcripts for labelling
- Jilesh: fixing loop
- Jilesh: updated labels with live call
- Vidhya: Fixes from team testing: student picker always shown, flashcards turn over in every browser, empty class list explains what to do
- Vidhya: Calm handling of study frustration; tutor changes approach  after the last hint; real transcripts for labelling
- Jilesh: updating experiment log
- Jilesh: updated to_label.csv
- Jilesh: Ran search for duplicate error message Analyzed question_bank_server.py:L370-430 Analyzed question_bank_server.py:L230-280 Analyzed question_bank_server.py:L280-320 Ran query Q_d36977a8 and Q_8461c1ba Ran check temperature in llm.py Analyzed llm.py:L1-41 Ran list functions in question_bank.py Ran check existing questions for concept_ohms_law Ran find propose_set in approval_gate Analyzed approval_gate.py:L745-800 Ran find all usages of drafts_for_concept Ran test select_question for concept_ohms_law Ran test question generation with temperature=0.7 and avoid list Ran test medium question generation Ran search for concept_ohms_law in tests Analyzed test_solver_key.py:L275-305 Analyzed test_integration_approval.py:L265-295 Analyzed test_integration_approval.py:L40-75 Analyzed llm.py:L20-41 Edited llm.py Analyzed prompts.py:L60-75 Edited prompts.py Analyzed question_setter.py:L35-120 Edited question_setter.py Edited question_setter.py Analyzed solver_key.py:L630-660 Analyzed solver_key.py:L655-667 Edited solver_key.py Ran run all approval and question tests Checked task Run all approval and question tests Checked task Run all approval and question tests Checked task Run all approval and question tests Ran live test question drafting and proposal for concept_ohms_law Ran check git status
- Vidhya: Hint grows only when the student asks for more help; a new question can move to its own topic
- Vidhya: Teach from the NCERT book: real excerpts, figures and formulas; learn a topic from the start; behind-the-scenes panel
- Vidhya: Figures that fit the question; a four-step learning path for a first-time student
- Vidhya: Behind the scenes names the model behind each step; the supervisor is labelled code (it routes by rules and calls no model)
- Vidhya: Figures picked across the whole book by rarity-weighted word match (near point -> human eye, blackboard -> myopia, twinkling stars -> 10.9); no stock buttons under replies
- Vidhya: Side panel: the workflow as a flowchart; the path the last message took lights up step by step, each step with who decides and the model behind it
- Jilesh: adding fix for all the concepts.
- Vidhya: Quiz and flashcards with the NCERT figure that fits; after a right answer, mastery and a level-up banner; after a wrong one, revision flashcards on the same topic; workflows for quiz, flashcards and lessons
- Vidhya: In a narrow window the behind-the-scenes panel opens as a drawer from a 'How it works' button (it used to drop below the page)
- Jilesh: Across all chapters in NCERT Class 10 Science, standard calculations round to 2 decimal places:
- Vidhya: Stuck alerts are per topic, and progress closes them
- Vidhya: Stuck alerts are per topic, and progress closes them
- Vidhya: Figures stay in the topic's chapter (a concave-mirror question no longer picks the eye chapter's concave-lens figure)
- Vidhya: Book card opens the section the reply names first, then the topic's own sections
- Vidhya: Intent check: stop the same hint looping on off-topic, rude and other-student messages
- Vidhya: Learn flow: no nagging banner, catch frustration and keyboard mashes, stay on the lesson topic
- Jilesh: fixing looping and null
- Vidhya: Change topic from the chat: Back to all topics, logo goes home, clear questions move the tutor
- Vidhya: Team review fixes: classmates' records, alerts that come back, intent gaps, quiz feedback, monitoring

### 2026-11-13

- Vidhya: Close the guide gaps: tutor as a ReAct agent over MCP, MCP over HTTP in Docker, learner-store server, learner model in the tutor, held-out folder, grader and harness fixes

