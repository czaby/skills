"""
Unit tests for the AFK state machine.

These tests are intentionally fast and isolated. They use hand-crafted
IssueSnapshot + AFKContext objects so we can test every transition
without any external dependencies (GitHub, filesystem, etc.).

This is the style of testing we want for the core decision logic.

Run via:
    python -m pytest .grok/skills/afk/tests/ -q
"""

from __future__ import annotations

import sys
from pathlib import Path

# Robust imports for both pytest and direct execution
try:
    from afk.data_models import IssueSnapshot, AFKContext, RequestWorktreeCleanup
    from afk.state_machine import decide_next_action
except ImportError:
    # Direct execution fallback
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from data_models import IssueSnapshot, AFKContext, RequestWorktreeCleanup
    from state_machine import decide_next_action


def _ctx() -> AFKContext:
    """Convenience helper for a default context."""
    return AFKContext(
        checklist_versions={"implementor": "v1", "reviewer": "v1"}
    )


# =============================================================================
# Basic / Initial State
# =============================================================================

def test_clean_issue_starts_as_implementor():
    snapshot = IssueSnapshot(number=42)
    action = decide_next_action(snapshot, _ctx())

    assert action.__class__.__name__ == "SpawnImplementor"
    assert action.issue == 42


# =============================================================================
# In Review → Approval Path
# =============================================================================

def test_reviewer_approval_requests_worktree_cleanup_and_final_labels():
    """
    Per #22 worktree lifecycle policy (completion path):
    On reviewer approval, SM returns RequestWorktreeCleanup (with associated
    final labels) so translator/apply can cleanup the worktree.
    This encodes the engine-owned policy instead of leaving it implicit.
    """
    snapshot = IssueSnapshot(
        number=17,
        current_afk_phase="in_review",
        last_subagent_outcome="approved",
    )
    action = decide_next_action(snapshot, _ctx())

    assert action.__class__.__name__ == "RequestWorktreeCleanup"
    assert action.issue == 17
    assert "grok" in action.add
    assert "status-in-review" in action.remove
    assert action.reason and ("cleanup" in action.reason.lower() or "approved" in action.reason.lower())


# =============================================================================
# In Review → Rejection + Retry Logic
# =============================================================================

def test_first_reviewer_rejection_requests_worktree_cleanup_for_fresh_retry():
    """
    Per #22: On rejection (retry < max), SM requests worktree cleanup (with
    labels for next attempt). This ensures the next implementor gets a *fresh*
    worktree (policy: new worktree for retry attempts).
    """
    snapshot = IssueSnapshot(
        number=23,
        current_afk_phase="in_review",
        last_subagent_outcome="rejected",
        retry_count=0,
    )
    action = decide_next_action(snapshot, _ctx())

    assert action.__class__.__name__ == "RequestWorktreeCleanup"
    assert "retry-1" in action.add
    assert "status-in-progress" in action.add
    assert "status-in-review" in action.remove
    assert action.reason and "cleanup" in action.reason.lower()


def test_second_reviewer_rejection_requests_worktree_cleanup_for_fresh_retry():
    """
    Same policy as first rejection: cleanup for fresh worktree on retry attempt.
    """
    snapshot = IssueSnapshot(
        number=23,
        current_afk_phase="in_review",
        last_subagent_outcome="rejected",
        retry_count=1,
    )
    action = decide_next_action(snapshot, _ctx())

    assert action.__class__.__name__ == "RequestWorktreeCleanup"
    assert "retry-2" in action.add
    assert "status-in-progress" in action.add
    assert action.reason and "cleanup" in action.reason.lower()


def test_third_reviewer_rejection_requests_worktree_cleanup_and_escalates_to_human():
    """
    Per #22: On final escalation (retry-2 rejection), request cleanup + human
    escalation labels. Engine owns the full terminal lifecycle decision.
    """
    snapshot = IssueSnapshot(
        number=23,
        current_afk_phase="in_review",
        last_subagent_outcome="rejected",
        retry_count=2,
    )
    action = decide_next_action(snapshot, _ctx())

    assert action.__class__.__name__ == "RequestWorktreeCleanup"
    assert action.issue == 23
    assert "human" in action.add
    assert any("agent" in r or "status" in r for r in action.remove)
    assert action.reason and ("cleanup" in action.reason.lower() or "escalat" in action.reason.lower())


# =============================================================================
# Already in rejected_review Phase
# =============================================================================

def test_rejected_review_with_retry_2_requests_cleanup_and_escalates():
    """
    Escalation via rejected_review phase also requests worktree cleanup.
    """
    snapshot = IssueSnapshot(
        number=55,
        current_afk_phase="rejected_review",
        last_subagent_outcome="rejected",
        retry_count=2,
    )
    action = decide_next_action(snapshot, _ctx())

    assert action.__class__.__name__ == "RequestWorktreeCleanup"
    assert "human" in action.add
    assert action.reason and "cleanup" in action.reason.lower()


def test_rejected_review_below_limit_requests_worktree_cleanup_for_fresh_retry():
    """
    rejected_review phase + retry<2 also triggers cleanup + retry labels (shared handler).
    """
    snapshot = IssueSnapshot(
        number=55,
        current_afk_phase="rejected_review",
        last_subagent_outcome="rejected",
        retry_count=1,
    )
    action = decide_next_action(snapshot, _ctx())

    assert action.__class__.__name__ == "RequestWorktreeCleanup"
    assert "retry-2" in action.add
    assert "status-in-progress" in action.add
    assert action.reason and "cleanup" in action.reason.lower()


# =============================================================================
# Checklist-test awareness (illustrative)
# =============================================================================

def test_checklist_test_issue_still_starts_as_implementor():
    """Checklist-test issues should follow the normal flow."""
    snapshot = IssueSnapshot(
        number=16,
        current_labels=["agent", "checklist-test"],
    )
    action = decide_next_action(snapshot, _ctx())

    assert action.__class__.__name__ == "SpawnImplementor"


# =============================================================================
# Blocker Awareness (Issue #21)
# =============================================================================

def test_initial_action_respects_open_blockers():
    """If an issue has open blockers, we should not start new work on it."""
    snapshot = IssueSnapshot(
        number=42,
        current_labels=["agent"],
        has_open_blockers=True,
        open_blockers=[15],
    )
    action = decide_next_action(snapshot, _ctx())

    assert action.__class__.__name__ == "NoOp"
    assert "blocked" in action.reason.lower()


def test_checklist_test_issue_still_respects_blockers():
    """Even checklist-test issues should respect blockers."""
    snapshot = IssueSnapshot(
        number=16,
        current_labels=["agent", "checklist-test"],
        has_open_blockers=True,
        open_blockers=[99],
    )
    action = decide_next_action(snapshot, _ctx())

    assert action.__class__.__name__ == "NoOp"


def test_unblocked_issue_starts_normally():
    """When blockers are resolved, the issue should become eligible again."""
    snapshot = IssueSnapshot(
        number=42,
        current_labels=["agent"],
        has_open_blockers=False,
        open_blockers=[],
    )
    action = decide_next_action(snapshot, _ctx())

    assert action.__class__.__name__ == "SpawnImplementor"


# =============================================================================
# Additional policy tests
# =============================================================================

def test_in_progress_phase_returns_noop():
    snapshot = IssueSnapshot(
        number=42,
        current_afk_phase="in_progress",
    )
    action = decide_next_action(snapshot, _ctx())
    assert action.__class__.__name__ == "NoOp"


# =============================================================================
# #27 expansions: sophisticated triage + SpawnReviewer path (TDD tracer bullet #1)
# =============================================================================

def test_in_review_after_implementor_spawns_reviewer():
    """After implementor finishes (phase in_review + last_role=implementor or no outcome yet),
    the state machine should spawn a reviewer (sophisticated initial/transition triage per #27).
    This exercises the previously unhandled path to SpawnReviewer action.
    """
    snapshot = IssueSnapshot(
        number=99,
        current_afk_phase="in_review",
        last_subagent_role="implementor",
        last_subagent_outcome=None,
    )
    action = decide_next_action(snapshot, _ctx())

    assert action.__class__.__name__ == "SpawnReviewer"
    assert action.issue == 99
    assert "review" in (getattr(action, "reason", "") or "").lower() or "implementor" in (getattr(action, "reason", "") or "").lower()


def test_inconsistent_labels_escalates_to_human():
    """Per SKILL.md authoritative label state machine, any inconsistent combo of status-* labels
    must trigger immediate escalation to human (additional edge in reviewer/escalation flows per #27).
    """
    snapshot = IssueSnapshot(
        number=123,
        current_labels=["agent", "status-in-progress", "status-in-review"],
    )
    action = decide_next_action(snapshot, _ctx())
    assert action.__class__.__name__ == "EscalateToHuman"
    assert "inconsistent" in (action.reason or "").lower() or "label" in (action.reason or "").lower() or "escalat" in (action.reason or "").lower()


# =============================================================================
# #22 Worktree Lifecycle Policy Tests (TDD vertical slices)
# =============================================================================

def test_initial_ready_with_existing_worktree_requests_cleanup_for_fresh_start():
    """
    Policy (#22): If a ready issue already has a worktree (stale from prior run),
    SM requests cleanup first. This ensures the implementor spawn gets a *fresh*
    worktree. (Next cycle after cleanup will spawn.)
    Uses the snapshot.worktree_exists field (previously unused in decisions).
    """
    snapshot = IssueSnapshot(
        number=42,
        current_labels=["agent"],
        worktree_exists=True,
        worktree_path="/tmp/grok-afk-worktrees/issue-42",
    )
    action = decide_next_action(snapshot, _ctx())

    assert action.__class__.__name__ == "RequestWorktreeCleanup"
    assert action.issue == 42
    assert "fresh" in action.reason.lower() or "stale" in action.reason.lower() or "cleanup" in action.reason.lower()


def test_initial_ready_without_worktree_starts_implementor():
    """Normal case: no existing worktree -> spawn fresh implementor (no cleanup needed)."""
    snapshot = IssueSnapshot(
        number=99,
        current_labels=["agent"],
        worktree_exists=False,
    )
    action = decide_next_action(snapshot, _ctx())

    assert action.__class__.__name__ == "SpawnImplementor"
    assert action.issue == 99


# =============================================================================
# Regression tests for issue #33: `grok` label must not block future AFK work
# (TDD red -> green)
# =============================================================================

def test_grok_label_no_longer_derives_completed_phase():
    """TDD test for #33.

    The `grok` label (used as completion signature on approval) must NOT cause
    _derive_phase() to return "completed" (the root cause of open agent+grok
    issues being incorrectly skipped via unhandled phase -> NoOp).

    Status-* labels must continue to derive their phases correctly (precedence).
    After the fix, open `agent`+`grok` issues (no status-*, no blockers) will
    correctly be treated as initial/ready and eligible for follow-up AFK work
    (docs, architecture, fixes, etc.) per the issue request.

    This test is written first (red under old code), then source fixed (green).
    """
    # Robust import (matches pattern used elsewhere in this test file)
    try:
        from afk.snapshot_builder import _derive_phase
    except ImportError:
        sys.path.insert(0, str(Path(__file__).parent.parent))
        from snapshot_builder import _derive_phase

    # Core assertion for the bugfix: grok must not produce the blocking "completed" phase
    assert _derive_phase(["agent", "grok"]) is None
    assert _derive_phase(["grok"]) is None
    assert _derive_phase([]) is None
    assert _derive_phase(["agent"]) is None

    # Status-* labels must still derive correctly (and take precedence over any grok)
    assert _derive_phase(["grok", "status-in-progress"]) == "in_progress"
    assert _derive_phase(["status-in-review", "agent", "grok"]) == "in_review"
    assert _derive_phase(["status-rejected-review", "grok"]) == "rejected_review"
    assert _derive_phase(["grok", "status-in-review", "retry-1"]) == "in_review"


def test_open_agent_grok_issue_is_ready_for_further_afk_work():
    """Positive behavior test for #33 fix.

    An open issue that carries both `agent` and the historical `grok` completion
    marker (but no status-* and no open blockers) must be treated as initial/ready
    and spawn a new implementor. This enables follow-up AFK work (e.g. docs,
    architecture refinements, additional fixes) on previously completed slices.

    Simulates the exact scenario from the bug report using the current snapshot
    shape (phase=None because derive no longer injects "completed" for grok).
    """
    snapshot = IssueSnapshot(
        number=33,
        current_labels=["agent", "grok", "afk-skill"],
        current_afk_phase=None,  # as produced by snapshot_builder post-#33 fix
        has_open_blockers=False,
        worktree_exists=False,
    )
    action = decide_next_action(snapshot, _ctx())

    assert action.__class__.__name__ == "SpawnImplementor"
    assert action.issue == 33
    assert "starting fresh" in (getattr(action, "reason", "") or "").lower() or "fresh" in (getattr(action, "reason", "") or "").lower()

