"""Tests for the Attention Engine."""

from datetime import date, datetime, timezone
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import pytest

from janus.models.attention import AttentionItem
from janus.models.event import Event
from janus.models.goal import Goal
from janus.models.task import Task
from janus.services.attention import get_attention_items
from janus.services.daily_briefing import create_daily_briefing


FIXED_TODAY = date(2026, 8, 28)

# =============================================================================
# Helpers
# =============================================================================

def _make_event(title: str, hour: int, minute: int) -> Event:
    start = datetime(FIXED_TODAY.year, FIXED_TODAY.month, FIXED_TODAY.day,
                     hour, minute, tzinfo=timezone.utc)
    return Event(title=title, start=start, all_day=False)

def _make_all_day_event(title: str) -> Event:
    start = datetime(FIXED_TODAY.year, FIXED_TODAY.month, FIXED_TODAY.day,
                     0, 0, tzinfo=timezone.utc)
    return Event(title=title, start=start, all_day=True)

def _make_task(title: str, due: date | None, priority: int = 1, completed: bool = False) -> Task:
    return Task(title=title, due_date=due, priority=priority)

def _make_goal(title: str, status: str = "active",
               related_tasks: list[str] | None = None) -> Goal:
    return Goal(title=title, status=status,
                related_tasks=related_tasks or [])


# =============================================================================
# 1. Task attention
# =============================================================================

class TestOverdueTask:
    def test_overdue_detected(self):
        tasks = [_make_task("Overdue task", date(2026, 8, 25), priority=1)]
        items = get_attention_items([], tasks, [], FIXED_TODAY)
        assert len(items) == 1
        assert items[0].title == "Overdue task"
        assert items[0].category == "overdue_task"
        assert items[0].score == 100
        assert "Overdue by 3 days" in items[0].reason

    def test_overdue_high_priority_accumulates(self):
        tasks = [_make_task("Urgent overdue", date(2026, 8, 25), priority=3)]
        items = get_attention_items([], tasks, [], FIXED_TODAY)
        assert len(items) == 1
        assert items[0].score == 150  # 100 + 50

    def test_priority_3_with_overdue_date_produces_item(self):
        """A priority 3 task with an overdue due date produces one attention item.

        The engine does not filter for 'completed' — that contract is enforced
        by load_tasks(), which only returns open Markdown tasks.
        """
        tasks = [_make_task("Urgent overdue high priority", date(2026, 8, 25), priority=3)]
        items = get_attention_items([], tasks, [], FIXED_TODAY)
        assert len(items) == 1
        assert items[0].category == "overdue_task"
        assert items[0].score == 150  # 100 overdue + 50 priority 3

    def test_task_without_due_date_not_overdue(self):
        tasks = [_make_task("No due date", None, priority=1)]
        items = get_attention_items([], tasks, [], FIXED_TODAY)
        assert len(items) == 0


class TestDueTodayTask:
    def test_due_today_detected(self):
        tasks = [_make_task("Due today task", FIXED_TODAY, priority=2)]
        items = get_attention_items([], tasks, [], FIXED_TODAY)
        assert len(items) == 1
        assert items[0].title == "Due today task"
        assert items[0].category == "due_today"
        assert items[0].score == 100  # 80 + 20


    def test_due_today_not_overdue(self):
        tasks = [_make_task("Due today", FIXED_TODAY, priority=1)]
        items = get_attention_items([], tasks, [], FIXED_TODAY)
        assert len(items) == 1
        assert items[0].category == "due_today"
        assert items[0].score == 80


class TestPriorityScoring:
    def test_priority_3_detected(self):
        tasks = [_make_task("Priority 3 task", date(2026, 9, 10), priority=3)]
        items = get_attention_items([], tasks, [], FIXED_TODAY)
        assert len(items) == 1
        assert items[0].category == "high_priority_task"
        assert items[0].score == 50

    def test_priority_2_without_other_condition_excluded(self):
        tasks = [_make_task("Priority 2 future", date(2026, 9, 10), priority=2)]
        items = get_attention_items([], tasks, [], FIXED_TODAY)
        assert len(items) == 0

    def test_priority_2_with_due_today_qualifies(self):
        tasks = [_make_task("Priority 2 due today", FIXED_TODAY, priority=2)]
        items = get_attention_items([], tasks, [], FIXED_TODAY)
        assert len(items) == 1
        assert items[0].score == 100


# =============================================================================
# 2. Event attention
# =============================================================================

class TestUpcomingEvent:
    def test_event_today_included(self):
        events = [_make_event("Team meeting", 14, 0)]
        mock_now = datetime(FIXED_TODAY.year, FIXED_TODAY.month, FIXED_TODAY.day,
                            13, 0, tzinfo=timezone.utc)
        items = get_attention_items(events, [], [], FIXED_TODAY, now=mock_now)
        assert len(items) == 1
        assert items[0].category == "upcoming_event"
        assert items[0].score == 10

    def test_past_event_today_excluded(self):
        events = [_make_event("Past meeting", 8, 0)]
        mock_now = datetime(FIXED_TODAY.year, FIXED_TODAY.month, FIXED_TODAY.day,
                            9, 0, tzinfo=timezone.utc)
        items = get_attention_items(events, [], [], FIXED_TODAY, now=mock_now)
        assert len(items) == 0

    def test_future_day_event_excluded(self):
        future_date = date(2026, 8, 29)
        future_start = datetime(future_date.year, future_date.month, future_date.day,
                                10, 0, tzinfo=timezone.utc)
        events = [Event(title="Tomorrow meeting", start=future_start)]
        items = get_attention_items(events, [], [], FIXED_TODAY)
        assert len(items) == 0

    def test_event_scoring(self):
        events = [_make_event("Standup", 9, 30)]
        mock_now = datetime(FIXED_TODAY.year, FIXED_TODAY.month, FIXED_TODAY.day,
                            9, 0, tzinfo=timezone.utc)
        items = get_attention_items(events, [], [], FIXED_TODAY, now=mock_now)
        assert len(items) == 1
        assert items[0].score == 10


# =============================================================================
# 3. Goal stagnation
# =============================================================================

class TestGoalStagnation:
    def test_active_goal_with_open_related_task_not_stalled(self):
        goals = [_make_goal("Endurance challenge", "active",
                            ["Buy running shoes", "Prepare training plan"])]
        tasks = [
            _make_task("Buy running shoes", None, priority=1),
        ]
        items = get_attention_items([], tasks, goals, FIXED_TODAY)
        assert len(items) == 0

    def test_active_goal_all_related_completed_is_stalled(self):
        goals = [_make_goal("Endurance challenge", "active",
                            ["Prepare training plan"])]
        tasks = []  # no open tasks
        items = get_attention_items([], tasks, goals, FIXED_TODAY)
        assert len(items) == 1
        item = items[0]
        assert item.title == "Endurance challenge"
        assert item.category == "goal_stalled"
        assert item.score == 40
        assert item.reason == "All linked tasks are completed. Define the next milestone, add a new action, or mark the goal as complete."

    def test_inactive_goal_ignored(self):
        goals = [_make_goal("Paused goal", "inactive", ["Some task"])]
        tasks = []
        items = get_attention_items([], tasks, goals, FIXED_TODAY)
        assert len(items) == 0

    def test_completed_goal_ignored(self):
        goals = [_make_goal("Done goal", "completed", ["Some task"])]
        tasks = []
        items = get_attention_items([], tasks, goals, FIXED_TODAY)
        assert len(items) == 0

    def test_missing_related_task_does_not_stall(self):
        # Goal references a task that doesn't exist at all in tasks.md
        goals = [_make_goal("Endurance challenge", "active",
                            ["Buy running shoes"])]
        tasks = []  # no tasks at all
        items = get_attention_items([], tasks, goals, FIXED_TODAY)
        assert len(items) == 0

    def test_goal_with_no_related_tasks_ignored(self):
        goals = [_make_goal("Standalone goal", "active", [])]
        tasks = []
        items = get_attention_items([], tasks, goals, FIXED_TODAY)
        assert len(items) == 0


# =============================================================================
# 4. Sorting
# =============================================================================

class TestSorting:
    def test_higher_score_first(self):
        tasks = [
            _make_task("Low priority", date(2026, 9, 10), priority=3),  # 50
            _make_task("Overdue", date(2026, 8, 25), priority=1),        # 100
        ]
        items = get_attention_items([], tasks, [], FIXED_TODAY)
        assert items[0].score == 100
        assert items[0].title == "Overdue"
        assert items[1].score == 50

    def test_deterministic_tie_breaking(self):
        tasks = [
            _make_task("B task", date(2026, 9, 10), priority=3),
            _make_task("A task", date(2026, 9, 10), priority=3),
        ]
        items = get_attention_items([], tasks, [], FIXED_TODAY)
        assert items[0].title == "A task"
        assert items[1].title == "B task"


# =============================================================================
# 5. Daily Briefing integration
# =============================================================================

class TestDailyBriefingWithAttention:
    def test_attention_items_in_briefing(self):
        tasks = [_make_task("Overdue", date(2026, 8, 25), priority=1)]
        goals = [_make_goal("Stalled goal", "active", ["Prepare training plan"])]
        briefing = create_daily_briefing([], tasks, goals, FIXED_TODAY)
        assert len(briefing.attention_items) == 2

    def test_max_3_items_displayed_via_briefing(self):
        # Create 4 attention items, but briefing itself doesn't limit;
        # the renderer (today.py) will limit to 3.
        tasks = [
            _make_task("Overdue 1", date(2026, 8, 25), priority=1),
            _make_task("Overdue 2", date(2026, 8, 26), priority=1),
            _make_task("Overdue 3", date(2026, 8, 27), priority=1),
            _make_task("Overdue 4", date(2026, 8, 27), priority=1),
        ]
        briefing = create_daily_briefing([], tasks, [], FIXED_TODAY)
        assert len(briefing.attention_items) == 4

    def test_suggested_focus_is_highest_ranked(self):
        tasks = [
            _make_task("Overdue", date(2026, 8, 25), priority=1),
            _make_task("High priority future", date(2026, 9, 10), priority=3),
        ]
        briefing = create_daily_briefing([], tasks, [], FIXED_TODAY)
        assert len(briefing.suggested_focus) == 2
        assert briefing.suggested_focus[0].title == "Overdue"
        assert briefing.suggested_focus[0].score == 100

    def test_empty_attention_state(self):
        briefing = create_daily_briefing([], [], [], FIXED_TODAY)
        assert briefing.attention_items == []
        assert briefing.suggested_focus == []

    def test_schedule_rendering_still_works(self):
        events = [_make_event("Team meeting", 10, 0)]
        tasks = []
        goals = []
        briefing = create_daily_briefing(events, tasks, goals, FIXED_TODAY)
        assert len(briefing.events) == 1
        assert briefing.events[0].title == "Team meeting"

    def test_goal_stalled_can_be_suggested_focus(self):
        """A stalled active goal with the highest attention score may become suggested_focus."""
        goals = [_make_goal("Training", "active", ["Prepare training plan"])]
        briefing = create_daily_briefing([], [], goals, FIXED_TODAY)
        assert len(briefing.suggested_focus) == 1
        assert briefing.suggested_focus[0].category == "goal_stalled"
        assert briefing.suggested_focus[0].title == "Training"
        assert "Define the next milestone" in briefing.suggested_focus[0].reason
