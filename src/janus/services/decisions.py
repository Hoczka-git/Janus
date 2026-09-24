"""Decision service — structured access to ADR markdown records.

Canonical storage is markdown ADR files in docs/decisions/. This service
reads those files into Decision objects for linking and querying, and
provides write-back for status changes (``update_decision_status``),
decision creation (``create_decision``), and bidirectional linking
(``link_decision_to_goal``, ``link_finding_to_decision``).

Follows the existing Janus dataclass/service pattern (goals.py,
knowledge_pipeline.py).
"""
from __future__ import annotations

import re
import logging
from datetime import datetime
from pathlib import Path

from janus._log import emit
from janus.integrations.atomic_io import (
    atomic_write,
    compute_content_hash,
)
from janus.models.decision import Decision, VALID_DECISION_STATUSES

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DECISIONS_DIR = PROJECT_ROOT / "docs" / "decisions"

logger = logging.getLogger(__name__)


def load_decisions() -> list[Decision]:
    """Load all ADR markdown files from docs/decisions/ into Decision objects.

    Returns decisions sorted by adr_number. Files that do not match the
    ``NNN-*.md`` pattern are skipped. Malformed ADR files produce a Decision
    with empty fields (graceful degradation); the file is still included
    so the caller can handle it.
    """
    if not DECISIONS_DIR.exists():
        return []

    decisions: list[Decision] = []
    for md_path in sorted(DECISIONS_DIR.glob("*.md")):
        # Only process files matching the ADR naming convention NNN-*.md
        match = re.match(r"^(\d{3,})-", md_path.name)
        if not match:
            continue
        try:
            decision = _parse_adr(md_path)
            decisions.append(decision)
        except Exception as exc:
            logger.warning("Failed to parse ADR %s: %s", md_path, exc)
            # Graceful degradation: include a minimal Decision so the file
            # is not silently lost.
            decisions.append(Decision(
                adr_number=match.group(1),
                title=md_path.stem,
            ))

    decisions.sort(key=lambda d: d.adr_number)
    emit(logger, "source.decisions.loaded",
         trace_id=None, span_id="load_decisions",
         decisions_loaded=len(decisions),
         message=f"Loaded {len(decisions)} decisions")
    return decisions


def get_decision(adr_number: str) -> Decision:
    """Load a single Decision by ADR number.

    Raises ValueError if no ADR file matches the given number.
    """
    # Normalize: accept "1" or "001"
    for d in load_decisions():
        if d.adr_number == adr_number or d.adr_number.lstrip("0") == adr_number.lstrip("0"):
            return d
    raise ValueError(f"Decision not found: {adr_number!r}")


def list_decisions_for_goal(goal_title: str) -> list[Decision]:
    """Return all decisions that reference this goal (by title).

    Searches the ADR text for the goal title. Returns an empty list if
    no decisions reference the goal.
    """
    all_decisions = load_decisions()
    result = []
    for d in all_decisions:
        if goal_title in d.goal_titles:
            result.append(d)
            continue
        # Also search the full text as a fallback (goal_titles may be
        # implicitly mentioned in context/decision/consequences without
        # being explicitly listed in a structured field).
        full_text = " ".join(filter(None, [d.context, d.decision, d.consequences]))
        if goal_title in full_text:
            result.append(d)
    return result


def list_decisions_by_status(status: str) -> list[Decision]:
    """Return all decisions with a given status.

    Raises ValueError if status is not a valid status string.
    """
    if status not in VALID_DECISION_STATUSES:
        raise ValueError(
            f"Invalid status: {status!r}. "
            f"Allowed values: {', '.join(VALID_DECISION_STATUSES)}"
        )
    return [d for d in load_decisions() if d.status == status]


def update_decision_status(adr_number: str, status: str) -> Decision:
    """Update a decision's status and write back to the markdown file.

    Only the ``## Status`` or ``Status`` section is rewritten; the rest
    of the ADR file is preserved. Raises ValueError if the decision or
    status is invalid.
    """
    if status not in VALID_DECISION_STATUSES:
        raise ValueError(
            f"Invalid status: {status!r}. "
            f"Allowed values: {', '.join(VALID_DECISION_STATUSES)}"
        )
    decision = get_decision(adr_number)

    # Find the ADR file
    adr_path = _find_adr_path(decision.adr_number)
    if adr_path is None:
        raise ValueError(f"ADR file not found for decision {adr_number!r}")

    content = adr_path.read_text()
    updated = _replace_status_in_markdown(content, status)
    atomic_write(
        adr_path,
        updated,
        expected_hash=compute_content_hash(content),
        written_by="services.decisions.update_decision_status",
    )

    decision.status = status
    decision.updated_at = datetime.now().astimezone()

    emit(logger, "service.decision.mutated",
         trace_id=None, span_id="update_decision_status",
         adr_number=adr_number,
         old_status=None,
         new_status=status,
         message=f"Decision {adr_number} status updated to {status}")
    return decision


def link_decision_to_goal(adr_number: str, goal_title: str) -> Decision:
    """Add a bidirectional link: decision -> goal and goal -> decision.

    Updates the Decision's ADR file (appends goal reference via wikilink)
    and appends the ADR number to Goal.decision_numbers in goals.md.

    No-op if the link already exists on both sides.
    Raises ValueError if the decision or goal is not found.
    """
    decision = get_decision(adr_number)
    adr_path = _find_adr_path(decision.adr_number)
    if adr_path is None:
        raise ValueError(f"ADR file not found for decision {adr_number!r}")

    content = adr_path.read_text()

    # Update decision side: add [[Goal: title]] wikilink if not present
    goal_wikilink = f"[[Goal: {goal_title}]]"
    if goal_wikilink not in content:
        # Append to the Context section or at the end
        new_content = content.rstrip() + f"\n\nSee {goal_wikilink} for the goal this decision addresses.\n"
        atomic_write(
            adr_path,
            new_content,
            expected_hash=compute_content_hash(content),
            written_by="services.decisions.link_decision_to_goal",
        )

    # Update goal side: append adr_number to Goal.decision_numbers.
    # update_goal_fields already persists the change (it calls update_goal),
    # so there is no need to append again here.
    from janus.services.goals import update_goal_fields
    update_goal_fields(goal_title, add_decision_number=adr_number)

    emit(logger, "service.decision.mutated",
         trace_id=None, span_id="link_decision_to_goal",
         adr_number=adr_number, goal_title=goal_title,
         message=f"Linked decision {adr_number} to goal '{goal_title}'")
    return decision


def link_finding_to_decision(adr_number: str, artifact_title: str, finding_index: int) -> None:
    """Link a research artifact's finding to a decision (bidirectional).

    Delegates to the research_artifacts service for the artifact-side update
    and updates the decision's ADR file with an 'Informed by' entry.

    Idempotent: no-op if the link already exists.
    """
    decision = get_decision(adr_number)
    adr_path = _find_adr_path(decision.adr_number)
    if adr_path is None:
        raise ValueError(f"ADR file not found for decision {adr_number!r}")

    content = adr_path.read_text()
    content_before = content  # Save for conflict detection

    # Update decision side: add artifact title to Informed by section
    if "## Informed by" not in content:
        content += f"\n## Informed by\n\n- {artifact_title}\n"
    elif f"- {artifact_title}" not in content.split("## Informed by", 1)[1]:
        # Insert item into existing Informed by section (before next ## section)
        marker = "## Informed by"
        idx = content.index(marker)
        rest = content[idx:]
        # Find end of Informed by section: next "## " heading
        next_section = re.search(r"\n##\s", rest[len(marker):])
        if next_section:
            insert_pos = idx + len(marker) + next_section.start()
            content = content[:insert_pos] + f"\n- {artifact_title}\n" + content[insert_pos:]
        else:
            content = content.rstrip() + f"\n- {artifact_title}\n"
    atomic_write(
        adr_path,
        content,
        expected_hash=compute_content_hash(content_before),
        written_by="services.decisions.link_finding_to_decision",
    )

    # Update artifact side via research_artifacts service
    from janus.services.research_artifacts import link_finding_to_decision as _link_finding
    _link_finding(artifact_title, finding_index, adr_number)

    emit(logger, "service.decision.mutated",
         trace_id=None, span_id="link_finding_to_decision",
         adr_number=adr_number, artifact_title=artifact_title, finding_index=finding_index,
         message=f"Linked finding {finding_index} of '{artifact_title}' to decision {adr_number}")


def create_decision(decision: Decision) -> Path:
    """Create a new ADR markdown file from a Decision object.

    Generates a file at docs/decisions/<NNN>-<slug>.md with the standard
    ADR sections (Status, Context, Decision, Consequences, Informed by).
    The adr_number in the Decision object determines the filename prefix.

    Raises ValueError if a file with the same number already exists.
    Returns the path to the created file.
    """
    DECISIONS_DIR.mkdir(parents=True, exist_ok=True)
    adr_path = _find_adr_path(decision.adr_number)
    if adr_path is not None:
        raise ValueError(f"ADR already exists for number {decision.adr_number!r}")

    filename = f"{decision.adr_number.zfill(3)}-{_slugify(decision.title)}.md"
    adr_path = DECISIONS_DIR / filename

    adr_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"# ADR-{decision.adr_number}: {decision.title}", "", "## Status", "", decision.status, "", "## Context", "", decision.context or "", "", "## Decision", "", decision.decision or "", "", "## Consequences", "", decision.consequences or "", ""]

    if decision.finding_sources:
        lines.append("## Informed by")
        lines.append("")
        for src in decision.finding_sources:
            lines.append(f"- {src}")
        lines.append("")

    if decision.goal_titles:
        for gt in decision.goal_titles:
            lines.append(f"[[Goal: {gt}]]")
        lines.append("")

    content = "\n".join(lines)
    atomic_write(
        adr_path,
        content,
        expected_hash=None,  # new file
        written_by="services.decisions.create_decision",
    )
    decision.updated_at = datetime.now().astimezone()

    emit(logger, "service.decision.created",
         trace_id=None, span_id="create_decision",
         adr_number=decision.adr_number, title=decision.title,
         path=str(adr_path),
         message=f"Created ADR {adr_path.name}")
    return adr_path


def create_decision_via_ingest(body: str, *, title: str = "",
                               source: str = "cli",
                               evidence: dict | None = None) -> "IngestResult":
    """Construct a DECISION_CREATED ActivityRecord and route it through
    the canonical ADR-005 ingestion gate (``ingest_activities``).

    The ``body`` is the full ADR markdown (YAML frontmatter + body).
    Returns the :class:`IngestResult` from the ingestion gate.
    """
    from datetime import datetime, timezone
    from janus.services.activity_ingest import (
        ActivityRecord,
        ActivityType,
        ingest_activities,
    )
    record = ActivityRecord(
        type=ActivityType.DECISION_CREATED,
        source=source,
        timestamp=datetime.now(timezone.utc),
        task_title=title or _title_from_body(body),
        captured_text=body,
        evidence=evidence or {},
    )
    return ingest_activities([record])[0]


def _title_from_body(body: str) -> str:
    """Best-effort title extraction from ADR markdown frontmatter."""
    import re as _re
    m = _re.match(r"^---\s*\ntitle:\s*(.+)\s*$", body, _re.MULTILINE)
    if m:
        return m.group(1).strip()
    return "Untitled"


def _slugify(text: str) -> str:
    """Convert text to a URL/filename-safe slug (lowercase, hyphen-separated)."""
    slug = re.sub(r"[^\w\s-]", "", text.lower())
    slug = re.sub(r"[\s_]+", "-", slug.strip())
    slug = re.sub(r"-+", "-", slug)
    return slug or "untitled"


def _find_adr_path(adr_number: str) -> Path | None:
    """Find the ADR markdown file matching the given number."""
    if not DECISIONS_DIR.exists():
        return None
    # Normalize to zero-padded 3-digit prefix
    padded = adr_number.zfill(3)
    # Try exact match with padded prefix
    for path in DECISIONS_DIR.glob(f"{padded}-*.md"):
        return path
    # Try with the original number
    for path in DECISIONS_DIR.glob(f"{adr_number}-*.md"):
        return path
    return None


def _parse_adr(path: Path) -> Decision:
    """Parse a single ADR markdown file into a Decision object."""
    content = path.read_text()

    num_match = re.match(r"^(\d{3,})-", path.name)
    if not num_match:
        raise ValueError(f"File does not match ADR naming convention: {path.name}")
    adr_number = num_match.group(1)

    title = _extract_title(content, path.stem)
    status = _extract_status(content)
    context = _extract_section(content, "Context")
    decision_text = _extract_section(content, "Decision")
    consequences = _extract_section(content, "Consequences")
    goal_titles = _extract_goal_links(content)
    supersedes_adr = _extract_supersedes(content)
    finding_sources = _extract_informed_by(content)
    created_at, updated_at = _extract_dates(content)

    return Decision(
        adr_number=adr_number,
        title=title,
        status=status,
        context=context,
        decision=decision_text,
        consequences=consequences,
        goal_titles=goal_titles,
        finding_sources=finding_sources,
        supersedes_adr=supersedes_adr,
        created_at=created_at,
        updated_at=updated_at,
    )


def _extract_title(content: str, fallback: str) -> str:
    """Extract the decision title from the ADR markdown.

    The title is the first ``#`` heading (H1). Falls back to the filename stem.
    """
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip()
    return fallback


def _extract_status(content: str) -> str:
    """Extract the status from the ADR markdown.

    Looks for a ``## Status`` section or a ``Status:`` key-value line.
    Defaults to 'proposed' if not found.
    """
    # Try "## Status" section
    status_match = re.search(r"^#+\s*Status\s*$\s*\n+(.+)$", content, re.MULTILINE)
    if status_match:
        raw = status_match.group(1).strip().splitlines()[0].strip()
        return _normalize_status(raw)

    # Try "Status: <value>" key-value style (ADR-003 pattern)
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.lower().startswith("**status:**"):
            raw = stripped.split("**", 2)[-1].strip()
            return _normalize_status(raw)
        if stripped.lower().startswith("status:"):
            raw = stripped[7:].strip()
            return _normalize_status(raw)

    return "proposed"


def _normalize_status(raw: str) -> str:
    """Normalize a status string to one of the valid status values.

    Recognizes qualified status prose (e.g. ``Accepted with implementation
    caveats``, ``Accepted (on consensus)``) by matching the leading canonical
    keyword, so a status that is *accepted with caveats* is reported as the
    canonical ``accepted`` value rather than falling through to ``proposed``.
    The full qualifier text is preserved in the ADR's prose; the discrete
    ``Decision.status`` field remains one of
    :data:`VALID_DECISION_STATUSES`.
    """
    lower = raw.lower().strip().rstrip(".")
    if lower in VALID_DECISION_STATUSES:
        return lower
    # Map common variations
    aliases = {
        "accepted": "accepted",
        "proposed": "proposed",
        "deprecated": "deprecated",
        "superseded": "superseded",
        "rejected": "deprecated",
        "withdrawn": "deprecated",
    }
    if lower in aliases:
        return aliases[lower]
    # Match qualified status strings, e.g. "accepted with implementation
    # caveats", "accepted (on consensus)", "proposed (under review)".
    for canonical in VALID_DECISION_STATUSES:
        if lower.startswith(canonical):
            return canonical
    return "proposed"


def _extract_section(content: str, section_name: str) -> str:
    """Extract the text content of a markdown section (e.g. '## Context').

    Returns text up to the next section heading or end of file.
    """
    # Match ## SectionName or # SectionName
    pattern = re.compile(
        rf"^#+\s+{re.escape(section_name)}\s*$\s*\n+(.*?)(?=^#+\s|^\Z)",
        re.MULTILINE | re.DOTALL,
    )
    match = pattern.search(content)
    if match:
        return match.group(1).strip()
    return ""


def _extract_goal_links(content: str) -> list[str]:
    """Extract goal titles referenced as wikilinks in the ADR.

    Looks for [[Goal: Title]] or [Goal: Title] style references.
    """
    goal_titles: list[str] = []
    # Pattern: [[Goal: Title]] or [Goal: Title]
    pattern = re.compile(r"\[\[?Goal:\s*(.+?)\]\]?\s*")
    for match in pattern.finditer(content):
        title = match.group(1).strip()
        if title and title not in goal_titles:
            goal_titles.append(title)
    return goal_titles


def _extract_informed_by(content: str) -> list[str]:
    """Extract research artifact titles referenced in the ADR's Informed by section.

    Looks for a '## Informed by' section header, then collects list items
    (lines starting with '- '). Each item is a research artifact title.
    """
    findings: list[str] = []
    lines = content.splitlines()
    in_section = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("## ") and "informed by" in stripped.lower():
            in_section = True
            continue
        if in_section:
            # End of section: another ## heading (but not ## Informed by itself)
            if stripped.startswith("## ") and "informed by" not in stripped.lower():
                in_section = False
                continue
            if stripped.startswith("- "):
                item = stripped[2:].strip()
                if item and item not in findings:
                    findings.append(item)
    return findings


def _extract_supersedes(content: str) -> str | None:
    """Extract the ADR number that this decision supersedes.

    Looks for 'Supersedes: ADR-001' or 'Supersedes: 001'.
    """
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.lower().startswith("supersedes:"):
            raw = stripped.split(":", 1)[1].strip()
            # Extract the ADR number (may be "ADR-001" or "001")
            num_match = re.search(r"(\d+)", raw)
            if num_match:
                return num_match.group(1)
            return raw if raw else None
    return None


def _extract_dates(content: str) -> tuple[datetime | None, datetime | None]:
    """Extract created_at and updated_at from ADR metadata.

    Looks for 'Date:' or 'Created:' / 'Updated:' frontmatter or inline.
    """
    created_at = None
    updated_at = None

    for line in content.splitlines():
        stripped = line.strip()
        lower = stripped.lower()

        if lower.startswith("date:"):
            raw = stripped.split(":", 1)[1].strip()
            dt = _try_parse_date(raw)
            if dt and created_at is None:
                created_at = dt
        elif lower.startswith("created:"):
            raw = stripped.split(":", 1)[1].strip()
            dt = _try_parse_date(raw)
            if dt:
                created_at = dt
        elif lower.startswith("updated:"):
            raw = stripped.split(":", 1)[1].strip()
            dt = _try_parse_date(raw)
            if dt:
                updated_at = dt

    return created_at, updated_at


def _try_parse_date(raw: str) -> datetime | None:
    """Attempt to parse an ISO date string into a timezone-aware datetime."""
    try:
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt = dt.astimezone()
        return dt
    except ValueError:
        return None


def _replace_status_in_markdown(content: str, new_status: str) -> str:
    """Replace the status in ADR markdown content.

    Handles both the '## Status' section and 'Status: <value>' key-value format.
    """
    # Try '## Status' section replacement
    status_pattern = re.compile(
        r"^#+\s*Status\s*$\s*\n+(.+)$",
        re.MULTILINE,
    )
    match = status_pattern.search(content)
    if match:
        # Replace the first non-empty line after the Status header
        start = match.start(1)
        # Find end of the status value (first newline + non-empty content)
        rest = content[start:]
        lines = rest.split("\n", 1)
        new_rest = new_status + ("\n" + lines[1] if len(lines) > 1 else "")
        return content[:start] + new_rest

    # Try '**Status:**' key-value replacement
    kv_pattern = re.compile(r"(\*\*Status:\*\*\s*)([^\n]+)", re.IGNORECASE)
    match = kv_pattern.search(content)
    if match:
        return kv_pattern.sub(lambda m: m.group(1) + new_status, content)

    # Try 'Status:' key-value replacement
    kv_pattern2 = re.compile(r"(Status:\s*)([^\n]+)", re.IGNORECASE)
    match = kv_pattern2.search(content)
    if match:
        return kv_pattern2.sub(lambda m: m.group(1) + new_status, content)

    # If no status field found, append one at the end
    return content + f"\n## Status\n\n{new_status}\n"
