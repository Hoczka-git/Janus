"""Markdown task loader for Janus."""

import re
from pathlib import Path
from datetime import date

from janus.models.task import Task


PROJECT_ROOT = Path(__file__).resolve().parents[3]
TASKS_PATH = PROJECT_ROOT / "data" / "tasks.md"


def load_tasks() -> list[Task]:
    """Load open tasks from data/tasks.md."""
    if not TASKS_PATH.exists():
        raise FileNotFoundError(f"Task file not found: {TASKS_PATH}")

    tasks: list[Task] = []

    with TASKS_PATH.open() as f:
        for line_num, line in enumerate(f, start=1):
            line = line.strip()

            if not line.startswith("- [ ]"):
                continue

            task = _parse_task_line(line, line_num)
            if task is not None:
                tasks.append(task)

    return tasks


def _parse_task_line(line: str, line_num: int) -> Task | None:
    """Parse a single task line. Returns None for completed tasks."""
    if line.startswith("- [x]"):
        return None

    content = line[5:].strip()
    title, metadata = _split_title_metadata(content)
    due_date = _parse_due_date(metadata, line_num)
    priority = _parse_priority(metadata, line_num)

    return Task(
        title=title,
        due_date=due_date,
        priority=priority,
    )


def _split_title_metadata(content: str) -> tuple[str, str]:
    """Split task content into title and metadata parts."""
    if "|" not in content:
        return content.strip(), ""

    parts = content.split("|", 1)
    return parts[0].strip(), parts[1]


def _parse_due_date(metadata: str, line_num: int) -> date | None:
    """Parse due date from metadata. Raises ValueError for invalid dates."""
    match = re.search(r"due:\s*(\S+)", metadata)
    if not match:
        return None

    date_str = match.group(1)
    try:
        return date.fromisoformat(date_str)
    except ValueError:
        raise ValueError(
            f"Invalid due date in task at line {line_num}: {date_str}"
        )


def _parse_priority(metadata: str, line_num: int) -> int:
    """Parse priority from metadata. Raises ValueError for invalid priorities."""
    match = re.search(r"priority:\s*(\S+)", metadata)
    if not match:
        return 1

    priority_str = match.group(1)
    try:
        return int(priority_str)
    except ValueError:
        raise ValueError(
            f"Invalid priority in task at line {line_num}: {priority_str}"
        )
