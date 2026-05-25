---
name: afk
description: Autonomous parallel execution of ready agent-labeled GitHub issues using a deterministic engine + very thin runner model.
---

> **2026+ Architecture**: The AFK system has been redesigned around an explicit, testable **AFK Engine**. The main orchestrator is now a Very Thin Runner (implemented in `orchestrator.py`) that mostly just calls `run_afk_cycle()` and executes the `SpawnRequest`s it returns. Most judgment, prompt generation, worktree decisions, and state machine logic now live inside the deterministic engine (see `AFK_ENGINE_DESIGN.md` and the modules in this directory). The runner additionally performs a single one-time startup hygiene step (issue #36) using `remove_stale_status_labels_once` from the apply layer before the first cycle.
>
> The older "smart orchestrator" model described in parts of this document is being phased out in favor of the new engine. New development should target the engine in `engine.py`, `state_machine.py`, `translator.py`, etc.
>
> **Migration & coexistence (see #29)**: Full guidance on how the legacy `fetch_afk_issues.py` / `find_ready_afk_issues.py` now fit as the data layer, step-by-step thin runner migration, parallel operation during transition, and the deprecation plan for old orchestration patterns is in the "Legacy Data Helpers, Coexistence Strategy..." section below (and the matching section in `AFK_ENGINE_DESIGN.md`). Direct use of the legacy scripts for ad-hoc, debug, and test purposes remains supported.

# AFK — Autonomous Parallel Issue Execution

**Goal**: Let Grok (as orchestrator) continuously discover, assign, and complete all currently unblocked **AFK** work on the project without the user having to manually pick and launch agents.

This skill turns the issue tracker into the single source of truth for what can be done autonomously.

## Core Philosophy

- The **issue tracker** (GitHub Issues) + labels + "Blocked by" text = the plan.
- One **orchestrator** (you, the main agent) decides *what* can be worked on right now.
- Multiple **worker subagents** do the actual implementation in parallel.
- When a worker finishes, the orchestrator immediately looks for the *next* ready piece of work.
- The user only intervenes for true HITL items or when they want to steer.

## Prerequisites (in this repo)

The project already uses good conventions that this skill relies on:

- Issues that are safe for autonomous work carry the **`agent`** label.
- Issues that are currently being worked on by an agent carry the **`in-progress`** label (or are assigned).
- Dependencies are expressed in the issue body using text like:
  - `Blocked by: #123, #456`
  - `Blocked by (completed work): Slice 2`
- Major epics use GitHub sub-issues (children of an Epic issue).
- Completion of an AFK slice is marked by adding the **`grok`** label (the "completion signature") + closing (or marking ready for review). The presence of `grok` on an *open* `agent`-labeled issue does **not** block future AFK work (e.g. follow-up documentation, architecture, or fixes); readiness is determined solely by the rules below (`agent` + no `status-*` + no unresolved blockers). See the fix for #33.

## How to Invoke

```bash
/afk
```

By default, `/afk` runs the full autonomous loop: it repeatedly calls the engine, spawns workers for ready issues, monitors them through the implementor → reviewer cycle, performs merges on approval, cleans up, and continues until there are zero ready issues **and** zero running subagents. When that happens it exits with a clear summary.

Optional parameters (future / CLI):

- `--max-concurrent 2`
- `--epic 3` (only consider sub-issues of a specific epic)
- `--dry-run`
- `--once` (run a single engine cycle and stop — useful for debugging or one-shot inspection)

## The Main Loop (Orchestrator Behavior)

**Default behavior**: The orchestrator runs the following loop continuously until there is nothing left to do (no ready issues and no running subagents). This is the normal, expected behavior when you simply type `/afk`.

The loop:

1. **Discover ready work**
   - Query all open issues that have the `agent` label.
   - Filter out any that already have `in-progress` (or are assigned to a person).
   - For each candidate, evaluate whether it has any **unresolved blockers** (see "Dependency Detection" below).
   - Only issues that are completely unblocked are considered "ready".

2. **Assign & spawn**
   - For each ready issue (up to `max_concurrent`, default 2):
     - Add the `in-progress` label.
     - Post a comment:  
       `🚀 Assigned to autonomous AFK worker. Starting now.`
     - Spawn a dedicated subagent with a strong, focused prompt (see below).
     - Record the mapping: `subagent_id → issue_number`.

3. **Monitor**
   - Wait for any running subagent to report completion (or poll periodically).
   - When a subagent signals that its issue is done:
     - The worker should have already added the `grok` label and closed (or updated) the issue.
     - Reap the subagent.

4. **Repeat**
   - Go back to step 1.
   - The loop continues automatically. Only when there are **zero ready issues** **and** zero running subagents does the orchestrator exit with a clear summary:
     > "All currently unblocked AFK work has been completed.  
     > Remaining open AFK issues are blocked by other open work."

## Dependency Detection (Critical)

**The single source of truth for dependencies is text in the issue *body*.**

An issue is considered **ready** for autonomous AFK work only if **all** of the following are true:

- Has the `agent` label
- Does **not** have the `in-progress` (or any `status-*`) label
- Is open (not closed)
- Every issue number referenced via a supported "blocker" phrase in the body is **closed**
- (Recommended) It is either a direct sub-issue of the main Epic or the Epic itself has no blocking work

**Note on the `grok` label (per #33)**: `grok` is only a historical completion marker added on approval. It is **not** a blocker. An open issue carrying both `agent` and `grok` (but no `status-*` labels and no unresolved body blockers) **is** eligible for further AFK work. The fetcher + `find_ready_afk_issues` + engine will correctly surface and act on it.

### Dependency Syntax (Authoritative Specification)

To declare that one AFK issue depends on the completion of another, add **one of the following phrases** in the **body** of the issue (not just the title or comments).

#### Supported Patterns

The parser (`parse_blockers` in `find_ready_afk_issues.py`) recognizes these forms (case-insensitive, markdown-tolerant):

| Pattern | Example | Notes |
|---------|---------|-------|
| `**Blocked by**: #NNN` | `**Blocked by**: #16` | Preferred for checklist-test chains |
| `Blocked by: #NNN, #MMM` | `Blocked by: #4, #5 and #12` | Multiple blockers on one line |
| `Blocked by: #NNN (reason)` | `Blocked by: #15 (human gate)` | Parenthetical notes are ignored |
| `Depends on: #NNN` | `Depends on: #3` | Equivalent to Blocked by |
| `Blocked by (completed work): ... (issue #NNN)` | `Blocked by (completed work): Slice 2 (issue #45)` | Common historical style |
| `Blocked by: (none)` | `Blocked by: (none – baseline)` | Explicitly declares no blockers |

**Markdown is fully supported**: `**Blocked by**`, `__Blocked by__`, `*Blocked by*`, `_Blocked by_` etc. will all be parsed correctly.

#### Rules & Recommendations

- Put the dependency declaration near the top of the issue body for visibility (right after the title and type is ideal).
- Use `**Blocked by**: #NNN` as the default style for new issues.
- You may list multiple blockers: `Blocked by: #16, #17`.
- "Related to", "See also", or "Parent Epic" do **not** create blockers — only the phrases above do.
- If an issue has **no** `Blocked by` / `Depends on` phrase at all, it is treated as having no blockers.
- Explicitly writing `Blocked by: (none)` or `Blocked by: none` makes the intent unmistakable (useful for baseline / first-in-chain issues).
- The parser only looks at the **body** text.
- **#30 update (Epic lifecycle)**: GitHub *sub-issue relationships* (direct children) are now used authoritatively for one specific case: determining whether an *agent-labeled Epic* has open children (treated as `has_open_blockers` in snapshots, preventing spawn on the Epic). Body "Blocked by" continues for all other dependency declarations. The sub-issue graph powers the automatic Epic closure hook (see Apply layer / engine). This is narrow, deliberate, and fully documented in `AFK_ENGINE_DESIGN.md`.

#### Anti-Patterns (Will Not Be Detected)

- Putting the dependency only in a comment
- Using only GitHub's project board or "linked issues" UI without body text
- `Blocked by #16` without the colon or "by" keyword in a supported phrase
- References hidden inside code blocks or tables

### How the Parser Works (for Orchestrators & Tool Authors)

See the implementation and tests in:
- `.grok/skills/afk/find_ready_afk_issues.py` → `parse_blockers()`
- `.grok/skills/afk/test_find_ready_afk_issues.py` (the unit tests)

The function returns a deduplicated list of issue numbers. The `find_ready_afk_issues()` function then compares those numbers against the set of actually closed issues.

Simple body parsing is the current mechanism. Future versions may additionally consult GitHub's dependency graph / sub-issues API.

## Git Worktree Isolation for AFK Workers (Current Practice)

**Goal**: Workers never touch the main checkout. All changes happen in an isolated git worktree on a private branch. Only the orchestrator ever touches `main`.

### Recommended Convention

- **Worktree base directory** (sibling to the repo): `../grok-afk-worktrees/`
  - Example on this machine: `/home/czaby/w/grok-afk-worktrees/`
- **Branch name**: `afk/<issue-number>` (e.g. `afk/42`)
- **Worktree path**: `/home/czaby/w/grok-afk-worktrees/issue-<number>`

### What the Orchestrator Must Do Before Spawning a Worker

You can use the convenience helper:

```bash
.grok/skills/afk/create_afk_worktree.sh 42
```

It will output lines the orchestrator can parse:

```
WORKTREE=/home/czaby/w/grok-afk-worktrees/issue-42
BRANCH=afk/42
ISSUE=42
```

(Or run the manual commands if you prefer:)

```bash
# Create the worktree + branch for issue 42 (run from the main grok checkout)
mkdir -p /home/czaby/w/grok-afk-worktrees
git worktree add -b afk/42 /home/czaby/w/grok-afk-worktrees/issue-42
```

Record the path and branch in your session state (`.grok/afk-session.json`).

Then pass the following block (customized) at the very top of the worker's prompt:

```markdown
## CRITICAL — ISOLATED GIT WORKTREE (MANDATORY)

You **must not** modify the original repository checkout at all.

- Worktree root (absolute path — use this for **every** tool call):
  `/home/czaby/w/grok-afk-worktrees/issue-42`

- Your private branch: `afk/42`

**Rules for tool usage (non-negotiable):**

1. **run_terminal_command**:
   - **Every** command must start with:
     `cd /home/czaby/w/grok-afk-worktrees/issue-42 && `
   - Good example:
     `cd /home/czaby/w/grok-afk-worktrees/issue-42 && git status`
     `cd /home/czaby/w/grok-afk-worktrees/issue-42 && python -m pytest -x`

2. **File system tools** (`read_file`, `write`, `search_replace`, `list_dir`, `grep`, etc.):
   - Always use the **full absolute path** under the worktree root.
   - Correct: `read_file` with target_file = `/home/czaby/w/grok-afk-worktrees/issue-42/README.md`
   - Correct: `list_dir` with target_directory = `/home/czaby/w/grok-afk-worktrees/issue-42/src`
   - Never use relative paths or paths under the original `grok/` directory.

3. **Committing & branching rules**:
   - You may create local commits on `afk/42` during development.
   - **You are forbidden from touching `main`, `origin/main`, or performing any merge/push to the primary branch.**
   - Only after the issue is **completely finished**, all tests pass, and you have written a final summary comment:
     - Produce one clean final commit (or amend the last one) with a message referencing the GitHub issue.
     - Tell the orchestrator you are done.
   - The orchestrator (not you) will merge `afk/42` into `main` from the primary checkout and clean up the worktree.

4. **Error / stuck / need human help**:
   - **Stop working immediately.**
   - Post a detailed comment on the GitHub issue explaining the problem.
   - **Leave the entire worktree exactly as it is** (do not `git reset`, `git clean`, or delete anything).
   - Exit cleanly.

The orchestrator will give the human the exact commands to inspect, continue, or discard your worktree.
```

### What the Orchestrator Must Do on Worker Completion or Failure

**On success** (after the worker reports done):
- From the **main** checkout, merge the worker's branch:
  ```bash
  git fetch origin afk/42 || true
  git merge --no-ff afk/42 -m "Merge afk/42: complete issue #42"
  git push origin main
  git branch -d afk/42
  git worktree remove /home/czaby/w/grok-afk-worktrees/issue-42
  ```

**On failure / stuck / human intervention requested**:
- Post the following (or similar) in the chat **and** on the GitHub issue:

  ```
  Worker for #42 encountered an error and exited.

  To inspect or continue the work yourself:

  cd /home/czaby/w/grok-afk-worktrees/issue-42
  git status
  git log --oneline -20 --graph
  git diff main..HEAD

  You can edit files directly in that directory using absolute paths.
  All the changes the agent made are preserved there.

  When you are ready to bring the work back (or discard it), tell me and I will run the cleanup commands.
  ```

- Also print the cleanup commands the human can run later if desired:
  ```bash
  git worktree remove /home/czaby/w/grok-afk-worktrees/issue-42 --force
  git branch -D afk/42
  ```

This pattern guarantees the main branch stays pristine and gives you (the human) a perfect, ready-to-use recovery environment for any autonomous worker.

## Reviewer Process & State Machine (Current Practice)

The AFK workflow is no longer a simple "spawn one worker and wait". Every issue now goes through a structured **Implement → Review** cycle with a hard limit on retries.

### Core Flow

1. Orchestrator spawns an **implementor** subagent in a dedicated worktree.
2. When the implementor finishes, it sets the appropriate labels and exits.
3. Orchestrator then spawns a **reviewer** subagent (fresh context) for the same issue.
4. The reviewer evaluates:
   - Code correctness and tests
   - Documentation quality (README + Architecture document must be correct, understandable, and complete)
   - Attempts to merge the branch into `main`
5. On approval:
   - Reviewer removes **all** `status-*` labels (and any prior ones) and adds the `grok` label (historical completion signature only; does **not** prevent future AFK on the issue if later reopened or for follow-ups — see #33 and readiness rules above). This must leave *exactly one* `status-*` (none in this case).
   - Keeps any `retry-*` labels + `agent`/`human`
   - Closes the issue
6. On rejection:
   - Reviewer sets `status-rejected-review` + the next `retry-N` label **while explicitly removing any previous `status-*` labels** (e.g. `status-in-review` or `status-in-progress`) in the same label edit. Must leave *exactly one* `status-*` label.
   - Orchestrator spawns a new implementor
7. After the second rejection (`retry-2` + another rejection), or on any inconsistent state (including >1 `status-*` labels left by reviewer), the orchestrator escalates the issue to human (`human` label).

### Label State Machine (Authoritative)

The orchestrator and agents must treat the following labels as the **single source of truth** for the issue state. Only one `status-*` label may be present at any time.

**Reviewer responsibility (per #35)**: Reviewers are the primary enforcers of this invariant when they transition an issue out of `in_review`. Their label edits (on approve or reject) must always result in a valid single-status state. The engine will still escalate on violation as a backstop, but the expectation is zero violations from reviewer actions.

**Valid combinations** (exactly one of these + exactly one of `agent` or `human`):

- `status-in-progress`
- `status-in-review`
- `status-rejected-review`
- `status-in-progress` + `retry-1`
- `status-in-review` + `retry-1`
- `status-rejected-review` + `retry-1`
- `status-in-progress` + `retry-2`
- `status-in-review` + `retry-2`
- `status-rejected-review` + `retry-2`

**Any other combination** of these labels is considered inconsistent and must trigger immediate escalation to `human`.

**Escalation rule**:
- When the orchestrator sees `status-rejected-review` + `retry-2` + `agent` on an open issue, it must replace `agent` with `human` (leaving all other labels unchanged) and stop autonomous work on that issue.

### Responsibilities

**Implementor**:
- Works exclusively in its assigned worktree.
- May merge latest `main` into its branch (especially after a merge-conflict rejection).
- Must read and follow the full AFK Implementor Checklist in `.grok/skills/afk/implementor-checklist.md` at the start of the task.
- Must ensure tests pass before requesting review.
- Must update documentation (README + Architecture document) so that the issue's functionality is properly described.
- Must not touch `main`.

**Reviewer** (separate subagent with fresh context):
- Follows the full AFK Reviewer Checklist in `.grok/skills/afk/reviewer-checklist.md` (including running the tests themselves).
- Reviews code, tests, and documentation.
- Attempts to merge the implementor's branch into `main`.
- On clean merge + acceptable quality: approves (removes *all prior* `status-*` labels, adds `grok`, closes). Must ensure exactly one `status-*` (or zero) remains.
- On any problem (including merge conflict): rejects with `status-rejected-review` + next retry label **while removing any prior `status-*` labels** (label hygiene per #35 to avoid engine escalation).
- Must post a clear comment explaining the verdict and specific issues.
- Never edits code or documentation.

### Documentation Ownership

Every issue is responsible for ensuring the documentation (README and Architecture document) is up-to-date with its functionality. The reviewer evaluates the *result*, not whether the implementor touched the files in that specific issue.

The Architecture document is created early as its own AFK issue and is then maintained by subsequent issues.

### Mandatory Checklists

The AFK skill defines two explicit, mandatory checklists:

- [implementor-checklist.md](implementor-checklist.md)
- [reviewer-checklist.md](reviewer-checklist.md)

These files live in `.grok/skills/afk/`.

**Both checklists are mandatory.** Every implementor and reviewer subagent **must** read the appropriate checklist at the very start of its work and follow it completely. The orchestrator will ensure the checklists are available in the subagent’s context by including their full content or by giving the subagent the exact absolute path and explicit instructions to read them first.

The checklists are the authoritative definition of what “done” and “properly reviewed” mean. They are deliberately kept as separate documents so they can be versioned, reviewed, and improved independently while still being reliably delivered to every subagent.

## Worker Subagent Prompt Template

Every spawned subagent receives a prompt similar to this (customized per issue):

```
You are an autonomous software engineering agent.

Your ONLY mission is to fully complete GitHub issue #{issue_number} in this repository.

Repository context:
- This is a private repo: czaby/grok
- The project is the FSD Europe Tracker (see fsd-europe-tracker/ folder, PRD.md, ISSUES.md)
- Follow all rules in the root grok.md (local file creation, no auto-commits unless asked, etc.)
- Use the /tdd skill when implementation work is required.

Rules you MUST follow:
1. Start by reading the full issue #{issue_number} (body + all comments).
2. Explore the relevant code and tests.
3. Work in small, verifiable steps. Prefer TDD (red → green → refactor) where it makes sense.
4. Every time you make meaningful progress, post a comment on the GitHub issue with:
   - What you just did
   - Current status
   - Any questions or blockers for the human
5. When you believe the issue is truly complete according to its acceptance criteria:
   - Add the `grok` label to the issue (this is your completion signature)
   - Update the issue body or add a final comment summarizing what was delivered
   - Close the issue (or mark it "ready for human review" if you are unsure)
6. Never work on anything outside the scope of this specific issue unless the issue itself says to do so.

You have full access to the file system, GitHub tools, and can run commands (prefer Docker where needed).

**The orchestrator will have prepended the full "CRITICAL — ISOLATED GIT WORKTREE" instructions (with the exact absolute paths for this worker) at the top of your prompt. Follow them strictly.**

Issue URL: https://github.com/czaby/grok/issues/{issue_number}

Begin.
```

## Configuration (for future versions)

The skill should support a small config (e.g. in `.grok/skills/afk/config.yaml` or as command arguments):

- `agent_label`: agent
- `in_progress_label`: in-progress
- `completion_signature_label`: grok
- `max_concurrent`: 2
- `epic_number`: 3 (optional filter)
- `dependency_parsing`: "body-text" | "github-dependencies"

## Safety & Human Oversight

- The orchestrator **never** works on issues without the `agent` label.
- Every worker is forced to post progress comments on the actual GitHub issue (transparency).
- The user can always intervene by removing the `in-progress` label or commenting "stop".
- Subagents run with the same safety rules as the main agent (Docker-first, etc.).

## Implementation Notes for the Orchestrator

When running this skill you (the main agent) should:

- **Data layer + ad-hoc queries (gh CLI fetcher)**: Run `python .grok/skills/afk/fetch_afk_issues.py --json` (or without --json for human output) when you need raw ready/blocked classification, live snapshots for debugging, custom tools, or direct inspection. It remains the hardened, production-ready implementation of discovery + `parse_blockers` + blocker resolution (with caching, #34 resilience, etc.). For label/comment mutations use direct `gh` commands. The **primary path for full autonomous loops** is the engine (see "How to Run the Full Skill" below and the migration section). The fetcher is invoked internally by `snapshot_builder.py` when `run_afk_cycle()` gathers live state. MCP tools are the fallback when richer GitHub APIs are required.

**Hardened Snapshot Builder (production, issue #25)**: The core AFK state snapshot (ready/blocked classification) is now production-hardened in the fetcher + pure logic:
- Robust parser (`parse_blockers` + follow-on capture) for real GitHub data including "Blocked by (completed work)", lists with "and"/commas, parentheticals, and varied phrasing.
- Per-run caching of blocker state lookups in the fetcher for performance on frequent orchestrator cycles.
- Improved error handling, timeouts, and structured logging (stderr) across fetch/resolve.
- Reliable worktree discovery/creation in `create_afk_worktree.sh` (numeric validation, git repo checks, `git worktree list` pre-discovery, better errors per the documented convention).
Full TDD coverage with Docker-first tests (`run-afk-tests.sh`). The builder remains simple/pure for reuse while being reliable for real repositories. See `.grok/skills/afk/test_find_ready_afk_issues.py` and the afk py files for details.
- **Fallback (MCP)**: Use the GitHub MCP tools via `search_tool`/`use_tool` (`list_issues`, `issue_read`, `issue_write`, `add_issue_comment`, `sub_issue_write`, ...) when richer sub-issue or project APIs are needed.

### Worktree + Reviewer lifecycle (mandatory for every worker)
- Before calling `spawn_subagent` for an issue:
  1. Create the worktree + private branch using the convention in the "Git Worktree Isolation for AFK Workers" section above.
  2. Record the exact worktree path and branch in your `.grok/afk-session.json` (under the running worker entry).
  3. Prepend the full "CRITICAL — ISOLATED GIT WORKTREE" block (with the concrete absolute paths) to the worker prompt.

- After an implementor reports done:
  - Do **not** merge yourself.
  - Spawn a reviewer subagent (fresh context) for the same issue.
  - The reviewer will attempt the merge into `main` and decide on approval or rejection via labels.

- After a reviewer reports done (via labels):
  - Read the current state machine labels.
  - If approved (`grok` label present + issue closed): clean up the worktree.
  - If rejected (`status-rejected-review` + `retry-N`): spawn a new implementor (new worktree) unless `retry-2` + another rejection has occurred.
  - If the state is inconsistent or `status-rejected-review` + `retry-2` + `agent` is seen on an open issue: escalate by swapping `agent` → `human` and stop autonomous work on that issue.

- After a worker fails or asks for help: leave the worktree in place and give the human the exact `cd` + inspection commands (see Error Handling below).

- Use `spawn_subagent` (with `background: true` when appropriate) to launch both implementors and reviewers.
- Use the subagent management tools (`wait_commands_or_subagents`, `get_command_or_subagent_output`, etc.) to monitor them.
- Maintain an internal todo list (using `todo_write`) for the overall AFK session if it becomes long.
- Keep the user informed at major milestones ("Started implementor for #42", "Reviewer rejected #42 (retry-1)", "Worker on #4 finished successfully", "No more ready work — exiting").
- **Default behavior**: Keep looping (call engine → spawn → monitor → repeat) until the engine reports `no_more_work` **and** there are no active subagents. Do not stop after one cycle unless `--once` (or equivalent) is explicitly requested.

## Future Enhancements

- Automatic creation of a "AFK Session" GitHub Discussion or comment thread for high-level logging.
- Support for Linear instead of / in addition to GitHub Issues.
- Better dependency graph using GitHub's native "linked issues" / "blocked by" relationships (beyond simple body text).
- ~~Cost / token usage reporting per worker~~ — **Delivered in #31**: `token_reporter.py` + `post_subagent_token_usage()` (and session recorder). Called by thin runner after every `get_command_or_subagent_output` (implementor + reviewer, success/failure). Posts human + machine-readable comment (tokens + optional est. USD cost) directly to the tracked GitHub issue. See "Token Usage Reporting (#31)" section below + AFK_ENGINE_DESIGN.md.
- (Narrow delivery in #30): Sub-issue relationships now power the Epic lifecycle rule for *agent-labeled Epics only* (open direct children → blockers in snapshot; auto-close of Epic in apply hook after last AFK child). See AFK_ENGINE_DESIGN.md for exact scope + the sibling hook implementation. General blocker use of the graph remains future.

**Implemented**: Isolated git worktrees per subagent with strict "only merge to main on success" policy + human recovery commands (see "Git Worktree Isolation for AFK Workers" section).

---

**This skill turns "I have a bunch of AFK issues" into "just run `/afk` and come back later when everything that could be done autonomously is done."**

Start simple, make the loop reliable, then add power features.

---

## Dry-Run Example (czaby/grok repo)

Using the data layer (`python .grok/skills/afk/fetch_afk_issues.py --json`, which the engine's snapshot builder also invokes internally) + the pure classification logic in `find_ready_afk_issues.py`:

**Currently ready for AFK (no open blockers):**
- **#4** – Implement core LangGraph agent nodes (search, verify, update JSON)
  - Only references "Blocked by (completed work): Slice 2"
- **#8** – Write documentation files (README.md, CONTRIBUTING.md, docs/SETUP.md)
  - Only "Related to: #9" (#9 is `human`, not blocking)

**Blocked:**
- **#5** – Blocked by #4 (still open)
- **#6** – Blocked by #5 (which is blocked by #4)

**Conclusion for this repo right now:** The orchestrator would mark **#4 and #8** as `in-progress` and spawn two subagents in parallel. When either finishes, it would immediately re-scan and could pick up the next one (e.g. #5 once #4 is done).

This is exactly the desired behavior.

---

## Error / Failure Handling (Subagent Crashes or Gets Stuck)

This is a critical real-world case the user highlighted.

**Policy the orchestrator must follow:**

1. If a subagent exits with an error, times out, or explicitly reports "I am blocked / need human help":
   - Immediately remove the `in-progress` label from the issue (or replace it with `needs-human` / `temporarily-human`).
   - Post a clear comment on the GitHub issue (see example below).
   - **In the same message (or a follow-up in the chat), give the human the exact recovery commands for the worktree** (customized with the real path recorded in your session state):
     ```
     Worker for #42 failed.

     To inspect or continue the changes yourself:

     cd /home/czaby/w/grok-afk-worktrees/issue-42
     git status
     git log --oneline -20 --graph
     git diff main..HEAD

     You can continue working directly in that directory (use absolute paths for all tools).
     All uncommitted and committed changes the agent made are preserved.

     When you are finished, tell me and I will merge the branch or clean up the worktree.
     ```
   - Do **not** keep the `in-progress` label — this prevents the issue from being ignored.
   - Continue processing any other ready AFK issues. Do not stop the whole loop because one worker failed.

2. The worker prompt (below) explicitly instructs subagents:
   - On unrecoverable error, update the GitHub issue with the problem and **exit cleanly** instead of looping forever.
   - Prefer to fail loudly with a good comment rather than silently dying.

3. The orchestrator should have a "stuck worker" detector (e.g., a subagent that has produced no comments on its issue for > 30–60 minutes can be considered suspect).

This way a failing subagent turns its issue into a **temporary HITL** item without poisoning the rest of the AFK pipeline. The user can fix the problem and the issue becomes eligible for AFK again on the next cycle.

---

## Improved Worker Subagent Prompt (Project-Specific)

Use the following as the base prompt when spawning a worker for an `agent`-labeled issue in this repository (customize the issue number and title):

```markdown
You are a focused autonomous software engineering subagent.

Your **only** job is to complete GitHub issue #{issue_number} ("{title}") to the best of your ability.

Repository: czaby/grok (private)
Project: Tesla FSD Europe Approval Tracker (see fsd-europe-tracker/ folder + PRD.md + ISSUES.md)

Hard rules:
- Follow every rule in the root `grok.md` (always create files with tools, no copy-paste, no auto git commit unless the user says so, Docker-first, etc.).
- **You MUST work exclusively inside the isolated git worktree** that the orchestrator created for you (the absolute path + branch name + tool usage rules will be given at the very top of your prompt). Never touch the original checkout.
- **You may only commit to `main` (directly or via merge) on successful, verified completion of the entire issue.** The reviewer (not you) will attempt the merge into `main` after you finish.
- Use the `/tdd` skill for any non-trivial implementation work.
- Post a meaningful progress comment on the actual GitHub issue **at least every 20–30 minutes** of real work (or after every major step).
- Documentation is your responsibility: before requesting review, ensure the README and Architecture document are up-to-date and properly describe the functionality delivered by this issue.
- At the very beginning of your work, you **must** read the full AFK Implementor Checklist from the file `.grok/skills/afk/implementor-checklist.md` (use the absolute path from the main repository if needed). These rules are mandatory.
- When you are confident the acceptance criteria are met:
  1. Set the correct status labels (`status-in-review` or similar) so the orchestrator can spawn the reviewer.
  2. Write a clear "Done" summary comment.
  3. Exit cleanly so the reviewer can take over.

Error handling:
- If you hit an unrecoverable blocker or error, **do not loop forever**.
- Post a detailed comment on the issue explaining the problem.
- Add a temporary label such as `needs-human` or `temporarily-human` if appropriate.
- **Leave the worktree exactly as it is** — do not clean, reset, or delete anything.
- Then exit cleanly so the orchestrator can give the human the exact recovery commands for your worktree.

You have full tool access (file system **inside your assigned worktree only**, GitHub via `gh` CLI or MCP tools, subagent spawning is **not** allowed for workers, terminal via Docker where needed).

Issue: https://github.com/czaby/grok/issues/{issue_number}

Begin work now.
```

---

## Concurrency & Monitoring Helpers

Recommended simple state file (the orchestrator maintains this):

`.grok/afk-session.json`
```json
{
  "session_started": "2026-05-23T22:10:00Z",
  "max_concurrent": 2,
  "running": {
    "subagent-abc123": {
      "issue": 4,
      "branch": "afk/4",
      "worktree": "/home/czaby/w/grok-afk-worktrees/issue-4",
      "started": "..."
    },
    "subagent-def456": {
      "issue": 8,
      "branch": "afk/8",
      "worktree": "/home/czaby/w/grok-afk-worktrees/issue-8",
      "started": "..."
    }
  },
  "completed": [4],
  "failed": []
}
```

The orchestrator should:
- Update this file whenever it spawns or reaps a worker.
- Use `wait_commands_or_subagents` + `get_command_or_subagent_output` to monitor.
- On any worker exit (success or failure), immediately run the "find ready issues" logic again.

This gives the user a single place to see the current AFK session state even if they are not watching the terminal.

## Token Usage Reporting (#31)

**Delivered by this issue.** On every subagent exit (implementor or reviewer, success or failure), the *thin runner/orchestrator* (not the engine) is responsible for capturing final token usage from the subagent result (via `get_command_or_subagent_output` or equivalent) and posting a clear comment to the tracked GitHub issue.

### Why here (runner-owned, like #36 hygiene)
- The engine remains a pure decision maker (spawns only).
- Post-completion side effects (comments, session writes for history) belong in the thin runner layer.
- Matches the existing pattern: hygiene + spawn execution + monitoring + re-cycle all runner duties.

### Usage in the orchestrator (after worker reaping)
```python
# After subagent completes and you have the metadata:
from afk.token_reporter import (
    post_subagent_token_usage,
    record_subagent_completion_in_session,
    estimate_cost_usd,  # if you want to compute separately
)

res = post_subagent_token_usage(
    issue_number=the_issue,
    role="implementor",  # or "reviewer"
    tokens_in=12345,
    tokens_out=6789,
    tokens_total=19134,
    model="grok-4.3",
    duration="6m 30s",
    tool_calls=57,
    subagent_id="019e5d40-...",
    final_status="success",  # or "error", "status-in-review", etc.
    error_info=None,
    dry_run=False,  # or True for testing
)
# res is rich dict: type, issue, success, dry_run, details, est_cost_usd, command, ...

# Recommended: also persist for aggregates / future snapshot history
record_subagent_completion_in_session(
    issue=the_issue, role="implementor",
    usage={"tokens_total": 19134, "est_cost_usd": res.get("est_cost_usd"), "model": "grok-4.3"},
    dry_run=False,
)
```

The posted comment is both human-readable and contains a machine-readable JSON block (`afk_subagent_usage`).

**Cost estimation**: Optional, best-effort via internal table in `token_reporter.py` (update rates as xAI pricing evolves). Unknown models → "N/A (pricing unknown)".

**Non-goals (v1)**: Real-time streaming, per-tool breakdown, budget enforcement.

See `token_reporter.py` (source + docstring), `orchestrator.py` (runner-owned #31 hook + completion handling), `cli.py` (legacy one-cycle reference), and the matching section in `AFK_ENGINE_DESIGN.md`.

---

## Reviewer Subagent Prompt Template (Project-Specific)

Use the following as the base prompt when spawning a **reviewer** for an `agent`-labeled issue (customize the issue number and title):

```markdown
You are a focused autonomous code reviewer with fresh context.

Your job is to review GitHub issue #{issue_number} ("{title}") that was just completed by an implementor.

Repository: czaby/grok (private)
Project: Tesla FSD Europe Approval Tracker

Hard rules:
- You have **not** seen any previous conversation with the implementor. You must form your own independent opinion.
- You must review:
  1. Code correctness and test quality against the acceptance criteria.
  2. Documentation quality (README and Architecture document must be correct, understandable, and complete for the changes in this issue).
- At the very beginning of your work, you **must** read the full AFK Reviewer Checklist from the file `.grok/skills/afk/reviewer-checklist.md` (use the absolute path from the main repository if needed). These rules are mandatory. You are required to run the tests yourself.
- You must attempt to merge the implementor's branch (usually `afk/{issue_number}`) into `main`.
- If the merge has conflicts or the quality is not acceptable, you must reject the issue.
- If everything is acceptable and the merge succeeds cleanly, you must approve.
- **Label hygiene is mandatory** (fixes #35): your approval/rejection label edits must always result in exactly one (or zero for final approve) `status-*` label. Use combined add/remove in one gh/MCP call and document it.

On approval:
- Remove **all** `status-*` labels (ensuring *exactly zero* remain after the edit).
- Add the `grok` label (completion signature / historical marker; explicitly does not block re-eligibility for AFK work on open issues per updated readiness rules and #33 fix).
- Keep any existing `retry-*` labels and the `agent` label.
- Post a clear success comment stating that the review passed and the issue is accepted. **Explicitly note the label hygiene step** (before/after labels + command used).
- Close the issue.

On rejection:
- Set `status-rejected-review` + the next retry label (`retry-1` or `retry-2`) **while removing any pre-existing `status-*` labels in the same operation** (e.g. via `gh issue edit --add-label ... --remove-label status-in-review,status-in-progress`). Must leave *exactly one* `status-*` label. This prevents the #35 escalation bug.
- Post a detailed comment explaining exactly what is wrong (be specific about the decision or area that is unclear or incorrect). **Include the exact label edit command(s) used.**
- If the rejection is due to a merge conflict, explicitly state this.

You may give suggestions, but the implementor is not required to follow them. If you reject, the implementor will have a chance to respond and improve the work.

Issue: https://github.com/czaby/grok/issues/{issue_number}

Begin the review now.
```

---

## How to Run the Full Skill (Current Best Practice — 2026+)

The AFK system has been re-architected around a **deterministic engine + very thin runner** model.

### Default Behavior: Full Autonomous Persistent Loop

**When you type `/afk`, the expected and default behavior is a fully autonomous persistent loop:**

- The orchestrator repeatedly calls the engine, spawns workers (implementor then reviewer), monitors them, performs merges on approval, cleans up, and **immediately** looks for the next ready piece of work.
- It does **not** stop after each cycle to ask for confirmation.
- It only exits when there are **zero ready issues** **and** zero running subagents.
- At that point it prints a clear summary and stops.

This is the normal, hands-off mode. The user should not need to re-invoke `/afk` or give explicit "continue" signals between cycles.

Only use `--once` (or equivalent) when you explicitly want a single snapshot for debugging.

```python
# The thin runner's main job (simplified) — note the one-time hygiene before the loop
# (added #36; see AFK_ENGINE_DESIGN.md for full spec).
session = load_afk_session()  # or {}
active_issues = get_current_live_subagent_issues()  # from spawn tracking
hygiene_res = remove_stale_status_labels_once(
    session=session, active_subagent_issues=active_issues, dry_run=...
)
# (runner processes hygiene_res for logging/events/optional comments)

while True:
    result = run_afk_cycle(dry_run=False, apply_changes=True)

    for req in result.spawn_requests:
        spawn_subagent(...)   # with proper worktree + prompt

    wait_for_subagents()

    # #31: after any worker exits (success/failure), extract tokens from harness output
    # and post immediately (before next cycle). Example:
    #   post_subagent_token_usage(issue=..., role=..., tokens_in=..., ... from get_...)
    #   record_subagent_completion_in_session(...)

    if result.no_more_work and no_running_subagents():
        print("All currently unblocked AFK work has been completed.")
        break
```

**Important (#36)**: The one-time stale `status-*` cleanup on `agent` issues (only when no active worker per dual detection) happens **once** at `/afk` entry, before any `run_afk_cycle()`. It is implemented as a narrow helper in `apply.py` (`remove_stale_status_labels_once`) that the runner calls. The engine and state machine are never involved. The runner (e.g. updated `cli.py`) owns loading the session, tracking live subagents, and acting on the rich results.

The user only needs to intervene for true HITL items or to steer (e.g. "stop", "only do #23", "pause after this cycle").

The engine (`engine.py`) performs:
- State discovery via `snapshot_builder`
- Decision making via the explicit state machine (`state_machine.py`)
- Plan generation via the translation layer (`translator.py`)
- Safe mutations (labels, session file, worktrees) via `apply.py`

As of the completion of issue #27, the state machine (`state_machine.py`) has expanded explicit coverage for additional designed policy areas: sophisticated initial triage (SpawnReviewer paths, label consistency checks per the authoritative rules), reviewer approval/rejection/escalation edges, and foundations for worktree policy decisions (via RequestWorktreeCleanup action support). 

Issue #22 completed the worktree lifecycle policy: the state machine now owns and emits `RequestWorktreeCleanup` (with associated labels) on completion (approval), rejection (to enable fresh worktree for retry attempts), escalation, and stale worktree on initial ready. `worktree_exists` from snapshots is used for fresh-vs-stale decisions. Translator materializes both `WorktreeAction` and `LabelChange`. See `state_machine.py`, updated tests (now 16+), `data_models.py`, and `translator.py`. The state machine is the authoritative executable spec for AFK rules including worktree lifecycle.

The thin runner receives an `AFKCycleResult` and only executes `SpawnRequest`s. It does **not** make policy decisions about what should be worked on. When all subagents finish, it immediately calls the engine again for the next cycle. The loop exits naturally only when the engine reports `no_more_work` **and** there are no active workers.

**Error / partial result handling for thin runner (per #26):** If `result.errors` is non-empty (rich dicts with `phase`, `error`, `type`, `details`, `attempt`, optional `issue`):
- Log and inspect (engine owns the details).
- Transient snapshot errors (common for gh/fetch): safe to immediately re-call `run_afk_cycle()`.
- Partial success (some spawns/actions despite errors): proceed with available work (best-effort is valuable).
- Persistent/total failures: surface to user or escalate (add `human` label).
See also `AFK_ENGINE_DESIGN.md` (entrypoint section) and `engine.py` docstring. The #26 delivery + prior apply best-effort (#24) makes the full loop robust for long-running autonomous use.

### Key Principle

The main agent is a **very thin runner** whose default job is simply:

- Repeatedly call `run_afk_cycle()`
- Execute whatever `SpawnRequest`s come back
- Monitor workers
- Re-cycle when workers exit
- Stop only when the engine says there is nothing left

Almost all judgment, prompt construction, checklist enforcement, worktree policy, and state transitions live inside the deterministic engine.

See `AFK_ENGINE_DESIGN.md` for the full architecture and `engine.py` for the primary entrypoint.

The older manual "smart orchestrator" loop is legacy and being phased out.

### Implementation Modules (New AFK Engine + Thin Runner)

The deterministic AFK engine + the Very Thin Runner live in this directory:

- `orchestrator.py` — **Canonical thin runner** (hygiene once, full persistent loop, worktree path resolution, CRITICAL prompt injection, spawn hook points, #31 token reporting). This is what the TUI `/afk` handler and `python -m afk.orchestrator` should use.
- `cli.py` — Minimal one-cycle CLI wrapper (still useful for ad-hoc debugging).
- `engine.py` — Primary entrypoint `run_afk_cycle()`
- `state_machine.py` — `decide_next_action()` + policy helpers (the explicit rules)
- `translator.py` — Action → concrete plan (including rich prompt generation + checklist injection)
- `apply.py` — Safe mutations (labels, session file, worktrees) + `remove_stale_status_labels_once` (#36)
- `snapshot_builder.py` — Raw data → rich snapshots + context
- `data_models.py` — All core typed models (`IssueSnapshot`, `SpawnRequest`, `AFKPlan`, `AFKCycleResult`, etc.)

See `AFK_ENGINE_DESIGN.md` for the complete architecture.

### Legacy Data Helpers, Coexistence Strategy, Thin Runner Migration Guide, and Deprecation Plan

**Context (delivered by #29)**: The AFK system has completed its transition to the deterministic **AFK Engine + very thin runner** architecture (see `AFK_ENGINE_DESIGN.md`, `engine.py`, `state_machine.py`, `translator.py`, `snapshot_builder.py`, `apply.py`, and prior issues #22–#28/#36). The older "smart orchestrator" model (direct discovery, blocker resolution, judgment, and spawning logic living in the main agent prompt or ad-hoc scripts) is legacy and being phased out. New development and full `/afk` usage target the engine.

#### How Existing `fetch_afk_issues.py` / `find_ready_afk_issues.py` Fit into the New World

These scripts are **stable, hardened, and intentionally preserved** as the reusable **data-gathering and classification layer**. They are **not** removed or deprecated for their core purpose:

- `fetch_afk_issues.py`: gh CLI-based fetcher for open `agent`-labeled issues. Performs blocker resolution (with per-run caching for performance, graceful handling of invalid/non-existent refs per #34, structured logging, timeouts). Invokes the pure logic and returns `{"ready": [...], "blocked": [...]}` (plus metadata). Primary consumer: `snapshot_builder.py` (via subprocess when live data is needed for `run_afk_cycle`).
- `find_ready_afk_issues.py`: Pure (stdlib-only) module with the authoritative `parse_blockers()` (implements the Dependency Syntax table in this doc, including markdown tolerance, "completed work" forms, follow-on list capture, code-block stripping for #34 robustness) + `find_ready_afk_issues()` classifier + `is_epic_issue()`. Excellent for direct calls, tests, and embedding.
- **Usage in the engine (new world)**: `snapshot_builder._fetch_live_agent_issues()` calls the fetcher; results feed `_convert_to_snapshots()` → rich `IssueSnapshot`s (with worktree discovery, phase derivation, etc.) passed to the state machine. The legacy code powers the "discover ready work" step without the thin runner or engine having to duplicate the logic.
- **Direct / standalone use remains fully supported and recommended for**:
  - Ad-hoc human inspection and live debugging: `python .grok/skills/afk/fetch_afk_issues.py`
  - Machine-readable snapshots for custom tooling: `... --json`
  - Unit and integration tests (see `test_find_ready_afk_issues.py` and the engine flow tests in `tests/`).
  - Validation/comparison during transition or when building custom snapshot providers.
  - One-off queries outside a full engine cycle.

They are **no longer the primary orchestration mechanism** for the complete autonomous loop. The engine owns end-to-end state machine decisions, prompt generation (including mandatory checklist injection), worktree policy, and safe apply. The thin runner only calls the engine entrypoint and executes the resulting `SpawnRequest`s.

All existing references in this document to the parser, its tests, and the fetcher (e.g. in Dependency Detection and "How the Parser Works") remain accurate and authoritative.

#### Step-by-Step Migration Guide for the Thin Runner

If you are authoring or maintaining a custom thin runner / orchestrator (or updating prompts that duplicated legacy discovery logic), follow this migration. The goal is to move all policy/judgment into the engine while keeping the runner extremely thin.

**Legacy pattern (pre-engine "smart orchestrator" style — simplified)**:
```python
# Direct data fetch + manual orchestration in the runner/main agent
while True:
    raw = subprocess.check_output(["python", ".grok/skills/afk/fetch_afk_issues.py", "--json"])
    data = json.loads(raw)
    ready, blocked = find_ready_afk_issues(...)  # or inline logic
    for item in ready:
        # manual: add in-progress label, post comment, construct prompt (no checklists), create worktree, spawn_subagent, record session...
    # manual monitor loop, re-fetch on completion, repeat until no ready + no subs
```

**New authoritative pattern (thin runner + engine — see `cli.py` and the loop in "Default Behavior" below)**:
```python
# Runner owns only: session, live subagent tracking, one-time hygiene, spawn execution, monitoring, re-cycle

# === One-time startup hygiene (#36) — thin runner responsibility, before first cycle ===
session = load_afk_session()  # or {}
active_issues = get_current_live_subagent_issues()  # from your spawn tracking
hygiene_results = remove_stale_status_labels_once(
    session=session, active_subagent_issues=active_issues, dry_run=..., repo_root=...
)
# Log/process hygiene_results (rich per-issue dicts); engine is untouched

while True:
    result: AFKCycleResult = run_afk_cycle(dry_run=False, apply_changes=True)

    for req in result.spawn_requests:
        # req is self-contained: issue, role ("implementor"|"reviewer"), worktree, branch, prompt (already includes full checklist + rich snapshot guidance), reason
        spawn_subagent_with_worktree(req)  # prepends CRITICAL worktree block etc.

    wait_for_subagents()  # or background task monitoring

    if result.no_more_work and no_running_subagents():
        print("All currently unblocked AFK work has been completed.")
        break

    # Rich observability (always available):
    # result.plan, result.applied_changes, result.notes, result.errors (per-phase structured)
```

**Migration steps**:
1. Update your entrypoint to import `from afk.engine import run_afk_cycle` and `from afk.apply import remove_stale_status_labels_once`.
2. Implement the one-time hygiene call exactly once per `/afk` (or equivalent invocation), after loading session + discovering live workers, before the first `run_afk_cycle()`.
3. Replace manual discovery/classification + prompt construction with the engine call + handling of `SpawnRequest`s (the translator now owns rich prompt generation, including dynamic snapshot context, retry guidance, and exact checklist embedding).
4. Remove (or comment) any duplicated blocker parsing, label state judgment, or worktree policy from the runner — the state machine is now the executable spec.
5. Update error handling to use `result.errors` (log per-phase; safe retry for transient snapshot errors; proceed on partial success; escalate only persistent cases).
6. Test incrementally with `--dry-run` / `apply_changes=False` and the Docker test harness.
7. Verify against the authoritative state machine rules in `state_machine.py` and tests.

See `orchestrator.py` (the canonical thin runner with hygiene + full loop + worktree materialization + CRITICAL prompt injection), `cli.py` (still useful for one-cycle), `engine.py` docstring (resilience contract for thin runners), and `tests/test_engine_flow.py` (simulated thin-runner loops, multi-cycle, hygiene smoke).

#### How to Run the Old and New Systems in Parallel During Transition

The design deliberately supports safe coexistence (no shared mutable state between direct data calls and engine cycles):

- **Zero interference**: Legacy scripts perform only read-only `gh` queries (list/view). An active engine-based `/afk` loop (which also uses gh under the hood via the fetcher) can run at the same time.
- **Practical patterns**:
  - Primary autonomous work: Use the engine (`/afk` or `python .grok/skills/afk/orchestrator.py` — the canonical Very Thin Runner). `cli.py` remains for quick one-cycle ad-hoc/debug use.
  - Live inspection / debugging: Run `python .grok/skills/afk/fetch_afk_issues.py --json` (or the human form) in a separate shell. Compare its ready/blocked output to what the engine sees on a dry-run cycle.
  - Validation during custom runner development: Capture fetcher JSON, inject via patched `build_snapshots_and_context` (pattern used heavily in `test_engine_flow.py`), or run the legacy classifier side-by-side with engine results.
  - One-off engine snapshot: `python .grok/skills/afk/orchestrator.py --once --dry-run` (or the older `cli.py` equivalent).
  - Full comparison harness: The 50+-issue load tests and multi-cycle simulations in the test suite exercise the engine while the underlying data layer is the same legacy code.
- Docker-first verification works for all combinations (`run-afk-tests.sh` mounts the tree read-only for safety).
- Benefit: You can keep legacy scripts around indefinitely for ad-hoc power and confidence checks while the production path is 100% the engine.

This matches the "production-hardened snapshot builder" goal from #25 while enabling the clean architecture of #22–#28.

#### Deprecation Plan for Old Orchestration Code in SKILL.md

This section **is** the deprecation plan (as explicitly required by the issue). It lives here so it is versioned, reviewable, and delivered to every implementor/reviewer via the checklists and prompts:

- **Phase 0 (now, post-#29 delivery)**: Full documentation of roles, migration, coexistence, and this plan. Legacy scripts remain first-class for data/ad-hoc/test use. "Preferred path" guidance in Implementation Notes updated to reflect engine primacy. Old manual loop descriptions annotated as legacy. No functionality removed.
- **Phase 1 (near-term — after real-world multi-cycle /afk success and positive adoption feedback, typically tracked in follow-up AFK issues)**: De-emphasize direct `fetch`/`find` examples in high-level "How to Run" and orchestrator notes (engine examples become the default). Add "data layer / ad-hoc / test only" emphasis in the scripts' own module docstrings via a future documentation PR/issue if warranted. SKILL.md and DESIGN.md will be updated again when this phase starts.
- **Phase 2 (longer-term — when direct use of the scripts for orchestration logic in prompts, custom runners, and docs has dropped to near-zero)**: Consider light formal deprecation notices (e.g., "Legacy data utility — prefer the engine for full cycles") in the top-level CLI docstrings and SKILL references. The scripts themselves, their tests, and their role inside `snapshot_builder` will be preserved (they are valuable, stable, and reusable). No removal of code or files is currently planned.
- **Advancement criteria**: (a) Multiple successful autonomous sessions using only engine paths, (b) reviewer confirmation that migration guidance in SKILL.md is clear and complete, (c) explicit new AFK issue or PR to advance the phase and update this plan + related examples.
- **Maintenance**: Any evolution of this plan or the legacy role is itself eligible for AFK tracking (agent label on a documentation issue). The checklists will continue to point implementors here for context.

**Related authoritative references**: `AFK_ENGINE_DESIGN.md` (new dedicated migration section added in #29), `engine.py:19` (run_afk_cycle contract), `snapshot_builder.py:46`, `cli.py:30` (#36 hygiene), and the full test suite (`run-afk-tests.sh`).

This plan ensures a smooth, low-risk transition while preserving everything that still works well.

### Checklists

The two mandatory checklists (`implementor-checklist.md` and `reviewer-checklist.md`) are now injected into prompts by the engine (in the translation layer) rather than relying solely on subagent discipline.