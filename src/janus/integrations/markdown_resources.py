"""Markdown resource loader for Janus — parses data/resources.md."""
import logging
import re
from pathlib import Path
from datetime import date, datetime

from janus.integrations.atomic_io import read_modify_write
from janus.models.resource import Resource, ResourceType

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
RESOURCES_PATH = PROJECT_ROOT / "data" / "resources.md"


def load_resources(
    path: Path | None = None,
    trace_id: str | None = None,
) -> list[Resource]:
    """Load all resources from data/resources.md.

    Returns [] if file is missing.
    """
    fp = path if path is not None else RESOURCES_PATH
    if not fp.exists():
        return []

    items: list[Resource] = []
    lines_scanned = 0

    with fp.open() as f:
        for line_num, line in enumerate(f, start=1):
            lines_scanned += 1
            line = line.strip()
            if not line.startswith("rs-"):
                continue
            item = _parse_resource_line(line, line_num)
            if item is not None:
                items.append(item)

    logger.debug("Loaded %d resources from %s", len(items), fp)
    return items


def _parse_resource_line(line: str, line_num: int) -> Resource:
    """Parse one line → Resource. Raises ValueError on bad metadata."""
    # Format: rs-<id> | <title> | type: <type> | capacity: <n> | used: <n> | ...
    parts = line.split(" | ", 1)
    id_part = parts[0]
    rest = parts[1] if len(parts) > 1 else ""

    if not id_part.startswith("rs-"):
        raise ValueError(f"Invalid resource line {line_num}: missing rs- prefix")

    item_id = id_part[3:]  # strip "rs-"

    # Extract title (before first metadata key) and metadata
    meta_match = re.search(
        r"\s*\|\s*(type:|capacity:|used:|unit:|available_from:|available_until:|goal:|notes:)\s*",
        rest,
    )
    if meta_match:
        title = rest[:meta_match.start()].strip()
        metadata = rest[meta_match.start():]
    else:
        title = rest.strip()
        metadata = ""

    if not title:
        raise ValueError(f"Empty title in resource at line {line_num}")

    # Parse metadata fields
    type_raw = _parse_field(metadata, r"type:\s*(\S+)", "type", line_num, default="other")
    resource_type = ResourceType(type_raw) if type_raw else ResourceType.OTHER

    capacity_raw = _parse_field(metadata, r"capacity:\s*(\S+)", "capacity", line_num, default="0")
    capacity = float(capacity_raw) if capacity_raw else 0.0

    used_raw = _parse_field(metadata, r"used:\s*(\S+)", "used", line_num, default="0")
    used = float(used_raw) if used_raw else 0.0

    unit_match = re.search(r"unit:\s*([^|]+)", metadata)
    unit = unit_match.group(1).strip() if unit_match else ""

    available_from_str = _parse_field(metadata, r"available_from:\s*(\S+)", "available_from", line_num, default=None)
    available_from = None
    if available_from_str:
        try:
            available_from = date.fromisoformat(available_from_str)
        except ValueError:
            raise ValueError(f"Invalid available_from in resource at line {line_num}: {available_from_str}")

    available_until_str = _parse_field(metadata, r"available_until:\s*(\S+)", "available_until", line_num, default=None)
    available_until = None
    if available_until_str:
        try:
            available_until = date.fromisoformat(available_until_str)
        except ValueError:
            raise ValueError(f"Invalid available_until in resource at line {line_num}: {available_until_str}")

    goal_match = re.search(r"goal:\s*([^|]+)", metadata)
    linked_goal_title = goal_match.group(1).strip() if goal_match else ""

    notes_match = re.search(r"notes:\s*([^|]+)", metadata)
    notes = notes_match.group(1).strip() if notes_match else ""

    return Resource(
        id=item_id,
        title=title,
        resource_type=resource_type,
        capacity=capacity,
        used=used,
        unit=unit,
        available_from=available_from,
        available_until=available_until,
        linked_goal_title=linked_goal_title,
        notes=notes,
    )


def _parse_field(metadata: str, pattern: str, field_name: str, line_num: int, default: str | None) -> str | None:
    """Extract a single metadata field value, returning default if not found."""
    match = re.search(pattern, metadata)
    if not match:
        return default
    return match.group(1)


def _format_resource_line(rs: Resource) -> str:
    """Serialize Resource → line (only non-default fields emitted)."""
    parts = [f"rs-{rs.id} | {rs.title}"]

    if rs.resource_type != ResourceType.OTHER:
        parts.append(f"type: {rs.resource_type.value}")
    if rs.capacity != 0.0:
        parts.append(f"capacity: {rs.capacity}")
    if rs.used != 0.0:
        parts.append(f"used: {rs.used}")
    if rs.unit:
        parts.append(f"unit: {rs.unit}")
    if rs.available_from is not None:
        parts.append(f"available_from: {rs.available_from.isoformat()}")
    if rs.available_until is not None:
        parts.append(f"available_until: {rs.available_until.isoformat()}")
    if rs.linked_goal_title:
        parts.append(f"goal: {rs.linked_goal_title}")
    if rs.notes:
        parts.append(f"notes: {rs.notes}")

    return " | ".join(parts)


def save_resource(rs: Resource) -> None:
    """Append a new Resource to data/resources.md (append mode, create file if needed)."""
    line = _format_resource_line(rs)
    read_modify_write(
        RESOURCES_PATH,
        lambda cur: cur + line + "\n",
        backup=True,
    )


def update_resource(rs: Resource) -> None:
    """In-place rewrite of one resource by id."""
    raw_content = RESOURCES_PATH.read_text()
    lines = raw_content.splitlines()
    found = False
    new_lines: list[str] = []
    for line in lines:
        if line.startswith(f"rs-{rs.id} |"):
            new_lines.append(_format_resource_line(rs))
            found = True
        else:
            new_lines.append(line)

    if not found:
        raise ValueError(f"Resource not found: {rs.id}")

    content = "\n".join(new_lines) + "\n"
    read_modify_write(
        RESOURCES_PATH,
        lambda cur: content if cur == raw_content else cur,
        backup=True,
    )
