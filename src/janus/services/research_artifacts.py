"""Research artifact service — CRUD and linking operations.

Persistence is via markdown files in data/research/<slug>.md
(markdown_research.py integration). Business logic lives here; storage
details are in the integration layer.

Follows the existing Janus dataclass/service pattern (goals.py, decisions.py).
"""
from __future__ import annotations

import logging
from pathlib import Path

from janus._log import emit
from janus.models.research_artifact import (
    Finding,
    ResearchArtifact,
)
from janus.integrations.markdown_research import (
    RESEARCH_DIR,
    load_artifact as _load_artifact,
    load_all_artifacts as _load_all_artifacts,
    save_artifact as _save_artifact,
    update_artifact as _update_artifact,
)

logger = logging.getLogger(__name__)


def create_artifact(artifact: ResearchArtifact) -> Path:
    """Validate and persist a new ResearchArtifact to data/research/<slug>.md.

    Raises ValueError if an artifact with the same slug already exists.
    Returns the path to the created file.
    """
    path = _save_artifact(artifact)
    emit(logger, "service.research_artifact.mutated",
         trace_id=None, span_id="create_artifact",
         slug=path.stem, title=artifact.title,
         operation="create",
         message=f"Created research artifact '{path.stem}'")
    return path


def create_artifact_via_ingest(body: str, *, title: str = "", source: str = "cli",
                               evidence: dict | None = None) -> "IngestResult":
    """Construct a RESEARCH_ARTIFACT ActivityRecord and route it through
    the canonical ADR-005 ingestion gate (``ingest_activities``).

    The ``body`` is the full research artifact markdown (frontmatter +
    sections).  ``title`` is used solely for the record's ``task_title``
    field (the canonical title is parsed from the body itself).

    Returns the :class:`IngestResult` from the ingestion gate.
    """
    from datetime import datetime, timezone
    from janus.services.activity_ingest import (
        ActivityRecord,
        ActivityType,
        ingest_activities,
    )
    record = ActivityRecord(
        type=ActivityType.RESEARCH_ARTIFACT,
        source=source,
        timestamp=datetime.now(timezone.utc),
        task_title=title or _slugify_title_from_body(body),
        captured_text=body,
        evidence=evidence or {},
    )
    return ingest_activities([record])[0]


def _slugify_title_from_body(body: str) -> str:
    """Best-effort title extraction from markdown frontmatter."""
    import re
    m = re.match(r"^---\s*\ntitle:\s*(.+)\s*$", body, re.MULTILINE)
    if m:
        return m.group(1).strip()
    return "Untitled"


def load_artifact(slug: str) -> ResearchArtifact:
    """Load a single research artifact by slug.

    Raises ValueError if not found.
    """
    return _load_artifact(slug)


def load_all_artifacts() -> list[ResearchArtifact]:
    """Load all research artifacts from data/research/.

    Returns [] if directory or files are missing.
    """
    return _load_all_artifacts()


def update_artifact(artifact: ResearchArtifact, slug: str | None = None) -> Path:
    """Update an existing research artifact in place.

    If slug is None, it is derived from the artifact title.
    Raises ValueError if the artifact file does not exist.
    """
    path = _update_artifact(artifact, slug)
    emit(logger, "service.research_artifact.mutated",
         trace_id=None, span_id="update_artifact",
         slug=path.stem, title=artifact.title,
         operation="update",
         message=f"Updated research artifact '{path.stem}'")
    return path


def link_finding_to_decision(
    artifact_title: str,
    finding_index: int,
    adr_number: str,
) -> ResearchArtifact | None:
    """Link a finding (by index) in a persisted artifact to a decision.

    Updates the artifact's Finding.decision_numbers in-place and persists
    the artifact. The decision-side update (Informed by section) is handled
    by services/decisions.py:link_finding_to_decision.

    Idempotent: no-op if the adr_number is already in the finding's
    decision_numbers. If the finding is not found, raises ValueError.

    Args:
        artifact_title: The title of the research artifact (used to locate
            the file via slugified title).
        finding_index: Zero-based index into the artifact's findings list.
        adr_number: The ADR number to link (e.g. "005").

    Returns:
        The updated ResearchArtifact, or None if the artifact is not found.
    """
    # Find the artifact by title — we need to scan all artifacts since
    # the slug is derived from the title.
    artifacts = load_all_artifacts()
    target = None
    target_slug = None
    for art in artifacts:
        if art.title == artifact_title:
            target = art
            target_slug = _slugify_title(art.title)
            break

    if target is None:
        logger.warning("Artifact not found for finding link: %s", artifact_title)
        return None

    if finding_index < 0 or finding_index >= len(target.findings):
        raise ValueError(
            f"Finding index {finding_index} out of range "
            f"(artifact has {len(target.findings)} findings)"
        )

    finding = target.findings[finding_index]
    if adr_number not in finding.decision_numbers:
        finding.decision_numbers.append(adr_number)

    # Also update artifact-level decision_numbers
    if adr_number not in target.decision_numbers:
        target.decision_numbers.append(adr_number)

    update_artifact(target, slug=target_slug)
    emit(logger, "service.research_artifact.mutated",
         trace_id=None, span_id="link_finding_to_decision",
         slug=target_slug, adr_number=adr_number, finding_index=finding_index,
         message=f"Linked finding {finding_index} to decision {adr_number}")
    return target


def get_artifacts_for_decision(adr_number: str) -> list[str]:
    """Return titles of all research artifacts that reference this ADR number.

    Scans all artifacts and their findings' decision_numbers.
    """
    artifacts = load_all_artifacts()
    result = []
    for art in artifacts:
        if adr_number in art.decision_numbers:
            result.append(art.title)
        else:
            for finding in art.findings:
                if adr_number in finding.decision_numbers:
                    result.append(art.title)
                    break
    return result


def get_findings_for_decision(adr_number: str) -> list[tuple[str, int]]:
    """Return (artifact_title, finding_index) tuples for findings linked to this ADR.

    Scans all artifacts and their findings' decision_numbers.
    """
    artifacts = load_all_artifacts()
    result = []
    for art in artifacts:
        for i, finding in enumerate(art.findings):
            if adr_number in finding.decision_numbers:
                result.append((art.title, i))
    return result


def _slugify_title(title: str) -> str:
    """Convert a title to its slug form (mirrors markdown_research._slugify)."""
    import re
    slug = title.lower()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_]+", "-", slug.strip())
    slug = re.sub(r"-+", "-", slug)
    return slug.strip("-") or "untitled"
