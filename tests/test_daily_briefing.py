"""Tests for Daily Briefing service with the Attention Engine."""

from datetime import date

import pytest

from janus.models.task import Task
from janus.models.goal import Goal
from janus.services.daily_briefing import create_daily_briefing


class TestDailyBriefing:
    def test_empty_briefing(self):
        today = date(2026, 8, 28)
        events = []
        tasks = []
        goals = []
        briefing = create_daily_briefing(events, tasks, goals, today)

        assert briefing.attention_items == []
        assert briefing.suggested_focus is None

    def test_overdue_task(self):
        today = date(2026, 8, 28)
        overdue_task = Task(
            title="Book dentist appointment",
            due_date=date(2026, 8, 25),
            priority=1,
        )
        tasks = [overdue_task]
        goals = []
        briefing = create_daily_briefing([], tasks, goals, today)

        assert len(briefing.attention_items) == 1
        item = briefing.attention_items[0]
        assert item.title == "Book dentist appointment"
        assert item.category == "overdue_task"
        assert item.score == 100
        assert "Overdue by 3 days" in item.reason
        assert briefing.suggested_focus is not None
        assert briefing.suggested_focus.title == "Book dentist appointment"

    def test_due_today_task(self):
        today = date(2026, 8, 28)
        due_today_task = Task(
            title="Buy groceries",
            due_date=today,
            priority=1,
        )
        tasks = [due_today_task]
        goals = []
        briefing = create_daily_briefing([], tasks, goals, today)

        assert len(briefing.attention_items) == 1
        item = briefing.attention_items[0]
        assert item.title == "Buy groceries"
        assert item.category == "due_today"
        assert item.score == 80
        assert "Due today" in item.reason

    def test_high_priority_task(self):
        today = date(2026, 8, 28)
        high_priority_task = Task(
            title="Prepare training plan",
            due_date=date(2026, 9, 10),
            priority=3,
        )
        tasks = [high_priority_task]
        goals = []
        briefing = create_daily_briefing([], tasks, goals, today)

        assert len(briefing.attention_items) == 1
        item = briefing.attention_items[0]
        assert item.title == "Prepare training plan"
        assert item.category == "high_priority_task"
        assert item.score == 50
        assert "High priority task" in item.reason

    def test_overdue_high_priority_accumulates(self):
        today = date(2026, 8, 28)
        task = Task(
            title="Urgent dentist",
            due_date=date(2026, 8, 25),
            priority=3,
        )
        tasks = [task]
        goals = []
        briefing = create_daily_briefing([], tasks, goals, today)

        assert len(briefing.attention_items) == 1
        assert briefing.attention_items[0].score == 150  # 100 + 50

    def test_due_today_priority_2_accumulates(self):
        today = date(2026, 8, 28)
        task = Task(
            title="Due today P2",
            due_date=today,
            priority=2,
        )
        tasks = [task]
        goals = []
        briefing = create_daily_briefing([], tasks, goals, today)

        assert len(briefing.attention_items) == 1
        assert briefing.attention_items[0].score == 100  # 80 + 20

    def test_suggested_focus_is_highest_score(self):
        today = date(2026, 8, 28)
        tasks = [
            Task(title="Overdue", due_date=date(2026, 8, 25), priority=1),  # 100
            Task(title="High priority future", due_date=date(2026, 9, 10), priority=3),  # 50
            Task(title="Due today", due_date=today, priority=1),  # 80
        ]
        goals = []
        briefing = create_daily_briefing([], tasks, goals, today)

        assert len(briefing.attention_items) == 3
        assert briefing.suggested_focus is not None
        assert briefing.suggested_focus.title == "Overdue"  # 100 > 80 > 50
        assert [item.title for item in briefing.attention_items] == \
               ["Overdue", "Due today", "High priority future"]

    def test_suggested_focus_max_3_in_briefing(self):
        """Daily Briefing carries all items; renderer limits to 3."""
        today = date(2026, 8, 28)
        tasks = [
            Task(title=f"Task {i}", due_date=date(2026, 8, 24 - i),
                 priority=1)
            for i in range(5)
        ]
        goals = []
        briefing = create_daily_briefing([], tasks, goals, today)

        # Engine returns all 5; renderer will show 3.
        assert len(briefing.attention_items) == 5

    def test_goal_stalled_attracts_attention(self):
        today = date(2026, 8, 28)
        tasks = []
        goals = [Goal(title="Training", status="active",
                      related_tasks=["Prepare training plan"])]
        briefing = create_daily_briefing([], tasks, goals, today)

        assert len(briefing.attention_items) == 1
        item = briefing.attention_items[0]
        assert item.title == "Training"
        assert item.category == "goal_stalled"
        assert item.score == 40
        assert "All linked tasks are completed" in item.reason

    def test_goal_with_open_task_not_stalled(self):
        today = date(2026, 8, 28)
        tasks = [Task(title="Open task", due_date=None, priority=1)]
        goals = [Goal(title="Training", status="active",
                      related_tasks=["Open task"])]
        briefing = create_daily_briefing([], tasks, goals, today)

        # Goal should not generate stalled item because open task exists
        stalled_items = [i for i in briefing.attention_items if i.category == "goal_stalled"]
        assert len(stalled_items) == 0

    def test_multiple_goals_one_stalled(self):
        today = date(2026, 8, 28)
        tasks = []
        goals = [
            Goal(title="G1", status="active", related_tasks=["Prepare training plan"]),
            Goal(title="G2", status="active", related_tasks=["Nope task"]),  # missing ref
        ]
        briefing = create_daily_briefing([], tasks, goals, today)

        assert len(briefing.attention_items) == 1
        assert briefing.attention_items[0].title == "G1"
