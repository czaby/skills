"""
Core data models for the AFK engine.

These types are the primary contract between the different layers
(state machine, translator, snapshot builder, apply logic, etc.).
"""

from dataclasses import dataclass, field
from typing import Literal, Any


# =============================================================================
# Core Snapshots & Context (Inputs to decision logic)
# =============================================================================

@dataclass
class IssueSnapshot:
    """Rich, pre-digested view of a single issue for decision making."""
    number: int
    current_labels: list[str] = field(default_factory=list)

    # Blocker information (derived by snapshot builder)
    has_open_blockers: bool = False
    open_blockers: list[int] = field(default_factory=list)

    # Worktree information
    worktree_exists: bool = False
    worktree_path: str | None = None

    # Recent AFK execution history on this specific issue
    last_subagent_role: Literal["implementor", "reviewer"] | None = None
    last_subagent_outcome: str | None = None   # "approved", "rejected", "error", etc.
    retry_count: int = 0

    # Derived convenience field (e.g. "in_review", "rejected_review", "in_progress", None)
    current_afk_phase: str | None = None

    # #30 Epic lifecycle: set by snapshot_builder for agent-labeled Epics (title/label
    # heuristic or presence of sub-issues). Used by state machine to avoid spawning
    # work on Epics and by diagnostics.
    is_epic: bool = False


@dataclass
class AFKContext:
    """Broader, cross-cutting context for a decision cycle."""
    session: dict[str, Any] = field(default_factory=dict)           # relevant parts of .grok/afk-session.json
    checklist_versions: dict[str, str] = field(default_factory=dict)  # e.g. {"implementor": "v1", ...}
    engine_config: dict[str, Any] = field(default_factory=dict)
    # Add other global/session-level data as needed


# =============================================================================
# High-level Actions (Output of decide_next_action)
# =============================================================================

@dataclass
class SpawnImplementor:
    issue: int
    reason: str = ""
    checklist_ref: str = ""
    snapshot: IssueSnapshot | None = None


@dataclass
class SpawnReviewer:
    issue: int
    reason: str = ""
    checklist_ref: str = ""
    snapshot: IssueSnapshot | None = None


@dataclass
class ApplyLabelChanges:
    issue: int
    add: list[str] = field(default_factory=list)
    remove: list[str] = field(default_factory=list)


@dataclass
class RequestWorktreeCleanup:
    """Request to clean up the AFK worktree for an issue (engine-owned lifecycle policy per #22).

    Can carry associated label changes so that a single Action from the state machine
    can drive both the cleanup and the final state transition (approval/retry/escalation).
    This keeps translation simple and policy centralized in the state machine.
    """
    issue: int
    reason: str = ""
    add: list[str] = field(default_factory=list)
    remove: list[str] = field(default_factory=list)


@dataclass
class EscalateToHuman:
    issue: int
    reason: str = ""


@dataclass
class NoOp:
    reason: str = ""


Action = (
    SpawnImplementor
    | SpawnReviewer
    | ApplyLabelChanges
    | RequestWorktreeCleanup
    | EscalateToHuman
    | NoOp
)


# =============================================================================
# Concrete Plan Items (Output of translation layer)
# =============================================================================

@dataclass
class LabelChange:
    issue: int
    add: list[str] = field(default_factory=list)
    remove: list[str] = field(default_factory=list)


@dataclass
class WorktreeAction:
    issue: int
    action: Literal["create", "cleanup"]
    reason: str = ""


@dataclass
class SessionUpdate:
    updates: dict[str, Any] = field(default_factory=dict)


@dataclass
class SpawnRequest:
    """Rich, self-contained request that the thin runner can execute directly."""
    issue: int
    role: Literal["implementor", "reviewer"]
    worktree: str
    branch: str
    prompt: str
    reason: str = ""


PlanItem = LabelChange | SpawnRequest | WorktreeAction | SessionUpdate


@dataclass
class AFKPlan:
    """The complete, concrete plan produced by the translation layer."""
    plan_items: list[PlanItem] = field(default_factory=list)


# =============================================================================
# Final Result returned to the thin runner / orchestrator
# =============================================================================

@dataclass
class AFKCycleResult:
    """Rich result returned by the high-level engine entrypoint."""
    spawn_requests: list[SpawnRequest] = field(default_factory=list)
    plan: AFKPlan | None = None
    applied_changes: list[Any] = field(default_factory=list)   # detailed success/failure info
    notes: list[str] = field(default_factory=list)
    no_more_work: bool = False
    errors: list[Any] = field(default_factory=list)