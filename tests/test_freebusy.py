"""Tests for calendar free/busy slot computation."""

from datetime import date, datetime, timedelta, timezone

import pytest

from janus.models.event import Event
from janus.models.time_block import TimeBlock
from janus.services.freebusy import compute_free_slots


FIXED_TODAY = date(2026, 8, 28)
LOCAL_TZ = timezone(timedelta(hours=2))  # arbitrary fixed tz for determinism


def _ts(hour: int, minute: int = 0, tz=LOCAL_TZ) -> datetime:
    """Build a timezone-aware datetime for FIXED_TODAY at the given local time."""
    return datetime(FIXED_TODAY.year, FIXED_TODAY.month, FIXED_TODAY.day,
                    hour, minute, tzinfo=tz)


def _timed_event(title: str, sh: int, sm: int, eh: int, em: int) -> Event:
    """Timed event from (start hour, start min) to (end hour, end min)."""
    return Event(
        title=title,
        start=_ts(sh, sm),
        end=_ts(eh, em),
        all_day=False,
    )


class TestNoEvents:
    def test_empty_events_returns_full_work_window(self):
        """No events (configured calendar, empty result) → full window."""
        slots = compute_free_slots([], FIXED_TODAY, tz=LOCAL_TZ)
        assert len(slots) == 1
        assert slots[0].is_free
        assert slots[0].start == _ts(9, 0)
        assert slots[0].end == _ts(17, 0)
        assert slots[0].duration_minutes == 480


class TestGapComputation:
    def test_correct_gaps_between_non_overlapping_events(self):
        """9-10:30 busy, 11-12 busy → gaps 10:30-11 and 12-17."""
        events = [
            _timed_event("Standup", 9, 0, 10, 30),
            _timed_event("Deep work", 11, 0, 12, 0),
        ]
        slots = compute_free_slots(events, FIXED_TODAY, tz=LOCAL_TZ)
        assert len(slots) == 2
        assert slots[0].start == _ts(10, 30)
        assert slots[0].end == _ts(11, 0)
        assert slots[0].duration_minutes == 30
        assert slots[1].start == _ts(12, 0)
        assert slots[1].end == _ts(17, 0)
        assert slots[1].duration_minutes == 300

    def test_full_window_one_slot(self):
        events = [_timed_event("Busy", 9, 0, 17, 0)]
        slots = compute_free_slots(events, FIXED_TODAY, tz=LOCAL_TZ)
        assert slots == []


class TestMerging:
    def test_overlapping_events_merged(self):
        """Two overlapping events produce one merged busy interval."""
        events = [
            _timed_event("Meeting A", 9, 0, 11, 0),
            _timed_event("Meeting B", 10, 0, 12, 0),  # overlaps with A
        ]
        slots = compute_free_slots(events, FIXED_TODAY, tz=LOCAL_TZ)
        assert len(slots) == 1
        assert slots[0].start == _ts(12, 0)
        assert slots[0].end == _ts(17, 0)
        assert slots[0].duration_minutes == 300

    def test_back_to_back_meetings_merged_boundary(self):
        """Events that touch (end == next start) merge into one block."""
        events = [
            _timed_event("A", 9, 0, 10, 0),
            _timed_event("B", 10, 0, 12, 0),
        ]
        slots = compute_free_slots(events, FIXED_TODAY, tz=LOCAL_TZ)
        assert len(slots) == 1
        assert slots[0].start == _ts(12, 0)
        assert slots[0].end == _ts(17, 0)


class TestMinSlot:
    def test_slots_below_minimum_filtered(self):
        """15-min gaps with default 30-min minimum are dropped."""
        events = [
            _timed_event("A", 9, 0, 10, 0),
            _timed_event("B", 10, 15, 10, 30),  # gap 10:00-10:15 = 15 min
            _timed_event("C", 10, 45, 15, 0),  # gap 10:30-10:45 = 15 min
        ]
        slots = compute_free_slots(events, FIXED_TODAY, tz=LOCAL_TZ)
        # Only the 15:00-17:00 gap (120 min) survives.
        assert len(slots) == 1
        assert slots[0].start == _ts(15, 0)
        assert slots[0].end == _ts(17, 0)

    def test_slots_above_minimum_kept(self):
        events = [
            _timed_event("A", 9, 0, 10, 0),
            _timed_event("B", 10, 30, 11, 0),  # gap 10:00-10:30 = 30 min
        ]
        slots = compute_free_slots(events, FIXED_TODAY, tz=LOCAL_TZ)
        assert len(slots) == 2
        assert slots[0].duration_minutes == 30
        assert slots[1].duration_minutes == 360

    def test_custom_min_slot(self):
        events = [
            _timed_event("A", 9, 0, 10, 0),
            _timed_event("B", 10, 30, 11, 0),  # 30-min gap
        ]
        # With 60-min threshold, the 30-min gap is dropped; only 11-17 kept.
        slots = compute_free_slots(events, FIXED_TODAY, min_slot_minutes=60,
                                   tz=LOCAL_TZ)
        assert len(slots) == 1
        assert slots[0].start == _ts(11, 0)


class TestWorkHoursClamp:
    def test_events_outside_work_hours_ignored_from_blocks(self):
        """Event 8-18 with work hours 9-17 → busy 9-17, free within window only."""
        events = [_timed_event("Wide", 8, 0, 18, 0)]
        slots = compute_free_slots(events, FIXED_TODAY, tz=LOCAL_TZ)
        assert slots == []

    def test_event_starting_before_work_hours_clamped(self):
        """Event starting at 7 ends at 10:30 → busy clamped to 9-10:30."""
        events = [_timed_event("Early", 7, 0, 10, 30)]
        slots = compute_free_slots(events, FIXED_TODAY, tz=LOCAL_TZ)
        assert len(slots) == 1
        assert slots[0].start == _ts(10, 30)
        assert slots[0].end == _ts(17, 0)

    def test_custom_work_hours(self):
        events = [_timed_event("M", 10, 0, 11, 0)]
        slots = compute_free_slots(events, FIXED_TODAY,
                                   work_hours=(10, 14), tz=LOCAL_TZ)
        assert len(slots) == 1
        assert slots[0].start == _ts(11, 0)
        assert slots[0].end == _ts(14, 0)
        assert slots[0].duration_minutes == 180


class TestAllDayEvents:
    def test_all_day_event_excluded_from_computation(self):
        """All-day events should not appear as timed busy blocks."""
        events = [
            Event(title="Holiday", start=_ts(0, 0), end=None, all_day=True),
        ]
        slots = compute_free_slots(events, FIXED_TODAY, tz=LOCAL_TZ)
        # No timed events → full work window.
        assert len(slots) == 1
        assert slots[0].is_free


class TestMissingEndTime:
    def test_timed_event_without_end_falls_back_to_60_minutes(self):
        """A timed event with end=None blocks for 60 minutes from start."""
        events = [
            Event(title="Odd event", start=_ts(10, 0), end=None, all_day=False),
        ]
        slots = compute_free_slots(events, FIXED_TODAY, tz=LOCAL_TZ)
        assert len(slots) == 2
        assert slots[0].start == _ts(9, 0)
        assert slots[0].end == _ts(10, 0)
        assert slots[1].start == _ts(11, 0)
        assert slots[1].end == _ts(17, 0)


class TestOtherDayEvents:
    def test_events_on_other_days_excluded(self):
        """Events on a different day do not affect today's free slots."""
        other_day = datetime(2026, 8, 29, 10, 0, tzinfo=LOCAL_TZ)
        events = [
            Event(title="Tomorrow", start=other_day,
                  end=other_day.replace(hour=12), all_day=False),
        ]
        slots = compute_free_slots(events, FIXED_TODAY, tz=LOCAL_TZ)
        assert len(slots) == 1
        assert slots[0].start == _ts(9, 0)
        assert slots[0].end == _ts(17, 0)
