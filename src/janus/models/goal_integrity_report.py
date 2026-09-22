"""Goal integrity audit domain models for Janus.

``GoalIntegrityReport`` and ``GoalIntegrityIssue`` represent the
deterministic health-check result produced by the Goal Integrity Audit
(see ``docs/design/goal_integrity_audit.md`` §4, §5, §6, §10).

These are read-only value objects. The audit service
(``janus.services.goal_integrity``) constructs them and the CLI
(``janus.goals_cli``) renders them.
"""
from dataclasses import dataclass, field
from datetime import datetime


# ── Severity levels (spec §5) ──────────────────────────────────────────────────
# Ordered by severity: error > warning > info.
_SEVERITY_ORDER = {"error": 3, "warning": 2, "info": 1}


@dataclass
class GoalIntegrityIssue:
    """A single integrity issue found during the audit.

    Attributes:
        code: Deterministic issue code (spec §6). One of:
            ``GOAL_WITHOUT_TASKS``, ``UNKNOWN_GOAL_REFERENCE``,
            ``INVALID_METRIC``, ``STALE_ACTIVITY``.
        severity: ``error`` | ``warning`` | ``info``.
        goal_id: The goal title affected, or ``None`` if not goal-specific.
        task_id: The task title affected (for UNKNOWN_GOAL_REFERENCE),
            or ``None`` if not task-specific.
        message: Human-readable explanation.
        details: Optional structured diagnostic payload.
    """
    code: str
    severity: str
    goal_id: str | None = None
    task_id: str | None = None
    message: str = ""
    details: dict | None = None

    def to_dict(self) -> dict:
        """Serialize to a JSON-friendly dict (spec §10)."""
        return {
            "code": self.code,
            "severity": self.severity,
            "goal_id": self.goal_id,
            "task_id": self.task_id,
            "message": self.message,
            "details": self.details or {},
        }


@dataclass
class GoalIntegrityReport:
    """The complete result of a Goal Integrity Audit (spec §4).

    Attributes:
        goals_checked: Number of goals inspected.
        tasks_checked: Number of tasks inspected.
        issues: List of ``GoalIntegrityIssue`` objects.
        healthy_checks: List of info-severity issues describing healthy
            states (goals with valid task linkage, recent activity, etc.).
        evaluated_at: When the audit was run.
    """
    goals_checked: int = 0
    tasks_checked: int = 0
    issues: list[GoalIntegrityIssue] = field(default_factory=list)
    healthy_checks: list[GoalIntegrityIssue] = field(default_factory=list)
    evaluated_at: datetime | None = None

    # ── Derived counts ───────────────────────────────────────────────────────

    @property
    def error_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == "error")

    @property
    def warning_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == "warning")

    @property
    def info_count(self) -> int:
        """Info count includes both warning-level healthy checks and
        info-severity issues (healthy observations)."""
        return len(self.healthy_checks) + sum(
            1 for i in self.issues if i.severity == "info"
        )

    @property
    def has_errors(self) -> bool:
        return self.error_count > 0

    def to_dict(self) -> dict:
        """Serialize to a JSON-friendly dict (spec §10)."""
        from dataclasses import asdict
        return {
            "goals_checked": self.goals_checked,
            "tasks_checked": self.tasks_checked,
            "issues": [i.to_dict() for i in self.issues],
            "healthy_checks": [i.to_dict() for i in self.healthy_checks],
            "error_count": self.error_count,
            "warning_count": self.warning_count,
            "info_count": self.info_count,
            "evaluated_at": (
                self.evaluated_at.isoformat()
                if self.evaluated_at else None
            ),
        }
