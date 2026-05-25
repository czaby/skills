#!/usr/bin/env python3
"""
AFK Thin Runner / Orchestrator (Very Thin Runner implementation).

This is the canonical home for the "Very Thin Runner" logic described in
SKILL.md and AFK_ENGINE_DESIGN.md.

Responsibilities (owned by the runner, NOT the engine):
- One-time startup hygiene (#36): call remove_stale_status_labels_once exactly once
  before the first run_afk_cycle(), passing live subagent knowledge from the harness.
- Repeatedly calling run_afk_cycle().
- Materializing real worktree paths + branches using the documented convention.
- Injecting the "CRITICAL — ISOLATED GIT WORKTREE (MANDATORY)" block into prompts
  before any subagent is actually spawned (the engine/translator only emit placeholders).
- Executing SpawnRequests (in the TUI harness this means calling the real
  spawn_subagent tool with background=True + proper cwd isolation).
- Post-completion side effects: token usage reporting (#31), session recording,
  worktree cleanup on final success, etc.
- The top-level loop: keep cycling until the engine says no_more_work AND there
  are zero live subagents.

This module is both:
1. Importable by the Grok TUI /afk handler (preferred integration path).
2. Directly executable for standalone / CLI / debugging use (`--once` is safe).

Design principle: Keep this file small and obvious. All real judgment lives in
the deterministic engine (state_machine, translator, etc.).

See also:
- cli.py (intentionally minimal one-cycle wrapper, still useful for ad-hoc)
- engine.py (the thing this runner drives)
- apply.py (remove_stale_status_labels_once and safe mutations)
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional, Set

# --- Package setup (robust even when run directly) ---
SCRIPT_DIR = Path(__file__).parent
if str(SCRIPT_DIR.parent) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR.parent))

from afk.apply import (
    _find_repo_root as _apply_find_repo_root,
    _get_worktree_base,
    remove_stale_status_labels_once,
)
from afk.data_models import AFKCycleResult, SpawnRequest
from afk.engine import run_afk_cycle
from afk.token_reporter import (
    post_subagent_token_usage,
    record_subagent_completion_in_session,
)

# =============================================================================
# Worktree path resolution (runner-owned, matches documented convention)
# =============================================================================

def resolve_worktree_paths(issue: int, target_repo_root: Optional[Path] = None) -> tuple[str, str]:
    """
    Return (worktree_path, branch) for the given issue using the official convention.

    Convention (from SKILL.md):
      - Worktree base: sibling to the target repo, named "grok-afk-worktrees"
      - Example: if target repo is /home/czaby/w/grok → /home/czaby/w/grok-afk-worktrees/issue-42
      - Branch: afk/<number>

    The engine currently emits placeholder /tmp paths in SpawnRequest.
    The thin runner MUST call this (or equivalent) and patch before spawning.
    """
    if target_repo_root is None:
        # Best effort: the repo we are currently inside (for AFK workers)
        try:
            target_repo_root = Path(
                subprocess.check_output(
                    ["git", "rev-parse", "--show-toplevel"], text=True, timeout=5
                ).strip()
            )
        except Exception:
            # Fallback to the .grok parent layout assumption
            target_repo_root = _apply_find_repo_root().parent / "w" / "grok"  # common dev layout

    base = _get_worktree_base(target_repo_root)  # from apply.py (sibling dir)
    worktree = str((base / f"issue-{issue}").resolve())
    branch = f"afk/{issue}"
    return worktree, branch


# =============================================================================
# CRITICAL worktree prompt block (injected by runner at spawn time)
# =============================================================================

CRITICAL_WORKTREE_BLOCK = """## CRITICAL — ISOLATED GIT WORKTREE (MANDATORY)

You **must not** modify the original repository checkout at all.

- Worktree root (absolute path — use this for **every** tool call):
  {worktree}

- Your private branch: {branch}

**Rules for tool usage (non-negotiable):**

1. **run_terminal_command**:
   - **Every** command must start with:
     `cd {worktree} && `
   - Good example:
     `cd {worktree} && git status`
     `cd {worktree} && python -m pytest -x`

2. **File system tools** (`read_file`, `write`, `search_replace`, `list_dir`, `grep`, etc.):
   - Always use the **full absolute path** under the worktree root.
   - Correct: `read_file` with target_file = `{worktree}/README.md`
   - Correct: `list_dir` with target_directory = `{worktree}/src`
   - Never use relative paths or paths under the original checkout.

3. **Committing & branching rules**:
   - You may create local commits on `{branch}` during development.
   - **You are forbidden from touching `main`, `origin/main`, or performing any merge/push to the primary branch.**
   - Only after the issue is **completely finished**, all tests pass, and you have written a final summary comment:
     - Produce one clean final commit (or amend the last one) with a message referencing the GitHub issue.
     - Tell the orchestrator you are done.
   - The orchestrator (not you) will merge `{branch}` into `main` from the primary checkout and clean up the worktree.

4. **Error / stuck / need human help**:
   - **Stop working immediately.**
   - Post a detailed comment on the GitHub issue explaining the problem.
   - **Leave the entire worktree exactly as it is** (do not `git reset`, `git clean`, or delete anything).
   - Exit cleanly.

The orchestrator will give the human the exact commands to inspect, continue, or discard your worktree.
"""


def enrich_spawn_request_with_worktree(
    req: SpawnRequest,
    target_repo_root: Optional[Path] = None,
) -> SpawnRequest:
    """
    Take a SpawnRequest from the engine (which may contain placeholder paths)
    and return a new one with real paths + the full CRITICAL worktree instructions
    prepended to the prompt.

    This must be called by the thin runner **immediately before** actually
    spawning the subagent.
    """
    real_worktree, real_branch = resolve_worktree_paths(req.issue, target_repo_root)

    # Prepend the critical block (the prompt from translator already contains
    # the implementor/reviewer checklists and rich snapshot context).
    critical_block = CRITICAL_WORKTREE_BLOCK.format(
        worktree=real_worktree, branch=real_branch
    )
    enriched_prompt = critical_block + "\n\n" + (req.prompt or "")

    return SpawnRequest(
        issue=req.issue,
        role=req.role,
        worktree=real_worktree,
        branch=real_branch,
        prompt=enriched_prompt,
        reason=req.reason,
    )


# =============================================================================
# Thin runner core
# =============================================================================

@dataclass
class AFKRunConfig:
    dry_run: bool = False
    apply_changes: bool = True
    max_concurrent: int = 2
    # Future: epic filter, etc.


class AFKThinRunner:
    """
    The Very Thin Runner for a complete /afk session.

    Typical usage from the Grok TUI harness:

        runner = AFKThinRunner(
            active_issues_provider=lambda: get_current_live_subagent_issues(),
            spawn_callback=spawn_real_subagent,   # your harness function
            on_completion=handle_worker_done,     # does token reporting etc.
        )
        runner.run_until_exhausted()

    The runner itself stays extremely simple: it only calls the engine and
    invokes the callbacks you give it. All policy is in the engine.
    """

    def __init__(
        self,
        *,
        config: Optional[AFKRunConfig] = None,
        target_repo_root: Optional[Path] = None,
        active_issues_provider: Optional[Callable[[], Set[int]]] = None,
        spawn_callback: Optional[Callable[[SpawnRequest], Any]] = None,
        completion_callback: Optional[Callable[[int, str, dict], None]] = None,
    ):
        self.config = config or AFKRunConfig()
        self.target_repo_root = target_repo_root
        self.active_issues_provider = active_issues_provider or (lambda: set())
        self.spawn_callback = spawn_callback
        self.completion_callback = completion_callback

        self.session: dict[str, Any] = {}
        self.session_path: Path
        self._load_session()

        self.live_subagents: dict[str, dict] = {}  # subagent_id -> metadata

    def _load_session(self) -> None:
        try:
            root = self.target_repo_root or _apply_find_repo_root()
        except Exception:
            root = Path("/home/czaby")  # last-resort fallback for global .grok

        self.session_path = root / ".grok" / "afk-session.json"
        if self.session_path.exists():
            try:
                self.session = json.loads(self.session_path.read_text(encoding="utf-8"))
            except Exception:
                self.session = {}
        else:
            self.session = {}

    def _save_session(self) -> None:
        try:
            tmp = self.session_path.with_name(self.session_path.name + ".tmp")
            tmp.write_text(json.dumps(self.session, indent=2, ensure_ascii=False), encoding="utf-8")
            tmp.replace(self.session_path)
        except Exception as ex:
            print(f"[orchestrator] Warning: failed to persist session: {ex}")

    def perform_startup_hygiene(self) -> list[dict]:
        """Exactly the #36 contract. Must be called once per /afk invocation."""
        print("[AFK #36] Executing one-time stale status-* label hygiene (thin runner)...")
        active = self.active_issues_provider()
        try:
            results = remove_stale_status_labels_once(
                session=self.session,
                active_subagent_issues=active,
                dry_run=self.config.dry_run,
                repo_root=self.target_repo_root,
            )
            if results:
                for r in results:
                    print(f"  #{r.get('issue')}: {r.get('status', r.get('details', ''))[:80]}")
            else:
                print("  No action required (or no open agent issues with stale labels).")
            return results
        except Exception as ex:
            print(f"[AFK #36] Non-fatal hygiene error (continuing): {ex}")
            return []

    def run_one_cycle(self) -> AFKCycleResult:
        """Single engine cycle. The runner's main primitive."""
        result = run_afk_cycle(
            dry_run=self.config.dry_run,
            apply_changes=self.config.apply_changes,
        )
        return result

    def process_spawn_requests(self, result: AFKCycleResult) -> list[SpawnRequest]:
        """
        Enrich + (optionally) spawn for every SpawnRequest in the result.

        Returns the enriched requests (real paths + critical block).
        Actual spawning is performed via the callback if provided.
        """
        enriched: list[SpawnRequest] = []
        for raw_req in result.spawn_requests:
            req = enrich_spawn_request_with_worktree(raw_req, self.target_repo_root)
            enriched.append(req)

            if self.spawn_callback:
                try:
                    sub_id = self.spawn_callback(req)
                    self.live_subagents[sub_id] = {
                        "issue": req.issue,
                        "role": req.role,
                        "started": datetime.now(timezone.utc).isoformat(),
                        "worktree": req.worktree,
                    }
                    print(f"[orchestrator] Spawned {req.role} for #{req.issue} (id={sub_id})")
                except Exception as ex:
                    print(f"[orchestrator] Spawn failed for #{req.issue}: {ex}")
            else:
                print(f"[orchestrator] Would spawn {req.role} for #{req.issue}")
                print(f"    worktree: {req.worktree}")
                print(f"    branch:   {req.branch}")
                print(f"    reason:   {req.reason}")
        return enriched

    def handle_worker_completion(
        self,
        subagent_id: str,
        issue: int,
        role: str,
        tokens: Optional[dict] = None,
        final_status: str = "success",
        error_info: Optional[str] = None,
    ) -> None:
        """
        Call this from the TUI harness after any subagent (implementor or reviewer)
        exits, success or failure. This is where #31 token reporting lives.
        """
        if subagent_id in self.live_subagents:
            del self.live_subagents[subagent_id]

        if tokens:
            try:
                res = post_subagent_token_usage(
                    issue_number=issue,
                    role=role,
                    tokens_in=tokens.get("in", 0),
                    tokens_out=tokens.get("out", 0),
                    tokens_total=tokens.get("total", 0),
                    model=tokens.get("model", "unknown"),
                    duration=tokens.get("duration", ""),
                    tool_calls=tokens.get("tool_calls", 0),
                    subagent_id=subagent_id,
                    final_status=final_status,
                    error_info=error_info,
                    dry_run=self.config.dry_run,
                )
                record_subagent_completion_in_session(
                    issue=issue,
                    role=role,
                    usage={
                        "tokens_total": tokens.get("total"),
                        "est_cost_usd": res.get("est_cost_usd"),
                        "model": tokens.get("model"),
                    },
                    dry_run=self.config.dry_run,
                )
                print(f"[orchestrator #31] Token usage posted for #{issue} ({role})")
            except Exception as ex:
                print(f"[orchestrator #31] Token reporting failed (non-fatal): {ex}")

        # Update local session view
        self._save_session()

    def run_until_exhausted(self, max_cycles: int = 100) -> None:
        """
        The default /afk persistent loop.

        Continues calling the engine, spawning, and re-cycling until:
          - engine reports no_more_work, AND
          - there are zero live subagents (from the provider)
        """
        print("=" * 72)
        print("AFK THIN RUNNER — FULL AUTONOMOUS SESSION STARTING")
        print("=" * 72)

        hygiene_res = self.perform_startup_hygiene()

        cycle = 0
        while cycle < max_cycles:
            cycle += 1
            print(f"\n[Cycle {cycle}] Running engine...")
            result = self.run_one_cycle()

            print(f"  no_more_work={result.no_more_work}  spawns={len(result.spawn_requests)}  errors={len(result.errors)}")

            self.process_spawn_requests(result)

            if result.no_more_work and not self.live_subagents and not self.active_issues_provider():
                print("\n" + "=" * 72)
                print("All currently unblocked AFK work has been completed.")
                print("Remaining open AFK issues (if any) are blocked by other open work.")
                print("=" * 72)
                break

            # In a real TUI harness the caller would now wait for subagents
            # using wait_commands_or_subagents / get_command_or_subagent_output.
            # This method is intentionally not blocking here — the harness owns waiting.
            if self.spawn_callback is None:
                # Standalone / test mode: just pause so a human can simulate progress
                print("\n[standalone] No spawn_callback provided. Pausing for manual simulation.")
                print("Press Enter to run next cycle (or Ctrl-C to exit)...")
                try:
                    input()
                except (EOFError, KeyboardInterrupt):
                    print("\nExiting early.")
                    break

            # Small courtesy pause in pure CLI mode to avoid hammering gh
            if self.spawn_callback is None:
                time.sleep(0.5)

        else:
            print(f"\nReached max_cycles={max_cycles} without natural exhaustion.")

        self._save_session()
        print("[orchestrator] Session saved. Run complete.")


# =============================================================================
# Standalone CLI (for direct execution and debugging)
# =============================================================================

def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="AFK Thin Orchestrator (recommended entrypoint for full /afk sessions)"
    )
    parser.add_argument("--dry-run", action="store_true", help="Compute plan but do not mutate")
    parser.add_argument("--no-apply", action="store_true", help="Skip safe mutations in engine")
    parser.add_argument("--once", action="store_true", help="Run a single engine cycle then exit (debugging)")
    parser.add_argument("--max-cycles", type=int, default=50, help="Safety cap for full loop mode")
    parser.add_argument("--target-repo", type=Path, default=None, help="Path to the git repo being AFK'd (for worktree sibling dir)")

    args = parser.parse_args(argv)

    config = AFKRunConfig(
        dry_run=args.dry_run,
        apply_changes=not args.no_apply,
    )

    runner = AFKThinRunner(
        config=config,
        target_repo_root=args.target_repo,
        # In pure CLI mode we have no live subagents and no real spawn mechanism.
        # The runner will print what it would do and (in non-once mode) pause between cycles.
    )

    if args.once:
        print("[orchestrator CLI] --once mode: hygiene + single cycle only")
        runner.perform_startup_hygiene()
        result = runner.run_one_cycle()
        runner.process_spawn_requests(result)
        print("\n[once] Cycle result:")
        print(f"  no_more_work={result.no_more_work}")
        print(f"  spawn_requests={len(result.spawn_requests)}")
        return 0 if result.no_more_work else 1

    # Full loop (the real /afk behavior when invoked without --once)
    runner.run_until_exhausted(max_cycles=args.max_cycles)
    return 0


if __name__ == "__main__":
    sys.exit(main())
