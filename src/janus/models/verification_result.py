"""VerificationResult model for Janus — Phase B (Evidence & Audit).

A ``VerificationResult`` is a standalone domain concept that captures
the outcome of a verification check. Unlike the ``CheckResult`` in
``verification.py`` (which is a mechanical gate result), a
``VerificationResult`` is a semantic record of what was verified,
how, and what the result means for the overall system state.

Spec: ``docs/janus-agency-first-development-phase.md`` §13 Phase B.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


class VerificationStatus(StrEnum):
    """Classification of a verification result."""

    PASS = "pass"
    """The verification passed."""

    FAIL = "fail"
    """The verification failed."""

    SKIP = "skip"
    """The verification was skipped."""

    ERROR = "error"
    """The verification could not be completed due to an error."""


@dataclass
class VerificationResult:
    """A standalone record of a verification outcome.

    This is a domain concept that captures the semantic result of a
    verification check, independent of the mechanical gate result.
    It can be linked to tasks, goals, or contracts.

    Attributes:
        id: Stable identity for the verification result.
        check_name: Name of the verification check.
        status: Classification of the verification result.
        expected: What was expected.
        actual: What was actually observed.
        severity: Severity of the result (info, warning, error).
        linked_task_title: Optional task this verification relates to.
        linked_goal_title: Optional goal this verification relates to.
        linked_contract: Optional contract this verification relates to.
        created_at: When the verification was performed.
        details: Additional details about the verification.
    """

    id: str
    check_name: str
    status: VerificationStatus = VerificationStatus.PASS
    expected: str = ""
    actual: str = ""
    severity: str = "info"  # info | warning | error
    linked_task_title: str = ""
    linked_goal_title: str = ""
    linked_contract: str = ""
    created_at: datetime | None = None
    details: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.id or not self.id.strip():
            raise ValueError("VerificationResult.id must not be empty")
        if not self.check_name or not self.check_name.strip():
            raise ValueError("VerificationResult.check_name must not be empty")
        if not isinstance(self.status, VerificationStatus):
            raise ValueError(
                f"Invalid status: {self.status!r}. "
                f"Allowed: {', '.join(s.value for s in VerificationStatus)}"
            )
        if self.severity not in ("info", "warning", "error"):
            raise ValueError(
                f"Invalid severity: {self.severity!r}. "
                f"Allowed: info, warning, error"
            )
        if self.created_at is None:
            self.created_at = datetime.now()
        if self.details is None:
            self.details = {}

    def to_dict(self) -> dict:
        """Serialize to a JSON-friendly dict."""
        from dataclasses import asdict

        raw = asdict(self)
        raw["status"] = self.status.value
        if self.created_at and hasattr(self.created_at, "isoformat"):
            raw["created_at"] = self.created_at.isoformat()
        return raw
