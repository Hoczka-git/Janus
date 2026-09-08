"""Tests for the Project domain model.

Covers the Project dataclass: field defaults, status validation,
non-empty title, milestone_title required, related_tasks deduplication,
and terminal status semantics.
"""

import pytest

from janus.models.project import Project


class TestProjectModel:
    def test_basic_construction(self):
        p = Project(title="P1", milestone_title="M1")
        assert p.title == "P1"
        assert p.milestone_title == "M1"
        assert p.description == ""
        assert p.deadline is None
        assert p.status == "open"
        assert p.order == 0
        assert p.related_tasks == []

    def test_all_fields(self):
        p = Project(
            title="P1",
            milestone_title="M1",
            description="A project",
            deadline="2026-10-31",
            status="active",
            order=2,
            related_tasks=["Task A", "Task B"],
        )
        assert p.status == "active"
        assert p.order == 2
        assert p.related_tasks == ["Task A", "Task B"]

    def test_empty_title_raises(self):
        with pytest.raises(ValueError, match="must not be empty"):
            Project(title="", milestone_title="M1")

    def test_whitespace_title_raises(self):
        with pytest.raises(ValueError, match="must not be empty"):
            Project(title="   ", milestone_title="M1")

    def test_empty_milestone_title_raises(self):
        with pytest.raises(ValueError, match="must not be empty"):
            Project(title="P1", milestone_title="")

    def test_invalid_status_raises(self):
        with pytest.raises(ValueError, match="Invalid project status"):
            Project(title="P1", milestone_title="M1", status="pending")

    def test_all_valid_statuses(self):
        for s in ("open", "active", "blocked", "completed", "skipped"):
            p = Project(title="P1", milestone_title="M1", status=s)
            assert p.status == s

    def test_related_tasks_dedup(self):
        p = Project(
            title="P1", milestone_title="M1",
            related_tasks=["Task A", "Task A", "Task B", "Task B"],
        )
        assert p.related_tasks == ["Task A", "Task B"]

    def test_related_tasks_preserves_order(self):
        p = Project(
            title="P1", milestone_title="M1",
            related_tasks=["Task C", "Task A", "Task B"],
        )
        assert p.related_tasks == ["Task C", "Task A", "Task B"]

    def test_default_related_tasks_not_shared(self):
        """Ensure default_factory list is not shared across instances."""
        p1 = Project(title="P1", milestone_title="M1")
        p2 = Project(title="P2", milestone_title="M1")
        p1.related_tasks.append("shared?")
        assert p2.related_tasks == []

    def test_is_terminal_completed(self):
        p = Project(title="P1", milestone_title="M1", status="completed")
        assert p.is_terminal is True

    def test_is_terminal_skipped(self):
        p = Project(title="P1", milestone_title="M1", status="skipped")
        assert p.is_terminal is True

    def test_is_terminal_open(self):
        p = Project(title="P1", milestone_title="M1", status="open")
        assert p.is_terminal is False

    def test_is_terminal_blocked(self):
        p = Project(title="P1", milestone_title="M1", status="blocked")
        assert p.is_terminal is False

    def test_is_terminal_static_method(self):
        assert Project.is_terminal_status("completed") is True
        assert Project.is_terminal_status("skipped") is True
        assert Project.is_terminal_status("open") is False
        assert Project.is_terminal_status("active") is False
        assert Project.is_terminal_status("blocked") is False

    def test_does_not_have_goal_title(self):
        """D1: Project must NOT store goal_title (I2: obtained via Milestone)."""
        p = Project(title="P1", milestone_title="M1")
        assert not hasattr(p, "goal_title")
