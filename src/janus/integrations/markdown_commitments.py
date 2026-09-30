"""Markdown commitment loader for Janus — parses data/commitments.md."""
import logging
import re
from pathlib import Path
from datetime import date, datetime

from janus.integrations.atomic_io import read_modify_write
from janus.models.commitment import Commitment, CommitmentStatus

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
COMMITMENTS_PATH = PROJECT_ROOT / "data" / "commitments.md"


def load_commitments(
    path: Path | None = None,
    trace_id: str | None = None,
) -> list[Commitment]:
    """Load all commitments from data/commitments.md.

    Returns [] if file is missing.
    """
    fp = path if path is not None else COMMITMENTS_PATH
    if not fp.exists():
        return []

    items: list[Commitment] = []
    lines_scanned = 0

    with fp.open() as f:
        for line_num, line in enumerate(f, start=1):
            lines_scanned += 1
            line = line.strip()
            if not line.startswith("cm-"):
                continue
            item = _parse_commitment_line(line, line_num)
            if item is not None:
                items.append(item)

    logger.debug("Loaded %d commitments from %s", len(items), fp)
    return items


def _parse_commitment_line(line: str, line_num: int) -> Commitment:
    """Parse one line → Commitment. Raises ValueError on bad metadata."""
    # Format: cm-<id> | <title> | status: <status> | due: <iso> | ...
    parts = line.split(" | ", 1)
    id_part = parts[0]
    rest = parts[1] if len(parts) > 1 else ""

    if not id_part.startswith("cm-"):
        raise ValueError(f"Invalid commitment line {line_num}: missing cm- prefix")

    item_id = id_part[3:]  # strip "cm-"

    # Extract title (before first metadata key) and metadata
    meta_match = re.search(
        r"\s*\|\s*(status:|due:|created_at:|completed_at:|goal:|notes:)\s*",
        rest,
    )
    if meta_match:
        title = rest[:meta_match.start()].strip()
        metadata = rest[meta_match.start():]
    else:
        title = rest.strip()
        metadata = ""

    if not title:
        raise ValueError(f"Empty title in commitment at line {line_num}")

    # Parse metadata fields
    status_raw = _parse_field(metadata, r"status:\s*(\S+)", "status", line_num, default="active")
    status = status_raw if status_raw else "active"

    due_match = re.search(r"due:\s*(\S+)", metadata)
    due_date = None
    if due_match:
        try:
            due_date = date.fromisoformat(due_match.group(1))
        except ValueError:
            raise ValueError(f"Invalid due date in commitment at line {line_num}: {due_match.group(1)}")

    created_at_str = _parse_field(metadata, r"created_at:\s*(\S+)", "created_at", line_num, default=None)
    created_at = None
    if created_at_str:
        try:
            created_at = datetime.fromisoformat(created_at_str)
        except ValueError:
            raise ValueError(f"Invalid created_at in commitment at line {line_num}: {created_at_str}")

    completed_at_str = _parse_field(metadata, r"completed_at:\s*(\S+)", "completed_at", line_num, default=None)
    completed_at = None
    if completed_at_str:
        try:
            completed_at = datetime.fromisoformat(completed_at_str)
        except ValueError:
            raise ValueError(f"Invalid completed_at in commitment at line {line_num}: {completed_at_str}")

    goal_match = re.search(r"goal:\s*([^|]+)", metadata)
    linked_goal_title = goal_match.group(1).strip() if goal_match else ""

    notes_match = re.search(r"notes:\s*([^|]+)", metadata)
    notes = notes_match.group(1).strip() if notes_match else ""

    return Commitment(
        id=item_id,
        title=title,
        status=CommitmentStatus(status),
        due_date=due_date,
        created_at=created_at,
        completed_at=completed_at,
        linked_goal_title=linked_goal_title,
        notes=notes,
    )


def _parse_field(metadata: str, pattern: str, field_name: str, line_num: int, default: str | None) -> str | None:
    """Extract a single metadata field value, returning default if not found."""
    match = re.search(pattern, metadata)
    if not match:
        return default
    return match.group(1)


def _format_commitment_line(cm: Commitment) -> str:
    """Serialize Commitment → line (only non-default fields emitted)."""
    parts = [f"cm-{cm.id} | {cm.title}"]

    if cm.status != CommitmentStatus.ACTIVE:
        parts.append(f"status: {cm.status.value}")
    if cm.due_date is not None:
        parts.append(f"due: {cm.due_date.isoformat()}")
    if cm.created_at is not None:
        parts.append(f"created_at: {cm.created_at.isoformat()}")
    if cm.completed_at is not None:
        parts.append(f"completed_at: {cm.completed_at.isoformat()}")
    if cm.linked_goal_title:
        parts.append(f"goal: {cm.linked_goal_title}")
    if cm.notes:
        parts.append(f"notes: {cm.notes}")

    return " | ".join(parts)


def save_commitment(cm: Commitment) -> None:
    """Append a new Commitment to data/commitments.md (append mode, create file if needed)."""
    line = _format_commitment_line(cm)
    read_modify_write(
        COMMITMENTS_PATH,
        lambda cur: cur + line + "\n",
        backup=True,
    )


def update_commitment(cm: Commitment) -> None:
    """In-place rewrite of one commitment by id."""
    raw_content = COMMITMENTS_PATH.read_text()
    lines = raw_content.splitlines()
    found = False
    new_lines: list[str] = []
    for line in lines:
        if line.startswith(f"cm-{cm.id} |"):
            new_lines.append(_format_commitment_line(cm))
            found = True
        else:
            new_lines.append(line)

    if not found:
        raise ValueError(f"Commitment not found: {cm.id}")

    content = "\n".join(new_lines) + "\n"
    read_modify_write(
        COMMITMENTS_PATH,
        lambda cur: content if cur == raw_content else cur,
        backup=True,
    )
