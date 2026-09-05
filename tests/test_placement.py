"""Tests for task placement computation."""

from datetime import date, datetime, timedelta, timezone

import pytest

from janus.models.attention import AttentionItem
from janus.models.task import Task
from janus.models.time_block import Placement, TimeBlock
from janus.services.placement import (
    suggest_placement,
    _parse_estimate_minutes,
)


FIXED_TODAY = date(2026, 8, 28)
LOCAL_TZ = timezone(timedelta(hours=2))


def _ts(hour: int, minute: int = 0) -> datetime:
    return datetime(FIXED_TODAY.year, FIXED_TODAY.month, FIXED_TODAY.day,
                    hour, minute, tzinfo=LOCAL_TZ)


def _slot(start_h: int, start_m: int, end_h: int, end_m: int) -> TimeBlock:
    return TimeBlock(
        start=_ts(start_h, start_m),
        end=_ts(end_h, end_m),
        type="free",
    )


def _task(title: str, extra_metadata=None) -> Task:
    return Task(title=title, due_date=None, priority=1,
                extra_metadata=extra_metadata)


def _item(title: str, category: str, score: int = 80) -> AttentionItem:
    return AttentionItem(title=title, reason="test", score=score,
                         category=category)


class TestEmptyInput:
    def test_no_free_slots_returns_empty(self):
        tasks = [_task("T1")]
        items = [_item("T1", "due_today", score=80)]
        placements = suggest_placement([], tasks, items)
        assert placements == []

    def test_no_tasks_returns_empty(self):
        slots = [_slot(10, 0, 11, 0)]
        placements = suggest_placement(slots, [], [])
        assert placements == []


class TestHighestScoreAssignedFirst:
    def test_highest_scored_task_gets_first_slot(self):
        slots = [
            _slot(10, 0, 11, 0),  # 60 min
            _slot(11, 0, 12, 0),  # 60 min
        ]
        tasks = [_task("T1"), _task("T2")]
        # attention_items pre-sorted by score (desc) — T2 (100) before T1 (50).
        items = [
            _item("T2", "overdue_task", score=100),
            _item("T1", "high_priority_task", score=50),
        ]
        placements = suggest_placement(slots, tasks, items)
        assert len(placements) == 2
        assert placements[0].task_title == "T2"
        assert placements[0].slot.start == _ts(10, 0)
        assert placements[1].task_title == "T1"
        assert placements[1].slot.start == _ts(11, 0)


class TestSlotConsumption:
    def test_two_tasks_same_slot_not_double_booked(self):
        """A slot consumed by one task is not reused for a second task."""
        slots = [_slot(10, 0, 11, 0)]  # only one slot
        tasks = [_task("T1"), _task("T2")]
        items = [
            _item("T1", "due_today", score=80),
            _item("T2", "due_today", score=80),
        ]
        placements = suggest_placement(slots, tasks, items)
        assert len(placements) == 1
        assert placements[0].task_title == "T1"  # first in score order

    def test_stops_when_no_slots_remain(self):
        slots = [_slot(10, 0, 10, 30)]  # 30 min, only fits one task
        tasks = [_task("T1"), _task("T2"), _task("T3")]
        items = [
            _item("T1", "due_today", score=80),
            _item("T2", "high_priority_task", score=50),
            _item("T3", "in_progress_task", score=30),
        ]
        placements = suggest_placement(slots, tasks, items)
        assert len(placements) == 1
        assert placements[0].task_title == "T1"


class TestMinSlotFilter:
    def test_slots_below_min_not_used(self):
        """Slots smaller than min_slot_minutes are skipped for placement."""
        slots = [_slot(10, 0, 10, 15)]  # 15 min
        tasks = [_task("T1")]
        items = [_item("T1", "due_today", score=80)]
        placements = suggest_placement(slots, tasks, items,
                                       min_slot_minutes=30)
        assert placements == []

    def test_custom_min_skips_small_slots(self):
        slots = [
            _slot(10, 0, 10, 15),  # 15 min, too small
            _slot(10, 30, 11, 30),  # 60 min, ok
        ]
        tasks = [_task("T1")]
        items = [_item("T1", "due_today", score=80)]
        placements = suggest_placement(slots, tasks, items,
                                       min_slot_minutes=30)
        assert len(placements) == 1
        assert placements[0].slot.start == _ts(10, 30)


class TestExcludedCategories:
    def test_upcoming_event_excluded(self):
        slots = [_slot(10, 0, 11, 0)]
        tasks = []
        items = [_item("Meeting", "upcoming_event", score=10)]
        placements = suggest_placement(slots, tasks, items)
        assert placements == []

    def test_goal_stalled_excluded(self):
        slots = [_slot(10, 0, 11, 0)]
        tasks = []
        items = [_item("Goal", "goal_stalled", score=40)]
        placements = suggest_placement(slots, tasks, items)
        assert placements == []


class TestEstimateMetadata:
    def test_estimate_metadata_skips_too_small_slots(self):
        """A task with estimate=90min skips a 30-min slot for a 90-min one."""
        slots = [
            _slot(10, 0, 10, 30),  # 30 min, too small for 90-min estimate
            _slot(11, 0, 12, 30),  # 90 min, fits
        ]
        tasks = [_task("T1", extra_metadata=["estimate: 90min"])]
        items = [_item("T1", "due_today", score=80)]
        placements = suggest_placement(slots, tasks, items)
        assert len(placements) == 1
        assert placements[0].slot.start == _ts(11, 0)
        assert "90 min" in placements[0].reason

    def test_estimate_hours_parsed(self):
        slots = [_slot(10, 0, 11, 0)]  # 60 min
        tasks = [_task("T1", extra_metadata=["estimate: 1h"])]
        items = [_item("T1", "due_today", score=80)]
        placements = suggest_placement(slots, tasks, items)
        assert len(placements) == 1
        assert "60 min" in placements[0].reason

    def test_no_estimate_in_reason(self):
        """Without an estimate, reason includes the no-duration qualifier."""
        slots = [_slot(10, 0, 11, 0)]
        tasks = [_task("T1")]
        items = [_item("T1", "due_today", score=80)]
        placements = suggest_placement(slots, tasks, items)
        assert len(placements) == 1
        assert "no task duration on record" in placements[0].reason


class TestParseEstimate:
    def test_min_format(self):
        assert _parse_estimate_minutes(["estimate: 90min"]) == 90

    def test_minutes_format(self):
        assert _parse_estimate_minutes(["duration: 45 minutes"]) == 45

    def test_hours_format(self):
        assert _parse_estimate_minutes(["estimate: 2 hours"]) == 120

    def test_decimal_hours(self):
        assert _parse_estimate_minutes(["estimate: 1.5 hours"]) == 90

    def test_no_estimate(self):
        assert _parse_estimate_minutes(["some other metadata"]) is None

    def test_none_metadata(self):
        assert _parse_estimate_minutes(None) is None

    def test_multiple_entries(self):
        assert _parse_estimate_minutes(
            ["priority: high", "estimate: 60min", "tag: work"]
        ) == 60
