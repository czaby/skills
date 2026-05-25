#!/usr/bin/env python3
"""
AFK Ready Issue Finder

Helper for the /afk skill.

This module contains the pure classification logic used by the AFK orchestrator
to decide which `agent`-labeled issues are currently unblocked and safe to work on.

## Canonical Dependency Syntax

See the full authoritative specification and examples in:
.grok/skills/afk/SKILL.md → "Dependency Syntax (Authoritative Specification)"

Supported blocker phrases (recognized by parse_blockers):

- **Blocked by**: #123
- Blocked by: #123, #456 (and #789)
- **Depends on**: #45
- Blocked by (completed work): Slice 2 (issue #4)
- Blocked by: (none)

The parser is deliberately tolerant of:
- Markdown emphasis (**Blocked by**, _Depends on_, etc.)
- Parenthetical notes after the number
- "and", commas, semicolons, etc. between multiple blockers

## Usage (from the main orchestrator agent)

1. Preferred: Run `python .grok/skills/afk/fetch_afk_issues.py --json`
   (uses gh CLI to fetch `agent` issues + resolve blocker states).
2. Or manually: Use GitHub MCP / gh CLI to obtain open `agent` issues (with bodies)
   and the set of closed blocker numbers.
3. Feed the data to `find_ready_afk_issues()` (or run this file directly with JSON files).
4. It returns (ready_issues, blocked_issues_with_reasons).

The module is intentionally pure (stdlib only) so it can be used from the orchestrator,
from fetcher scripts, or from unit tests without any GitHub API calls.
"""

import json
import re
import sys
from typing import Any, Dict, List, Set, Tuple

BLOCKER_PATTERNS = [
    # Declaration-style only (post-#34 robustness). These are the authoritative syntactic forms
    # from SKILL.md. Prose uses of the words "blocked by" (even followed by #NNN in an example)
    # will no longer falsely trigger blocker extraction.
    # Primary capture requires the declaration flavor (colon, bold, "completed work", paren note, etc.)
    # immediately around the "Blocked by" / "Depends on" phrase.
    r"(?i)(?:^|[\n*_\s])(?:blocked by|depends on)\s*[:*]\s*#?(\d+)",  # "Blocked by: #NN" or "**Blocked by** #NN"
    r"(?i)blocked by\s*\(completed work\)[^#]*#(\d+)",               # historical "Blocked by (completed work): ... #NN"
    r"(?i)blocked by\s*[^#]{0,30}\(issue\s*#(\d+)\)",                # "Blocked by ... (issue #NN)"
    r"(?i)depends on\s*[^#]{0,20}#(\d+)",                            # "Depends on: #NN" (with some tolerance)
]


def _strip_markdown_code_for_parsing(body: str) -> str:
    """
    Remove markdown code blocks and inline code from body text before
    searching for blocker declarations.

    This prevents false-positive blocker extraction from:
    - Example error traces in bug report issues (e.g. "gh issue view 404" inside
      prose describing a parser crash).
    - Code snippets, shell sessions, or JSON examples that happen to contain #NNN.
    - Backticked syntax mentions like `Blocked by` in descriptive text.

    Fenced blocks (``` or ~~~) and `inline code` are stripped. This is sufficient
    to unblock AFK discovery on repos with self-referential bug reports like #34.
    """
    if not isinstance(body, str):
        return ""
    text = body
    # Remove fenced code blocks (```lang ... ``` or ~~~ ... ~~~). (?s) for dotall across newlines.
    text = re.sub(r'(?s)```.*?```', ' ', text)
    text = re.sub(r'(?s)~~~.*?~~~', ' ', text)
    # Remove inline code spans `...` (non-greedy, stop at newline to be safe).
    text = re.sub(r'`[^`\n]+`', ' ', text)
    return text


def parse_blockers(body: str) -> List[int]:
    """Extract issue numbers mentioned as blockers in the body.

    Production-hardened (for AFK snapshot builder, issue #25):
    - Robust matching of realistic GitHub phrasings (completed work, lists via follow-on capture,
      parentheticals, extra prose between keyword and number).
    - Defensive handling of non-string / None bodies.
    - Deduplication while preserving order.
    - Conservative follow-on # capture only when blocker context present (safer: over-block > false-ready).
    - Code-aware: markdown fenced blocks and inline `code` are stripped first so that
      example traces, syntax docs, or error messages inside code do not produce false blockers
      (e.g. "gh issue view 404" in the body of the bug report for this very problem, #34).
    """
    if not isinstance(body, str):
        return []

    cleaned = _strip_markdown_code_for_parsing(body)

    blockers: List[int] = []
    for pattern in BLOCKER_PATTERNS:
        for match in re.finditer(pattern, cleaned):
            try:
                blockers.append(int(match.group(1)))
            except (ValueError, IndexError):
                pass

    # Follow-on list capture for common real patterns like "#10 and #11", ", #12"
    # after a blocker keyword. We only scan *from the first blocker phrase onward*
    # (and only a limited window) using a stricter regex requiring explicit "#"
    # to avoid picking up stray numbers that appear in free text, examples,
    # external trackers, versions, or unrelated sections *after* the phrase.
    #
    # Declaration-aware trigger (post-#34): only open the follow-on window for phrases
    # that look like *AFK dependency declarations* (colon, bold **, or immediate # after "by/on"),
    # not for prose uses such as "discovery was blocked by a reference to #404" in bug reports.
    # This is the key robustness fix so that self-describing AFK bug issues do not poison discovery.
    first_blocker = re.search(r'(?i)\b(?:blocked by|depends on)\s*[:*#]', cleaned)
    if not first_blocker:
        # Fallback: also accept the very common bolded form "**Blocked by** #NN" etc.
        first_blocker = re.search(r'(?i)\*\*(?:blocked by|depends on)\*\*', cleaned)

    if first_blocker:
        start_pos = first_blocker.start()
        after = cleaned[start_pos : start_pos + 256]  # conservative proximity window (#32)
        for m in re.finditer(r'#(\d+)', after):  # require explicit # (stricter than original #?)
            n = int(m.group(1))
            if n > 0 and n not in blockers:
                blockers.append(n)

    return blockers

def is_epic_issue(issue: Dict[str, Any]) -> bool:
    """Heuristic for meta/epic tracking issues.

    We treat an issue as an epic for *filtering* purposes only if it has an
    explicit "epic" label **or** its title starts with "epic".

    **#30 Epic lifecycle update**: Agent-labeled epics (agent + the heuristic)
    are *no longer skipped* from AFK data flows. They participate in snapshot
    construction so that open direct sub-issues can be detected as blockers
    and the auto-close hook in apply can fire when the last child completes.
    Only pure (non-`agent`) epics are filtered from normal ready/blocked
    classification. This prevents false positives on regular work (e.g. this
    very issue's title) while enabling the lifecycle rule.
    """
    title = (issue.get("title") or "").lower().strip()
    labels = [l.get("name", "").lower() for l in issue.get("labels", [])]

    return "epic" in labels or title.startswith("epic")

def find_ready_afk_issues(
    all_afk_issues: List[Dict[str, Any]],
    closed_issue_numbers: Set[int],
    epic_sub_issue_numbers: Set[int] | None = None,
    in_progress_label: str = "in-progress",
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Returns (ready_issues, blocked_issues_with_reason)
    """
    ready = []
    blocked = []

    for issue in all_afk_issues:
        num = issue.get("number")
        title = issue.get("title", "")
        body = issue.get("body", "") or ""
        labels = [l.get("name", "") for l in issue.get("labels", [])]

        # Skip epics / meta tracking issues
        # #30 Epic lifecycle rule: agent-labeled Epics are *not* skipped (they participate for
        # open direct sub-issue detection as blockers + post-close auto-close hook in apply).
        # Only pure (non-agent) epics are filtered from normal AFK work classification.
        if is_epic_issue(issue) and "agent" not in labels:
            continue

        # Skip anything already in progress
        if in_progress_label in labels:
            continue

        # Parse blockers from body
        raw_blockers = parse_blockers(body)

        # Also treat any "Blocked by Slice X (issue #Y)" style references
        # For now we rely on explicit #NNN numbers in the body.

        unresolved = []
        for b in raw_blockers:
            if b not in closed_issue_numbers:
                unresolved.append(b)

        # Optional: only consider issues that are children of the main Epic
        if epic_sub_issue_numbers is not None and num not in epic_sub_issue_numbers:
            continue

        if unresolved:
            blocked.append({
                "number": num,
                "title": title,
                "blocked_by": unresolved,
                "reason": f"Still waiting on open issues: {unresolved}"
            })
        else:
            ready.append({
                "number": num,
                "title": title,
                "labels": labels,
            })

    # Sort ready issues by number (smaller first = usually earlier in the plan)
    ready.sort(key=lambda x: x["number"])

    return ready, blocked


def main():
    """
    CLI usage example (for manual testing by the agent):

    python find_ready_afk_issues.py issues.json closed.json [epic_subs.json]
    """
    if len(sys.argv) < 3:
        print("Usage: python find_ready_afk_issues.py <all_afk_issues.json> <closed_numbers.json> [epic_sub_numbers.json]")
        sys.exit(1)

    with open(sys.argv[1]) as f:
        all_afk = json.load(f)

    with open(sys.argv[2]) as f:
        closed = set(json.load(f))

    epic_subs = None
    if len(sys.argv) > 3:
        with open(sys.argv[3]) as f:
            epic_subs = set(json.load(f))

    ready, blocked = find_ready_afk_issues(all_afk, closed, epic_subs)

    print(json.dumps({"ready": ready, "blocked": blocked}, indent=2))


if __name__ == "__main__":
    main()