"""Markdown research artifact persistence for Janus.

Loads, saves, and updates research artifacts from data/research/<slug>.md.
Follows the existing markdown-only persistence pattern (markdown_goals.py,
markdown_followups.py).

Each artifact is stored as a single markdown file with YAML frontmatter
for metadata and structured sections for findings.
"""
import logging
import re
from datetime import datetime
from pathlib import Path

from janus._log import emit
from janus.integrations.data_protection import protected_write, compute_content_hash
from janus.models.research_artifact import (
    ARTIFACT_TYPES,
    CONFIDENCE_LEVELS,
    SOURCE_TYPES,
    Finding,
    ResearchArtifact,
    Source,
)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
RESEARCH_DIR = PROJECT_ROOT / "data" / "research"

logger = logging.getLogger(__name__)

# Frontmatter: opens with 3+ dashes on its own line, closes with 3+ dashes.
# Matches either at start-of-body or after a newline (Kanban may prepend
# metadata lines like ``integration_required: false`` before the fence).
_FRONTMATTER_RE = re.compile(
    r"(?:^|\n)-{3,}\s*\n(.*?)(\n-{3,}\s*(?:\n|$))", re.DOTALL
)


def load_artifact(slug: str) -> ResearchArtifact:
    """Load a single research artifact by its slug (filename stem without .md).

    Raises ValueError if no matching file exists.
    """
    path = _find_artifact_path(slug)
    if path is None:
        raise ValueError(f"Research artifact not found: {slug!r}")
    return _parse_artifact(path)


def load_all_artifacts() -> list[ResearchArtifact]:
    """Load all research artifacts from data/research/.

    Returns [] if the directory or files are missing.
    Files that fail to parse are logged and skipped (graceful degradation).
    """
    if not RESEARCH_DIR.exists():
        return []

    artifacts: list[ResearchArtifact] = []
    for md_path in sorted(RESEARCH_DIR.glob("*.md")):
        try:
            artifacts.append(_parse_artifact(md_path))
        except Exception as exc:
            logger.warning("Failed to parse research artifact %s: %s", md_path, exc)
    return artifacts


def save_artifact(artifact: ResearchArtifact) -> Path:
    """Persist a new research artifact to data/research/<slug>.md.

    The slug is derived from the artifact title via _slugify().
    Raises ValueError if a file with the same slug already exists.
    """
    RESEARCH_DIR.mkdir(parents=True, exist_ok=True)
    slug = _slugify(artifact.title)
    path = RESEARCH_DIR / f"{slug}.md"
    if path.exists():
        raise ValueError(f"Research artifact already exists at slug {slug!r}")
    content = _serialize_artifact(artifact)
    protected_write(
        path,
        content,
        expected_hash=None,  # new file, no conflict possible
        written_by="markdown_research.save_artifact",
    )
    emit(logger, "source.research.artifact_saved",
         trace_id=None, span_id="save_artifact",
         slug=slug, title=artifact.title,
         message=f"Saved research artifact '{slug}'")
    return path


def update_artifact(artifact: ResearchArtifact, slug: str | None = None) -> Path:
    """Update an existing research artifact in place.

    If slug is not provided, it is derived from the artifact title.
    Raises ValueError if the file does not exist.
    """
    if slug is None:
        slug = _slugify(artifact.title)
    path = _find_artifact_path(slug)
    if path is None:
        raise ValueError(f"Research artifact not found: {slug!r}")
    content = _serialize_artifact(artifact)
    protected_write(
        path,
        content,
        expected_hash=compute_content_hash(path.read_text(encoding="utf-8")) if path.exists() else None,
        written_by="markdown_research.update_artifact",
    )
    emit(logger, "source.research.artifact_updated",
         slug=slug, title=artifact.title,
         message=f"Updated research artifact '{slug}'")
    return path


def _find_artifact_path(slug: str) -> Path | None:
    """Find a research artifact file by slug (stem match)."""
    if not RESEARCH_DIR.exists():
        return None
    # Try exact match first
    direct = RESEARCH_DIR / f"{slug}.md"
    if direct.exists():
        return direct
    # Try prefix match (slug may have been generated differently)
    for path in RESEARCH_DIR.glob("*.md"):
        if path.stem == slug:
            return path
    return None


def _slugify(text: str) -> str:
    """Convert text to a slug suitable for a filename.

    Lowercase, alphanumeric + hyphens, deduplicated hyphens.
    """
    slug = text.lower()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_]+", "-", slug.strip())
    slug = re.sub(r"-+", "-", slug)
    slug = slug.strip("-")
    return slug or "untitled"


def _parse_artifact_content(content: str) -> ResearchArtifact:
    """Parse research artifact markdown text into a ResearchArtifact object.

    Accepts the full markdown content (frontmatter + body) and returns
    the structured in-memory model.  Used by both ``_parse_artifact``
    (for file loading) and the Hermes→Janus ingestion path where the
    body arrives as a raw string rather than a file on disk.
    """
    frontmatter, body = _split_frontmatter(content)

    title = frontmatter.get("title", "")
    artifact_type = frontmatter.get("artifact_type", "report")
    target = frontmatter.get("target", "")
    version = int(frontmatter.get("version", 1))
    linked_goal_titles = list(frontmatter.get("linked_goal_titles", []) or [])
    decision_numbers = list(frontmatter.get("decision_numbers", []) or [])
    created_at = _parse_datetime(frontmatter.get("created_at") or "")
    updated_at = _parse_datetime(frontmatter.get("updated_at") or "")
    summary = _extract_section(body, "Summary")
    conclusions = _extract_section(body, "Conclusions")
    findings = _extract_findings(body)

    return ResearchArtifact(
        title=title,
        artifact_type=artifact_type,
        target=target,
        summary=summary,
        conclusions=conclusions,
        findings=findings,
        version=version,
        created_at=created_at,
        updated_at=updated_at,
        linked_goal_titles=linked_goal_titles,
        decision_numbers=decision_numbers,
    )


def _parse_artifact(path: Path) -> ResearchArtifact:
    """Parse a research artifact markdown file into a ResearchArtifact object."""
    content = path.read_text()
    return _parse_artifact_content(content)


def _serialize_artifact(artifact: ResearchArtifact) -> str:
    """Serialize a ResearchArtifact to markdown with frontmatter + sections."""
    lines: list[str] = []
    lines.append("---")
    lines.append(f"title: {artifact.title}")
    lines.append(f"artifact_type: {artifact.artifact_type}")
    if artifact.target:
        lines.append(f"target: {artifact.target}")
    lines.append(f"version: {artifact.version}")
    if artifact.created_at:
        lines.append(f"created_at: {_format_datetime(artifact.created_at)}")
    if artifact.updated_at:
        lines.append(f"updated_at: {_format_datetime(artifact.updated_at)}")
    if artifact.linked_goal_titles:
        lines.append("linked_goal_titles:")
        for gt in artifact.linked_goal_titles:
            lines.append(f'  - "{gt}"')
    if artifact.decision_numbers:
        lines.append("decision_numbers:")
        for dn in artifact.decision_numbers:
            lines.append(f'  - "{dn}"')
    lines.append("---")
    lines.append("")

    if artifact.summary:
        lines.append("# Summary")
        lines.append("")
        lines.append(artifact.summary)
        lines.append("")

    if artifact.conclusions:
        lines.append("# Conclusions")
        lines.append("")
        lines.append(artifact.conclusions)
        lines.append("")

    if artifact.findings:
        lines.append("# Findings")
        lines.append("")
        for i, finding in enumerate(artifact.findings):
            lines.append(f"## Finding {i + 1}")
            lines.append("")
            lines.append(f"**Statement:** {finding.statement}")
            if finding.topic:
                lines.append(f"**Topic:** {finding.topic}")
            lines.append(f"**Confidence:** {finding.confidence}")
            if finding.decision_numbers:
                lines.append("**Decision numbers:**")
                for dn in finding.decision_numbers:
                    lines.append(f'  - "{dn}"')
            else:
                lines.append("**Decision numbers:** []")
            if finding.sources:
                lines.append("")
                lines.append("### Sources")
                lines.append("")
                for src in finding.sources:
                    lines.append(f"- [url]({src.url})")
                    if src.title:
                        lines.append(f"  - title: {src.title}")
                    if src.source_type:
                        lines.append(f"  - type: {src.source_type}")
                    if src.accessed_at:
                        lines.append(f"  - accessed: {_format_datetime(src.accessed_at)}")
            lines.append("")

    return "\n".join(lines)


def _split_frontmatter(content: str) -> tuple[dict, str]:
    """Split markdown into (frontmatter dict, body string).

    Frontmatter is delimited by '---' lines. Returns ({}, content) if
    no frontmatter is present.
    """
    lines = content.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, content
    idx = 1
    fm_lines: list[str] = []
    while idx < len(lines) and lines[idx].strip() != "---":
        fm_lines.append(lines[idx])
        idx += 1
    body = "\n".join(lines[idx + 1:]) if idx < len(lines) else ""
    return _parse_simple_yaml("\n".join(fm_lines)), body


def _strip_janus_domain_frontmatter(body: str) -> str:
    """Remove a leading ``janus_domain`` frontmatter block from *body*.

    When a Hermes Kanban task completes, the task body may contain a
    ``janus_domain`` frontmatter block (the Janus↔Hermes bridge), possibly
    preceded by Kanban-injected metadata lines (e.g.
    ``integration_required: false``), followed by the actual artifact or ADR
    markdown.  This function strips that leading ``janus_domain`` block
    (and any preceding metadata lines) so the remaining text can be parsed
    by ``_parse_artifact_content`` or ``_parse_decision_content``, which
    expect the *first* ``---``-delimited block to be their own frontmatter.

    If the body does not contain a ``janus_domain`` block, it is returned
    unchanged.
    """
    if not body or not body.strip():
        return body or ""
    # Use the project's frontmatter regex to find the first --- block.
    match = _FRONTMATTER_RE.search(body)
    if match is None:
        return body
    if "janus_domain" not in match.group(1):
        # First frontmatter block is NOT a janus_domain block — leave as-is.
        return body
    # Return everything after the closing --- of the janus_domain block.
    return body[match.end():]


def _parse_simple_yaml(text: str) -> dict:
    """Parse a minimal YAML subset: key: value and key: [list, ...] and nested lists.

    Handles scalar values and list values (both inline ``[a, b]`` and
    block-style ``  - item``).
    """
    result: dict = {}
    current_key: str | None = None
    current_list: list | None = None

    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        if not line or line.strip().startswith("#"):
            continue
        stripped = line.strip()

        # Top-level key (no leading indentation)
        if not line.startswith(" "):
            if ":" in stripped:
                key, _, val = stripped.partition(":")
                key = key.strip()
                val = val.strip()
                if val:
                    # Try inline list [a, b, c]
                    if val.startswith("[") and val.endswith("]"):
                        items = [
                            _unquote(x.strip())
                            for x in val[1:-1].split(",")
                            if x.strip()
                        ]
                        result[key] = items
                    else:
                        result[key] = _unquote(val)
                    current_key = None
                    current_list = None
                else:
                    # Block-style list or nested — start collecting
                    current_key = key
                    result[key] = []
                    current_list = result[key]
            else:
                current_key = None
                current_list = None
        else:
            # Indented line — belongs to current_key's list
            if current_key is not None and current_list is not None and stripped.startswith("- "):
                item = stripped[2:].strip()
                current_list.append(_unquote(item))

    return result


def _unquote(val: str) -> str:
    """Strip surrounding quotes from a value."""
    val = val.strip()
    if len(val) >= 2 and val[0] == val[-1] and val[0] in ('"', "'"):
        return val[1:-1]
    return val


def _parse_datetime(raw: str) -> datetime | None:
    """Parse an ISO datetime string into a timezone-aware datetime."""
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt = dt.astimezone()
        return dt
    except (ValueError, TypeError):
        return None


def _format_datetime(dt: datetime) -> str:
    """Format a datetime as ISO 8601 string."""
    if dt.tzinfo is None:
        dt = dt.astimezone()
    return dt.isoformat()


def _extract_section(body: str, section_name: str) -> str:
    """Extract text under a markdown heading (## SectionName or # SectionName)."""
    pattern = re.compile(
        r"^#+\s+" + re.escape(section_name) + r"\s*$\s*\n+(.*?)(?=^#+\s|^\Z)",
        re.MULTILINE | re.DOTALL,
    )
    match = pattern.search(body)
    if match:
        return match.group(1).strip()
    return ""


def _extract_findings(body: str) -> list[Finding]:
    """Extract findings from the # Findings section of an artifact."""
    findings: list[Finding] = []
    finding_pattern = re.compile(
        r"^##\s+Finding\s+\d+\s*$",
        re.MULTILINE,
    )
    matches = list(finding_pattern.finditer(body))
    for i, match in enumerate(matches):
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        finding_text = body[start:end].strip()
        finding = _parse_finding_block(finding_text)
        if finding:
            findings.append(finding)
    return findings


def _parse_finding_block(text: str) -> Finding | None:
    """Parse a single finding block into a Finding object."""
    statement = ""
    topic = ""
    confidence = "sredni"
    decision_numbers: list[str] = []
    sources: list[Source] = []

    lines = text.splitlines()
    in_sources = False
    source_lines: list[str] = []

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("### Sources"):
            in_sources = True
            continue
        if re.match(r"^##\s", stripped) and not stripped.startswith("## Finding"):
            # Next section started
            in_sources = False
            continue

        if stripped.startswith("**Statement:**"):
            statement = stripped[len("**Statement:**"):].strip()
        elif stripped.startswith("**Topic:**"):
            topic = stripped[len("**Topic:**"):].strip()
        elif stripped.startswith("**Confidence:**"):
            raw = stripped[len("**Confidence:**"):].strip()
            if raw in CONFIDENCE_LEVELS:
                confidence = raw
        elif stripped.startswith("**Decision numbers:**"):
            raw = stripped[len("**Decision numbers:**"):].strip()
            if raw == "[]":
                decision_numbers = []
            # Block-style list items will be captured in the next loop iteration
        elif in_sources:
            if stripped.startswith("- ") or stripped.startswith("  - "):
                source_lines.append(stripped)
            elif stripped.startswith("title:") or stripped.startswith("type:") or stripped.startswith("accessed:"):
                source_lines.append(stripped)

    # Parse sources from collected lines
    sources = _parse_source_lines(source_lines)

    # Parse decision_numbers from indented list items after "**Decision numbers:**"
    # These appear as `  - "value"` lines
    decision_numbers = _parse_decision_number_list(text)

    if not statement:
        return None

    if not sources:
        return None

    return Finding(
        statement=statement,
        topic=topic,
        confidence=confidence,
        sources=sources,
        decision_numbers=decision_numbers,
    )


def _parse_decision_number_list(text: str) -> list[str]:
    """Extract decision numbers from the indented list under **Decision numbers:**."""
    result: list[str] = []
    lines = text.splitlines()
    in_decision_list = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("**Decision numbers:**"):
            raw = stripped[len("**Decision numbers:**"):].strip()
            if raw == "[]":
                return []
            in_decision_list = True
            continue
        if in_decision_list:
            if stripped.startswith("- "):
                item = _unquote(stripped[2:].strip())
                if item:
                    result.append(item)
            elif stripped.startswith("**"):
                # Next field
                in_decision_list = False
            elif not stripped:
                continue
            else:
                in_decision_list = False
    return result


def _parse_source_lines(lines: list[str]) -> list[Source]:
    """Parse source lines from the format:
    - [url](http://...)
      - title: ...
      - type: ...
      - accessed: ...
    """
    sources: list[Source] = []
    current_source: Source | None = None

    for line in lines:
        stripped = line.strip()
        # Strip leading "- " for sub-fields like "- title: ..."
        if stripped.startswith("- "):
            stripped = stripped[2:].strip()
        url_match = re.match(r"\[url\]\((.+)\)$", stripped)
        if url_match:
            if current_source is not None and current_source.url:
                sources.append(current_source)
            url = url_match.group(1)
            current_source = Source(url=url, title="", source_type="web")
        elif current_source is not None:
            if stripped.startswith("title:"):
                current_source.title = stripped[len("title:"):].strip()
            elif stripped.startswith("type:"):
                raw = stripped[len("type:"):].strip()
                if raw in SOURCE_TYPES:
                    current_source.source_type = raw
            elif stripped.startswith("accessed:"):
                raw = stripped[len("accessed:"):].strip()
                current_source.accessed_at = _parse_datetime(raw)

    if current_source is not None and current_source.url:
        sources.append(current_source)

    return sources
