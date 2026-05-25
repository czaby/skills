"""
AFK Engine - High Level Entry Point

This module exposes the primary public interface for the deterministic AFK system.

The main function is `run_afk_cycle`. It is intentionally kept as a thin
coordinator that delegates to the other focused modules.
"""

from __future__ import annotations

from .data_models import AFKCycleResult, AFKContext, SpawnRequest
from .snapshot_builder import build_snapshots_and_context
from .state_machine import decide_next_action
from .translator import translate_actions_to_plan
from .apply import apply_safe_plan


def run_afk_cycle(
    dry_run: bool = False,
    apply_changes: bool = True,
    **kwargs,
) -> AFKCycleResult:
    """
    Primary entry point for the AFK engine.

    This is the function the Very Thin Runner (main orchestrator agent)
    is expected to call.

    High-level flow:
        1. Gather raw state (GitHub + filesystem + session)
        2. Build rich IssueSnapshots + AFKContext (with engine-level retry for transients)
        3. Run the state machine for each relevant issue (per-snapshot isolation)
        4. Translate high-level decisions into a concrete AFKPlan
        5. Apply safe mutations (unless dry_run or apply_changes=False; already best-effort)
        6. Return a rich AFKCycleResult (including SpawnRequests, .errors on any layer failure)

    #26 resilience: NEVER raises on normal layer failures (snapshot builder, SM,
    translator, apply). Always returns AFKCycleResult. Rich structured errors
    (phase, error, type, details, attempt, optional issue) are collected for
    observability. Snapshot builder has 2-attempt recovery for transients.
    Partial progress is supported and valuable.

    Thin runner guidance (see SKILL.md + DESIGN.md): if result.errors:
    - Log/inspect (phase-specific).
    - For transient snapshot errs: safe to retry the cycle soon.
    - On persistent errors with partial spawns/actions: proceed with what you have.
    - Escalate only on repeated total failures.
    The engine owns recovery and best-effort; runner stays thin.

    The function is intentionally kept as a thin coordinator (with explicit
    protection + error collection per #26).
    """
    errors: list[dict] = []

    # 1. Gather raw state (None triggers live fetch via snapshot_builder + fetch_afk_issues.py)
    raw_state: dict | None = None

    # 2. Build rich snapshots + context (with simple retry recovery for transients per #26)
    snapshots: list = []
    context = AFKContext(
        checklist_versions={
            "implementor": "implementor-checklist.md",
            "reviewer": "reviewer-checklist.md",
        }
    )
    for attempt in range(1, 3):
        try:
            snapshots, context = build_snapshots_and_context(raw_state)
            break
        except Exception as e:
            if attempt == 2:
                errors.append({
                    "phase": "snapshot",
                    "error": str(e),
                    "type": type(e).__name__,
                    "details": "build_snapshots_and_context failed (fetch/convert/discover); includes internal paths now surfaced",
                    "attempt": attempt,
                })
            # retry on transient (no sleep for test speed / determinism)
            snapshots, context = [], context

    # 3. Run the state machine for each issue (per-snapshot isolation for resilience)
    actions = []
    for snap in snapshots:
        try:
            action = decide_next_action(snap, context)
            if action.__class__.__name__ != "NoOp":
                actions.append(action)
        except Exception as e:
            errors.append({
                "phase": "state_machine",
                "issue": getattr(snap, "number", None),
                "error": str(e),
                "type": type(e).__name__,
                "details": "decide_next_action failed for this snapshot (isolated)",
                "attempt": 1,
            })

    # 4. Translate high-level actions into a concrete AFKPlan
    plan = None
    try:
        plan = translate_actions_to_plan(actions, context)
    except Exception as e:
        errors.append({
            "phase": "translator",
            "error": str(e),
            "type": type(e).__name__,
            "details": "translate_actions_to_plan failed",
            "attempt": 1,
        })
        plan = None

    # 5. Apply safe mutations (labels, session, worktrees)
    applied = None
    if apply_changes and not dry_run:
        try:
            applied = apply_safe_plan(plan, context, dry_run=dry_run)
        except Exception as e:
            errors.append({
                "phase": "apply",
                "error": str(e),
                "type": type(e).__name__,
                "details": "apply_safe_plan raised (unexpected; layer is best-effort)",
                "attempt": 1,
            })
            applied = []

    # 6. Extract SpawnRequests for the thin runner
    spawn_requests: list[SpawnRequest] = []
    if plan:
        for item in plan.plan_items:
            if isinstance(item, SpawnRequest):
                spawn_requests.append(item)

    notes = [
        f"Cycle complete. High-level actions: {len(actions)}",
        f"Plan items generated: {len(plan.plan_items) if plan else 0}",
    ]
    if errors:
        notes.append(f"errors recorded: {len(errors)} (see .errors for details)")

    return AFKCycleResult(
        spawn_requests=spawn_requests,
        plan=plan,
        applied_changes=applied or [],
        notes=notes,
        no_more_work=(len(actions) == 0 and len(errors) == 0),
        errors=errors,
    )