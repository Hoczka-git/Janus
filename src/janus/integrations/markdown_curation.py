"""Markdown persistence for CurationProposal (data/curation_proposals.md).

Follows the existing Janus markdown-persistence pattern (markdown_inbox.py,
markdown_followups.py): one line per record, ``|``-delimited fields,
front-matter-style metadata.  Uses ``atomic_io.read_modify_write`` for all
writes and supports a custom ``path`` for testability.
"""

import logging
import re
import uuid
from datetime import datetime
from pathlib import Path

from janus.integrations.atomic_io import atomic_write, compute_content_hash
from janus.models.curation_proposal import CurationProposal, APPROVAL_STATES
from janus.models.knowledge_summary import KnowledgeSummary
from janus.models.research_artifact import Finding, ResearchArtifact, Source

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
PROPOSALS_PATH = PROJECT_ROOT / "data" / "curation_proposals.md"


# ── Load ────────────────────────────────────────────────────────────────────

def load_proposals(path: Path | None = None) -> list[CurationProposal]:
    """Load all curation proposals from data/curation_proposals.md.

    Returns [] if the file is missing.  Lines that fail to parse are logged
    and skipped (graceful degradation), matching the markdown_inbox pattern.
    """
    fp = path if path is not None else PROPOSALS_PATH
    if not fp.exists():
        return []

    proposals: list[CurationProposal] = []
    with fp.open() as f:
        for line_num, line in enumerate(f, start=1):
            line = line.strip()
            if not line.startswith("cp-"):
                continue
            try:
                proposal = _parse_proposal_line(line, line_num)
                if proposal is not None:
                    proposals.append(proposal)
            except Exception as exc:
                logger.warning(
                    "Failed to parse curation proposal line %d: %s", line_num, exc
                )
    logger.debug("Loaded %d curation proposals from %s", len(proposals), fp)
    return proposals


# ── Save (new append) ──────────────────────────────────────────────────────

def save_proposal(proposal: CurationProposal) -> None:
    """Append a new proposal to data/curation_proposals.md."""
    line = _format_proposal_line(proposal)
    content = atomic_read(PROPOSALS_PATH)
    atomic_write(
        PROPOSALS_PATH,
        content + line + "\n",
        expected_hash=compute_content_hash(content) if content else None,
        written_by="markdown_curation.save_proposal",
    )


# ── Update (in-place rewrite) ──────────────────────────────────────────────

def update_proposal(proposal: CurationProposal) -> None:
    """Rewrite an existing proposal line in-place by proposal_id."""
    raw_content = atomic_read(PROPOSALS_PATH)
    if not raw_content:
        raise ValueError(f"Curation proposal not found: {proposal.proposal_id}")
    lines = raw_content.splitlines()
    found = False
    new_lines: list[str] = []
    for line in lines:
        if line.startswith(f"cp-{proposal.proposal_id} |"):
            new_lines.append(_format_proposal_line(proposal))
            found = True
        else:
            new_lines.append(line)
    if not found:
        raise ValueError(f"Curation proposal not found: {proposal.proposal_id}")
    new_content = "\n".join(new_lines) + "\n"
    atomic_write(
        PROPOSALS_PATH,
        new_content,
        expected_hash=compute_content_hash(raw_content),
        written_by="markdown_curation.update_proposal",
    )


# ── Serialization helpers ──────────────────────────────────────────────────

def _format_proposal_line(proposal: CurationProposal) -> str:
    """Serialize a CurationProposal to a single delimited line.

    Only non-default fields are emitted (matching the markdown_inbox pattern
    of omitting ``state: pending`` for InboxItem).
    """
    # Summary is serialized as a compact JSON-ish blob so the whole record
    # fits one line while remaining human-readable at a glance.
    summary_json = _serialize_summary_json(proposal.summary)
    warnings_json = _serialize_warnings_json(proposal.warnings)

    parts = [f"cp-{proposal.proposal_id} | {summary_json}"]

    parts.append(f"warnings: {warnings_json}")
    parts.append(f"state: {proposal.approval_state}")
    if proposal.created_at:
        parts.append(f"created_at: {proposal.created_at.isoformat()}")
    if proposal.updated_at:
        parts.append(f"updated_at: {proposal.updated_at.isoformat()}")
    if proposal.approver:
        parts.append(f"approver: {proposal.approver}")
    if proposal.decision_note:
        parts.append(f"note: {proposal.decision_note}")
    if proposal.vault_path:
        parts.append(f"vault_path: {proposal.vault_path}")

    return " | ".join(parts)


def _parse_proposal_line(line: str, line_num: int) -> CurationProposal | None:
    """Parse one line → CurationProposal. Raises ValueError on bad data."""
    parts = line.split(" | ", 2)
    if len(parts) < 3:
        raise ValueError(
            f"Invalid curation line {line_num}: expected 'cp-<id> | <summary> | <metadata>'"
        )
    id_part = parts[0]
    summary_json = parts[1]
    rest = parts[2]

    if not id_part.startswith("cp-"):
        raise ValueError(f"Invalid curation line {line_num}: missing cp- prefix")
    proposal_id = id_part[3:]

    # Parse metadata fields
    state = _parse_field(rest, r"state:\s*(\S+)", default="pending_approval")
    if state not in APPROVAL_STATES:
        raise ValueError(
            f"Invalid state in curation line {line_num}: {state!r}. "
            f"Allowed: {', '.join(APPROVAL_STATES)}"
        )

    created_at_str = _parse_field(rest, r"created_at:\s*(\S+)", default=None)
    created_at = _parse_dt(created_at_str)
    updated_at_str = _parse_field(rest, r"updated_at:\s*(\S+)", default=None)
    updated_at = _parse_dt(updated_at_str)

    approver = (_parse_field(rest, r"approver:\s*([^|]+)", default="") or "").strip()
    decision_note = (_parse_field(rest, r"note:\s*([^|]+)", default="") or "").strip()
    vault_path = (_parse_field(rest, r"vault_path:\s*([^|]+)", default="") or "").strip()

    # Parse warnings (the ``warnings:`` field may contain ``|`` inside the JSON
    # array, so extract it first before splitting metadata).
    warnings_json = _extract_field_before(rest, "warnings:", default="[]")
    warnings = _parse_warnings_json(warnings_json)

    summary = _parse_summary_json(summary_json)

    return CurationProposal(
        proposal_id=proposal_id,
        summary=summary,
        warnings=warnings,
        approval_state=state,
        created_at=created_at,
        updated_at=updated_at,
        approver=approver,
        decision_note=decision_note,
        vault_path=vault_path,
    )


def _parse_field(metadata: str, pattern: str, default: str | None) -> str | None:
    match = re.search(pattern, metadata)
    return match.group(1) if match else default


def _extract_field_before(text: str, field_name: str, default: str) -> str:
    """Extract a field value that may contain delimiters (e.g. JSON arrays).

    Finds ``field_name:`` and returns everything up to the next ``key:`` pattern
    or end-of-string.  The ``field_name`` search is anchored on the exact
    prefix so that ``warnings:`` does not match ``notes:`` etc.
    """
    idx = text.find(field_name)
    if idx == -1:
        return default
    start = idx + len(field_name)
    rest = text[start:].strip()
    # The next field is introduced by " | key:" (the delimiter is " | ").
    next_field = re.search(r"\|\s+(state:|created_at:|updated_at:|approver:|note:|vault_path:|warnings:)", rest)
    if next_field:
        return rest[:next_field.start()].strip()
    return rest.strip()


def _parse_dt(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt = dt.astimezone()
        return dt
    except (ValueError, TypeError):
        return None


def _serialize_summary_json(summary: KnowledgeSummary) -> str:
    """Serialize a KnowledgeSummary to a compact single-line JSON string."""
    import json

    def finding_dict(f: Finding) -> dict:
        return {
            "statement": f.statement,
            "topic": f.topic,
            "confidence": f.confidence,
            "sources": [
                {"url": s.url, "title": s.title, "source_type": s.source_type}
                for s in f.sources
            ],
            "decision_numbers": list(f.decision_numbers),
        }

    def topic_block_dict(tb) -> dict:
        return {
            "topic": tb.topic,
            "composite_confidence": tb.composite_confidence,
            "narrative": tb.narrative,
            "findings": [finding_dict(f) for f in tb.findings],
        }

    payload = {
        "target": summary.target,
        "title": summary.title,
        "summary_text": summary.summary_text,
        "conclusions": summary.conclusions,
        "topic_blocks": [topic_block_dict(tb) for tb in summary.topic_blocks],
        "entities": list(summary.entities),
        "knowledge_gaps": list(summary.knowledge_gaps),
        "artifact_version": summary.artifact_version,
        "generated_at": summary.generated_at.isoformat() if summary.generated_at else None,
    }
    return json.dumps(payload, separators=(",", ":"), ensure_ascii=False)


def _parse_summary_json(raw: str) -> KnowledgeSummary:
    """Deserialize a KnowledgeSummary from its compact JSON form."""
    import json

    data = json.loads(raw)
    topic_blocks: list = []
    for tb_data in data.get("topic_blocks", []):
        findings: list[Finding] = []
        for f_data in tb_data.get("findings", []):
            sources = [
                Source(url=s["url"], title=s.get("title", ""), source_type=s.get("source_type", "web"))
                for s in f_data.get("sources", [])
            ]
            findings.append(Finding(
                statement=f_data["statement"],
                topic=f_data.get("topic", ""),
                confidence=f_data.get("confidence", "sredni"),
                sources=sources,
                decision_numbers=list(f_data.get("decision_numbers", [])),
            ))
        from janus.models.knowledge_summary import TopicBlock
        topic_blocks.append(TopicBlock(
            topic=tb_data["topic"],
            findings=findings,
            composite_confidence=tb_data.get("composite_confidence", ""),
            narrative=tb_data.get("narrative", ""),
        ))

    generated_at = None
    if data.get("generated_at"):
        generated_at = _parse_dt(data["generated_at"])

    return KnowledgeSummary(
        target=data["target"],
        title=data["title"],
        summary_text=data["summary_text"],
        conclusions=data["conclusions"],
        topic_blocks=topic_blocks,
        entities=list(data.get("entities", [])),
        knowledge_gaps=list(data.get("knowledge_gaps", [])),
        artifact_version=int(data.get("artifact_version", 1)),
        generated_at=generated_at,
    )


def _serialize_warnings_json(warnings: list[dict]) -> str:
    import json
    return json.dumps(warnings, separators=(",", ":"), ensure_ascii=False)


def _parse_warnings_json(raw: str) -> list[dict]:
    import json
    if not raw or raw == "[]":
        return []
    return json.loads(raw)


def atomic_read(path: Path) -> str:
    """Read file content as text, returning empty string if missing."""
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def next_proposal_id() -> str:
    """Generate a fresh curation proposal id (8-char hex, no prefix).

    The ``cp-`` prefix is added by the line formatter when persisted and
    stripped by the line parser when loaded — see the markdown_inbox pattern
    where ``InboxItem.id`` carries the ``ix-`` prefix.
    """
    return uuid.uuid4().hex[:8]
