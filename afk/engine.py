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
        2. Build rich IssueSnapshots + AFKContext
        3. Repeatedly run the state machine + translate + apply (bounded internal passes)
           so that RequestWorktreeCleanup (and similar non-spawn progress actions)
           automatically cause follow-up decisions (e.g. rejection → cleanup →
           SpawnImplementor for retry) inside the *same* run_afk_cycle() call.
        4. Return a rich AFKCycleResult (SpawnRequests from the final stable state,
           all applied side-effects, errors, etc.)

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

    # 3–6. Multi-pass decision + apply loop (the key fix).
    # If RequestWorktreeCleanup is emitted (rejection path, stale worktree, etc.),
    # we apply it and immediately re-evaluate inside the same run_afk_cycle() so
    # the follow-on SpawnImplementor for a retry (or other progress) is produced
    # automatically. The thin runner no longer has to manually "remember" to
    # re-cycle after a cleanup.
    max_internal_passes = 4
    all_actions: list = []
    all_spawn_requests: list[SpawnRequest] = []
    all_applied: list = []

    for _internal_pass in range(max_internal_passes):
        try:
            pass_snapshots, pass_context = build_snapshots_and_context(raw_state)
        except Exception as e:
            errors.append({
                "phase": "snapshot",
                "error": str(e),
                "type": type(e).__name__,
                "details": f"build_snapshots_and_context failed on internal pass {_internal_pass}",
                "attempt": _internal_pass,
            })
            break

        actions_this_pass = []
        for snap in pass_snapshots:
            try:
                action = decide_next_action(snap, pass_context)
                if action.__class__.__name__ != "NoOp":
                    actions_this_pass.append(action)
            except Exception as e:
                errors.append({
                    "phase": "state_machine",
                    "issue": getattr(snap, "number", None),
                    "error": str(e),
                    "type": type(e).__name__,
                    "details": "decide_next_action failed (internal pass)",
                    "attempt": _internal_pass,
                })

        if not actions_this_pass:
            break

        plan = None
        try:
            plan = translate_actions_to_plan(actions_this_pass, pass_context)
        except Exception as e:
            errors.append({
                "phase": "translator",
                "error": str(e),
                "type": type(e).__name__,
                "details": "translate_actions_to_plan failed (internal pass)",
                "attempt": _internal_pass,
            })
            break

        applied_this_pass: list = []
        if apply_changes and not dry_run:
            try:
                applied_this_pass = apply_safe_plan(plan, pass_context, dry_run=dry_run) or []
                all_applied.extend(applied_this_pass)
            except Exception as e:
                errors.append({
                    "phase": "apply",
                    "error": str(e),
                    "type": type(e).__name__,
                    "details": "apply_safe_plan failed (internal pass)",
                    "attempt": _internal_pass,
                })

        if plan:
            for item in plan.plan_items:
                if isinstance(item, SpawnRequest):
                    all_spawn_requests.append(item)

        all_actions.extend(actions_this_pass)

        # Continue while we produced non-spawn progress (especially
        # RequestWorktreeCleanup). The next internal pass will see the
        # post-cleanup snapshot and can emit the retry SpawnImplementor.
        had_non_spawn_progress = any(
            not isinstance(item, SpawnRequest)
            for item in (plan.plan_items if plan else [])
        )
        if not had_non_spawn_progress:
            break

    notes = [
        f"Cycle complete. High-level actions (all passes): {len(all_actions)}",
        f"Internal decision passes: {_internal_pass + 1}",
        f"SpawnRequests produced: {len(all_spawn_requests)}",
    ]
    if errors:
        notes.append(f"errors recorded: {len(errors)} (see .errors for details)")

    return AFKCycleResult(
        spawn_requests=all_spawn_requests,
        plan=None,
        applied_changes=all_applied,
        notes=notes,
        no_more_work=(len(all_actions) == 0 and len(errors) == 0),
        errors=errors,
    )

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