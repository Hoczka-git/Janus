"""Markdown inbox loader for Janus — parses data/inbox.md."""

import logging
import re
from pathlib import Path
from datetime import datetime

from janus.models.inbox import InboxItem, CAPTURE_SOURCES, TRIAGE_STATES

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
INBOX_PATH = PROJECT_ROOT / "data" / "inbox.md"


def load_inbox_items(
    path: Path | None = None,
    trace_id: str | None = None,
) -> list[InboxItem]:
    """Load all inbox items from data/inbox.md.

    Returns [] if file is missing (inbox starts empty; file created on first capture).
    """
    inbox_path = path if path is not None else INBOX_PATH
    if not inbox_path.exists():
        return []

    items: list[InboxItem] = []
    lines_scanned = 0

    with inbox_path.open() as f:
        for line_num, line in enumerate(f, start=1):
            lines_scanned += 1
            line = line.strip()
            if not line.startswith("ix-"):
                continue
            item = _parse_inbox_line(line, line_num)
            if item is not None:
                items.append(item)

    logger.debug("Loaded %d inbox items from %s", len(items), inbox_path)
    return items


def _parse_inbox_line(line: str, line_num: int) -> InboxItem:
    """Parse one line → InboxItem. Raises ValueError on bad metadata."""
    # Format: ix-<id> | <captured_text> | source: <source> | captured_at: <iso> | ...
    parts = line.split(" | ", 1)
    id_part = parts[0]
    rest = parts[1] if len(parts) > 1 else ""

    if not id_part.startswith("ix-"):
        raise ValueError(f"Invalid inbox line {line_num}: missing ix- prefix")

    item_id = id_part[3:]  # strip "ix-"

    # Extract captured_text (everything before first metadata key) and metadata
    metadata = rest
    captured_text = rest

    # Find the first metadata key pattern and split there
    meta_match = re.search(r"\b(source:|captured_at:|context:|state:|triage_note:|triage_at:|goal:|research:)\s*", rest)
    if meta_match:
        split_pos = meta_match.start()
        captured_text = rest[:split_pos].strip()
        metadata = rest[split_pos:]

    # Parse metadata fields
    source_raw = _parse_field(metadata, r"source:\s*(\S+)", "source", line_num, default="manual")
    source = source_raw if source_raw else "manual"
    captured_at_str = _parse_field(metadata, r"captured_at:\s*(\S+)", "captured_at", line_num, default=None)
    captured_at = None
    if captured_at_str:
        try:
            captured_at = datetime.fromisoformat(captured_at_str)
        except ValueError:
            raise ValueError(f"Invalid captured_at in inbox item at line {line_num}: {captured_at_str}")

    context = _parse_field(metadata, r"context:\s*(.+?)(?=\s*\|\s*(?:source:|captured_at:|context:|state:|triage_note:|triage_at:|goal:|research:)|$)", "context", line_num, default="")
    # Simpler: context is everything between "context: " and the next "|" that starts a known key
    context_match = re.search(r"context:\s*([^|]+)", metadata)
    context = context_match.group(1).strip() if context_match else ""

    triage_state_raw = _parse_field(metadata, r"state:\s*(\S+)", "state", line_num, default="pending")
    triage_state = triage_state_raw if triage_state_raw else "pending"
    triage_note_match = re.search(r"triage_note:\s*([^|]+)", metadata)
    triage_note = triage_note_match.group(1).strip() if triage_note_match else ""

    triage_at_str = _parse_field(metadata, r"triage_at:\s*(\S+)", "triage_at", line_num, default=None)
    triage_at = None
    if triage_at_str:
        try:
            triage_at = datetime.fromisoformat(triage_at_str)
        except ValueError:
            raise ValueError(f"Invalid triage_at in inbox item at line {line_num}: {triage_at_str}")

    goal_match = re.search(r"goal:\s*([^|]+)", metadata)
    linked_goal_title = goal_match.group(1).strip() if goal_match else ""

    research_match = re.search(r"research:\s*([^|]+)", metadata)
    linked_research_title = research_match.group(1).strip() if research_match else ""

    return InboxItem(
        id=item_id,
        captured_text=captured_text,
        source=source,
        captured_at=captured_at,
        context=context,
        triage_state=triage_state,
        triage_note=triage_note,
        triage_at=triage_at,
        linked_goal_title=linked_goal_title,
        linked_research_title=linked_research_title,
    )


def _parse_field(metadata: str, pattern: str, field_name: str, line_num: int, default: str | None) -> str | None:
    """Extract a single metadata field value, returning default if not found."""
    match = re.search(pattern, metadata)
    if not match:
        return default
    return match.group(1)


def _format_inbox_line(item: InboxItem) -> str:
    """Serialize InboxItem → line (only non-default fields emitted)."""
    parts = [f"ix-{item.id} | {item.captured_text}"]

    if item.source != "manual":
        parts.append(f"source: {item.source}")
    if item.captured_at is not None:
        parts.append(f"captured_at: {item.captured_at.isoformat()}")
    if item.context:
        parts.append(f"context: {item.context}")
    if item.triage_state != "pending":
        parts.append(f"state: {item.triage_state}")
    if item.triage_note:
        parts.append(f"triage_note: {item.triage_note}")
    if item.triage_at is not None:
        parts.append(f"triage_at: {item.triage_at.isoformat()}")
    if item.linked_goal_title:
        parts.append(f"goal: {item.linked_goal_title}")
    if item.linked_research_title:
        parts.append(f"research: {item.linked_research_title}")

    return " | ".join(parts)


def save_inbox_item(item: InboxItem) -> None:
    """Append a new InboxItem to data/inbox.md (append mode, create file if needed)."""
    line = _format_inbox_line(item)
    with INBOX_PATH.open("a") as f:
        f.write(line + "\n")


def update_inbox_item(item: InboxItem) -> None:
    """In-place rewrite of one inbox item by id."""
    lines = INBOX_PATH.read_text().splitlines()
    found = False
    new_lines: list[str] = []
    for line in lines:
        if line.startswith(f"ix-{item.id} |"):
            new_lines.append(_format_inbox_line(item))
            found = True
        else:
            new_lines.append(line)

    if not found:
        raise ValueError(f"Inbox item not found: {item.id}")

    INBOX_PATH.write_text("\n".join(new_lines) + "\n")
