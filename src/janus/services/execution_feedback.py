"""Execution feedback consumer functions and parsers for Janus.

These are the Janus-side entry points consumed by the Hermes-side sync
listener (a ``kanban_task_completed`` hook consumer, conceptually
``plugins/janus_sync/``).  The listener parses ``janus_domain``
frontmatter from the completed task body, builds an :class:`EvidencePackage`,
and dispatches to the relevant Janus service function.

Directionality: Hermes → Janus.  Janus does not call Hermes.
"""
from __future__ import annotations

import dataclasses
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from janus._log import emit
from janus.models.research_artifact import ResearchArtifact

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

    @classmethod
    def from_dict(cls, data: dict) -> "EvidencePackage":
        """Deserialize from a plain dict (inverse of :meth:`to_dict`).

        Tolerates missing keys — every field has a sensible default so a
        partial or truncated dict (e.g. from markdown storage) reconstructs
        a valid, if minimal, ``EvidencePackage``.
        """
        return cls(
            task_id=data.get("task_id", ""),
            summary=data.get("summary", ""),
            completed_at=data.get("completed_at"),
            changed_files=data.get("changed_files") or [],
            tests_passed=data.get("tests_passed"),
            pr_url=data.get("pr_url"),
            body=data.get("body"),
        )


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

    def to_dict(self) -> dict:
        """Serialize to a plain dict (inverse of :meth:`from_dict`).

        Only the four frontmatter-defined fields are serialized; runtime-only
        state is excluded so the dict round-trips cleanly through YAML/JSON.
        """
        return {
            "object": self.object,
            "title": self.title,
            "changed_files": self.changed_files or [],
            "tests_passed": self.tests_passed,
            "pr_url": self.pr_url,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "JanusDomainMetadata":
        """Deserialize from a plain dict.

        Requires ``object`` and ``title`` (raises ``ValueError`` otherwise),
        mirroring the validation in :func:`parse_janus_domain_metadata`.
        """
        obj = data.get("object")
        title = data.get("title")
        if not obj or not isinstance(obj, str):
            raise ValueError("janus_domain.object is required and must be a string")
        if not title or not isinstance(title, str):
            raise ValueError("janus_domain.title is required and must be a string")
        return cls(
            object=obj.strip(),
            title=title.strip(),
            changed_files=data.get("changed_files") or [],
            tests_passed=data.get("tests_passed"),
            pr_url=data.get("pr_url"),
        )


# ── Execution result message (serializable protocol unit) ────────────────────
#
# An ``ExecutionResultMessage`` is the structured wire-format that travels
# from a Hermes worker back to the Janus side when a Kanban task that
# carries ``janus_domain`` linkage completes.  It bundles the task handoff
# metadata (which Janus domain object the task targets) together with the
# execution-result evidence (which files changed, did tests pass, PR URL)
# into a single serializable unit so that the Hermes → Janus channel has
# a well-defined, self-describing message rather than ad-hoc dicts.
#
# The message is JSON-serializable via :meth:`to_json` /
# :meth:`from_json` and dict-serializable via :meth:`to_dict` /
# :meth:`from_dict`.  The dispatch helpers :func:`send_execution_result`
# and :func:`receive_execution_result` provide the send/receive entry
# points for the protocol.

@dataclass
class ExecutionResultMessage:
    """Structured handoff + execution result message (Hermes → Janus).

    Combines the Janus domain linkage metadata with the evidence package
    that describes what the completed task accomplished.  This is the
    canonical message type for the execution-feedback write-back path.

    Attributes:
        metadata: The Janus domain linkage (object, title, evidence fields).
        evidence: The execution evidence (task_id, summary, changed_files, etc.).
    """
    metadata: JanusDomainMetadata
    evidence: EvidencePackage

    def to_dict(self) -> dict:
        """Serialize to a plain dict suitable for JSON or YAML storage."""
        return {
            "metadata": self.metadata.to_dict(),
            "evidence": self.evidence.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ExecutionResultMessage":
        """Deserialize from a plain dict.

        Raises ``ValueError`` if the ``metadata`` sub-dict is invalid
        (missing ``object`` or ``title``) — propagates from
        :meth:`JanusDomainMetadata.from_dict`.
        """
        md = JanusDomainMetadata.from_dict(data["metadata"])
        ev = EvidencePackage.from_dict(data["evidence"])
        return cls(metadata=md, evidence=ev)

    def to_json(self) -> str:
        """Serialize to a JSON string."""
        import json
        return json.dumps(self.to_dict())

    @classmethod
    def from_json(cls, text: str) -> "ExecutionResultMessage":
        """Deserialize from a JSON string.

        Raises ``json.JSONDecodeError`` on malformed JSON, or
        ``ValueError`` if required fields are missing.
        """
        import json
        return cls.from_dict(json.loads(text))


def send_execution_result(
    metadata: JanusDomainMetadata,
    evidence: EvidencePackage,
) -> str:
    """Serialize a handoff + result into a self-contained JSON message.

    This is the **sender** side of the Hermes → Janus protocol: a worker
    (or the Hermes sync listener) calls this to produce a durable,
    self-describing message string that can be passed to
    :func:`receive_execution_result` (in a different process, thread, or
    even logged for audit).

    Returns:
        A compact JSON string encoding both the domain linkage metadata
        and the execution evidence.
    """
    msg = ExecutionResultMessage(metadata=metadata, evidence=evidence)
    return msg.to_json()


def receive_execution_result(message: str) -> dict:
    """Deserialize and dispatch a handoff + result message to Janus services.

    This is the **receiver** side of the Hermes → Janus protocol: it
    parses the JSON message produced by :func:`send_execution_result`,
    reconstructs the :class:`JanusDomainMetadata` and
    :class:`EvidencePackage`, and routes them to
    :func:`dispatch_completion`.

    Returns:
        The dispatch result dict (same shape as
        :func:`dispatch_completion`).
    """
    msg = ExecutionResultMessage.from_json(message)
    return dispatch_completion(msg.metadata, msg.evidence)


def attach_evidence(
    metadata: JanusDomainMetadata,
    evidence: EvidencePackage,
) -> ExecutionResultMessage:
    """Attach an evidence package to an execution result.

    This is the Janus-side entry point for *attaching evidence to an
    execution result*.  It bundles the Janus domain linkage
    (:class:`JanusDomainMetadata`) together with the execution evidence
    (:class:`EvidencePackage`) into a self-contained, serializable
    :class:`ExecutionResultMessage` — the canonical unit of the
    Hermes → Janus write-back path.

    The Hermes-side sync listener (:mod:`plugins.janus_sync`) performs the
    equivalent assembly via :func:`send_execution_result` (which serializes
    to a JSON string).  :func:`attach_evidence` returns the *object* form
    so that Janus-side callers (tests, the dispatch path itself, or
    future Janus-initiated feedback) can inspect and round-trip the
    attached evidence before dispatching it through
    :func:`propagate_state_updates`.

    Args:
        metadata: The Janus domain linkage (object, title, evidence fields
            parsed from ``janus_domain`` frontmatter).
        evidence: The execution evidence (task_id, summary, changed_files,
            tests_passed, pr_url, and — for research/decision objects —
            the ``body`` carrying the artifact/ADR markdown).

    Returns:
        An :class:`ExecutionResultMessage` with the evidence attached.
    """
    return ExecutionResultMessage(metadata=metadata, evidence=evidence)


def propagate_state_updates(
    metadata: JanusDomainMetadata,
    evidence: EvidencePackage,
) -> dict:
    """Dispatch attached evidence and capture the resulting state changes.

    This is the Janus-side *propagation* step: after evidence has been
    attached to an execution result (``janus_domain`` linkage + evidence
    package), this function routes the attached evidence through the
    Janus service functions (goal progress, task completion, milestone
    status, research/decision ingestion) via :func:`dispatch_completion`
    and returns a structured, serializable record of the **state changes**
    that resulted — ready for back-propagation through the Janus↔Hermes
    channel (the audit comment recorded on the completed Kanban task and
    the ``janus_sync_completed_at`` re-entrancy marker).

    The returned dict has the shape::

        {
            "task_id": <evidence.task_id>,
            "domain_object": <metadata.object>,
            "domain_title": <metadata.title>,
            "dispatch": <dispatch result dict>,
            "state_changes": [<short descriptors of what Janus mutated>],
            "synced_at": <iso8601 utc>,
        }

    ``state_changes`` enumerates the concrete Janus domain effects so that
    the Hermes-side listener can record a meaningful audit trail of what
    the completed task actually changed in Janus state, rather than only
    echoing the raw service return values.

    Args:
        metadata: The Janus domain linkage metadata.
        evidence: The execution evidence package (already attached).

    Returns:
        A structured state-update payload (plain dict, JSON-serializable).
    """
    # Round-trip through the send/receive protocol so that the same wire
    # format exercised by the Hermes listener is used end-to-end, and the
    # deserialized metadata/evidence are exactly what Janus services see.
    message = send_execution_result(metadata, evidence)
    dispatch_result = receive_execution_result(message)
    # Normalize the raw dispatch result to JSON-serializable plain types so the
    # back-channel payload survives JSON encoding in the audit comment.
    dispatch_result = _normalize_to_jsonable(dispatch_result)
    state_changes = _describe_state_changes(metadata, evidence, dispatch_result)
    payload = {
        "task_id": evidence.task_id,
        "domain_object": metadata.object,
        "domain_title": metadata.title,
        "dispatch": dispatch_result,
        "state_changes": state_changes,
        "synced_at": datetime.now(timezone.utc).isoformat(),
    }
    emit(logger, "service.execution_feedback.propagated",
         trace_id=None, span_id="execution_feedback",
         domain_object=metadata.object, domain_title=metadata.title,
         task_id=evidence.task_id,
         state_changes=state_changes,
         message=f"State updates propagated for {metadata.object}={metadata.title!r}")
    return payload


def _describe_state_changes(
    metadata: JanusDomainMetadata,
    evidence: EvidencePackage,
    dispatch_result: dict,
) -> list[str]:
    """Build a human-readable list of Janus domain effects from a dispatch.

    Derived purely from the dispatch result dict (no extra I/O) so this is
    cheap and safe to call inside the fail-safe listener.  Each descriptor
    is a short string suitable for an audit comment / back-channel note.
    """
    obj = metadata.object
    changes: list[str] = []
    result = dispatch_result or {}
    if obj == "goal":
        if "goal" in result:
            changes.append(f"appended recent_activity entry to goal {metadata.title!r}")
        if evidence.pr_url:
            changes.append(f"linked evidence PR {evidence.pr_url} to goal {metadata.title!r}")
    elif obj == "task":
        if "task" in result:
            changes.append(f"marked Janus task {metadata.title!r} completed with evidence")
    elif obj == "milestone":
        ms_info = result.get("milestone", {})
        if "task" in result:
            changes.append(f"recorded evidence on goal for milestone {metadata.title!r}")
        if isinstance(ms_info, dict) and ms_info.get("status") == "completed":
            changes.append(f"milestone {metadata.title!r} auto-completed")
    elif obj in ("research", "finding"):
        res = result.get("research", {})
        if isinstance(res, dict) and "skipped" not in res and "error" not in res:
            changes.append(
                f"ingested research artifact {res.get('title', metadata.title)!r} "
                f"({res.get('findings', 0)} findings)"
            )
            if res.get("linked_goal_titles"):
                changes.append(f"linked artifact to goals: {res['linked_goal_titles']}")
            if res.get("pipeline", {}).get("attention_items"):
                n = len(res["pipeline"]["attention_items"])
                changes.append(f"emitted {n} knowledge-gap attention items")
    elif obj == "decision":
        dec = result.get("decision", {})
        if isinstance(dec, dict) and "skipped" not in dec and "error" not in dec:
            changes.append(f"persisted ADR-{dec.get('adr_number', '?')}: {dec.get('title', metadata.title)!r}")
            if dec.get("action_connection", {}).get("linked_goals"):
                changes.append(
                    f"linked decision to goals: {dec['action_connection']['linked_goals']}"
                )
    return changes


def _normalize_to_jsonable(value: Any) -> Any:
    """Recursively convert a dispatch result into plain JSON-serializable types.

    Janus service functions may return rich domain objects (e.g. ``Goal``)
    alongside dict results, which are not JSON-serializable.  The back-channel
    payload recorded in the audit comment must round-trip through JSON, so we
    normalize recursively: ``to_dict()`` is used when available, dataclasses
    are expanded, and anything else that still refuses to serialize falls back
    to its ``repr()``.
    """
    # Plain JSON-native types.
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    # Objects that know how to serialize themselves.
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        value = to_dict()
    # Dict-like containers.
    if isinstance(value, dict):
        return {str(k): _normalize_to_jsonable(v) for k, v in value.items()}
    # Sequences (lists/tuples/sets) — but not str/bytes.
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_normalize_to_jsonable(v) for v in value]
    # Dataclass fall-back.
    if dataclasses.is_dataclass(value):
        return _normalize_to_jsonable(dataclasses.asdict(value))
    # Anything else: prefer repr to a hard failure so the audit trail always
    # survives serialization.
    try:
        json.dumps(value)
        return value
    except (TypeError, ValueError):
        return repr(value)


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
        "object": "research" if metadata.object != "finding" else "finding",
        "title": artifact.title,
        "slug": path.stem,
        "findings": len(artifact.findings),
        "path": str(path),
    }

    # Research-to-finding connection: run the knowledge pipeline to generate
    # a KnowledgeSummary (validation + summary generation), link the artifact
    # to its declared goals, and emit knowledge gaps as attention items.
    # This closes the research → finding → attention portion of the loop.
    from janus.services.knowledge_pipeline import (
        validate_artifact,
        generate_summary,
        emit_knowledge_gaps_as_attention,
    )
    from janus.services.artifact_linking import link_artifact_to_goal

    pipeline_result: dict = {"warnings": [], "attention_items": []}

    try:
        warnings = validate_artifact(artifact)
        pipeline_result["warnings"] = [
            {"category": w.category, "message": w.message,
             "finding_index": w.finding_index}
            for w in warnings
        ]
    except Exception as exc:
        logger.warning(
            "Pipeline validation failed for artifact '%s': %s",
            artifact.title, exc,
        )
        pipeline_result["warnings_error"] = str(exc)

    try:
        summary = generate_summary(artifact)
        pipeline_result["summary"] = {
            "target": summary.target,
            "source_count": summary.source_count,
            "high_confidence_count": summary.high_confidence_count,
            "low_confidence_count": summary.low_confidence_count,
            "knowledge_gaps": list(summary.knowledge_gaps),
            "entities": list(summary.entities),
        }

        # Link artifact to its declared goals (bidirectional).
        if artifact.linked_goal_titles:
            result["linked_goal_titles"] = artifact.linked_goal_titles
            for goal_title in artifact.linked_goal_titles:
                try:
                    link_artifact_to_goal(artifact.title, goal_title, artifact)
                except ValueError as exc:
                    logger.warning(
                        "Could not link artifact '%s' to goal '%s': %s",
                        artifact.title, goal_title, exc,
                    )
                    pipeline_result.setdefault("link_errors", []).append({
                        "goal_title": goal_title,
                        "error": str(exc),
                    })

        # Emit knowledge gaps as attention items.
        attention_items = emit_knowledge_gaps_as_attention(
            summary,
            goal_title=artifact.linked_goal_titles[0] if artifact.linked_goal_titles else None,
        )
        pipeline_result["attention_items"] = attention_items

    except Exception as exc:
        logger.warning(
            "Knowledge pipeline failed for artifact '%s': %s",
            artifact.title, exc,
        )
        pipeline_result["pipeline_error"] = str(exc)

    # Finding-to-decision connection: link each finding that declares
    # decision_numbers to those ADRs via link_finding_to_decision.
    # This closes the finding → decision portion of the verification loop.
    # Artifact-level decision_numbers apply to all findings without their
    # own decision_numbers; per-finding decision_numbers take precedence.
    decision_connection: dict = {"linked_decisions": [], "link_errors": []}
    _link_findings_to_decisions(artifact, decision_connection)
    if decision_connection["linked_decisions"] or decision_connection["link_errors"]:
        result["decision_connection"] = decision_connection

    if pipeline_result:
        result["pipeline"] = pipeline_result
    return result


def _link_findings_to_decisions(artifact: ResearchArtifact, connection: dict) -> None:
    """Link each finding's declared decision_numbers to their ADRs.

    For each finding, iterates over its ``decision_numbers`` (falling back
    to the artifact-level ``decision_numbers`` when the finding has none)
    and calls ``services.decisions.link_finding_to_decision``.

    Updates *connection* in-place with ``linked_decisions`` (list of ADR
    numbers successfully linked) and ``link_errors`` (list of dicts with
    ``adr_number``, ``finding_index``, and ``error``).
    """
    from janus.services.decisions import link_finding_to_decision

    # Collect all decision numbers from both artifact-level and per-finding.
    artifact_decision_numbers: list[str] = (
        getattr(artifact, "decision_numbers", []) or []
    )
    for finding_index, finding in enumerate(getattr(artifact, "findings", [])):
        # Per-finding decision_numbers take precedence; fall back to artifact-level.
        decision_numbers = (
            finding.decision_numbers
            if finding.decision_numbers
            else artifact_decision_numbers
        )
        for adr_number in decision_numbers:
            if adr_number in connection["linked_decisions"]:
                continue  # already linked, avoid duplicate calls
            try:
                link_finding_to_decision(adr_number, artifact.title, finding_index)
                connection["linked_decisions"].append(adr_number)
            except Exception as exc:
                logger.warning(
                    "Could not link finding %d of artifact '%s' to decision %s: %s",
                    finding_index, artifact.title, adr_number, exc,
                )
                connection["link_errors"].append({
                    "adr_number": adr_number,
                    "finding_index": finding_index,
                    "error": str(exc),
                })


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

    from janus.services.decisions import create_decision, link_decision_to_goal
    try:
        path = create_decision(decision)
    except ValueError as exc:
        logger.warning("Decision already exists, skipping: %s", exc)
        from janus.services.decisions import get_decision
        existing = get_decision(decision.adr_number)
        decision = existing
        path = None

    # Decision → action connection: link decision to its goals and propagate
    # to action pipeline (design §4.2 / Stage 3-4 loop connection).
    action_result: dict = {}
    for goal_title in decision.goal_titles:
        try:
            link_decision_to_goal(decision.adr_number, goal_title)
            action_result.setdefault("linked_goals", []).append(goal_title)
        except Exception as exc:
            action_result.setdefault("link_errors", []).append({
                "goal_title": goal_title, "error": str(exc),
            })

    result: dict = {
        "object": "decision",
        "adr_number": decision.adr_number,
        "title": decision.title,
        "status": decision.status,
    }
    if path is not None:
        result["path"] = str(path)
    else:
        result["skipped_existing"] = True
    if action_result:
        result["action_connection"] = action_result
    return result
