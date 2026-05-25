# AFK Engine — Design Document

**Status**: Design phase complete. Implementation in progress.

This document captures the final architecture decisions made during the 2026 grill-me design session for the new deterministic AFK system.

## Goals

- Remove non-deterministic judgment from the main orchestrator ("Very Thin Runner").
- Make the AFK decision logic explicit, centralized, reviewable, and highly testable.
- Create a single, reliable high-level entrypoint that can be called by a minimal orchestrator.
- Support rich observability and best-effort progress.
- Keep the system maintainable and evolvable.

## Core Philosophy

- **The engine is the brain.** It owns:
  - State machine / decision logic
  - Prompt generation (including mandatory checklists)
  - Worktree lifecycle decisions
  - Safe mutations (labels, session file, worktree ops)
- **The main agent is a Very Thin Runner.** It only:
  - Calls the engine's high-level entrypoint
  - Executes `SpawnRequest`s returned by the engine
  - Handles truly external events (user "stop", manual intervention)

## Key Components

### 1. High-Level Entry Point

**Function**: `run_afk_cycle(dry_run=False, apply_changes=True, ...) -> AFKCycleResult`

This is the primary (and normally only) function the thin orchestrator calls.

Responsibilities:
- Gather raw state
- Build rich `IssueSnapshot`s + `AFKContext`
- Run the state machine
- Translate decisions into a concrete `AFKPlan`
- Apply safe parts of the plan (best effort)
- Return a rich result containing `SpawnRequest`s and full diagnostics

The function always returns a result (never raises on normal failures). Errors are reported in the result.

**#26 Update (Comprehensive Error Handling & Resilience):** The engine now provides full phase isolation (snapshot with retry, per-item SM, translator, apply), rich structured `errors` in `AFKCycleResult`, and recovery strategies. See engine.py docstring and implementation for thin runner guidance on `.errors`/partial results (log/inspect per-phase; retry transients; proceed on partial; escalate only persistent). This fulfills the issue goal + reviewer feedback on snapshot reporting.

### 2. Data Model (see `data_models.py`)

Core types include:
- `IssueSnapshot`: Rich per-issue view (labels, blockers, worktree status, recent AFK history, retry count, derived phase, etc.)
- `AFKContext`: Session-level and cross-cutting information
- High-level `Action` variants (`SpawnImplementor`, `SpawnReviewer`, `ApplyLabelChanges`, `RequestWorktreeCleanup`, `EscalateToHuman`, `NoOp`)
- `AFKPlan`: List of concrete `PlanItem`s
- Rich `SpawnRequest` (self-contained: full prompt, worktree, branch, role, reason)
- `AFKCycleResult`: Final output to the runner (spawns + plan + applied changes + notes + errors)

### 3. State Machine (`state_machine.py`)

Primary function: `decide_next_action(issue: IssueSnapshot, context: AFKContext) -> Action`

Design:
- Relatively flat dispatcher based on current AFK phase.
- Delegates to focused, well-named policy helper functions.
- Returns high-level declarative actions (not concrete plan items).

The code itself is intended to be the clearest and most authoritative specification of the AFK rules.

### 4. Translation Layer (`translator.py`)

Converts high-level `Action`s into a concrete `AFKPlan`.

- Uses a dispatcher + per-action handler functions.
- Responsible for generating rich, self-contained `SpawnRequest`s (including full prompts and checklist references).
- Does **not** make new policy decisions — it faithfully materializes decisions made by the state machine.

### 5. Apply Layer (`apply.py`)

Applies the safe, non-spawn parts of an `AFKPlan`:
- GitHub label mutations
- `.grok/afk-session.json` updates
- Worktree creation/cleanup

Characteristics:
- Best-effort by default (we prefer partial progress over total failure).
- Returns detailed success/failure reporting.
- Supports dry-run mode.

### 6. Snapshot Builder (`snapshot_builder.py`)

Separate deterministic component that turns raw data (GitHub + filesystem + session file) into rich `IssueSnapshot`s and an `AFKContext`.

This separation enables:
- Fast, pure unit tests of the state machine using hand-crafted snapshots.
- Independent evolution of data gathering logic.

### 7. Thin High-Level Coordinator (`engine.py`)

The `run_afk_cycle` function coordinates the other modules but contains minimal logic itself.

## Module Structure

```
.grok/skills/afk/
├── __init__.py
├── engine.py                 # Thin coordinator + run_afk_cycle
├── data_models.py            # All core types
├── state_machine.py          # decide_next_action + policy helpers
├── translator.py             # Action → AFKPlan (including prompt gen)
├── apply.py                  # Safe mutation application
├── snapshot_builder.py       # Raw data → rich snapshots + context
├── cli.py                    # Command line interface
└── tests/
    └── ...                   # Fast, isolated tests (especially state machine)
```

## Testing Philosophy

- **Decision logic must be fast and pure.** The vast majority of state machine tests use hand-crafted `IssueSnapshot` + `AFKContext` objects.
- Heavy use of table-driven / parameterized tests for transitions.
- Translation layer (especially prompt generation) is unit tested in isolation.
- Integration tests for the full pipeline use mocked or recorded snapshot data.
- Real end-to-end tests (with actual GitHub) are minimized and clearly separated.

The goal is that the core logic tests can (and should) be run on every change to the AFK skill.

## Key Shifts from Previous Design

| Area                        | Before (Old Orchestrator)          | After (New Engine)                          |
|----------------------------|------------------------------------|---------------------------------------------|
| Judgment                     | Spread across main agent prompt    | Centralized in explicit state machine       |
| Prompt generation            | Mostly in agent prompts            | Owned by the engine (in translation layer)  |
| Worktree decisions           | Orchestrator judgment              | Engine policy                               |
| Checklist enforcement        | Relied on subagent discipline      | Engine injects checklists into prompts      |
| Observability                | Limited                            | Rich `AFKCycleResult` + plan + notes        |
| Testability of rules         | Difficult                          | Excellent (pure functions + crafted data)   |
| Orchestrator complexity      | High                               | Extremely thin (call engine + spawn)        |

## Current Status (as of late May 2026)

- Architecture and data model largely finalized via extended grill-me design session.
- Core module structure agreed.
- All core modules implemented:
  - `data_models.py`, `state_machine.py`, `engine.py` (skeleton + policy)
  - Snapshot builder (hardened in #25)
  - Translator (rich prompts + checklist injection in #23)
  - **Apply layer (safe mutations) completed in #24** — label changes via gh, session file updates (safe merge/atomic), worktree create/cleanup, detailed best-effort reporting, full dry-run + error resilience.
- Comprehensive tests (state machine, translator, engine flow + apply) + Docker-first runner.
- SKILL.md reflects the engine model; design doc updated.

## Open Implementation Areas (not fundamental design questions)

- Polish of the CLI (minor).
- Further hardening / live session snapshot population (history fields).
- Optional future enhancements (e.g. deeper GitHub dependency graph integration).

These are treated as normal engineering work rather than open design debates.

## Next Steps

1. (Completed) Full engine modules including apply layer (#24).
2. Ongoing: exercise via real /afk runs, collect operational feedback.
3. Future polish items listed above.
4. Keep SKILL.md and this design doc in sync with any minor evolutions.

## Implementation Note: Rich Prompt Generation (#23)

The "Detailed prompt generation strategy inside the translator" (open item) was completed in issue #23 via TDD.

**Changes**:
- Extended `SpawnImplementor`/`SpawnReviewer` (data_models) with optional `snapshot: IssueSnapshot | None`.
- State machine now threads the full `IssueSnapshot` when emitting spawn actions.
- `translator.py` `_build_*_prompt` completely overhauled:
  - Dynamic "Rich Issue Snapshot" section (phase, labels, retry_count, open_blockers, last_subagent_*, worktree).
  - Conditional high-leverage guidance (RETRY ATTEMPT #N with "do not repeat mistakes"; OPEN BLOCKERS handling; REVIEW FOCUS for implementor->reviewer handoff).
  - Clean checklist embedding with `=== XXX CHECKLIST (MANDATORY) ===` / `END` delimiters + exact file content.
  - Enhanced headers/footers reinforcing checklist rules, 20-30min progress comments, todo_write for 3+ steps, Docker-first (AGENTS), source-first research, status labels on exit.
- Tests: `test_translator.py` expanded with rich snapshot-driven cases (backward compat preserved via defaults). All run via Docker.
- Design doc + TDD vertical slices followed; no policy changes, pure enrichment in translation layer.

This delivers the "highest-leverage remaining piece for AFK agent performance" per the issue. Snapshot builder history fields remain partially stubbed for live (hand-crafted in tests; inferable from labels/session in future).

## Implementation Note: Apply Layer (Safe Mutations) (#24)

The apply layer (the final core piece after #22 worktree policy + #23 prompts) was completed via TDD in issue #24.

**Changes in `apply.py`**:
- `apply_safe_plan(plan, context, dry_run=False)` fully implemented (stub replaced).
- Label mutations: `gh issue edit` subprocess (add/remove labels), modeled on the hardened fetcher in `fetch_afk_issues.py`.
- Worktree ops: `WorktreeAction` ("create" via `create_afk_worktree.sh`, "cleanup" via `git worktree remove` + `git branch -D`), using documented sibling path convention.
- Session updates: safe recursive merge + atomic tmp+rename write of `.grok/afk-session.json`.
- Detailed per-item `dict` reports (type, issue, success, dry_run, details, error, command, etc.) for `AFKCycleResult.applied_changes`.
- Best-effort + partial success: every plan item isolated in try/except; continues on individual gh/git/fs failures.
- Full dry_run support (no side effects, descriptive "would" reports).
- Robust repo root detection, error handling, no debug code.
- 10+ new tests added to `test_engine_flow.py` (mocks for subprocess/fs, dry_run, partial success, edge cases). All via Docker.

**Test results (Docker python:3.12-slim)**: Full suite (36 tests) passes cleanly after implementation.

**Documentation**: Updated this design doc + test runner for full coverage. (No top-level ARCHITECTURE.md exists; AFK design doc is the authoritative reference for the engine.)

This completes the "Apply Layer (Safe Mutations)" goal, closing the engine implementation loop.

## Startup Hygiene Step — Stale `status-*` Label Removal (#36)

**Added in #36 (per grill 2026-05-25).** A narrow, one-time hygiene function `remove_stale_status_labels_once(...)` lives in the apply layer (`apply.py`). 

**Trigger & Ownership (thin runner only)**:
- Called **exactly once** at the very start of a `/afk` invocation by the thin runner / entrypoint (example in `cli.py`), **after** loading the session file + discovering live subagents, but **before** the first `run_afk_cycle()`.
- The `engine.py`, `state_machine.py`, `snapshot_builder.py`, `translator.py` etc. are **completely untouched** — this is purely a runner-layer startup step.

**Inputs (explicit, from runner)**:
- The loaded session dict (especially its `"running"` section).
- An explicit `set[int]` of issue numbers that have currently live/active subagents in *this process*.

**Qualification & Behavior**:
- Scans (via best-effort `gh issue list --label agent --state open`) for open `agent`-labeled issues that also carry one or more `status-*` labels.
- An issue is cleaned **only if** it has `agent` + `status-*` **and** is absent from *both* the session running issues **and** the live active set.
- **Sole action**: best-effort removal of the `status-*` labels only (reuses the exact `gh issue edit --remove-label` + `_run_cmd` patterns and error handling from the apply layer; supports `dry_run` fully).
- **Never**: writes to session, posts GH comments, touches non-`status-*` labels, or performs any other mutation.
- Returns a list of rich per-issue result dicts (`type`, `issue`, `success`, `dry_run`, `details`, `error`, `labels_removed`, `command`, `status`, ...). The thin runner is responsible for all observability, session event recording, and optional human-facing comments using these results.

**Design Rationale (from grill)**:
- Keeps the hygiene action minimal, pure, and maximally testable (unit tests with hand-crafted sessions + mocked gh; one integration smoke exercising "startup hygiene then cycle").
- Preserves the "very thin runner + pure deterministic engine" architecture.
- Complements existing reviewer label-hygiene (#35) and makes the system robust to interrupted sessions/crashes without manual intervention.

**Testing**: Added to `test_engine_flow.py` (TDD: tests first → GREEN; 45 tests total pass via `run-afk-tests.sh` Docker harness). Covers stale clean, dual-detection skips, non-qualifying issues, dry-run, partial failures, best-effort, and integration with `run_afk_cycle`.

**CLI / Runner Integration**: `cli.py` (and real orchestrator code) now calls it at the documented point and prints summary results. Real runners supply the live `active_subagent_issues` set from their `spawn_subagent` / background task tracking.

**Docs**: This section + updates to `SKILL.md`.

## Token Usage + Cost Reporting on Subagent Completion (#31)

**Delivered in #31.** A new small module `token_reporter.py` (plus exports in `__init__.py`) provides:

- `post_subagent_token_usage(...)`: Formats and posts (via gh CLI) a human-readable + machine-readable (`afk_subagent_usage` JSON) comment to the tracked GitHub issue. Includes input/output/total tokens, optional est. USD cost (via internal best-effort pricing table for known models), duration, tool calls, role, subagent ID, final status (success/failure paths).
- `record_subagent_completion_in_session(...)`: Best-effort atomic merge of usage entry into `.grok/afk-session.json` (under `usage_log` + per-issue last record) for history/aggregates/diagnostics.
- `estimate_cost_usd(model, in, out)`: Standalone estimator (None for unknown models).

**Ownership & Trigger (thin runner only, post-finish)**:
- Called by the orchestrator immediately after `get_command_or_subagent_output` (or equivalent) returns for any worker (implementor or reviewer).
- Inputs: extracted fields from the harness completion metadata (tokens, model, etc.) + issue/role/status.
- **Never** called from inside the engine, state machine, or snapshot builder — keeps the "very thin runner" contract and pure decision logic.
- Full dry-run support; rich per-call result dicts (type, issue, success, est_cost_usd, details, ...).
- Resilient: gh failures or bad data never abort the AFK loop.

**Design alignment**:
- Mirrors the #36 hygiene pattern exactly (runner-owned, best-effort, observable results, no engine changes).
- Fulfills the issue requirements: visible in GH issue (single source of truth), machine + human readable, integrates with existing session/monitoring, non-breaking.
- Cost is explicitly optional ("if pricing known").

**Testing**: New dedicated `tests/test_token_reporter.py` (TDD: RED first via import failure → GREEN with 6+ focused tests for estimator, dry-run, real gh path (mocked), failure resilience, session recording, contract). Full suite (now 65 tests) passes via `run-afk-tests.sh` (Docker python:3.12-slim).

**Runner integration examples**: See updated `cli.py`, `afk-cycle-runner.py`, `afk-run-cycle.py`, and the new dedicated section in `SKILL.md`.

**Docs**: This section + comprehensive updates to `SKILL.md` (new "Token Usage Reporting (#31)" + loop example + future list + migration notes) + `token_reporter.py` docstring.

No changes to engine.py / state_machine / translator / snapshot_builder / data_models (intentional; keeps architecture clean).

---

## Integration & End-to-End Test Suite (#28)

**Delivered in #28 (TDD, Docker-first):** Solid integration and end-to-end coverage for the full engine as the "critical for confidence in the new architecture" follow-up after core modules (#22-27, #36).

### What Was Added
- 7 new focused tests in `tests/test_engine_flow.py` (now part of the 56 total passing in the suite):
  - Single full `run_afk_cycle` pipeline exercised with mocked `IssueSnapshot` data injected at the clean `build_snapshots_and_context` boundary (SM + translator + plan/spawn generation; rich prompts verified).
  - Multi-cycle simulations with progressive snapshots: implementor → reviewer handoff, approval (cleanup + grok paths), reject/retry/escalate sequences.
  - Thin runner + engine interaction: `cli.py` main (hygiene-once + cycle), and a simulated orchestrator loop that repeatedly invokes the engine until `no_more_work`.
  - Load/perf sanity: 50-issue cycle completes in <<1s (pure deterministic logic).
- All use `unittest.mock.patch` on the snapshot builder (recorded/mocked data pattern explicitly called for in the design philosophy and issue #28). No live GitHub calls; fully deterministic and fast in the Docker test env.
- Existing 49 tests (state machine units, translator rich cases, apply #24, error #26, hygiene #36) remain untouched and passing.
- TDD followed: new tests added first (RED verified via `run-afk-tests.sh`), minimal test fixes for environment/attr details to GREEN, refactor for clarity. 2 full Docker runs post-changes confirmed 56/56 clean.

### How to Run
Always via the project's Docker-first harness (zero host installs, per AGENTS.md + checklist):
```bash
.grok/skills/afk/run-afk-tests.sh
```
(Or `HEADED=...` not applicable here.) Inside container: `PYTHONPATH=.grok/skills python -m pytest .grok/skills/afk/tests/ -q --tb=short`.

Covers the exact tasks from #28:
- Full `run_afk_cycle` with mocked/recorded data
- Multiple cycles + state transitions
- Thin runner + engine interaction
- Perf/load considerations (sanity level)

### Rationale & Future
- Respects "Integration tests for the full pipeline use mocked or recorded snapshot data" (design) and "Real end-to-end tests (with actual GitHub) are minimized".
- The builder patch boundary keeps tests fast/pure while exercising the real coordinator + decision + translation logic.
- If richer recorded data (JSON fixtures from real fetches) is desired later, the injection pattern already supports `raw_state` (passed through builder) or snapshot lists.
- No changes to production engine/apply/state_machine/etc. (pure test + doc addition). README impact: none (internal AFK engine detail; root README focuses on fsd-europe-tracker consumer project).

**Test count after #28**: 56 (all via `run-afk-tests.sh` in python:3.12-slim).

---

## Migration Path, Coexistence Strategy, and Deprecation Plan (#29)

This section complements the comprehensive user-facing guidance added to `SKILL.md` in issue #29. The design intentionally preserves the legacy `fetch_afk_issues.py` + `find_ready_afk_issues.py` as a stable data layer rather than replacing or removing them.

### Role of the Legacy Scripts in the Engine Architecture
- They power `snapshot_builder._fetch_live_agent_issues()` (subprocess call to the fetcher for live `agent` issues + blocker resolution) and supply the pure classification used to produce `IssueSnapshot`s.
- This keeps the snapshot builder simple, leverages the already-hardened (#25) fetcher/parser (caching, #34 resilience, error handling), and allows independent evolution of data gathering vs. decision logic.
- Direct CLI / import use of the scripts remains valuable for ad-hoc queries, debugging, custom snapshot providers, and the test suite — no design pressure to internalize them further.

### Thin Runner Migration (Design Implications)
The thin runner contract is deliberately minimal and stable:
- One-time call to `remove_stale_status_labels_once` (apply layer, runner-owned, pre-first-cycle).
- Repeated calls to `run_afk_cycle(...)` → consume `SpawnRequest`s and `AFKCycleResult` (including `.errors` for resilience per #26).
- All policy (including worktree lifecycle per #22, label hygiene support, checklist injection via translator) lives in the engine/state machine.

Custom thin runners (or orchestrator prompts that previously contained discovery loops) migrate by adopting the pattern shown in `cli.py` and the SKILL.md "Default Behavior" example. The engine's rich `SpawnRequest` (with pre-built prompt containing the exact mandatory checklists) removes the need for runners to duplicate prompt construction.

### Coexistence During Transition
- Safe by design: legacy scripts are read-only data tools. Engine cycles and direct `fetch_afk_issues.py` invocations can run concurrently with no coordination required.
- Recommended for confidence: run ad-hoc fetcher queries or dry-run engine cycles while the primary path is the full engine loop. The test suite (`tests/test_engine_flow.py`) already demonstrates side-by-side usage via mocks and the real data layer.
- Docker-first verification (`run-afk-tests.sh`) exercises the integrated system.

### Deprecation Plan (Summary — Full Details in SKILL.md)
- Phase 0 (current): Legacy scripts documented as the intentional data layer; migration guide + coexistence examples + this plan added to SKILL.md and this design doc. No code removal.
- Phase 1 (near-term): De-emphasize direct orchestration examples in high-level docs once engine adoption is proven in practice.
- Phase 2 (future): Optional light deprecation notices in script docstrings if direct use for orchestration falls to zero. The components and their tests remain permanently supported as part of the snapshot pipeline.
- Advancement of phases will be tracked via new AFK issues and will update both this document and SKILL.md.

No changes were made to the core engine modules, data models, or tests for #29 (pure documentation delivery). The architecture (engine as brain, runner as thin executor, legacy as stable data provider) is stable and was validated through #28 integration coverage.

---

**This design shifts AFK from "smart orchestrator with a lot of implicit judgment" to "explicit, testable engine + dumb runner".**

---

## Epic Lifecycle Rule (#30)

**Implemented (TDD, Docker-first) per the authoritative grilled spec captured in the issue body.**

### Rule
- Agent-labeled Epics (those with `agent` + epic heuristic: "epic" label or title.startswith("epic")) are included in AFK snapshots (previously completely filtered).
- While they have any open *direct* GitHub sub-issue children, they are treated as having open blockers (`has_open_blockers=True`, `open_blockers` populated from sub-issue numbers; union with body "Blocked by" if any). This is done in `snapshot_builder._convert_to_snapshots` via new best-effort `_get_open_direct_sub_issue_numbers` (uses `gh api repos/czaby/grok/issues/N/sub_issues` + state filter; resilient except -> []).
- `IssueSnapshot` gained `is_epic: bool` (set by builder for qualifying agent epics).
- State machine `_decide_initial_action` guards agent epics: returns `NoOp` (never `SpawnImplementor`). Combined with early blocker gate, Epics are never picked for direct AFK work while children open (and even after, to avoid meta issues receiving work).
- **Auto-close**: Inside `apply.py` (the "Apply layer"), a post-processing hook `_check_and_auto_close_parent_epics_for_grok_completions` runs after every plan. It inspects `LabelChange`s that add "grok" (AFK-driven child completion/approval). For each:
  - Resolves child's parent via `gh api /issues/<child>` (uses `parent_issue_url`).
  - If parent has `agent`: queries its direct subs.
  - If zero open remain (was last child): `gh issue edit <parent> --state closed --add-label grok` (agent untouched).
  - Records rich `{"type": "epic_auto_close", "issue": parent, "child": child, "success":, "dry_run":, "details":, "command":, ...}` in `applied_changes`.
- Only AFK child completions (via plan/apply in a `run_afk_cycle`) trigger auto-close. No periodic scan. Direct children only. Best-effort + full dry-run.
- If last child closed outside AFK, Epic may remain open (per spec) until observed (then NoOp guard applies; no spawn).
- `AFKCycleResult` surfaces the events via `applied_changes` for observability.

### Files Changed (core)
- `data_models.py` (is_epic field)
- `find_ready_afk_issues.py` + `fetch_afk_issues.py` (agent epics now flow)
- `snapshot_builder.py` (enrichment + helper + import)
- `state_machine.py` (guard)
- `apply.py` (hook + call from `apply_safe_plan`)
- `tests/test_find_ready_afk_issues.py`, `tests/test_engine_flow.py`, `test_state_machine.py` (new/updated coverage; mocks for gh/subprocess)
- `AFK_ENGINE_DESIGN.md`, `SKILL.md` (this section + updates)

### Testing & Verification
- Vertical TDD slices (tests first per tdd/SKILL.md).
- 8+ full runs of `.grok/skills/afk/run-afk-tests.sh` (Docker python:3.12-slim, ro mount, zero host install): 58 tests pass cleanly (up from 56).
- New tests cover: agent epic pass-through, SM NoOp guard (is_epic=True snapshots), apply hook (dry_run last-child triggers close result; non-last/non-agent do not; mocks on `_run_cmd`).
- All via the project's strict Docker harness (AGENTS.md + checklist).

### Documentation Impact
- Updated this design doc and `SKILL.md` (see below).
- No root `ARCHITECTURE.md` or `README.md` changes needed (per prior notes in this doc: "No top-level ARCHITECTURE.md exists; AFK design doc is the authoritative reference"; root README focuses on fsd-europe-tracker consumer). Justification per checklist item 5: AFK engine changes are fully documented in the skill's DESIGN + SKILL (the canonical locations); links remain valid; no consumer-visible surface changed.

This completes the Epic lifecycle rule exactly as specified, with rich diagnostics, testability, and zero scope creep.