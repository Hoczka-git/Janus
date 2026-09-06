"""Markdown task loader for Janus."""

import logging
import re
from pathlib import Path
from datetime import date

from janus._log import emit
from janus.models.task import Task, ALLOWED_STATES


PROJECT_ROOT = Path(__file__).resolve().parents[3]
TASKS_PATH = PROJECT_ROOT / "data" / "tasks.md"

logger = logging.getLogger(__name__)


def load_tasks(
    path: Path | None = None,
    trace_id: str | None = None,
) -> list[Task]:
    """Load open tasks from data/tasks.md.

    Args:
        path: Optional explicit file path. When omitted, the module-level
            ``TASKS_PATH`` is used. Callers that own their own path constant
            (e.g. ``janus.services.tasks``) should pass it explicitly so that
            monkeypatching at the service layer is respected.
        trace_id: Trace identifier propagated for observability events.
    """
    tasks_path = path if path is not None else TASKS_PATH
    if not tasks_path.exists():
        raise FileNotFoundError(f"Task file not found: {tasks_path}")

    tasks: list[Task] = []
    lines_scanned = 0

    with tasks_path.open() as f:
        for line_num, line in enumerate(f, start=1):
            lines_scanned += 1
            line = line.strip()

            if not line.startswith("- [ ]"):
                continue

            task = _parse_task_line(line, line_num)
            if task is not None:
                tasks.append(task)

    emit(logger, "source.tasks.loaded",
         trace_id=trace_id, span_id="load_tasks",
         correlation_id=trace_id,
         file_path=str(tasks_path),
         lines_scanned=lines_scanned,
         tasks_loaded=len(tasks),
         parse_errors=0,
         message=f"Loaded {len(tasks)} open tasks from tasks.md")

    return tasks


def _parse_task_line(line: str, line_num: int) -> Task | None:
    """Parse a single task line. Returns None for completed tasks."""
    if line.startswith("- [x]"):
        return None
    content = line[5:].strip()
    title, metadata = _split_title_metadata(content)
    due_date = _parse_due_date(metadata, line_num)
    priority = _parse_priority(metadata, line_num)
    state = _parse_state(metadata, line_num)
    progress = _parse_progress(metadata, line_num)
    extra_metadata = _extract_unknown_metadata(metadata)

    return Task(
        title=title,
        due_date=due_date,
        priority=priority,
        state=state,
        progress=progress,
        extra_metadata=extra_metadata,
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


def _parse_state(metadata: str, line_num: int) -> str | None:
    """Parse state from metadata. Returns None if not present.

    Odrzuca 'done' jako invalid — jedynym autorytetem jest checkbox [x].
    """
    match = re.search(r"state:\s*(\S+)", metadata)
    if not match:
        return None

    state_str = match.group(1)
    if state_str not in ALLOWED_STATES:
        raise ValueError(
            f"Invalid task state at line {line_num}: {state_str!r}. "
            f"Allowed values: {', '.join(sorted(ALLOWED_STATES))}"
        )

    return state_str


def _parse_progress(metadata: str, line_num: int) -> int | None:
    """Parse progress from metadata. Returns None if not present.

    Progress must be an integer between 0 and 100.
    """
    match = re.search(r"progress:\s*(\S+)", metadata)
    if not match:
        return None

    progress_str = match.group(1)
    try:
        progress = int(progress_str)
    except ValueError:
        raise ValueError(
            f"Invalid progress at line {line_num}: {progress_str!r}. "
            f"Must be an integer between 0 and 100"
        )

    if not (0 <= progress <= 100):
        raise ValueError(
            f"Progress must be between 0 and 100 at line {line_num}: {progress}"
        )

    return progress


def _extract_unknown_metadata(metadata: str) -> list[str]:
    """Extract unknown metadata fields that should be preserved.

    Znane pola (due, priority, state, progress) są parsowane i usuwane z
    metadanych; pozostałe pola są zachowywane jako lista stringów.
    """
    known_patterns = [
        r"due:\s*\S+",
        r"priority:\s*\S+",
        r"state:\s*\S+",
        r"progress:\s*\S+",
    ]

    remaining = metadata
    for pattern in known_patterns:
        remaining = re.sub(pattern, "", remaining)

    parts = [p.strip() for p in remaining.split("|") if p.strip()]
    return parts


def _format_task_line(task: Task) -> str:
    """Format a Task back to a markdown line.

    Format: - [ ] Title | due: ... | priority: ... | state: ... | progress: ...

    Known fields are normalized. Unknown fields (extra_metadata) are appended
    after known fields to preserve them.
    """
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
