"""
Snapshot Builder

Responsible for turning raw data (GitHub issues via gh/MCP, filesystem
worktrees, .grok/afk-session.json, etc.) into rich, pre-digested
`IssueSnapshot` objects and an `AFKContext`.

This module is intentionally separate from the decision logic so that:
- The state machine can be tested with hand-crafted snapshots.
- The data gathering logic can evolve independently.
- We have a clear, testable boundary.
"""

from __future__ import annotations

import subprocess
import json
from pathlib import Path
from typing import Any

from .data_models import IssueSnapshot, AFKContext

# #30: import for is_epic check (agent epics only get sub-issue enrichment)
try:
    from .find_ready_afk_issues import is_epic_issue
except ImportError:
    # direct / test fallback
    from find_ready_afk_issues import is_epic_issue


def build_snapshots_and_context(raw_state: dict | None = None) -> tuple[list[IssueSnapshot], AFKContext]:
    """
    Main entry point for the snapshot builder layer.

    If `raw_state` is not provided, it will attempt to fetch live data
    using the existing `fetch_afk_issues.py` helper where possible.
    """
    context = AFKContext(
        checklist_versions={
            "implementor": "implementor-checklist.md",
            "reviewer": "reviewer-checklist.md",
        }
    )

    if raw_state is None:
        raw_state = _fetch_live_agent_issues()

    snapshots = _convert_to_snapshots(raw_state)

    return snapshots, context


def _fetch_live_agent_issues() -> dict:
    """Attempt to fetch current agent-labeled issues using the existing fetcher.

    Raises on real failures (subprocess error, non-zero exit, bad JSON) so the
    engine layer can record rich structured errors in AFKCycleResult (addresses
    graceful + observable snapshot failures per #26 and reviewer feedback).
    Silent empty only for legitimate "no issues" case after successful fetch.
    """
    try:
        # Use the existing fetch_afk_issues.py which already does the hard work
        result = subprocess.run(
            ["python3", str(Path(__file__).parent / "fetch_afk_issues.py"), "--json"],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode == 0:
            data = json.loads(result.stdout)
            # The fetcher returns {"ready": [...], "blocked": [...]}
            # We combine them for snapshot purposes
            all_issues = data.get("ready", []) + data.get("blocked", [])
            return {"issues": all_issues}
        else:
            raise RuntimeError(f"fetch_afk_issues.py exited {result.returncode}: {result.stderr[:200]}")
    except Exception as e:
        raise RuntimeError(f"_fetch_live_agent_issues failed: {type(e).__name__}: {e}") from e


def _convert_to_snapshots(raw_state: dict) -> list[IssueSnapshot]:
    """Convert raw issue data into rich IssueSnapshot objects."""
    snapshots: list[IssueSnapshot] = []
    existing_worktrees = _discover_worktrees()

    issues = raw_state.get("issues", []) or raw_state.get("ready", []) + raw_state.get("blocked", [])

    for item in issues:
        number = item.get("number")
        if not number:
            continue

        labels = item.get("labels", [])
        if isinstance(labels, list) and labels and isinstance(labels[0], dict):
            labels = [l.get("name", "") for l in labels]

        blocked_by = item.get("blocked_by", []) or []

        worktree_path = existing_worktrees.get(number)

        snapshot = IssueSnapshot(
            number=number,
            current_labels=labels,
            has_open_blockers=len(blocked_by) > 0,
            open_blockers=blocked_by,
            worktree_exists=worktree_path is not None,
            worktree_path=worktree_path,
            last_subagent_role=None,
            last_subagent_outcome=None,
            retry_count=0,
            current_afk_phase=_derive_phase(labels),
        )

        # #30 Epic lifecycle rule (agent Epics only):
        # Enrich with open *direct* sub-issue children from GitHub sub-issue graph.
        # If any open children, force has_open_blockers=True and include their numbers
        # (union with any body blockers). Sub-issue graph is authoritative per spec.
        # Also set is_epic=True so state machine can guard against spawning work on Epics.
        # Best-effort (gh may be unavailable in some test envs; _get returns [] safely).
        if "agent" in (labels or []):
            try:
                if is_epic_issue({"title": item.get("title", ""), "labels": [{"name": l} for l in (labels or [])]}):
                    snapshot.is_epic = True
                    open_children = _get_open_direct_sub_issue_numbers(number)
                    if open_children:
                        snapshot.has_open_blockers = True
                        combined = sorted(set((snapshot.open_blockers or [])) | set(open_children))
                        snapshot.open_blockers = combined
            except Exception:
                # Never break snapshot construction for enrichment failures.
                pass

        snapshots.append(snapshot)

    return snapshots


def _discover_worktrees() -> dict[int, str]:
    """
    Simple worktree discovery.

    Looks for directories matching the convention used by create_afk_worktree.sh:
    ../grok-afk-worktrees/issue-<number> (sibling to the main repo checkout).

    Raises on failure (git rev-parse or fs issues) so engine can record rich
    error details in AFKCycleResult (per #26 resilience + reviewer feedback on
    silent internal builder failures). Empty dict only on clean "no worktrees" .
    """
    worktrees: dict[int, str] = {}

    try:
        # Robustly find the main repo root via git (works regardless of CWD or layout)
        repo_root_str = subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=Path(__file__).parent,
            text=True,
            timeout=5,
        ).strip()
        repo_root = Path(repo_root_str)
        # Convention: sibling directory to the repo root
        base = repo_root.parent / "grok-afk-worktrees"
        if base.exists():
            for entry in base.iterdir():
                if entry.is_dir() and entry.name.startswith("issue-"):
                    try:
                        num = int(entry.name.split("-", 1)[1])
                        worktrees[num] = str(entry.resolve())
                    except ValueError:
                        continue
    except Exception as e:
        raise RuntimeError(f"_discover_worktrees failed: {type(e).__name__}: {e}") from e

    return worktrees


def _derive_phase(labels: list[str]) -> str | None:
    """Derive a simple AFK phase from labels.

    Only status-* labels map to a phase (used by the state machine for
    routing decisions). The `grok` label serves solely as a historical
    "completion signature" marker (added on reviewer approval per SKILL.md);
    its presence no longer derives any phase or acts as a blocker for
    future AFK eligibility on open `agent`-labeled issues.

    This change fixes the incorrect blocking behavior reported in #33.
    """
    label_set = set(labels)
    if "status-in-review" in label_set:
        return "in_review"
    if "status-rejected-review" in label_set:
        return "rejected_review"
    if "status-in-progress" in label_set:
        return "in_progress"
    return None


# =============================================================================
# #30 Epic lifecycle support (direct sub-issue children as blockers for agent Epics)
# =============================================================================

def _get_open_direct_sub_issue_numbers(issue_number: int) -> list[int]:
    """
    Best-effort: return numbers of *open* direct sub-issues (children) of the given
    issue using the gh CLI + GitHub REST sub-issues endpoint.

    Returns [] silently on any failure (no gh in env, auth, network, timeout, parse,
    non-existent, or the issue has no children). This keeps snapshot building
    resilient (#25/#26 patterns).

    The sub-issue graph (not body "Blocked by") is authoritative for the Epic
    lifecycle rule per the grilled spec in #30.
    """
    try:
        # gh api returns JSON array of sub-issue objects (each has "number", "state", etc.)
        # Hardcoded owner/repo is acceptable here: this AFK engine deployment targets
        # czaby/grok exclusively; other code (fetcher etc.) makes similar assumptions.
        cmd = [
            "gh", "api",
            f"repos/czaby/grok/issues/{issue_number}/sub_issues",
        ]
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0 or not result.stdout.strip():
            return []
        subs = json.loads(result.stdout)
        if not isinstance(subs, list):
            return []
        open_nums: list[int] = []
        for s in subs:
            if isinstance(s, dict):
                state = s.get("state", "")
                num = s.get("number")
                if state != "closed" and num is not None:
                    try:
                        open_nums.append(int(num))
                    except (ValueError, TypeError):
                        continue
        return sorted(set(open_nums))
    except Exception:
        # Best effort only — never let sub-issue lookup break the entire snapshot cycle.
        return []