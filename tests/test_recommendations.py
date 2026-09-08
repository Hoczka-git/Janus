"""Tests for goal-aware task recommendations."""

from datetime import date

import pytest

from janus.models.goal import Goal
from janus.models.task import Task
from janus.models.project import Project
from janus.services.recommendations import (
    Recommendation,
    recommend_tasks,
    recommend_for_goal,
    recommend_next_actions,
    _task_base_score,
    _project_progress_score,
    _milestone_urgency_score,
)

FIXED_TODAY = date(2026, 8, 28)


def _task(title, due_date=None, priority=1):
    return Task(title=title, due_date=due_date, priority=priority)


def _goal(title, related_tasks=None, milestones=None, projects=None):
    return Goal(
        title=title,
        status="active",
        related_tasks=related_tasks or [],
        milestones=milestones or [],
        projects=projects or [],
    )


# ── Scoring helpers ──────────────────────────────────────────

class TestTaskBaseScore:
    def test_overdue_task(self):
        score = _task_base_score(_task("X", due_date="2026-08-01"), FIXED_TODAY)
        assert score >= 100

    def test_due_today(self):
        score = _task_base_score(_task("X", due_date="2026-08-28"), FIXED_TODAY)
        assert score >= 80

    def test_due_soon(self):
        score = _task_base_score(_task("X", due_date="2026-08-31"), FIXED_TODAY)
        assert score >= 60

    def test_high_priority(self):
        score = _task_base_score(_task("X", priority=3), FIXED_TODAY)
        assert score >= 30

    def test_no_due_date_no_priority(self):
        score = _task_base_score(_task("X"), FIXED_TODAY)
        assert score == 0


class TestProjectProgressScore:
    def test_all_completed(self):
        proj = Project(title="P", milestone_title="M", related_tasks=["A", "B"])
        score = _project_progress_score(proj, {"A", "B"})
        assert score == 1.0

    def test_half_completed(self):
        proj = Project(title="P", milestone_title="M", related_tasks=["A", "B"])
        score = _project_progress_score(proj, {"A"})
        assert score == 0.5

    def test_no_tasks(self):
        proj = Project(title="P", milestone_title="M", related_tasks=[])
        score = _project_progress_score(proj, set())
        assert score == 0.0


class TestMilestoneUrgencyScore:
    def test_overdue(self):
        score = _milestone_urgency_score({"deadline": "2026-08-01"}, FIXED_TODAY)
        assert score >= 50

    def test_due_today(self):
        score = _milestone_urgency_score({"deadline": "2026-08-28"}, FIXED_TODAY)
        assert score >= 40

    def test_no_deadline(self):
        score = _milestone_urgency_score({}, FIXED_TODAY)
        assert score == 0


# ── Recommendation basics ──────────────────────────────────

class TestRecommendTasks:
    def test_no_goals_returns_empty(self):
        result = recommend_tasks([], [], set(), FIXED_TODAY)
        assert result == []

    def test_inactive_goal_excluded(self):
        goal = _goal("G", related_tasks=["A"], milestones=[{"title": "M1", "status": "in_progress", "order": 0}])
        goal.status = "completed"
        result = recommend_tasks([goal], [_task("A")], set(), FIXED_TODAY)
        assert result == []

    def test_recommends_open_task(self):
        goal = _goal("G", related_tasks=["Task A"], milestones=[{"title": "M1", "status": "in_progress", "order": 0}])
        result = recommend_tasks([goal], [_task("Task A")], set(), FIXED_TODAY)
        assert len(result) >= 1
        assert result[0].kind == "task"
        assert result[0].title == "Task A"
        assert result[0].goal_title == "G"

    def test_goal_filter(self):
        g1 = _goal("Goal1", related_tasks=["A"], milestones=[{"title": "M1", "status": "in_progress", "order": 0}])
        g2 = _goal("Goal2", related_tasks=["B"], milestones=[{"title": "M2", "status": "in_progress", "order": 0}])
        result = recommend_tasks([g1, g2], [_task("A"), _task("B")], set(), FIXED_TODAY, goal_filter="Goal1")
        assert all(r.goal_title == "Goal1" for r in result)

    def test_kind_filter_task(self):
        goal = _goal("G", related_tasks=["A"], milestones=[{"title": "M1", "status": "in_progress", "order": 0}])
        result = recommend_tasks([goal], [_task("A")], set(), FIXED_TODAY, kind_filter="task")
        assert all(r.kind == "task" for r in result)

    def test_kind_filter_project(self):
        goal = _goal("G", milestones=[{"title": "M1", "status": "in_progress", "order": 0}])
        proj = Project(title="P1", milestone_title="M1", status="active", related_tasks=["A"])
        goal.projects = [proj]
        result = recommend_tasks([goal], [_task("A")], set(), FIXED_TODAY, kind_filter="project")
        # Task A is assigned to P1, so P1 is the current project with open task
        assert all(r.kind == "project" for r in result)

    def test_kind_filter_milestone(self):
        goal = _goal("G", milestones=[{"title": "M1", "status": "open", "order": 0}])
        result = recommend_tasks([goal], [], set(), FIXED_TODAY, kind_filter="milestone")
        assert all(r.kind == "milestone" for r in result)

    def test_min_score_filter(self):
        goal = _goal("G", related_tasks=["A"], milestones=[{"title": "M1", "status": "in_progress", "order": 0}])
        result = recommend_tasks([goal], [_task("A")], set(), FIXED_TODAY, min_score=999)
        assert result == []

    def test_max_results(self):
        goals = [
            _goal(f"G{i}", related_tasks=[f"A{i}"], milestones=[{"title": f"M{i}", "status": "in_progress", "order": 0}])
            for i in range(5)
        ]
        tasks = [_task(f"A{i}") for i in range(5)]
        result = recommend_tasks(goals, tasks, set(), FIXED_TODAY, max_results=2)
        assert len(result) <= 2


class TestRecommendForGoal:
    def test_single_goal(self):
        goal = _goal("G", related_tasks=["A"], milestones=[{"title": "M1", "status": "in_progress", "order": 0}])
        result = recommend_for_goal(goal, [_task("A")], set(), FIXED_TODAY)
        assert len(result) >= 1
        assert result[0].goal_title == "G"

    def test_project_filter(self):
        goal = _goal("G", related_tasks=["A", "B"], milestones=[{"title": "M1", "status": "in_progress", "order": 0}])
        proj = Project(title="P1", milestone_title="M1", status="active", related_tasks=["A"])
        goal.projects = [proj]
        result = recommend_for_goal(goal, [_task("A"), _task("B")], set(), FIXED_TODAY, project_filter="P1")
        assert all(r.project_title == "P1" for r in result)

    def test_milestone_filter(self):
        goal = _goal("G", related_tasks=["A"], milestones=[
            {"title": "M1", "status": "in_progress", "order": 0},
            {"title": "M2", "status": "open", "order": 1},
        ])
        result = recommend_tasks([goal], [_task("A")], set(), FIXED_TODAY, milestone_filter="M1")
        assert all(r.milestone_title == "M1" for r in result)


class TestRecommendNextActions:
    def test_returns_tasks_only(self):
        goal = _goal("G", related_tasks=["A"], milestones=[{"title": "M1", "status": "in_progress", "order": 0}])
        result = recommend_next_actions([goal], [_task("A")], set(), FIXED_TODAY)
        assert all(r.kind == "task" for r in result)

    def test_max_5_results(self):
        goals = [
            _goal(f"G{i}", related_tasks=[f"A{i}"], milestones=[{"title": f"M{i}", "status": "in_progress", "order": 0}])
            for i in range(10)
        ]
        tasks = [_task(f"A{i}") for i in range(10)]
        result = recommend_next_actions(goals, tasks, set(), FIXED_TODAY)
        assert len(result) <= 5


class TestRecommendationFields:
    def test_recommendation_has_all_fields(self):
        goal = _goal("G", related_tasks=["A"], milestones=[{"title": "M1", "status": "in_progress", "order": 0}])
        result = recommend_tasks([goal], [_task("A")], set(), FIXED_TODAY)
        assert len(result) >= 1
        rec = result[0]
        assert isinstance(rec.title, str)
        assert rec.kind in ("task", "project", "milestone")
        assert isinstance(rec.goal_title, str)
        assert isinstance(rec.score, int)
        assert isinstance(rec.reason, str)

    def test_project_recommendation_has_project_title(self):
        goal = _goal("G", milestones=[{"title": "M1", "status": "in_progress", "order": 0}])
        proj = Project(title="P1", milestone_title="M1", status="active", related_tasks=["A"])
        goal.projects = [proj]
        result = recommend_tasks([goal], [_task("A")], set(), FIXED_TODAY)
        assert len(result) >= 1
        rec = result[0]
        assert rec.project_title is not None or rec.kind != "project"

    def test_milestone_recommendation_has_milestone_title(self):
        goal = _goal("G", milestones=[{"title": "M1", "status": "open", "order": 0}])
        result = recommend_tasks([goal], [], set(), FIXED_TODAY)
        assert len(result) >= 1
        rec = result[0]
        assert rec.milestone_title == "M1" or rec.kind != "milestone"


class TestRecommendationWithProjects:
    def test_project_assignment_overrides_dynamic(self):
        """I6: explicit project assignment wins over dynamic derivation."""
        goal = _goal("G", related_tasks=["A", "B"], milestones=[
            {"title": "M1", "status": "in_progress", "order": 0},
            {"title": "M2", "status": "open", "order": 1},
        ])
        proj = Project(title="P1", milestone_title="M1", status="active", related_tasks=["B"])
        goal.projects = [proj]
        result = recommend_tasks([goal], [_task("A"), _task("B")], set(), FIXED_TODAY)
        assert len(result) >= 1
        # B is assigned to P1, so P1 should be recommended first
        rec = result[0]
        assert rec.kind == "project" or rec.title == "B"

    def test_completed_project_excluded(self):
        goal = _goal("G", milestones=[{"title": "M1", "status": "in_progress", "order": 0}])
        proj = Project(title="P1", milestone_title="M1", status="completed", related_tasks=["A"])
        goal.projects = [proj]
        result = recommend_tasks([goal], [_task("A")], set(), FIXED_TODAY)
        # P1 is completed, so it should not be recommended
        assert not any(r.kind == "project" and r.project_title == "P1" for r in result)

    def test_project_with_no_tasks(self):
        goal = _goal("G", milestones=[{"title": "M1", "status": "in_progress", "order": 0}])
        proj = Project(title="P1", milestone_title="M1", status="active")
        goal.projects = [proj]
        result = recommend_tasks([goal], [], set(), FIXED_TODAY)
        assert len(result) >= 1
        assert result[0].kind == "project"
        assert result[0].title == "P1"


class TestRecommendationRanking:
    def test_sorted_by_score_descending(self):
        goal = _goal("G", related_tasks=["A", "B", "C"], milestones=[
            {"title": "M1", "status": "in_progress", "order": 0},
        ])
        tasks = [
            _task("A", due_date="2026-08-29", priority=3),
            _task("B", due_date="2026-08-30", priority=2),
            _task("C", due_date="2026-09-01", priority=1),
        ]
        result = recommend_tasks([goal], tasks, set(), FIXED_TODAY)
        # Scores should be descending
        for i in range(len(result) - 1):
            assert result[i].score >= result[i + 1].score

    def test_task_ranked_higher_than_project(self):
        """Tasks should generally rank higher than projects."""
        goal = _goal("G", related_tasks=["A"], milestones=[
            {"title": "M1", "status": "in_progress", "order": 0},
        ])
        result = recommend_tasks([goal], [_task("A")], set(), FIXED_TODAY)
        if len(result) > 1:
            # Task should come before project
            task_indices = [i for i, r in enumerate(result) if r.kind == "task"]
            project_indices = [i for i, r in enumerate(result) if r.kind == "project"]
            if task_indices and project_indices:
                assert task_indices[0] < project_indices[0]