"""Markdown preference loader for Janus — parses data/preferences.md."""
import logging
import re
from pathlib import Path
from datetime import date, datetime

from janus.integrations.atomic_io import read_modify_write
from janus.models.preference import Preference, PreferenceCategory

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
PREFERENCES_PATH = PROJECT_ROOT / "data" / "preferences.md"


def load_preferences(
    path: Path | None = None,
    trace_id: str | None = None,
) -> list[Preference]:
    """Load all preferences from data/preferences.md.

    Returns [] if file is missing.
    """
    fp = path if path is not None else PREFERENCES_PATH
    if not fp.exists():
        return []

    items: list[Preference] = []
    lines_scanned = 0

    with fp.open() as f:
        for line_num, line in enumerate(f, start=1):
            lines_scanned += 1
            line = line.strip()
            if not line.startswith("pf-"):
                continue
            item = _parse_preference_line(line, line_num)
            if item is not None:
                items.append(item)

    logger.debug("Loaded %d preferences from %s", len(items), fp)
    return items


def _parse_preference_line(line: str, line_num: int) -> Preference:
    """Parse one line → Preference. Raises ValueError on bad metadata."""
    # Format: pf-<id> | <title> | category: <cat> | value: <val> | ...
    parts = line.split(" | ", 1)
    id_part = parts[0]
    rest = parts[1] if len(parts) > 1 else ""

    if not id_part.startswith("pf-"):
        raise ValueError(f"Invalid preference line {line_num}: missing pf- prefix")

    item_id = id_part[3:]  # strip "pf-"

    # Extract title (before first metadata key) and metadata
    meta_match = re.search(
        r"\s*\|\s*(category:|value:|priority:|active:|created_at:|notes:)\s*",
        rest,
    )
    if meta_match:
        title = rest[:meta_match.start()].strip()
        metadata = rest[meta_match.start():]
    else:
        title = rest.strip()
        metadata = ""

    if not title:
        raise ValueError(f"Empty title in preference at line {line_num}")

    # Parse metadata fields
    cat_raw = _parse_field(metadata, r"category:\s*(\S+)", "category", line_num, default="other")
    category = PreferenceCategory(cat_raw) if cat_raw else PreferenceCategory.OTHER

    value_match = re.search(r"value:\s*([^|]+)", metadata)
    value = value_match.group(1).strip() if value_match else ""

    priority_raw = _parse_field(metadata, r"priority:\s*(\S+)", "priority", line_num, default="3")
    priority = int(priority_raw) if priority_raw else 3

    active_raw = _parse_field(metadata, r"active:\s*(\S+)", "active", line_num, default="true")
    active = active_raw.lower() != "false" if active_raw else True

    created_at_str = _parse_field(metadata, r"created_at:\s*(\S+)", "created_at", line_num, default=None)
    created_at = None
    if created_at_str:
        try:
            created_at = datetime.fromisoformat(created_at_str)
        except ValueError:
            raise ValueError(f"Invalid created_at in preference at line {line_num}: {created_at_str}")

    notes_match = re.search(r"notes:\s*([^|]+)", metadata)
    notes = notes_match.group(1).strip() if notes_match else ""

    return Preference(
        id=item_id,
        title=title,
        category=category,
        value=value,
        priority=priority,
        active=active,
        created_at=created_at,
        notes=notes,
    )


def _parse_field(metadata: str, pattern: str, field_name: str, line_num: int, default: str | None) -> str | None:
    """Extract a single metadata field value, returning default if not found."""
    match = re.search(pattern, metadata)
    if not match:
        return default
    return match.group(1)


def _format_preference_line(pf: Preference) -> str:
    """Serialize Preference → line (only non-default fields emitted)."""
    parts = [f"pf-{pf.id} | {pf.title}"]

    if pf.category != PreferenceCategory.OTHER:
        parts.append(f"category: {pf.category.value}")
    if pf.value:
        parts.append(f"value: {pf.value}")
    if pf.priority != 3:
        parts.append(f"priority: {pf.priority}")
    if not pf.active:
        parts.append(f"active: false")
    if pf.created_at is not None:
        parts.append(f"created_at: {pf.created_at.isoformat()}")
    if pf.notes:
        parts.append(f"notes: {pf.notes}")

    return " | ".join(parts)


def save_preference(pf: Preference) -> None:
    """Append a new Preference to data/preferences.md (append mode, create file if needed)."""
    line = _format_preference_line(pf)
    read_modify_write(
        PREFERENCES_PATH,
        lambda cur: cur + line + "\n",
        backup=True,
    )


def update_preference(pf: Preference) -> None:
    """In-place rewrite of one preference by id."""
    raw_content = PREFERENCES_PATH.read_text()
    lines = raw_content.splitlines()
    found = False
    new_lines: list[str] = []
    for line in lines:
        if line.startswith(f"pf-{pf.id} |"):
            new_lines.append(_format_preference_line(pf))
            found = True
        else:
            new_lines.append(line)

    if not found:
        raise ValueError(f"Preference not found: {pf.id}")

    content = "\n".join(new_lines) + "\n"
    read_modify_write(
        PREFERENCES_PATH,
        lambda cur: content if cur == raw_content else cur,
        backup=True,
    )
