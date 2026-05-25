"""
Translation Layer

Converts high-level declarative `Action`s (produced by the state machine)
into a concrete `AFKPlan` containing `LabelChange`, `SpawnRequest`,
`WorktreeAction`, etc.

Key responsibilities:
- Generating rich, self-contained `SpawnRequest` objects (full prompts)
- Injecting the correct checklist references (implementor / reviewer)
- Producing concrete label changes and worktree actions
- Keeping prompt generation deterministic and testable
"""

from __future__ import annotations

try:
    from .data_models import (
        Action,
        AFKPlan,
        AFKContext,
        SpawnImplementor,
        SpawnReviewer,
        ApplyLabelChanges,
        RequestWorktreeCleanup,
        EscalateToHuman,
        NoOp,
        SpawnRequest,
        LabelChange,
        WorktreeAction,
        SessionUpdate,
    )
except ImportError:
    # Allow running tests / direct execution with PYTHONPATH pointing to afk/ dir
    from data_models import (
        Action,
        AFKPlan,
        AFKContext,
        SpawnImplementor,
        SpawnReviewer,
        ApplyLabelChanges,
        RequestWorktreeCleanup,
        EscalateToHuman,
        NoOp,
        SpawnRequest,
        LabelChange,
        WorktreeAction,
        SessionUpdate,
    )


def translate_actions_to_plan(
    actions: list[Action],
    context: AFKContext,
) -> AFKPlan:
    """
    Main entry point for the translation layer.

    Takes a list of high-level actions (from `decide_next_action`) and
    produces a fully materialized `AFKPlan`.
    """
    plan_items = []

    for action in actions:
        items = _translate_single_action(action, context)
        plan_items.extend(items)

    return AFKPlan(plan_items=plan_items)


def _translate_single_action(action: Action, context: AFKContext) -> list:
    """Dispatch to the appropriate handler for each Action type."""
    if isinstance(action, SpawnImplementor):
        return _handle_spawn_implementor(action, context)
    elif isinstance(action, SpawnReviewer):
        return _handle_spawn_reviewer(action, context)
    elif isinstance(action, ApplyLabelChanges):
        return _handle_apply_label_changes(action, context)
    elif isinstance(action, RequestWorktreeCleanup):
        return _handle_worktree_cleanup(action, context)
    elif isinstance(action, EscalateToHuman):
        # Escalation is mostly a label + human notification action for now
        return _handle_escalate_to_human(action, context)
    elif isinstance(action, NoOp):
        return []
    else:
        # Unknown action — log it but don't crash the plan
        return []


# =============================================================================
# Individual Action Handlers
# =============================================================================

def _handle_spawn_implementor(action: SpawnImplementor, context: AFKContext) -> list:
    """Turn a SpawnImplementor decision into a rich SpawnRequest."""
    prompt = _build_implementor_prompt(action, context, getattr(action, "snapshot", None))

    spawn_req = SpawnRequest(
        issue=action.issue,
        role="implementor",
        worktree=f"/tmp/afk-worktrees/issue-{action.issue}",  # placeholder (runner will materialize)
        branch=f"afk/{action.issue}",
        prompt=prompt,
        reason=action.reason,
    )

    return [spawn_req]


def _handle_spawn_reviewer(action: SpawnReviewer, context: AFKContext) -> list:
    """Turn a SpawnReviewer decision into a rich SpawnRequest."""
    prompt = _build_reviewer_prompt(action, context, getattr(action, "snapshot", None))

    spawn_req = SpawnRequest(
        issue=action.issue,
        role="reviewer",
        worktree=f"/tmp/afk-worktrees/issue-{action.issue}",
        branch=f"afk/{action.issue}",
        prompt=prompt,
        reason=action.reason,
    )

    return [spawn_req]


def _handle_apply_label_changes(action: ApplyLabelChanges, context: AFKContext) -> list:
    return [LabelChange(issue=action.issue, add=action.add, remove=action.remove)]


def _handle_worktree_cleanup(action: RequestWorktreeCleanup, context: AFKContext) -> list:
    """Translate RequestWorktreeCleanup (from SM lifecycle policy) to concrete items.

    If the Request carries label changes (for approval/retry/escalation), include
    a LabelChange too. This integrates the state machine's worktree decisions.
    """
    items = [WorktreeAction(issue=action.issue, action="cleanup", reason=action.reason)]
    if action.add or action.remove:
        items.append(LabelChange(issue=action.issue, add=action.add, remove=action.remove))
    return items


def _handle_escalate_to_human(action: EscalateToHuman, context: AFKContext) -> list:
    # For now we just record the escalation as a label change + note.
    # The actual human notification can be handled by the runner or apply layer.
    return [
        LabelChange(
            issue=action.issue,
            add=["human"],
            remove=["agent", "status-in-progress", "status-in-review"],
        )
    ]


# =============================================================================
# Prompt Construction (owned by the engine)
# =============================================================================

import os

def _read_checklist(checklist_ref: str) -> str:
    """Read checklist content from disk. Falls back to a note if not found."""
    base_dir = os.path.dirname(__file__)
    path = os.path.join(base_dir, checklist_ref) if not os.path.isabs(checklist_ref) else checklist_ref

    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return f"[Checklist file not found at {checklist_ref}. Please ensure it exists.]"


def _build_implementor_prompt(
    action: SpawnImplementor, context: AFKContext, snapshot: IssueSnapshot | None = None
) -> str:
    """
    Construct a rich, dynamic, high-quality prompt for an AFK implementor.

    This is the core of #23: pulls extensive context from IssueSnapshot
    (history, blockers, retries, phase, etc.) to make prompts significantly
    more effective. Checklist is cleanly embedded with clear delimiters.
    """
    checklist_content = _read_checklist(
        action.checklist_ref or "implementor-checklist.md"
    )

    snapshot_section = ""
    dynamic_guidance = ""
    if snapshot:
        blockers_list = snapshot.open_blockers or []
        blockers_str = ", ".join(f"#{b}" for b in blockers_list) if blockers_list else "none"
        last_activity = (
            f"{snapshot.last_subagent_role} (outcome: {snapshot.last_subagent_outcome})"
            if snapshot.last_subagent_role
            else "N/A"
        )
        wt_status = (
            f"exists at {snapshot.worktree_path}"
            if snapshot.worktree_exists
            else "fresh (will be provisioned)"
        )
        snapshot_section = f"""
## Rich Issue Snapshot (for high-leverage context)
- Issue: #{snapshot.number}
- Current phase: {snapshot.current_afk_phase or "initial/ready"}
- Labels: {", ".join(snapshot.current_labels or []) or "[]"}
- Retry count: {snapshot.retry_count}
- Open blockers: {blockers_str}
- Last subagent: {last_activity}
- Worktree: {wt_status}
"""

        if snapshot.retry_count > 0:
            dynamic_guidance += f"""
**RETRY ATTEMPT #{snapshot.retry_count}**: Previous {snapshot.last_subagent_role} attempt ended in "{snapshot.last_subagent_outcome}". Carefully review all GitHub comments/feedback from prior runs. Do NOT repeat the same mistakes. Address the exact issues that caused rejection.
"""
        if snapshot.has_open_blockers:
            dynamic_guidance += f"""
**OPEN BLOCKERS**: {blockers_str}. You must make meaningful progress or explicitly document (in comments or a note) how you are handling the dependencies. Do not ignore them.
"""

    header = (
        f"You are an autonomous AFK implementor.\n\n"
        f"Your ONLY mission is to fully and correctly complete GitHub issue #{action.issue}.\n\n"
        f"Reason/context for this work: {action.reason}\n\n"
        f"{snapshot_section}"
        f"{dynamic_guidance}"
        "You MUST read and follow the mandatory AFK Implementor Checklist at the VERY START of your session. It is the authoritative source of process rules.\n\n"
        "=== IMPLEMENTOR CHECKLIST (MANDATORY) ===\n\n"
    )

    footer = (
        "\n\n=== END OF IMPLEMENTOR CHECKLIST ===\n\n"
        "Create a plan (use todo_write for any multi-step work with 3+ actions). Work exclusively inside the provided worktree/branch for this issue. Follow Docker-first policy for all tools and tests. Post meaningful progress comments on the GitHub issue at least every 20-30 minutes of real work. Research by reading actual source code first (per AGENTS.md). When acceptance criteria are met, set the correct status label and exit cleanly.\n"
        "Produce excellent, tested, documented work."
    )

    return header + checklist_content + footer


def _build_reviewer_prompt(
    action: SpawnReviewer, context: AFKContext, snapshot: IssueSnapshot | None = None
) -> str:
    """Construct a rich, dynamic, high-quality prompt for an AFK reviewer."""
    checklist_content = _read_checklist(
        action.checklist_ref or "reviewer-checklist.md"
    )

    snapshot_section = ""
    dynamic_guidance = ""
    if snapshot:
        blockers_str = ", ".join(f"#{b}" for b in (snapshot.open_blockers or [])) or "none"
        last_activity = (
            f"{snapshot.last_subagent_role} (outcome: {snapshot.last_subagent_outcome})"
            if snapshot.last_subagent_role
            else "N/A"
        )
        snapshot_section = f"""
## Rich Issue Snapshot (review context)
- Issue: #{snapshot.number}
- Phase: {snapshot.current_afk_phase or "in_review"}
- Labels: {", ".join(snapshot.current_labels or []) or "[]"}
- Retry count: {snapshot.retry_count}
- Open blockers: {blockers_str}
- Last subagent: {last_activity}
"""

        if snapshot.last_subagent_role == "implementor":
            dynamic_guidance += """
**REVIEW FOCUS**: The preceding implementor attempt just completed (or transitioned). Thoroughly validate that all stated goals/reasons were addressed and that no regressions were introduced. Run relevant tests yourself.
"""
        if snapshot.retry_count > 0:
            dynamic_guidance += f"""
**RETRY CONTEXT**: This is overall retry #{snapshot.retry_count}. Pay extra attention to whether previous rejection reasons have been fully resolved.
"""

    header = (
        f"You are an autonomous AFK reviewer with fresh perspective.\n\n"
        f"Your job is to independently and rigorously review the work on GitHub issue #{action.issue}.\n\n"
        f"Reason this review was requested: {action.reason}\n\n"
        f"{snapshot_section}"
        f"{dynamic_guidance}"
        "You MUST read and follow the mandatory AFK Reviewer Checklist below. You are required to exercise the code/tests yourself where relevant.\n\n"
        "=== REVIEWER CHECKLIST (MANDATORY) ===\n\n"
    )

    footer = (
        "\n\n=== END OF REVIEWER CHECKLIST ===\n\n"
        "Produce a clear, independent verdict with specific evidence. "
        "**CRITICAL label hygiene (per #35)**: If approving, remove *all* `status-*` labels and add `grok`. If rejecting, set `status-rejected-review` + the next `retry-N` **while removing any previous `status-*` labels in the *same* edit operation** (e.g. `gh issue edit --add-label status-rejected-review,retry-1 --remove-label status-in-review,status-in-progress` or MCP equivalent). Leave *exactly one* `status-*` label. The state machine escalates immediately on >1 (see SKILL.md). Document the exact label commands you ran in your review comment."
    )

    return header + checklist_content + footer
