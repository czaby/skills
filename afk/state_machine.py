"""
AFK State Machine

This module contains the explicit, centralized decision logic for the AFK engine.
The primary entry point is `decide_next_action`.

Design goals:
- Make the rules readable and reviewable as code.
- Keep `decide_next_action` as a relatively flat dispatcher.
- Delegate to focused, well-named policy helper functions.
- Be highly unit-testable (no side effects, no GitHub calls).
"""

from __future__ import annotations

from .data_models import (
    IssueSnapshot,
    AFKContext,
    Action,
    SpawnImplementor,
    SpawnReviewer,
    RequestWorktreeCleanup,
    EscalateToHuman,
    NoOp,
)


def decide_next_action(issue: IssueSnapshot, context: AFKContext) -> Action:
    """
    Core decision function for a single issue.

    Returns a high-level declarative Action that the translation layer
    will later turn into concrete plan items (labels, SpawnRequests, etc.).

    Blocker policy (per issue #21):
    - If the issue has open blockers, we generally do **not** start new autonomous
      work on it (return NoOp).
    - This applies especially strongly to initial / ready states.
    - Once work is already in progress (in_progress, in_review, etc.), we usually
      let the current phase complete even if new blockers appear (the subagent
      is already running).
    """
    # Early blocker gate for initial/ready states (core of #21)
    if issue.has_open_blockers and (issue.current_afk_phase or "none") in (None, "none", "ready"):
        return NoOp(
            reason=f"Blocked by open issues: {issue.open_blockers}. Will become eligible once blockers are resolved."
        )

    # #27 expansion: label state consistency (authoritative from SKILL.md)
    # Any combo with >1 status-* label is inconsistent and must escalate.
    status_labels = [l for l in (issue.current_labels or []) if l.startswith("status-")]
    if len(status_labels) > 1:
        return EscalateToHuman(
            issue=issue.number,
            reason="Inconsistent AFK state: multiple status-* labels present (e.g. status-in-progress + status-in-review). Escalating per SKILL label state machine rules.",
        )

    phase = issue.current_afk_phase or "none"

    if phase in (None, "none", "ready"):
        return _decide_initial_action(issue, context)

    if phase == "in_progress":
        return _decide_from_implementor_in_progress(issue, context)

    if phase == "in_review":
        return _decide_from_in_review(issue, context)

    if phase == "rejected_review":
        return _decide_from_rejected_review(issue, context)

    return NoOp(reason=f"Unhandled AFK phase: {phase}")


# =============================================================================
# Phase-specific decision helpers
# =============================================================================

def _decide_initial_action(issue: IssueSnapshot, context: AFKContext) -> Action:
    """
    Issue has no active AFK status yet.

    Default policy: Most agent-labeled issues start with an implementor.

    Special handling:
    - Issues carrying the "checklist-test" label are explicitly intended to
      exercise the full AFK implementor + reviewer + checklist process.
      They follow the normal flow.
    """
    checklist_ref = context.checklist_versions.get("implementor", "latest")

    # #30 Epic lifecycle rule guard (agent Epics only):
    # Never spawn direct work (implementor) on an agent-labeled Epic, regardless of
    # blockers state. Epics are meta; they are blocked while children open (via
    # snapshot enrichment) and auto-closed via apply hook on last AFK child close.
    # (Prevents the undesirable "picking up the Epic itself" described in #30.)
    if getattr(issue, "is_epic", False) and "agent" in (issue.current_labels or []):
        return NoOp(
            reason="Agent-labeled Epic (is_epic=True per snapshot); subject to Epic lifecycle rule. "
                   "Blocked while open direct children (sub-issue graph). Auto-close only via apply-layer "
                   "post-child-completion hook. No direct AFK work/spawn on Epics."
        )

    # #22 worktree lifecycle policy: if stale worktree exists for a ready issue,
    # request cleanup first (ensures fresh worktree for the new implementor).
    # The without-worktree case (or after cleanup) proceeds to spawn.
    if issue.worktree_exists:
        return RequestWorktreeCleanup(
            issue=issue.number,
            reason="Stale worktree exists for ready issue — requesting cleanup to provide a fresh worktree for the implementor (per engine lifecycle policy).",
        )

    reason = "No active AFK status — starting fresh"
    if "checklist-test" in (issue.current_labels or []):
        reason = "Checklist verification test issue — exercising full AFK flow"

    return SpawnImplementor(
        issue=issue.number,
        reason=reason,
        checklist_ref=checklist_ref,
        snapshot=issue,
    )


def _decide_from_implementor_in_progress(issue: IssueSnapshot, context: AFKContext) -> Action:
    """
    The issue is currently being worked on by an implementor
    (status-in-progress).
    """
    # While an implementor is running we generally do nothing.
    # The engine will be called again when the subagent exits.
    #
    # Worktree lifecycle policy is now owned by the state machine (#22):
    # - Stale worktrees cleaned on initial/ready if present.
    # - Cleanup requested on approval, rejection (for fresh retry), escalation.
    # - Fresh worktree vs reuse decisions driven from here via RequestWorktreeCleanup.
    return NoOp(reason="Implementor still in progress")


def _decide_from_in_review(issue: IssueSnapshot, context: AFKContext) -> Action:
    """The issue is currently in 'status-in-review' (a reviewer has finished or the issue just transitioned)."""
    outcome = issue.last_subagent_outcome

    # #27 expansion: sophisticated triage for reviewer spawn.
    # If we just transitioned from implementor (or no outcome yet), spawn reviewer
    # rather than assuming an unexpected outcome. This closes the implementor -> reviewer
    # loop via the engine state machine.
    if issue.last_subagent_role == "implementor" or outcome is None or outcome not in ("approved", "rejected"):
        checklist_ref = context.checklist_versions.get("reviewer", "latest")
        return SpawnReviewer(
            issue=issue.number,
            reason="Implementor phase complete or transitioned to review; spawning fresh reviewer for independent assessment (expanded triage per #27)",
            checklist_ref=checklist_ref,
            snapshot=issue,
        )

    if outcome == "approved":
        return _handle_reviewer_approval(issue, context)

    if outcome == "rejected":
        return _handle_reviewer_rejection(issue, context)

    return NoOp(reason=f"Unexpected outcome while in_review: {outcome}")


def _decide_from_rejected_review(issue: IssueSnapshot, context: AFKContext) -> Action:
    """The issue is in rejected_review state."""
    return _handle_reviewer_rejection(issue, context)


# =============================================================================
# Policy helpers (reviewer flow, retry, escalation, etc.)
# =============================================================================

def _handle_reviewer_approval(issue: IssueSnapshot, context: AFKContext) -> Action:
    """
    Reviewer approved the work.

    Worktree lifecycle policy (#22): return RequestWorktreeCleanup carrying the
    final labels. This moves the decision into the explicit state machine.
    Translator will materialize both LabelChange and WorktreeAction(cleanup).
    """
    return RequestWorktreeCleanup(
        issue=issue.number,
        reason="Reviewer approved the work — requesting worktree cleanup per engine lifecycle policy (completion path).",
        add=["grok"],
        remove=["status-in-review"],
    )


def _handle_reviewer_rejection(issue: IssueSnapshot, context: AFKContext) -> Action:
    """
    Reviewer rejected the work.

    Rules:
    - If this is the 2nd rejection (retry_count >= 2), escalate to human.
    - Otherwise, increment retry counter, move back to in-progress, and let
      a new implementor attempt fix the issues.
    """
    current_retry = issue.retry_count

    if current_retry >= 2:
        return RequestWorktreeCleanup(
            issue=issue.number,
            reason="Maximum retries (retry-2) reached — requesting worktree cleanup and escalating to human per lifecycle policy.",
            add=["human"],
            remove=["agent", "status-in-review", "status-in-progress", "rejected_review"],
        )

    next_retry = current_retry + 1

    return RequestWorktreeCleanup(
        issue=issue.number,
        reason="Reviewer rejection — requesting worktree cleanup so the retry implementor gets a fresh worktree (per lifecycle policy for new attempts).",
        add=[f"retry-{next_retry}", "status-in-progress"],
        remove=["status-in-review", "rejected_review"],
    )


# Future helpers (if needed):
# - _should_spawn_reviewer(...)
# - _compute_initial_action_for_checklist_test_issue(...)
# (Worktree lifecycle policy per #22 is now implemented via RequestWorktreeCleanup
# returns in the approval/rejection/escalation/initial paths + worktree_exists checks.)
