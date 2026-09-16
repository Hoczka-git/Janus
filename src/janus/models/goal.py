from dataclasses import dataclass, field
from janus.models.project import Project


@dataclass
class Goal:
    # Required
    title: str                              # persistence identity, immutable in MVP

    # Optional descriptive
    description: str = ""
    status: str = "active"                  # active | completed | inactive
    deadline: str | None = None             # ISO date YYYY-MM-DD

    # Optional metric fields (7 new)
    metric_name: str | None = None          # e.g. "Body fat %"
    metric_unit: str | None = None          # e.g. "%", "PLN", "kg"
    start_value: float | None = None        # baseline
    current_value: float | None = None      # latest
    target_value: float | None = None       # desired outcome
    direction: str | None = None            # "increase" | "decrease"

    # Task relationship
    related_tasks: list[str] = None         # supporting task titles (deduped, ordered)

    # Execution planning (optional)
    # Stored as list[dict] (not list[Milestone]) to avoid import cycle and
    # keep markdown serialization simple. The service layer constructs
    # Milestone objects from the dicts when needed.
    milestones: list[dict] | None = None     # list of milestone dicts (see spec)

# Projects: explicit task assignment within milestones.
    # Stored as list[dict] internally for markdown serialization; the service
    # layer constructs Project objects from the dicts when needed.
    # The domain model Goal.projects exposes list[Project] (via the service).
    projects: list[dict] | None = None     # list of project dicts

    # Measurement requirements (optional, see design §3.1)
    # Stored as list[dict] for the same rationale as milestones. Each dict:
    #   {"metric": str, "unit": str, "frequency": str, "preferred_time": str,
    #    "interval_days": int}
    measurement_requirements: list[dict] | None = None
    research_artifact_titles: list[str] | None = field(default_factory=list)
    decision_numbers: list[str] = field(default_factory=list)  # ADR numbers that shaped this goal
    followup_ids: list[str] = field(default_factory=list)  # follow-up IDs linked to this goal
    inactivity_window_days: int | None = None  # per-goal override of system default (design §6.3)

    # Execution-feedback activity log (design §4.5 / §7). Each entry is a
    # plain dict so that it round-trips through markdown_goals without a
    # dedicated model import cycle. The service layer constructs
    # RecentActivityEntry objects when richer access is needed.
    # List of dicts: {task_id, summary, completed_at, changed_files,
    #                  tests_passed, pr_url}
    recent_activity: list[dict] | None = None

    # Skill tracking (MVP — evidence-based skill development, see design §4.1)
    skill_name: str | None = None
        # Human-readable skill label, e.g. "Python", "ML system design",
        # "technical writing". A goal develops one primary skill.
        # None = no skill tracking for this goal.

    skill_evidence: list[dict] | None = None
        # Filtered/projected view of recent_activity for tasks that
        # practiced this skill. Each dict has the same shape as
        # recent_activity entries:
        #   {task_id, summary, completed_at, changed_files,
        #    tests_passed, pr_url}
        # Computed on demand at first; persisted if query performance
        # requires it.

    def __post_init__(self):
        if self.related_tasks is None:
            self.related_tasks = []
        # Dedup preserving order
        self.related_tasks = self._dedup_related_tasks(self.related_tasks)
        if self.milestones is None:
            self.milestones = []
        if self.projects is None:
            self.projects = []
        if self.measurement_requirements is None:
            self.measurement_requirements = []
        if self.research_artifact_titles is None:
            self.research_artifact_titles = []
        self.research_artifact_titles = self._dedup_related_tasks(self.research_artifact_titles)
        if self.recent_activity is None:
            self.recent_activity = []
        if self.skill_evidence is None:
            self.skill_evidence = []
        if self.decision_numbers is None:
            self.decision_numbers = []
        self.decision_numbers = self._dedup_related_tasks(self.decision_numbers)
        if self.followup_ids is None:
            self.followup_ids = []
        self.followup_ids = self._dedup_related_tasks(self.followup_ids)
        for t in self.research_artifact_titles:
            if not isinstance(t, str):
                raise ValueError(
                    f"Goal.research_artifact_titles must contain str instances, "
                    f"got {type(t).__name__}"
                )
        if self.skill_name is not None:
            if not isinstance(self.skill_name, str) or not self.skill_name.strip():
                raise ValueError(
                    "skill_name must be a non-empty string if provided"
                )
            self.skill_name = self.skill_name.strip()
        if self.status not in ("active", "completed", "inactive"):
            raise ValueError(
                f"Invalid goal status: {self.status!r}. "
                f"Allowed: active, completed, inactive"
            )
        if self.direction is not None and self.direction not in ("increase", "decrease"):
            raise ValueError(
                f"Invalid direction: {self.direction!r}. "
                f"Allowed: increase, decrease"
            )
        if not self.title or not self.title.strip():
            raise ValueError("Goal title must not be empty")

    @staticmethod
    def _dedup_related_tasks(tasks: list[str]) -> list[str]:
        """Deduplicate preserving order."""
        seen = set()
        result = []
        for t in tasks:
            if t not in seen:
                seen.add(t)
                result.append(t)
        return result
