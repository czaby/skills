"""
Command-line interface for the AFK engine.

This is intentionally small. Most behavior lives in the engine modules.

As of #36: the thin runner entrypoint (this CLI, and real /afk orchestrator code)
performs a one-time call to remove_stale_status_labels_once(...) at startup,
before the first run_afk_cycle(). The hygiene function is narrow (only stale
status-* label removal on agent issues using dual session+live detection).
The runner owns session loading, live subagent set construction, and all
result processing / observability.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .engine import run_afk_cycle


def main() -> None:
    parser = argparse.ArgumentParser(description="AFK Engine")
    parser.add_argument("--dry-run", action="store_true", help="Compute plan but do not apply changes")
    parser.add_argument("--no-apply", action="store_true", help="Do not apply safe mutations")

    args = parser.parse_args()

    # === One-time startup hygiene (#36) - thin runner responsibility ===
    # Called exactly once per /afk invocation, after session load + live discovery
    # (here: session load + empty live set for cli; real runner supplies active
    # subagents from its spawn tracking), BEFORE the first run_afk_cycle().
    # Function returns rich results; runner decides what to do with them (log,
    # session event, optional GH comment). Engine remains untouched.
    hygiene_results: list[dict] = []
    try:
        # Same repo root convention used by apply layer (reliable even if cwd varies)
        repo_root = Path(__file__).resolve().parents[3]
        session_path = repo_root / ".grok" / "afk-session.json"
        session: dict = {}
        if session_path.exists():
            try:
                session = json.loads(session_path.read_text(encoding="utf-8"))
            except Exception:
                session = {}  # best-effort; corrupt session -> treat as empty

        # cli itself does not manage live subagents (those are in the full
        # orchestrator using spawn_subagent / background tasks). Pass empty set.
        # The real thin runner (e.g. main Grok /afk handler) must pass the
        # current set of live issue numbers from its subagent tracking.
        active_issues: set[int] = set()

        from .apply import remove_stale_status_labels_once

        hygiene_results = remove_stale_status_labels_once(
            session=session,
            active_subagent_issues=active_issues,
            dry_run=args.dry_run,
            repo_root=repo_root,
        )

        if hygiene_results:
            print("[AFK #36] Startup hygiene results (stale status-* removal on agent issues):")
            for r in hygiene_results:
                print(
                    f"  #{r.get('issue')}: success={r.get('success')} "
                    f"dry_run={r.get('dry_run')} removed={r.get('labels_removed', [])} "
                    f"| {r.get('details', '')[:100]}"
                )
        else:
            print("[AFK #36] Startup hygiene: no qualifying stale status-* on agent issues (or all active).")
    except Exception as ex:
        # Hygiene is best-effort / non-fatal startup step. Always proceed to engine.
        print(f"[AFK #36] Warning: non-fatal error during startup hygiene (continuing to cycle): {ex}")

    # First (and subsequent) engine cycle happens *after* the hygiene pass.
    result = run_afk_cycle(
        dry_run=args.dry_run,
        apply_changes=not args.no_apply,
    )

    print(result)


# =============================================================================
# #31: Token usage reporting hook (runner / orchestrator responsibility)
# =============================================================================
# After any subagent (implementor or reviewer) completes — success or failure —
# the thin runner calls the following (after extracting fields from
# get_command_or_subagent_output / harness metadata):
#
#   from afk.token_reporter import post_subagent_token_usage, record_subagent_completion_in_session
#   usage_res = post_subagent_token_usage(
#       issue_number=..., role=..., tokens_in=..., tokens_out=..., tokens_total=...,
#       model=..., duration=..., tool_calls=..., subagent_id=..., final_status=...,
#       dry_run=...
#   )
#   # Then (optional but recommended for history/aggregates):
#   sess_res = record_subagent_completion_in_session(issue=..., role=..., usage={...})
#
# Both return rich dicts (like remove_stale... and apply results) for logging + observability.
# The comment is posted directly to the GitHub issue (single source of truth).
# See token_reporter.py, SKILL.md, and AFK_ENGINE_DESIGN.md for full contract + examples.
# This is deliberately outside the engine (post-finish side effect, like #36 hygiene).
# =============================================================================


if __name__ == "__main__":
    main()