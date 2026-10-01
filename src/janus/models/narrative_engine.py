"""Narrative Explanation Engine for Janus — Phase B (Evidence & Audit).

The narrative explanation engine provides "how Janus knows progress
occurred" — it generates human-readable explanations of progress
based on evidence, outcomes, and verification results.

Spec: ``docs/janus-agency-first-development-phase.md`` §13 Phase B.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


class ExplanationType(StrEnum):
    """Type of narrative explanation."""

    PROGRESS = "progress"
    """Explanation of how progress occurred."""

    REGRESSION = "regression"
    """Explanation of why regression occurred."""

    STALL = "stall"
    """Explanation of why progress stalled."""

    COMPLETION = "completion"
    """Explanation of how a task or goal was completed."""

    OUTCOME = "outcome"
    """Explanation of an outcome."""


@dataclass
class NarrativeExplanation:
    """A narrative explanation of progress or outcome.

    Attributes:
        id: Stable identity for the explanation.
        explanation_type: Type of explanation.
        subject: What the explanation is about (e.g., task title, goal title).
        explanation: The human-readable explanation.
        evidence_ids: IDs of evidence that support this explanation.
        outcome_ids: IDs of outcomes that support this explanation.
        verification_ids: IDs of verifications that support this explanation.
        created_at: When the explanation was generated.
        confidence: Confidence level of the explanation (0.0 to 1.0).
    """

    id: str
    explanation_type: ExplanationType
    subject: str
    explanation: str = ""
    evidence_ids: list[str] = field(default_factory=list)
    outcome_ids: list[str] = field(default_factory=list)
    verification_ids: list[str] = field(default_factory=list)
    created_at: datetime | None = None
    confidence: float = 0.5

    def __post_init__(self) -> None:
        if not self.id or not self.id.strip():
            raise ValueError("NarrativeExplanation.id must not be empty")
        if not self.subject or not self.subject.strip():
            raise ValueError("NarrativeExplanation.subject must not be empty")
        if not isinstance(self.explanation_type, ExplanationType):
            raise ValueError(
                f"Invalid explanation_type: {self.explanation_type!r}. "
                f"Allowed: {', '.join(t.value for t in ExplanationType)}"
            )
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(
                f"Invalid confidence: {self.confidence!r}. "
                f"Must be between 0.0 and 1.0"
            )
        if self.created_at is None:
            self.created_at = datetime.now()
        if self.evidence_ids is None:
            self.evidence_ids = []
        if self.outcome_ids is None:
            self.outcome_ids = []
        if self.verification_ids is None:
            self.verification_ids = []

    def to_dict(self) -> dict:
        """Serialize to a JSON-friendly dict."""
        from dataclasses import asdict

        raw = asdict(self)
        raw["explanation_type"] = self.explanation_type.value
        if self.created_at and hasattr(self.created_at, "isoformat"):
            raw["created_at"] = self.created_at.isoformat()
        return raw


class NarrativeEngine:
    """Engine for generating narrative explanations.

    This engine generates human-readable explanations of progress
    based on evidence, outcomes, and verification results.
    """

    def __init__(self) -> None:
        """Initialize the narrative engine."""
        self._explanations: list[NarrativeExplanation] = []

    def add_explanation(self, explanation: NarrativeExplanation) -> None:
        """Add a narrative explanation."""
        self._explanations.append(explanation)

    def get_explanations(
        self,
        subject: str | None = None,
        explanation_type: ExplanationType | None = None,
    ) -> list[NarrativeExplanation]:
        """Get explanations, optionally filtered by subject and type."""
        result = self._explanations
        if subject:
            result = [e for e in result if e.subject == subject]
        if explanation_type:
            result = [e for e in result if e.explanation_type == explanation_type]
        return result

    def generate_progress_explanation(
        self,
        subject: str,
        evidence_ids: list[str],
        outcome_ids: list[str],
        verification_ids: list[str],
    ) -> NarrativeExplanation:
        """Generate a progress explanation.

        Args:
            subject: What the explanation is about.
            evidence_ids: IDs of evidence that support this explanation.
            outcome_ids: IDs of outcomes that support this explanation.
            verification_ids: IDs of verifications that support this explanation.

        Returns:
            A narrative explanation of progress.
        """
        explanation = NarrativeExplanation(
            id=f"narrative-{len(self._explanations) + 1}",
            explanation_type=ExplanationType.PROGRESS,
            subject=subject,
            explanation=self._build_explanation_text(
                subject, evidence_ids, outcome_ids, verification_ids
            ),
            evidence_ids=evidence_ids,
            outcome_ids=outcome_ids,
            verification_ids=verification_ids,
            confidence=self._compute_confidence(
                evidence_ids, outcome_ids, verification_ids
            ),
        )
        self._explanations.append(explanation)
        return explanation

    def _build_explanation_text(
        self,
        subject: str,
        evidence_ids: list[str],
        outcome_ids: list[str],
        verification_ids: list[str],
    ) -> str:
        """Build the explanation text."""
        parts = [f"Progress on '{subject}' is supported by:"]
        if evidence_ids:
            parts.append(f"  - {len(evidence_ids)} evidence item(s)")
        if outcome_ids:
            parts.append(f"  - {len(outcome_ids)} outcome record(s)")
        if verification_ids:
            parts.append(f"  - {len(verification_ids)} verification result(s)")
        return "\n".join(parts)

    def _compute_confidence(
        self,
        evidence_ids: list[str],
        outcome_ids: list[str],
        verification_ids: list[str],
    ) -> float:
        """Compute confidence based on available evidence."""
        total = len(evidence_ids) + len(outcome_ids) + len(verification_ids)
        if total == 0:
            return 0.0
        # More evidence = higher confidence, capped at 1.0
        return min(1.0, total / 10.0)
