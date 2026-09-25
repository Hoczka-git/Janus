"""Tests for the strategic summary service and CLI.

Implements the acceptance criteria from
``docs/design/strategic_summary_spec.md`` §6 and §7.

Covers:
- StrategicSummary model and JSON serialization.
- Portfolio health counts and edge cases.
- Stalled-work detection using existing health signals.
- Neglected-goal detection and severity ranking.
- Cross-domain links: research artifacts, decisions, follow-ups.
- Recommended actions.
- Strategic summary rendering.
- Deadline/milestone handling.
- Compatibility with pre-computed assessments and summary inputs.
"""

from dataclasses import asdict
from datetime import date, datetime, timedelta, timezone

import pytest

from janus.models.goal import Goal
from janus.models.goal_health_assessment import GoalHealthAssessment
from janus.models.goal_signal import GoalSignal
from janus.models.strategic_summary import (
    CrossDomainLink,
    NeglectedGoal,
    PortfolioHealthCounts,
    RecommendedAction,
    StalledGoal,
    StrategicSummary,
)
from janus.services.strategic_summary import (
    _compute_portfolio_health_counts,
    _has_upcoming_milestone_or_deadline,
    create_strategic_summary,
    render_strategic_summary,
)


FIXED_TODAY = date(2026, 9, 6)
FIXED_NOW = datetime(
    2026,
    9,
    6,
    12,
    0,
    0,
    tzinfo=timezone.utc,
)


# ── Test helpers ──────────────────────────────────────────────────────────────


def _make_goal(
    title="Test goal",
    status="active",
    deadline=None,
    related_tasks=None,
    milestones=None,
    metric_name=None,
    metric_unit=None,
    start_value=None,
    current_value=None,
    target_value=None,
    direction=None,
    measurement_requirements=None,
    inactivity_window_days=None,
    **kw,
):
    """Create a Goal with sensible defaults for tests."""

    return Goal(
        title=title,
        status=status,
        deadline=deadline,
        related_tasks=related_tasks or [],
        milestones=milestones or [],
        metric_name=metric_name,
        metric_unit=metric_unit,
        start_value=start_value,
        current_value=current_value,
        target_value=target_value,
        direction=direction,
        measurement_requirements=measurement_requirements or [],
        inactivity_window_days=inactivity_window_days,
        **kw,
    )


def _make_metric_goal(**kw):
    defaults = dict(
        title="Body fat",
        metric_name="Body fat %",
        metric_unit="%",
        start_value=23.0,
        current_value=20.0,
        target_value=15.0,
        direction="decrease",
    )
    defaults.update(kw)
    return _make_goal(**defaults)


def _make_assessment(
    goal_title,
    health_state="healthy",
    dominant_signal=None,
    progress=None,
    progress_delta=None,
    days_since_last_activity=None,
    measurement_overdue_count=0,
    signals=None,
):
    return GoalHealthAssessment(
        goal_title=goal_title,
        health_state=health_state,
        signals=signals or [],
        dominant_signal=dominant_signal,
        progress=progress,
        progress_delta=progress_delta,
        days_since_last_activity=days_since_last_activity,
        measurement_overdue_count=measurement_overdue_count,
        evaluated_at=FIXED_NOW,
    )


def _sig(
    signal,
    score=40,
    reason="test reason",
):
    return GoalSignal(
        signal=signal,
        score=score,
        reason=reason,
        timestamp=FIXED_NOW,
    )


def _snap(
    goal_title,
    metric_name,
    value,
    days_ago,
    source="manual",
):
    ts = FIXED_NOW - timedelta(days=days_ago)

    from janus.models.metric_snapshot import MetricSnapshot

    return MetricSnapshot(
        timestamp=ts,
        goal_title=goal_title,
        metric_name=metric_name,
        value=value,
        source=source,
    )


# ===========================================================================
# PortfolioHealthCounts
# ===========================================================================


class TestPortfolioHealthCounts:
    def test_defaults_zero(self):
        counts = PortfolioHealthCounts()

        assert counts.total_active == 0
        assert counts.healthy == 0
        assert counts.watch == 0
        assert counts.stalled == 0
        assert counts.completed == 0
        assert counts.inactive == 0

    def test_serializes_to_dict(self):
        counts = PortfolioHealthCounts(
            total_active=2,
            healthy=1,
            stalled=1,
            completed=1,
        )

        result = counts.to_dict()

        assert result["total_active"] == 2
        assert result["healthy"] == 1
        assert result["stalled"] == 1
        assert result["completed"] == 1


# ===========================================================================
# _compute_portfolio_health_counts
# ===========================================================================


class TestComputePortfolioHealthCounts:
    def test_counts_by_state(self):
        goals = [
            _make_goal(title="G1", status="active"),
            _make_goal(title="G2", status="active"),
            _make_goal(title="G3", status="active"),
            _make_goal(title="Done", status="completed"),
            _make_goal(title="Paused", status="inactive"),
        ]

        assessments = [
            _make_assessment(
                "G1",
                health_state="healthy",
            ),
            _make_assessment(
                "G2",
                health_state="watch",
            ),
            _make_assessment(
                "G3",
                health_state="stalled",
                dominant_signal=_sig(
                    "goal_overdue",
                    100,
                ),
            ),
        ]

        counts = _compute_portfolio_health_counts(
            goals,
            assessments,
        )

        assert counts.total_active == 3
        assert counts.healthy == 1
        assert counts.watch == 1
        assert counts.stalled == 1
        assert counts.completed == 1
        assert counts.inactive == 1

    def test_all_completed(self):
        """All goals completed → empty active portfolio."""
        goals = [
            _make_goal(
                title="G1",
                status="completed",
            )
        ]

        counts = _compute_portfolio_health_counts(
            goals,
            [],
        )

        assert counts.total_active == 0
        assert counts.completed == 1
        assert counts.stalled == 0
        assert counts.watch == 0

    def test_all_inactive_excluded_from_health(self):
        """Inactive goals are excluded from health evaluation."""
        goals = [
            _make_goal(
                title="G1",
                status="inactive",
            )
        ]

        counts = _compute_portfolio_health_counts(
            goals,
            [],
        )

        assert counts.total_active == 0
        assert counts.inactive == 1
        assert counts.healthy == 0


# ===========================================================================
# StrategicSummary model
# ===========================================================================


class TestStrategicSummaryModel:
    def test_model_has_all_fields(self):
        """StrategicSummary has all five sections."""
        now = datetime.now(timezone.utc)

        counts = PortfolioHealthCounts(
            total_active=2,
            healthy=1,
            watch=1,
        )

        summary = StrategicSummary(
            generated_at=now,
            portfolio_health_counts=counts,
        )

        assert summary.generated_at == now
        assert summary.portfolio_health_counts == counts
        assert summary.stalled_goals == []
        assert summary.neglected_goals == []
        assert summary.recommended_actions == []
        assert summary.cross_domain_links == []

    def test_serializes_to_dict(self):
        """StrategicSummary serializes to a nested dictionary."""
        now = datetime.now(timezone.utc)

        summary = StrategicSummary(
            generated_at=now,
            portfolio_health_counts=PortfolioHealthCounts(),
            stalled_goals=[
                StalledGoal(
                    goal_title="G",
                    health_state="stalled",
                    dominant_signal="goal_overdue",
                    dominant_signal_score=100,
                    dominant_signal_reason="passed",
                )
            ],
            neglected_goals=[
                NeglectedGoal(
                    goal_title="G",
                    health_state="stalled",
                    dominant_signal="goal_overdue",
                    dominant_signal_score=100,
                    dominant_signal_reason="passed",
                )
            ],
            recommended_actions=[
                RecommendedAction(
                    goal_title="G",
                    health_state="stalled",
                    dominant_signal="goal_overdue",
                    dominant_signal_score=100,
                    dominant_signal_reason="passed",
                )
            ],
            cross_domain_links=[
                CrossDomainLink(
                    goal_title="G",
                    category="decision",
                    title="ADR-001",
                )
            ],
        )

        result = summary.to_dict()

        assert result["portfolio_health_counts"]["total_active"] == 0
        assert len(result["stalled_goals"]) == 1
        assert result["stalled_goals"][0]["goal_title"] == "G"
        assert len(result["recommended_actions"]) == 1
        assert len(result["cross_domain_links"]) == 1
        assert result["cross_domain_links"][0]["category"] == "decision"

        # Also ensure the dataclass representation is structurally compatible.
        assert asdict(summary)["generated_at"] == now


# ===========================================================================
# create_strategic_summary
# ===========================================================================


class TestCreateStrategicSummary:
    def test_aggregates_assessments_and_links(self):
        """Summary aggregates assessments and cross-domain links."""
        goals = [
            _make_goal(
                title="G",
                related_tasks=["Task A"],
            )
        ]

        dominant = _sig(
            "goal_stalled",
            40,
            "All tasks done",
        )

        assessments = [
            _make_assessment(
                "G",
                health_state="stalled",
                dominant_signal=dominant,
                progress=0.0,
                progress_delta=0.0,
                days_since_last_activity=5,
            )
        ]

        links = [
            CrossDomainLink(
                goal_title="G",
                category="decision",
                title="ADR-001",
            )
        ]

        summary = create_strategic_summary(
            goals=goals,
            assessments=assessments,
            cross_links=links,
            today=FIXED_TODAY,
            now=FIXED_NOW,
        )

        assert summary.generated_at == FIXED_NOW
        assert summary.portfolio_health_counts.stalled == 1
        assert summary.portfolio_health_counts.watch == 0

        assert len(summary.stalled_goals) == 1
        assert summary.stalled_goals[0].goal_title == "G"
        assert summary.stalled_goals[0].health_state == "stalled"

        assert len(summary.cross_domain_links) == 1
        assert summary.cross_domain_links[0].category == "decision"
        assert summary.cross_domain_links[0].title == "ADR-001"

    def test_all_healthy_returns_empty_stalled_and_recommendations(self):
        """All healthy goals produce no stalled or recommended actions."""
        goals = [
            _make_goal(
                title="G1",
                related_tasks=["A"],
            ),
            _make_goal(
                title="G2",
                related_tasks=["B"],
            ),
        ]

        assessments = [
            _make_assessment(
                "G1",
                health_state="healthy",
            ),
            _make_assessment(
                "G2",
                health_state="healthy",
            ),
        ]

        summary = create_strategic_summary(
            goals=goals,
            assessments=assessments,
            today=FIXED_TODAY,
            now=FIXED_NOW,
        )

        assert summary.stalled_goals == []
        assert summary.neglected_goals == []
        assert summary.recommended_actions == []
        assert summary.portfolio_health_counts.healthy == 2

    def test_stalled_goal_produces_recommendation(self):
        """A stalled goal produces a recommended action."""
        goals = [
            _make_goal(
                title="G",
                related_tasks=["Task A"],
            )
        ]

        assessments = [
            _make_assessment(
                "G",
                health_state="stalled",
                dominant_signal=_sig(
                    "goal_overdue",
                    100,
                    "passed deadline",
                ),
                progress=0.0,
                progress_delta=0.0,
                days_since_last_activity=5,
            )
        ]

        summary = create_strategic_summary(
            goals=goals,
            assessments=assessments,
            today=FIXED_TODAY,
            now=FIXED_NOW,
        )

        assert len(summary.recommended_actions) == 1
        assert summary.recommended_actions[0].goal_title == "G"
        assert (
            summary.recommended_actions[0].health_state
            == "stalled"
        )

    def test_stalled_goal_recommendation_populated_with_remediation(self):
        """End-to-end: create_strategic_summary derives remediation_action
        from the health assessment through create_recommended_actions."""

        goals = [
            _make_goal(
                title="G",
                related_tasks=["Task A"],
            )
        ]

        assessments = [
            _make_assessment(
                "G",
                health_state="stalled",
                dominant_signal=_sig(
                    "goal_overdue",
                    100,
                    "passed deadline",
                ),
                progress=0.0,
                progress_delta=0.0,
                days_since_last_activity=5,
            )
        ]

        summary = create_strategic_summary(
            goals=goals,
            assessments=assessments,
            today=FIXED_TODAY,
            now=FIXED_NOW,
        )

        assert len(summary.recommended_actions) == 1
        assert summary.recommended_actions[0].remediation_action is not None
        assert "Deadline has passed" in summary.recommended_actions[0].remediation_action

    def test_stalled_goal_appears_in_stalled_and_recommendations(self):
        """An overdue active goal is surfaced in both sections."""
        goal = _make_goal(
            title="Stalled G",
            related_tasks=["Task A"],
            deadline="2026-08-30",
        )

        summary = create_strategic_summary(
            goals=[goal],
            today=FIXED_TODAY,
            now=FIXED_NOW,
            open_task_titles=set(),
            all_task_titles={"Task A"},
            metric_snapshots_by_goal={},
            followups=[],
            research_artifacts=[],
            decisions=[],
            attention_items=[],
            recommendations=[],
            goal_reviews=[],
        )

        assert len(summary.stalled_goals) == 1
        assert summary.stalled_goals[0].goal_title == "Stalled G"
        assert summary.stalled_goals[0].dominant_signal == "goal_overdue"

        assert len(summary.recommended_actions) == 1
        assert summary.recommended_actions[0].goal_title == "Stalled G"

    def test_all_healthy_returns_empty(self):
        """All healthy goals produce empty stalled/neglected/recommendations."""
        goal = _make_goal(
            title="Healthy G",
            related_tasks=["Task A"],
            deadline="2026-09-20",
        )

        summary = create_strategic_summary(
            goals=[goal],
            today=FIXED_TODAY,
            now=FIXED_NOW,
            open_task_titles={"Task A"},
            all_task_titles={"Task A"},
            metric_snapshots_by_goal={},
            followups=[],
            research_artifacts=[],
            decisions=[],
            attention_items=[],
            recommendations=[],
            goal_reviews=[],
        )

        assert summary.stalled_goals == []
        assert summary.neglected_goals == []
        assert summary.recommended_actions == []
        assert summary.portfolio_health_counts.healthy == 1

    def test_all_completed_empty_portfolio(self):
        """All completed goals produce an empty active portfolio."""
        goals = [
            _make_goal(
                title="G1",
                status="completed",
            )
        ]

        summary = create_strategic_summary(
            goals=goals,
            assessments=[],
            today=FIXED_TODAY,
            now=FIXED_NOW,
        )

        assert summary.portfolio_health_counts.total_active == 0
        assert summary.portfolio_health_counts.completed == 1
        assert summary.stalled_goals == []
        assert summary.neglected_goals == []
        assert summary.recommended_actions == []

    def test_all_completed_returns_empty_portfolio(self):
        """All completed goals are excluded from action lists."""
        goal = _make_goal(
            title="Done",
            status="completed",
            related_tasks=["Task A"],
        )

        summary = create_strategic_summary(
            goals=[goal],
            today=FIXED_TODAY,
            now=FIXED_NOW,
            open_task_titles=set(),
            all_task_titles={"Task A"},
            metric_snapshots_by_goal={},
            followups=[],
            research_artifacts=[],
            decisions=[],
            attention_items=[],
            recommendations=[],
            goal_reviews=[],
        )

        assert summary.stalled_goals == []
        assert summary.neglected_goals == []
        assert summary.recommended_actions == []
        assert summary.portfolio_health_counts.completed == 1

    def test_all_inactive_empty_portfolio(self):
        """All inactive goals are excluded from health evaluation."""
        goals = [
            _make_goal(
                title="G1",
                status="inactive",
            )
        ]

        summary = create_strategic_summary(
            goals=goals,
            assessments=[],
            today=FIXED_TODAY,
            now=FIXED_NOW,
        )

        assert summary.portfolio_health_counts.total_active == 0
        assert summary.portfolio_health_counts.inactive == 1
        assert summary.stalled_goals == []
        assert summary.neglected_goals == []
        assert summary.recommended_actions == []

    def test_all_inactive_excluded(self):
        """All inactive goals are excluded from action lists."""
        goal = _make_goal(
            title="Paused",
            status="inactive",
            related_tasks=["Task A"],
        )

        summary = create_strategic_summary(
            goals=[goal],
            today=FIXED_TODAY,
            now=FIXED_NOW,
            open_task_titles=set(),
            all_task_titles={"Task A"},
            metric_snapshots_by_goal={},
            followups=[],
            research_artifacts=[],
            decisions=[],
            attention_items=[],
            recommendations=[],
            goal_reviews=[],
        )

        assert summary.stalled_goals == []
        assert summary.neglected_goals == []
        assert summary.recommended_actions == []
        assert summary.portfolio_health_counts.inactive == 1
        assert summary.portfolio_health_counts.total_active == 0

    def test_neglected_goals_exclude_inactive_and_completed(self):
        """Inactive and completed goals are excluded from neglected."""
        goals = [
            _make_goal(
                title="Paused",
                status="inactive",
            ),
            _make_goal(
                title="Done",
                status="completed",
            ),
        ]

        assessments = [
            _make_assessment(
                "Paused",
                health_state="watch",
                dominant_signal=_sig(
                    "progress_slow",
                    40,
                ),
            ),
            _make_assessment(
                "Done",
                health_state="stalled",
                dominant_signal=_sig(
                    "goal_overdue",
                    100,
                ),
            ),
        ]

        summary = create_strategic_summary(
            goals=goals,
            assessments=assessments,
            today=FIXED_TODAY,
            now=FIXED_NOW,
        )

        assert summary.stalled_goals == []
        assert summary.neglected_goals == []

    def test_serializes_to_dict(self):
        """StrategicSummary exposes all expected sections."""
        summary = create_strategic_summary(
            goals=[],
            assessments=[],
            today=FIXED_TODAY,
            now=FIXED_NOW,
        )

        result = summary.to_dict()

        assert "generated_at" in result
        assert "portfolio_health_counts" in result
        assert "stalled_goals" in result
        assert "neglected_goals" in result
        assert "recommended_actions" in result
        assert "cross_domain_links" in result
        assert result["stalled_goals"] == []

    def test_stalled_sorted_by_score_desc(self):
        """Stalled goals are sorted by dominant signal score."""
        goals = [
            _make_goal(title="G1"),
            _make_goal(title="G2"),
        ]

        assessments = [
            _make_assessment(
                "G1",
                health_state="stalled",
                dominant_signal=_sig(
                    "goal_stalled",
                    40,
                ),
            ),
            _make_assessment(
                "G2",
                health_state="stalled",
                dominant_signal=_sig(
                    "goal_overdue",
                    100,
                ),
            ),
        ]

        summary = create_strategic_summary(
            goals=goals,
            assessments=assessments,
            today=FIXED_TODAY,
            now=FIXED_NOW,
        )

        assert summary.stalled_goals[0].goal_title == "G2"
        assert summary.stalled_goals[1].goal_title == "G1"


# ===========================================================================
# Neglected goals
# ===========================================================================


class TestNeglectedGoals:
    def test_watch_goal_with_no_activity_is_neglected(self):
        """A watch goal without active strategic attention is neglected."""
        goal = _make_metric_goal(
            title="Slow Progress",
            deadline=None,
            related_tasks=[],
        )

        snapshots = {
            "Slow Progress": [
                _snap(
                    "Slow Progress",
                    "Body fat %",
                    20.0,
                    15,
                )
            ]
        }

        summary = create_strategic_summary(
            goals=[goal],
            today=FIXED_TODAY,
            now=FIXED_NOW,
            open_task_titles=set(),
            all_task_titles=set(),
            metric_snapshots_by_goal=snapshots,
            followups=[],
            research_artifacts=[],
            decisions=[],
            attention_items=[],
            recommendations=[],
            goal_reviews=[],
        )

        assert len(summary.neglected_goals) == 1
        assert summary.neglected_goals[0].health_state == "watch"
        assert summary.neglected_goals[0].goal_title == "Slow Progress"

    def test_completed_goal_not_in_neglected(self):
        """Completed goals are never neglected."""
        goal = _make_goal(
            title="Done",
            status="completed",
            related_tasks=["Task A"],
        )

        summary = create_strategic_summary(
            goals=[goal],
            today=FIXED_TODAY,
            now=FIXED_NOW,
            open_task_titles=set(),
            all_task_titles={"Task A"},
            metric_snapshots_by_goal={},
            followups=[],
            research_artifacts=[],
            decisions=[],
            attention_items=[],
            recommendations=[],
            goal_reviews=[],
        )

        assert all(
            item.goal_title != "Done"
            for item in summary.neglected_goals
        )

    def test_inactive_goal_not_in_neglected(self):
        """Inactive goals are never neglected."""
        goal = _make_goal(
            title="Paused",
            status="inactive",
            related_tasks=["Task A"],
        )

        summary = create_strategic_summary(
            goals=[goal],
            today=FIXED_TODAY,
            now=FIXED_NOW,
            open_task_titles=set(),
            all_task_titles={"Task A"},
            metric_snapshots_by_goal={},
            followups=[],
            research_artifacts=[],
            decisions=[],
            attention_items=[],
            recommendations=[],
            goal_reviews=[],
        )

        assert all(
            item.goal_title != "Paused"
            for item in summary.neglected_goals
        )

    def test_severity_ranking_stalled_before_watch(self):
        """Neglected goals rank stalled before watch."""
        stalled_goal = _make_goal(
            title="Stalled G",
            related_tasks=["Task A"],
        )

        req = {
            "metric": "weight",
            "unit": "kg",
            "frequency": "daily",
        }

        watch_goal = _make_goal(
            title="Watch G",
            related_tasks=["Task B"],
            metric_name="weight",
            measurement_requirements=[req],
        )

        summary = create_strategic_summary(
            goals=[
                stalled_goal,
                watch_goal,
            ],
            today=FIXED_TODAY,
            now=FIXED_NOW,
            open_task_titles=set(),
            all_task_titles={
                "Task A",
                "Task B",
            },
            metric_snapshots_by_goal={},
            followups=[],
            research_artifacts=[],
            decisions=[],
            attention_items=[],
            recommendations=[],
            goal_reviews=[],
        )

        assert len(summary.neglected_goals) == 2
        assert (
            summary.neglected_goals[0].health_state
            == "stalled"
        )
        assert (
            summary.neglected_goals[1].health_state
            == "watch"
        )


# ===========================================================================
# Stalled detection
# ===========================================================================


class TestStalledDetection:
    def test_goal_stalled_signal(self):
        """goal_stalled signal produces a stalled goal."""
        goal = _make_goal(
            title="G",
            related_tasks=["Task A"],
        )

        summary = create_strategic_summary(
            goals=[goal],
            today=FIXED_TODAY,
            now=FIXED_NOW,
            open_task_titles=set(),
            all_task_titles={"Task A"},
            metric_snapshots_by_goal={},
            followups=[],
            research_artifacts=[],
            decisions=[],
            attention_items=[],
            recommendations=[],
            goal_reviews=[],
        )

        stalled = [
            item
            for item in summary.stalled_goals
            if item.goal_title == "G"
        ]

        assert stalled

        stalled_goal = stalled[0]

        assert stalled_goal.dominant_signal == "goal_stalled"
        assert stalled_goal.dominant_signal_score == 40

    def test_goal_overdue_signal(self):
        """goal_overdue signal produces a stalled goal."""
        goal = _make_goal(
            title="Overdue",
            deadline="2026-08-30",
            related_tasks=["Task A"],
        )

        summary = create_strategic_summary(
            goals=[goal],
            today=FIXED_TODAY,
            now=FIXED_NOW,
            open_task_titles=set(),
            all_task_titles={"Task A"},
            metric_snapshots_by_goal={},
            followups=[],
            research_artifacts=[],
            decisions=[],
            attention_items=[],
            recommendations=[],
            goal_reviews=[],
        )

        stalled = [
            item
            for item in summary.stalled_goals
            if item.goal_title == "Overdue"
        ]

        assert stalled

        stalled_goal = stalled[0]

        assert stalled_goal.dominant_signal == "goal_overdue"
        assert stalled_goal.dominant_signal_score == 100

    def test_no_recent_activity_signal(self):
        """no_recent_activity signal produces a stalled goal."""
        goal = _make_metric_goal(
            title="Inactive metric"
        )

        summary = create_strategic_summary(
            goals=[goal],
            today=FIXED_TODAY,
            now=FIXED_NOW,
            open_task_titles=set(),
            all_task_titles=set(),
            metric_snapshots_by_goal={},
            followups=[],
            research_artifacts=[],
            decisions=[],
            attention_items=[],
            recommendations=[],
            goal_reviews=[],
        )

        stalled = [
            item
            for item in summary.stalled_goals
            if item.goal_title == "Inactive metric"
        ]

        assert stalled

        stalled_goal = stalled[0]

        assert (
            stalled_goal.dominant_signal
            == "no_recent_activity"
        )

    def test_stalled_sorted_by_score_desc(self):
        """Stalled goals are sorted by dominant signal score."""
        g1 = _make_goal(
            title="G1",
            related_tasks=["Task A"],
        )

        g2 = _make_goal(
            title="G2",
            deadline="2026-08-30",
            related_tasks=["Task B"],
        )

        summary = create_strategic_summary(
            goals=[g1, g2],
            today=FIXED_TODAY,
            now=FIXED_NOW,
            open_task_titles=set(),
            all_task_titles={
                "Task A",
                "Task B",
            },
            metric_snapshots_by_goal={},
            followups=[],
            research_artifacts=[],
            decisions=[],
            attention_items=[],
            recommendations=[],
            goal_reviews=[],
        )

        assert len(summary.stalled_goals) == 2
        assert (
            summary.stalled_goals[0].dominant_signal_score
            >= summary.stalled_goals[1].dominant_signal_score
        )
        assert summary.stalled_goals[0].goal_title == "G2"


# ===========================================================================
# Cross-domain links
# ===========================================================================


class TestCrossDomainLinks:
    def test_cross_domain_links_from_precomputed_input(self):
        """Precomputed cross-domain links are preserved."""
        goal = _make_goal(
            title="G"
        )

        links = [
            CrossDomainLink(
                goal_title="G",
                category="research_artifact",
                title="Note A",
            ),
            CrossDomainLink(
                goal_title="G",
                category="decision",
                title="ADR-001",
            ),
            CrossDomainLink(
                goal_title="G",
                category="follow_up",
                title="Follow-up 1",
            ),
        ]

        summary = create_strategic_summary(
            goals=[goal],
            assessments=[],
            cross_links=links,
            today=FIXED_TODAY,
            now=FIXED_NOW,
        )

        assert len(summary.cross_domain_links) == 3

        categories = {
            link.category
            for link in summary.cross_domain_links
        }

        assert categories == {
            "research_artifact",
            "decision",
            "follow_up",
        }

    def test_research_artifact_link(self):
        """Research artifact links surface in the summary."""
        from janus.models.research_artifact import ResearchArtifact

        goal = _make_goal(
            title="My Goal",
            related_tasks=["Task A"],
        )

        artifact = ResearchArtifact(
            title="Research Note",
            linked_goal_titles=["My Goal"],
        )

        summary = create_strategic_summary(
            goals=[goal],
            today=FIXED_TODAY,
            now=FIXED_NOW,
            open_task_titles=set(),
            all_task_titles=set(),
            metric_snapshots_by_goal={},
            followups=[],
            research_artifacts=[artifact],
            decisions=[],
            attention_items=[],
            recommendations=[],
            goal_reviews=[],
        )

        link = next(
            (
                item
                for item in summary.cross_domain_links
                if (
                    item.goal_title == "My Goal"
                    and item.category == "research_artifact"
                )
            ),
            None,
        )

        assert link is not None
        assert link.title == "Research Note"

    def test_decision_link(self):
        """Decision links surface in the summary."""
        from janus.models.decision import Decision

        goal = _make_goal(
            title="My Goal",
            related_tasks=["Task A"],
        )

        decision = Decision(
            adr_number="001",
            title="ADR Title",
            goal_titles=["My Goal"],
        )

        summary = create_strategic_summary(
            goals=[goal],
            today=FIXED_TODAY,
            now=FIXED_NOW,
            open_task_titles=set(),
            all_task_titles=set(),
            metric_snapshots_by_goal={},
            followups=[],
            research_artifacts=[],
            decisions=[decision],
            attention_items=[],
            recommendations=[],
            goal_reviews=[],
        )

        link = next(
            (
                item
                for item in summary.cross_domain_links
                if (
                    item.goal_title == "My Goal"
                    and item.category == "decision"
                )
            ),
            None,
        )

        assert link is not None
        assert link.title == "ADR Title"

    def test_followup_link(self):
        """Follow-up links surface in the summary."""
        from janus.models.follow_up import FollowUp

        goal = _make_goal(
            title="My Goal",
            related_tasks=["Task A"],
        )

        followup = FollowUp(
            id="fu-001",
            title="Book review",
            linked_goal_title="My Goal",
        )

        summary = create_strategic_summary(
            goals=[goal],
            today=FIXED_TODAY,
            now=FIXED_NOW,
            open_task_titles=set(),
            all_task_titles=set(),
            metric_snapshots_by_goal={},
            followups=[followup],
            research_artifacts=[],
            decisions=[],
            attention_items=[],
            recommendations=[],
            goal_reviews=[],
        )

        link = next(
            (
                item
                for item in summary.cross_domain_links
                if (
                    item.goal_title == "My Goal"
                    and item.category == "follow_up"
                )
            ),
            None,
        )

        assert link is not None
        assert link.title == "Book review"

    def test_multiple_cross_links_same_goal(self):
        """Multiple cross-domain links for one goal all surface."""
        from janus.models.decision import Decision
        from janus.models.follow_up import FollowUp
        from janus.models.research_artifact import ResearchArtifact

        goal = _make_goal(
            title="My Goal",
            related_tasks=["Task A"],
        )

        artifact = ResearchArtifact(
            title="Note",
            linked_goal_titles=["My Goal"],
        )

        decision = Decision(
            adr_number="001",
            title="ADR",
            goal_titles=["My Goal"],
        )

        followup = FollowUp(
            id="fu-001",
            title="Follow",
            linked_goal_title="My Goal",
        )

        summary = create_strategic_summary(
            goals=[goal],
            today=FIXED_TODAY,
            now=FIXED_NOW,
            open_task_titles=set(),
            all_task_titles=set(),
            metric_snapshots_by_goal={},
            followups=[followup],
            research_artifacts=[artifact],
            decisions=[decision],
            attention_items=[],
            recommendations=[],
            goal_reviews=[],
        )

        my_links = [
            link
            for link in summary.cross_domain_links
            if link.goal_title == "My Goal"
        ]

        assert len(my_links) == 3

        categories = {
            link.category
            for link in my_links
        }

        assert categories == {
            "research_artifact",
            "decision",
            "follow_up",
        }


# ===========================================================================
# Status / CLI rendering
# ===========================================================================


class TestStatusRendering:
    def test_status_command_exists(self):
        """janus status is wired as a command."""
        from janus.strategic_cli import show_status

        assert callable(show_status)

    def test_status_is_not_weekly_or_today(self):
        """status remains distinct from today and weekly."""
        from janus import show_status, show_today, show_weekly

        assert show_status is not show_today
        assert show_status is not show_weekly

    def test_render_includes_all_sections(self):
        """Renderer includes all major summary sections."""
        summary = StrategicSummary(
            generated_at=FIXED_NOW,
            portfolio_health_counts=PortfolioHealthCounts(
                total_active=3,
                healthy=1,
                watch=1,
                stalled=1,
            ),
            stalled_goals=[
                StalledGoal(
                    goal_title="Stalled G",
                    health_state="stalled",
                    dominant_signal="goal_stalled",
                    dominant_signal_score=40,
                    dominant_signal_reason="All tasks done",
                    progress=0.0,
                    progress_delta=0.0,
                    days_since_last_activity=5,
                    measurement_overdue_count=0,
                )
            ],
            neglected_goals=[
                NeglectedGoal(
                    goal_title="Stalled G",
                    health_state="stalled",
                    dominant_signal="goal_stalled",
                    dominant_signal_score=40,
                    dominant_signal_reason="All tasks done",
                    progress=0.0,
                    days_since_last_activity=5,
                )
            ],
            recommended_actions=[
                RecommendedAction(
                    goal_title="Stalled G",
                    health_state="stalled",
                    dominant_signal="goal_stalled",
                    dominant_signal_score=40,
                    dominant_signal_reason="All tasks done",
                    progress=0.0,
                    days_since_last_activity=5,
                    suggested_next_step="Define next milestone",
                    cross_links=[],
                )
            ],
            cross_domain_links=[],
        )

        output = render_strategic_summary(summary)

        assert "JANUS — STRATEGIC SUMMARY" in output
        assert "PORTFOLIO HEALTH" in output
        assert "STALLED WORK" in output
        assert "NEGLECTED GOALS" in output
        assert "RECOMMENDED ACTIONS" in output
        assert "Stalled G" in output
        assert "score=40" in output
        assert "Define next milestone" in output

    def test_render_empty_portfolio(self):
        """Empty/healthy portfolio renders empty sections."""
        summary = StrategicSummary(
            generated_at=FIXED_NOW,
            portfolio_health_counts=PortfolioHealthCounts(
                total_active=1,
                healthy=1,
            ),
        )

        output = render_strategic_summary(summary)

        assert "No stalled goals." in output
        assert "No neglected goals." in output
        assert "No recommendations." in output

    def test_renders_stalled_and_recommendations(self):
        """Renderer includes stalled goal details."""
        goals = [
            _make_goal(
                title="G",
                related_tasks=[],
            )
        ]

        assessments = [
            _make_assessment(
                "G",
                health_state="stalled",
                dominant_signal=_sig(
                    "goal_overdue",
                    100,
                    "deadline passed",
                ),
                progress=0.0,
                progress_delta=-1.0,
                days_since_last_activity=40,
                measurement_overdue_count=1,
            )
        ]

        summary = create_strategic_summary(
            goals=goals,
            assessments=assessments,
            today=FIXED_TODAY,
            now=FIXED_NOW,
        )

        output = render_strategic_summary(summary)

        assert "G" in output
        assert "score=100" in output
        assert "Reason: deadline passed" in output
        assert "Progress: 0.0%" in output
        assert "Measurements overdue: 1" in output

    def test_does_not_render_stalled_for_completed(self):
        """Completed goals never appear as stalled or neglected."""
        goals = [
            _make_goal(
                title="G",
                status="completed",
            )
        ]

        summary = create_strategic_summary(
            goals=goals,
            assessments=[],
            today=FIXED_TODAY,
            now=FIXED_NOW,
        )

        output = render_strategic_summary(summary)

        assert "No stalled goals." in output
        assert "No neglected goals." in output

    def test_render_includes_remediation_action(self):
        """Renderer surfaces remediation_action on recommended actions."""
        summary = StrategicSummary(
            generated_at=FIXED_NOW,
            portfolio_health_counts=PortfolioHealthCounts(
                total_active=1, stalled=1,
            ),
            recommended_actions=[
                RecommendedAction(
                    goal_title="Stalled G",
                    health_state="stalled",
                    dominant_signal="goal_stalled",
                    dominant_signal_score=40,
                    dominant_signal_reason="All tasks done",
                    progress=0.0,
                    progress_delta=0.0,
                    days_since_last_activity=5,
                    suggested_next_step="Define next milestone",
                    remediation_action="All linked tasks are completed. Define the next milestone.",
                    cross_links=[],
                )
            ],
            cross_domain_links=[],
        )
        output = render_strategic_summary(summary)
        assert "Remediation: All linked tasks are completed" in output
        assert "Suggested action: Define next milestone" in output

    def test_render_omits_remediation_when_none(self):
        """No remediation_action on a recommendation - not rendered."""
        summary = StrategicSummary(
            generated_at=FIXED_NOW,
            portfolio_health_counts=PortfolioHealthCounts(
                total_active=1, healthy=1,
            ),
            recommended_actions=[
                RecommendedAction(
                    goal_title="Healthy G",
                    health_state="healthy",
                    dominant_signal="",
                    dominant_signal_score=0,
                    dominant_signal_reason="",
                )
            ],
            cross_domain_links=[],
        )
        output = render_strategic_summary(summary)
        assert "Remediation:" not in output

    def test_recommended_action_model_accepts_remediation_field(self):
        """The strategic summary RecommendedAction model supports remediation_action."""
        from janus.models.strategic_summary import RecommendedAction as SSA
        ra = SSA(
            goal_title="G",
            health_state="stalled",
            dominant_signal="goal_overdue",
            dominant_signal_score=100,
            dominant_signal_reason="overdue",
            remediation_action="Deadline has passed.",
        )
        assert ra.remediation_action == "Deadline has passed."
        assert ra.remediation_action is not None

    def test_recommended_action_remediation_defaults_none(self):
        """remediation_action defaults to None on RecommendedAction."""
        from janus.models.strategic_summary import RecommendedAction as SSA
        ra = SSA(
            goal_title="G",
            health_state="healthy",
            dominant_signal="",
            dominant_signal_score=0,
            dominant_signal_reason="",
        )
        assert ra.remediation_action is None


# ===========================================================================
# Edge cases
# ===========================================================================


class TestEdgeCases:
    def test_goal_with_open_tasks_but_progress_slow_is_watch(self):
        """progress_slow with no stalled signal produces watch."""
        goal = _make_metric_goal(
            title="Slow G"
        )

        snapshots = {
            "Slow G": [
                _snap(
                    "Slow G",
                    "Body fat %",
                    20.0,
                    15,
                )
            ]
        }

        summary = create_strategic_summary(
            goals=[goal],
            today=FIXED_TODAY,
            now=FIXED_NOW,
            open_task_titles=set(),
            all_task_titles=set(),
            metric_snapshots_by_goal=snapshots,
            followups=[],
            research_artifacts=[],
            decisions=[],
            attention_items=[],
            recommendations=[],
            goal_reviews=[],
        )

        assert summary.neglected_goals

        neglected = summary.neglected_goals[0]

        assert neglected.health_state == "watch"
        assert neglected.dominant_signal == "progress_slow"

    def test_measurement_due_no_metric_history(self):
        """Measurement due with no history increments overdue count."""
        req = {
            "metric": "weight",
            "unit": "kg",
            "frequency": "daily",
        }

        goal = _make_goal(
            title="Meas G",
            related_tasks=["Task A"],
            metric_name="weight",
            measurement_requirements=[req],
        )

        summary = create_strategic_summary(
            goals=[goal],
            today=FIXED_TODAY,
            now=FIXED_NOW,
            open_task_titles={"Task A"},
            all_task_titles={"Task A"},
            metric_snapshots_by_goal={},
            followups=[],
            research_artifacts=[],
            decisions=[],
            attention_items=[],
            recommendations=[],
            goal_reviews=[],
        )

        assert summary.neglected_goals

        neglected = summary.neglected_goals[0]

        assert neglected.measurement_overdue_count >= 1
        assert neglected.health_state == "watch"

    def test_deadline_soon_with_open_tasks_is_healthy(self):
        """Deadline soon with open tasks does not by itself cause neglect."""
        goal = _make_goal(
            title="Soon G",
            deadline="2026-09-10",
            related_tasks=["Task A"],
        )

        summary = create_strategic_summary(
            goals=[goal],
            today=FIXED_TODAY,
            now=FIXED_NOW,
            open_task_titles={"Task A"},
            all_task_titles={"Task A"},
            metric_snapshots_by_goal={},
            followups=[],
            research_artifacts=[],
            decisions=[],
            attention_items=[],
            recommendations=[],
            goal_reviews=[],
        )

        assert all(
            item.goal_title != "Soon G"
            for item in summary.stalled_goals
        )

        assert all(
            item.goal_title != "Soon G"
            for item in summary.neglected_goals
        )

        assert summary.portfolio_health_counts.healthy == 1

    def test_no_cross_links_recommendation_still_surfaces(self):
        """A stalled goal does not require cross-domain links."""
        goal = _make_goal(
            title="G",
            related_tasks=["Task A"],
        )

        summary = create_strategic_summary(
            goals=[goal],
            today=FIXED_TODAY,
            now=FIXED_NOW,
            open_task_titles=set(),
            all_task_titles={"Task A"},
            followups=[],
            research_artifacts=[],
            decisions=[],
            attention_items=[],
            recommendations=[],
            goal_reviews=[],
        )

        assert len(summary.recommended_actions) == 1

        action = summary.recommended_actions[0]

        assert action.goal_title == "G"
        assert action.cross_links == []


# ===========================================================================
# Upcoming deadline / milestone helper
# ===========================================================================


class TestUpcomingDeadlineHelper:
    def test_future_goal_deadline(self):
        goal = _make_goal(
            title="G",
            deadline="2026-09-20",
            related_tasks=[],
        )

        assert (
            _has_upcoming_milestone_or_deadline(
                goal,
                FIXED_TODAY,
            )
            is True
        )

    def test_past_goal_deadline(self):
        goal = _make_goal(
            title="G",
            deadline="2026-08-30",
            related_tasks=[],
        )

        assert (
            _has_upcoming_milestone_or_deadline(
                goal,
                FIXED_TODAY,
            )
            is False
        )

    def test_no_deadline_no_milestones(self):
        goal = _make_goal(
            title="G",
            related_tasks=[],
        )

        assert (
            _has_upcoming_milestone_or_deadline(
                goal,
                FIXED_TODAY,
            )
            is False
        )

    def test_future_milestone(self):
        goal = _make_goal(
            title="G",
            milestones=[
                {
                    "title": "M1",
                    "goal_title": "G",
                    "description": "",
                    "deadline": "2026-09-20",
                    "status": "open",
                    "order": 0,
                }
            ],
        )

        assert (
            _has_upcoming_milestone_or_deadline(
                goal,
                FIXED_TODAY,
            )
            is True
        )

    def test_completed_milestone_not_upcoming(self):
        goal = _make_goal(
            title="G",
            milestones=[
                {
                    "title": "M1",
                    "goal_title": "G",
                    "description": "",
                    "deadline": "2026-09-20",
                    "status": "completed",
                    "order": 0,
                }
            ],
        )

        assert (
            _has_upcoming_milestone_or_deadline(
                goal,
                FIXED_TODAY,
            )
            is False
        )