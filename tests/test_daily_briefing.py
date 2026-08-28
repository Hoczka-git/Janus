from datetime import date

import pytest

from janus.models.task import Task
from janus.services.daily_briefing import create_daily_briefing


class TestDailyBriefing:
    def test_empty_briefing(self):
        today = date(2026, 8, 28)
        events = []
        tasks = []
        briefing = create_daily_briefing(events, tasks, today)

        assert len(briefing.overdue_tasks) == 0
        assert len(briefing.due_today_tasks) == 0
        assert len(briefing.high_priority_tasks) == 0
        assert len(briefing.suggested_focus) == 0

    def test_overdue_task(self):
        today = date(2026, 8, 28)
        overdue_task = Task(
            title="Book dentist appointment",
            due_date=date(2026, 8, 25),
            priority=1,
        )
        tasks = [overdue_task]
        briefing = create_daily_briefing(events=[], tasks=tasks, today=today)

        assert len(briefing.overdue_tasks) == 1
        assert briefing.overdue_tasks[0].title == "Book dentist appointment"
        assert len(briefing.due_today_tasks) == 0
        assert len(briefing.high_priority_tasks) == 0
        assert len(briefing.suggested_focus) == 1
        assert briefing.suggested_focus[0].title == "Book dentist appointment"

    def test_due_today_task(self):
        today = date(2026, 8, 28)
        due_today_task = Task(
            title="Buy groceries",
            due_date=today,
            priority=1,
        )
        tasks = [due_today_task]
        briefing = create_daily_briefing(events=[], tasks=tasks, today=today)

        assert len(briefing.overdue_tasks) == 0
        assert len(briefing.due_today_tasks) == 1
        assert briefing.due_today_tasks[0].title == "Buy groceries"
        assert len(briefing.high_priority_tasks) == 0
        assert len(briefing.suggested_focus) == 1
        assert briefing.suggested_focus[0].title == "Buy groceries"

    def test_high_priority_task(self):
        today = date(2026, 8, 28)
        high_priority_task = Task(
            title="Prepare training plan",
            due_date=date(2026, 9, 10),
            priority=3,
        )
        tasks = [high_priority_task]
        briefing = create_daily_briefing(events=[], tasks=tasks, today=today)

        assert len(briefing.overdue_tasks) == 0
        assert len(briefing.due_today_tasks) == 0
        assert len(briefing.high_priority_tasks) == 1
        assert briefing.high_priority_tasks[0].title == "Prepare training plan"
        assert len(briefing.suggested_focus) == 1
        assert briefing.suggested_focus[0].title == "Prepare training plan"

    def test_exclusivity_overdue_not_in_due_today(self):
        today = date(2026, 8, 28)
        overdue_task = Task(
            title="Book dentist appointment",
            due_date=date(2026, 8, 25),
            priority=1,
        )
        tasks = [overdue_task]
        briefing = create_daily_briefing(events=[], tasks=tasks, today=today)

        assert len(briefing.overdue_tasks) == 1
        assert len(briefing.due_today_tasks) == 0
        assert len(briefing.high_priority_tasks) == 0
        assert len(briefing.suggested_focus) == 1
        assert briefing.suggested_focus[0].title == "Book dentist appointment"

    def test_exclusivity_overdue_not_in_high_priority(self):
        today = date(2026, 8, 28)
        overdue_high_priority = Task(
            title="Overdue high priority",
            due_date=date(2026, 8, 25),
            priority=3,
        )
        tasks = [overdue_high_priority]
        briefing = create_daily_briefing(events=[], tasks=tasks, today=today)

        assert len(briefing.overdue_tasks) == 1
        assert len(briefing.due_today_tasks) == 0
        assert len(briefing.high_priority_tasks) == 0
        assert len(briefing.suggested_focus) == 1
        assert briefing.suggested_focus[0].title == "Overdue high priority"

    def test_exclusivity_due_today_not_in_high_priority(self):
        today = date(2026, 8, 28)
        due_today_high_priority = Task(
            title="Due today high priority",
            due_date=today,
            priority=3,
        )
        tasks = [due_today_high_priority]
        briefing = create_daily_briefing(events=[], tasks=tasks, today=today)

        assert len(briefing.overdue_tasks) == 0
        assert len(briefing.due_today_tasks) == 1
        assert len(briefing.high_priority_tasks) == 0
        assert len(briefing.suggested_focus) == 1
        assert briefing.suggested_focus[0].title == "Due today high priority"

    def test_suggested_focus_ordering(self):
        today = date(2026, 8, 28)
        overdue_task = Task(
            title="Overdue task",
            due_date=date(2026, 8, 25),
            priority=1,
        )
        due_today_task = Task(
            title="Due today task",
            due_date=today,
            priority=1,
        )
        high_priority_task = Task(
            title="High priority task",
            due_date=date(2026, 9, 10),
            priority=3,
        )
        tasks = [due_today_task, high_priority_task, overdue_task]
        briefing = create_daily_briefing(events=[], tasks=tasks, today=today)

        assert len(briefing.suggested_focus) == 3
        assert briefing.suggested_focus[0].title == "Overdue task"
        assert briefing.suggested_focus[1].title == "Due today task"
        assert briefing.suggested_focus[2].title == "High priority task"

    def test_suggested_focus_max_3(self):
        today = date(2026, 8, 28)
        tasks = [
            Task(title="Task 0", due_date=date(2026, 8, 24), priority=1),
            Task(title="Task 1", due_date=date(2026, 8, 25), priority=1),
            Task(title="Task 2", due_date=date(2026, 8, 26), priority=1),
            Task(title="Task 3", due_date=date(2026, 8, 27), priority=1),
            Task(title="Task 4", due_date=date(2026, 8, 28), priority=1),
        ]
        briefing = create_daily_briefing(events=[], tasks=tasks, today=today)

        assert len(briefing.suggested_focus) == 3
        assert [t.title for t in briefing.suggested_focus] == ["Task 0", "Task 1", "Task 2"]

    def test_suggested_focus_stable_ordering_same_priority(self):
        today = date(2026, 8, 28)
        task1 = Task(title="Task A", due_date=date(2026, 8, 25), priority=1)
        task2 = Task(title="Task B", due_date=date(2026, 8, 26), priority=1)
        task3 = Task(title="Task C", due_date=date(2026, 8, 27), priority=1)
        tasks = [task1, task2, task3]
        briefing = create_daily_briefing(events=[], tasks=tasks, today=today)

        assert len(briefing.suggested_focus) == 3
        assert [t.title for t in briefing.suggested_focus] == ["Task A", "Task B", "Task C"]
