#!/usr/bin/env python3
"""
AFK Ready Issues Fetcher (gh CLI version)

Primary entry point for the /afk skill orchestrator when using the native
GitHub CLI instead of (or alongside) the GitHub MCP tools.

It:
1. Uses `gh` to fetch all open issues carrying the target label (default: agent).
2. Parses "Blocked by #NNN" references from their bodies.
3. Resolves the state of each referenced blocker via `gh issue view`.
4. Feeds the data into the pure classification logic in find_ready_afk_issues.py.
5. Returns ready vs. blocked issues (JSON or human-readable).

This keeps the orchestrator simple:
    python .grok/skills/afk/fetch_afk_issues.py --json

The script deliberately uses only `gh` + local Python so the long-running
AFK loop does not need repeated MCP schema discovery calls.

Usage examples:
    # Human summary (default)
    python .grok/skills/afk/fetch_afk_issues.py

    # Machine-readable for the agent
    python .grok/skills/afk/fetch_afk_issues.py --json

    # Custom label
    python .grok/skills/afk/fetch_afk_issues.py --label "ready-for-agent"

    # Limit output
    python .grok/skills/afk/fetch_afk_issues.py --limit 20 --json
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Set

# Ensure we can import the sibling pure-logic module
SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))

from find_ready_afk_issues import (
    find_ready_afk_issues,
    parse_blockers,
    is_epic_issue,
)

# Simple per-run cache for get_issue_state (perf for frequent AFK cycles / repeated blocker refs).
# Addresses caching/performance AC for snapshot builder (issue #25).
_issue_state_cache: Dict[int, str] = {}


def run_gh(args: List[str], check: bool = True) -> Any:
    """Run a gh command and return parsed JSON or raw text.
    Hardened error handling + logging for production (issue #25).
    """
    cmd = ["gh"] + args
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=60,
        )
    except subprocess.TimeoutExpired as e:
        print(f"gh command timed out: {' '.join(cmd)}", file=sys.stderr)
        if check:
            sys.exit(1)
        raise
    except Exception as e:
        print(f"gh command error: {' '.join(cmd)}: {e}", file=sys.stderr)
        if check:
            sys.exit(1)
        raise

    if check and result.returncode != 0:
        print(f"gh command failed: {' '.join(cmd)}", file=sys.stderr)
        print(result.stderr, file=sys.stderr)
        sys.exit(1)
    if args[0] == "issue" and ("list" in args or "view" in args):
        # Most of our calls request --json
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError:
            return result.stdout.strip()
    return result.stdout.strip()


def fetch_open_issues(label: str, limit: int) -> List[Dict[str, Any]]:
    """Fetch open issues with the given label using gh."""
    fields = "number,title,body,labels,state,assignees,createdAt,updatedAt"
    cmd = [
        "issue", "list",
        "--label", label,
        "--state", "open",
        "--json", fields,
        "--limit", str(limit),
    ]
    return run_gh(cmd)


def get_issue_state(issue_number: int) -> str:
    """Return 'OPEN' or 'CLOSED' (or 'UNKNOWN' on error) for a specific issue.
    Uses module-level per-run cache for performance (AC #3 for snapshot builder in frequent /afk cycles).
    #34: Graceful handling for non-existent/invalid blocker refs (never sys.exit; treat as open blocker).
    """
    global _issue_state_cache
    if issue_number in _issue_state_cache:
        return _issue_state_cache[issue_number]
    try:
        # Use check=False so bad/non-existent issue numbers (common in stale "Blocked by" refs)
        # do not cause sys.exit(1) in run_gh. This fixes the hard crash reported in #34.
        data = run_gh(["issue", "view", str(issue_number), "--json", "number,state"], check=False)
        if isinstance(data, dict):
            state = data.get("state", "UNKNOWN")
        else:
            # stdout was error text or empty (gh failed for nonexistent #); treat as open
            state = "UNKNOWN"
        _issue_state_cache[issue_number] = state
        return state
    except Exception as e:
        print(f"Warning: could not resolve state of #{issue_number}: {e}", file=sys.stderr)
        return "UNKNOWN"


def collect_referenced_blockers(issues: List[Dict[str, Any]]) -> Set[int]:
    """Extract every unique issue number mentioned as a blocker across the given issues."""
    blockers: Set[int] = set()
    for issue in issues:
        body = issue.get("body") or ""
        blockers.update(parse_blockers(body))
    return blockers


def resolve_closed_blockers(blocker_numbers: Set[int]) -> Set[int]:
    """Return the subset of blocker numbers that are currently CLOSED.
    Hardened with better logging + graceful handling (AC #4).
    """
    closed: Set[int] = set()
    for num in sorted(blocker_numbers):
        try:
            state = get_issue_state(num)
            if state == "CLOSED":
                closed.add(num)
        except Exception as e:
            # Non-fatal: treat unknown as open so we don't accidentally mark ready.
            # Enhanced for prod (includes more context).
            print(f"Warning: could not resolve state of #{num}: {e}", file=sys.stderr)
    return closed


def main() -> None:
    global _issue_state_cache
    _issue_state_cache.clear()  # fresh per invocation for predictable snapshot behavior

    parser = argparse.ArgumentParser(
        description="Fetch agent-labeled issues and classify ready vs blocked using gh CLI. (Snapshot builder hardened for #25: caching + errors.)"
    )
    parser.add_argument(
        "--label", default="agent",
        help="Label used to identify autonomous-work issues (default: agent)"
    )
    parser.add_argument(
        "--limit", type=int, default=50,
        help="Maximum number of issues to fetch (default: 50)"
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Output machine-readable JSON instead of human summary"
    )
    parser.add_argument(
        "--epic", type=int, default=None,
        help="Optional: only consider direct children of this epic issue number (epic sub filtering; agent epics handled via sub-issue graph in engine per #30)"
    )
    args = parser.parse_args()

    print(f"Fetching open issues with label '{args.label}' via gh ...", file=sys.stderr)

    all_afk_issues = fetch_open_issues(args.label, args.limit)

    # #30 Epic lifecycle: do NOT filter agent epics here.
    # All issues from the --label agent query carry the agent label (by construction).
    # Agent epics (is_epic + agent) must flow through to find_ready_afk_issues (which now only
    # skips *pure* non-agent epics) and onward to snapshot_builder so that open direct
    # sub-issues can be detected (via gh api) and marked as has_open_blockers.
    # This enables the blocked-while-children-open rule + the post-child-close auto-close hook in apply.
    # (Pure tracking epics without agent remain excluded as before.)
    referenced = collect_referenced_blockers(all_afk_issues)
    closed_blockers = resolve_closed_blockers(referenced)

    ready, blocked = find_ready_afk_issues(
        all_afk_issues,
        closed_blockers,
        epic_sub_issue_numbers=None,  # sub-issue child discovery now implemented in snapshot_builder for agent epics (#30)
        in_progress_label="in-progress",
    )

    result = {
        "label": args.label,
        "total_fetched": len(all_afk_issues),
        "ready": ready,
        "blocked": blocked,
        "closed_blockers_considered": sorted(closed_blockers),
        "referenced_blockers": sorted(referenced),
    }

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print("\n=== AFK Ready Issues (gh fetcher) ===\n")
        if ready:
            print("READY TO START:")
            for r in ready:
                print(f"  #{r['number']:3d}  {r['title']}")
        else:
            print("No issues currently ready (all blocked or in-progress).")

        if blocked:
            print("\nBLOCKED:")
            for b in blocked:
                print(f"  #{b['number']:3d}  {b['title']}")
                print(f"         waiting on: {b.get('blocked_by', [])}")

        print(f"\nSummary: {len(ready)} ready, {len(blocked)} blocked.")
        print("(Run with --json for structured output the orchestrator can parse.)")


if __name__ == "__main__":
    main()