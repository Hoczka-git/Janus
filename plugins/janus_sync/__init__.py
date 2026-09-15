"""Janus execution-feedback sync listener (Hermes → Janus).

Hooks ``kanban_task_completed`` in the worker process, mirroring the pattern
established by the replenishment plugin (``plugins/replenishment``).  When a
completed Kanban task carries ``janus_domain`` frontmatter — the sole runtime
bridge linking a Hermes task to a Janus domain object — the listener:

1. Reads the completed task body (``kanban_db.get_task``).
2. Parses the ``janus_domain`` frontmatter via the Janus-side
   ``execution_feedback.parse_janus_domain_metadata``.
3. If metadata is present, assembles an :class:`EvidencePackage`-compatible
   dict from the completion payload, the closing run's metadata, and a
   best-effort ``git diff --name-only`` over the task workspace.
4. Dispatches to ``execution_feedback.dispatch_completion`` which routes to
   the correct Janus service function (``goals.update_goal_progress``,
   ``tasks.complete_janus_task``, ``milestones.update_milestone_status``).
5. Records an audit comment on the completed task describing the outcome.

Directionality: Hermes → Janus.  Janus never calls back into Hermes.

Fail-safe and idempotent by design:

* The listener is fully best-effort — a broken Janus file, a parse error, or
  a service exception is logged to the task comment thread and never
  propagates to the hook dispatcher (a misbehaving observer must not break the
  board-state transition).  The Kanban task is already ``done`` by the time
  this hook fires, so a sync failure is a secondary concern.
* The Janus service functions are themselves idempotent (they update by title
  lookup, not append).  A re-entrant ``kanban_task_completed`` firing for the
  same task is a no-op.  An additional in-body ``janus_sync_completed_at``
  guard prevents reprocessing across runs — see
  :func:`kanban_db.janus_sync_already_processed`.

Opt-in: enabled via ``hermes plugins enable janus_sync``.
"""
from __future__ import annotations

import logging
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


# Per-task serialization lock for concurrent hook invocations.  Two workers
# firing ``kanban_task_completed`` for the same Janus-linked task at the same
# time would otherwise both pass the fast-path ``janus_sync_already_processed``
# read and then race to dispatch + stamp the marker, causing Janus
# ``protected_write`` to raise ``DataConflictError`` (a file-level hash race,
# not a logical one — the service functions are idempotent by title/task_id).
# A threading.Lock keyed by task_id serializes dispatch so only the winning
# thread touches Janus storage; the other observes the stamped marker and
# returns ``already_synced``.  This keeps the marker applied *after* a
# successful dispatch (preserving the failure-retry contract from design §5.1)
# while making concurrent dispatch safe.
_sync_locks: dict[str, threading.Lock] = {}
_sync_locks_guard = threading.Lock()


def _task_sync_lock(task_id: str) -> threading.Lock:
    """Return (creating if needed) the per-task sync lock."""
    with _sync_locks_guard:
        lock = _sync_locks.get(task_id)
        if lock is None:
            lock = threading.Lock()
            _sync_locks[task_id] = lock
        return lock


# ---------------------------------------------------------------------------
# Per-task re-entrancy guard (in-process concurrency)
# ---------------------------------------------------------------------------
# ``janus_sync_already_processed`` (SELECT) and ``mark_janus_sync_completed``
# (UPDATE) are not atomic with each other, so two concurrent hook firings for
# the same task can both pass the "already processed" check before either
# stamps the marker — a classic TOCTOU race.  SQLite's ``BEGIN IMMEDIATE``
# write lock would serialize the writes, but the *read-check* happens before
# the write txn opens, so it doesn't close the gap.
#
# We close it with a process-local ``threading.Lock`` per ``task_id``: the
# first thread to enter acquires the lock, performs the full read-check-dispatch-
# stamp cycle, and only then releases so the second thread — running the
# same ``_run_sync`` — observes the stamped marker and returns
# ``already_synced`` instead of re-dispatching.
#
# This covers *in-process* concurrency (the dispatcher may fan out multiple
# worker hooks into the same observer host).  Cross-process re-entrancy is
# already guarded by ``janus_sync_already_processed`` reading the DB marker,
# which persists across worker restarts — this lock simply makes the
# same-process race-safe so the marker is observed exactly once per task.
_janus_sync_locks: dict[str, threading.Lock] = {}
_janus_sync_locks_guard = threading.Lock()


def _sync_lock_for(task_id: str) -> threading.Lock:
    """Return (creating if necessary) the in-process lock for *task_id*."""
    with _janus_sync_locks_guard:
        lock = _janus_sync_locks.get(task_id)
        if lock is None:
            lock = threading.Lock()
            _janus_sync_locks[task_id] = lock
        return lock


# ---------------------------------------------------------------------------
# Hook callback
# ---------------------------------------------------------------------------
def on_task_completed(
    task_id: str,
    *,
    board: Optional[str] = None,
    assignee: Optional[str] = None,
    run_id: Optional[int] = None,
    summary: Optional[str] = None,
    profile_name: Optional[str] = None,
    **_kwargs: Any,
) -> Optional[dict]:
    """``kanban_task_completed`` callback — best-effort, never raises.

    Hook payload (from ``kanban_db.complete_task``):

        task_id: str, board: str | None, assignee: str | None,
        run_id: int | None, summary: str | None, profile_name: str.

    Return values are ignored by the hook dispatcher — this function exists
    purely for its side effects.  It returns the sync result dict (for tests)
    or ``None`` when the task carries no Janus linkage.
    """
    try:
        return _run_sync(task_id, board=board, run_id=run_id, summary=summary)
    except Exception as exc:  # noqa: BLE001 — observer must never break completion
        logger.warning(
            "janus_sync: error while processing task %s: %s",
            task_id, exc, exc_info=True,
        )
        _try_record_error(task_id, board, exc)
        # Phase 1 — emit a structured janus_sync_failed event (design §6.5)
        # so the dispatcher / dashboard surfaces the failure alongside the
        # audit comment.
        _try_append_sync_failed_event(task_id, board, exc)
        return None


def _run_sync(
    task_id: str,
    *,
    board: Optional[str] = None,
    run_id: Optional[int] = None,
    summary: Optional[str] = None,
) -> Optional[dict]:
    """Core sync logic, factored out for testability.

    Raises on unexpected internal errors; ``on_task_completed`` wraps this in
    try/except so the hook never propagates a failure.

    Returns the dispatch result dict, or ``None`` when the task has no Janus
    linkage (no ``janus_domain`` frontmatter).

    Concurrency: a per-task process lock serializes concurrent hook firings
    for the *same* task_id, closing the TOCTOU gap between
    ``janus_sync_already_processed`` (read) and ``mark_janus_sync_completed``
    (write).  The second concurrent caller observes the stamped marker and
    returns ``already_synced`` instead of re-dispatching.
    """
    lock = _sync_lock_for(task_id)
    with lock:
        from hermes_cli import kanban_db as kb

        conn = kb.connect(board=board) if board else kb.connect()
        try:
        task = kb.get_task(conn, task_id)

        if task is None:
            return None

        body = task.body or ""

        # Fast-path re-entrancy guard. The marker is read directly from the DB
        # so it survives across worker runs.
        if kb.janus_sync_already_processed(conn, task_id):
            return {"status": "already_synced", "task_id": task_id}

        # Parse janus_domain frontmatter (Janus-side helper).
        try:
            metadata = _parse_janus_domain(body)
        except ValueError as exc:
            _try_record_error(task_id, board, exc, detail="parse_janus_domain")
            return {
                "status": "parse_error",
                "task_id": task_id,
                "error": str(exc),
            }

        if metadata is None:
            # No Janus linkage — nothing to sync (common completion path untouched).
            return {"status": "no_linkage", "task_id": task_id}

        # Build the evidence package from the completion payload + run metadata.
        evidence = _build_evidence(task, run_id, summary, conn, kb)

        # Serialize concurrent hook invocations for the same task. The initial
        # janus_sync_already_processed() check is not atomic with the marker
        # write, so two concurrent workers could otherwise both dispatch.
        with _task_sync_lock(task_id):
            # Re-check under the lock: another thread may have completed the
            # sync while this thread was waiting.
            if kb.janus_sync_already_processed(conn, task_id):
                return {"status": "already_synced", "task_id": task_id}

            # Dispatch to the Janus service function (idempotent) and capture
            # the resulting state changes for back-propagation through the
            # channel.
            propagation = _dispatch_to_janus(metadata, evidence)

            # Stamp the marker only after successful dispatch. If dispatch
            # fails, the marker remains absent and a later hook invocation can
            # retry the sync.
            kb.mark_janus_sync_completed(conn, task_id)

            # Record an audit comment on the completed task.
            _try_add_audit_comment(conn, kb, task_id, metadata, propagation)

        # Phase 1 — structured state-change events (design §6.1/§6.5).
        # The kanban_db mark_janus_sync_completed() emits a bare
        # ``janus_sync_completed`` event ({"synced_at": ts}).  We append a
        # richer ``janus_sync_succeeded`` event carrying the domain object,
        # title, and the concrete state_changes so downstream tasks / the
        # dispatcher can read what Janus actually mutated without parsing
        # audit comments.
        _try_append_sync_event(
            conn, kb, task_id, "janus_sync_succeeded",
            {
                "domain_object": metadata.object,
                "domain_title": metadata.title,
                "state_changes": propagation.get("state_changes", []),
                "synced_at": propagation.get("synced_at"),
            },
        )

        # ``dispatch`` preserves the raw service dispatch results (backward-
        # compatible shape: {"goal": ...} / {"task": ...} etc.) while the
        # top-level ``state_changes`` surfaces what Janus actually mutated —
        # the propagated state updates echoing back through the channel.
        return {
            "status": "synced",
            "task_id": task_id,
            "domain_object": metadata.object,
            "domain_title": metadata.title,
            "dispatch": propagation.get("dispatch", {}),
            "state_changes": propagation.get("state_changes", []),
            "synced_at": propagation.get("synced_at"),
        }
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# janus_domain parsing & evidence assembly
# ---------------------------------------------------------------------------
def _parse_janus_domain(body: str) -> Optional[Any]:
    """Parse ``janus_domain`` frontmatter using the Janus-side parser.

    Returns a ``JanusDomainMetadata`` instance or ``None``.  Re-raises
    ``ValueError`` for malformed frontmatter (the caller records it).
    """
    from janus.services.execution_feedback import parse_janus_domain_metadata
    return parse_janus_domain_metadata(body)


def _build_evidence(
    task: Any,
    run_id: Optional[int],
    summary: Optional[str],
    conn,
    kb,
) -> "EvidencePackage":
    """Assemble an :class:`EvidencePackage` for the Janus service functions.

    Evidence field sources (per design §4.5):

    * ``task_id``    — from the Kanban task itself.
    * ``summary``    — from the completion payload (or the run summary).
    * ``completed_at`` — UTC ISO-8601 timestamp at sync time.
    * ``changed_files`` — worker metadata (if reported) or a best-effort
      ``git diff --name-only`` over the task workspace.
    * ``tests_passed`` — worker metadata ``verification`` / ``tests_passed``
      flag, if reported by the closing run.
    * ``pr_url``    — worker metadata ``pr_url``, if the integration gate
      produced one.
    * ``janus_body`` — worker metadata ``janus_body``, a clean artifact/ADR
      body separate from Kanban metadata (design §7.3 Option A). Used in
      preference to ``body`` for research/finding/decision ingestion.
    * ``metric_updates`` — worker metadata ``metric_updates``: a declarative
      list of metric advancements for goal objects (design §6.2).
    """
    from janus.services.execution_feedback import EvidencePackage

    task_id = task.id
    changed_files: list[str] = []
    tests_passed = None
    pr_url = None
    janus_body = None
    metric_updates = None

    # The task body carries ``janus_domain`` frontmatter and — for
    # ``object: research|finding|decision`` — the full markdown artifact or
    # ADR that must be ingested into Janus storage (design spec §7.2/§7.3
    # Option B).  Pass it through so ``dispatch_completion`` can ingest it.
    body = task.body or ""

    # Try to enrich from the closing run's metadata.  If the run_id passed by
    # the hook doesn't resolve (e.g. a stale id in tests, or a task completed
    # without an explicit run), fall back to the task's current_run_id and
    # then its most recent run.
    run = None
    for candidate in (run_id, getattr(task, "current_run_id", None)):
        if candidate is None:
            continue
        try:
            r = kb.get_run(conn, int(candidate))
        except Exception:
            r = None
        # Only accept runs that actually belong to this task (guards against
        # stale / cross-task run ids, e.g. a hardcoded 1 in tests).
        if r is not None and getattr(r, "task_id", None) == task_id:
            run = r
            break
    if run is None:
        # Fall back to the most recent run for this task.
        try:
            row = conn.execute(
                "SELECT id FROM task_runs WHERE task_id = ? "
                "ORDER BY id DESC LIMIT 1",
                (task_id,),
            ).fetchone()
            if row is not None:
                run = kb.get_run(conn, int(row["id"]))
        except Exception:  # noqa: BLE001
            pass
    if run is not None and run.metadata:
        meta = run.metadata
        if meta.get("tests_passed") is not None:
            tests_passed = bool(meta["tests_passed"])
        if meta.get("pr_url"):
            pr_url = str(meta["pr_url"])
        cf = meta.get("changed_files")
        if isinstance(cf, list) and cf:
            changed_files = [str(f) for f in cf]
        # Design §6.2: declarative metric_updates from the worker.
        mu = meta.get("metric_updates")
        if isinstance(mu, list) and mu:
            metric_updates = [m for m in mu if isinstance(m, dict)]
        # Design §7.3 Option A: a clean janus_body separate from Kanban metadata.
        jb = meta.get("janus_body")
        if isinstance(jb, str) and jb.strip():
            janus_body = jb

    # Fall back to a workspace git diff for changed files.
    if not changed_files:
        changed_files = _workspace_changed_files(task)

    return EvidencePackage(
        task_id=task_id,
        summary=summary or "",
        completed_at=datetime.now(timezone.utc).isoformat(),
        changed_files=changed_files,
        tests_passed=tests_passed,
        pr_url=pr_url,
        body=body,
        janus_body=janus_body,
        metric_updates=metric_updates,
    )


def _workspace_changed_files(task: Any) -> list[str]:
    """Best-effort ``git diff --name-only`` for the task workspace.

    Returns an empty list on any failure — the listener is fail-safe and
    ``changed_files`` is informational evidence, not a completion gate.
    """
    ws = getattr(task, "workspace_path", None)
    if not ws:
        return []
    ws_path = Path(ws).expanduser()
    if not ws_path.is_dir():
        return []
    git = os.environ.get("GIT_EXECUTABLE", "git")
    target = _detect_target_branch(ws_path, git)
    if not target:
        # No remote / trunk branch configured (common in local test repos).
        # Fall back to diffing against the first commit so we still capture
        # the changed files for this workspace.
        base = _first_commit(ws_path, git)
    else:
        # Compare against the merge-base with the target to capture only this
        # task's commits, mirroring the integration contract's diff-stat intent.
        base = _run_git(ws_path, [git, "merge-base", "origin/" + target, "HEAD"])
    if not base:
        # No base to diff against (e.g. empty repo) — list nothing.
        return []
    args: list[str] = [git, "diff", "--name-only", "--diff-filter=AM", base, "HEAD"]
    try:
        out = _run_git(ws_path, args)
        if out:
            return [line.strip() for line in out.splitlines() if line.strip()]
    except Exception:  # noqa: BLE001
        return []
    return []


def _first_commit(ws_path: Path, git: str) -> Optional[str]:
    """Return the SHA of the first (root) commit in *ws_path*, or None."""
    try:
        out = _run_git(ws_path, [git, "rev-list", "--max-parents=0", "HEAD"])
    except Exception:  # noqa: BLE001
        return None
    return out.strip() or None


def _detect_target_branch(ws_path: Path, git: str) -> Optional[str]:
    """Resolve the repository's target (trunk) branch name via ``origin/HEAD``.

    Returns the branch name without the ``origin/`` prefix, or ``None`` when
    it cannot be determined (e.g. no remote configured).  Mirrors the
    resolution order in ``janus.git_sync.detect_target_branch``.
    """
    try:
        head = _run_git(ws_path, [git, "rev-parse", "--abbrev-ref", "origin/HEAD"])
    except Exception:  # noqa: BLE001
        return None
    if not head or head == "origin/HEAD":
        return None
    return head.split("/", 1)[1] if "/" in head else head


def _run_git(cwd: Path, args: list[str]) -> str:
    """Run a git command non-interactively. Returns stdout on success (``""``
    on any failure).  Mirrors ``janus.git_sync._git_out`` / ``web_git._git``
    fail-fast pattern (``GIT_TERMINAL_PROMPT=0``, stdin nulled).
    """
    import subprocess
    env = dict(os.environ)
    env["GIT_TERMINAL_PROMPT"] = "0"
    proc = subprocess.run(
        args, cwd=str(cwd),
        capture_output=True, text=True,
        encoding="utf-8", errors="replace",
        timeout=10, stdin=subprocess.DEVNULL, env=env,
    )
    return proc.stdout.strip() if proc.returncode == 0 else ""


def _dispatch_to_janus(metadata: Any, evidence: "EvidencePackage") -> dict:
    """Call the Janus-side execution-feedback dispatch + state propagation.

    ``metadata`` is a ``JanusDomainMetadata`` (has ``.object`` / ``.title``);
    ``evidence`` is an ``EvidencePackage`` dataclass.  ``dispatch_completion``
    serializes the evidence to a dict before passing it to the service
    functions.

    The handoff + result is routed through the
    :func:`send_execution_result` / :func:`receive_execution_result`
    protocol so that the Hermes → Janus wire format (JSON message
    encoding both the domain linkage metadata and the execution evidence)
    is exercised end-to-end.  ``receive_execution_result`` deserializes
    the message back into ``JanusDomainMetadata`` and ``EvidencePackage``
    and dispatches to the Janus service functions.

    The resulting Janus state changes are then captured via
    :func:`propagate_state_updates` — which dispatches the attached
    evidence and returns a structured, serializable record of what changed
    (goal recent_activity, task evidence, milestone completion, research
    ingestion, ADR persistence, etc.) — so they can be recorded in the
    audit comment and back-propagated through the Janus↔Hermes channel.
    """
    from janus.services.execution_feedback import (
        propagate_state_updates,
    )
    # propagate_state_updates round-trips through send/receive_execution_result
    # (exercising the wire protocol) and dispatches the attached evidence to
    # the Janus service functions, then captures the resulting state changes.
    payload = propagate_state_updates(metadata, evidence)
    # The payload is already plain JSON-serializable (dicts / strs); normalize
    # any object values with to_dict() for the audit comment as a safety net.
    return {
        key: (
            v.to_dict() if hasattr(v, "to_dict") else v
        )
        for key, v in payload.items()
    }


# ---------------------------------------------------------------------------
# Audit comment helpers (mirror replenishment's error/comment pattern)
# ---------------------------------------------------------------------------
_AUDIT_COMMENT_AUTHOR = "janus_sync"


def _try_add_audit_comment(conn, kb, task_id: str, metadata: Any,
                           dispatch_result: dict) -> None:
    """Record a structured audit comment on the completed task.

    The comment surfaces the Janus-side state changes that resulted from
    the sync (propagated back through the Janus↔Hermes channel) so the
    audit trail records *what changed*, not just the raw service return
    values.  ``dispatch_result`` is the structured payload produced by
    :func:`propagate_state_updates` and carries ``state_changes`` and
    ``synced_at``.
    """
    try:
        obj = getattr(metadata, "object", None)
        title = getattr(metadata, "title", None)
        state_changes = dispatch_result.get("state_changes", [])
        synced_at = dispatch_result.get("synced_at")
        change_summary = (
            "; ".join(state_changes) if state_changes else "(no domain state changes)"
        )
        summary = (
            f"Janus sync completed for {obj}={title!r}: {change_summary}"
        )
        if synced_at:
            summary += f" [synced_at={synced_at}]"
        kb.add_comment(conn, task_id, _AUDIT_COMMENT_AUTHOR, summary)
    except Exception as exc:  # noqa: BLE001
        logger.debug("janus_sync: add_comment failed: %s", exc)


def _try_record_error(
    task_id: str,
    board: Optional[str],
    exc: Exception,
    *,
    detail: Optional[str] = None,
    source_id: Optional[str] = None,
) -> None:
    """Write a structured error comment on the task, best-effort."""
    from hermes_cli import kanban_db as kb

    conn = None
    try:
        conn = kb.connect(board=board) if board else kb.connect()
        suffix = ""
        if detail:
            suffix += f" [{detail}]"
        if source_id:
            suffix += f" (source={source_id})"
        kb.add_comment(
            conn, task_id, _AUDIT_COMMENT_AUTHOR,
            f"[janus_sync] error processing task{suffix}: "
            f"{type(exc).__name__}: {exc}",
        )
    except Exception:  # noqa: BLE001
        pass
    finally:
        if conn is not None:
            conn.close()


# ---------------------------------------------------------------------------
# Structured sync events (design §6.1 / §6.5)
# ---------------------------------------------------------------------------
def _try_append_sync_event(
    conn, kb, task_id: str, kind: str, payload: dict,
) -> None:
    """Append a structured ``janus_sync_*`` task event, best-effort.

    ``mark_janus_sync_completed`` emits a bare ``janus_sync_completed`` event
    carrying only ``{"synced_at": ts}``.  These helpers append richer events
    (``janus_sync_succeeded`` / ``janus_sync_failed``) carrying the domain
    object, title, and concrete state_changes so downstream tasks and the
    dispatcher can read what Janus actually mutated without parsing audit
    comments.

    Called from within the already-open ``_run_sync`` txn context (the
    connection is already open).  For the failure path (called from
    ``on_task_completed``'s except handler) the connection is opened fresh
    via :func:`_try_append_sync_failed_event`.
    """
    try:
        kb._append_event(conn, task_id, kind, payload)
    except Exception as exc:  # noqa: BLE001
        logger.debug("janus_sync: _append_event(%s) failed: %s", kind, exc)


def _try_append_sync_failed_event(
    task_id: Optional[str], board: Optional[str], exc: Exception,
) -> None:
    """Append a ``janus_sync_failed`` task event, best-effort.

    Mirrors :func:`_try_record_error` for connection lifecycle: opens a
    connection to the same board as the sync attempt, appends the event,
    and never raises.
    """
    from hermes_cli import kanban_db as kb

    if not task_id:
        return
    conn = None
    try:
        conn = kb.connect(board=board) if board else kb.connect()
        kb._append_event(conn, task_id, "janus_sync_failed", {
            "error_type": type(exc).__name__,
            "error_message": str(exc),
            "detail": getattr(exc, "args", None),
        })
    except Exception as exc2:  # noqa: BLE001
        logger.debug("janus_sync: _append_event(janus_sync_failed) failed: %s", exc2)
    finally:
        if conn is not None:
            conn.close()


# ---------------------------------------------------------------------------
# Plugin registration
# ---------------------------------------------------------------------------

def register(ctx) -> None:
    """Register the ``kanban_task_completed`` hook callback.

    Wires :func:`on_task_completed` into the Hermes plugin lifecycle so that
    when a Kanban task is completed (after the write txn commits, per the
    kanban_db lifecycle-hook contract), the listener parses any
    ``janus_domain`` frontmatter and dispatches to the Janus service
    functions.

    The hook is observer-only: return values are ignored by the dispatcher,
    and :func:`on_task_completed` is fully best-effort — it never raises.
    """
    ctx.register_hook("kanban_task_completed", on_task_completed)
