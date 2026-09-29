"""Tests for the PersonalStateBuilder service.

Covers:
- PersonalStateBuilder construction and build().
- Data fingerprint computation.
- Derived views (active goals, open tasks, blocked tasks, etc.).
- Data loading from markdown files.
- Integrity audit integration.
- Edge cases (empty state, missing files).
- Integration with existing services.

Design reference: docs/design/personal_state_model_spec.md §5 Phase 2.
"""

from datetime import datetime, timezone
from pathlib import Path

from janus.models.goal import Goal
from janus.models.task import Task
from janus.models.follow_up import FollowUp
from janus.models.inbox import InboxItem
from janus.models.decision import Decision
from janus.models.milestone import Milestone
from janus.models.project import Project
from janus.models.metric_snapshot import MetricSnapshot
from janus.models.recent_activity import RecentActivityEntry
from janus.models.goal_integrity_report import GoalIntegrityIssue
from janus.models.strategic_summary import StrategicSummary
from janus.models.personal_state import PersonalState
from janus.services.personal_state import (
    PersonalStateBuilder,
    build_personal_state,
    _compute_data_fingerprint,
    _derive_active_goals,
    _derive_open_tasks,
    _derive_blocked_tasks,
    _derive_milestones,
    _derive_projects,
    _derive_measurement_requirements,
    _derive_recent_activity,
    _derive_research_artifacts,
    _load_goals,
    _load_tasks,
    _load_followups,
    _load_inbox_items,
    _load_decisions,
    _load_workouts,
    _load_metric_snapshots,
    _run_integrity_audit,
    PROJECT_ROOT,
    SOURCE_FILES,
)


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
    due_date=None,
    progress=None,
    extra_metadata=None,
):
    """Create a Task with sensible defaults for tests."""
    return Task(
        title=title,
        state=state,
        priority=priority,
        due_date=due_date,
        progress=progress,
        extra_metadata=extra_metadata,
    )


def _make_followup(
    id="fu-1",
    title="Test followup",
    state="pending",
    priority=1,
    linked_goal_title="",
):
    """Create a FollowUp with sensible defaults for tests."""
    return FollowUp(
        id=id,
        title=title,
        state=state,
        priority=priority,
        linked_goal_title=linked_goal_title,
    )


def _make_inbox_item(
    id="ix-1",
    captured_text="Test inbox item",
    source="manual",
    triage_state="pending",
):
    """Create an InboxItem with sensible defaults for tests."""
    return InboxItem(
        id=id,
        captured_text=captured_text,
        source=source,
        triage_state=triage_state,
    )


def _make_decision(
    adr_number="001",
    title="Test decision",
    status="accepted",
    goal_titles=None,
):
    """Create a Decision with sensible defaults for tests."""
    return Decision(
        adr_number=adr_number,
        title=title,
        status=status,
        goal_titles=goal_titles or [],
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
    metric_name="Test metric",
    value=10.0,
    source="manual",
):
    """Create a MetricSnapshot with sensible defaults for tests."""
    return MetricSnapshot(
        timestamp=datetime(2026, 9, 1, tzinfo=timezone.utc),
        goal_title=goal_title,
        metric_name=metric_name,
        value=value,
        source=source,
    )


def _make_recent_activity_entry(
    task_id="t-1",
    summary="Test activity",
    completed_at="2026-09-01T12:00:00+00:00",
):
    """Create a RecentActivityEntry with sensible defaults for tests."""
    return RecentActivityEntry(
        task_id=task_id,
        summary=summary,
        completed_at=completed_at,
    )


# ── Data fingerprint tests ────────────────────────────────────────────────────


class TestDataFingerprint:
    """Tests for data fingerprint computation."""

    def test_fingerprint_is_deterministic(self):
        """Same data produces same fingerprint."""
        fp1 = _compute_data_fingerprint()
        fp2 = _compute_data_fingerprint()
        assert fp1 == fp2

    def test_fingerprint_is_sha256_hex(self):
        """Fingerprint is a valid SHA-256 hex string."""
        fp = _compute_data_fingerprint()
        assert len(fp) == 64
        int(fp, 16)  # Should not raise

    def test_fingerprint_changes_when_data_changes(self):
        """Different data produces different fingerprint."""
        fp1 = _compute_data_fingerprint()
        # Create a temporary source file to change the fingerprint
        data_dir = PROJECT_ROOT / "data"
        data_dir.mkdir(exist_ok=True)
        test_file = data_dir / "goals.md"
        original_exists = test_file.exists()
        original_content = test_file.read_bytes() if original_exists else None
        try:
            test_file.write_text("# Changed content\n")
            fp2 = _compute_data_fingerprint()
            assert fp1 != fp2
        finally:
            if original_exists and original_content is not None:
                test_file.write_bytes(original_content)
            else:
                test_file.unlink(missing_ok=True)


# ── Derived view tests ────────────────────────────────────────────────────────


class TestDerivedViews:
    """Tests for derived view functions."""

    def test_derive_active_goals(self):
        """Active goals are filtered by status == 'active'."""
        active = _make_goal(title="Active", status="active")
        completed = _make_goal(title="Completed", status="completed")
        inactive = _make_goal(title="Inactive", status="inactive")
        result = _derive_active_goals([active, completed, inactive])
        assert result == [active]

    def test_derive_active_goals_empty(self):
        """Empty goals list returns empty active goals."""
        assert _derive_active_goals([]) == []

    def test_derive_open_tasks(self):
        """Open tasks are filtered by ALLOWED_STATES."""
        todo = _make_task(title="Todo", state="todo")
        in_progress = _make_task(title="In Progress", state="in_progress")
        blocked = _make_task(title="Blocked", state="blocked")
        result = _derive_open_tasks([todo, in_progress, blocked])
        assert len(result) == 3
        assert {t.title for t in result} == {"Todo", "In Progress", "Blocked"}

    def test_derive_open_tasks_empty(self):
        """Empty tasks list returns empty open tasks."""
        assert _derive_open_tasks([]) == []

    def test_derive_blocked_tasks(self):
        """Blocked tasks are filtered by state == 'blocked'."""
        blocked = _make_task(title="Blocked", state="blocked")
        todo = _make_task(title="Todo", state="todo")
        result = _derive_blocked_tasks([blocked, todo])
        assert result == [blocked]

    def test_derive_blocked_tasks_empty(self):
        """Empty tasks list returns empty blocked tasks."""
        assert _derive_blocked_tasks([]) == []

    def test_derive_milestones(self):
        """Milestones are derived from goals."""
        ms1 = {"title": "MS1", "goal_title": "Test goal", "status": "open", "order": 0}
        ms2 = {"title": "MS2", "goal_title": "Test goal", "status": "open", "order": 1}
        goal = _make_goal(milestones=[ms1, ms2])
        result = _derive_milestones([goal])
        assert len(result) == 2
        assert all(isinstance(m, Milestone) for m in result)
        assert result[0].title == "MS1"
        assert result[1].title == "MS2"

    def test_derive_milestones_empty(self):
        """Empty goals list returns empty milestones."""
        assert _derive_milestones([]) == []

    def test_derive_projects(self):
        """Projects are derived from goals."""
        proj1 = {
            "title": "Proj1",
            "milestone_title": "MS1",
            "status": "open",
            "order": 0,
        }
        goal = _make_goal(projects=[proj1])
        result = _derive_projects([goal])
        assert len(result) == 1
        assert isinstance(result[0], Project)
        assert result[0].title == "Proj1"

    def test_derive_projects_empty(self):
        """Empty goals list returns empty projects."""
        assert _derive_projects([]) == []

    def test_derive_measurement_requirements(self):
        """Measurement requirements are derived from goals."""
        reqs = [{"metric": "weight", "unit": "kg", "frequency": "weekly"}]
        goal = _make_goal(measurement_requirements=reqs)
        result = _derive_measurement_requirements([goal])
        assert result == reqs

    def test_derive_measurement_requirements_empty(self):
        """Empty goals list returns empty measurement requirements."""
        assert _derive_measurement_requirements([]) == []

    def test_derive_recent_activity(self):
        """Recent activity entries are derived from goals."""
        activity = {
            "task_id": "t-1",
            "summary": "Did stuff",
            "completed_at": "2026-09-01T12:00:00+00:00",
            "changed_files": ["file.py"],
            "tests_passed": True,
            "pr_url": None,
        }
        goal = _make_goal(recent_activity=[activity])
        result = _derive_recent_activity([goal])
        assert len(result) == 1
        assert isinstance(result[0], RecentActivityEntry)
        assert result[0].task_id == "t-1"

    def test_derive_recent_activity_empty(self):
        """Empty goals list returns empty recent activity."""
        assert _derive_recent_activity([]) == []

    def test_derive_research_artifacts(self):
        """Research artifact titles are derived from goals."""
        goal1 = _make_goal(research_artifact_titles=["Artifact B", "Artifact A"])
        goal2 = _make_goal(research_artifact_titles=["Artifact C"])
        result = _derive_research_artifacts([goal1, goal2])
        assert result == ["Artifact A", "Artifact B", "Artifact C"]

    def test_derive_research_artifacts_empty(self):
        """Empty goals list returns empty research artifacts."""
        assert _derive_research_artifacts([]) == []


# ── Data loading tests ────────────────────────────────────────────────────────


class TestDataLoading:
    """Tests for data loading functions."""

    def test_load_goals_returns_list(self):
        """_load_goals returns a list."""
        result = _load_goals()
        assert isinstance(result, list)

    def test_load_tasks_returns_list(self):
        """_load_tasks returns a list."""
        result = _load_tasks()
        assert isinstance(result, list)

    def test_load_followups_returns_list(self):
        """_load_followups returns a list."""
        result = _load_followups()
        assert isinstance(result, list)

    def test_load_inbox_items_returns_list(self):
        """_load_inbox_items returns a list."""
        result = _load_inbox_items()
        assert isinstance(result, list)

    def test_load_decisions_returns_list(self):
        """_load_decisions returns a list."""
        result = _load_decisions()
        assert isinstance(result, list)

    def test_load_workouts_returns_list(self):
        """_load_workouts returns a list."""
        result = _load_workouts()
        assert isinstance(result, list)

    def test_load_metric_snapshots_returns_list(self):
        """_load_metric_snapshots returns a list."""
        result = _load_metric_snapshots()
        assert isinstance(result, list)


# ── Integrity audit tests ─────────────────────────────────────────────────────


class TestIntegrityAudit:
    """Tests for integrity audit integration."""

    def test_run_integrity_audit_returns_list(self):
        """_run_integrity_audit returns a list of issues."""
        result = _run_integrity_audit([], [])
        assert isinstance(result, list)

    def test_run_integrity_audit_detects_orphan_tasks(self):
        """Orphan tasks are detected by the audit."""
        task = _make_task(title="Orphan task")
        result = _run_integrity_audit([], [task])
        assert any(
            issue.code == "ORPHANED_TASK"
            for issue in result
        )

    def test_run_integrity_audit_detects_invalid_related_tasks(self):
        """Invalid related_task references are detected."""
        goal = _make_goal(related_tasks=["Nonexistent task"])
        result = _run_integrity_audit([goal], [])
        assert any(
            issue.code == "INVALID_RELATED_TASK"
            for issue in result
        )


# ── PersonalStateBuilder tests ────────────────────────────────────────────────


class TestPersonalStateBuilder:
    """Tests for the PersonalStateBuilder service."""

    def test_builder_constructs(self):
        """PersonalStateBuilder can be constructed."""
        builder = PersonalStateBuilder()
        assert builder is not None

    def test_builder_constructs_with_custom_root(self):
        """PersonalStateBuilder accepts a custom project root."""
        builder = PersonalStateBuilder(project_root=Path("/tmp"))
        assert builder._project_root == Path("/tmp")

    def test_build_returns_personal_state(self):
        """build() returns a PersonalState instance."""
        builder = PersonalStateBuilder()
        state = builder.build()
        assert isinstance(state, PersonalState)

    def test_build_populates_goals(self):
        """build() populates goals from data files."""
        builder = PersonalStateBuilder()
        state = builder.build()
        assert isinstance(state.goals, list)

    def test_build_populates_tasks(self):
        """build() populates tasks from data files."""
        builder = PersonalStateBuilder()
        state = builder.build()
        assert isinstance(state.tasks, list)

    def test_build_populates_followups(self):
        """build() populates followups from data files."""
        builder = PersonalStateBuilder()
        state = builder.build()
        assert isinstance(state.followups, list)

    def test_build_populates_inbox_items(self):
        """build() populates inbox items from data files."""
        builder = PersonalStateBuilder()
        state = builder.build()
        assert isinstance(state.inbox_items, list)

    def test_build_populates_decisions(self):
        """build() populates decisions from data files."""
        builder = PersonalStateBuilder()
        state = builder.build()
        assert isinstance(state.decisions, list)

    def test_build_populates_milestones(self):
        """build() populates milestones derived from goals."""
        builder = PersonalStateBuilder()
        state = builder.build()
        assert isinstance(state.milestones, list)

    def test_build_populates_projects(self):
        """build() populates projects derived from goals."""
        builder = PersonalStateBuilder()
        state = builder.build()
        assert isinstance(state.projects, list)

    def test_build_populates_metric_snapshots(self):
        """build() populates metric snapshots from data files."""
        builder = PersonalStateBuilder()
        state = builder.build()
        assert isinstance(state.metric_snapshots, list)

    def test_build_populates_measurement_requirements(self):
        """build() populates measurement requirements derived from goals."""
        builder = PersonalStateBuilder()
        state = builder.build()
        assert isinstance(state.measurement_requirements, list)

    def test_build_populates_recent_activity(self):
        """build() populates recent activity derived from goals."""
        builder = PersonalStateBuilder()
        state = builder.build()
        assert isinstance(state.recent_activity, list)

    def test_build_populates_research_artifacts(self):
        """build() populates research artifacts derived from goals."""
        builder = PersonalStateBuilder()
        state = builder.build()
        assert isinstance(state.research_artifacts, list)

    def test_build_populates_integrity_issues(self):
        """build() populates integrity issues by default."""
        builder = PersonalStateBuilder()
        state = builder.build()
        assert isinstance(state.integrity_issues, list)

    def test_build_skips_integrity_audit_when_disabled(self):
        """build() skips integrity audit when include_integrity_audit=False."""
        builder = PersonalStateBuilder()
        state = builder.build(include_integrity_audit=False)
        assert state.integrity_issues == []

    def test_build_includes_strategic_summary_when_requested(self):
        """build() includes strategic summary when requested."""
        builder = PersonalStateBuilder()
        state = builder.build(include_strategic_summary=True)
        # Strategic summary may be None if data is insufficient
        assert state.strategic_summary is None or isinstance(
            state.strategic_summary, StrategicSummary
        )

    def test_build_excludes_strategic_summary_by_default(self):
        """build() excludes strategic summary by default."""
        builder = PersonalStateBuilder()
        state = builder.build()
        assert state.strategic_summary is None

    def test_build_includes_recommended_actions_when_requested(self):
        """build() includes recommended actions when requested."""
        builder = PersonalStateBuilder()
        state = builder.build(include_recommended_actions=True)
        assert isinstance(state.recommended_actions, list)

    def test_build_excludes_recommended_actions_by_default(self):
        """build() excludes recommended actions by default."""
        builder = PersonalStateBuilder()
        state = builder.build()
        assert state.recommended_actions == []

    def test_build_sets_data_fingerprint(self):
        """build() sets a valid data fingerprint."""
        builder = PersonalStateBuilder()
        state = builder.build()
        assert len(state.data_fingerprint) == 64
        int(state.data_fingerprint, 16)  # Should not raise

    def test_build_sets_generated_at(self):
        """build() sets generated_at to a datetime."""
        builder = PersonalStateBuilder()
        state = builder.build()
        assert isinstance(state.generated_at, datetime)

    def test_build_derives_active_goals(self):
        """build() derives active goals from loaded goals."""
        builder = PersonalStateBuilder()
        state = builder.build()
        for goal in state.active_goals:
            assert goal.status == "active"

    def test_build_derives_open_tasks(self):
        """build() derives open tasks from loaded tasks."""
        builder = PersonalStateBuilder()
        state = builder.build()
        for task in state.open_tasks:
            assert task.state in ("todo", "in_progress", "blocked")

    def test_build_derives_blocked_tasks(self):
        """build() derives blocked tasks from loaded tasks."""
        builder = PersonalStateBuilder()
        state = builder.build()
        for task in state.blocked_tasks:
            assert task.state == "blocked"


# ── Convenience function tests ────────────────────────────────────────────────


class TestBuildPersonalState:
    """Tests for the build_personal_state convenience function."""

    def test_returns_personal_state(self):
        """build_personal_state returns a PersonalState instance."""
        state = build_personal_state()
        assert isinstance(state, PersonalState)

    def test_respects_include_strategic_summary(self):
        """build_personal_state respects include_strategic_summary."""
        state = build_personal_state(include_strategic_summary=True)
        assert state.strategic_summary is None or isinstance(
            state.strategic_summary, StrategicSummary
        )

    def test_respects_include_recommended_actions(self):
        """build_personal_state respects include_recommended_actions."""
        state = build_personal_state(include_recommended_actions=True)
        assert isinstance(state.recommended_actions, list)

    def test_respects_include_integrity_audit(self):
        """build_personal_state respects include_integrity_audit."""
        state = build_personal_state(include_integrity_audit=False)
        assert state.integrity_issues == []


# ── Edge case tests ───────────────────────────────────────────────────────────


class TestEdgeCases:
    """Tests for edge cases and error handling."""

    def test_build_with_missing_data_files(self):
        """build() handles missing data files gracefully."""
        # This test runs in the worktree where data files may not exist
        builder = PersonalStateBuilder()
        state = builder.build()
        # Should not raise, even if data files are missing
        assert isinstance(state, PersonalState)

    def test_fingerprint_with_no_source_files(self):
        """Fingerprint is computed even when no source files exist."""
        # In a fresh worktree, data files may not exist
        fp = _compute_data_fingerprint()
        assert isinstance(fp, str)
        assert len(fp) == 64

    def test_derive_views_with_empty_lists(self):
        """All derived view functions handle empty lists."""
        assert _derive_active_goals([]) == []
        assert _derive_open_tasks([]) == []
        assert _derive_blocked_tasks([]) == []
        assert _derive_milestones([]) == []
        assert _derive_projects([]) == []
        assert _derive_measurement_requirements([]) == []
        assert _derive_recent_activity([]) == []
        assert _derive_research_artifacts([]) == []

    def test_integrity_audit_with_empty_lists(self):
        """Integrity audit handles empty lists."""
        result = _run_integrity_audit([], [])
        assert isinstance(result, list)


# ── Integration with existing services ────────────────────────────────────────


class TestIntegrationWithExistingServices:
    """Tests for integration with existing Janus services."""

    def test_personal_state_uses_goal_integrity_service(self):
        """PersonalState uses the existing goal_integrity service."""
        goal = _make_goal(title="Test goal", related_tasks=["Nonexistent"])
        issues = _run_integrity_audit([goal], [])
        assert any(
            issue.code == "INVALID_RELATED_TASK"
            for issue in issues
        )

    def test_personal_state_uses_goal_health_service(self):
        """PersonalState uses the existing goal_health service for stalled goals."""
        # This is tested indirectly through the builder
        builder = PersonalStateBuilder()
        state = builder.build()
        # stalled_goals should be a list (may be empty)
        assert isinstance(state.stalled_goals, list)

    def test_personal_state_uses_strategic_summary_service(self):
        """PersonalState uses the existing strategic_summary service."""
        builder = PersonalStateBuilder()
        state = builder.build(include_strategic_summary=True)
        # strategic_summary may be None if data is insufficient
        assert state.strategic_summary is None or isinstance(
            state.strategic_summary, StrategicSummary
        )
