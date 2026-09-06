"""Bidirectional linking between research artifacts and goals.

Since research artifacts currently have no persistence layer (markdown
persistence is a follow-up), this service accepts in-memory artifacts
and operates on the goals persistence layer directly. The artifact
side is updated in-memory and returned to the caller, who is
responsible for persistence (or receives the updated artifact).

For the MVP, the linking service provides:
- Bidirectional sync helpers (artifact <-> goal)
- Query helpers (which artifacts point at a goal, which goals an artifact points at)

When artifact persistence is added, these functions can be made fully
self-contained (load → modify → save on both sides).
"""

import logging

from janus._log import emit
from janus.integrations.markdown_goals import load_goals, update_goal
from janus.models.goal import Goal
from janus.models.research_artifact import ResearchArtifact

logger = logging.getLogger(__name__)


def link_artifact_to_goal(
    artifact_title: str,
    goal_title: str,
    artifact: ResearchArtifact | None = None,
) -> ResearchArtifact | None:
    """Add a bidirectional link: artifact -> goal and goal -> artifact.

    Updates the Goal in persistence (markdown_goals) and returns the
    updated artifact (in-memory). If ``artifact`` is provided, its
    ``linked_goal_titles`` is updated on the returned copy; if
    ``artifact`` is None, the artifact side is not updated (the caller
    is responsible for passing it in when they have an in-memory instance).

    No-op if the link already exists on both sides.

    Raises ValueError if the goal does not exist.
    """
    # Update goal side (persistent)
    goal = _get_goal_or_raise(goal_title)
    if artifact_title not in goal.research_artifact_titles:
        goal.research_artifact_titles.append(artifact_title)
        update_goal(goal)
        emit(logger, "service.artifact_linking.linked",
             trace_id=None, span_id="link_artifact_to_goal",
             goal_title=goal_title, artifact_title=artifact_title,
             message=f"Linked artifact '{artifact_title}' to goal '{goal_title}'")

    # Update artifact side (in-memory, caller owns persistence)
    if artifact is not None:
        if artifact_title != artifact.title:
            raise ValueError(
                f"Artifact title mismatch: {artifact_title!r} != {artifact.title!r}"
            )
        if goal_title not in artifact.linked_goal_titles:
            artifact.linked_goal_titles.append(goal_title)
        return artifact

    return None


def unlink_artifact_from_goal(
    artifact_title: str,
    goal_title: str,
    artifact: ResearchArtifact | None = None,
) -> ResearchArtifact | None:
    """Remove a bidirectional link. No-op if the link does not exist.

    Removes from the Goal in persistence and returns the updated artifact
    (in-memory) if one was provided.
    """
    goal = _get_goal_or_raise(goal_title)
    if artifact_title in goal.research_artifact_titles:
        goal.research_artifact_titles.remove(artifact_title)
        update_goal(goal)
        emit(logger, "service.artifact_linking.unlinked",
             trace_id=None, span_id="unlink_artifact_from_goal",
             goal_title=goal_title, artifact_title=artifact_title,
             message=f"Unlinked artifact '{artifact_title}' from goal '{goal_title}'")

    if artifact is not None:
        if goal_title in artifact.linked_goal_titles:
            artifact.linked_goal_titles.remove(goal_title)
        return artifact

    return None


def get_artifacts_for_goal(goal_title: str) -> list[str]:
    """Return the list of artifact titles linked to this goal.

    Since artifacts are not persisted yet, this returns the title list
    from the goal's ``research_artifact_titles`` field. When artifact
    persistence is added, this can resolve to full ResearchArtifact objects.
    """
    goal = _get_goal_or_raise(goal_title)
    return list(goal.research_artifact_titles)


def get_goals_for_artifact(artifact_title: str) -> list[str]:
    """Return the list of goal titles linked to this artifact.

    Since artifacts are not persisted yet, this scans all goals and
    returns those that reference the given artifact title in their
    ``research_artifact_titles`` field.
    """
    goals = load_goals()
    return [
        g.title for g in goals
        if artifact_title in g.research_artifact_titles
    ]


def _get_goal_or_raise(goal_title: str) -> Goal:
    """Load a goal by title, raising ValueError if not found."""
    goals = load_goals()
    matches = [g for g in goals if g.title == goal_title]
    if not matches:
        raise ValueError(f"Goal not found: {goal_title!r}")
    if len(matches) > 1:
        raise ValueError(f"Multiple goals found with title {goal_title!r}")
    return matches[0]
