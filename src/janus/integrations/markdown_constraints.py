"""Markdown constraint loader for Janus — parses data/constraints.md."""
import logging
import re
from pathlib import Path
from datetime import date, datetime

from janus.integrations.atomic_io import read_modify_write
from janus.models.constraint import Constraint, ConstraintType

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
CONSTRAINTS_PATH = PROJECT_ROOT / "data" / "constraints.md"


def load_constraints(
    path: Path | None = None,
    trace_id: str | None = None,
) -> list[Constraint]:
    """Load all constraints from data/constraints.md.

    Returns [] if file is missing.
    """
    fp = path if path is not None else CONSTRAINTS_PATH
    if not fp.exists():
        return []

    items: list[Constraint] = []
    lines_scanned = 0

    with fp.open() as f:
        for line_num, line in enumerate(f, start=1):
            lines_scanned += 1
            line = line.strip()
            if not line.startswith("ct-"):
                continue
            item = _parse_constraint_line(line, line_num)
            if item is not None:
                items.append(item)

    logger.debug("Loaded %d constraints from %s", len(items), fp)
    return items


def _parse_constraint_line(line: str, line_num: int) -> Constraint:
    """Parse one line → Constraint. Raises ValueError on bad metadata."""
    # Format: ct-<id> | <title> | type: <type> | severity: <sev> | ...
    parts = line.split(" | ", 1)
    id_part = parts[0]
    rest = parts[1] if len(parts) > 1 else ""

    if not id_part.startswith("ct-"):
        raise ValueError(f"Invalid constraint line {line_num}: missing ct- prefix")

    item_id = id_part[3:]  # strip "ct-"

    # Extract title (before first metadata key) and metadata
    meta_match = re.search(
        r"\s*\|\s*(type:|severity:|active:|created_at:|expires_at:|goal:|notes:)\s*",
        rest,
    )
    if meta_match:
        title = rest[:meta_match.start()].strip()
        metadata = rest[meta_match.start():]
    else:
        title = rest.strip()
        metadata = ""

    if not title:
        raise ValueError(f"Empty title in constraint at line {line_num}")

    # Parse metadata fields
    type_raw = _parse_field(metadata, r"type:\s*(\S+)", "type", line_num, default="other")
    constraint_type = ConstraintType(type_raw) if type_raw else ConstraintType.OTHER

    severity_raw = _parse_field(metadata, r"severity:\s*(\S+)", "severity", line_num, default="medium")
    severity = severity_raw if severity_raw else "medium"

    active_raw = _parse_field(metadata, r"active:\s*(\S+)", "active", line_num, default="true")
    active = active_raw.lower() != "false" if active_raw else True

    created_at_str = _parse_field(metadata, r"created_at:\s*(\S+)", "created_at", line_num, default=None)
    created_at = None
    if created_at_str:
        try:
            created_at = datetime.fromisoformat(created_at_str)
        except ValueError:
            raise ValueError(f"Invalid created_at in constraint at line {line_num}: {created_at_str}")

    expires_at_str = _parse_field(metadata, r"expires_at:\s*(\S+)", "expires_at", line_num, default=None)
    expires_at = None
    if expires_at_str:
        try:
            expires_at = date.fromisoformat(expires_at_str)
        except ValueError:
            raise ValueError(f"Invalid expires_at in constraint at line {line_num}: {expires_at_str}")

    goal_match = re.search(r"goal:\s*([^|]+)", metadata)
    linked_goal_title = goal_match.group(1).strip() if goal_match else ""

    notes_match = re.search(r"notes:\s*([^|]+)", metadata)
    notes = notes_match.group(1).strip() if notes_match else ""

    return Constraint(
        id=item_id,
        title=title,
        constraint_type=constraint_type,
        severity=severity,
        active=active,
        created_at=created_at,
        expires_at=expires_at,
        linked_goal_title=linked_goal_title,
        notes=notes,
    )


def _parse_field(metadata: str, pattern: str, field_name: str, line_num: int, default: str | None) -> str | None:
    """Extract a single metadata field value, returning default if not found."""
    match = re.search(pattern, metadata)
    if not match:
        return default
    return match.group(1)


def _format_constraint_line(ct: Constraint) -> str:
    """Serialize Constraint → line (only non-default fields emitted)."""
    parts = [f"ct-{ct.id} | {ct.title}"]

    if ct.constraint_type != ConstraintType.OTHER:
        parts.append(f"type: {ct.constraint_type.value}")
    if ct.severity != "medium":
        parts.append(f"severity: {ct.severity}")
    if not ct.active:
        parts.append(f"active: false")
    if ct.created_at is not None:
        parts.append(f"created_at: {ct.created_at.isoformat()}")
    if ct.expires_at is not None:
        parts.append(f"expires_at: {ct.expires_at.isoformat()}")
    if ct.linked_goal_title:
        parts.append(f"goal: {ct.linked_goal_title}")
    if ct.notes:
        parts.append(f"notes: {ct.notes}")

    return " | ".join(parts)


def save_constraint(ct: Constraint) -> None:
    """Append a new Constraint to data/constraints.md (append mode, create file if needed)."""
    line = _format_constraint_line(ct)
    read_modify_write(
        CONSTRAINTS_PATH,
        lambda cur: cur + line + "\n",
        backup=True,
    )


def update_constraint(ct: Constraint) -> None:
    """In-place rewrite of one constraint by id."""
    raw_content = CONSTRAINTS_PATH.read_text()
    lines = raw_content.splitlines()
    found = False
    new_lines: list[str] = []
    for line in lines:
        if line.startswith(f"ct-{ct.id} |"):
            new_lines.append(_format_constraint_line(ct))
            found = True
        else:
            new_lines.append(line)

    if not found:
        raise ValueError(f"Constraint not found: {ct.id}")

    content = "\n".join(new_lines) + "\n"
    read_modify_write(
        CONSTRAINTS_PATH,
        lambda cur: content if cur == raw_content else cur,
        backup=True,
    )
