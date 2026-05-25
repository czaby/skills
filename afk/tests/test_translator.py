"""
Basic tests for the translation layer.

These tests verify that high-level Actions are correctly turned into
concrete plan items, including rich SpawnRequests with checklist references.

Run via:
    python -m pytest .grok/skills/afk/tests/ -q
"""

from __future__ import annotations

import sys
from pathlib import Path

try:
    from afk.data_models import (
        AFKContext,
        IssueSnapshot,
        SpawnImplementor,
        SpawnReviewer,
        SpawnRequest,
        ApplyLabelChanges,
        RequestWorktreeCleanup,
        LabelChange,
        WorktreeAction,
    )
    from afk.translator import translate_actions_to_plan
except ImportError:
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from data_models import (
        AFKContext,
        IssueSnapshot,
        SpawnImplementor,
        SpawnReviewer,
        SpawnRequest,
        ApplyLabelChanges,
        RequestWorktreeCleanup,
        LabelChange,
        WorktreeAction,
    )
    from translator import translate_actions_to_plan


def test_spawn_implementor_produces_rich_spawn_request_with_checklist():
    ctx = AFKContext(
        checklist_versions={"implementor": "implementor-checklist.md"}
    )

    actions = [SpawnImplementor(issue=42, reason="test", checklist_ref="implementor-checklist.md")]
    plan = translate_actions_to_plan(actions, ctx)

    assert len(plan.plan_items) == 1
    req = plan.plan_items[0]
    assert req.__class__.__name__ == "SpawnRequest"
    assert req.issue == 42
    assert req.role == "implementor"
    assert "implementor-checklist.md" in req.prompt or "Checklist" in req.prompt


def test_label_change_action_passes_through():
    ctx = AFKContext()
    actions = [ApplyLabelChanges(issue=7, add=["grok"], remove=["status-in-review"])]
    plan = translate_actions_to_plan(actions, ctx)

    assert len(plan.plan_items) == 1
    item = plan.plan_items[0]
    assert item.__class__.__name__ == "LabelChange"
    assert item.issue == 7
    assert "grok" in item.add


def test_spawn_reviewer_produces_reviewer_request_with_checklist():
    ctx = AFKContext(checklist_versions={"reviewer": "reviewer-checklist.md"})
    actions = [SpawnReviewer(issue=99, reason="review test", checklist_ref="reviewer-checklist.md")]
    plan = translate_actions_to_plan(actions, ctx)

    assert len(plan.plan_items) == 1
    req = plan.plan_items[0]
    assert req.role == "reviewer"
    assert "reviewer-checklist.md" in req.prompt or "Checklist" in req.prompt


def test_worktree_cleanup_action_with_labels_produces_both_worktree_and_label_items():
    """
    Integration for #22: RequestWorktreeCleanup carrying labels (from SM policy)
    must translate to *both* a WorktreeAction (cleanup) *and* a LabelChange.
    This wires the state machine decision through to apply layer.
    """
    ctx = AFKContext()
    action = RequestWorktreeCleanup(
        issue=7,
        reason="Approved — cleanup + grok label",
        add=["grok"],
        remove=["status-in-review"],
    )
    plan = translate_actions_to_plan([action], ctx)

    assert len(plan.plan_items) == 2
    kinds = [item.__class__.__name__ for item in plan.plan_items]
    assert "WorktreeAction" in kinds
    assert "LabelChange" in kinds

    wt = next(i for i in plan.plan_items if isinstance(i, WorktreeAction))
    assert wt.action == "cleanup"
    assert wt.issue == 7

    lc = next(i for i in plan.plan_items if isinstance(i, LabelChange))
    assert "grok" in lc.add
    assert "status-in-review" in lc.remove


# =============================================================================
# TDD for #23: Rich prompt generation in translation layer (vertical slices)
# =============================================================================

def test_spawn_implementor_prompt_with_rich_issue_snapshot_includes_dynamic_history_blockers_retry():
    """TDD tracer bullet (first RED slice for #23).

    Verifies that the public translate_actions_to_plan (and underlying prompt
    builders) produce a SpawnRequest whose .prompt pulls richer context from
    the IssueSnapshot (recent history, blockers, retries, phase, labels, worktree)
    and generates significantly higher-quality, dynamic, high-leverage prompts
    while cleanly embedding the mandatory checklist.

    This test uses a realistic snapshot with retry + blockers (as used in
    state_machine tests) and will drive the implementation of snapshot threading
    + dynamic prompt logic.
    """
    ctx = AFKContext(
        checklist_versions={"implementor": "implementor-checklist.md"}
    )

    snap = IssueSnapshot(
        number=23,
        current_labels=["agent", "status-in-progress", "retry-1"],
        has_open_blockers=True,
        open_blockers=[42, 99],
        worktree_exists=True,
        worktree_path="/tmp/afk-worktrees/issue-23",
        last_subagent_role="implementor",
        last_subagent_outcome="rejected",
        retry_count=1,
        current_afk_phase="in_progress",
    )

    actions = [
        SpawnImplementor(
            issue=23,
            reason="Address reviewer rejection and unblock dependents",
            checklist_ref="implementor-checklist.md",
            snapshot=snap,
        )
    ]

    plan = translate_actions_to_plan(actions, ctx)

    assert len(plan.plan_items) == 1
    req = plan.plan_items[0]
    assert req.__class__.__name__ == "SpawnRequest"
    assert req.issue == 23
    assert req.role == "implementor"

    p = req.prompt

    # === Rich dynamic context from IssueSnapshot (core of #23) ===
    assert "#23" in p
    assert "retry" in p.lower() and ("1" in p or "#1" in p or "retry-1" in p)
    assert "rejected" in p.lower()
    assert any(str(b) in p for b in [42, 99, "#42", "#99"])
    assert "blocker" in p.lower() or "blocked" in p.lower() or "open blockers" in p.lower()
    # Dynamic instruction for retry/history
    assert (
        "previous" in p.lower()
        or "prior" in p.lower()
        or "learn from" in p.lower()
        or "address" in p.lower()
        or "do not repeat" in p.lower()
    )
    # Phase/labels/worktree context surfaced
    assert (
        "in_progress" in p
        or "status-in-progress" in p
        or "retry-1" in p
        or "worktree" in p.lower()
    )

    # === High-quality prompt structure ===
    assert "autonomous AFK implementor" in p or "AFK implementor" in p
    assert "ONLY mission" in p or "complete GitHub issue" in p
    assert "Reason this work" in p or "Address reviewer rejection" in p

    # === Clean checklist embedding (mandatory, clear delimiters per design) ===
    assert "IMPLEMENTOR CHECKLIST (MANDATORY)" in p
    assert "END OF IMPLEMENTOR CHECKLIST" in p
    # Actual checklist content is present (e.g. the progress rule it mandates)
    assert "20-30 minutes" in p or "progress comments" in p

    # Snapshot-driven content is in addition to (not replacing) the checklist
    assert len(p) > 2000  # checklist is long; rich prompt is substantial


def test_spawn_reviewer_prompt_with_rich_snapshot_produces_dynamic_review_context():
    """Additional coverage for #23 rich prompts (reviewer path + snapshot).

    Ensures reviewer prompts also benefit from snapshot context (e.g. implementor
    history) and maintain clean checklist embedding + high-quality structure.
    """
    ctx = AFKContext(checklist_versions={"reviewer": "reviewer-checklist.md"})
    snap = IssueSnapshot(
        number=99,
        current_labels=["agent", "status-in-review"],
        has_open_blockers=False,
        open_blockers=[],
        last_subagent_role="implementor",
        last_subagent_outcome="approved",
        retry_count=0,
        current_afk_phase="in_review",
    )
    action = SpawnReviewer(
        issue=99,
        reason="Post-implementor review",
        checklist_ref="reviewer-checklist.md",
        snapshot=snap,
    )
    plan = translate_actions_to_plan([action], ctx)
    req = plan.plan_items[0]
    p = req.prompt

    assert req.role == "reviewer"
    assert "#99" in p
    assert "in_review" in p or "status-in-review" in p
    assert "REVIEW FOCUS" in p or "implementor attempt" in p.lower()
    assert "REVIEWER CHECKLIST (MANDATORY)" in p
    assert "END OF REVIEWER CHECKLIST" in p
    assert "20-30 minutes" in p or "progress comments" in p or "verdict" in p.lower()


# =============================================================================
# TDD for #35: Reviewer label hygiene reminder in generated prompts
# =============================================================================

def test_reviewer_prompt_footer_includes_label_hygiene_reminder_per_issue_35():
    """TDD (red→green) for #35.

    The reviewer prompt footer generated by translator.py must now include
    a crisp mandatory reminder about removing prior `status-*` labels when
    approving or rejecting. This enforces the "exactly one status-*" invariant
    at the AI prompt layer (primary per grill decision for this issue).

    Pairs with the new checklist item + SKILL.md updates. Existing tests
    continue to pass; this adds coverage for the hygiene language.
    """
    ctx = AFKContext(checklist_versions={"reviewer": "reviewer-checklist.md"})
    action = SpawnReviewer(
        issue=35,
        reason="test label hygiene for status-* removal on reject/approve",
        checklist_ref="reviewer-checklist.md",
    )
    plan = translate_actions_to_plan([action], ctx)
    req = plan.plan_items[0]
    p = req.prompt

    assert req.role == "reviewer"
    assert "#35" in p

    # New hygiene reminder must be present (footer text)
    assert (
        "label hygiene" in p.lower()
        or ("exactly one" in p.lower() and "status" in p.lower())
        or "remove any prior" in p.lower()
        or ("remove" in p.lower() and "status-" in p and "label" in p.lower())
    )

    # Must reference the rejection/approval label actions + consequence
    assert "status-rejected-review" in p or "status-rejected" in p.lower()
    assert "grok" in p  # approval path

    # Checklist still cleanly embedded
    assert "END OF REVIEWER CHECKLIST" in p
    assert "REVIEWER CHECKLIST (MANDATORY)" in p
