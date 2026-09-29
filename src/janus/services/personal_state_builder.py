"""Personal State Builder service for Janus.

Constructs the ``PersonalState`` aggregate from the canonical data files
(goals, tasks, followups, inbox) on demand. The aggregate is a read-model
— it is not persisted and is reconstructed on every access.

The builder follows the construction lifecycle from the spec (§3.3):
1. Read all source data files
2. Build domain models from raw data
3. Derive computed views (active goals, open tasks, stalled goals, etc.)
4. Run integrity checks (orphan detection, dangling references)
5. Compute strategic summary if requested
6. Return immutable ``PersonalState`` instance

Spec: docs/design/personal_state_model_spec.md
"""

from __future__ import annotations

import hashlib
import logging
from datetime import date, datetime
from pathlib import Path
from typing import Any

from janus.models.goal import Goal
from janus.models.task import Task, ALLOWED_STATES
from janus.models.follow_up import FollowUp
from janus.models.inbox import InboxItem
from janus.models.milestone import Milestone
from janus.models.project import Project
from janus.models.metric_snapshot import MetricSnapshot
from janus.models.recent_activity import RecentActivityEntry
from janus.models.goal_integrity_report import GoalIntegrityReport, GoalIntegrityIssue
from janus.models.strategic_summary import StrategicSummary, RecommendedAction
from janus.models.personal_state import PersonalState

logger = logging.getLogger(__name__)

# Project root for data-file access.
PROJECT_ROOT = Path(__file__).resolve().parents[3]

# Source data file paths (relative to project root).
GOALS_PATH = PROJECT_ROOT / "data" / "goals.md"
TASKS_PATH = PROJECT_ROOT / "data" / "tasks.md"
FOLLOWUPS_PATH = PROJECT_ROOT / "data" / "followups.md"
INBOX_PATH = PROJECT_ROOT / "data" / "inbox.md"


class PersonalStateBuilder:
    """Builds the ``PersonalState`` aggregate from canonical data files.

    The builder is a service-layer API — it is the single entry point for
    constructing the personal state read-model. It delegates to existing
    services for data loading, health assessment, and integrity checking,
    and assembles the results into a unified ``PersonalState`` instance.

    Usage:
        builder = PersonalStateBuilder()
        state = builder.build()
        print(f"Active goals: {len(state.active_goals)}")
        print(f"Open tasks: {len(state.open_tasks)}")
    """

    def __init__(
        self,
        goals_path: Path | None = None,
        tasks_path: Path | None = None,
        followups_path: Path | None = None,
        inbox_path: Path | None = None,
    ) -> None:
        """Initialize the builder with optional custom file paths.

        Args:
            goals_path: Path to goals.md. Defaults to the project-level path.
            tasks_path: Path to tasks.md. Defaults to the project-level path.
            followups_path: Path to followups.md. Defaults to the project-level path.
            inbox_path: Path to inbox.md. Defaults to the project-level path.
        """
        self._goals_path = goals_path or GOALS_PATH
        self._tasks_path = tasks_path or TASKS_PATH
        self._followups_path = followups_path or FOLLOWUPS_PATH
        self._inbox_path = inbox_path or INBOX_PATH

    def build(
        self,
        *,
        include_strategic_summary: bool = False,
        include_integrity_check: bool = True,
        today: date | None = None,
    ) -> PersonalState:
        """Construct the ``PersonalState`` aggregate.

        Args:
            include_strategic_summary: If True, compute and attach a
                ``StrategicSummary`` to the aggregate. Default False.
            include_integrity_check: If True, run the goal integrity audit
                and attach issues to the aggregate. Default True.
            today: Reference date for health/integrity checks. Defaults to
                ``date.today()``.

        Returns:
            A fully constructed ``PersonalState`` instance.

        Raises:
            FileNotFoundError: If a required data file is missing.
            ValueError: If a data file contains malformed data.
        """
        if today is None:
            today = date.today()

        # Step 1: Read all source data files.
        goals = self._load_goals()
        tasks = self._load_tasks()
        followups = self._load_followups()
        inbox_items = self._load_inbox()

        # Step 2: Build domain models (already done by loaders).
        # Step 3: Derive computed views.
        active_goals = self._derive_active_goals(goals)
        open_tasks = self._derive_open_tasks(tasks)
        blocked_tasks = self._derive_blocked_tasks(tasks)
        stalled_goals = self._derive_stalled_goals(goals, tasks, today)
        neglected_goals = self._derive_neglected_goals(goals, tasks, today)
        milestones = self._derive_milestones(goals)
        projects = self._derive_projects(goals)
        metric_snapshots = self._derive_metric_snapshots(goals)
        measurement_requirements = self._derive_measurement_requirements(goals)
        recent_activity = self._derive_recent_activity(goals)
        research_artifacts = self._derive_research_artifacts(goals)

        # Step 4: Run integrity checks.
        integrity_issues: list[GoalIntegrityIssue] = []
        if include_integrity_check:
            integrity_issues = self._run_integrity_check(goals, tasks)

        # Step 5: Compute strategic summary if requested.
        strategic_summary: StrategicSummary | None = None
        recommended_actions: list[RecommendedAction] = []
        if include_strategic_summary:
            strategic_summary = self._compute_strategic_summary(
                goals, tasks, today
            )
            recommended_actions = (
                strategic_summary.recommended_actions
                if strategic_summary
                else []
            )

        # Step 6: Compute fingerprint and return.
        fingerprint = self._compute_fingerprint()

        return PersonalState(
            generated_at=datetime.now().astimezone(),
            data_fingerprint=fingerprint,
            goals=goals,
            active_goals=active_goals,
            stalled_goals=stalled_goals,
            neglected_goals=neglected_goals,
            tasks=tasks,
            open_tasks=open_tasks,
            blocked_tasks=blocked_tasks,
            followups=followups,
            inbox_items=inbox_items,
            milestones=milestones,
            projects=projects,
            metric_snapshots=metric_snapshots,
            measurement_requirements=measurement_requirements,
            recent_activity=recent_activity,
            research_artifacts=research_artifacts,
            strategic_summary=strategic_summary,
            recommended_actions=recommended_actions,
            integrity_issues=integrity_issues,
        )

    def compute_fingerprint(self) -> str:
        """Compute the data fingerprint for cache invalidation.

        The fingerprint is a SHA-256 hash of all source data files. If any
        file changes, the fingerprint changes, enabling callers to detect
        when the aggregate needs to be rebuilt.

        Returns:
            A hex-encoded SHA-256 hash string.
        """
        return self._compute_fingerprint()

    # ── Data loading ─────────────────────────────────────────────────────────

    def _load_goals(self) -> list[Goal]:
        """Load goals from the goals data file."""
        from unittest.mock import patch

        from janus.integrations.markdown_goals import load_goals as _load

        # load_goals uses the module-level GOALS_PATH; we need to pass
        # our custom path. The loader accepts a trace_id parameter but
        # uses GOALS_PATH directly. We'll monkeypatch the module constant.
        import janus.integrations.markdown_goals as mg
        with patch.object(mg, "GOALS_PATH", self._goals_path):
            return _load()

    def _load_tasks(self) -> list[Task]:
        """Load tasks from the tasks data file."""
        from janus.integrations.markdown_tasks import load_tasks as _load

        # load_tasks accepts a path parameter.
        try:
            return _load(path=self._tasks_path)
        except FileNotFoundError:
            # If the file doesn't exist, return empty list (consistent
            # with load_goals behavior).
            return []

    def _load_followups(self) -> list[FollowUp]:
        """Load follow-ups from the followups data file."""
        from janus.integrations.markdown_followups import load_followups as _load

        # load_followups accepts a path parameter.
        try:
            return _load(path=self._followups_path)
        except FileNotFoundError:
            return []

    def _load_inbox(self) -> list[InboxItem]:
        """Load inbox items from the inbox data file."""
        from janus.integrations.markdown_inbox import load_inbox_items as _load

        # load_inbox_items accepts a path parameter.
        try:
            return _load(path=self._inbox_path)
        except FileNotFoundError:
            return []

    # ── Derived views ────────────────────────────────────────────────────────

    def _derive_active_goals(self, goals: list[Goal]) -> list[Goal]:
        """Derive active goals (status == 'active')."""
        return [g for g in goals if g.status == "active"]

    def _derive_open_tasks(self, tasks: list[Task]) -> list[Task]:
        """Derive open tasks (state in ALLOWED_STATES or None, which means todo)."""
        return [t for t in tasks if (t.state or "todo") in ALLOWED_STATES]

    def _derive_blocked_tasks(self, tasks: list[Task]) -> list[Task]:
        """Derive blocked tasks (state == 'blocked')."""
        return [t for t in tasks if t.state == "blocked"]

    def _derive_stalled_goals(
        self,
        goals: list[Goal],
        tasks: list[Task],
        today: date,
    ) -> list[Goal]:
        """Derive stalled goals based on health signals.

        A goal is stalled if its health assessment reports a 'stalled' state.
        This delegates to the existing ``assess_goal_health()`` service.
        """
        from janus.services.goal_health import assess_goal_health

        stalled: list[Goal] = []
        for goal in goals:
            if goal.status != "active":
                continue
            assessment = assess_goal_health(
                goal,
                today,
                open_task_titles={t.title for t in tasks},
                all_task_titles={t.title for t in tasks},
            )
            if assessment and assessment.health_state == "stalled":
                stalled.append(goal)
        return stalled

    def _derive_neglected_goals(
        self,
        goals: list[Goal],
        tasks: list[Task],
        today: date,
    ) -> list[Goal]:
        """Derive neglected goals based on inactivity signals.

        A goal is neglected if it has no recent activity and no open tasks.
        This delegates to the existing ``assess_goal_health()`` service.
        """
        from janus.services.goal_health import assess_goal_health

        neglected: list[Goal] = []
        for goal in goals:
            if goal.status != "active":
                continue
            assessment = assess_goal_health(
                goal,
                today,
                open_task_titles={t.title for t in tasks},
                all_task_titles={t.title for t in tasks},
            )
            if assessment and assessment.health_state == "watch":
                # A goal in 'watch' state with no open related tasks is neglected.
                has_open_related = any(
                    t.title in (goal.related_tasks or [])
                    for t in tasks
                )
                if not has_open_related:
                    neglected.append(goal)
        return neglected

    def _derive_milestones(self, goals: list[Goal]) -> list[Milestone]:
        """Derive milestones from goals."""
        milestones: list[Milestone] = []
        for goal in goals:
            for ms_dict in (goal.milestones or []):
                if isinstance(ms_dict, dict):
                    milestone = Milestone(
                        title=ms_dict.get("title", ""),
                        goal_title=goal.title,
                        description=ms_dict.get("description", ""),
                        deadline=ms_dict.get("deadline"),
                        status=ms_dict.get("status", "open"),
                        order=ms_dict.get("order", 0),
                    )
                    milestones.append(milestone)
        return milestones

    def _derive_projects(self, goals: list[Goal]) -> list[Project]:
        """Derive projects from goals."""
        projects: list[Project] = []
        for goal in goals:
            for proj_dict in (goal.projects or []):
                if isinstance(proj_dict, dict):
                    project = Project(
                        title=proj_dict.get("title", ""),
                        milestone_title=proj_dict.get("milestone_title", ""),
                        description=proj_dict.get("description", ""),
                        deadline=proj_dict.get("deadline"),
                        status=proj_dict.get("status", "open"),
                        order=proj_dict.get("order", 0),
                        related_tasks=proj_dict.get("related_tasks", []),
                    )
                    projects.append(project)
        return projects

    def _derive_metric_snapshots(
        self, goals: list[Goal]
    ) -> list[MetricSnapshot]:
        """Derive metric snapshots from goals."""
        from janus.integrations.metric_history import get_metric_snapshots

        snapshots: list[MetricSnapshot] = []
        for goal in goals:
            if goal.metric_name:
                snapshots.extend(get_metric_snapshots(goal.title))
        return snapshots

    def _derive_measurement_requirements(
        self, goals: list[Goal]
    ) -> list[dict]:
        """Derive measurement requirements from goals."""
        requirements: list[dict] = []
        for goal in goals:
            for req in (goal.measurement_requirements or []):
                if isinstance(req, dict):
                    requirements.append(req)
        return requirements

    def _derive_recent_activity(
        self, goals: list[Goal]
    ) -> list[RecentActivityEntry]:
        """Derive recent activity entries from goals."""
        entries: list[RecentActivityEntry] = []
        for goal in goals:
            for entry_dict in (goal.recent_activity or []):
                if isinstance(entry_dict, dict):
                    entry = RecentActivityEntry(
                        task_id=entry_dict.get("task_id", ""),
                        summary=entry_dict.get("summary", ""),
                        completed_at=entry_dict.get("completed_at", ""),
                        changed_files=entry_dict.get("changed_files", []),
                        tests_passed=entry_dict.get("tests_passed"),
                        pr_url=entry_dict.get("pr_url"),
                    )
                    entries.append(entry)
        return entries

    def _derive_research_artifacts(self, goals: list[Goal]) -> list[str]:
        """Derive research artifact titles linked to goals."""
        titles: set[str] = set()
        for goal in goals:
            titles.update(goal.research_artifact_titles or [])
        return sorted(titles)

    # ── Integrity check ──────────────────────────────────────────────────────

    def _run_integrity_check(
        self,
        goals: list[Goal],
        tasks: list[Task],
    ) -> list[GoalIntegrityIssue]:
        """Run the goal integrity audit and return issues."""
        from janus.services.goal_integrity import audit_goal_integrity

        report = audit_goal_integrity(goals, tasks)
        return report.issues

    # ── Strategic summary ────────────────────────────────────────────────────

    def _compute_strategic_summary(
        self,
        goals: list[Goal],
        tasks: list[Task],
        today: date,
    ) -> StrategicSummary | None:
        """Compute the strategic summary from goals and tasks."""
        from janus.services.strategic_summary import build_strategic_snapshot

        try:
            open_task_titles = {t.title for t in tasks if t.state in ALLOWED_STATES}
            all_task_titles = {t.title for t in tasks}
            snapshot = build_strategic_snapshot(
                goals, today, open_task_titles, all_task_titles
            )
            # Build a StrategicSummary from the snapshot.
            # The snapshot contains GoalStateSnapshot objects; we need to
            # convert them to the StrategicSummary format.
            from janus.models.strategic_summary import (
                StalledGoal,
                NeglectedGoal,
                PortfolioHealthCounts,
            )

            stalled_goals: list[StalledGoal] = []
            neglected_goals: list[NeglectedGoal] = []
            counts = PortfolioHealthCounts()

            for gs in snapshot.goals:
                if gs.goal_status == "active":
                    counts.total_active += 1
                    if gs.health_state == "healthy":
                        counts.healthy += 1
                    elif gs.health_state == "watch":
                        counts.watch += 1
                    elif gs.health_state == "stalled":
                        counts.stalled += 1
                        stalled_goals.append(StalledGoal(
                            goal_title=gs.goal_title,
                            health_state=gs.health_state or "unknown",
                            dominant_signal=gs.dominant_signal or "unknown",
                            dominant_signal_score=gs.dominant_signal_score,
                            dominant_signal_reason="",
                            progress=gs.progress,
                            progress_delta=gs.progress_delta,
                            days_since_last_activity=gs.days_since_last_activity,
                            measurement_overdue_count=gs.measurement_overdue_count,
                        ))
                    elif gs.health_state == "watch":
                        neglected_goals.append(NeglectedGoal(
                            goal_title=gs.goal_title,
                            health_state=gs.health_state or "unknown",
                            dominant_signal=gs.dominant_signal or "unknown",
                            dominant_signal_score=gs.dominant_signal_score,
                            dominant_signal_reason="",
                            progress=gs.progress,
                            progress_delta=gs.progress_delta,
                            days_since_last_activity=gs.days_since_last_activity,
                            measurement_overdue_count=gs.measurement_overdue_count,
                        ))
                elif gs.goal_status == "completed":
                    counts.completed += 1
                elif gs.goal_status == "inactive":
                    counts.inactive += 1

            return StrategicSummary(
                generated_at=snapshot.generated_at,
                portfolio_health_counts=counts,
                stalled_goals=stalled_goals,
                neglected_goals=neglected_goals,
            )
        except Exception as exc:
            logger.warning("Failed to compute strategic summary: %s", exc)
            return None

    # ── Fingerprint ──────────────────────────────────────────────────────────

    def _compute_fingerprint(self) -> str:
        """Compute SHA-256 fingerprint of all source data files.

        The fingerprint covers: goals.md, tasks.md, followups.md, inbox.md.
        If a file is missing, it is represented by a placeholder string
        so the fingerprint still changes when the file is created.

        Returns:
            A hex-encoded SHA-256 hash string.
        """
        hasher = hashlib.sha256()
        for path in [
            self._goals_path,
            self._tasks_path,
            self._followups_path,
            self._inbox_path,
        ]:
            if path.exists():
                content = path.read_bytes()
                hasher.update(content)
            else:
                # Represent missing files with a stable placeholder.
                hasher.update(f"MISSING:{path.name}".encode())
        return hasher.hexdigest()
