"""Project progress data model for Janus weekly review."""

from dataclasses import dataclass


@dataclass
class ProjectProgress:
    """Progress summary for a single Project within a Goal.

    ``completed_tasks`` and ``total_tasks`` are derived from the Project's
    related_tasks list and the Goal's completed task set.
    """

    project_title: str
    milestone_title: str
    status: str
    completed_tasks: int
    total_tasks: int
