"""Overload detection for Janus calendar-aware planning.

Determines whether a day is overloaded relative to available work-hours,
using both measured busy-fraction and an estimate-free task-count heuristic.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

from janus.models.event import Event
from janus.models.task import Task
from janus.models.time_block import TimeBlock

PROJECT_ROOT = Path(__file__).resolve().parents[3]
CONFIG_PATH = PROJECT_ROOT / "config" / "config.toml"


@dataclass
class PlanningConfig:
    """Configuration for calendar-aware planning.

    All values are optional with sensible defaults so existing configs
    without a ``[planning]`` section continue to work.
    """

    work_hours_start: int = 9
    work_hours_end: int = 17
    min_focus_slot_minutes: int = 30
    overload_task_count_threshold: int = 4
    overload_busy_fraction_threshold: float = 0.5

    # Derived constants (not user-configurable).
    work_hours_total: int = field(init=False)  # total minutes in work window
    _crit_fraction: float = field(default=0.8, init=False)

    def __post_init__(self) -> None:
        self.work_hours_total = (self.work_hours_end - self.work_hours_start) * 60

    @property
    def work_hours(self) -> tuple[int, int]:
        return (self.work_hours_start, self.work_hours_end)

    def critical_busy_fraction(self) -> float:
        return self._crit_fraction


def load_planning_config(path: Optional[Path] = None) -> PlanningConfig:
    """Load the ``[planning]`` section from config.toml.

    Returns a PlanningConfig with defaults for any missing field. If the
    config file does not exist or has no ``[planning]`` section, all values
    are defaults.
    """
    config_path = path or CONFIG_PATH
    if not config_path.exists():
        return PlanningConfig()

    with config_path.open("rb") as f:
        data = tomllib.load(f)

    section = data.get("planning", {})
    return PlanningConfig(
        work_hours_start=section.get("work_hours_start", 9),
        work_hours_end=section.get("work_hours_end", 17),
        min_focus_slot_minutes=section.get("min_focus_slot_minutes", 30),
        overload_task_count_threshold=section.get("overload_task_count_threshold", 4),
        overload_busy_fraction_threshold=section.get(
            "overload_busy_fraction_threshold", 0.5
        ),
    )


def _urgent_task_count(tasks: list[Task], today: date) -> int:
    """Count tasks that are overdue + due today + high priority (priority>=3)."""
    count = 0
    for task in tasks:
        overdue = (task.due_date is not None and task.due_date < today)
        due_today = (task.due_date is not None and task.due_date == today)
        high_prio = task.priority >= 3
        if overdue or due_today or high_prio:
            count += 1
    return count


def _urgent_task_count_for_overload(tasks: list[Task], today: date) -> int:
    """Count tasks that are overdue OR due today OR high priority.

    Per spec §6.1 criterion 2: 'overdue + due today + high priority (priority >= 3).'
    A task qualifies if it matches any of these.
    """
    return _urgent_task_count(tasks, today)


def evaluate_load(
    events: list[Event],
    tasks: list[Task],
    day: date,
    free_slots: list[TimeBlock],
    config: Optional[PlanningConfig] = None,
) -> tuple[Optional[str], Optional[str]]:
    """Evaluate whether a day is overloaded.

    Args:
        events: Today's events.
        tasks: Open tasks.
        day: The date being evaluated.
        free_slots: Free slots computed for the day (from compute_free_slots).
        config: Planning thresholds. Defaults to loaded config.

    Returns:
        (warning_level, message) where warning_level is "warning" or
        "critical", or (None, None) if not overloaded. The message includes
        a confidence tag: ``[measured]`` (busy-fraction) or ``[estimated]``
        (task-count fallback).
    """
    cfg = config or load_planning_config()
    total_minutes = cfg.work_hours_total
    if total_minutes <= 0:
        return (None, None)

    urgent_count = _urgent_task_count_for_overload(tasks, day)

    # ── Criterion 1: busy-fraction overload (primary, measured) ──────────────
    free_minutes = sum(slot.duration_minutes for slot in free_slots)
    busy_minutes = total_minutes - free_minutes
    busy_fraction = busy_minutes / total_minutes

    if busy_fraction > cfg.critical_busy_fraction():
        # e.g. >80% busy → critical
        busy_hours = busy_minutes / 60
        msg = (
            f"⚠ HIGH MEETING LOAD TODAY — {busy_hours:.0f}/{total_minutes/60:.0f} hours "
            f"scheduled. {urgent_count} task(s) due today. [measured]"
        )
        return ("critical", msg)

    if busy_fraction > cfg.overload_busy_fraction_threshold:
        # e.g. >50% busy → warning
        busy_hours = busy_minutes / 60
        msg = (
            f"⚠ HIGH MEETING LOAD TODAY — {busy_hours:.0f}/{total_minutes/60:.0f} hours "
            f"scheduled. {urgent_count} task(s) due today. [measured]"
        )
        return ("warning", msg)

    # ── Criterion 2: task-count overload (fallback, estimated) ───────────────
    if urgent_count >= cfg.overload_task_count_threshold:
        free_hours = free_minutes / 60
        msg = (
            f"⚠ HIGH TASK LOAD TODAY — {urgent_count} urgent task(s) "
            f"(overdue/due today/high priority) with {free_hours:.0f} hour(s) "
            f"of free time. [estimated]"
        )
        return ("warning", msg)

    # ── Criterion 3: free-slot exhaustion ────────────────────────────────────
    min_double = cfg.min_focus_slot_minutes * 2
    has_small_slots = bool(free_slots) and not any(
        slot.duration_minutes >= min_double for slot in free_slots
    )
    if has_small_slots and urgent_count >= 1:
        largest = max(slot.duration_minutes for slot in free_slots)
        msg = (
            f"⚠ No focus block large enough for deep work "
            f"(largest free block: {largest} min). {urgent_count} urgent "
            f"task(s) due today. [estimated]"
        )
        return ("warning", msg)

    return (None, None)
