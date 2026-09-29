"""Tests for the Personal State model and builder service.

Covers:
- PersonalState model construction and serialization.
- PersonalStateBuilder construction from data files.
- Derived views (active goals, open tasks, blocked tasks, etc.).
- Fingerprint computation and change detection.
- Integrity issue detection.
- Strategic summary integration.
- Error handling for missing/malformed data.
"""

from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from janus.models.goal import Goal
from janus.models.task import Task, ALLOWED_STATES
from janus.models.follow_up import FollowUp
from janus.models.inbox import InboxItem
from janus.models.milestone import Milestone
from janus.models.project import Project
from janus.models.metric_snapshot import MetricSnapshot
from janus.models.recent_activity import RecentActivityEntry
from janus.models.goal_integrity_report import GoalIntegrityIssue
from janus.models.strategic_summary import StrategicSummary, PortfolioHealthCounts
from janus.models.personal_state import PersonalState
from janus.services.personal_state_builder import PersonalStateBuilder


FIXED_TODAY = date(2026, 9, 29)
FIXED_NOW = datetime(2026, 9, 29, 12, 0, 0, tzinfo=timezone.utc)


# ── Test helpers ──────────────────────────────────────────────────────────────


def _make_goal(
    title="Test goal",
    status="active",
    deadline=None,
    related_tasks=None,
    milestones=None,
    projects=None,
    metric_name=None,
    metric_unit=None,
    start_value=None,
    current_value=None,
    target_value=None,
    direction=None,
    measurement_requirements=None,
    inactivity_window_days=None,
    research_artifact_titles=None,
    decision_numbers=None,
    followup_ids=None,
    recent_activity=None,
    **kw,
):
    """Create a Goal with sensible defaults for tests."""
    return Goal(
        title=title,
        status=status,
        deadline=deadline,
        related_tasks=related_tasks or [],
        milestones=milestones or [],
        projects=projects or [],
        metric_name=metric_name,
        metric_unit=metric_unit,
        start_value=start_value,
        current_value=current_value,
        target_value=target_value,
        direction=direction,
        measurement_requirements=measurement_requirements or [],
        inactivity_window_days=inactivity_window_days,
        research_artifact_titles=research_artifact_titles or [],
        decision_numbers=decision_numbers or [],
        followup_ids=followup_ids or [],
        recent_activity=recent_activity or [],
        **kw,
    )


def _make_task(
    title="Test task",
    state="todo",
    priority=1,
    progress=None,
    extra_metadata=None,
):
    """Create a Task with sensible defaults for tests."""
    return Task(
        title=title,
        state=state,
        priority=priority,
        progress=progress,
        extra_metadata=extra_metadata or [],
    )


def _make_followup(
    id="fu-1",
    title="Test followup",
    state="pending",
    priority=1,
):
    """Create a FollowUp with sensible defaults for tests."""
    return FollowUp(
        id=id,
        title=title,
        state=state,
        priority=priority,
    )


def _make_inbox_item(
    id="ix-1",
    captured_text="Test inbox item",
    source="manual",
):
    """Create an InboxItem with sensible defaults for tests."""
    return InboxItem(
        id=id,
        captured_text=captured_text,
        source=source,
    )


def _make_milestone(
    title="Test milestone",
    goal_title="Test goal",
    status="open",
    order=0,
):
    """Create a Milestone with sensible defaults for tests."""
    return Milestone(
        title=title,
        goal_title=goal_title,
        status=status,
        order=order,
    )


def _make_project(
    title="Test project",
    milestone_title="Test milestone",
    status="open",
    order=0,
):
    """Create a Project with sensible defaults for tests."""
    return Project(
        title=title,
        milestone_title=milestone_title,
        status=status,
        order=order,
    )


def _make_metric_snapshot(
    goal_title="Test goal",
    metric_name="Weight",
    value=75.0,
    source="manual",
):
    """Create a MetricSnapshot with sensible defaults for tests."""
    return MetricSnapshot(
        timestamp=FIXED_NOW,
        goal_title=goal_title,
        metric_name=metric_name,
        value=value,
        source=source,
    )


def _make_recent_activity(
    task_id="t-1",
    summary="Completed task",
    completed_at="2026-09-29T10:00:00+00:00",
):
    """Create a RecentActivityEntry with sensible defaults for tests."""
    return RecentActivityEntry(
        task_id=task_id,
        summary=summary,
        completed_at=completed_at,
    )


def _make_integrity_issue(
    code="ORPHANED_TASK",
    severity="warning",
    goal_id=None,
    task_id="Orphan task",
    message="Task has no link to any goal",
):
    """Create a GoalIntegrityIssue with sensible defaults for tests."""
    return GoalIntegrityIssue(
        code=code,
        severity=severity,
        goal_id=goal_id,
        task_id=task_id,
        message=message,
    )


# ── PersonalState model tests ─────────────────────────────────────────────────


class TestPersonalStateModel:
    """Tests for the PersonalState dataclass."""

    def test_create_minimal_personal_state(self):
        """PersonalState can be created with minimal required fields."""
        state = PersonalState(
            generated_at=FIXED_NOW,
            data_fingerprint="abc123",
        )
        assert state.generated_at == FIXED_NOW
        assert state.data_fingerprint == "abc123"
        assert state.goals == []
        assert state.active_goals == []
        assert state.tasks == []
        assert state.open_tasks == []
        assert state.followups == []
        assert state.inbox_items == []
        assert state.milestones == []
        assert state.projects == []
        assert state.metric_snapshots == []
        assert state.measurement_requirements == []
        assert state.recent_activity == []
        assert state.research_artifacts == []
        assert state.strategic_summary is None
        assert state.recommended_actions == []
        assert state.integrity_issues == []

    def test_create_full_personal_state(self):
        """PersonalState can be created with all fields populated."""
        goal = _make_goal()
        task = _make_task()
        followup = _make_followup()
        inbox = _make_inbox_item()
        milestone = _make_milestone()
        project = _make_project()
        snapshot = _make_metric_snapshot()
        activity = _make_recent_activity()
        issue = _make_integrity_issue()

        state = PersonalState(
            generated_at=FIXED_NOW,
            data_fingerprint="abc123",
            goals=[goal],
            active_goals=[goal],
            tasks=[task],
            open_tasks=[task],
            followups=[followup],
            inbox_items=[inbox],
            milestones=[milestone],
            projects=[project],
            metric_snapshots=[snapshot],
            measurement_requirements=[{"metric": "Weight", "unit": "kg"}],
            recent_activity=[activity],
            research_artifacts=["Research 1"],
            integrity_issues=[issue],
        )

        assert state.goals == [goal]
        assert state.active_goals == [goal]
        assert state.tasks == [task]
        assert state.open_tasks == [task]
        assert state.followups == [followup]
        assert state.inbox_items == [inbox]
        assert state.milestones == [milestone]
        assert state.projects == [project]
        assert state.metric_snapshots == [snapshot]
        assert state.recent_activity == [activity]
        assert state.research_artifacts == ["Research 1"]
        assert state.integrity_issues == [issue]

    def test_to_dict_serializes_datetime(self):
        """to_dict converts datetime to ISO format strings."""
        state = PersonalState(
            generated_at=FIXED_NOW,
            data_fingerprint="abc123",
        )
        d = state.to_dict()
        assert isinstance(d["generated_at"], str)
        assert "2026-09-29" in d["generated_at"]

    def test_to_dict_serializes_nested_datetimes(self):
        """to_dict recursively converts nested datetimes."""
        snapshot = _make_metric_snapshot()
        state = PersonalState(
            generated_at=FIXED_NOW,
            data_fingerprint="abc123",
            metric_snapshots=[snapshot],
        )
        d = state.to_dict()
        assert isinstance(d["metric_snapshots"][0]["timestamp"], str)


# ── PersonalStateBuilder tests ────────────────────────────────────────────────


class TestPersonalStateBuilder:
    """Tests for the PersonalStateBuilder service."""

    def test_builder_init_default_paths(self):
        """Builder initializes with default paths."""
        builder = PersonalStateBuilder()
        assert builder._goals_path.name == "goals.md"
        assert builder._tasks_path.name == "tasks.md"
        assert builder._followups_path.name == "followups.md"
        assert builder._inbox_path.name == "inbox.md"

    def test_builder_init_custom_paths(self, tmp_path):
        """Builder accepts custom file paths."""
        builder = PersonalStateBuilder(
            goals_path=tmp_path / "goals.md",
            tasks_path=tmp_path / "tasks.md",
            followups_path=tmp_path / "followups.md",
            inbox_path=tmp_path / "inbox.md",
        )
        assert builder._goals_path == tmp_path / "goals.md"
        assert builder._tasks_path == tmp_path / "tasks.md"

    def test_compute_fingerprint_deterministic(self):
        """Fingerprint is deterministic for the same file content."""
        builder = PersonalStateBuilder()
        fp1 = builder.compute_fingerprint()
        fp2 = builder.compute_fingerprint()
        assert fp1 == fp2
        assert len(fp1) == 64  # SHA-256 hex length

    def test_compute_fingerprint_changes_with_content(self, tmp_path):
        """Fingerprint changes when file content changes."""
        goals_file = tmp_path / "goals.md"
        goals_file.write_text("# Goals\n## Goal 1\n")

        builder = PersonalStateBuilder(goals_path=goals_file)
        fp1 = builder.compute_fingerprint()

        goals_file.write_text("# Goals\n## Goal 1\n## Goal 2\n")
        fp2 = builder.compute_fingerprint()

        assert fp1 != fp2

    def test_compute_fingerprint_missing_files(self, tmp_path):
        """Fingerprint handles missing files gracefully."""
        builder = PersonalStateBuilder(
            goals_path=tmp_path / "nonexistent_goals.md",
            tasks_path=tmp_path / "nonexistent_tasks.md",
        )
        fp = builder.compute_fingerprint()
        assert len(fp) == 64
        assert isinstance(fp, str)

    def test_build_empty_state(self, tmp_path):
        """Builder returns empty state when no data files exist."""
        builder = PersonalStateBuilder(
            goals_path=tmp_path / "goals.md",
            tasks_path=tmp_path / "tasks.md",
            followups_path=tmp_path / "followups.md",
            inbox_path=tmp_path / "inbox.md",
        )
        state = builder.build()

        assert isinstance(state, PersonalState)
        assert state.goals == []
        assert state.tasks == []
        assert state.followups == []
        assert state.inbox_items == []
        assert state.active_goals == []
        assert state.open_tasks == []
        assert state.blocked_tasks == []
        assert state.milestones == []
        assert state.projects == []
        assert state.integrity_issues == []
        assert state.strategic_summary is None
        assert len(state.data_fingerprint) == 64

    def test_build_with_goals_and_tasks(self, tmp_path):
        """Builder loads goals and tasks from data files."""
        goals_file = tmp_path / "goals.md"
        goals_file.write_text(
            "# Goals\n\n"
            "## Goal: Active Goal\n"
            "Status: active\n"
            "Related tasks: Task 1\n"
        )
        tasks_file = tmp_path / "tasks.md"
        tasks_file.write_text(
            "# Tasks\n\n"
            "- [ ] Task 1\n"
            "- [ ] Blocked Task | state: blocked\n"
        )

        builder = PersonalStateBuilder(
            goals_path=goals_file,
            tasks_path=tasks_file,
            followups_path=tmp_path / "followups.md",
            inbox_path=tmp_path / "inbox.md",
        )
        state = builder.build()

        assert len(state.goals) == 1
        assert state.goals[0].title == "Active Goal"
        assert len(state.tasks) == 2
        assert len(state.open_tasks) == 2  # Both are open (todo + blocked)
        assert len(state.blocked_tasks) == 1
        assert state.blocked_tasks[0].title == "Blocked Task"

    def test_build_derives_active_goals(self, tmp_path):
        """Builder correctly derives active goals."""
        goals_file = tmp_path / "goals.md"
        goals_file.write_text(
            "# Goals\n\n"
            "## Goal: Active Goal\n"
            "Status: active\n\n"
            "## Goal: Completed Goal\n"
            "Status: completed\n\n"
            "## Goal: Inactive Goal\n"
            "Status: inactive\n"
        )

        builder = PersonalStateBuilder(
            goals_path=goals_file,
            tasks_path=tmp_path / "tasks.md",
            followups_path=tmp_path / "followups.md",
            inbox_path=tmp_path / "inbox.md",
        )
        state = builder.build()

        assert len(state.goals) == 3
        assert len(state.active_goals) == 1
        assert state.active_goals[0].title == "Active Goal"

    def test_build_derives_milestones_and_projects(self, tmp_path):
        """Builder derives milestones and projects from goals."""
        goals_file = tmp_path / "goals.md"
        goals_file.write_text(
            "# Goals\n\n"
            "## Goal: Test Goal\n"
            "Status: active\n"
            "Related tasks: Task 1\n\n"
            "## Milestones\n\n"
            "### Milestone: MS1\n"
            "Status: open\n\n"
            "## Projects\n\n"
            "### Project: P1\n"
            "Milestone: MS1\n"
            "Status: open\n"
        )

        builder = PersonalStateBuilder(
            goals_path=goals_file,
            tasks_path=tmp_path / "tasks.md",
            followups_path=tmp_path / "followups.md",
            inbox_path=tmp_path / "inbox.md",
        )
        state = builder.build()

        assert len(state.milestones) == 1
        assert state.milestones[0].title == "MS1"
        assert len(state.projects) == 1
        assert state.projects[0].title == "P1"

    def test_build_derives_research_artifacts(self, tmp_path):
        """Builder derives research artifact titles from goals."""
        goals_file = tmp_path / "goals.md"
        goals_file.write_text(
            "# Goals\n\n"
            "## Goal: Test Goal\n"
            "Status: active\n"
            "Research artifacts:\n"
            "- Paper 1\n"
            "- Paper 2\n"
        )

        builder = PersonalStateBuilder(
            goals_path=goals_file,
            tasks_path=tmp_path / "tasks.md",
            followups_path=tmp_path / "followups.md",
            inbox_path=tmp_path / "inbox.md",
        )
        state = builder.build()

        assert "Paper 1" in state.research_artifacts
        assert "Paper 2" in state.research_artifacts

    def test_build_with_integrity_check(self, tmp_path):
        """Builder runs integrity check and attaches issues."""
        goals_file = tmp_path / "goals.md"
        goals_file.write_text(
            "# Goals\n\n"
            "## Goal: Test Goal\n"
            "Status: active\n"
            "Related tasks: Nonexistent Task\n"
        )
        tasks_file = tmp_path / "tasks.md"
        tasks_file.write_text("# Tasks\n\n- [ ] Orphan Task\n")

        builder = PersonalStateBuilder(
            goals_path=goals_file,
            tasks_path=tasks_file,
            followups_path=tmp_path / "followups.md",
            inbox_path=tmp_path / "inbox.md",
        )
        state = builder.build(include_integrity_check=True)

        assert len(state.integrity_issues) > 0
        # Should have ORPHANED_TASK for the orphan task
        orphan_issues = [
            i for i in state.integrity_issues if i.code == "ORPHANED_TASK"
        ]
        assert len(orphan_issues) > 0

    def test_build_without_integrity_check(self, tmp_path):
        """Builder skips integrity check when disabled."""
        goals_file = tmp_path / "goals.md"
        goals_file.write_text(
            "# Goals\n\n"
            "## Goal: Test Goal\n"
            "Status: active\n"
        )
        tasks_file = tmp_path / "tasks.md"
        tasks_file.write_text("# Tasks\n\n- [ ] Orphan Task\n")

        builder = PersonalStateBuilder(
            goals_path=goals_file,
            tasks_path=tasks_file,
            followups_path=tmp_path / "followups.md",
            inbox_path=tmp_path / "inbox.md",
        )
        state = builder.build(include_integrity_check=False)

        assert state.integrity_issues == []

    def test_build_with_strategic_summary(self, tmp_path):
        """Builder computes strategic summary when requested."""
        goals_file = tmp_path / "goals.md"
        goals_file.write_text(
            "# Goals\n\n"
            "## Goal: Test Goal\n"
            "Status: active\n"
            "Related tasks: Task 1\n"
        )
        tasks_file = tmp_path / "tasks.md"
        tasks_file.write_text("# Tasks\n\n- [ ] Task 1\n")

        builder = PersonalStateBuilder(
            goals_path=goals_file,
            tasks_path=tasks_file,
            followups_path=tmp_path / "followups.md",
            inbox_path=tmp_path / "inbox.md",
        )
        state = builder.build(include_strategic_summary=True)

        assert state.strategic_summary is not None
        assert isinstance(state.strategic_summary, StrategicSummary)
        assert state.strategic_summary.portfolio_health_counts.total_active >= 0

    def test_build_without_strategic_summary(self, tmp_path):
        """Builder skips strategic summary by default."""
        goals_file = tmp_path / "goals.md"
        goals_file.write_text(
            "# Goals\n\n"
            "## Goal: Test Goal\n"
            "Status: active\n"
        )

        builder = PersonalStateBuilder(
            goals_path=goals_file,
            tasks_path=tmp_path / "tasks.md",
            followups_path=tmp_path / "followups.md",
            inbox_path=tmp_path / "inbox.md",
        )
        state = builder.build()

        assert state.strategic_summary is None
        assert state.recommended_actions == []

    def test_build_with_followups_and_inbox(self, tmp_path):
        """Builder loads followups and inbox items."""
        followups_file = tmp_path / "followups.md"
        followups_file.write_text(
            "# Follow-ups\n\n"
            "fu-1 | Test followup | state: pending | priority: 3\n"
        )
        inbox_file = tmp_path / "inbox.md"
        inbox_file.write_text(
            "# Inbox\n\n"
            "ix-1 | Test inbox item | source: manual | captured_at: 2026-09-29\n"
        )

        builder = PersonalStateBuilder(
            goals_path=tmp_path / "goals.md",
            tasks_path=tmp_path / "tasks.md",
            followups_path=followups_file,
            inbox_path=inbox_file,
        )
        state = builder.build()

        assert len(state.followups) == 1
        assert state.followups[0].title == "Test followup"
        assert len(state.inbox_items) == 1
        assert state.inbox_items[0].captured_text == "Test inbox item"

    def test_build_derived_views_consistency(self, tmp_path):
        """Derived views are consistent with base collections."""
        goals_file = tmp_path / "goals.md"
        goals_file.write_text(
            "# Goals\n\n"
            "## Goal: Active Goal\n"
            "Status: active\n"
            "Related tasks: Task 1\n\n"
            "## Goal: Completed Goal\n"
            "Status: completed\n"
        )
        tasks_file = tmp_path / "tasks.md"
        tasks_file.write_text(
            "# Tasks\n\n"
            "- [ ] Task 1\n"
            "- [ ] Task 2 | state: blocked\n"
        )

        builder = PersonalStateBuilder(
            goals_path=goals_file,
            tasks_path=tasks_file,
            followups_path=tmp_path / "followups.md",
            inbox_path=tmp_path / "inbox.md",
        )
        state = builder.build()

        # active_goals is a subset of goals
        assert all(g in state.goals for g in state.active_goals)
        # open_tasks is a subset of tasks
        assert all(t in state.tasks for t in state.open_tasks)
        # blocked_tasks is a subset of open_tasks
        assert all(t in state.open_tasks for t in state.blocked_tasks)
        # blocked_tasks have state == "blocked"
        assert all(t.state == "blocked" for t in state.blocked_tasks)

    def test_build_with_custom_today(self, tmp_path):
        """Builder accepts custom reference date."""
        goals_file = tmp_path / "goals.md"
        goals_file.write_text(
            "# Goals\n\n"
            "## Goal: Test Goal\n"
            "Status: active\n"
        )

        builder = PersonalStateBuilder(
            goals_path=goals_file,
            tasks_path=tmp_path / "tasks.md",
            followups_path=tmp_path / "followups.md",
            inbox_path=tmp_path / "inbox.md",
        )
        state = builder.build(today=FIXED_TODAY)

        assert isinstance(state, PersonalState)

    def test_fingerprint_includes_all_source_files(self, tmp_path):
        """Fingerprint changes when any source file changes."""
        goals_file = tmp_path / "goals.md"
        tasks_file = tmp_path / "tasks.md"
        followups_file = tmp_path / "followups.md"
        inbox_file = tmp_path / "inbox.md"

        goals_file.write_text("# Goals\n")
        tasks_file.write_text("# Tasks\n")
        followups_file.write_text("# Follow-ups\n")
        inbox_file.write_text("# Inbox\n")

        builder = PersonalStateBuilder(
            goals_path=goals_file,
            tasks_path=tasks_file,
            followups_path=followups_file,
            inbox_path=inbox_file,
        )
        fp1 = builder.compute_fingerprint()

        # Change only the inbox file
        inbox_file.write_text("# Inbox\n\n- New item\n")
        fp2 = builder.compute_fingerprint()

        assert fp1 != fp2


# ── Integration-style tests ───────────────────────────────────────────────────


class TestPersonalStateIntegration:
    """Integration tests for the PersonalState API layer."""

    def test_full_build_with_all_components(self, tmp_path):
        """Full build with goals, tasks, followups, inbox, and integrity check."""
        goals_file = tmp_path / "goals.md"
        goals_file.write_text(
            "# Goals\n\n"
            "## Goal: Learn Rust\n"
            "Status: active\n"
            "Related tasks: Read Rust book\n"
            "Research artifacts:\n"
            "- Rust Book\n\n"
            "## Milestones\n\n"
            "### Milestone: Complete book\n"
            "Status: open\n\n"
            "## Projects\n\n"
            "### Project: Exercises\n"
            "Milestone: Complete book\n"
            "Status: open\n"
        )
        tasks_file = tmp_path / "tasks.md"
        tasks_file.write_text(
            "# Tasks\n\n"
            "- [ ] Read Rust book\n"
            "- [ ] Do exercises | state: blocked\n"
        )
        followups_file = tmp_path / "followups.md"
        followups_file.write_text(
            "# Follow-ups\n\n"
            "fu-1 | Buy Rust book | state: pending | priority: 3\n"
        )
        inbox_file = tmp_path / "inbox.md"
        inbox_file.write_text(
            "# Inbox\n\n"
            "ix-1 | Consider Rust project | source: manual | captured_at: 2026-09-29\n"
        )

        builder = PersonalStateBuilder(
            goals_path=goals_file,
            tasks_path=tasks_file,
            followups_path=followups_file,
            inbox_path=inbox_file,
        )
        state = builder.build(
            include_strategic_summary=True,
            include_integrity_check=True,
        )

        # Verify all components are present
        assert len(state.goals) == 1
        assert len(state.active_goals) == 1
        assert len(state.tasks) == 2
        assert len(state.open_tasks) == 2
        assert len(state.blocked_tasks) == 1
        assert len(state.followups) == 1
        assert len(state.inbox_items) == 1
        assert len(state.milestones) == 1
        assert len(state.projects) == 1
        assert len(state.research_artifacts) == 1
        assert state.strategic_summary is not None
        assert len(state.data_fingerprint) == 64

    def test_build_is_deterministic(self, tmp_path):
        """Building twice with same data produces same fingerprint."""
        goals_file = tmp_path / "goals.md"
        goals_file.write_text(
            "# Goals\n\n"
            "## Goal: Test Goal\n"
            "Status: active\n"
        )

        builder = PersonalStateBuilder(
            goals_path=goals_file,
            tasks_path=tmp_path / "tasks.md",
            followups_path=tmp_path / "followups.md",
            inbox_path=tmp_path / "inbox.md",
        )
        state1 = builder.build()
        state2 = builder.build()

        assert state1.data_fingerprint == state2.data_fingerprint

    def test_build_reflects_data_changes(self, tmp_path):
        """Rebuilding after data changes produces different fingerprint."""
        goals_file = tmp_path / "goals.md"
        goals_file.write_text(
            "# Goals\n\n"
            "## Goal: Test Goal\n"
            "Status: active\n"
        )

        builder = PersonalStateBuilder(
            goals_path=goals_file,
            tasks_path=tmp_path / "tasks.md",
            followups_path=tmp_path / "followups.md",
            inbox_path=tmp_path / "inbox.md",
        )
        state1 = builder.build()

        # Add a new goal
        goals_file.write_text(
            "# Goals\n\n"
            "## Goal: Test Goal\n"
            "Status: active\n\n"
            "## Goal: New Goal\n"
            "Status: active\n"
        )
        state2 = builder.build()

        assert state1.data_fingerprint != state2.data_fingerprint
        assert len(state2.goals) == 2
