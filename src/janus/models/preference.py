"""Preference model for Janus — Phase C (Personal State).

A ``Preference`` represents a user preference that affects how Janus
should interact with the user or execute tasks. Preferences are tracked
as part of the PersonalState aggregate to provide a complete view of
the user's current state.

Spec: ``docs/janus-agency-first-development-phase.md`` §13 Phase C.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


class PreferenceCategory(StrEnum):
    """Category of preference."""

    COMMUNICATION = "communication"
    """How the user prefers to be notified or communicated with."""

    EXECUTION = "execution"
    """How the user prefers tasks to be executed."""

    PLANNING = "planning"
    """How the user prefers planning to be done."""

    REVIEW = "review"
    """How the user prefers reviews to be conducted."""

    OTHER = "other"
    """Any other category of preference."""


@dataclass
class Preference:
    """A user preference.

    Attributes:
        id: Stable identity for the preference.
        title: Human-readable description of the preference.
        category: Category of the preference.
        value: The preference value (e.g., "email", "morning", "weekly").
        priority: Priority of the preference (1-5, 5 = highest).
        active: Whether the preference is currently active.
        created_at: When the preference was created.
        notes: Additional notes about the preference.
    """

    id: str
    title: str
    category: PreferenceCategory = PreferenceCategory.OTHER
    value: str = ""
    priority: int = 3  # 1-5
    active: bool = True
    created_at: datetime | None = None
    notes: str = ""

    def __post_init__(self) -> None:
        if not self.id or not self.id.strip():
            raise ValueError("Preference.id must not be empty")
        if not self.title or not self.title.strip():
            raise ValueError("Preference.title must not be empty")
        if not isinstance(self.category, PreferenceCategory):
            raise ValueError(
                f"Invalid category: {self.category!r}. "
                f"Allowed: {', '.join(c.value for c in PreferenceCategory)}"
            )
        if self.priority not in (1, 2, 3, 4, 5):
            raise ValueError(
                f"Invalid priority: {self.priority!r}. "
                f"Allowed: 1, 2, 3, 4, 5"
            )
        if self.created_at is None:
            self.created_at = datetime.now()

    def to_dict(self) -> dict:
        """Serialize to a JSON-friendly dict."""
        from dataclasses import asdict

        raw = asdict(self)
        raw["category"] = self.category.value
        if self.created_at and hasattr(self.created_at, "isoformat"):
            raw["created_at"] = self.created_at.isoformat()
        return raw
