"""Tests for remediation action derivation (R1).

Covers:
- derive_remediation_action() mapping signal -> concrete action
- {reason} substitution in templates
- healthy goals return None
- unknown signals fall back to health-state defaults
- derive_remediation_for_reviews() batch wrapper
- GoalReview.remediation_action is populated by create_weekly_review()
"""

from dataclasses import replace
from datetime import date, datetime

from janus.models.goal import Goal
from janus.models.goal_health_assessment import GoalHealthAssessment
from janus.models.goal_signal import GoalSignal
from janus.models.weekly_review import GoalReview, WeeklyReview
from janus.services.recommended_actions import (
    derive_remediation_action,
    derive_remediation_for_reviews,
)


def _make_assessment(
    goal_title="Test Goal",
    health_state="stalled",
    signal="goal_overdue",
    reason="Deadline 2025-01-01 passed",
) -> GoalHealthAssessment:
    """Build a minimal GoalHealthAssessment for testing."""
    sig = GoalSignal(
        signal=signal,
        score=80,
        reason=reason,
        timestamp=datetime(2025, 1, 15),
    )
    return GoalHealthAssessment(
        goal_title=goal_title,
        health_state=health_state,
        signals=[sig],
        dominant_signal=sig,
        progress=50.0,
        progress_delta=-10.0,
        days_since_last_activity=45,
        measurement_overdue_count=0,
    )


def _make_goal(title="Test Goal") -> Goal:
    return Goal(title=title, status="active")


# ── derive_remediation_action ─────────────────────────────────────────────────


def test_stalled_overdue_signal():
    """Goal with goal_overdue signal gets high-priority remediation."""
    a = _make_assessment(signal="goal_overdue")
    ra = derive_remediation_action(a, goal=_make_goal())
    assert ra is not None
    assert ra.health_state == "stalled"
    assert ra.signal == "goal_overdue"
    assert "Deadline has passed" in ra.action
    assert ra.priority == 100


def test_deadline_today_signal():
    a = _make_assessment(health_state="stalled", signal="goal_deadline_today")
    ra = derive_remediation_action(a, goal=_make_goal())
    assert ra is not None
    assert ra.priority == 90
    assert "today" in ra.action.lower()


def test_milestone_slipped_signal():
    a = _make_assessment(signal="milestone_slipped")
    ra = derive_remediation_action(a, goal=_make_goal())
    assert ra is not None
    assert ra.priority == 80
    assert "Milestone deadline was missed" in ra.action


def test_goal_stalled_signal():
    a = _make_assessment(signal="goal_stalled")
    ra = derive_remediation_action(a, goal=_make_goal())
    assert ra is not None
    assert ra.priority == 40
    assert "completed" in ra.action.lower()


def test_no_recent_activity_signal():
    a = _make_assessment(signal="no_recent_activity")
    ra = derive_remediation_action(a, goal=_make_goal())
    assert ra is not None
    assert ra.priority == 35
    assert "No activity" in ra.action


def test_watch_progress_slow_signal():
    a = _make_assessment(health_state="watch", signal="progress_slow")
    ra = derive_remediation_action(a, goal=_make_goal())
    assert ra is not None
    assert ra.health_state == "watch"
    assert ra.signal == "progress_slow"
    assert ra.priority == 40
    assert "slow" in ra.action.lower()


def test_watch_measurement_due_signal():
    a = _make_assessment(health_state="watch", signal="measurement_due")
    ra = derive_remediation_action(a, goal=_make_goal())
    assert ra is not None
    assert ra.priority == 45
    assert "Measurement requirements are overdue" in ra.action


def test_watch_progress_regressing_signal():
    """progress_regressing gets a medium-high priority remediation."""
    a = _make_assessment(health_state="watch", signal="progress_regressing", reason="Progress regressed by 25.0 percentage points")
    ra = derive_remediation_action(a, goal=_make_goal())
    assert ra is not None
    assert ra.health_state == "watch"
    assert ra.signal == "progress_regressing"
    assert ra.priority == 50
    assert "regressed" in ra.action.lower()


def test_watch_deadline_soon_signal_reason_substitution():
    a = _make_assessment(
        health_state="watch",
        signal="goal_deadline_soon",
        reason="due in 3 days",
    )
    ra = derive_remediation_action(a, goal=_make_goal())
    assert ra is not None
    assert "due in 3 days" in ra.action
    assert "({reason})" not in ra.action


def test_watch_milestone_deadline_soon_signal_reason_substitution():
    a = _make_assessment(
        health_state="watch",
        signal="milestone_deadline_soon",
        reason="ends in 5 days",
    )
    ra = derive_remediation_action(a, goal=_make_goal())
    assert ra is not None
    assert "ends in 5 days" in ra.action


def test_watch_goal_inactive_signal():
    a = _make_assessment(health_state="watch", signal="goal_inactive")
    ra = derive_remediation_action(a, goal=_make_goal())
    assert ra is not None
    assert ra.priority == 30
    assert "future milestone" in ra.action.lower()


def test_healthy_returns_none():
    a = _make_assessment(health_state="healthy", signal="")
    ra = derive_remediation_action(a, goal=_make_goal())
    assert ra is None


def test_no_dominant_signal_falls_back_to_state():
    """Unhealthy with dominant_signal=None should use health-state fallback."""
    a = GoalHealthAssessment(
        goal_title="Test Goal",
        health_state="stalled",
        signals=[],
        dominant_signal=None,
    )
    ra = derive_remediation_action(a, goal=_make_goal())
    assert ra is not None
    assert ra.signal == "stalled"
    assert "stalled" in ra.action.lower()


def test_unknown_signal_falls_back_to_state():
    """A signal not in rules falls back to health-state default text."""
    sig = GoalSignal(signal="unknown_signal", score=70, reason="weird", timestamp=datetime(2025, 1, 15))
    a = GoalHealthAssessment(
        goal_title="Test Goal",
        health_state="stalled",
        signals=[sig],
        dominant_signal=sig,
    )
    ra = derive_remediation_action(a, goal=_make_goal())
    assert ra is not None
    assert ra.priority == 40  # stalled default
    assert "stalled" in ra.action.lower()


def test_unknown_signal_watch_state():
    sig = GoalSignal(signal="unknown_signal", score=50, reason="weird", timestamp=datetime(2025, 1, 15))
    a = GoalHealthAssessment(
        goal_title="Test Goal",
        health_state="watch",
        signals=[sig],
        dominant_signal=sig,
    )
    ra = derive_remediation_action(a, goal=_make_goal())
    assert ra is not None
    assert ra.priority == 30  # watch default
    assert "at risk" in ra.action.lower()


def test_goal_title_from_goal_object():
    goal = Goal(title="My Custom Goal Title", status="active")
    a = _make_assessment(goal_title="Assessment Title")
    ra = derive_remediation_action(a, goal=goal)
    assert ra is not None
    assert ra.goal_title == "My Custom Goal Title"


def test_goal_title_falls_back_to_assessment():
    a = _make_assessment(goal_title="Assessment Title")
    ra = derive_remediation_action(a, goal=None)
    assert ra is not None
    assert ra.goal_title == "Assessment Title"


def test_reason_template_without_reason_falls_back():
    """{reason} template with empty reason should get a generic fallback."""
    a = _make_assessment(
        health_state="watch",
        signal="goal_deadline_soon",
        reason="",
    )
    ra = derive_remediation_action(a, goal=_make_goal())
    assert ra is not None
    assert "see goal health report" in ra.action
    assert "({reason})" not in ra.action


# ── derive_remediation_for_reviews ─�───────────────────────────────────────────


def test_batch_derivation_all_goals():
    goals = [_make_goal("G1"), _make_goal("G2")]
    a1 = _make_assessment(goal_title="G1", signal="goal_overdue")
    a2 = _make_assessment(goal_title="G2", signal="progress_slow", health_state="watch")
    result = derive_remediation_for_reviews([a1, a2], goals, today=date(2025, 1, 15))
    assert set(result.keys()) == {"G1", "G2"}
    assert result["G1"] is not None
    assert result["G2"] is not None
    assert result["G1"].signal == "goal_overdue"
    assert result["G2"].signal == "progress_slow"


def test_batch_healthy_goal_returns_none():
    a = _make_assessment(health_state="healthy", signal="")
    result = derive_remediation_for_reviews([a], [_make_goal()], today=date(2025, 1, 15))
    assert result["Test Goal"] is None


# ── create_weekly_review integration ───────────────────────────────────────────


def test_goal_review_has_remediation_field():
    """GoalReview model has a remediation_action field."""
    gr = GoalReview(goal=_make_goal())
    assert hasattr(gr, "remediation_action")
    assert gr.remediation_action is None


def test_weekly_review_remediation_populated():
    """create_weekly_review populates remediation_action for stalled goals.

    We patch the health assessment to return a stalled assessment and verify
    that the GoalReview gets a remediation action string populated.
    """
    import janus.services.weekly_review as wr_mod
    import janus.services.goal_health as gh_mod
    from unittest.mock import patch

    goal = Goal(title="Stalled Goal", status="active")
    sig = GoalSignal(
        signal="goal_overdue",
        score=80,
        reason="Deadline passed",
        timestamp=datetime(2025, 1, 15),
    )
    fake_assessment = GoalHealthAssessment(
        goal_title="Stalled Goal",
        health_state="stalled",
        signals=[sig],
        dominant_signal=sig,
        progress=50.0,
        progress_delta=-10.0,
        days_since_last_activity=45,
    )

    with patch.object(wr_mod, "load_goals", return_value=[goal]), \
         patch.object(wr_mod, "load_tasks", return_value=[]), \
         patch.object(wr_mod, "_read_completed_task_titles", return_value=[]), \
         patch.object(wr_mod, "compute_goal_progress", return_value=50.0), \
         patch.object(wr_mod, "compute_all_project_progress", return_value=[]), \
         patch.object(wr_mod, "derive_next_action", return_value=None), \
         patch("janus.integrations.metric_history.get_metric_snapshots", return_value=[]), \
         patch.object(gh_mod, "assess_goal_health", return_value=fake_assessment):

        review = wr_mod.create_weekly_review()

    assert len(review.goals) == 1
    assert review.goals[0].remediation_action is not None
    assert "Deadline has passed" in review.goals[0].remediation_action


def test_weekly_review_no_remediation_for_healthy():
    """create_weekly_review leaves remediation_action as None for healthy goals."""
    import janus.services.weekly_review as wr_mod
    import janus.services.goal_health as gh_mod
    from unittest.mock import patch

    goal = Goal(title="Healthy Goal", status="active")
    fake_assessment = GoalHealthAssessment(
        goal_title="Healthy Goal",
        health_state="healthy",
        signals=[],
        dominant_signal=None,
    )

    with patch.object(wr_mod, "load_goals", return_value=[goal]), \
         patch.object(wr_mod, "load_tasks", return_value=[]), \
         patch.object(wr_mod, "_read_completed_task_titles", return_value=[]), \
         patch.object(wr_mod, "compute_goal_progress", return_value=50.0), \
         patch.object(wr_mod, "compute_all_project_progress", return_value=[]), \
         patch.object(wr_mod, "derive_next_action", return_value=None), \
         patch("janus.integrations.metric_history.get_metric_snapshots", return_value=[]), \
         patch.object(gh_mod, "assess_goal_health", return_value=fake_assessment):

        review = wr_mod.create_weekly_review()

    assert len(review.goals) == 1
    assert review.goals[0].remediation_action is None


# ── render_recommended_actions includes remediation ────────────────────────────


def test_render_includes_remediation():
    """render_recommended_actions surfaces the remediation_action field."""
    from janus.services.recommended_actions import render_recommended_actions

    a = _make_assessment(signal="goal_overdue")
    ra = derive_remediation_action(a, goal=_make_goal("Test Goal"))

    from janus.models.recommended_action import RecommendedAction
    action = RecommendedAction(
        goal_title="Test Goal",
        health_state="stalled",
        remediation_action=ra.action,
    )
    rendered = render_recommended_actions([action])
    assert "Remediation:" in rendered
    assert ra.action in rendered
