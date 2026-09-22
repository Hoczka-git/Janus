"""Inbox service for Janus — CRUD and triage operations."""
from __future__ import annotations

import logging
import uuid
from datetime import datetime
from pathlib import Path

from janus._log import emit
from janus.models.inbox import InboxItem, TRIAGE_STATES
from janus.integrations.markdown_inbox import (
    INBOX_PATH as _INBOX_PATH_MOD,
    save_inbox_item,
    update_inbox_item,
    load_inbox_items,
)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
INBOX_PATH = PROJECT_ROOT / "data" / "inbox.md"

logger = logging.getLogger(__name__)


def add_inbox_item(
    captured_text: str,
    source: str = "manual",
    context: str = "",
    linked_goal_title: str = "",
    linked_research_title: str = "",
    inbox_id: str | None = None,
) -> InboxItem:
    """Validate, create, append to data/inbox.md, return it."""
    if not captured_text or not captured_text.strip():
        raise ValueError("captured_text must not be empty")
    if source not in ("telegram", "cli", "manual", "research", "email", "other"):
        raise ValueError(f"Invalid source: {source!r}")

    item_id = inbox_id if inbox_id else ("ix-" + uuid.uuid4().hex[:8])
    item = InboxItem(
        id=item_id,
        captured_text=captured_text.strip(),
        source=source,
        context=context.strip(),
        linked_goal_title=linked_goal_title.strip(),
        linked_research_title=linked_research_title.strip(),
    )
    save_inbox_item(item)

    emit(logger, "service.inbox.mutated",
         trace_id=None, span_id="service",
         operation="add", inbox_id=item_id,
         message=f"Inbox item '{item_id}' added")

    return item


def add_inbox_item_via_ingest(
    captured_text: str,
    source: str = "cli",
    context: str = "",
    linked_goal_title: str = "",
    linked_research_title: str = "",
) -> "IngestResult":
    """Construct an INBOX_CAPTURED ActivityRecord and route it through the
    canonical ADR-005 ingestion gate (``ingest_activities``).

    ``captured_text`` is passed as the record's ``captured_text`` field,
    which the gateway's ``_dispatch_inbox`` writes through ``atomic_io``.

    Returns the :class:`IngestResult` from the ingestion gate.
    """
    from datetime import datetime, timezone
    from janus.services.activity_ingest import (
        ActivityRecord,
        ActivityType,
        ingest_activities,
    )
    evidence = {}
    if context:
        evidence["context"] = context
    record = ActivityRecord(
        type=ActivityType.INBOX_CAPTURED,
        source=source,
        timestamp=datetime.now(timezone.utc),
        inbox_id=None,
        captured_text=captured_text,
        evidence=evidence,
    )
    return ingest_activities([record])[0]


def triage_item(inbox_id: str, triage_state: str, triage_note: str = "") -> InboxItem:
    """Set triage_state + triage_at + triage_note on an inbox item by id.

    Raises ValueError if not found, if already triaged (terminal state),
    or if triage_state is invalid. Returns updated InboxItem.
    """
    if triage_state not in TRIAGE_STATES:
        raise ValueError(f"Invalid triage_state: {triage_state!r}")

    items = load_inbox_items(path=INBOX_PATH)
    found = None
    for item in items:
        if item.id == inbox_id:
            found = item
            break

    if found is None:
        raise ValueError(f"Inbox item not found: {inbox_id}")

    if found.triage_state != "pending":
        raise ValueError(f"Inbox item {inbox_id} already triaged (state={found.triage_state!r})")

    found.triage_state = triage_state
    found.triage_note = triage_note.strip()
    found.triage_at = datetime.now()
    update_inbox_item(found)

    emit(logger, "service.inbox.mutated",
         trace_id=None, span_id="service",
         operation="triage", inbox_id=inbox_id,
         new_state=triage_state,
         message=f"Inbox item '{inbox_id}' triaged to {triage_state}")

    return found


def list_inbox_items(triage_state: str | None = None) -> list[InboxItem]:
    """Load all items; optional filter by triage_state."""
    items = load_inbox_items(path=INBOX_PATH)
    if triage_state is None:
        return items
    return [i for i in items if i.triage_state == triage_state]


def get_inbox_item(inbox_id: str) -> InboxItem:
    """Load single item by exact id. Raises ValueError if not found."""
    items = load_inbox_items(path=INBOX_PATH)
    for item in items:
        if item.id == inbox_id:
            return item
    raise ValueError(f"Inbox item not found: {inbox_id}")
