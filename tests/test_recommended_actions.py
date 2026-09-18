"""Tests for the recommended next-actions engine (spec §4).

Covers:
- RecommendedAction model fields and ``suggested_action`` priority logic
- ``identify_neglected_goals`` threshold logic (§26)
- ``create_recommended_actions`` ranking and source integration
- ``render_recommended_actions`` markdown output (§4.10, §79)
- Edge cases: all healthy, all completed, no cross-links, etc.
"""

from datetime import date, datetime, timezone

import pytest

from janus.models.goal import Goal
from janus.models.goal_signal import GoalSignal
from janus.models.goal_health_assessment import GoalHealthAssessment
from janus.models.weekly_review import GoalReview
from janus.models.attention import AttentionItem
from janus.models.recommended_action import (
    CrossDomainLink,
    RecommendedAction,
    TaskRecommendation,
)
from janus.services.recommended_actions import (
    create_recommended_actions,
    identify_neglected_goals,
    render_recommended_actions,
    _has_upcoming_milestone_or_deadline,
    _collect_cross_domain_links,
    _task_recommendations_by_goal,
)
from janus.services.goal_health import INACTIVITY_WINDOW_DAYS

FIXED_TODAY = date(2026, 9, 6)
FIXED_NOW = datetime(2026, 9, 6, 12, 0, 0, tzinfo=timezone.utc)


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
):
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
    )


def _make_assessment(
    goal_title,
    health_state="healthy",
    signals=None,
    dominant_signal=None,
    progress=None,
    progress_delta=None,
    days_since_last_activity=None,
    measurement_overdue_count=0,
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


def _make_signal(signal, score=40, reason="test reason"):
    return GoalSignal(signal=signal, score=score, reason=reason, timestamp=FIXED_NOW)


# ── Model tests ──────────────────────────────────────────────────────────────

class TestRecommendedActionModel:
    def test_has_all_fields(self):
        ra = RecommendedAction(
            goal_title="G",
            health_state="stalled",
            dominant_signal="goal_overdue",
            dominant_signal_score=100,
            dominant_signal_reason="passed",
        )
        assert ra.goal_title == "G"
        assert ra.health_state == "stalled"
        assert ra.dominant_signal_score == 100
        assert ra.cross_links == []
        assert ra.task_recommendations == []

    def test_suggested_action_priority(self):
        """suggested_next_step takes priority over attention_reason (§57)."""
        ra = RecommendedAction(
            goal_title="G",
            health_state="stalled",
            suggested_next_step="Write report",
            attention_reason="Overdue by 3 days",
        )
        assert ra.suggested_action == "Write report"

    def test_suggested_action_fallback_to_attention(self):
        """When no suggested_next_step, fall back to attention_reason."""
        ra = RecommendedAction(
            goal_title="G",
            health_state="watch",
            suggested_next_step=None,
            attention_reason="In-progress task",
        )
        assert ra.suggested_action == "In-progress task"

    def test_suggested_action_none_when_both_absent(self):
        ra = RecommendedAction(
            goal_title="G",
            health_state="watch",
            suggested_next_step=None,
            attention_reason=None,
        )
        assert ra.suggested_action is None

    def test_serializes_to_dict(self):
        ra = RecommendedAction(
            goal_title="G",
            health_state="stalled",
            cross_links=[CrossDomainLink(
                goal_title="G", category="decision", title="ADR-001"
            )],
        )
        d = ra.to_dict()
        assert d["goal_title"] == "G"
        assert len(d["cross_links"]) == 1
        assert d["cross_links"][0]["category"] == "decision"


# ── identify_neglected_goals ─────────────────────────────────────────────────

class TestIdentifyNeglectedGoals:
    def test_watch_goal_with_no_activity_is_neglected(self):
        """A watch goal with days > inactivity window is neglected (§26)."""
        goal = _make_goal(title="Slow G")
        a = _make_assessment(
            "Slow G", health_state="watch",
            days_since_last_activity=35,
            dominant_signal=_make_signal("progress_slow", 40),
        )
        result = identify_neglected_goals([a], [goal], set(), FIXED_TODAY)
        assert len(result) == 1
        assert result[0].goal_title == "Slow G"

    def test_healthy_goal_not_neglected(self):
        goal = _make_goal(title="Healthy G")
        a = _make_assessment("Healthy G", health_state="healthy")
        result = identify_neglected_goals([a], [goal], set(), FIXED_TODAY)
        assert result == []

    def test_completed_goal_excluded(self):
        goal = _make_goal(title="Done", status="completed")
        a = _make_assessment("Done", health_state="stalled")
        result = identify_neglected_goals([a], [goal], set(), FIXED_TODAY)
        assert result == []

    def test_inactive_goal_excluded(self):
        goal = _make_goal(title="Paused", status="inactive")
        a = _make_assessment("Paused", health_state="watch")
        result = identify_neglected_goals([a], [goal], set(), FIXED_TODAY)
        assert result == []

    def test_measurement_overdue_is_neglected(self):
        """measurement_overdue_count > 0 → neglected even with 0 days."""
        goal = _make_goal(
            title="Meas G",
            related_tasks=["Task A"],
            metric_name="weight",
            measurement_requirements=[{"metric": "weight", "frequency": "daily"}],
        )
        a = _make_assessment(
            "Meas G", health_state="watch",
            days_since_last_activity=0,
            measurement_overdue_count=2,
            dominant_signal=_make_signal("measurement_due", 45),
        )
        result = identify_neglected_goals(
            [a], [goal], {"Task A"}, FIXED_TODAY,
        )
        assert len(result) == 1

    def test_no_open_tasks_no_upcoming_is_neglected(self):
        """No open related tasks + no upcoming milestone/deadline → neglected."""
        goal = _make_goal(title="G", related_tasks=["Task A"])
        a = _make_assessment(
            "G", health_state="watch",
            days_since_last_activity=5,
            dominant_signal=_make_signal("progress_slow", 40),
        )
        result = identify_neglected_goals([a], [goal], set(), FIXED_TODAY)
        assert len(result) == 1

    def test_open_tasks_upcoming_not_neglected(self):
        """Open related tasks with upcoming milestone → not neglected."""
        goal = _make_goal(title="G", related_tasks=["Task A"])
        a = _make_assessment(
            "G", health_state="watch",
            days_since_last_activity=5,
            dominant_signal=_make_signal("progress_slow", 40),
        )
        result = identify_neglected_goals(
            [a], [goal], {"Task A"}, FIXED_TODAY,
        )
        assert result == []

    def test_stalled_meets_threshold_is_neglected(self):
        """A stalled goal that meets the threshold is in the neglected list."""
        goal = _make_goal(title="G", related_tasks=[])
        a = _make_assessment(
            "G", health_state="stalled",
            days_since_last_activity=5,
            dominant_signal=_make_signal("goal_stalled", 40),
        )
        result = identify_neglected_goals([a], [goal], set(), FIXED_TODAY)
        assert len(result) == 1


# ── create_recommended_actions ───────────────────────────────────────────────

class TestCreateRecommendedActions:
    def test_no_assessments_returns_empty(self):
        actions = create_recommended_actions([], [])
        assert actions == []

    def test_healthy_goals_return_empty(self):
        goal = _make_goal(title="Healthy G")
        a = _make_assessment("Healthy G", health_state="healthy")
        actions = create_recommended_actions([a], [goal])
        assert actions == []

    def test_stalled_goal_produces_action(self):
        """A stalled goal produces a RecommendedAction (§6.2)."""
        goal = _make_goal(title="Stalled G", related_tasks=["Task A"])
        dom = _make_signal("goal_stalled", 40, "All tasks done")
        a = _make_assessment(
            "Stalled G", health_state="stalled",
            dominant_signal=dom, progress=0.0, progress_delta=0.0,
            days_since_last_activity=5,
        )
        actions = create_recommended_actions(
            [a], [goal],
            goal_reviews=[],
            attention_items=[],
            today=FIXED_TODAY, now=FIXED_NOW,
        )
        assert len(actions) == 1
        ra = actions[0]
        assert ra.goal_title == "Stalled G"
        assert ra.health_state == "stalled"
        assert ra.dominant_signal == "goal_stalled"
        assert ra.dominant_signal_score == 40

    def test_watch_with_neglected_conditions_produces_action(self):
        """A watch goal meeting neglected threshold produces an action."""
        goal = _make_goal(title="Watch G")
        dom = _make_signal("progress_slow", 40)
        a = _make_assessment(
            "Watch G", health_state="watch",
            dominant_signal=dom,
            days_since_last_activity=40,
        )
        actions = create_recommended_actions(
            [a], [goal], today=FIXED_TODAY, now=FIXED_NOW,
        )
        assert len(actions) == 1
        assert actions[0].health_state == "watch"

    def test_suggested_next_step_from_goal_review(self):
        """Suggested action comes from GoalReview.suggested_next_step (§4)."""
        goal = _make_goal(title="G", related_tasks=["Task A"])
        a = _make_assessment(
            "G", health_state="stalled",
            dominant_signal=_make_signal("goal_stalled", 40),
            days_since_last_activity=5,
        )
        gr = GoalReview(goal=goal, suggested_next_step="Define next milestone")
        actions = create_recommended_actions(
            [a], [goal],
            goal_reviews=[gr], today=FIXED_TODAY, now=FIXED_NOW,
        )
        assert len(actions) == 1
        assert actions[0].suggested_next_step == "Define next milestone"
        assert actions[0].suggested_action == "Define next milestone"

    def test_attention_reason_fallback(self):
        """When no suggested_next_step, attention_reason is used (§57)."""
        goal = _make_goal(title="G")
        a = _make_assessment(
            "G", health_state="stalled",
            dominant_signal=_make_signal("goal_overdue", 100),
            days_since_last_activity=5,
        )
        att = AttentionItem(
            title="G", reason="Goal deadline has passed",
            score=100, category="goal_overdue",
        )
        actions = create_recommended_actions(
            [a], [goal],
            attention_items=[att],
            today=FIXED_TODAY, now=FIXED_NOW,
        )
        assert len(actions) == 1
        assert actions[0].attention_reason == "Goal deadline has passed"
        assert actions[0].suggested_action == "Goal deadline has passed"

    def test_task_recommendations_integrated(self):
        """Task-level recommendations from recommend_tasks() are included (§4)."""
        goal = _make_goal(title="G", related_tasks=["Task A"])
        a = _make_assessment(
            "G", health_state="stalled",
            dominant_signal=_make_signal("goal_stalled", 40),
            days_since_last_activity=5,
        )
        # Simulate a Recommendation object from recommendations service
        from janus.services.recommendations import Recommendation
        rec = Recommendation(
            title="Task A", kind="task", goal_title="G",
            score=80, reason="Due soon",
        )
        actions = create_recommended_actions(
            [a], [goal],
            recommendations=[rec],
            today=FIXED_TODAY, now=FIXED_NOW,
        )
        assert len(actions) == 1
        assert len(actions[0].task_recommendations) == 1
        assert actions[0].task_recommendations[0].title == "Task A"
        assert actions[0].task_recommendations[0].score == 80

    def test_cross_links_integrated(self):
        """Cross-domain links are attached to the recommendation (§4, §82)."""
        goal = _make_goal(title="G")
        a = _make_assessment(
            "G", health_state="stalled",
            dominant_signal=_make_signal("goal_overdue", 100),
            days_since_last_activity=5,
        )
        links = [
            CrossDomainLink(goal_title="G", category="decision", title="ADR-001"),
            CrossDomainLink(goal_title="G", category="research_artifact", title="Note"),
        ]
        actions = create_recommended_actions(
            [a], [goal], cross_links=links,
            today=FIXED_TODAY, now=FIXED_NOW,
        )
        assert len(actions) == 1
        assert len(actions[0].cross_links) == 2
        categories = {l.category for l in actions[0].cross_links}
        assert categories == {"decision", "research_artifact"}

    def test_all_healthy_returns_empty(self):
        goals = [
            _make_goal(title="G1", related_tasks=["A"]),
            _make_goal(title="G2", related_tasks=["B"]),
        ]
        assessments = [
            _make_assessment("G1", health_state="healthy"),
            _make_assessment("G2", health_state="healthy"),
        ]
        actions = create_recommended_actions(assessments, goals, today=FIXED_TODAY)
        assert actions == []

    def test_completed_goals_excluded(self):
        goal = _make_goal(title="Done", status="completed")
        a = _make_assessment("Done", health_state="completed")
        actions = create_recommended_actions(
            [a], [goal], today=FIXED_TODAY,
        )
        assert actions == []

    def test_ranking_stalled_before_watch(self):
        """Stalled goals rank before watch goals (spec §61)."""
        goals = [
            _make_goal(title="Watch G"),
            _make_goal(title="Stalled G"),
        ]
        assessments = [
            _make_assessment(
                "Watch G", health_state="watch",
                dominant_signal=_make_signal("progress_slow", 40),
                days_since_last_activity=40,
            ),
            _make_assessment(
                "Stalled G", health_state="stalled",
                dominant_signal=_make_signal("goal_overdue", 100),
                days_since_last_activity=5,
            ),
        ]
        actions = create_recommended_actions(
            assessments, goals, today=FIXED_TODAY, now=FIXED_NOW,
        )
        assert len(actions) == 2
        assert actions[0].goal_title == "Stalled G"
        assert actions[1].goal_title == "Watch G"

    def test_ranking_by_score_within_stalled(self):
        """Stalled goals sorted by dominant signal score descending."""
        goals = [
            _make_goal(title="G1"),
            _make_goal(title="G2"),
        ]
        assessments = [
            _make_assessment(
                "G1", health_state="stalled",
                dominant_signal=_make_signal("goal_stalled", 40),
                days_since_last_activity=50,
            ),
            _make_assessment(
                "G2", health_state="stalled",
                dominant_signal=_make_signal("goal_overdue", 100),
                days_since_last_activity=5,
            ),
        ]
        actions = create_recommended_actions(
            assessments, goals, today=FIXED_TODAY, now=FIXED_NOW,
        )
        assert len(actions) == 2
        assert actions[0].goal_title == "G2"  # score 100 > 40
        assert actions[1].goal_title == "G1"


# ── render_recommended_actions ───────────────────────────────────────────────

class TestRenderRecommendedActions:
    def test_empty_returns_no_recommendations(self):
        output = render_recommended_actions([])
        assert "No recommendations" in output

    def test_render_includes_all_fields(self):
        links = [
            CrossDomainLink(goal_title="G", category="decision", title="ADR-001"),
        ]
        ra = RecommendedAction(
            goal_title="G", health_state="stalled",
            dominant_signal="goal_stalled", dominant_signal_score=40,
            dominant_signal_reason="All tasks done",
            progress=0.0, progress_delta=0.0,
            days_since_last_activity=5, measurement_overdue_count=0,
            suggested_next_step="Define next milestone",
            cross_links=links,
        )
        output = render_recommended_actions([ra])
        assert "G [stalled, score=40]" in output
        assert "Reason: All tasks done" in output
        assert "Progress: 0.0%" in output
        assert "Activity: 5d since last" in output
        assert "Measurements overdue: 0" in output
        assert "Suggested action: Define next milestone" in output
        assert "decision: ADR-001" in output

    def test_render_task_recommendations(self):
        ra = RecommendedAction(
            goal_title="G", health_state="stalled",
            dominant_signal="goal_stalled", dominant_signal_score=40,
            dominant_signal_reason="All tasks done",
            task_recommendations=[
                TaskRecommendation(title="Task A", score=80, reason="Due soon"),
            ],
        )
        output = render_recommended_actions([ra])
        assert "Task: Task A (score=80)" in output

    def test_render_uses_attention_when_no_suggested_step(self):
        ra = RecommendedAction(
            goal_title="G", health_state="stalled",
            dominant_signal="goal_overdue", dominant_signal_score=100,
            dominant_signal_reason="Overdue",
            attention_reason="Deadline passed",
        )
        output = render_recommended_actions([ra])
        assert "Suggested action: Deadline passed" in output

    def test_render_uses_suggested_next_step_first(self):
        ra = RecommendedAction(
            goal_title="G", health_state="stalled",
            dominant_signal="goal_overdue", dominant_signal_score=100,
            dominant_signal_reason="Overdue",
            suggested_next_step="Write report",
            attention_reason="Deadline passed",
        )
        output = render_recommended_actions([ra])
        assert "Suggested action: Write report" in output
        assert "Deadline passed" not in output.split("Suggested action:")[1]


# ── Helper tests ─────────────────────────────────────────────────────────────

class TestHelpers:
    def test_upcoming_deadline_true(self):
        goal = _make_goal(title="G", deadline="2026-09-20")
        assert _has_upcoming_milestone_or_deadline(goal, FIXED_TODAY) is True

    def test_past_deadline_false(self):
        goal = _make_goal(title="G", deadline="2026-08-30")
        assert _has_upcoming_milestone_or_deadline(goal, FIXED_TODAY) is False

    def test_no_deadline_no_milestones_false(self):
        goal = _make_goal(title="G")
        assert _has_upcoming_milestone_or_deadline(goal, FIXED_TODAY) is False

    def test_future_milestone_true(self):
        goal = _make_goal(
            title="G",
            milestones=[{"title": "M1", "goal_title": "G", "description": "",
                          "deadline": "2026-09-20", "status": "open", "order": 0}],
        )
        assert _has_upcoming_milestone_or_deadline(goal, FIXED_TODAY) is True

    def test_completed_milestone_false(self):
        goal = _make_goal(
            title="G",
            milestones=[{"title": "M1", "goal_title": "G", "description": "",
                          "deadline": "2026-09-20", "status": "completed", "order": 0}],
        )
        assert _has_upcoming_milestone_or_deadline(goal, FIXED_TODAY) is False

    def test_task_recommendations_by_goal(self):
        from janus.services.recommendations import Recommendation
        recs = [
            Recommendation(title="Task A", kind="task", goal_title="G1",
                           score=50, reason="due"),
            Recommendation(title="Task B", kind="task", goal_title="G2",
                           score=30, reason="priority"),
            Recommendation(title="Proj", kind="project", goal_title="G1",
                           score=60, reason="proj"),  # excluded — not task kind
        ]
        result = _task_recommendations_by_goal(recs)
        assert "G1" in result
        assert "G2" in result
        assert len(result["G1"]) == 1
        assert result["G1"][0].title == "Task A"

    def test_task_recommendations_empty(self):
        result = _task_recommendations_by_goal(None)
        assert result == {}

    def test_collect_cross_domain_links_dedup(self):
        from janus.models.research_artifact import ResearchArtifact
        from janus.models.decision import Decision
        from janus.models.follow_up import FollowUp
        goal_titles = {"G"}
        art = ResearchArtifact(title="Note", linked_goal_titles=["G"])
        dec = Decision(adr_number="001", title="ADR", goal_titles=["G"])
        fu = FollowUp(id="fu-001", title="Follow", linked_goal_title="G")
        links = _collect_cross_domain_links(
            goal_titles,
            research_artifacts=[art],
            decisions=[dec],
            followups=[fu],
        )
        assert len(links) == 3
        categories = {l.category for l in links}
        assert categories == {"research_artifact", "decision", "follow_up"}
