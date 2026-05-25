"""
TDD tests for AFK token usage reporter (#31).

Follows patterns from test_engine_flow.py, test_find_ready_afk_issues.py:
- Robust imports (package + flat fallback)
- unittest.mock.patch for subprocess (gh calls)
- Docker-first execution via run-afk-tests.sh (no host pytest)
- Focus on dry-run, best-effort error resilience, rich result dicts, session updates
- Covers success + failure paths for implementor/reviewer

RED phase first: these will fail until token_reporter.py is implemented.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch, MagicMock
import json

# Robust imports matching project convention (enables relative + package use in Docker tests)
try:
    from afk.token_reporter import (
        estimate_cost_usd,
        post_subagent_token_usage,
        record_subagent_completion_in_session,
    )
    from afk.data_models import AFKContext
except ImportError:
    # Fallback for direct test runs / PYTHONPATH
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from token_reporter import (
        estimate_cost_usd,
        post_subagent_token_usage,
        record_subagent_completion_in_session,
    )
    from data_models import AFKContext


def test_estimate_cost_usd_known_model():
    """Cost estimator returns plausible positive float for known models (red until impl)."""
    cost = estimate_cost_usd("grok-4", 10000, 5000)
    assert cost is not None
    assert isinstance(cost, float)
    assert cost > 0
    assert cost < 1.0  # reasonable for small counts


def test_estimate_cost_usd_unknown_model_returns_none():
    """Unknown model or None -> None (no crash, optional feature)."""
    assert estimate_cost_usd(None, 100, 50) is None
    assert estimate_cost_usd("future-model-x", 100, 50) is None
    assert estimate_cost_usd("grok-99", 100, 50) is None


def test_post_subagent_token_usage_dry_run_no_side_effects_and_rich_result():
    """Dry-run path: returns rich dict, no subprocess.gh calls, includes est cost + formatted details."""
    with patch("afk.token_reporter.subprocess.run") as mock_run:
        result = post_subagent_token_usage(
            issue_number=31,
            role="implementor",
            tokens_in=12345,
            tokens_out=6789,
            tokens_total=19134,
            model="grok-4.3",
            duration="6m 30s",
            tool_calls=57,
            subagent_id="019e5d40-2100-7f03-b60b-03da71713d66",
            final_status="success",
            dry_run=True,
        )
        mock_run.assert_not_called()

    assert result["type"] == "token_usage_comment"
    assert result["issue"] == 31
    assert result["success"] is True
    assert result["dry_run"] is True
    assert "DRY-RUN" in result.get("details", "") or "would post" in result.get("details", "").lower()
    assert result.get("est_cost_usd") is not None
    assert "12345 in / 6789 out" in result.get("details", "") or "Tokens" in str(result)


def test_post_subagent_token_usage_real_path_calls_gh_and_returns_success_result():
    """Real (non-dry) path: invokes gh issue comment with good body; returns success result dict."""
    mock_res = MagicMock()
    mock_res.returncode = 0
    mock_res.stdout = "comment created"
    mock_res.stderr = ""

    with patch("afk.token_reporter.subprocess.run", return_value=mock_res) as mock_run:
        result = post_subagent_token_usage(
            issue_number=42,
            role="reviewer",
            tokens_in=8000,
            tokens_out=3200,
            tokens_total=11200,
            model="grok-3",
            duration="4m 12s",
            tool_calls=31,
            subagent_id="abc-123",
            final_status="status-in-review",
            dry_run=False,
        )

    # Verify gh was called (at least once, with expected cmd shape)
    assert mock_run.called
    called_cmd = mock_run.call_args[0][0] if mock_run.call_args else []
    cmd_str = " ".join(called_cmd) if isinstance(called_cmd, (list, tuple)) else str(called_cmd)
    assert "gh" in cmd_str
    assert "issue" in cmd_str
    assert "comment" in cmd_str or "42" in cmd_str

    assert result["type"] == "token_usage_comment"
    assert result["issue"] == 42
    assert result["success"] is True
    assert result["dry_run"] is False
    assert result.get("est_cost_usd") is not None  # grok-3 known


def test_post_subagent_token_usage_failure_path_is_resilient():
    """gh failure (nonzero rc): still returns result with success=False + error details (best-effort, no raise)."""
    mock_res = MagicMock()
    mock_res.returncode = 1
    mock_res.stdout = ""
    mock_res.stderr = "rate limit or auth error"

    with patch("afk.token_reporter.subprocess.run", return_value=mock_res) as mock_run:
        result = post_subagent_token_usage(
            issue_number=99,
            role="implementor",
            tokens_in=100,
            tokens_out=10,
            tokens_total=110,
            final_status="error",
            error_info="subagent crashed",
            dry_run=False,
        )

    assert result["success"] is False
    assert "error" in result or result.get("stderr")
    assert result["issue"] == 99
    assert "error" in result.get("details", "").lower() or result.get("error")


def test_record_subagent_completion_in_session_dry_run_and_merge():
    """Session recording helper: dry-run + real (atomic write pattern), appends usage entry."""
    fake_session = {"running": {}, "completed": []}
    tmp_path = Path("/tmp") / "afk-session-test.json"  # will be mocked in real path

    # Dry run
    res_dry = record_subagent_completion_in_session(
        issue=31,
        role="implementor",
        usage={"tokens_total": 19134, "est_cost_usd": 0.048},
        session_path=tmp_path,
        dry_run=True,
    )
    assert res_dry["success"]
    assert res_dry["dry_run"]
    assert "would merge" in res_dry.get("details", "").lower()

    # Real path: mock fs + atomic write
    with patch("pathlib.Path.exists", return_value=True), \
         patch("pathlib.Path.read_text", return_value=json.dumps(fake_session)), \
         patch("pathlib.Path.write_text") as mock_write, \
         patch("pathlib.Path.replace") as mock_replace:
        res_real = record_subagent_completion_in_session(
            issue=31,
            role="reviewer",
            usage={"tokens_in": 5000, "model": "grok-4"},
            session_path=tmp_path,
            dry_run=False,
        )
        assert res_real["success"]
        assert res_real["dry_run"] is False
        # Ensure write + replace happened (atomic)
        assert mock_write.called or mock_replace.called


def test_reporter_importable_and_non_breaking():
    """Smoke: module loads, funcs are callable, accept minimal args for both roles (v1 contract)."""
    assert callable(estimate_cost_usd)
    assert callable(post_subagent_token_usage)
    assert callable(record_subagent_completion_in_session)

    # Minimal calls should not crash (even if result imperfect before full impl)
    r1 = post_subagent_token_usage(issue_number=1, role="implementor", dry_run=True)
    assert isinstance(r1, dict)
    r2 = post_subagent_token_usage(issue_number=2, role="reviewer", dry_run=True)
    assert isinstance(r2, dict)
