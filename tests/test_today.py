from datetime import date, timedelta

import pytest

from janus.models.task import Task
from janus.today import requires_attention


@pytest.mark.parametrize(
    ("task", "today", "expected"),
    [
        (
            Task(
                title="Overdue task",
                due_date=date(2026, 8, 27),
            ),
            date(2026, 8, 28),
            True,
        ),
        (
            Task(
                title="Due today",
                due_date=date(2026, 8, 28),
            ),
            date(2026, 8, 28),
            True,
        ),
        (
            Task(
                title="Future task",
                due_date=date(2026, 8, 29),
            ),
            date(2026, 8, 28),
            False,
        ),
        (
            Task(
                title="High priority",
                priority=3,
            ),
            date(2026, 8, 28),
            True,
        ),
        (
            Task(
                title="Normal task",
                priority=1,
            ),
            date(2026, 8, 28),
            False,
        ),
    ],
)
def test_requires_attention(
    task: Task,
    today: date,
    expected: bool,
) -> None:
    assert requires_attention(task, today) is expected
