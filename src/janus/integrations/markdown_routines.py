"""Markdown routine loader for Janus — parses data/routines.md."""
import logging
import re
from pathlib import Path
from datetime import date, datetime

from janus.integrations.atomic_io import read_modify_write
from janus.models.routine import Routine, RoutineFrequency

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
ROUTINES_PATH = PROJECT_ROOT / "data" / "routines.md"


def load_routines(
    path: Path | None = None,
    trace_id: str | None = None,
) -> list[Routine]:
    """Load all routines from data/routines.md.

    Returns [] if file is missing.
    """
    fp = path if path is not None else ROUTINES_PATH
    if not fp.exists():
        return []

    items: list[Routine] = []
    lines_scanned = 0

    with fp.open() as f:
        for line_num, line in enumerate(f, start=1):
            lines_scanned += 1
            line = line.strip()
            if not line.startswith("rt-"):
                continue
            item = _parse_routine_line(line, line_num)
            if item is not None:
                items.append(item)

    logger.debug("Loaded %d routines from %s", len(items), fp)
    return items


def _parse_routine_line(line: str, line_num: int) -> Routine:
    """Parse one line → Routine. Raises ValueError on bad metadata."""
    # Format: rt-<id> | <title> | frequency: <freq> | status: <status> | ...
    parts = line.split(" | ", 1)
    id_part = parts[0]
    rest = parts[1] if len(parts) > 1 else ""

    if not id_part.startswith("rt-"):
        raise ValueError(f"Invalid routine line {line_num}: missing rt- prefix")

    item_id = id_part[3:]  # strip "rt-"

    # Extract title (before first metadata key) and metadata
    meta_match = re.search(
        r"\s*\|\s*(frequency:|status:|created_at:|last_completed:|streak:|goal:|notes:)\s*",
        rest,
    )
    if meta_match:
        title = rest[:meta_match.start()].strip()
        metadata = rest[meta_match.start():]
    else:
        title = rest.strip()
        metadata = ""

    if not title:
        raise ValueError(f"Empty title in routine at line {line_num}")

    # Parse metadata fields
    freq_raw = _parse_field(metadata, r"frequency:\s*(\S+)", "frequency", line_num, default="daily")
    frequency = RoutineFrequency(freq_raw) if freq_raw else RoutineFrequency.DAILY

    status_raw = _parse_field(metadata, r"status:\s*(\S+)", "status", line_num, default="active")
    status = status_raw if status_raw else "active"

    created_at_str = _parse_field(metadata, r"created_at:\s*(\S+)", "created_at", line_num, default=None)
    created_at = None
    if created_at_str:
        try:
            created_at = datetime.fromisoformat(created_at_str)
        except ValueError:
            raise ValueError(f"Invalid created_at in routine at line {line_num}: {created_at_str}")

    last_completed_str = _parse_field(metadata, r"last_completed:\s*(\S+)", "last_completed", line_num, default=None)
    last_completed = None
    if last_completed_str:
        try:
            last_completed = datetime.fromisoformat(last_completed_str)
        except ValueError:
            raise ValueError(f"Invalid last_completed in routine at line {line_num}: {last_completed_str}")

    streak_raw = _parse_field(metadata, r"streak:\s*(\S+)", "streak", line_num, default="0")
    streak = int(streak_raw) if streak_raw else 0

    goal_match = re.search(r"goal:\s*([^|]+)", metadata)
    linked_goal_title = goal_match.group(1).strip() if goal_match else ""

    notes_match = re.search(r"notes:\s*([^|]+)", metadata)
    notes = notes_match.group(1).strip() if notes_match else ""

    return Routine(
        id=item_id,
        title=title,
        frequency=frequency,
        status=status,
        created_at=created_at,
        last_completed=last_completed,
        streak=streak,
        linked_goal_title=linked_goal_title,
        notes=notes,
    )


def _parse_field(metadata: str, pattern: str, field_name: str, line_num: int, default: str | None) -> str | None:
    """Extract a single metadata field value, returning default if not found."""
    match = re.search(pattern, metadata)
    if not match:
        return default
    return match.group(1)


def _format_routine_line(rt: Routine) -> str:
    """Serialize Routine → line (only non-default fields emitted)."""
    parts = [f"rt-{rt.id} | {rt.title}"]

    if rt.frequency != RoutineFrequency.DAILY:
        parts.append(f"frequency: {rt.frequency.value}")
    if rt.status != "active":
        parts.append(f"status: {rt.status}")
    if rt.created_at is not None:
        parts.append(f"created_at: {rt.created_at.isoformat()}")
    if rt.last_completed is not None:
        parts.append(f"last_completed: {rt.last_completed.isoformat()}")
    if rt.streak != 0:
        parts.append(f"streak: {rt.streak}")
    if rt.linked_goal_title:
        parts.append(f"goal: {rt.linked_goal_title}")
    if rt.notes:
        parts.append(f"notes: {rt.notes}")

    return " | ".join(parts)


def save_routine(rt: Routine) -> None:
    """Append a new Routine to data/routines.md (append mode, create file if needed)."""
    line = _format_routine_line(rt)
    read_modify_write(
        ROUTINES_PATH,
        lambda cur: cur + line + "\n",
        backup=True,
    )


def update_routine(rt: Routine) -> None:
    """In-place rewrite of one routine by id."""
    raw_content = ROUTINES_PATH.read_text()
    lines = raw_content.splitlines()
    found = False
    new_lines: list[str] = []
    for line in lines:
        if line.startswith(f"rt-{rt.id} |"):
            new_lines.append(_format_routine_line(rt))
            found = True
        else:
            new_lines.append(line)

    if not found:
        raise ValueError(f"Routine not found: {rt.id}")

    content = "\n".join(new_lines) + "\n"
    read_modify_write(
        ROUTINES_PATH,
        lambda cur: content if cur == raw_content else cur,
        backup=True,
    )
