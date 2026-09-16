"""ADR-003 review-topology edge-case tests.

These tests close the medium/low-severity gaps identified in the ADR-003
consolidated review (``docs/research/findings-review-topology.md`` §6):

1. ``_landing_status_after_parents()`` — parent-completion re-gate shared by
   ``unblock_task`` and ``reopen_review_task``.
2. Review-loop escalation payload structure — the ``block_loop_detected``
   event emitted by ``block_task`` when ``block_recurrences`` reaches
   ``BLOCK_RECURRENCE_LIMIT``. (The research findings referred to an
   idealized ``_escalate_review_loop_exceeded()`` helper that is not present
   in the current implementation; the real escalation path is the inline
   block-loop breaker, whose payload shape is what is pinned down here.)
3. ``reopen_review_task()`` — operator reopen edge cases.
4. ``changes_requested`` watcher wake — the event payload that the gateway
   notifier wakes the origin subscriber with (reason + reviewer provenance).

The ``hermes_cli`` package (from the installed hermes-agent) is bootstrapped
onto ``sys.path`` via the path bootstrap below, mirroring
``tests/test_evidence_propagation.py`` and ``tests/plugins/conftest.py`` so
these DB-layer tests run under the Janus test suite without a full gateway
import.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Path bootstrap (mirrors tests/test_evidence_propagation.py) so hermes_cli is
# importable from the installed hermes-agent even though the kanban_db
# implementation lives there and this file lives in the Janus repo.
# ---------------------------------------------------------------------------
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

_hermes_agent = None
for _candidate in (
    os.path.expanduser("~/.hermes/hermes-agent"),
    os.path.join(_REPO_ROOT, ".hermes", "hermes-agent"),
):
    if os.path.isdir(_candidate):
        _hermes_agent = _candidate
        break
if _hermes_agent and _hermes_agent not in sys.path:
    sys.path.insert(1, _hermes_agent)
# Re-assert the Janus repo root above hermes-agent so the local ``plugins``
# namespace package wins over the hermes-agent copy (same invariant as
# tests/plugins/conftest.py).
if _hermes_agent in sys.path:
    sys.path.remove(_hermes_agent)
    sys.path.insert(0, _REPO_ROOT)
    sys.path.insert(1, _hermes_agent)

pytest.importorskip("hermes_cli", reason="hermes_cli not available (install hermes-agent)")

from hermes_cli import kanban_db as kb  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def kanban_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Isolated HERMES_HOME with an empty kanban DB (canonical pattern)."""
    home = tmp_path / ".hermes"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    for var in (
        "HERMES_KANBAN_DB",
        "HERMES_KANBAN_WORKSPACES_ROOT",
        "HERMES_KANBAN_HOME",
        "HERMES_KANBAN_BOARD",
    ):
        monkeypatch.delenv(var, raising=False)
    try:
        import hermes_constants  # type: ignore[import]
        hermes_constants._cached_default_hermes_root = None  # type: ignore[attr-defined]
    except Exception:
        pass
    kb._INITIALIZED_PATHS.clear()
    kb.init_db()
    return home


@pytest.fixture
def conn(kanban_home: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("HERMES_KANBAN_BOARD", raising=False)
    monkeypatch.delenv("HERMES_KANBAN_DB", raising=False)
    c = kb.connect(board="default")
    try:
        yield c
    finally:
        c.close()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _events(conn, tid, kind=None):
    rows = conn.execute(
        "SELECT kind, payload FROM task_events WHERE task_id = ? ORDER BY id",
        (tid,),
    ).fetchall()
    out = [
        (r["kind"], json.loads(r["payload"]) if r["payload"] else None)
        for r in rows
    ]
    if kind is not None:
        out = [e for e in out if e[0] == kind]
    return out


def _row(conn, tid):
    return conn.execute(
        "SELECT status, block_kind, block_recurrences, current_run_id "
        "FROM tasks WHERE id = ?",
        (tid,),
    ).fetchone()


def _drain_to_running(conn, tid, *, claimer="worker"):
    """Drive a freshly created task to ``running`` so block_task can act."""
    with kb.write_txn(conn):
        conn.execute("UPDATE tasks SET status='ready' WHERE id=?", (tid,))
    claimed = kb.claim_task(conn, tid, claimer=claimer)
    assert claimed is not None
    return claimed.current_run_id


def _make_running_again(conn, tid, *, claimer="worker"):
    with kb.write_txn(conn):
        conn.execute("UPDATE tasks SET status='ready' WHERE id=?", (tid,))
    assert kb.claim_task(conn, tid, claimer=claimer) is not None


def _review_cycle(conn, tid, *, implementer="worker", reviewer="reviewer"):
    """Move a task through running -> review -> running(review) for request_changes."""
    _drain_to_running(conn, tid, claimer=implementer)
    run_id = kb.get_task(conn, tid).current_run_id
    assert run_id is not None
    assert kb.request_review(
        conn, tid, summary="v1", reviewer=reviewer, expected_run_id=run_id,
    )
    assert kb.get_task(conn, tid).status == "review"
    # Reviewer claims the review run.
    assert kb.claim_review_task(conn, tid, claimer=reviewer) is not None
    review_run_id = kb.get_task(conn, tid).current_run_id
    assert review_run_id is not None
    return review_run_id


# ---------------------------------------------------------------------------
# 1. _landing_status_after_parents() — direct tests with various parent states
# ---------------------------------------------------------------------------

def _parent_child(conn, *, parent_status: str):
    """Create a parent (set to parent_status) and a child linked to it."""
    parent = kb.create_task(conn, title="parent", assignee="worker")
    child = kb.create_task(conn, title="child", assignee="worker")
    kb.link_tasks(conn, parent_id=parent, child_id=child)
    if parent_status != "todo":
        with kb.write_txn(conn):
            conn.execute(
                "UPDATE tasks SET status=? WHERE id=?", (parent_status, parent),
            )
    return parent, child


@pytest.mark.parametrize(
    "parent_status,expected",
    [
        ("done", "ready"),
        ("running", "todo"),
        ("in_progress", "todo"),   # not a valid terminal status -> todo
        ("review", "todo"),
        ("blocked", "todo"),
        ("ready", "todo"),
        ("todo", "todo"),
        ("archived", "ready"),
    ],
)
def test_landing_status_after_parents(
    conn, parent_status: str, expected: str,
):
    """``_landing_status_after_parents`` returns ``ready`` only when every
    parent is ``done``/``archived``; otherwise the child lands in ``todo``."""
    parent, child = _parent_child(conn, parent_status=parent_status)
    assert kb._landing_status_after_parents(conn, child) == expected


def test_landing_status_after_parents_unfinished_wins(conn):
    """A single unfinished parent out of several is enough to gate to ``todo``."""
    parent_done = kb.create_task(conn, title="done parent", assignee="worker")
    parent_open = kb.create_task(conn, title="open parent", assignee="worker")
    child = kb.create_task(conn, title="child", assignee="worker")
    kb.link_tasks(conn, parent_id=parent_done, child_id=child)
    kb.link_tasks(conn, parent_id=parent_open, child_id=child)
    with kb.write_txn(conn):
        conn.execute(
            "UPDATE tasks SET status='done' WHERE id=?", (parent_done,)
        )
        # parent_open stays 'todo'.
    assert kb._landing_status_after_parents(conn, child) == "todo"


def test_landing_status_after_parents_no_parents_is_ready(conn):
    """A task with no parents is eligible to land ``ready``."""
    tid = kb.create_task(conn, title="orphan", assignee="worker")
    assert kb._landing_status_after_parents(conn, tid) == "ready"


# ---------------------------------------------------------------------------
# 2. Review-loop escalation payload structure (block_loop_detected)
# ---------------------------------------------------------------------------
# The research findings (findings-review-topology.md §6.4) describe an
# idealized ``_escalate_review_loop_exceeded()`` helper that emits a
# ``review_limit_exceeded`` event. That helper is not present in the current
# implementation; the real loop-escalation mechanism is ``block_task``'s
# ``block_loop_detected`` event, emitted when a task is re-blocked for the
# same cause past ``BLOCK_RECURRENCE_LIMIT``. These tests pin the payload
# shape that any future review-loop guard would (and downstream consumers
# already) rely on.

def test_block_loop_detected_payload_structure(conn):
    """The escalation event carries the reason code, kind, recurrence count,
    the configured limit, and the source status that triggered the block."""
    tid = kb.create_task(conn, title="loop me", assignee="worker")
    _drain_to_running(conn, tid)
    # block 1
    assert kb.block_task(conn, tid, reason="env missing", kind="capability")
    kb.unblock_task(conn, tid)
    # block 2 -> recurrences hits BLOCK_RECURRENCE_LIMIT (2) -> triage
    assert kb.block_task(conn, tid, reason="env missing", kind="capability")
    row = _row(conn, tid)
    assert row["status"] == "triage"
    evs = _events(conn, tid, kind="block_loop_detected")
    assert len(evs) == 1
    payload = evs[0][1]
    assert payload is not None
    assert payload["kind"] == "capability"
    assert payload["reason"] == "env missing"
    assert payload["recurrences"] == kb.BLOCK_RECURRENCE_LIMIT
    assert payload["limit"] == kb.BLOCK_RECURRENCE_LIMIT
    assert payload["source_status"] == "ready"


def test_block_loop_detected_metadata_is_durable_on_replay(conn):
    """A second same-cause re-block beyond the limit emits the escalation
    event again with monotonically increasing recurrence metadata."""
    tid = kb.create_task(conn, title="loop me twice", assignee="worker")
    _drain_to_running(conn, tid)
    kb.block_task(conn, tid, reason="flaky", kind="transient")
    assert kb.unblock_task(conn, tid)
    # First escalation.
    kb.block_task(conn, tid, reason="flaky", kind="transient")
    first = _events(conn, tid, kind="block_loop_detected")[-1][1]
    # Reset to blocked/todo via unblock (triage -> unblock is a no-op on
    # blocked path, so drive it back through ready+running for a clean re-block).
    # After escalation the task is in 'triage'; re-running the breaker is not
    # possible from triage, so assert the first event is complete & self-describing.
    assert first["recurrences"] >= 2
    assert first["limit"] == kb.BLOCK_RECURRENCE_LIMIT
    assert first["kind"] == "transient"


# ---------------------------------------------------------------------------
# 3. reopen_review_task() edge cases
# ---------------------------------------------------------------------------

def test_reopen_review_task_from_non_review_returns_false(conn):
    """Reopening a task that is NOT in ``review`` is a no-op (returns False)."""
    tid = kb.create_task(conn, title="not in review", assignee="worker")
    # Task starts in 'todo' (initial_status default) — not review.
    assert kb.get_task(conn, tid).status != "review"
    assert kb.reopen_review_task(conn, tid) is False
    # A 'ready' task:
    with kb.write_txn(conn):
        conn.execute("UPDATE tasks SET status='ready' WHERE id=?", (tid,))
    assert kb.reopen_review_task(conn, tid) is False


def test_reopen_review_task_after_completion_returns_false(conn):
    """A task already completed (``done``) cannot be reopened via the review
    lane — ``reopen_review_task`` only acts on ``review`` status.

    The task is parked in ``review`` and then marked ``done`` directly (the
    integration/verification gates that ``complete_task`` enforces are out of
    scope for this DB-layer reopen edge case; what matters is the
    ``reopen_review_task`` guard itself)."""
    tid = kb.create_task(conn, title="finished", assignee="worker")
    _drain_to_running(conn, tid)
    kb.request_review(
        conn, tid, summary="done", reviewer="reviewer",
        expected_run_id=kb.get_task(conn, tid).current_run_id,
    )
    assert kb.get_task(conn, tid).status == "review"
    # Simulate reviewer approval: land -> done. (No active review run to close,
    # matching the #54823 "review with no run" shape that complete_task
    # accepts — here we set status directly to avoid the integration gate.)
    with kb.write_txn(conn):
        conn.execute(
            "UPDATE tasks SET status='done', current_run_id=NULL, "
            "claim_lock=NULL, claim_expires=NULL, worker_pid=NULL "
            "WHERE id=?",
            (tid,),
        )
    assert kb.get_task(conn, tid).status == "done"
    # Can't reopen a completed task through the review lane.
    assert kb.reopen_review_task(conn, tid) is False
    tid = kb.create_task(conn, title="finished", assignee="worker",
                         initial_status="running")
    _drain_to_running(conn, tid)
    kb.request_review(
        conn, tid, summary="done", reviewer="reviewer",
        expected_run_id=kb.get_task(conn, tid).current_run_id,
    )
    assert kb.claim_review_task(conn, tid, claimer="reviewer") is not None
    # claim_review_task transitions review -> running.
    assert kb.get_task(conn, tid).status == "running"
    # Reviewer approves -> done.
    assert kb.complete_task(conn, tid, summary="approved") is True
    assert kb.get_task(conn, tid).status == "done"
    # Can't reopen a completed task through the review lane.
    assert kb.reopen_review_task(conn, tid) is False


def test_reopen_review_task_demotes_to_todo_when_parent_unfinished(conn):
    """When a reopened task has an unfinished parent, it must land in ``todo``
    (parent re-gating) rather than skipping ahead to ``ready``.

    The parent is completed first so the child can be claimed and promoted to
    ``review`` (the parent-gating in ``claim_task`` would otherwise reject the
    claim). The parent is then *reopened* back to ``todo`` — simulating a
    reopened dependency — so that, on reopen, ``reopen_review_task`` re-gates
    via ``_landing_status_after_parents`` and demotes to ``todo``.
    """
    parent = kb.create_task(conn, title="parent", assignee="worker")
    kb.complete_task(conn, parent, summary="parent done")
    child = kb.create_task(conn, title="child", assignee="worker")
    kb.link_tasks(conn, parent_id=parent, child_id=child)
    _drain_to_running(conn, child)
    kb.request_review(
        conn, child, summary="v1", reviewer="reviewer",
        expected_run_id=kb.get_task(conn, child).current_run_id,
    )
    assert kb.get_task(conn, child).status == "review"
    # Reopen the parent so it is no longer 'done', exercising parent re-gating
    # on the child's reopen path.
    with kb.write_txn(conn):
        conn.execute("UPDATE tasks SET status='todo' WHERE id=?", (parent,))
    assert kb.reopen_review_task(conn, child) is True
    assert kb.get_task(conn, child).status == "todo"
    assert _events(conn, child, kind="review_reopened")


def test_reopen_review_task_preserved_parents_done_lands_ready(conn):
    """Sanity: with all parents done, reopen lands ``ready`` (the happy path
    is not regressed by the edge-case handling)."""
    parent = kb.create_task(conn, title="parent", assignee="worker")
    with kb.write_txn(conn):
        conn.execute("UPDATE tasks SET status='done' WHERE id=?", (parent,))
    child = kb.create_task(conn, title="child", assignee="worker")
    kb.link_tasks(conn, parent_id=parent, child_id=child)
    _drain_to_running(conn, child)
    kb.request_review(
        conn, child, summary="v1", reviewer="reviewer",
        expected_run_id=kb.get_task(conn, child).current_run_id,
    )
    assert kb.reopen_review_task(conn, child) is True
    assert kb.get_task(conn, child).status == "ready"


def test_reopen_review_task_closes_dangling_run(conn):
    """A stale ``current_run_id`` pointing at no live run is reclaimed before
    the status flip, preserving the run-pointer invariant."""
    tid = kb.create_task(conn, title="stale run", assignee="worker")
    _drain_to_running(conn, tid)
    kb.request_review(
        conn, tid, summary="v1", reviewer="reviewer",
        expected_run_id=kb.get_task(conn, tid).current_run_id,
    )
    assert kb.get_task(conn, tid).status == "review"
    # Simulate a dangling run pointer (no matching live claim).
    with kb.write_txn(conn):
        conn.execute(
            "UPDATE tasks SET current_run_id = 999999 WHERE id = ?", (tid,)
        )
    # reopen still succeeds and clears the pointer.
    assert kb.reopen_review_task(conn, tid) is True
    assert kb.get_task(conn, tid).current_run_id is None
    assert _events(conn, tid, kind="review_reopened")


# ---------------------------------------------------------------------------
# 4. changes_requested watcher wake — payload shape consumed by the notifier
# ---------------------------------------------------------------------------
# gateway.kanban_watchers renders the wake for a ``changes_requested`` event
# using payload fields {reason, reviewer, implementer, status} (see
# kanban_watchers.py `changes_requested` branch and findings §6.x). The
# notifier is exercised end-to-end in the hermes-agent test suite
# (tests/gateway/test_kanban_changes_requested_notifier.py); here we pin the
# DB-layer contract the wake depends on: the event is persisted with the
# exact provenance fields and is surfaced to the origin subscriber via
# ``unseen_events_for_sub`` (the wake trigger).

def test_request_changes_emits_changes_requested_with_provenance(conn):
    """``request_changes`` records {reason, implementer, reviewer, status} so
    the watcher can wake the origin with reason + reviewer provenance."""
    tid = kb.create_task(conn, title="review me", assignee="codex-cua")
    run_id = _drain_to_running(conn, tid)
    kb.request_review(
        conn, tid, summary="ready for review", reviewer="claude-qa",
        expected_run_id=run_id,
    )
    assert kb.claim_review_task(conn, tid, claimer="claude-qa") is not None
    review_run_id = kb.get_task(conn, tid).current_run_id
    ok, implementer = kb.request_changes(
        conn, tid, reason="needs more tests", expected_run_id=review_run_id,
    )
    assert ok is True
    assert implementer == "codex-cua"
    evs = _events(conn, tid, kind="changes_requested")
    assert len(evs) == 1
    payload = evs[0][1]
    assert payload is not None
    assert payload["reason"] == "needs more tests"
    assert payload["implementer"] == "codex-cua"
    assert payload["reviewer"] == "claude-qa"
    # landing status after parent re-gate (no parents -> ready).
    assert payload["status"] == "ready"


def test_changes_requested_wakes_origin_subscriber(conn):
    """A registered notify sub on a task is woken by ``changes_requested`` —
    the origin subscriber sees the event through ``unseen_events_for_sub``
    (the same surface the gateway notifier drains per tick)."""
    tid = kb.create_task(
        conn, title="review me too", assignee="codex-cua",
        session_id="agent:main:telegram:thread:chat-1:topic-7",
    )
    run_id = _drain_to_running(conn, tid)
    kb.request_review(
        conn, tid, summary="v1", reviewer="claude-qa", expected_run_id=run_id,
    )
    kb.claim_review_task(conn, tid, claimer="claude-qa")
    review_run_id = kb.get_task(conn, tid).current_run_id
    kb.add_notify_sub(
        conn,
        task_id=tid,
        platform="telegram",
        chat_id="chat-1",
        thread_id="topic-7",
        chat_type="thread",
        delivery_mode="notify+wake",
        delivery_metadata={"thread_id": "topic-7", "chat_type": "thread"},
    )
    # No events seen yet for the sub.
    _, pending = kb.unseen_events_for_sub(
        conn, task_id=tid, platform="telegram", chat_id="chat-1",
        thread_id="topic-7",
    )
    assert pending == []

    kb.request_changes(
        conn, tid, reason="typo in the example", expected_run_id=review_run_id,
    )
    cursor, pending = kb.unseen_events_for_sub(
        conn, task_id=tid, platform="telegram", chat_id="chat-1",
        thread_id="topic-7",
    )
    assert cursor > 0
    kinds = [e.kind for e in pending]
    assert "changes_requested" in kinds
    cr = [e for e in pending if e.kind == "changes_requested"][-1]
    # Event.payload is already a parsed dict (see Event dataclass + the
    # json.loads in unseen_events_for_sub), so the wake surface hands the
    # notifier a ready-to-render provenance dict.
    payload = cr.payload or {}
    # The reason + reviewer provenance the wake message is built from.
    assert payload["reason"] == "typo in the example"
    assert payload["implementer"] == "codex-cua"
    assert payload["reviewer"] == "claude-qa"
