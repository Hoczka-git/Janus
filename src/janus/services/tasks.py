"""Task write service for Janus.

Creates and persists tasks to data/tasks.md without touching
the existing loading logic.
"""

from datetime import date
from pathlib import Path
import logging

from janus._log import emit
from janus.models.task import Task
from janus.integrations.markdown_tasks import (
    _parse_task_line,
    _format_task_line,
)
from janus.integrations.data_protection import protected_write, protected_append, compute_content_hash

PROJECT_ROOT = Path(__file__).resolve().parents[3]
TASKS_PATH = PROJECT_ROOT / "data" / "tasks.md"

logger = logging.getLogger(__name__)


def add_task(title: str, due_date: date | None = None, priority: int = 1) -> Task:
    """Validate input, create a Task, append it to data/tasks.md, and return it."""
    _validate_title(title)
    _validate_priority(priority)
    _validate_due_date(due_date)

    task = Task(title=title, due_date=due_date, priority=priority)
    _append_task(task)

    emit(logger, "service.task.mutated",
         trace_id=None, span_id="service",
         operation="add", task_title=title,
         previous_state=None, new_state=None, new_progress=None,
         message=f"Task '{title}' added")

    return task


def complete_task(title: str) -> Task:
    """Find an open task by exact title, mark it completed, and return it.

    Raises:
        ValueError: if no matching open task is found, if multiple match,
                     or if the matching task is already completed.
    """
    _validate_title(title)

    raw_content = TASKS_PATH.read_text()
    lines = raw_content.splitlines()
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
        raise ValueError(f"Found {len(matches)} open tasks matching title: {title}")

    idx = matches[0]
    line = lines[idx]
    lines[idx] = "- [x] " + line[len("- [ ] "):]

    content = "\n".join(lines) + "\n"
    protected_write(
        TASKS_PATH,
        content,
        expected_hash=compute_content_hash(raw_content),
        written_by="services.tasks.complete_task",
    )

    emit(logger, "service.task.mutated",
         trace_id=None, span_id="service",
         operation="complete", task_title=title,
         previous_state="todo", new_state="completed", new_progress=None,
         message=f"Task '{title}' completed")

    return Task(title=title)


def complete_janus_task(title: str, evidence: dict | None = None) -> Task:
    """Mark a Janus task complete with execution-feedback evidence.

    Called by the Hermes-side execution-feedback sync listener when a
    Kanban task that carries ``janus_domain: object: task`` linkage
    completes.

    Finds the open task by exact title, marks it completed (checkbox
    ``- [x]``), and records evidence metadata on the task line.
    The evidence dict (with keys ``task_id``, ``summary``,
    ``completed_at``, ``changed_files``, ``tests_passed``, ``pr_url``)
    is serialized into ``extra_metadata`` as ``janus_evidence_*`` fields.

    Idempotent: if the task is already completed, it is re-written with
    the new evidence (no error).

    Args:
        title: exact task title (open or completed).
        evidence: Evidence package dict.

    Returns:
        The completed Task.

    Raises:
        ValueError: if no matching task is found or multiple match.
    """
    _validate_title(title)

    raw_content = TASKS_PATH.read_text()
    lines = raw_content.splitlines()
    matches: list[int] = []

    for i, line in enumerate(lines):
        # Match both open (- [ ]) and completed (- [x]) tasks
        if not (line.startswith("- [ ] ") or line.startswith("- [x] ")):
            continue
        content = line[len("- [ ] "):] if line.startswith("- [ ] ") \
            else line[len("- [x] "):]
        task_title = content.split(" | ", 1)[0] if " | " in content else content
        if task_title == title:
            matches.append(i)

    if not matches:
        raise ValueError(f"Task not found: {title}")
    if len(matches) > 1:
        raise ValueError(f"Multiple tasks found with title: {title}")

    idx = matches[0]
    task = _parse_task_line(lines[idx], idx + 1)
    # If already completed, _parse_task_line returns None; reconstruct from raw
    if task is None:
        content = lines[idx][len("- [x] "):]
        task_title = content.split(" | ", 1)[0] if " | " in content else content
        task = Task(title=task_title.strip())

    # Serialize evidence into extra_metadata
    ev = evidence or {}
    task.extra_metadata = task.extra_metadata or []
    # Remove any prior janus_evidence fields for idempotency
    task.extra_metadata = [
        m for m in task.extra_metadata if not m.startswith("janus_evidence_")
    ]
    if ev.get("task_id"):
        task.extra_metadata.append(f"janus_evidence_task_id: {ev['task_id']}")
    if ev.get("completed_at"):
        task.extra_metadata.append(f"janus_evidence_completed_at: {ev['completed_at']}")
    if ev.get("tests_passed") is not None:
        task.extra_metadata.append(
            f"janus_evidence_tests_passed: {ev['tests_passed']}"
        )
    if ev.get("pr_url"):
        task.extra_metadata.append(f"janus_evidence_pr_url: {ev['pr_url']}")
    if ev.get("changed_files"):
        for f in ev["changed_files"]:
            task.extra_metadata.append(f"janus_evidence_changed_file: {f}")

    # Format as completed
    line = f"- [x] {task.title}"
    parts = []
    if task.due_date is not None:
        parts.append(f"due: {task.due_date.isoformat()}")
    if task.priority != 1:
        parts.append(f"priority: {task.priority}")
    if task.state is not None:
        parts.append(f"state: {task.state}")
    if task.progress is not None:
        parts.append(f"progress: {task.progress}")
    if task.extra_metadata:
        parts.extend(task.extra_metadata)
    if parts:
        line += " | " + " | ".join(parts)
    lines[idx] = line

    content = "\n".join(lines) + "\n"
    protected_write(
        TASKS_PATH,
        content,
        expected_hash=compute_content_hash(raw_content),
        written_by="services.tasks.complete_janus_task",
    )

    emit(logger, "service.task.mutated",
         trace_id=None, span_id="service",
         operation="complete_janus_task", task_title=title,
         previous_state="todo" if not lines[idx].startswith("- [x]") else "completed",
         new_state="completed", new_progress=None,
         message=f"Task '{title}' completed with Janus evidence")

    return task


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


ALLOWED_STATES = frozenset({"todo", "in_progress", "blocked"})


def list_tasks() -> list[Task]:
    """Return all open (incomplete) tasks from data/tasks.md, in file order.

    Open tasks are those with an unchecked checkbox (``- [ ]``). Completed
    tasks (``- [x]``) are excluded and remain the sole responsibility of
    ``complete_task``.

    Uses the service-layer ``TASKS_PATH`` constant so that monkeypatching
    ``janus.services.tasks.TASKS_PATH`` (as tests and the CLI handler do) is
    respected.
    """
    from janus.integrations.markdown_tasks import load_tasks

    return load_tasks(TASKS_PATH)


def set_task_state(title: str, state: str) -> Task:
    """Update the state of an open task, preserving all other metadata.

    Args:
        title: exact task title to match
        state: one of 'todo', 'in_progress', 'blocked'

    Returns the updated Task.

    Raises:
        ValueError: if no matching open task found, if multiple match,
                     if the matching task is already completed, or if
                     the state value is invalid.
    """
    _validate_title(title)
    if state not in ALLOWED_STATES:
        raise ValueError(
            f"Invalid task state: {state!r}. "
            f"Allowed values: {', '.join(sorted(ALLOWED_STATES))}"
        )

    raw_content = TASKS_PATH.read_text()
    lines = raw_content.splitlines()
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
    task = _parse_task_line(lines[idx], idx + 1)
    if task is None:
        raise ValueError(f"Task not found: {title}")

    task.state = state
    lines[idx] = _format_task_line(task)
    content = "\n".join(lines) + "\n"
    protected_write(
        TASKS_PATH,
        content,
        expected_hash=compute_content_hash(raw_content),
        written_by="services.tasks.set_task_state",
    )

    emit(logger, "service.task.mutated",
         trace_id=None, span_id="service",
         operation="set_state", task_title=title,
         previous_state=None, new_state=state, new_progress=None,
         message=f"Task '{title}' state set to '{state}'")

    return task


def set_task_progress(title: str, progress: int) -> Task:
    """Update the progress of an open task, preserving all other metadata.

    Progress must be an integer between 0 and 100 inclusive.
    Progress 100 does NOT automatically complete the task —
    completion still requires `janus task complete`.

    Args:
        title: exact task title to match
        progress: integer between 0 and 100

    Returns the updated Task.

    Raises:
        ValueError: if no matching open task found, if multiple match,
                     if the matching task is already completed, or if
                     progress is not an integer in [0, 100].
    """
    _validate_title(title)
    if not isinstance(progress, int) or not (0 <= progress <= 100):
        raise ValueError(
            f"Progress must be an integer between 0 and 100, got {progress!r}"
        )

    raw_content = TASKS_PATH.read_text()
    lines = raw_content.splitlines()
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
    task = _parse_task_line(lines[idx], idx + 1)
    if task is None:
        raise ValueError(f"Task not found: {title}")

    task.progress = progress
    lines[idx] = _format_task_line(task)
    content = "\n".join(lines) + "\n"
    protected_write(
        TASKS_PATH,
        content,
        expected_hash=compute_content_hash(raw_content),
        written_by="services.tasks.set_task_progress",
    )

    emit(logger, "service.task.mutated",
         trace_id=None, span_id="service",
         operation="set_progress", task_title=title,
         previous_state=None, new_state=None, new_progress=progress,
         message=f"Task '{title}' progress set to {progress}%")

    return task


def _append_task(task: Task) -> None:
    line = _format_task_line(task)
    protected_append(
        TASKS_PATH,
        line + "\n",
        written_by="services.tasks._append_task",
    )


def _format_task_line(task: Task) -> str:
    parts = [f"- [ ] {task.title}"]

    if task.due_date is not None:
        parts.append(f"due: {task.due_date.isoformat()}")

    if task.priority != 1:
        parts.append(f"priority: {task.priority}")

    if task.state is not None:
        parts.append(f"state: {task.state}")

    if task.progress is not None:
        parts.append(f"progress: {task.progress}")

    if task.extra_metadata:
        parts.extend(task.extra_metadata)

    if len(parts) > 1:
        return " | ".join(parts)

    return parts[0]
