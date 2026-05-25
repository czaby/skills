"""
AFK Engine Package

This package contains the deterministic, testable core of the new AFK system.

Primary public API:
    from afk_engine import run_afk_cycle

    result = run_afk_cycle()
"""

from .engine import run_afk_cycle

from .apply import remove_stale_status_labels_once
from .token_reporter import (
    post_subagent_token_usage,
    record_subagent_completion_in_session,
    estimate_cost_usd,
)

__all__ = [
    "run_afk_cycle",
    "remove_stale_status_labels_once",
    "post_subagent_token_usage",
    "record_subagent_completion_in_session",
    "estimate_cost_usd",
]