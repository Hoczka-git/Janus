"""Structured remediation action models for Janus (spec §3.2, §5.1, §4.1).

These dataclasses are the *structured* remediation surface produced by the
remediation engine (``services/remediation.py``). They coexist with — and do
not replace — the advisory remediation text produced by
``services/recommended_actions.py`` (the advisory ``RemediationAction`` in
``models/recommended_action.py`` with its ``action: str`` field).

Where the advisory layer answers "what should I do about this?" in prose,
this structured layer answers "what *operation* should run, with what
typed parameters, and what preconditions/effects attach to it?" so that an
operator (CLI, Hermes, policy gate) can programmatically confirm, queue,
or auto-apply actions.

Design reference: ``docs/design/goal_remediation_engine_spec.md``.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


# ── Action type taxonomy (spec §3.1) ──────────────────────────────────────────
# A closed enum of structured operation types. Each maps to a parameter shape
# defined in §5.2. The enum is the contract implementers build against; the
# parameter bag lets new specific actions avoid enum churn.

REASSIGN = "reassign"
SPLIT = "split"
ESCALATE = "escalate"
ARCHIVE = "archive"
NOTIFY = "notify"
TASK = "task"
RESCHEDULE = "reschedule"
MEASURE = "measure"
INVESTIGATE = "investigate"
NONE = "none"

# Closed set of all valid action types (spec §3.1).
ALL_ACTION_TYPES = (
    REASSIGN,
    SPLIT,
    ESCALATE,
    ARCHIVE,
    NOTIFY,
    TASK,
    RESCHEDULE,
    MEASURE,
    INVESTIGATE,
    NONE,
)

# Actions that are purely informational and do not require operator
# confirmation before being surfaced (spec §8 / §3.2 requires_confirmation).
_INFORMATIVE_TYPES = frozenset({INVESTIGATE, NOTIFY, NONE})


@dataclass(frozen=True)
class RemediationAction:
    """A structured remediation operation suggested for a goal (spec §3.2).

    This is a **suggestion**, not an executed operation. An operator (CLI,
    Hermes, policy) confirms or rejects it before any side effects occur.

    Attributes:
        goal_title: The goal this action applies to.
        action_type: One of the §3.1 taxonomy values.
        suggestion_id: Stable id for dedup / audit
            (goal_title + action_type + hashed parameter key).
        health_state: ``healthy`` | ``watch`` | ``stalled`` | ``completed``
            | ``None``.
        dominant_signal: The signal identifier, if any.
        dominant_signal_score: The signal score, if any.
        dominant_signal_reason: Human-readable diagnosis.
        structural_issues: Integrity issue codes that apply, if any.
        parameters: Typed-per-action_type parameter bag (spec §5.2).
        priority: Higher = more urgent; reuses remediation-rule priorities
            as a starting point (spec §3.3).
        generated_at: When this suggestion was produced.
        requires_confirmation: False for informational actions
            (``investigate``, ``notify``, ``none``) (spec §8).
    """

    goal_title: str
    action_type: str
    suggestion_id: str
    # ── Diagnosis ─────────────────────────────────────────────────────
    health_state: str
    dominant_signal: str | None
    dominant_signal_score: int
    dominant_signal_reason: str
    structural_issues: list[str] = field(default_factory=list)
    # ── Action parameters (typed per action_type) ─────────────────────
    parameters: dict[str, Any] = field(default_factory=dict)
    # ── Priority / urgency ────────────────────────────────────────────
    priority: int = 0
    # ── Metadata ──────────────────────────────────────────────────────
    generated_at: datetime | None = None
    requires_confirmation: bool = True

    def __post_init__(self) -> None:
        if self.action_type not in ALL_ACTION_TYPES:
            raise ValueError(
                f"Invalid action_type: {self.action_type!r}. "
                f"Allowed: {', '.join(ALL_ACTION_TYPES)}"
            )
        if not self.requires_confirmation and self.action_type not in (
            _INFORMATIVE_TYPES
        ):
            raise ValueError(
                f"requires_confirmation=False is only valid for "
                f"informational action types {_INFORMATIVE_TYPES}, "
                f"got action_type={self.action_type!r}"
            )
        # Informational types must not require confirmation.
        if self.action_type in _INFORMATIVE_TYPES:
            object.__setattr__(self, "requires_confirmation", False)


@dataclass
class RemediationSummary:
    """Aggregate roll-up of remediation suggestions (spec §5.1)."""

    goals_with_actions: int = 0
    by_type: dict[str, int] = field(default_factory=dict)
    by_health_state: dict[str, int] = field(default_factory=dict)
    stalled_goal_titles: list[str] = field(default_factory=list)
    overdue_goal_titles: list[str] = field(default_factory=list)
    needs_confirmation_count: int = 0
    highest_priority_action: RemediationAction | None = None


@dataclass
class RemediationSuggestions:
    """All structured remediation suggestions for a goal portfolio (spec §5.1).

    Attributes:
        generated_at: When the suggestions were produced.
        per_goal: All suggested actions across goals (one primary per
            active goal, plus any secondary actions).
        summary: Aggregate roll-up (spec §5.1 ``RemediationSummary``).
    """

    generated_at: datetime
    per_goal: list[RemediationAction] = field(default_factory=list)
    summary: RemediationSummary = field(default_factory=RemediationSummary)
