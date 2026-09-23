"""Next-action derivation for Janus goal execution planning.

.. deprecated::
    This module is a backward-compatible re-export shim. The next-action
    engine has been consolidated into the domain layer at
    :mod:`janus.domain.planning`. New code should import from the
    domain layer directly.

    The engine considers task ordering, milestone state, and goal structure.

    Task-to-milestone membership is derived dynamically (not stored) per
    ADR-003 Q3: a shared task "belongs to" whichever non-terminal milestone
    is earliest in ``order``. As earlier milestones complete or are skipped,
    the task becomes eligible for the next non-terminal milestone that
    contains it.

    When a Goal has Projects (see design spec:
    docs/design/goal_milestone_project_task_hierarchy.md), the engine traverses
    the full hierarchy:

        Goal -> Current Milestone -> Current Project -> Open Task

    Project assignment always overrides dynamic milestone derivation (I6).
    Goals without Projects retain the legacy R1-R5 behavior unchanged.

    See docs/design/execution_planning.md for the full rule table.
"""

from janus.domain.planning import (
    NextAction,
    _assigned_project_tasks,
    _find_project_for_milestone,
    _first_active_milestone,
    _first_non_terminal_milestone,
    _get_project_by_title,
    _open_task_titles,
    derive_milestone_task_set,
    derive_milestone_tasks,
    derive_next_action,
    milestone_objs,
    project_objs,
)

# Private aliases preserved for backward compatibility.
_milestone_objs = milestone_objs
_project_objs = project_objs

__all__ = [
    "NextAction",
    "derive_next_action",
    "derive_milestone_tasks",
    "derive_milestone_task_set",
    "milestone_objs",
    "project_objs",
    "_milestone_objs",
    "_project_objs",
    "derive_milestone_tasks",
    "derive_milestone_task_set",
]
