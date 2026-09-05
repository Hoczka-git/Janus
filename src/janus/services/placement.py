"""Task placement computation for Janus calendar-aware planning.

Recommends realistic task placement into available free focus blocks,
using attention scores to prioritize which tasks get first choice of slots.
"""

from __future__ import annotations

import re

from janus.models.attention import AttentionItem
from janus.models.task import Task
from janus.models.time_block import Placement, TimeBlock

# Task-derived attention categories eligible for placement.
_PLACEMENT_CATEGORIES = frozenset({
    "overdue_task",
    "due_today",
    "high_priority_task",
    "blocked_task",
    "in_progress_task",
})

# Best-effort estimate parsing from extra_metadata entries.
# Order matters: check hours first (more specific), then minutes.
_ESTIMATE_HOURS_RE = re.compile(
    r"(?:estimate|duration)\s*:\s*(\d+(?:\.\d+)?)\s*hours?", re.IGNORECASE
)
_ESTIMATE_MIN_RE = re.compile(
    r"(?:estimate|duration)\s*:\s*(\d+)\s*(?:min|minutes)", re.IGNORECASE
)
_ESTIMATE_H_RE = re.compile(
    r"(?:estimate|duration)\s*:\s*(\d+(?:\.\d+)?)\s*h\b", re.IGNORECASE
)


def _parse_estimate_minutes(extra_metadata: list[str] | None) -> int | None:
    """Best-effort parse of an estimated duration from task extra_metadata.

    Supports ``estimate: 90min``, ``duration: 2h``, ``estimate: 1.5 hours``.
    Returns None if no estimate is present or parseable.
    """
    if not extra_metadata:
        return None

    for entry in extra_metadata:
        m = _ESTIMATE_HOURS_RE.search(entry)
        if m:
            return int(float(m.group(1)) * 60)
        m = _ESTIMATE_H_RE.search(entry)
        if m:
            return int(float(m.group(1)) * 60)
        m = _ESTIMATE_MIN_RE.search(entry)
        if m:
            return int(m.group(1))

    return None


def _build_reason(
    task: Task,
    slot: TimeBlock,
    urgent: bool,
) -> str:
    """Build a human-readable placement reason with confidence qualifier."""
    estimate = _parse_estimate_minutes(task.extra_metadata)

    if estimate is not None:
        if slot.duration_minutes >= estimate:
            basis = (
                f"Due today; fits in available {slot.duration_minutes}-min block "
                f"(duration estimate: {estimate} min)"
            )
        else:
            basis = (
                f"Partial fit — slot is {slot.duration_minutes} min "
                f"but estimate is {estimate} min"
            )
    else:
        qualifier = "estimated fit — no task duration on record"
        hint = "Due today" if urgent else "High priority"
        basis = f"{hint}; fits in available {slot.duration_minutes}-min block ({qualifier})"

    return basis


def suggest_placement(
    free_slots: list[TimeBlock],
    tasks: list[Task],
    attention_items: list[AttentionItem],
    min_slot_minutes: int = 30,
) -> list[Placement]:
    """Recommend task placement into available free focus blocks.

    Args:
        free_slots: Available free TimeBlocks (sorted by start, from
            compute_free_slots).
        tasks: Open tasks.
        attention_items: Already-scored attention items (from the Attention
            Engine). Task-derived items in placement-eligible categories are
            used to prioritize placement.
        min_slot_minutes: Minimum slot size for placement. Default 30.

    Returns:
        Placements in attention-score order, each consuming one free slot.
        Empty list when no free slots exist.
    """
    # Collect placement-eligible attention items, preserving the existing
    # score-ordered arrangement of attention_items.
    eligible_items: list[AttentionItem] = [
        item for item in attention_items
        if item.category in _PLACEMENT_CATEGORIES
    ]

    # Map titles to Task objects for metadata lookup.
    task_by_title = {t.title: t for t in tasks}

    # Consume free slots as we assign tasks.
    available_slots = list(free_slots)  # sorted by start (from compute_free_slots)
    placements: list[Placement] = []

    for item in eligible_items:
        if not available_slots:
            break

        # Find the first slot that meets the minimum and (if estimate exists)
        # is large enough. Without an estimate, any slot >= min qualifies.
        task = task_by_title.get(item.title)
        estimate = _parse_estimate_minutes(task.extra_metadata) if task else None

        chosen_idx: int | None = None
        for idx, slot in enumerate(available_slots):
            if slot.duration_minutes < min_slot_minutes:
                continue
            if estimate is not None and slot.duration_minutes < estimate:
                continue
            chosen_idx = idx
            break

        if chosen_idx is None:
            continue

        chosen_slot = available_slots.pop(chosen_idx)
        urgent = item.category in ("overdue_task", "due_today", "in_progress_task")
        reason = _build_reason(task, chosen_slot, urgent) if task else (
            f"Slot available {chosen_slot.start:%H:%M}–{chosen_slot.end:%H:%M}"
        )
        placements.append(Placement(
            task_title=item.title,
            slot=chosen_slot,
            reason=reason,
        ))

    return placements
