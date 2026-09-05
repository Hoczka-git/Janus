"""Shared pytest fixtures for the Janus test suite.

The ``goal_stalled`` signal in ``janus.services.attention`` requires at least
one related task title to appear in ``all_task_titles`` (loaded from
``data/tasks.md``) before it can fire.  Since ``data/tasks.md`` is gitignored
and absent from the worktree (commit e843b0e), tests that exercise the stall
path need a controlled source of task titles to remain self-contained and
reproducible.

This autouse fixture monkeypatches ``_load_all_task_titles`` to return a fixed
set containing "Prepare training plan" — mirroring the content of the real
``data/tasks.md`` before it was gitignored — so the goal-stagnation tests
behave as if the production file existed with that content.
"""

import pytest


@pytest.fixture(autouse=True)
def _tasks_md_for_stall(monkeypatch):
    """Provide a non-empty all_task_titles so the goal_stalled signal can fire.

    Mirrors the real content pre-e843b0e: "Prepare training plan" as a
    completed task, which several goal-stagnation tests reference as a
    related task that exists but is fully done.
    """
    monkeypatch.setattr(
        "janus.services.attention._load_all_task_titles",
        lambda _path: {"Prepare training plan"},
    )
