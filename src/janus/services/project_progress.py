"""Project progress calculation — single source of truth for Project task completion.

Weekly Review delegates to ``compute_project_progress`` here rather than
duplicating Project traversal logic.

A Project's progress is:
    completed_project_tasks / total_project_tasks

where the task completion state comes from the Goal's completed_task_titles set.
"""

from janus.models.goal import Goal
from janus.models.project import Project
from janus.models.project_progress import ProjectProgress


def compute_project_progress(
    project: Project, completed_task_titles: set[str],
) -> ProjectProgress:
    """Compute progress for a Project.

    Progress is measured against the Project's related_tasks: how many of
    those tasks are in the completed set.

    Args:
        project: The Project domain object.
        completed_task_titles: Set of currently-completed task titles.

    Returns:
        A ProjectProgress with completed/total counts.
    """
    total = len(project.related_tasks)
    completed = sum(1 for t in project.related_tasks if t in completed_task_titles)
    return ProjectProgress(
        project_title=project.title,
        milestone_title=project.milestone_title,
        status=project.status,
        completed_tasks=completed,
        total_tasks=total,
    )


def compute_all_project_progress(
    goal: Goal, completed_task_titles: set[str],
) -> list[ProjectProgress]:
    """Compute progress for all Projects in a Goal, ordered by milestone then project order.

    Projects with no related_tasks report total_tasks=0, completed_tasks=0.
    """
    from janus.services.projects import get_projects_for_goal
    projs = get_projects_for_goal(goal.title)
    return [compute_project_progress(p, completed_task_titles) for p in projs]
