"""Recent activity entry model for Janus goals.

A ``RecentActivityEntry`` records a single piece of evidence that a
Hermes Kanban task contributed to a goal.  Entries are stored as a list
of dicts on the ``Goal`` model (mirrors the milestones/projects pattern —
plain dicts for simple markdown serialization, the service layer
constructs objects when needed).

Design reference:
    docs/janus_hermes_execution_feedback_handoff_design.md §4.5

Evidence flow (design §4.5):

| Evidence field   | Source                          | Janus destination                 |
|------------------|---------------------------------|-----------------------------------|
| ``task_id``      | Kanban task ID                  | Audit trail in domain object      |
| ``summary``      | ``kanban_complete()`` summary   | Activity log / recent activity    |
| ``completed_at`` | Timestamp at completion         | ``recent_activity`` timestamp     |
| ``changed_files``| Worker reports / workspace diff | Linked to domain object           |
| ``tests_passed`` | Worker metadata / verification  | Confidence signal for domain obj  |
| ``pr_url``       | Integration gate result         | Links domain object to proof      |
"""

from dataclasses import dataclass, field


@dataclass
class RecentActivityEntry:
    """A single activity/evidence record appended to a goal's recent_activity.

    Attributes:
        task_id: The Hermes Kanban task ID that drove this activity.
        summary: Human-readable summary from ``kanban_complete()``.
        completed_at: ISO timestamp string marking when the activity occurred.
        changed_files: Files touched by the completing task (best-effort).
        tests_passed: Whether the completing task's tests passed.
        pr_url: URL of the integration PR, if the task had ``integration_required``.
    """

    task_id: str
    summary: str
    completed_at: str
    changed_files: list[str] = field(default_factory=list)
    tests_passed: bool | None = None
    pr_url: str | None = None

    def to_dict(self) -> dict:
        """Serialize to a plain dict for markdown persistence."""
        d = {
            "task_id": self.task_id,
            "summary": self.summary,
            "completed_at": self.completed_at,
            "changed_files": list(self.changed_files),
        }
        if self.tests_passed is not None:
            d["tests_passed"] = self.tests_passed
        if self.pr_url is not None:
            d["pr_url"] = self.pr_url
        return d

    @classmethod
    def from_dict(cls, data: dict) -> "RecentActivityEntry":
        """Construct from a persisted dict, tolerating missing keys."""
        return cls(
            task_id=data.get("task_id", ""),
            summary=data.get("summary", ""),
            completed_at=data.get("completed_at", ""),
            changed_files=list(data.get("changed_files", []) or []),
            tests_passed=data.get("tests_passed"),
            pr_url=data.get("pr_url"),
        )
