"""
Apply Layer

Responsible for taking a concrete `AFKPlan` and applying the safe,
non-spawn side effects:

- GitHub label mutations (via gh CLI, preferred per SKILL.md conventions)
- Updates to `.grok/afk-session.json` (safe merge + atomic write)
- Worktree creation / cleanup operations (via git + create_afk_worktree.sh)

Design principles (per AFK_ENGINE_DESIGN.md + issue #24):
- Best-effort by default (partial progress preferred over total failure)
- Excellent, structured reporting of successes vs failures per item
- Full support for dry-run / no-op mode (no real mutations)
- Never performs `spawn_subagent` calls (runner responsibility only)
- Good error handling: per-item isolation, never raises on expected failures
- Follows patterns from fetch_afk_issues.py (subprocess gh/git, robust errors)

The returned list items are plain dicts (flexible for AFKCycleResult + observability).
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

try:
    from .data_models import (
        AFKPlan,
        AFKContext,
        LabelChange,
        WorktreeAction,
        SessionUpdate,
    )
except ImportError:
    # Allow direct execution / test fallback (PYTHONPATH or flat)
    from data_models import (
        AFKPlan,
        AFKContext,
        LabelChange,
        WorktreeAction,
        SessionUpdate,
    )


def _find_repo_root() -> Path:
    """
    Compute the repository root from this module's location in the
    canonical layout: repo/.grok/skills/afk/apply.py

    Uses pure Path arithmetic (reliable, no extra deps, works in slim Docker
    test images without git). In real orchestrator runs the layout is identical.
    """
    # parents[0]=afk, [1]=skills, [2]=.grok, [3]=repo root
    return Path(__file__).resolve().parents[3]


def _get_worktree_base(repo_root: Path) -> Path:
    """Sibling worktree base per documented convention (and create_afk_worktree.sh)."""
    return repo_root.parent / "grok-afk-worktrees"


def _run_cmd(cmd: list[str], timeout: int = 60) -> dict[str, Any]:
    """
    Run a shell command (gh, git, bash script) and return structured result.
    Never raises for the caller; used for best-effort application.
    """
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return {
            "success": result.returncode == 0,
            "returncode": result.returncode,
            "stdout": result.stdout.strip(),
            "stderr": result.stderr.strip(),
            "cmd": " ".join(cmd),
        }
    except subprocess.TimeoutExpired as e:
        return {
            "success": False,
            "returncode": -1,
            "stdout": "",
            "stderr": f"Command timed out after {timeout}s: {' '.join(cmd)}",
            "cmd": " ".join(cmd),
            "exception": str(e),
        }
    except Exception as e:
        return {
            "success": False,
            "returncode": -1,
            "stdout": "",
            "stderr": str(e),
            "cmd": " ".join(cmd),
            "exception": str(type(e)),
        }


def _apply_label_change(
    change: LabelChange, dry_run: bool, repo_root: Path
) -> dict[str, Any]:
    """Apply (or simulate) a single LabelChange via gh CLI."""
    issue = change.issue
    add = change.add or []
    remove = change.remove or []

    if not add and not remove:
        return {
            "type": "label_change",
            "issue": issue,
            "success": True,
            "dry_run": dry_run,
            "details": "No label changes requested (noop)",
            "error": None,
        }

    add_str = ",".join(add) if add else ""
    remove_str = ",".join(remove) if remove else ""

    cmd = ["gh", "issue", "edit", str(issue)]
    if add_str:
        cmd += ["--add-label", add_str]
    if remove_str:
        cmd += ["--remove-label", remove_str]

    if dry_run:
        return {
            "type": "label_change",
            "issue": issue,
            "success": True,
            "dry_run": True,
            "details": f"DRY-RUN: would run: {' '.join(cmd)} (add={add}, remove={remove})",
            "error": None,
            "command": " ".join(cmd),
        }

    run_res = _run_cmd(cmd)
    success = run_res["success"]
    details = (
        f"gh label edit for #{issue}: add={add} remove={remove}. "
        f"rc={run_res['returncode']}. stdout={run_res['stdout'][:200]}"
    )
    if not success:
        details += f" stderr={run_res['stderr'][:200]}"

    return {
        "type": "label_change",
        "issue": issue,
        "success": success,
        "dry_run": False,
        "details": details,
        "error": None if success else run_res["stderr"] or run_res.get("exception"),
        "command": run_res.get("cmd"),
    }


def _apply_worktree_action(
    action: WorktreeAction, dry_run: bool, repo_root: Path
) -> dict[str, Any]:
    """Apply (or simulate) worktree create or cleanup using git + helper script."""
    issue = action.issue
    wt_action = action.action  # "create" | "cleanup"
    reason = action.reason or ""
    wt_base = _get_worktree_base(repo_root)
    wt_path = wt_base / f"issue-{issue}"
    branch = f"afk/{issue}"

    if dry_run:
        return {
            "type": "worktree",
            "issue": issue,
            "success": True,
            "dry_run": True,
            "details": f"DRY-RUN: would perform WorktreeAction {wt_action} for #{issue} (path={wt_path}, branch={branch}). Reason: {reason}",
            "error": None,
            "action": wt_action,
        }

    if wt_action == "cleanup":
        # Best-effort cleanup. Use --force to be resilient to partial states.
        cmds = [
            ["git", "-C", str(repo_root), "worktree", "remove", "--force", str(wt_path)],
            ["git", "-C", str(repo_root), "branch", "-D", branch],
        ]
        all_success = True
        details_parts = []
        last_err = None
        for c in cmds:
            r = _run_cmd(c)
            details_parts.append(f"{r['cmd']}: rc={r['returncode']}")
            if not r["success"]:
                all_success = False
                last_err = r["stderr"] or r.get("exception")
        details = "; ".join(details_parts) + f" | reason={reason}"
        return {
            "type": "worktree",
            "issue": issue,
            "success": all_success,
            "dry_run": False,
            "details": details,
            "error": last_err,
            "action": "cleanup",
            "path": str(wt_path),
        }

    elif wt_action == "create":
        # Delegate to the canonical helper (which does validation + git worktree add)
        script = repo_root / ".grok/skills/afk/create_afk_worktree.sh"
        cmd = ["bash", str(script), str(issue)]
        r = _run_cmd(cmd, timeout=120)
        success = r["success"]
        details = f"create script for #{issue}: rc={r['returncode']}. output={r['stdout'][:300]}"
        if not success:
            details += f" err={r['stderr'][:200]}"
        return {
            "type": "worktree",
            "issue": issue,
            "success": success,
            "dry_run": False,
            "details": details,
            "error": None if success else (r["stderr"] or r.get("exception")),
            "action": "create",
            "output": r["stdout"],
        }

    else:
        return {
            "type": "worktree",
            "issue": issue,
            "success": False,
            "dry_run": False,
            "details": f"Unknown worktree action: {wt_action}",
            "error": f"Unknown action {wt_action}",
            "action": wt_action,
        }


def _merge_updates(base: dict[str, Any], updates: dict[str, Any]) -> dict[str, Any]:
    """Recursive dict merge (handles nested 'running' etc. safely)."""
    result = dict(base)  # shallow copy of top
    for k, v in updates.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = _merge_updates(result[k], v)
        else:
            result[k] = v
    return result


def _apply_session_update(
    upd: SessionUpdate, dry_run: bool, session_path: Path
) -> dict[str, Any]:
    """Safely merge updates into the AFK session JSON (atomic write on real path)."""
    updates = upd.updates or {}

    if dry_run:
        return {
            "type": "session",
            "success": True,
            "dry_run": True,
            "details": f"DRY-RUN: would merge into {session_path}: {updates}",
            "error": None,
            "updates": updates,
        }

    try:
        current: dict[str, Any] = {}
        if session_path.exists():
            try:
                current = json.loads(session_path.read_text(encoding="utf-8"))
            except Exception:
                current = {}  # corrupt -> start fresh, best effort

        merged = _merge_updates(current, updates)

        # Atomic write: write tmp then rename (works across filesystems in practice for small files)
        tmp_path = session_path.with_name(session_path.name + ".tmp")
        tmp_path.write_text(json.dumps(merged, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp_path.replace(session_path)

        return {
            "type": "session",
            "success": True,
            "dry_run": False,
            "details": f"Session updated at {session_path} (keys: {list(updates.keys())})",
            "error": None,
            "path": str(session_path),
        }
    except Exception as e:
        return {
            "type": "session",
            "success": False,
            "dry_run": False,
            "details": f"Session update failed for {session_path}: {e}",
            "error": str(e),
            "updates_attempted": updates,
        }


def apply_safe_plan(
    plan: AFKPlan | None,
    context: AFKContext,
    dry_run: bool = False,
) -> list[dict[str, Any]]:
    """
    Apply the safe (non-spawn) portions of an AFKPlan.

    Best-effort: processes every item, records individual outcomes, continues
    on errors. Supports dry_run fully (no real mutations, descriptive reports).

    Returns list of per-item result dicts for AFKCycleResult.applied_changes.
    """
    if plan is None or not getattr(plan, "plan_items", None):
        return []

    results: list[dict[str, Any]] = []

    try:
        repo_root = _find_repo_root()
    except Exception as e:
        return [
            {
                "type": "error",
                "success": False,
                "dry_run": dry_run,
                "details": f"Failed to locate repo root: {e}",
                "error": str(e),
            }
        ]

    session_path = repo_root / ".grok" / "afk-session.json"

    for item in plan.plan_items:
        try:
            if isinstance(item, LabelChange):
                r = _apply_label_change(item, dry_run, repo_root)
                results.append(r)
            elif isinstance(item, WorktreeAction):
                r = _apply_worktree_action(item, dry_run, repo_root)
                results.append(r)
            elif isinstance(item, SessionUpdate):
                r = _apply_session_update(item, dry_run, session_path)
                results.append(r)
            else:
                # SpawnRequest or future items: explicitly ignored here (runner duty)
                results.append(
                    {
                        "type": "ignored_spawn_or_other",
                        "success": True,
                        "dry_run": dry_run,
                        "details": f"Ignored non-safe item of type {type(item).__name__} (spawns are runner responsibility)",
                        "error": None,
                    }
                )
        except Exception as ex:
            # Per-item isolation: never let one failure abort the rest
            results.append(
                {
                    "type": "error",
                    "issue": getattr(item, "issue", None),
                    "success": False,
                    "dry_run": dry_run,
                    "details": f"Unexpected exception applying {type(item).__name__}: {ex}",
                    "error": str(ex),
                }
            )

    # #30 Epic lifecycle: immediate post-child-AFK-completion sibling check + auto-close hook.
    # Triggered inside Apply layer (for LabelChanges that add "grok", i.e. AFK-driven
    # completion of a child). Only direct children; only acts on agent Epics; leaves agent label;
    # adds grok + closes parent if it was the last open child. Best-effort, dry_run supported,
    # rich per-event reporting in applied_changes. Matches grilled spec exactly (reactive,
    # no periodic scan, only AFK closes, same cycle).
    try:
        _check_and_auto_close_parent_epics_for_grok_completions(plan, dry_run, repo_root, results)
    except Exception as ex:
        results.append({
            "type": "epic_lifecycle_hook_error",
            "success": False,
            "dry_run": dry_run,
            "details": f"Unexpected error in Epic auto-close hook: {ex}",
            "error": str(ex),
        })

    return results


# =============================================================================
# #36: One-time stale status-* label hygiene (remove only)
# Per authoritative grill findings (2026-05-25) + issue design:
# - Called exactly once by thin runner (e.g. cli.py) at /afk startup,
#   AFTER session load + live subagent discovery, BEFORE first run_afk_cycle().
# - ONLY removes qualifying stale status-* labels on agent issues.
# - Inputs: explicit session dict (for "running" section) + set of live active issue nums.
# - Dual detection: not in running issues AND not in live active set.
# - Narrow scope ONLY: gh label removes (best-effort via existing patterns), dry_run,
#   rich per-issue result dicts. NO session writes, NO GH comments, NO other side effects.
# - Thin runner owns all recording/observability using the returned results.
# - Engine, state machine, snapshot builder, translator untouched.
# - Reuses _run_cmd, _find_repo_root, gh edit patterns from apply layer.
# =============================================================================

def remove_stale_status_labels_once(
    *,
    session: dict[str, Any] | None = None,
    active_subagent_issues: set[int] | None = None,
    dry_run: bool = False,
    repo_root: Path | None = None,
) -> list[dict[str, Any]]:
    """
    One-time startup hygiene pass for stale status-* labels on `agent` issues.

    An issue qualifies for cleanup IFF:
      - It is open and carries the `agent` label
      - It carries at least one `status-*` label
      - Its number is absent from BOTH the session "running" section (issue nums)
        AND the explicit live `active_subagent_issues` set passed by the thin runner.

    The function's **sole responsibility** is performing the label removals
    (best-effort, using the same gh CLI patterns as _apply_label_change).
    It returns a list of rich per-item result dicts so the caller (thin runner)
    can perform session events, optional comments, logging, etc.

    Supports full dry_run (descriptive reports, zero mutations).
    Idempotent and safe when nothing to do.

    This implements exactly the design agreed in the #36 grill session.
    """
    session = session or {}
    active: set[int] = set(active_subagent_issues or [])

    if repo_root is None:
        try:
            repo_root = _find_repo_root()
        except Exception as e:
            return [
                {
                    "type": "error",
                    "success": False,
                    "dry_run": dry_run,
                    "details": f"Failed to locate repo root for hygiene: {e}",
                    "error": str(e),
                }
            ]

    # Extract issue numbers from session "running" (previous/archived workers)
    running_section = session.get("running", {}) or {}
    running_issues: set[int] = set()
    for val in running_section.values():
        if isinstance(val, dict):
            iss = val.get("issue")
            if isinstance(iss, (int, str)) and str(iss).isdigit():
                running_issues.add(int(iss))

    # Discover candidates (open agent issues bearing >=1 status-* label)
    candidates = _find_agent_issues_with_status_labels(repo_root)

    results: list[dict[str, Any]] = []
    for cand in candidates:
        num = cand["number"]
        status_labels: list[str] = cand.get("status_labels", [])
        if not status_labels:
            continue

        is_active = (num in running_issues) or (num in active)

        if is_active:
            results.append(
                {
                    "type": "stale_status_cleanup",
                    "issue": num,
                    "success": True,
                    "dry_run": dry_run,
                    "details": (
                        f"Skipped (active worker recorded): issue #{num} present in session "
                        f"running or live subagent set. Preserving labels: {status_labels}"
                    ),
                    "error": None,
                    "labels_removed": [],
                    "status": "skipped_active",
                }
            )
            continue

        # Qualifies for removal: only status-* (never touch agent, grok, retry-*, etc.)
        remove_str = ",".join(status_labels)
        cmd: list[str] = ["gh", "issue", "edit", str(num), "--remove-label", remove_str]

        if dry_run:
            results.append(
                {
                    "type": "stale_status_cleanup",
                    "issue": num,
                    "success": True,
                    "dry_run": True,
                    "details": f"DRY-RUN: would run: {' '.join(cmd)} (remove={status_labels} from agent #{num})",
                    "error": None,
                    "labels_removed": status_labels,
                    "command": " ".join(cmd),
                    "status": "would_clean",
                }
            )
            continue

        # Real best-effort removal (follows _apply_label_change + _run_cmd exactly)
        run_res = _run_cmd(cmd)
        success = run_res["success"]
        details = (
            f"gh label edit (stale hygiene) for agent #{num}: remove={status_labels}. "
            f"rc={run_res['returncode']}. stdout={run_res['stdout'][:200]}"
        )
        if not success:
            details += f" stderr={run_res['stderr'][:200]}"

        results.append(
            {
                "type": "stale_status_cleanup",
                "issue": num,
                "success": success,
                "dry_run": False,
                "details": details,
                "error": None if success else (run_res.get("stderr") or run_res.get("exception")),
                "labels_removed": status_labels if success else [],
                "command": run_res.get("cmd"),
                "status": "cleaned" if success else "error",
            }
        )

    return results


def _find_agent_issues_with_status_labels(repo_root: Path) -> list[dict[str, Any]]:
    """
    Best-effort discovery of open issues carrying BOTH `agent` and >=1 `status-*` label.
    Uses the same gh + _run_cmd patterns as the rest of the apply layer and fetcher.
    Returns list of dicts with 'number' and 'status_labels' (only the status ones).
    On any failure (no gh, auth, network, parse) returns [] silently (best effort).
    """
    fields = "number,title,labels,state"
    cmd = [
        "gh",
        "issue",
        "list",
        "--label",
        "agent",
        "--state",
        "open",
        "--json",
        fields,
        "--limit",
        "100",
    ]
    run_res = _run_cmd(cmd, timeout=60)
    if not run_res.get("success"):
        return []

    stdout = run_res.get("stdout", "")
    if not stdout:
        return []

    try:
        data = json.loads(stdout)
    except Exception:
        return []

    if not isinstance(data, list):
        data = []

    candidates: list[dict[str, Any]] = []
    for item in data:
        try:
            num = item.get("number")
            if num is None:
                continue
            num = int(num)

            raw_labels = item.get("labels", []) or []
            # Normalize: gh --json sometimes yields list[str], sometimes list[dict{name}]
            if raw_labels and isinstance(raw_labels[0], dict):
                labels = [str(l.get("name", "")) for l in raw_labels if isinstance(l, dict)]
            else:
                labels = [str(l) for l in raw_labels if isinstance(l, (str, int))]

            status_labels = [l for l in labels if l.startswith("status-")]
            if status_labels and "agent" in labels:
                candidates.append(
                    {
                        "number": num,
                        "status_labels": status_labels,
                        "labels": labels,
                    }
                )
        except Exception:
            continue

    return candidates


# =============================================================================
# #30: Epic lifecycle auto-close hook (Apply layer, post child grok completion)
# =============================================================================

def _check_and_auto_close_parent_epics_for_grok_completions(
    plan: AFKPlan | None,
    dry_run: bool,
    repo_root: Path,
    results: list[dict[str, Any]],
) -> None:
    """
    #30 Epic lifecycle sibling check + conditional auto-close.

    Called from apply_safe_plan after processing plan items.
    For every LabelChange in the plan that adds the "grok" label (signaling AFK-driven
    completion/approval of that child issue), we:
    - Query the child's parent via GitHub API (parent_issue_url populated for sub-issues).
    - If the parent currently carries the `agent` label:
      - Query its direct sub-issues.
      - If zero *open* children remain (this was the last):
        - gh edit the parent: --state closed --add-label grok (agent left untouched).
        - Append rich "epic_auto_close" result dict (success, dry_run, child, details, cmd, error).
    - Best-effort, isolated, full dry_run support, no exceptions propagated.
    - Only AFK completions (those going through plan/apply) trigger it.
    - Direct children only; no proactive scan of all Epics.

    This implements the "immediate post-child-close ... inside the Apply layer ... same run_afk_cycle"
    requirement from the authoritative grilled spec exactly.
    """
    if plan is None or not getattr(plan, "plan_items", None):
        return

    for item in plan.plan_items:
        if not isinstance(item, LabelChange):
            continue
        adds = item.add or []
        if "grok" not in adds:
            continue

        child_num = item.issue
        try:
            # 1. Fetch child to discover parent (sub-issue relationship)
            child_api = ["gh", "api", f"repos/czaby/grok/issues/{child_num}"]
            child_res = _run_cmd(child_api, timeout=30)
            if not child_res.get("success"):
                continue
            try:
                child_data = json.loads(child_res.get("stdout", "{}") or "{}")
            except Exception:
                continue

            parent_url = child_data.get("parent_issue_url") or ""
            # Some payloads may nest differently; fall back gracefully
            if not parent_url and isinstance(child_data.get("parent"), dict):
                parent_url = child_data["parent"].get("url", "") or child_data["parent"].get("html_url", "")

            if not parent_url or "/issues/" not in str(parent_url):
                continue
            try:
                parent_num = int(str(parent_url).rstrip("/").split("/")[-1])
            except Exception:
                continue

            # 2. Does parent have agent label right now?
            parent_api = ["gh", "api", f"repos/czaby/grok/issues/{parent_num}", "--jq", ".labels | map(.name)"]
            parent_res = _run_cmd(parent_api, timeout=30)
            if not parent_res.get("success"):
                continue
            try:
                p_labels = json.loads(parent_res.get("stdout", "[]") or "[]")
            except Exception:
                p_labels = []
            if "agent" not in [str(l) for l in p_labels]:
                continue

            # 3. Query direct subs of parent; count open ones (current GH state)
            subs_api = ["gh", "api", f"repos/czaby/grok/issues/{parent_num}/sub_issues"]
            subs_res = _run_cmd(subs_api, timeout=30)
            if not subs_res.get("success"):
                continue
            try:
                sublist = json.loads(subs_res.get("stdout", "[]") or "[]")
            except Exception:
                sublist = []
            open_children = [
                s.get("number") for s in sublist
                if isinstance(s, dict) and s.get("state") != "closed"
            ]
            if len(open_children) != 0:
                # Not the last child (or race); do not close
                continue

            # 4. Last open child for this agent Epic -> auto close it (add grok, close, leave agent)
            close_cmd = [
                "gh", "issue", "edit", str(parent_num),
                "--state", "closed",
                "--add-label", "grok",
            ]
            if dry_run:
                results.append({
                    "type": "epic_auto_close",
                    "issue": parent_num,
                    "success": True,
                    "dry_run": True,
                    "details": f"DRY-RUN: would close agent Epic #{parent_num} (last direct child #{child_num} completed via grok in this cycle's plan)",
                    "child": child_num,
                    "command": " ".join(close_cmd),
                    "labels_added": ["grok"],
                })
                continue

            close_res = _run_cmd(close_cmd, timeout=60)
            success = close_res.get("success", False)
            details = (
                f"Auto-closed agent Epic #{parent_num} (last child #{child_num} AFK-completed). "
                f"rc={close_res.get('returncode')}. stdout={ (close_res.get('stdout') or '')[:150] }"
            )
            if not success:
                details += f" stderr={(close_res.get('stderr') or '')[:150]}"
            results.append({
                "type": "epic_auto_close",
                "issue": parent_num,
                "success": success,
                "dry_run": False,
                "details": details,
                "error": None if success else (close_res.get("stderr") or close_res.get("exception")),
                "child": child_num,
                "command": close_res.get("cmd") or " ".join(close_cmd),
                "labels_added": ["grok"] if success else [],
            })
        except Exception as ex:
            results.append({
                "type": "epic_auto_close",
                "issue": None,
                "success": False,
                "dry_run": dry_run,
                "details": f"Hook error while checking parent for child #{child_num}: {ex}",
                "error": str(ex),
                "child": child_num,
            })
