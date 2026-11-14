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

- **Anurag:** Led pedagogical consultation with Class 10 Science faculty at Narayana School; designed the 5-module curriculum questionnaire; labelled 20 student response transcripts for judge calibration; authored demo script and validated concept graph and golden question sets.
- **Aman:** Designed and validated the hybrid retrieval pipeline (BM25 + Chroma embeddings + RRF) and query expansion rules; authored the red-team adversarial attacks suite (E2) and held-out test harness isolation; drafted memory policy under minor privacy constraints.
- **Jilesh:** Architected LangGraph multi-agent StateGraph, supervisor routing logic, agent prompts, and Reflexion improvement loop; led prompt tuning and intent classification improvements; conducted architecture reviews and integration testing.
- **Abhishek:** Engineered FastMCP math-tools with deterministic SymPy solvers, question-bank MCP server, and tool hooks; designed teacher approval gate with SHA-256 state signing; authored threat model (20 threats) and guardrail policies.
- **Vidhya:** Implemented FastAPI streaming backend and modern responsive student/teacher web UI; provisioned Docker Compose, Prometheus metrics, and Grafana alertmanager; curated 40 simulated student cards and gold question datasets; integrated MCP-over-HTTP and ReAct tutor architecture.

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
- Jilesh: Hardened the LangGraph supervisor loop by attributing quiz scores to the question's specific concept (N1), gating progression on rolling mastery averages rather than single scores (N2), safely halting replanning on unapproved questions (N3), and capping hint ladder escalations to at most once per turn (N4).
- Jilesh: Fixed test suite failures by integrating Reflexion lesson retrieval and quiz grading into the LangGraph supervisor loop, hardening math answer-key parsing, and updating contract tests.
- Abhishek: tests: pin the MCP tool list (R4 threat model, T3)
- Abhishek: THREAT_MODEL.md: rewrite so every claim is true in code (R4 Stage 6)
- Abhishek: grader: never show the checker's detail to the student (quiz key leak)
- Abhishek: THREAT_MODEL.md: restore what the rewrite dropped from the scaffold page
- Abhishek: grader: ask the LLM for is_correct, so fail-closed doesn't mark every rubric answer wrong
- Jilesh: Missing Implementation Gaps & Architecture TODOs 1.  Question Setter Solver Integration 2. NCERT Exemplar Ingestion 3. Signature Challenge A (Two-Student Comparison) 4. Automated Retention Expiry 5. Cryptographic Deletion Receipt
- Jilesh: Resolved architecture gaps: solver pre-computation for question setter, exemplar ingestion, two-student differential demo, and DPDP retention expiry with deletion receipts.
- Jilesh: Refactored codebase imports by moving all lazy and function-level imports to module-level across agents, tools, web, and evaluation suites.
- Jilesh: Updated evaluation report with architecture details, baseline comparisons, and empirical findings.
- Jilesh: Generated evaluation report tables, streamlined Makefile test/run targets, and prepared deployment configurations.
- Vidhya: Review fixes on main: concave-lens power sign; stub runs stay out of the report
- Vidhya: Student and teacher apps for real use; demo tools in presenter mode; Grafana and alert fixes
- Vidhya: Cap model replies at LLM_MAX_TOKENS (1500) so low-credit keys work
- Vidhya: Study plans, student names and a student picker; clearer hints and approval log; tests no longer write to the app's databases

### 2026-11-12

- Jilesh: Fixed deterministic math solver formula aliases (FORMULA_ALIASES for mirrors, lenses, and circuits) and resolved answer-key computation crashes during question proposal.
- Jilesh: Upgraded fallback question selection to support difficulty tiers (easy, medium) and split compound prompts into single-value keys compatible with automated math grading.
- Jilesh: Standardized GUARD_SYSTEM_PROMPT safety categories to match the complete Llama Guard taxonomy (S1–S14) for minor protection.
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
- Jilesh: Prevented endless Socratic questioning loops by having the tutor validate correct student explanations and transition them to quizzes, while preserving chapter context across graph turns.
- Jilesh: Eval test against live LLM calls
- Vidhya: Fixes from team testing: student picker always shown, flashcards turn over in every browser, empty class list explains what to do
- Vidhya: Calm handling of study frustration; tutor changes approach  after the last hint; real transcripts for labelling
- Jilesh: updating experiment log
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

### 2026-11-14

- Anurag: Fix flashcard "Ask Tutor" routing and anchor retrieval strictly within active topic chapter
- Jilesh: Strictly anchor figure selection to active chapter and ensure cross-chapter citation consistency (BUG-03)
- Jilesh: Integrate Narayana School teacher consultation findings, configure authentic crisis helplines, and ingest Cohen's kappa calibration
- Jilesh: Complete live LLM evaluations across all suites (E1–E4, Gold, Retrieval) with zero pending markers in REPORT.md
- Jilesh: Add Teacher Prince Kumar credit, NCERT source attribution, and live student diagram feedback to README.md and DEMO.md
- Abhishek: Align THREAT_MODEL.md, intent classifier, and student UI terminology with exact runtime GUARD_MODEL configuration
- Jilesh: Package final submission archive (submission.zip) with full verification of reproducible one-command setup