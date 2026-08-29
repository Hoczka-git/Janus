"""Task write service for Janus.

Creates and persists tasks to data/tasks.md without touching
the existing loading logic.
"""

from datetime import date
from pathlib import Path

from janus.models.task import Task

PROJECT_ROOT = Path(__file__).resolve().parents[3]
TASKS_PATH = PROJECT_ROOT / "data" / "tasks.md"


def add_task(title: str, due_date: date | None = None, priority: int = 1) -> Task:
    """Validate input, create a Task, append it to data/tasks.md, and return it."""
    _validate_title(title)
    _validate_priority(priority)
    _validate_due_date(due_date)

    task = Task(title=title, due_date=due_date, priority=priority)
    _append_task(task)

    return task


def complete_task(title: str) -> Task:
    """Find an open task by exact title, mark it completed, and return it.

    Raises:
        ValueError: if no matching open task is found, if multiple match,
                     or if the matching task is already completed.
    """
    _validate_title(title)

    lines = TASKS_PATH.read_text().splitlines()
    matches: list[int] = []

    for i, line in enumerate(lines):
        if not line.startswith("- [ ] "):
            continue
        content = line[len("- [ ] "):]
        task_title = content.split(" | ", 1)[0] if " | " in content else content
        if task_title == title:
            matches.append(i)

    if not matches:
        raise ValueError(f"Task not found: {title}")
    if len(matches) > 1:
        raise ValueError(f"Multiple open tasks found with title: {title}")

    idx = matches[0]
    line = lines[idx]
    lines[idx] = "- [x] " + line[len("- [ ] "):]

    TASKS_PATH.write_text("\n".join(lines) + "\n")

    return Task(title=title)


def _validate_title(title: str) -> None:
    if not title or not title.strip():
        raise ValueError("Task title cannot be empty")


def _validate_priority(priority: int) -> None:
    if priority < 1:
        raise ValueError("Priority must be >= 1")


def _validate_due_date(due_date: date | None) -> None:
    if due_date is not None:
        try:
            date.fromisoformat(due_date.isoformat())
        except ValueError:
            raise ValueError(f"Invalid due date: {due_date}")


def _append_task(task: Task) -> None:
    line = _format_task_line(task)
    with TASKS_PATH.open("a") as f:
        f.write(line + "\n")


def _format_task_line(task: Task) -> str:
    parts = [f"- [ ] {task.title}"]

    if task.due_date is not None:
        parts.append(f"due: {task.due_date.isoformat()}")

    if task.priority != 1:
        parts.append(f"priority: {task.priority}")

    if len(parts) > 1:
        return " | ".join(parts)

    return parts[0]
