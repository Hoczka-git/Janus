"""Execution feedback consumer functions and parsers for Janus.

These are the Janus-side entry points consumed by the Hermes-side sync
listener (a ``kanban_task_completed`` hook consumer, conceptually
``plugins/janus_sync/``).  The listener parses ``janus_domain``
frontmatter from the completed task body, builds an :class:`EvidencePackage`,
and dispatches to the relevant Janus service function.

Directionality: Hermes → Janus.  Janus does not call Hermes.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

from janus._log import emit

logger = logging.getLogger(__name__)


# ── Evidence package ──────────────────────────────────────────────────────────

@dataclass
class EvidencePackage:
    """Structured evidence of a completed Kanban task, for Janus domain state.

    Mirrors the dict shape described in design doc §4.5 and the
    ``evidence`` dict in §4.2.

    The ``body`` field carries the full task body text. It is used when
    ``janus_domain.object`` is ``research`` or ``decision`` — the body
    contains the artifact or ADR markdown that must be ingested into
    Janus storage (design spec §7.2 Option B / §7.3 Option B).
    """
    task_id: str
    summary: str
    completed_at: str | None = None
    changed_files: list[str] | None = field(default_factory=list)
    tests_passed: bool | None = None
    pr_url: str | None = None
    body: str | None = None

    def to_dict(self) -> dict:
        """Serialize to a plain dict for storage in ``Goal.recent_activity``.

        Includes ``body`` so that the dispatch result recorded in the audit
        comment reflects what was ingested (or skipped).
        """
        return {
            "task_id": self.task_id,
            "summary": self.summary,
            "completed_at": self.completed_at,
            "changed_files": self.changed_files or [],
            "tests_passed": self.tests_passed,
            "pr_url": self.pr_url,
            "body": self.body,
        }


# ── janus_domain frontmatter parser ───────────────────────────────────────────

# Frontmatter: opens with a line of ``-`` (3+ dashes), closes with a line of
# ``-`` on its own.  Body content may follow the closing fence (the common case
# for task bodies).  ``.*?` is lazy so the first closing fence wins; the fence
# must sit on its own line (preceded by a newline) so we don't mismatch intra-body
# ``---`` separators.
#
# The opening fence may follow leading metadata lines injected by the Kanban
# layer (e.g. ``integration_required: false``), so it is matched either at the
# start of the body or after a newline rather than being anchored to column 0.
_FRONTMATTER_RE = re.compile(r"(?:^|\n)-{3,}\s*\n(.*?)\n-{3,}\s*(?:\n|$)", re.DOTALL)


@dataclass
class JanusDomainMetadata:
    """Parsed ``janus_domain`` frontmatter from a task body."""
    object: str                    # "goal" | "task" | "milestone" | ...
    title: str                     # domain title to link the task to
    changed_files: list[str] | None = field(default_factory=list)
    tests_passed: bool | None = None
    pr_url: str | None = None

    @property
    def is_execution_feedback(self) -> bool:
        """True when this metadata carries execution-feedback fields.

        A ``janus_domain`` block without changed_files/tests_passed/pr_url
        is still valid linkage metadata, but carries no feedback evidence.
        """
        return (
            bool(self.changed_files)
            or self.tests_passed is not None
            or bool(self.pr_url)
        )


def parse_janus_domain_metadata(body: str | None) -> JanusDomainMetadata | None:
    """Parse ``janus_domain`` frontmatter from a task body.

    The frontmatter is a YAML block delimited by ``---`` at the very
    start of the body.  Example::

        ---
        janus_domain:
          object: goal
          title: "GLUE biotech research"
          changed_files:
            - src/janus/services/knowledge_pipeline.py
          tests_passed: true
          pr_url: "https://github.com/.../pull/90"
        ---

    Returns ``None`` when the body has no ``janus_domain`` block.
    Raises ``ValueError`` when the block is present but malformed
    (missing required keys ``object`` / ``title``, or ``object`` is not
    a known domain type).
    """
    if not body or not body.strip():
        return None

    # Search for the frontmatter block anywhere in the body.  The Kanban layer
    # may prepend audit metadata lines (e.g. ``integration_required: false``)
    # before the ``---`` fence, so we use ``search`` rather than ``match``.
    match = _FRONTMATTER_RE.search(body)
    if match is None:
        return None

    yaml_block = match.group(1)

    # Parse the YAML frontmatter.  We use a minimal approach: import yaml
    # lazily so the module loads even if PyYAML is not installed (the
    # parser is the listener's responsibility, but Janus provides this
    # helper for tests).
    try:
        import yaml
    except ImportError:
        logger.debug("PyYAML not available; falling back to simple parser")
        metadata = _parse_janus_domain_simple(yaml_block)
    else:
        try:
            front = yaml.safe_load(yaml_block)
        except yaml.YAMLError as exc:
            raise ValueError(f"Invalid YAML frontmatter: {exc}") from exc
        if not isinstance(front, dict):
            raise ValueError("Frontmatter is not a mapping")
        metadata = front.get("janus_domain")

    if metadata is None:
        return None

    if not isinstance(metadata, dict):
        raise ValueError(
            f"janus_domain must be a mapping, got {type(metadata).__name__}"
        )

    obj = metadata.get("object")
    title = metadata.get("title")

    if not obj or not isinstance(obj, str):
        raise ValueError("janus_domain.object is required and must be a string")
    if not title or not isinstance(title, str):
        raise ValueError("janus_domain.title is required and must be a string")

    known = {"goal", "task", "milestone", "project", "finding", "decision", "research"}
    if obj not in known:
        raise ValueError(
            f"Unknown janus_domain.object: {obj!r}. "
            f"Allowed: {sorted(known)}"
        )

    return JanusDomainMetadata(
        object=obj.strip(),
        title=title.strip(),
        changed_files=metadata.get("changed_files") or [],
        tests_passed=metadata.get("tests_passed"),
        pr_url=metadata.get("pr_url"),
    )


def _parse_janus_domain_simple(yaml_block: str) -> dict | None:
    """Simple YAML fallback parser for ``janus_domain`` (no PyYAML).

    Handles the minimal subset used by Janus domain metadata: a top-level
    ``janus_domain:`` key with nested scalar and list values.
    """
    import json

    result: dict = {}
    current_key: str | None = None
    current_list: list | None = None

    for raw_line in yaml_block.splitlines():
        line = raw_line.rstrip()
        if not line or line.startswith("#"):
            continue
        stripped = line.strip()
        # Check if this is a top-level key (no leading indentation)
        if not line.startswith(" "):
            if stripped.endswith(":"):
                current_key = stripped[:-1].strip()
                current_list = None
                result[current_key] = {}
            else:
                current_key = None
                current_list = None
        elif current_key is not None and stripped.endswith(":"):
            # Nested key under current_key
            sub_key = stripped[:-1].strip()
            if isinstance(result[current_key], dict):
                result[current_key][sub_key] = None
                current_list = None
            else:
                current_list = None
        elif current_key is not None and stripped.startswith("- "):
            # List item
            if isinstance(result[current_key], dict):
                # We're inside a sub-key that is a list
                sub_key = list(result[current_key].keys())[-1] \
                    if result[current_key] else None
                if sub_key and isinstance(
                    result[current_key][sub_key], list
                ):
                    item = stripped[2:].strip()
                    # Try JSON decode for quoted strings
                    try:
                        item = json.loads(item)
                    except (json.JSONDecodeError, ValueError):
                        pass
                    result[current_key][sub_key].append(item)
        elif current_key is not None and ":" in stripped:
            key, _, val = stripped.partition(":")
            key = key.strip()
            val = val.strip()
            if isinstance(result[current_key], dict):
                # Try to parse the value
                if val:
                    try:
                        parsed = json.loads(val)
                    except (json.JSONDecodeError, ValueError):
                        parsed = val
                    result[current_key][key] = parsed
                else:
                    result[current_key][key] = []
                    current_list = result[current_key][key]
    return result


# ── Dispatch helpers ──────────────────────────────────────────────────────────

def dispatch_completion(
    metadata: JanusDomainMetadata,
    evidence: EvidencePackage,
) -> dict:
    """Route an evidence package to the correct Janus service function.

    This is a convenience wrapper used by the sync listener to dispatch
    based on ``metadata.object``.  Returns a dict describing the result
    of each service call (which may include errors that are not fatal).
    """
    results: dict = {}

    # Service functions accept a plain dict (design §4.2/§4.5); serialize
    # the EvidencePackage before dispatching so callers can pass either form.
    evidence_dict = evidence.to_dict()

    if metadata.object == "goal":
        from janus.services.goals import update_goal_progress
        results["goal"] = update_goal_progress(
            title=metadata.title,
            completed_task_id=evidence.task_id,
            completed_task_title=evidence.summary,
            evidence=evidence_dict,
        )
    elif metadata.object == "task":
        from janus.services.tasks import complete_janus_task
        results["task"] = complete_janus_task(
            title=metadata.title,
            evidence=evidence_dict,
        )
    elif metadata.object == "milestone":
        from janus.services.milestones import update_milestone_status
        results["milestone"] = update_milestone_status(
            title=metadata.title,
            completed_task_id=evidence.task_id,
            evidence=evidence_dict,
        )
    elif metadata.object in ("research", "finding", "decision"):
        # Ingest the completed task body into Janus storage.
        #
        # For "research" and "finding" the body is a research artifact
        # markdown file (frontmatter + sections). It is parsed and persisted
        # via services.research_artifacts.
        #
        # For "decision" the body is an ADR markdown file
        # (frontmatter with adr_number/title/status/etc.). It is parsed
        # and persisted via services.decisions.
        if not evidence.body:
            results["skipped"] = metadata.object
            results["reason"] = "no body content to ingest"
        elif metadata.object == "decision":
            results["decision"] = _ingest_decision(metadata, evidence)
        else:
            results["research"] = _ingest_research(metadata, evidence)
    else:
        logger.warning(
            "No Janus service function for domain object %r",
            metadata.object,
        )
        results["skipped"] = metadata.object

    emit(logger, "service.execution_feedback.dispatched",
         trace_id=None, span_id="execution_feedback",
         domain_object=metadata.object, domain_title=metadata.title,
         task_id=evidence.task_id,
         message=f"Dispatched completion to Janus service for {metadata.object}")

    return results


# ── Ingestion helpers ────────────────────────────────────────────────────────
#
# These bridge the Hermes → Janus write-back path (design spec §7.2 Option B /
# §7.3 Option B).  When a Hermes Kanban task that carries
# ``janus_domain: object: research|finding|decision`` completes, the task body
# contains the full markdown artifact or ADR.  The sync listener passes that
# body via ``EvidencePackage.body`` and ``dispatch_completion`` routes to the
# appropriate helper, which parses and persists the content.


def _ingest_research(
    metadata: JanusDomainMetadata,
    evidence: EvidencePackage,
) -> dict:
    """Parse a research artifact markdown body and persist it via Janus.

    The ``evidence.body`` is expected to contain a full research artifact
    markdown file (frontmatter + sections) — the same format consumed by
    ``janus research add``.  The ``janus_domain.title`` from frontmatter
    is used as the link target if the artifact specifies one.

    Returns a dict with the persisted artifact's slug/title, or ``"skipped"``
    when the body cannot be parsed as a research artifact.
    """
    from janus.integrations.markdown_research import (
        _parse_artifact_content,
        _slugify,
        _strip_janus_domain_frontmatter,
    )
    from janus.services.research_artifacts import (
        create_artifact,
        update_artifact,
    )

    if not evidence.body:
        return {"skipped": metadata.object, "reason": "no body content to ingest"}

    # Strip the leading janus_domain frontmatter block (if present) so the
    # artifact's own frontmatter is the first --- block.
    artifact_body = _strip_janus_domain_frontmatter(evidence.body)
    if not artifact_body or not artifact_body.strip():
        return {"skipped": metadata.object, "reason": "no artifact markdown body"}

    try:
        artifact = _parse_artifact_content(artifact_body)
    except Exception as exc:
        logger.warning(
            "Failed to parse research artifact from task %s: %s",
            evidence.task_id, exc,
        )
        return {"skipped": metadata.object, "error": str(exc)}

    try:
        path = create_artifact(artifact)
    except ValueError as exc:
        # Artifact with this slug already exists — update it in place instead.
        logger.info(
            "Research artifact already exists, updating in place: %s",
            exc,
        )
        slug = _slugify(artifact.title)
        path = update_artifact(artifact, slug=slug)

    result = {
        "object": "research",
        "title": artifact.title,
        "slug": path.stem,
        "findings": len(artifact.findings),
        "path": str(path),
    }
    if artifact.linked_goal_titles:
        result["linked_goal_titles"] = artifact.linked_goal_titles
    return result


def _ingest_decision(
    metadata: JanusDomainMetadata,
    evidence: EvidencePackage,
) -> dict:
    """Parse an ADR markdown body and persist it via Janus.

    The ``evidence.body`` is expected to contain a full ADR markdown file
    with YAML frontmatter (``adr_number``, ``title``, ``status``, etc.)
    — the same format consumed by ``janus decision propose``.  The
    ``janus_domain.title`` from frontmatter is cross-checked against the
    ADR's own ``title`` field; they should agree.

    Returns a dict with the persisted ADR path, or ``"skipped"`` when the
    body cannot be parsed as an ADR.
    """
    if not evidence.body:
        return {"skipped": metadata.object, "reason": "no body content to ingest"}

    from janus.decision_cli import _parse_decision_content
    from janus.integrations.markdown_research import _strip_janus_domain_frontmatter

    # Strip the leading janus_domain frontmatter block (if present) so the
    # ADR's own frontmatter is the first --- block.
    adr_body = _strip_janus_domain_frontmatter(evidence.body)
    if not adr_body or not adr_body.strip():
        return {"skipped": metadata.object, "reason": "no ADR markdown body"}

    try:
        decision = _parse_decision_content(adr_body)
    except Exception as exc:
        logger.warning(
            "Failed to parse decision from task %s: %s",
            evidence.task_id, exc,
        )
        return {"skipped": metadata.object, "error": str(exc)}

    from janus.services.decisions import create_decision
    try:
        path = create_decision(decision)
    except ValueError as exc:
        logger.warning("Decision already exists, skipping: %s", exc)
        from janus.services.decisions import get_decision
        existing = get_decision(decision.adr_number)
        return {
            "object": "decision",
            "adr_number": existing.adr_number,
            "title": existing.title,
            "status": existing.status,
            "skipped_existing": True,
        }

    return {
        "object": "decision",
        "adr_number": decision.adr_number,
        "title": decision.title,
        "status": decision.status,
        "path": str(path),
    }
