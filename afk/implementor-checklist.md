# AFK Implementor Checklist

This checklist **must** be followed by every autonomous implementor subagent working on an `agent`-labeled issue.

The subagent is expected to treat every item as mandatory. "I think this doesn't apply" is not acceptable without explicit justification in the final handoff comment.

## 1. Understanding & Planning
- [ ] Read the full issue body and **all** comments (including any previous rejection reports).
- [ ] Read relevant project documents: PRD.md, ISSUES.md, ARCHITECTURE.md (current state), grok.md, and AGENTS.md.
- [ ] Identify all testable acceptance criteria.
- [ ] Explore the existing codebase in the assigned isolated worktree to understand current state and conventions.
- [ ] Create a clear plan (can be in thinking or todo list) before writing significant code.

## 2. Worktree & Process Discipline
- [ ] Work **exclusively** inside the assigned isolated git worktree using absolute paths and the required `cd` prefix for all terminal commands.
- [ ] Never modify the original main checkout.
- [ ] Post meaningful progress comments on the real GitHub issue at least every 20–30 minutes of real work (or after major milestones).
- [ ] Follow Docker-first policy: never install tools on the host for testing, building, or running the project.

## 3. Implementation
- [ ] Implement exactly what the issue requests plus any requirements from previous rejection comments (if this is a retry).
- [ ] Do not add significant scope beyond the issue without explicit justification.
- [ ] Follow existing project conventions, patterns, and style.
- [ ] Handle errors gracefully with appropriate logging.
- [ ] Remove any temporary debug code, commented-out experiments, or dead code before final handoff.

## 4. Testing (Mandatory)
- [ ] Write or update automated tests that cover the requirements and acceptance criteria.
- [ ] Use TDD (red → green → refactor) for non-trivial new functionality.
- [ ] Run **all** relevant tests (unit, integration, and any existing test suites for the affected area).
- [ ] Confirm that **every test passes** cleanly before requesting review.
- [ ] Tests must be runnable via the project's standard Docker-based test commands (no host-only execution for heavy tests).

## 5. Documentation
- [ ] Update the README (root and/or project-specific) so that the new functionality is clearly described and usable by a new reader.
- [ ] Update `ARCHITECTURE.md` if the change affects:
  - High-level architecture
  - Major components or data flow
  - Design decisions
  - Public interfaces
  - Significant new capabilities
- [ ] If no Architecture document update is needed, explicitly justify why in the final handoff comment.
- [ ] Ensure all links in documentation remain valid.

## 6. Final Handoff Preparation
- [ ] Produce one clean final commit on the private branch (referencing the GitHub issue number).
- [ ] In the "ready for reviewer" comment on GitHub, include:
  - Summary of what was delivered
  - List of changed files
  - Test results (which tests were run and that they all passed)
  - Documentation Impact Statement (README + ARCHITECTURE.md status)
  - How to verify the work locally
- [ ] Set the appropriate label (`status-in-review` or equivalent) and exit cleanly.

## 7. Error / Stuck Handling
- [ ] If blocked, post a detailed comment on the GitHub issue explaining the problem.
- [ ] Leave the worktree exactly as-is (no cleanup or reset).
- [ ] Exit without looping indefinitely.

---

**Rule**: You may not declare the issue complete until you have honestly completed (or explicitly justified skipping) every item above. The reviewer will check this checklist.