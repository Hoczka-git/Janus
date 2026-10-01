"""Tests for agency-aware ranking in recommendations.

Covers the integration of least-substitutive-mode selection into the
recommendation ranking layer:
- _agency_score_boost values for all mode combinations
- Ranking preference: USER > COLLABORATIVE > JANUS
- Backward compatibility: no agency_context → no boost
- Edge cases: milestone/project actions without agency

Note: recommend_tasks returns one recommendation per goal (the next action).
To test ranking across task types, we use multiple goals with different tasks.
"""

from datetime import date

import pytest

from janus.models.execution_mode import ExecutionMode
from janus.models.goal import Goal
from janus.models.support_mode import SupportMode
from janus.models.task import Task
from janus.models.task_agency import TaskAgency
from janus.services.agency_planning import AgencyContext
from janus.services.recommendations import (
    _agency_score_boost,
    recommend_tasks,
)


# ── Helpers ──────────────────────────────────────────────────────────────────


def _task(title: str, **kwargs) -> Task:
    return Task(title=title, **kwargs)


def _goal(title: str = "Test Goal", **kwargs) -> Goal:
    return Goal(title=title, **kwargs)


def _milestone(title: str, order: int = 0, status: str = "open") -> dict:
    return {"title": title, "goal_title": "G", "status": status, "order": order}


# ── _agency_score_boost ──────────────────────────────────────────────────────


class TestAgencyScoreBoost:
    """Verify _agency_score_boost returns correct values for all combinations."""

    def test_none_agency_returns_zero(self):
        assert _agency_score_boost(None) == 0

    def test_user_explain(self):
        agency = TaskAgency(
            execution_mode=ExecutionMode.USER,
            support_mode=SupportMode.EXPLAIN,
            reason="test",
        )
        assert _agency_score_boost(agency) == 25  # 20 + 5

    def test_user_coach(self):
        agency = TaskAgency(
            execution_mode=ExecutionMode.USER,
            support_mode=SupportMode.COACH,
            reason="test",
        )
        assert _agency_score_boost(agency) == 24  # 20 + 4

    def test_user_scaffold(self):
        agency = TaskAgency(
            execution_mode=ExecutionMode.USER,
            support_mode=SupportMode.SCAFFOLD,
            reason="test",
        )
        assert _agency_score_boost(agency) == 23  # 20 + 3

    def test_user_review(self):
        agency = TaskAgency(
            execution_mode=ExecutionMode.USER,
            support_mode=SupportMode.REVIEW,
            reason="test",
        )
        assert _agency_score_boost(agency) == 22  # 20 + 2

    def test_user_execute(self):
        agency = TaskAgency(
            execution_mode=ExecutionMode.USER,
            support_mode=SupportMode.EXECUTE,
            reason="test",
        )
        assert _agency_score_boost(agency) == 20  # 20 + 0

    def test_collaborative_explain(self):
        agency = TaskAgency(
            execution_mode=ExecutionMode.COLLABORATIVE,
            support_mode=SupportMode.EXPLAIN,
            reason="test",
        )
        assert _agency_score_boost(agency) == 15  # 10 + 5

    def test_collaborative_scaffold(self):
        agency = TaskAgency(
            execution_mode=ExecutionMode.COLLABORATIVE,
            support_mode=SupportMode.SCAFFOLD,
            reason="test",
        )
        assert _agency_score_boost(agency) == 13  # 10 + 3

    def test_janus_execute(self):
        agency = TaskAgency(
            execution_mode=ExecutionMode.JANUS,
            support_mode=SupportMode.EXECUTE,
            reason="test",
        )
        assert _agency_score_boost(agency) == 0  # 0 + 0

    def test_janus_explain(self):
        """JANUS execution with EXPLAIN support — unusual but possible."""
        agency = TaskAgency(
            execution_mode=ExecutionMode.JANUS,
            support_mode=SupportMode.EXPLAIN,
            reason="test",
        )
        assert _agency_score_boost(agency) == 5  # 0 + 5

    def test_user_beats_collaborative(self):
        """USER execution always scores higher than COLLABORATIVE."""
        user_agency = TaskAgency(
            execution_mode=ExecutionMode.USER,
            support_mode=SupportMode.EXECUTE,
            reason="test",
        )
        collab_agency = TaskAgency(
            execution_mode=ExecutionMode.COLLABORATIVE,
            support_mode=SupportMode.EXPLAIN,
            reason="test",
        )
        assert _agency_score_boost(user_agency) > _agency_score_boost(collab_agency)

    def test_collaborative_beats_janus(self):
        """COLLABORATIVE execution always scores higher than JANUS."""
        collab_agency = TaskAgency(
            execution_mode=ExecutionMode.COLLABORATIVE,
            support_mode=SupportMode.EXECUTE,
            reason="test",
        )
        janus_agency = TaskAgency(
            execution_mode=ExecutionMode.JANUS,
            support_mode=SupportMode.EXPLAIN,
            reason="test",
        )
        assert _agency_score_boost(collab_agency) > _agency_score_boost(janus_agency)

    def test_explain_beats_execute(self):
        """EXPLAIN support always scores higher than EXECUTE."""
        explain_agency = TaskAgency(
            execution_mode=ExecutionMode.USER,
            support_mode=SupportMode.EXPLAIN,
            reason="test",
        )
        execute_agency = TaskAgency(
            execution_mode=ExecutionMode.USER,
            support_mode=SupportMode.EXECUTE,
            reason="test",
        )
        assert _agency_score_boost(explain_agency) > _agency_score_boost(execute_agency)


# ── Agency-aware ranking ─────────────────────────────────────────────────────


class TestAgencyAwareRanking:
    """Verify that agency classification affects recommendation ranking.

    recommend_tasks returns one recommendation per goal (the next action).
    To test ranking across task types, we use multiple goals with different tasks.
    """

    def test_user_task_ranks_above_janus_task(self):
        """USER-mode task should rank above JANUS-mode task with same urgency."""
        goal_user = Goal(
            title="Learning Goal",
            milestones=[_milestone("M1")],
            related_tasks=["Learn Python"],
        )
        goal_janus = Goal(
            title="Admin Goal",
            milestones=[_milestone("M1")],
            related_tasks=["Sync data"],
        )
        tasks = [
            _task("Learn Python"),       # USER + EXPLAIN → boost 25
            _task("Sync data"),          # JANUS + EXECUTE → boost 0
        ]
        context = AgencyContext(skill_evidence_count=0, goal_health="healthy")

        result = recommend_tasks(
            [goal_user, goal_janus], tasks, set(), date.today(), agency_context=context
        )

        # Both goals should have recommendations
        assert len(result) >= 2

        # USER task should have higher score than JANUS task
        user_rec = next(r for r in result if r.title == "Learn Python")
        janus_rec = next(r for r in result if r.title == "Sync data")
        assert user_rec.score > janus_rec.score

    def test_collaborative_ranks_between_user_and_janus(self):
        """COLLABORATIVE should rank between USER and JANUS."""
        goal_user = Goal(
            title="Learning Goal",
            milestones=[_milestone("M1")],
            related_tasks=["Learn Python"],
        )
        goal_collab = Goal(
            title="Design Goal",
            milestones=[_milestone("M1")],
            related_tasks=["Design system"],
        )
        goal_janus = Goal(
            title="Admin Goal",
            milestones=[_milestone("M1")],
            related_tasks=["Sync data"],
        )
        tasks = [
            _task("Learn Python"),                           # USER → boost 25
            _task("Design system", extra_metadata=["estimate: 8 hours"]),  # COLLABORATIVE → boost 15
            _task("Sync data"),                              # JANUS → boost 0
        ]
        context = AgencyContext(skill_evidence_count=0, goal_health="healthy")

        result = recommend_tasks(
            [goal_user, goal_collab, goal_janus], tasks, set(), date.today(), agency_context=context
        )

        user_rec = next(r for r in result if r.title == "Learn Python")
        collab_rec = next(r for r in result if r.title == "Design system")
        janus_rec = next(r for r in result if r.title == "Sync data")

        assert user_rec.score > collab_rec.score
        assert collab_rec.score > janus_rec.score

    def test_no_agency_context_no_boost(self):
        """Without agency_context, scores should not include agency boost."""
        goal_user = Goal(
            title="Learning Goal",
            milestones=[_milestone("M1")],
            related_tasks=["Learn Python"],
        )
        goal_janus = Goal(
            title="Admin Goal",
            milestones=[_milestone("M1")],
            related_tasks=["Sync data"],
        )
        tasks = [
            _task("Learn Python"),
            _task("Sync data"),
        ]

        result = recommend_tasks([goal_user, goal_janus], tasks, set(), date.today())

        # Both should have agency=None
        assert all(r.agency is None for r in result)

        # Scores should be based on urgency only (both 0 for no due date/priority)
        user_rec = next(r for r in result if r.title == "Learn Python")
        janus_rec = next(r for r in result if r.title == "Sync data")
        assert user_rec.score == janus_rec.score

    def test_agency_boost_does_not_override_urgency(self):
        """Agency boost should not make a low-urgency USER task outrank a high-urgency JANUS task."""
        goal_user = Goal(
            title="Learning Goal",
            milestones=[_milestone("M1")],
            related_tasks=["Learn Python"],
        )
        goal_janus = Goal(
            title="Admin Goal",
            milestones=[_milestone("M1")],
            related_tasks=["Sync data"],
        )
        tasks = [
            _task("Learn Python"),                           # USER → boost 25, urgency 0
            _task("Sync data", due_date="2020-01-01"),       # JANUS → boost 0, urgency 100 (overdue)
        ]
        context = AgencyContext(skill_evidence_count=0, goal_health="healthy")

        result = recommend_tasks(
            [goal_user, goal_janus], tasks, set(), date.today(), agency_context=context
        )

        user_rec = next(r for r in result if r.title == "Learn Python")
        janus_rec = next(r for r in result if r.title == "Sync data")

        # JANUS task is overdue (urgency 100) — should still rank higher
        assert janus_rec.score > user_rec.score

    def test_milestone_action_has_no_agency_boost(self):
        """Milestone actions have no agency → no boost."""
        goal = Goal(
            title="G",
            milestones=[_milestone("M1")],
            related_tasks=[],
        )
        tasks: list[Task] = []
        context = AgencyContext(skill_evidence_count=0, goal_health="healthy")

        result = recommend_tasks([goal], tasks, set(), date.today(), agency_context=context)

        # Milestone action should have no agency
        assert len(result) > 0
        assert result[0].kind == "milestone"
        assert result[0].agency is None

    def test_project_action_has_no_agency_boost(self):
        """Project actions have no agency → no boost."""
        goal = Goal(
            title="G",
            milestones=[_milestone("M1")],
            projects=[{
                "title": "P1",
                "milestone_title": "M1",
                "status": "open",
                "order": 0,
                "related_tasks": [],
            }],
            related_tasks=[],
        )
        tasks: list[Task] = []
        context = AgencyContext(skill_evidence_count=0, goal_health="healthy")

        result = recommend_tasks([goal], tasks, set(), date.today(), agency_context=context)

        # Project action should have no agency
        assert len(result) > 0
        assert result[0].kind == "project"
        assert result[0].agency is None


# ── Edge cases ───────────────────────────────────────────────────────────────


class TestAgencyRankingEdgeCases:
    """Edge cases for agency-aware ranking."""

    def test_empty_goals(self):
        """No goals → no recommendations."""
        result = recommend_tasks([], [], set(), date.today())
        assert result == []

    def test_all_tasks_completed(self):
        """All tasks completed → milestone action (no agency)."""
        goal = Goal(
            title="G",
            milestones=[_milestone("M1")],
            related_tasks=["Learn Python"],
        )
        tasks: list[Task] = []
        context = AgencyContext(skill_evidence_count=0, goal_health="healthy")

        result = recommend_tasks(
            [goal], tasks, {"Learn Python"}, date.today(), agency_context=context
        )
        assert len(result) > 0
        assert result[0].kind == "milestone"
        assert result[0].agency is None

    def test_multiple_goals_independent_ranking(self):
        """Each goal's recommendations are ranked independently."""
        goal1 = Goal(
            title="Admin Goal",
            milestones=[_milestone("M1")],
            related_tasks=["Sync data"],
        )
        goal2 = Goal(
            title="Learning Goal",
            milestones=[_milestone("M1")],
            related_tasks=["Learn Python"],
        )
        tasks = [_task("Sync data"), _task("Learn Python")]
        context = AgencyContext(skill_evidence_count=0, goal_health="healthy")

        result = recommend_tasks(
            [goal1, goal2], tasks, set(), date.today(), agency_context=context
        )

        admin_recs = [r for r in result if r.goal_title == "Admin Goal"]
        learning_recs = [r for r in result if r.goal_title == "Learning Goal"]

        assert len(admin_recs) > 0
        assert len(learning_recs) > 0

        # Admin task → JANUS → lower score
        assert admin_recs[0].agency is not None
        assert admin_recs[0].agency.execution_mode == ExecutionMode.JANUS
        # Learning task → USER → higher score
        assert learning_recs[0].agency is not None
        assert learning_recs[0].agency.execution_mode == ExecutionMode.USER

    def test_agency_boost_with_filters(self):
        """Agency boost works correctly with kind/project/milestone filters."""
        goal_user = Goal(
            title="Learning Goal",
            milestones=[_milestone("M1")],
            related_tasks=["Learn Python"],
        )
        goal_janus = Goal(
            title="Admin Goal",
            milestones=[_milestone("M1")],
            related_tasks=["Sync data"],
        )
        tasks = [_task("Learn Python"), _task("Sync data")]
        context = AgencyContext(skill_evidence_count=0, goal_health="healthy")

        result = recommend_tasks(
            [goal_user, goal_janus], tasks, set(), date.today(),
            agency_context=context,
            kind_filter="task",
        )

        assert len(result) >= 2
        assert all(r.kind == "task" for r in result)

        user_rec = next(r for r in result if r.title == "Learn Python")
        janus_rec = next(r for r in result if r.title == "Sync data")
        assert user_rec.score > janus_rec.score

    def test_agency_boost_with_min_score(self):
        """Agency boost can push a task above min_score threshold."""
        goal = Goal(
            title="G",
            milestones=[_milestone("M1")],
            related_tasks=["Learn Python"],
        )
        tasks = [_task("Learn Python")]
        context = AgencyContext(skill_evidence_count=0, goal_health="healthy")

        # Without boost, score would be 0 (no due date, no priority)
        # With USER+EXPLAIN boost, score is 25
        result = recommend_tasks(
            [goal], tasks, set(), date.today(),
            agency_context=context,
            min_score=10,
        )
        assert len(result) == 1
        assert result[0].score >= 10

    def test_agency_boost_cannot_push_above_min_score_without_boost(self):
        """Without agency context, a task with score 0 should be filtered by min_score."""
        goal = Goal(
            title="G",
            milestones=[_milestone("M1")],
            related_tasks=["Learn Python"],
        )
        tasks = [_task("Learn Python")]

        result = recommend_tasks(
            [goal], tasks, set(), date.today(),
            min_score=10,
        )
        assert len(result) == 0
