"""Tests for overload detection."""

from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from janus.models.event import Event
from janus.models.task import Task
from janus.models.time_block import TimeBlock
from janus.services.overload import (
    PlanningConfig,
    evaluate_load,
    load_planning_config,
)


FIXED_TODAY = date(2026, 8, 28)
LOCAL_TZ = timezone(timedelta(hours=2))


def _ts(hour: int, minute: int = 0, tz=LOCAL_TZ) -> datetime:
    return datetime(FIXED_TODAY.year, FIXED_TODAY.month, FIXED_TODAY.day,
                    hour, minute, tzinfo=tz)


def _timed_event(title: str, sh: int, sm: int, eh: int, em: int) -> Event:
    return Event(title=title, start=_ts(sh, sm), end=_ts(eh, em), all_day=False)


def _task(title: str, due=None, priority: int = 1) -> Task:
    return Task(title=title, due_date=due, priority=priority)


DEFAULT_CFG = PlanningConfig()  # 9-17, 480 min work window


class TestNoOverload:
    def test_low_busy_and_few_tasks(self):
        """≤50% busy and ≤3 urgent tasks → (None, None)."""
        events = [_timed_event("M", 9, 0, 11, 0)]  # 2 hours busy
        free_slots = [
            TimeBlock(start=_ts(11, 0), end=_ts(17, 0), type="free"),
        ]
        tasks = [_task("One", due=FIXED_TODAY, priority=1)]
        level, msg = evaluate_load(events, tasks, FIXED_TODAY, free_slots, DEFAULT_CFG)
        assert level is None
        assert msg is None

    def test_empty_everything(self):
        events = []
        # Full window free.
        free_slots = [
            TimeBlock(start=_ts(9, 0), end=_ts(17, 0), type="free"),
        ]
        tasks = []
        level, msg = evaluate_load(events, tasks, FIXED_TODAY, free_slots, DEFAULT_CFG)
        assert level is None
        assert msg is None


class TestBusyFractionWarning:
    def test_warning_above_50_percent_busy(self):
        """>50% of work hours busy → warning [measured]."""
        # 4.5 hours busy out of 8 → 0.5625 > 0.5
        events = [_timed_event("M", 9, 0, 13, 30)]  # 270 min busy / 480 = 0.5625
        free_slots = [
            TimeBlock(start=_ts(13, 30), end=_ts(17, 0), type="free"),
        ]
        tasks = []
        level, msg = evaluate_load(events, tasks, FIXED_TODAY, free_slots, DEFAULT_CFG)
        assert level == "warning"
        assert msg is not None
        assert "[measured]" in msg
        assert "4" in msg  # 4 hours scheduled (4.5 truncated to 4)
        assert "8" in msg


class TestBusyFractionCritical:
    def test_critical_above_80_percent_busy(self):
        """>80% of work hours busy → critical [measured]."""
        # 6 hours busy out of 8 → 75% is warning. Need >80% → e.g. 390 min (6.5h).
        events = [_timed_event("M", 9, 0, 15, 30)]  # 390 min / 480 = 0.8125
        free_slots = [
            TimeBlock(start=_ts(15, 30), end=_ts(17, 0), type="free"),
        ]
        tasks = []
        level, msg = evaluate_load(events, tasks, FIXED_TODAY, free_slots, DEFAULT_CFG)
        assert level == "critical"
        assert "[measured]" in msg

    def test_fully_booked_is_critical(self):
        """9-17 fully booked → critical."""
        events = [_timed_event("M", 9, 0, 17, 0)]  # 480 min busy = 100%
        free_slots = []
        tasks = []
        level, msg = evaluate_load(events, tasks, FIXED_TODAY, free_slots, DEFAULT_CFG)
        assert level == "critical"
        assert "[measured]" in msg


class TestTaskCountFallback:
    def test_task_count_warning_when_low_busy(self):
        """Low busy fraction but ≥4 urgent tasks → warning [estimated]."""
        # Very light calendar (only 1 hour), but 4 urgent tasks.
        events = [_timed_event("M", 9, 0, 10, 0)]  # 60 min / 480 = 12.5%
        free_slots = [
            TimeBlock(start=_ts(10, 0), end=_ts(17, 0), type="free"),
        ]
        tasks = [
            _task("T1", due=FIXED_TODAY, priority=1),       # due today
            _task("T2", due=date(2026, 8, 25), priority=1), # overdue
            _task("T3", due=date(2026, 9, 10), priority=3), # high prio
            _task("T4", due=date(2026, 9, 10), priority=3), # high prio
        ]
        level, msg = evaluate_load(events, tasks, FIXED_TODAY, free_slots, DEFAULT_CFG)
        assert level == "warning"
        assert "[estimated]" in msg

    def test_below_task_count_threshold_no_warning(self):
        """3 urgent tasks (below threshold of 4) and low busy → no warning."""
        events = [_timed_event("M", 9, 0, 10, 0)]
        free_slots = [
            TimeBlock(start=_ts(10, 0), end=_ts(17, 0), type="free"),
        ]
        tasks = [
            _task("T1", due=FIXED_TODAY, priority=1),
            _task("T2", due=date(2026, 8, 25), priority=1),
            _task("T3", due=date(2026, 9, 10), priority=3),
        ]
        level, msg = evaluate_load(events, tasks, FIXED_TODAY, free_slots, DEFAULT_CFG)
        assert level is None
        assert msg is None


class TestFreeSlotExhaustion:
    def test_small_slots_with_urgent_task_warning(self):
        """Free slots exist but none ≥ 2*min_slot_minutes, with ≥1 urgent → warning."""
        events = []
        # 8 free slots of 30 min each, all < 60 (= 2*30).
        # Total free = 240 min → busy = 240 → 50% (not >50%, so criterion 1
        # doesn't fire). Each slot is 30 min (< 60), and ≥1 urgent task.
        free_slots = [
            TimeBlock(start=_ts(9, 0), end=_ts(9, 30), type="free"),
            TimeBlock(start=_ts(9, 30), end=_ts(10, 0), type="free"),
            TimeBlock(start=_ts(10, 0), end=_ts(10, 30), type="free"),
            TimeBlock(start=_ts(10, 30), end=_ts(11, 0), type="free"),
            TimeBlock(start=_ts(11, 0), end=_ts(11, 30), type="free"),
            TimeBlock(start=_ts(11, 30), end=_ts(12, 0), type="free"),
            TimeBlock(start=_ts(12, 0), end=_ts(12, 30), type="free"),
            TimeBlock(start=_ts(12, 30), end=_ts(13, 0), type="free"),
        ]
        tasks = [_task("Urgent", due=FIXED_TODAY, priority=1)]
        level, msg = evaluate_load(events, tasks, FIXED_TODAY, free_slots, DEFAULT_CFG)
        assert level == "warning"
        assert "[estimated]" in msg

    def test_small_slots_without_urgent_no_warning(self):
        """Small slots but no urgent tasks → no warning."""
        events = []
        # 10 free slots of 30 min each = 300 min free (180 min busy = 37.5% < 50%).
        # All slots < 60 min, but no urgent task → no criterion-3 trigger.
        free_slots = [
            TimeBlock(start=_ts(9, 0), end=_ts(9, 30), type="free"),
            TimeBlock(start=_ts(9, 30), end=_ts(10, 0), type="free"),
            TimeBlock(start=_ts(10, 0), end=_ts(10, 30), type="free"),
            TimeBlock(start=_ts(10, 30), end=_ts(11, 0), type="free"),
            TimeBlock(start=_ts(11, 0), end=_ts(11, 30), type="free"),
            TimeBlock(start=_ts(11, 30), end=_ts(12, 0), type="free"),
            TimeBlock(start=_ts(12, 0), end=_ts(12, 30), type="free"),
            TimeBlock(start=_ts(12, 30), end=_ts(13, 0), type="free"),
            TimeBlock(start=_ts(13, 0), end=_ts(13, 30), type="free"),
            TimeBlock(start=_ts(13, 30), end=_ts(14, 0), type="free"),
        ]
        tasks = [_task("Future", due=date(2026, 9, 10), priority=1)]  # not urgent
        level, msg = evaluate_load(events, tasks, FIXED_TODAY, free_slots, DEFAULT_CFG)
        assert level is None
        assert msg is None


class TestConfidenceTag:
    def test_measured_tag_for_busy_fraction(self):
        events = [_timed_event("M", 9, 0, 14, 0)]  # 300/480 = 0.625 > 0.5
        free_slots = [
            TimeBlock(start=_ts(14, 0), end=_ts(17, 0), type="free"),
        ]
        tasks = []
        level, msg = evaluate_load(events, tasks, FIXED_TODAY, free_slots, DEFAULT_CFG)
        assert level == "warning"
        assert "[measured]" in msg

    def test_estimated_tag_for_task_count(self):
        events = [_timed_event("M", 9, 0, 10, 0)]  # 60/480 = 0.125
        free_slots = [
            TimeBlock(start=_ts(10, 0), end=_ts(17, 0), type="free"),
        ]
        tasks = [
            _task("T1", due=FIXED_TODAY, priority=1),
            _task("T2", due=FIXED_TODAY, priority=1),
            _task("T3", due=FIXED_TODAY, priority=1),
            _task("T4", due=FIXED_TODAY, priority=1),
        ]
        level, msg = evaluate_load(events, tasks, FIXED_TODAY, free_slots, DEFAULT_CFG)
        assert level == "warning"
        assert "[estimated]" in msg


class TestConfigLoader:
    def test_defaults_when_no_config(self):
        cfg = load_planning_config(path=Path("/nonexistent/config.toml"))
        assert cfg.work_hours_start == 9
        assert cfg.work_hours_end == 17
        assert cfg.min_focus_slot_minutes == 30
        assert cfg.overload_task_count_threshold == 4
        assert cfg.overload_busy_fraction_threshold == 0.5
        assert cfg.work_hours_total == 480

    def test_loads_planning_section(self, tmp_path):
        config_path = tmp_path / "config.toml"
        config_path.write_text(
            "[planning]\n"
            "work_hours_start = 8\n"
            "work_hours_end = 18\n"
            "min_focus_slot_minutes = 45\n"
            "overload_task_count_threshold = 3\n"
            "overload_busy_fraction_threshold = 0.6\n"
        )
        cfg = load_planning_config(path=config_path)
        assert cfg.work_hours_start == 8
        assert cfg.work_hours_end == 18
        assert cfg.work_hours_total == 600
        assert cfg.min_focus_slot_minutes == 45
        assert cfg.overload_task_count_threshold == 3
        assert cfg.overload_busy_fraction_threshold == 0.6


class TestCustomConfig:
    def test_critical_threshold_with_custom_config(self):
        cfg = PlanningConfig(
            work_hours_start=8, work_hours_end=16,
            overload_busy_fraction_threshold=0.5,
        )
        assert cfg.work_hours_total == 480
        # 90% busy → critical (>80%)
        events = [_timed_event("M", 8, 0, 15, 36)]  # 456 min / 480 = 0.95
        free_slots = [
            TimeBlock(start=_ts(15, 36), end=_ts(16, 0), type="free"),
        ]
        tasks = []
        level, msg = evaluate_load(events, tasks, FIXED_TODAY, free_slots, cfg)
        assert level == "critical"
