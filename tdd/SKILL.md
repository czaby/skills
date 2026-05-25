---
name: tdd
description: Test-driven development with red-green-refactor loop. Use when user wants to build features or fix bugs using TDD, mentions "red-green-refactor", wants integration tests, or asks for test-first development.
---

# TDD Skill (Updated for local git workflow)

**Local git rule (updated per user preference):**
**Do not** run `git commit` automatically after a Red → Green → Refactor cycle or any step.
Only perform `git commit` when the user explicitly asks for it (e.g. "commit", "git commit", "make a commit for this").
Only `git push` when the user explicitly requests it.

[Original TDD skill from Matt Pocock below — adapted for this workspace]

# Test-Driven Development

## Philosophy

**Core principle**: Tests should verify behavior through public interfaces, not implementation details. Code can change entirely; tests shouldn't.

**Good tests** are integration-style: they exercise real code paths through public APIs. They describe _what_ the system does, not _how_ it does it. A good test reads like a specification - "user can checkout with valid cart" tells you exactly what capability exists. These tests survive refactors because they don't care about internal structure.

**Bad tests** are coupled to implementation. They mock internal collaborators, test private methods, or verify through external means (like querying a database directly instead of using the interface). The warning sign: your test breaks when you refactor, but behavior hasn't changed. If you rename an internal function and tests fail, those tests were testing implementation, not behavior.

See [tests.md](tests.md) for examples and [mocking.md](mocking.md) for mocking guidelines.

## Anti-Pattern: Horizontal Slices

**DO NOT write all tests first, then all implementation.** This is "horizontal slicing" - treating RED as "write all tests" and GREEN as "write all code."

This produces **crap tests**:

- Tests written in bulk test _imagined_ behavior, not _actual_ behavior
- You end up testing the _shape_ of things (data structures, function signatures) rather than user-facing behavior
- Tests become insensitive to real changes - they pass when behavior breaks, fail when behavior is fine
- You outrun your headlights, committing to test structure before understanding the implementation

**Correct approach**: Vertical slices via tracer bullets. One test → one implementation → repeat. Each test responds to what you learned from the previous cycle. Because you just wrote the code, you know exactly what behavior matters and how to verify it.

```
WRONG (horizontal):
  RED:   test1, test2, test3, test4, test5
  GREEN: impl1, impl2, impl3, impl4, impl5

RIGHT (vertical):
  RED→GREEN: test1→impl1
  RED→GREEN: test2→impl2
  RED→GREEN: test3→impl3
  ...
```

## Workflow

### 1. Planning

When exploring the codebase, use the project's domain glossary so that test names and interface vocabulary match the project's language, and respect ADRs in the area you're touching.

Before writing any code:

- [ ] Confirm with user what interface changes are needed
- [ ] Confirm with user which behaviors to test (prioritize)
- [ ] Identify opportunities for [deep modules](deep-modules.md) (small interface, deep implementation)
- [ ] Design interfaces for [testability](interface-design.md)
- [ ] List the behaviors to test (not implementation steps)
- [ ] Get user approval on the plan

Ask: "What should the public interface look like? Which behaviors are most important to test?"

**You can't test everything.** Confirm with the user exactly which behaviors matter most. Focus testing effort on critical paths and complex logic, not every possible edge case.

### 2. Tracer Bullet

Write ONE test that confirms ONE thing about the system:

```
RED:   Write test for first behavior → test fails
GREEN: Write minimal code to pass → test passes
```

This is your tracer bullet - proves the path works end-to-end.

(Commit only when the user explicitly requests it.)

### 3. Incremental Loop

For each remaining behavior:

```
RED:   Write next test → fails
GREEN: Minimal code to pass → passes
```

Rules:

- One test at a time
- Only enough code to pass current test
- Don't anticipate future tests
- Keep tests focused on observable behavior

(Commit only when the user explicitly requests it.)

### 4. Refactor

After all tests pass (or after a meaningful group), look for [refactor candidates](refactoring.md):

- [ ] Extract duplication
- [ ] Deepen modules (move complexity behind simple interfaces)
- [ ] Apply SOLID principles where natural
- [ ] Consider what new code reveals about existing code
- [ ] Run tests after each refactor step

**Never refactor while RED.** Get to GREEN first.

(Commit only when the user explicitly requests it.)

## Checklist Per Cycle

```
[ ] Test describes behavior, not implementation
[ ] Test uses public interface only
[ ] Test would survive internal refactor
[ ] Code is minimal for this test
[ ] No speculative features added
```

## Local Git Commit Discipline (Updated)

- **Do not auto-commit** after RED, GREEN, or Refactor steps.
- Only run `git commit` when the user explicitly requests it (e.g. "commit this", "git commit now").
- Use clear, descriptive messages when a commit is requested.
- Never `git push` unless the user explicitly says "push", "git push", or similar.

If the user wants a commit for the current cycle, they will say so. You can suggest good commit points, but do not execute them automatically.

## UI / Frontend Testing Rule (Added 2026-05-23 per user request)

For any user-facing website or UI behavior (especially JavaScript-driven features like sorting, filtering, rendering):

- **Always write an automated browser test first** (RED) that drives a **real browser**.
- The test must actually open the page, interact with it (click, type, etc.), and assert on the visible/DOM result.
- **Never** rely only on manual verification or unit tests of JS functions for UI behavior.
- Use **Docker** to run the browser and test runner. Do not install Selenium, Playwright, or browsers on the host machine.
- Recommended stack: Playwright running inside the official `mcr.microsoft.com/playwright` Docker image.
- For development, you can run with `HEADED=1 ./tests/run-browser-tests.sh` (after `xhost +local:docker` on Linux) to watch the tests execute in a visible browser window.
- The test should start a local HTTP server (in-process) so `fetch()` calls work.
- Only mark the cycle GREEN after the browser test passes cleanly.
- Record this rule in the project TDD skill and follow it for every future UI slice.

## Independent / Autonomous Multi-Feature Execution (AFK Mode) — Added 2026-05-23

When a user provides a backlog of multiple independent features/tasks (often called "AFK features") and wants you to execute them with minimal supervision:

### Core Pattern
1. **User provides a backlog** (e.g. `website-afk-backlog.md`, `ISSUES.md`, or a numbered list).
2. **You maintain a living tracking document** (e.g. `*-backlog.md`) with status for each item (pending / in progress / done).
3. **Process one feature at a time**, completely independently:
   - Write failing test(s) first (RED) — usually real integration/browser tests.
   - Implement the minimal code required to make the test(s) pass (GREEN).
   - Run the relevant tests (frequently in isolation to avoid cross-test pollution).
   - Refactor only if needed and tests stay green.
   - Make a **local git commit** with a clear message describing the feature + TDD cycle.
4. **Only surface to the user** when:
   - You hit a blocker, or
   - You have completed the entire batch of requested AFK features.

### Key Practices Observed to Work Well
- Use Docker for *all* test execution (Playwright, Python/agent tests, etc.). Never install test runners or browsers on the host.
- For browser-based UI work: always drive real browsers via Playwright in Docker. Prefer running specific spec files when testing one feature in isolation.
- When persistence (localStorage, files, etc.) is involved, add aggressive cleanup in test `beforeEach` blocks or run tests in isolation.
- For non-UI work (e.g. agents): write pytest-style tests and execute them inside Docker containers with the required dependencies.
- Keep commits atomic and frequent — one commit per completed feature.
- Update the tracking document after every completed feature so the user has a clear audit trail when they return.
- Only push when the user explicitly says "commit and push".

### Example User Directive This Pattern Supports
> "Implement and test one by one all AFK features. Make a commit after every feature. Report back to me only if you have a blocker or you are done with all AFK features."

This mode allows the user to hand off a batch of work and receive a clean series of commits + passing tests when they check back in.

Record this pattern in the project TDD skill so it can be reused for future batches of independent work.
