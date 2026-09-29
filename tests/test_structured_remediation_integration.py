"""Tests for structured remediation integration with weekly review.

Covers:
- GoalReview model has structured_remediation field
- create_weekly_review populates structured_remediation for unhealthy goals
- create_weekly_review leaves structured_remediation as None for healthy goals
- Telegram weekly renders structured remediation
- CLI weekly renders structured remediation
- Structured remediation dict has expected shape (primary, secondaries, summary)
"""

from datetime import date, datetime
from unittest.mock import patch

from janus.models.goal import Goal
from janus.models.goal_health_assessment import GoalHealthAssessment
from janus.models.goal_signal import GoalSignal
from janus.models.weekly_review import GoalReview, WeeklyReview
from janus.services.weekly_review import create_weekly_review


def _make_goal(title="Test Goal", status="active"):
    return Goal(title=title, status=status)


def _make_stalled_assessment(goal_title="Test Goal"):
    sig = GoalSignal(
        signal="goal_overdue",
        score=100,
        reason="Deadline passed",
        timestamp=datetime(2025, 1, 15),
    )
    return GoalHealthAssessment(
        goal_title=goal_title,
        health_state="stalled",
        signals=[sig],
        dominant_signal=sig,
        progress=50.0,
        progress_delta=-10.0,
        days_since_last_activity=45,
    )


def _make_healthy_assessment(goal_title="Test Goal"):
    return GoalHealthAssessment(
        goal_title=goal_title,
        health_state="healthy",
        signals=[],
        dominant_signal=None,
    )


# ── Model tests ──────────────────────────────────────────────────────────────


class TestStructuredRemediationField:
    def test_goal_review_has_structured_remediation_field(self):
        gr = GoalReview(goal=_make_goal())
        assert hasattr(gr, "structured_remediation")
        assert gr.structured_remediation is None


# ── create_weekly_review integration ─────────────────────────────────────────


class TestWeeklyReviewStructuredRemediation:
    def test_stalled_goal_gets_structured_remediation(self):
        """create_weekly_review populates structured_remediation for stalled goals."""
        goal = _make_goal("Stalled Goal")
        assessment = _make_stalled_assessment("Stalled Goal")

        with patch("janus.services.weekly_review.load_goals", return_value=[goal]), \
             patch("janus.services.weekly_review.load_tasks", return_value=[]), \
             patch("janus.services.weekly_review._read_completed_task_titles", return_value=[]), \
             patch("janus.services.weekly_review._read_completed_task_dates", return_value={}), \
             patch("janus.services.weekly_review.compute_goal_progress", return_value=50.0), \
             patch("janus.services.weekly_review.compute_all_project_progress", return_value=[]), \
             patch("janus.services.weekly_review.derive_next_action", return_value=None), \
             patch("janus.integrations.metric_history.get_metric_snapshots", return_value=[]), \
             patch("janus.services.goal_health.assess_goal_health", return_value=assessment), \
             patch("janus.services.goal_integrity.audit_goal_integrity") as mock_audit, \
             patch("janus.services.remediation.create_remediation_suggestions") as mock_suggestions:

            # Mock the integrity audit to return empty issues.
            from janus.models.goal_integrity_report import GoalIntegrityReport
            mock_audit.return_value = GoalIntegrityReport()

            # Mock the remediation suggestions.
            from janus.models.remediation import (
                RemediationAction,
                RemediationSuggestions,
                RemediationSummary,
                ESCALATE,
            )
            action = RemediationAction(
                goal_title="Stalled Goal",
                action_type=ESCALATE,
                suggestion_id="test-id",
                health_state="stalled",
                dominant_signal="goal_overdue",
                dominant_signal_score=100,
                dominant_signal_reason="Deadline passed",
                priority=100,
            )
            mock_suggestions.return_value = RemediationSuggestions(
                generated_at=datetime(2025, 1, 15),
                per_goal=[action],
                summary=RemediationSummary(
                    goals_with_actions=1,
                    by_type={ESCALATE: 1},
                    by_health_state={"stalled": 1},
                    stalled_goal_titles=["Stalled Goal"],
                    needs_confirmation_count=1,
                    highest_priority_action=action,
                ),
            )

            review = create_weekly_review()

        assert len(review.goals) == 1
        gr = review.goals[0]
        assert gr.structured_remediation is not None
        assert gr.structured_remediation["primary"]["action_type"] == ESCALATE
        assert gr.structured_remediation["primary"]["priority"] == 100
        assert gr.structured_remediation["secondaries"] == []
        assert gr.structured_remediation["summary"]["goals_with_actions"] == 1

    def test_healthy_goal_no_structured_remediation(self):
        """create_weekly_review leaves structured_remediation as None for healthy goals."""
        goal = _make_goal("Healthy Goal")
        assessment = _make_healthy_assessment("Healthy Goal")

        with patch("janus.services.weekly_review.load_goals", return_value=[goal]), \
             patch("janus.services.weekly_review.load_tasks", return_value=[]), \
             patch("janus.services.weekly_review._read_completed_task_titles", return_value=[]), \
             patch("janus.services.weekly_review._read_completed_task_dates", return_value={}), \
             patch("janus.services.weekly_review.compute_goal_progress", return_value=50.0), \
             patch("janus.services.weekly_review.compute_all_project_progress", return_value=[]), \
             patch("janus.services.weekly_review.derive_next_action", return_value=None), \
             patch("janus.integrations.metric_history.get_metric_snapshots", return_value=[]), \
             patch("janus.services.goal_health.assess_goal_health", return_value=assessment), \
             patch("janus.services.goal_integrity.audit_goal_integrity") as mock_audit, \
             patch("janus.services.remediation.create_remediation_suggestions") as mock_suggestions:

            from janus.models.goal_integrity_report import GoalIntegrityReport
            mock_audit.return_value = GoalIntegrityReport()

            from janus.models.remediation import (
                RemediationAction,
                RemediationSuggestions,
                RemediationSummary,
                NONE,
            )
            action = RemediationAction(
                goal_title="Healthy Goal",
                action_type=NONE,
                suggestion_id="test-id",
                health_state="healthy",
                dominant_signal=None,
                dominant_signal_score=0,
                dominant_signal_reason="",
                priority=0,
            )
            mock_suggestions.return_value = RemediationSuggestions(
                generated_at=datetime(2025, 1, 15),
                per_goal=[action],
                summary=RemediationSummary(),
            )

            review = create_weekly_review()

        assert len(review.goals) == 1
        gr = review.goals[0]
        # Healthy goals get a 'none' action, but we don't surface it.
        assert gr.structured_remediation is None

    def test_multiple_goals_mixed_health(self):
        """Mixed healthy/stalled goals: only unhealthy get structured remediation."""
        goal1 = _make_goal("Stalled Goal")
        goal2 = _make_goal("Healthy Goal")
        assessment1 = _make_stalled_assessment("Stalled Goal")
        assessment2 = _make_healthy_assessment("Healthy Goal")

        def mock_assess(goal, *args, **kwargs):
            if goal.title == "Stalled Goal":
                return assessment1
            return assessment2

        with patch("janus.services.weekly_review.load_goals", return_value=[goal1, goal2]), \
             patch("janus.services.weekly_review.load_tasks", return_value=[]), \
             patch("janus.services.weekly_review._read_completed_task_titles", return_value=[]), \
             patch("janus.services.weekly_review._read_completed_task_dates", return_value={}), \
             patch("janus.services.weekly_review.compute_goal_progress", return_value=50.0), \
             patch("janus.services.weekly_review.compute_all_project_progress", return_value=[]), \
             patch("janus.services.weekly_review.derive_next_action", return_value=None), \
             patch("janus.integrations.metric_history.get_metric_snapshots", return_value=[]), \
             patch("janus.services.goal_health.assess_goal_health", side_effect=mock_assess), \
             patch("janus.services.goal_integrity.audit_goal_integrity") as mock_audit, \
             patch("janus.services.remediation.create_remediation_suggestions") as mock_suggestions:

            from janus.models.goal_integrity_report import GoalIntegrityReport
            mock_audit.return_value = GoalIntegrityReport()

            from janus.models.remediation import (
                RemediationAction,
                RemediationSuggestions,
                RemediationSummary,
                ESCALATE,
                NONE,
            )
            action1 = RemediationAction(
                goal_title="Stalled Goal",
                action_type=ESCALATE,
                suggestion_id="test-id-1",
                health_state="stalled",
                dominant_signal="goal_overdue",
                dominant_signal_score=100,
                dominant_signal_reason="Deadline passed",
                priority=100,
            )
            action2 = RemediationAction(
                goal_title="Healthy Goal",
                action_type=NONE,
                suggestion_id="test-id-2",
                health_state="healthy",
                dominant_signal=None,
                dominant_signal_score=0,
                dominant_signal_reason="",
                priority=0,
            )
            mock_suggestions.return_value = RemediationSuggestions(
                generated_at=datetime(2025, 1, 15),
                per_goal=[action1, action2],
                summary=RemediationSummary(
                    goals_with_actions=1,
                    by_type={ESCALATE: 1, NONE: 1},
                    by_health_state={"stalled": 1, "healthy": 1},
                    stalled_goal_titles=["Stalled Goal"],
                    needs_confirmation_count=1,
                    highest_priority_action=action1,
                ),
            )

            review = create_weekly_review()

        assert len(review.goals) == 2
        stalled = next(g for g in review.goals if g.goal.title == "Stalled Goal")
        healthy = next(g for g in review.goals if g.goal.title == "Healthy Goal")
        assert stalled.structured_remediation is not None
        assert stalled.structured_remediation["primary"]["action_type"] == ESCALATE
        assert healthy.structured_remediation is None


# ── Telegram weekly rendering ────────────────────────────────────────────────


class TestTelegramWeeklyStructuredRemediation:
    def test_telegram_renders_structured_remediation(self):
        """Telegram weekly surfaces structured remediation action type."""
        from janus.integrations.telegram_weekly import format_weekly_message

        gr = GoalReview(
            goal=_make_goal("Overdue Goal"),
            health_state="stalled",
            remediation_action="Deadline has passed.",
            structured_remediation={
                "primary": {
                    "action_type": "escalate",
                    "priority": 100,
                    "requires_confirmation": True,
                    "parameters": {"channel": "telegram"},
                },
                "secondaries": [],
                "summary": {"goals_with_actions": 1, "by_type": {"escalate": 1}},
            },
        )
        review = WeeklyReview(goals=[gr])
        text = format_weekly_message(review)
        assert "Action: escalate (priority: 100)" in text

    def test_telegram_renders_secondaries(self):
        """Telegram weekly surfaces secondary action types."""
        from janus.integrations.telegram_weekly import format_weekly_message

        gr = GoalReview(
            goal=_make_goal("Goal"),
            health_state="watch",
            structured_remediation={
                "primary": {
                    "action_type": "task",
                    "priority": 40,
                    "requires_confirmation": True,
                    "parameters": {},
                },
                "secondaries": [
                    {"action_type": "investigate", "priority": 30, "requires_confirmation": False, "parameters": {}},
                ],
                "summary": {"goals_with_actions": 1, "by_type": {"task": 1}},
            },
        )
        review = WeeklyReview(goals=[gr])
        text = format_weekly_message(review)
        assert "Action: task (priority: 40)" in text
        assert "Also: investigate" in text

    def test_telegram_no_structured_remediation_for_healthy(self):
        """Telegram weekly omits structured remediation for healthy goals."""
        from janus.integrations.telegram_weekly import format_weekly_message

        gr = GoalReview(
            goal=_make_goal("Healthy Goal"),
            health_state="healthy",
        )
        review = WeeklyReview(goals=[gr])
        text = format_weekly_message(review)
        assert "Action:" not in text
        assert "Also:" not in text


# ── CLI weekly rendering ─────────────────────────────────────────────────────


class TestCLIWeeklyStructuredRemediation:
    def test_cli_renders_structured_remediation(self, capsys):
        """CLI weekly surfaces structured remediation action type."""
        from janus.weekly import show_weekly

        gr = GoalReview(
            goal=_make_goal("Overdue Goal"),
            health_state="stalled",
            remediation_action="Deadline has passed.",
            structured_remediation={
                "primary": {
                    "action_type": "escalate",
                    "priority": 100,
                    "requires_confirmation": True,
                    "parameters": {"channel": "telegram"},
                },
                "secondaries": [],
                "summary": {"goals_with_actions": 1, "by_type": {"escalate": 1}},
            },
        )
        review = WeeklyReview(goals=[gr])

        with patch("janus.weekly.create_weekly_review", return_value=review):
            show_weekly()

        out = capsys.readouterr().out
        assert "Action: escalate (priority: 100)" in out

    def test_cli_renders_secondaries(self, capsys):
        """CLI weekly surfaces secondary action types."""
        from janus.weekly import show_weekly

        gr = GoalReview(
            goal=_make_goal("Goal"),
            health_state="watch",
            structured_remediation={
                "primary": {
                    "action_type": "task",
                    "priority": 40,
                    "requires_confirmation": True,
                    "parameters": {},
                },
                "secondaries": [
                    {"action_type": "measure", "priority": 45, "requires_confirmation": True, "parameters": {}},
                ],
                "summary": {"goals_with_actions": 1, "by_type": {"task": 1}},
            },
        )
        review = WeeklyReview(goals=[gr])

        with patch("janus.weekly.create_weekly_review", return_value=review):
            show_weekly()

        out = capsys.readouterr().out
        assert "Action: task (priority: 40)" in out
        assert "Also: measure" in out
