"""
AFK Token Usage Reporter (#31)

Small, focused module for posting subagent token usage + estimated cost
to the tracked GitHub issue when an implementor or reviewer worker finishes
(success or failure).

Designed for the *thin runner / orchestrator* (after `get_command_or_subagent_output`
or equivalent harness completion metadata returns).

- Best-effort, never breaks the core loop.
- Uses gh CLI (preferred, consistent with fetch/apply) via subprocess.
- Rich result dicts for runner observability / session / logging (like apply.py).
- Optional estimated USD cost (simple table; None if model unknown).
- Dry-run fully supported.
- Session recording helper for usage history / future aggregates.

Public API (importable by runners):
    from afk.token_reporter import (
        post_subagent_token_usage,
        record_subagent_completion_in_session,
        estimate_cost_usd,
    )

See SKILL.md and AFK_ENGINE_DESIGN.md for orchestrator integration guidance
and example call sites after worker reaping.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any, Optional


def _find_repo_root() -> Path:
    """Canonical repo root from inside .grok/skills/afk/ (matches apply.py, cli.py)."""
    return Path(__file__).resolve().parents[3]


def _run_cmd(cmd: list[str], timeout: int = 60) -> dict[str, Any]:
    """Run shell cmd (gh etc.) and return structured result. Never raises; best-effort."""
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
    except Exception as e:
        return {
            "success": False,
            "returncode": -1,
            "stdout": "",
            "stderr": str(e),
            "cmd": " ".join(cmd),
            "exception": str(type(e)),
        }


# Approximate per-token USD rates (2026-era estimates; update when xAI publishes new pricing).
# Keyed by lowercase model prefix. Rates are *per token*.
_PRICING_TABLE: dict[str, tuple[float, float]] = {
    "grok-4": (5.0e-6, 15.0e-6),
    "grok-4.3": (5.0e-6, 15.0e-6),
    "grok-3": (2.0e-6, 10.0e-6),
    "grok-beta": (3.0e-6, 12.0e-6),
}


def estimate_cost_usd(
    model: Optional[str],
    input_tokens: int,
    output_tokens: int,
) -> Optional[float]:
    """
    Best-effort cost estimate. Returns None for unknown model (no crash, feature is optional).
    """
    if not model or input_tokens < 0 or output_tokens < 0:
        return None
    key = model.lower().strip()
    # Try exact, then prefix match for variants (e.g. grok-4-turbo)
    rates = _PRICING_TABLE.get(key)
    if rates is None:
        for prefix, r in _PRICING_TABLE.items():
            if key.startswith(prefix):
                rates = r
                break
    if rates is None:
        return None
    in_rate, out_rate = rates
    cost = (input_tokens * in_rate) + (output_tokens * out_rate)
    return round(cost, 6)


def post_subagent_token_usage(
    *,
    issue_number: int,
    role: str,  # "implementor" | "reviewer"
    tokens_in: int = 0,
    tokens_out: int = 0,
    tokens_total: int = 0,
    model: Optional[str] = None,
    duration: Optional[str] = None,
    tool_calls: Optional[int] = None,
    subagent_id: Optional[str] = None,
    final_status: str = "success",
    error_info: Optional[str] = None,
    dry_run: bool = False,
    repo_root: Optional[Path] = None,
) -> dict[str, Any]:
    """
    Post (or simulate) a clear, human + machine-readable usage comment on the GitHub issue.

    Called by the thin runner / orchestrator immediately after a subagent completes
    (success, failure, or early exit) and token metadata is available from the harness.

    Returns rich result dict (consistent with apply.py results) for logging, session
    recording, and TUI visibility. Best-effort: never raises on gh errors.
    """
    if repo_root is None:
        try:
            repo_root = _find_repo_root()
        except Exception as e:
            return {
                "type": "token_usage_comment",
                "issue": issue_number,
                "success": False,
                "dry_run": dry_run,
                "details": f"Failed to locate repo root: {e}",
                "error": str(e),
            }

    est_cost = estimate_cost_usd(model, tokens_in, tokens_out)

    cost_str = f"${est_cost:.4f}" if est_cost is not None else "N/A (pricing unknown for model)"
    model_str = model or "unknown"
    duration_str = duration or "N/A"
    tool_str = str(tool_calls) if tool_calls is not None else "N/A"
    id_str = subagent_id or "N/A"

    error_line = f"- Error info: {error_info}\n" if error_info else ""

    body = (
        f"**AFK Subagent Finished** ({role})\n\n"
        f"- Subagent ID: {id_str}\n"
        f"- Duration: {duration_str}\n"
        f"- Tool calls: {tool_str}\n"
        f"- Tokens: {tokens_in} in / {tokens_out} out / {tokens_total} total\n"
        f"- Est. cost: {cost_str} (model: {model_str})\n"
        f"- Final status: {final_status}\n"
        f"{error_line}\n"
        "This data was captured automatically from the subagent harness on completion "
        "(visible without digging into TUI logs).\n\n"
        "<!-- AFK machine-readable token usage record (parseable by tools/scripts) -->\n"
        "```json\n"
        + json.dumps(
            {
                "type": "afk_subagent_usage",
                "issue": issue_number,
                "role": role,
                "subagent_id": subagent_id,
                "tokens": {
                    "input": tokens_in,
                    "output": tokens_out,
                    "total": tokens_total,
                },
                "model": model,
                "est_cost_usd": est_cost,
                "duration": duration,
                "tool_calls": tool_calls,
                "final_status": final_status,
            },
            indent=2,
        )
        + "\n```"
    )

    cmd = ["gh", "issue", "comment", str(issue_number), "--body", body]

    if dry_run:
        return {
            "type": "token_usage_comment",
            "issue": issue_number,
            "success": True,
            "dry_run": True,
            "details": f"DRY-RUN: would run: {' '.join(cmd[:4])} ... (body len={len(body)}). Est cost={est_cost}. Role={role} status={final_status}",
            "error": None,
            "command": " ".join(cmd),
            "est_cost_usd": est_cost,
            "body_preview": body[:300] + "...",
        }

    run_res = _run_cmd(cmd)
    success = run_res["success"]

    details = (
        f"gh issue comment for #{issue_number} (role={role}, status={final_status}): "
        f"rc={run_res['returncode']}. stdout={run_res['stdout'][:150]}"
    )
    if not success:
        details += f" | stderr={run_res['stderr'][:150]}"

    return {
        "type": "token_usage_comment",
        "issue": issue_number,
        "success": success,
        "dry_run": False,
        "details": details,
        "error": None if success else (run_res["stderr"] or run_res.get("exception")),
        "command": run_res.get("cmd"),
        "est_cost_usd": est_cost,
    }


def record_subagent_completion_in_session(
    *,
    issue: int,
    role: str,
    usage: dict[str, Any],
    session_path: Optional[Path] = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """
    Best-effort merge of completion/usage info into .grok/afk-session.json.

    Runner can call this after posting the comment (or in same step) to persist
    history for diagnostics, future snapshot enrichment, or aggregate cost views.

    Uses the same safe atomic-write pattern as apply.py.
    """
    if session_path is None:
        try:
            repo_root = _find_repo_root()
            session_path = repo_root / ".grok" / "afk-session.json"
        except Exception as e:
            return {
                "type": "session_usage_record",
                "issue": issue,
                "success": False,
                "dry_run": dry_run,
                "details": f"Failed to locate session path: {e}",
                "error": str(e),
            }

    entry = {
        "issue": issue,
        "role": role,
        "timestamp": None,  # runner can fill iso timestamp if desired
        "usage": usage,
    }

    if dry_run:
        return {
            "type": "session_usage_record",
            "issue": issue,
            "success": True,
            "dry_run": True,
            "details": f"DRY-RUN: would merge usage entry for #{issue} ({role}) into {session_path}",
            "error": None,
            "entry": entry,
        }

    try:
        current: dict[str, Any] = {}
        if session_path.exists():
            try:
                current = json.loads(session_path.read_text(encoding="utf-8"))
            except Exception:
                current = {}

        # Simple append to usage_log list (new or existing). Keep small.
        log = current.setdefault("usage_log", [])
        if isinstance(log, list):
            log.append(entry)
        else:
            current["usage_log"] = [entry]

        # Also maintain lightweight per-issue last_usage for quick lookup
        per_issue = current.setdefault("issue_usage", {})
        per_issue[str(issue)] = entry

        tmp_path = session_path.with_name(session_path.name + ".tmp")
        tmp_path.write_text(json.dumps(current, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp_path.replace(session_path)

        return {
            "type": "session_usage_record",
            "issue": issue,
            "success": True,
            "dry_run": False,
            "details": f"Session usage recorded for #{issue} (role={role}) at {session_path}",
            "error": None,
            "path": str(session_path),
        }
    except Exception as e:
        return {
            "type": "session_usage_record",
            "issue": issue,
            "success": False,
            "dry_run": False,
            "details": f"Session usage record failed for #{issue}: {e}",
            "error": str(e),
            "attempted_entry": entry,
        }
