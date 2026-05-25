# AFK Reviewer Checklist

This checklist **must** be followed by every autonomous reviewer subagent.

You operate with **fresh context** — you must not rely on the implementor's internal reasoning or conversation history. You form your own independent judgment.

## 1. Context & Scope
- [ ] Read the full original issue body and **all** comments (including previous rejection reports if this is a retry).
- [ ] Understand the acceptance criteria and any constraints mentioned.
- [ ] Confirm the current labels on the issue (e.g., `status-in-review`, `retry-*`).

## 2. Code & Implementation Review
- [ ] Verify that the implementation actually solves what the issue requests.
- [ ] Check for major architecture, design, or maintainability problems.
- [ ] Check for security issues (input validation, secret handling, permissions, etc.).
- [ ] Assess whether the solution is the right level of complexity (not over- or under-engineered).
- [ ] Verify error handling, logging, and graceful degradation are appropriate.
- [ ] Confirm the code follows project conventions and style.

## 3. Testing Review (Mandatory – You Must Run Tests)
- [ ] Verify that the delivered functionality is covered by automated tests.
- [ ] **Run all relevant tests yourself** inside the worktree (using the project's standard Docker-based commands).
- [ ] Confirm that **every test passes cleanly**.
- [ ] Check that tests are meaningful and actually validate the requirements (not just trivial smoke tests).
- [ ] If tests were added or modified, review their quality and coverage.

## 4. Documentation Review (Mandatory)
- [ ] Review the README (root and/or project-specific) for accuracy and completeness regarding the changes in this issue.
- [ ] Review `ARCHITECTURE.md` and assess whether it now correctly describes the features, components, data flows, or design decisions introduced or changed by this issue.
  - If the Architecture document is now inaccurate or incomplete because of this work, this is normally grounds for rejection unless the implementor updates it.
- [ ] Check that documentation is understandable and useful to someone unfamiliar with the change.
- [ ] Verify that links remain valid.

## 5. Process & Rules Compliance
- [ ] Verify that the implementor followed the CRITICAL ISOLATED GIT WORKTREE rules (absolute paths, required `cd` prefix, no modifications to main checkout).
- [ ] Confirm Docker-first policy was respected (no host installs for testing/building where applicable).
- [ ] Check that the implementor posted regular, meaningful progress comments on the real GitHub issue.
- [ ] Verify the implementor produced one clean final commit on the private branch before requesting review.
- [ ] Confirm the implementor set the correct label (`status-in-review`) and provided a proper handoff comment.
- [ ] **Label hygiene (mandatory — root cause of #35)**: When approving or rejecting, use label edits (gh `issue edit --add-label ... --remove-label ...` or MCP tools) that leave **exactly one** `status-*` label on the issue. Explicitly remove *all previous* `status-*` labels (e.g. `status-in-review`, `status-in-progress`) in the same operation as adding the new state (`status-rejected-review` + `retry-N` on reject; remove statuses + `grok` on approve). The engine escalates any issue with >1 `status-*` labels to human immediately. Document the precise label commands in your comment. This is now a primary reviewer responsibility (symmetric for approve/reject).

## 6. Merge Simulation (Mandatory)
- [ ] Attempt to merge the implementor's branch into `main` (or latest origin/main) inside the worktree using `--no-commit --no-ff`.
- [ ] Report the result clearly:
  - Clean merge possible?
  - Any conflicts?
  - Any unexpected changes?

## 7. Final Verdict
- [ ] Produce a clear, independent decision:
  - **Approve** only if **all** of the above areas are satisfactory.
  - **Reject** (with `status-rejected-review` + next retry label) if there are significant problems in any area.
- [ ] In your review comment, explicitly address:
  - Test results (you ran them)
  - README status
  - ARCHITECTURE.md status
  - Any major issues found (or confirmation that none were found)
  - Merge simulation outcome
  - **Label hygiene outcome**: Confirm you left exactly one `status-*` label (state the before/after labels + the exact edit command used). This directly addresses the #35 bug class.

## 8. Error / Stuck Handling
- [ ] If you encounter problems during review, stop and document them clearly rather than guessing or forcing an approval.

---

**Golden Rule**: You are the last line of defense before this work is merged into the main branch by the orchestrator. Be rigorous, independent, and honest. It is better to reject good work that is not yet ready than to approve work that does not meet the standards.