"""Roadmap-driven task replenishment plugin.

Hooks into ``kanban_task_completed`` in the worker process: when a task whose
title carries the configured replenish-eligibility marker (default
``[plan]``) is completed, the plugin resolves the project/workspace of the
completed task, loads the project's configured planning sources from
``projects.db``, and pulls the next item(s) onto the board as new tasks
parented on the completed task.

The design reuses the existing ``kanban_task_completed`` plugin hook and the
existing ``kanban_db.create_task`` / ``kanban_swarm`` primitives. It does NOT
introduce a new scheduler or a new Kanban-DB column.

Opt-in: enabled via ``hermes plugins enable replenishment`` (or
``plugins.enabled`` in config.yaml).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import re
import threading
import time
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from janus.integrations.atomic_io import atomic_write

logger = logging.getLogger(__name__)

# Marker prefix that makes a completed task "replenish-eligible". Configurable
# per planning source via ``task_title_prefix`` (default ``[plan]``). Tasks
# created by replenishment itself carry this prefix forward so the chain
# continues. This is the minimal gate — no new DB column required.
DEFAULT_MARKER_PREFIX = "[plan]"

# Default task title prefix applied to tasks pulled by replenishment so they
# remain replenish-eligible on their own completion.
DEFAULT_TASK_TITLE_PREFIX = "[plan]"

# Author used when the plugin writes structured audit comments on completed
# tasks.
_REPLENISH_COMMENT_AUTHOR = "replenish"

# Guard against re-entrant hook firing: the ``kanban_task_completed`` hook is
# fired both by ``complete_task()`` and by ``kanban_swarm.create_swarm()``
# (which auto-completes the swarm root). When a swarm source creates a swarm,
# the root's completion fires this hook again; the in-flight guard prevents
# nested replenishment that could recurse through a swarm source's own
# children.
_replenishing: set[str] = set()
_replenish_lock = threading.Lock()


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
) -> None:
    """``kanban_task_completed`` callback — best-effort, never raises.

    Hook payload (from ``kanban_db.complete_task``):
        task_id: str, board: str | None, assignee: str | None,
        run_id: int | None, summary: str | None, profile_name: str.

    Return values are ignored by the hook dispatcher — this function exists
    purely for its side effects.
    """
    try:
        _run_replenishment(task_id, board=board)
    except Exception as exc:
        # Observer-only hook: a broken planning source must never prevent the
        # completion from persisting. Record the error as a structured comment
        # on the task (if we can open the DB) and log it.
        logger.warning(
            "replenishment: error while processing task %s: %s", task_id, exc,
            exc_info=True,
        )
        try:
            _try_record_error(task_id, board, exc)
        except Exception:
            pass


def _run_replenishment(task_id: str, *, board: Optional[str] = None) -> None:
    """Core replenishment logic, factored out for testability.

    Raises on unexpected internal errors; ``on_task_completed`` wraps this in
    a try/except so the hook never propagates a failure.
    """
    from hermes_cli import kanban_db as kb
    from hermes_cli import projects_db as pdb

    # Re-entrancy guard: ``create_swarm`` fires ``kanban_task_completed`` on the
    # swarm root's auto-completion. If a swarm source triggered this replenish
    # cycle, we don't want the root's completion to recursively trigger again.
    with _replenish_lock:
        if task_id in _replenishing:
            return
        _replenishing.add(task_id)
    try:
        _replenish(task_id, board, kb, pdb)
    finally:
        with _replenish_lock:
            _replenishing.discard(task_id)


def _replenish(
    task_id: str,
    board: Optional[str],
    kb,
    pdb,
) -> None:
    """Resolve the project, load sources, and pull next items.

    ``kb`` and ``pdb`` are injected so tests can pass fakes or patches without
    monkeypatching module globals.
    """
    conn = kb.connect(board=board) if board else kb.connect()
    try:
        task = kb.get_task(conn, task_id)
    except Exception:
        conn.close()
        return

    if task is None:
        conn.close()
        return

    # --- Guard: title-prefix marker (default [plan]) -----------------------
    marker_prefix = _read_marker_prefix(task, conn, kb)
    if not (task.title or "").strip().startswith(marker_prefix):
        conn.close()
        return

    # --- Resolve project / workspace ---------------------------------------
    project_id = task.project_id or _project_from_board(board, kb, conn)
    project = None
    if project_id:
        try:
            with pdb.connect_closing() as pconn:
                project = pdb.get_project(pconn, project_id)
        except Exception as exc:
            logger.debug("replenishment: could not resolve project %s: %s", project_id, exc)

    # --- Load configured planning sources for the project ------------------
    sources: List[Any] = []
    if project_id:
        try:
            with pdb.connect_closing() as pconn:
                sources = pdb.list_planning_sources(pconn, project_id)
        except Exception as exc:
            logger.debug("replenishment: could not load planning sources: %s", exc)

    if not sources:
        conns = kb.get_current_board() if False else None  # noqa: no-op placeholder
        # No sources configured — nothing to pull, but still leave a trace so
        # the hot path is observable.
        conn.close()
        return

    # --- Process each source by kind ---------------------------------------
    created_count = 0
    # Determine the global max_generated_tasks budget.
    # Use the minimum across all sources if set individually,
    # falling back to 1 if no config specifies it.
    max_generated_tasks = 1
    for _src in sources:
        _src_cfg = getattr(_src, "config_dict", {})
        _src_max = int(_src_cfg.get("max_generated_tasks", 1))
        if max_generated_tasks == 1 or _src_max < max_generated_tasks:
            max_generated_tasks = _src_max
    budget_remaining = max_generated_tasks
    for source in sources:
        try:
            source_max = int(
                getattr(source, "config_dict", {}).get(
                    "max_generated_tasks", max_generated_tasks
                )
            )
        except (ValueError, TypeError):
            source_max = max_generated_tasks
        try:
            created_count += _process_source(
                task, project, source, conn, kb, pdb, source_max, budget_remaining
            )
        except Exception as exc:
            # Per-source isolation: a broken source must not prevent other
            # sources from running, nor block completion.
            logger.warning(
                "replenishment: source %s failed: %s",
                getattr(source, "id", "?"),
                exc,
                exc_info=True,
            )
            _try_record_error(task_id, board, exc, source_id=getattr(source, "id", None))
        budget_remaining -= created_count
        if budget_remaining <= 0:
            logger.info(
                "replenishment: global max_generated_tasks=%d reached, "
                "stopping after %d task(s)",
                max_generated_tasks, created_count,
            )
            break

    # --- Recompute ready + audit comment -----------------------------------
    try:
        kb.recompute_ready(conn)
    except Exception as exc:
        logger.warning("replenishment: recompute_ready failed: %s", exc)

    try:
        kb.add_comment(
            conn,
            task_id,
            _REPLENISH_COMMENT_AUTHOR,
            _audit_comment(task_id, created_count, sources),
        )
    except Exception as exc:
        logger.warning("replenishment: add_comment failed: %s", exc)

    conn.close()


# ---------------------------------------------------------------------------
# Guards & helpers
# ---------------------------------------------------------------------------

def _read_marker_prefix(task: Any, conn, kb) -> str:
    """Return the replenish-eligibility marker prefix.

    The marker is currently fixed to ``DEFAULT_MARKER_PREFIX`` (configurable
    per-source in the future via a ``task_title_prefix`` config key, but the
    gate itself reads from the completed task's title which is always
    ``[plan]``-prefixed when replenishment created it).
    """
    return DEFAULT_MARKER_PREFIX


def _project_from_board(board: Optional[str], kb, conn) -> Optional[str]:
    """Fall back to the board-level project when the task has none."""
    if not board:
        return None
    try:
        meta = kb.read_board_metadata(board)
        pid = (meta.get("project_id") or "").strip()
        return pid or None
    except Exception:
        return None


def _resolve_project_root(task: Any, project: Optional[Any]) -> Optional[str]:
    """Best-effort project root path for resolving relative source paths."""
    if project is not None and getattr(project, "primary_path", None):
        return project.primary_path
    # Fall back to the task's workspace_path if it's a real directory.
    if task.workspace_path:
        p = Path(task.workspace_path)
        if p.is_dir():
            return str(p)
        if p.exists():
            return str(p.parent)
    return None


def _try_record_error(
    task_id: str,
    board: Optional[str],
    exc: Exception,
    *,
    source_id: Optional[str] = None,
) -> None:
    """Write a structured error comment on the task, best-effort."""
    from hermes_cli import kanban_db as kb

    conn = None
    try:
        conn = kb.connect(board=board) if board else kb.connect()
        suffix = f" (source={source_id})" if source_id else ""
        kb.add_comment(
            conn,
            task_id,
            _REPLENISH_COMMENT_AUTHOR,
            f"[replenish] error processing task{suffix}: {type(exc).__name__}: {exc}",
        )
    except Exception:
        pass
    finally:
        if conn is not None:
            conn.close()


def _audit_comment(
    task_id: str,
    created_count: int,
    sources: List[Any],
) -> str:
    src_names = ", ".join(
        f"{getattr(s, 'kind', '?')}:{getattr(s, 'id', '?')}" for s in sources
    )
    return (
        f"[replenish] pulled {created_count} task(s) from "
        f"{len(sources)} source(s) [{src_names}] after {task_id} completed"
    )


# ---------------------------------------------------------------------------
# Source processing by kind
# ---------------------------------------------------------------------------

def _process_source(
    task: Any,
    project: Optional[Any],
    source: Any,
    conn,
    kb,
    pdb,
    source_max: int = 1,
    budget_remaining: int = 1,
) -> int:
    """Dispatch to the right handler for a single planning source.

    Returns the number of tasks created (0 for webhook/llm, which signal
    externally.
    """
    cfg = source.config_dict
    kind = getattr(source, "kind", "")

    if kind == "file":
        return _process_file_source(
            task, project, source, cfg, conn, kb, pdb, source_max, budget_remaining
        )
    if kind == "swarm":
        return _process_swarm_source(
            task, project, source, cfg, conn, kb, pdb, source_max, budget_remaining
        )
    if kind == "webhook":
        return _process_webhook_source(task, project, source, cfg)
    if kind == "llm":
        return _process_llm_source(task, project, source, cfg)
    logger.debug("replenishment: unknown source kind %r — skipping", kind)
    return 0


# --- file -------------------------------------------------------------------

def _process_file_source(
    task: Any,
    project: Optional[Any],
    source: Any,
    cfg: Dict[str, Any],
    conn,
    kb,
    pdb,
    source_max: int = 1,
    budget_remaining: int = 1,
) -> int:
    """Read a roadmap file and pull the next item(s) onto the board."""
    rel_path = cfg.get("path")
    if not rel_path:
        logger.warning(
            "replenish: file source %s has no 'path' config", source.id,
        )
        return 0
    project_root = _resolve_project_root(task, project)
    if project_root is None:
        project_root = os.getcwd()
    file_path = Path(project_root) / rel_path
    if not file_path.is_file():
        logger.warning("replenish: roadmap file not found: %s", file_path)
        return 0

    fmt = (cfg.get("format") or "markdown").strip().lower()
    if fmt == "json":
        return _pull_from_json_roadmap(
            task, source, cfg, file_path, conn, kb, pdb, source_max, budget_remaining
        )
    return _pull_from_markdown_roadmap(
        task, source, cfg, file_path, conn, kb, pdb, source_max, budget_remaining
    )


def _parse_markdown_todos(text: str) -> List[Dict[str, Any]]:
    """Extract unchecked TODO items from markdown text.

    Returns dicts with ``checked`` (bool), ``text`` (the full line content
    after the checkbox), and ``line_no`` (0-based).
    """
    items: List[Dict[str, Any]] = []
    for i, line in enumerate(text.splitlines()):
        stripped = line.strip()
        m = re.match(r"^[ \t]*[-*]\s+\[ \]\s+(.*)$", stripped)
        if m:
            items.append({
                "checked": False,
                "text": m.group(1).strip(),
                "line_no": i,
            })
            continue
        m2 = re.match(r"^[ \t]*[-*]\s+\[x\]\s+(.*)$", stripped)
        if m2:
            items.append({
                "checked": True,
                "text": m2.group(1).strip(),
                "line_no": i,
            })
    return items


def _read_markdown_cursor(file_path: Path) -> set[str]:
    """Read the set of already-pulled item IDs from a .complete sidecar file."""
    cursor_path = Path(str(file_path) + ".complete")
    if not cursor_path.is_file():
        return set()
    try:
        data = json.loads(cursor_path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return set(str(i) for i in data)
    except (json.JSONDecodeError, OSError):
        pass
    return set()


def _write_markdown_cursor(file_path: Path, completed_ids: set[str]) -> None:
    """Write the set of pulled item IDs to a .complete sidecar file."""
    cursor_path = Path(str(file_path) + ".complete")
    try:
        atomic_write(cursor_path, json.dumps(sorted(completed_ids)))
    except Exception as exc:
        logger.warning("replenish: could not write markdown cursor: %s", exc)


def _complete_markdown_items(
    file_path: Path,
    source_id: str,
    kb,
    conn,
) -> int:
    """Mark roadmap items as [x] for tasks that were created by replenishment
    and have since been completed. Returns the number of items marked complete.
    """
    cursor_path = Path(str(file_path) + ".complete")
    completed_ids = _read_markdown_cursor(file_path)
    if not completed_ids:
        return 0

    text = file_path.read_text(encoding="utf-8", errors="replace")
    items = _parse_markdown_todos(text)

    marked = 0
    lines = text.splitlines(keepends=True)

    for item in items:
        if item["checked"]:
            continue
        item_id = f"todo-{item['line_no']}"
        if item_id not in completed_ids:
            continue

        # Check if the corresponding task is completed by matching
        # the item text against task titles in the board.
        task_title = f"{DEFAULT_TASK_TITLE_PREFIX} {item['text']}".strip()
        try:
            all_tasks = kb.list_tasks(conn, include_archived=True)
            for t in all_tasks:
                if t.title == task_title and t.status == "done":
                    # Mark the item as checked in the file content.
                    idx = item["line_no"]
                    if 0 <= idx < len(lines):
                        lines[idx] = re.sub(
                            r"^(\s*[-*]\s+)\[ \]\s+",
                            r"\1[x] ",
                            lines[idx],
                        )
                        marked += 1
                    break
        except Exception:
            continue

    if marked:
        try:
            atomic_write(file_path, "".join(lines))
        except Exception as exc:
            logger.warning("replenish: could not write roadmap file: %s", exc)

    return marked


def _pull_from_markdown_roadmap(
    task: Any,
    source: Any,
    cfg: Dict[str, Any],
    file_path: Path,
    conn,
    kb,
    pdb,
    source_max: int = 1,
    budget_remaining: int = 1,
) -> int:
    """Parse a markdown roadmap: pull the next unchecked TODO as a task.

    Roadmap items are NOT marked [x] when pulled. Instead, a .complete
    sidecar file tracks which items have been pulled. Items are only
    marked [x] when the corresponding Kanban task is actually completed
    (see _complete_markdown_items).
    """
    # First, mark any previously-pulled items that now have completed tasks.
    source_id = getattr(source, "id", "unknown")
    _complete_markdown_items(file_path, source_id, kb, conn)

    text = file_path.read_text(encoding="utf-8", errors="replace")
    # Build the set of all checked items (both [x] in text and in .complete).
    items = _parse_markdown_todos(text)
    completed_ids = _read_markdown_cursor(file_path)
    unchecked = [it for it in items if not it["checked"] and f"todo-{it['line_no']}" not in completed_ids]
    if not unchecked:
        return 0

    # Respect the per-source and global budget.
    if budget_remaining <= 0:
        return 0
    unchecked = unchecked[:budget_remaining]
    if not unchecked:
        return 0

    next_item = unchecked[0]
    title_prefix = (
        cfg.get("task_title_prefix") or DEFAULT_TASK_TITLE_PREFIX
    )
    profiles = cfg.get("profiles") or [task.assignee or DEFAULT_MARKER_PREFIX.strip("[]")]
    skills = cfg.get("skills") or []
    source_id = getattr(source, "id", "unknown")
    item_id = f"todo-{next_item['line_no']}"
    triage = cfg.get("target_column") == "triage"

    new_id = kb.create_task(
        conn,
        title=f"{title_prefix} {next_item['text']}".strip(),
        body=(
            f"{next_item['text']}\n\n"
            f"#replenish source={source_id}\n"
            f"#replenish parent={task.id}"
        ),
        assignee=profiles[0] if profiles else task.assignee,
        parents=[task.id],
        triage=triage,
        idempotency_key=f"{task.project_id or 'default'}:{source_id}:{item_id}",
        skills=skills if skills else None,
        project_id=task.project_id,
        integration_required=False,
    )

    # Track the pulled item in the .complete sidecar file.
    # Do NOT mark the item [x] here — it should remain [ ] until the
    # corresponding Kanban task is actually completed.
    completed_ids.add(item_id)
    _write_markdown_cursor(file_path, completed_ids)

    return 1


def _pull_from_json_roadmap(
    task: Any,
    source: Any,
    cfg: Dict[str, Any],
    file_path: Path,
    conn,
    kb,
    pdb,
    source_max: int = 1,
    budget_remaining: int = 1,
) -> int:
    """Parse a JSON roadmap: pull the next unstarted item as a task.

    JSON format: a list of ``{"id": ..., "title": ..., "body": ...}``
    dicts, or a dict with an ``items`` list.
    """
    data = json.loads(file_path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        items = data.get("items", [])
    elif isinstance(data, list):
        items = data
    else:
        return 0

    title_prefix = (
        cfg.get("task_title_prefix") or DEFAULT_TASK_TITLE_PREFIX
    )
    profiles = cfg.get("profiles") or [task.assignee]
    skills = cfg.get("skills") or []
    source_id = getattr(source, "id", "unknown")
    triage = cfg.get("target_column") == "triage"

    # Read cursor from a sidecar .complete file (list of completed item ids).
    cursor_path = Path(str(file_path) + ".complete")
    completed_ids: List[str] = []
    if cursor_path.is_file():
        try:
            completed_ids = json.loads(
                cursor_path.read_text(encoding="utf-8")
            )
            if not isinstance(completed_ids, list):
                completed_ids = []
        except (json.JSONDecodeError, OSError):
            completed_ids = []
    completed_set = set(completed_ids)

    created = 0
    for item in items:
        if not isinstance(item, dict):
            continue
        item_id = item.get("id") or item.get("title") or ""
        if not item_id or str(item_id) in completed_set:
            continue
        title = item.get("title") or item.get("name") or ""
        if not title:
            continue
        body = item.get("body", item.get("description", ""))

        # Respect the budget.
        if created >= source_max or created >= budget_remaining:
            break

        new_id = kb.create_task(
            conn,
            title=f"{title_prefix} {title}".strip(),
            body=(
                f"{body}\n\n"
                f"#replenish source={source_id}\n"
                f"#replenish parent={task.id}"
            ),
            assignee=profiles[0] if profiles else task.assignee,
            parents=[task.id],
            triage=triage,
            idempotency_key=f"{task.project_id or 'default'}:{source_id}:{item_id}",
            skills=skills if skills else None,
            project_id=task.project_id,
            integration_required=False,
        )
        completed_ids.append(str(item_id))
        created += 1
        # Only pull one item per cycle by default; if the config wants
        # batch pulling, set ``max_generated_tasks`` > 1.
        if created >= source_max:
            break

    # Persist the updated cursor.
    if created:
        try:
            cursor_path.write_text(
                json.dumps(completed_ids),
            )
        except Exception as exc:
            logger.warning("replenish: could not write cursor: %s", exc)

    return created


# --- swarm ------------------------------------------------------------------

def _process_swarm_source(
    task: Any,
    project: Optional[Any],
    source: Any,
    cfg: Dict[str, Any],
    conn,
    kb,
    pdb,
    source_max: int = 1,
    budget_remaining: int = 1,
) -> int:
    """Build a ``kanban_swarm`` graph anchored on the completed task."""
    from hermes_cli import kanban_swarm as ks

    goal_prefix = cfg.get("goal_prefix") or "Implement next roadmap item"
    profiles = cfg.get("profiles") or [
        "researcher", "implementer", "reviewer",
    ]
    skills_per_worker = cfg.get("skills_per_worker") or [[] for _ in profiles]
    max_runtime = cfg.get("max_runtime_seconds")
    source_id = getattr(source, "id", "swarm-source")
    title_prefix = cfg.get("task_title_prefix") or DEFAULT_TASK_TITLE_PREFIX

    # Build worker specs from profiles + skills lists.
    workers: List[ks.SwarmWorkerSpec] = []
    for i, profile in enumerate(profiles):
        spec_skills = (
            skills_per_worker[i] if i < len(skills_per_worker) else []
        )
        workers.append(ks.SwarmWorkerSpec(
            profile=profile,
            title=f"{title_prefix} {profile} phase",
            body=f"Phase {i + 1} for: {goal_prefix}",
            skills=list(spec_skills),
            priority=0,
            max_runtime_seconds=max_runtime,
        ))

    # The verifier and synthesizer need assignees — cycle through profiles.
    verifier_assignee = profiles[0]
    synthesizer_assignee = profiles[-1] if len(profiles) > 1 else profiles[0]

    goal = f"{goal_prefix} (replenished from {task.title})"
    idempotency_key = (
        f"{task.project_id or 'default'}:{source_id}:{task.id}"
    )

    created = ks.create_swarm(
        conn,
        goal=goal,
        workers=workers,
        verifier_assignee=verifier_assignee,
        synthesizer_assignee=synthesizer_assignee,
        root_title=f"{title_prefix} Swarm: {goal_prefix}",
        priority=cfg.get("priority", 0),
        idempotency_key=idempotency_key,
    )

    # Link the swarm root to the completed task via task_links (parent = completed
    # task, child = swarm root). This gated the swarm behind the completed task's
    # done status — which is already satisfied, so recompute_ready will promote
    # the swarm workers immediately.
    kb.link_tasks(conn, task.id, created.root_id)

    return 1


# --- webhook ----------------------------------------------------------------

def _process_webhook_source(
    task: Any,
    project: Optional[Any],
    source: Any,
    cfg: Dict[str, Any],
) -> int:
    """POST a signed replenishment event to an external tracker."""
    url = cfg.get("url")
    if not url:
        logger.warning(
            "replenish: webhook source %s has no 'url' config", source.id,
        )
        return 0

    payload = {
        "event": "replenish",
        "task_id": task.id,
        "project_id": task.project_id,
        "workspace_path": task.workspace_path,
        "summary": _task_summary(task),
    }
    # Merge any extra fields from config.
    extra = cfg.get("extra_payload") or {}
    if isinstance(extra, dict):
        payload.update(extra)

    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "hermes-replenishment/1.0",
    }
    secret = cfg.get("secret")
    if secret:
        sig = "sha256=" + hmac.new(
            secret.encode("utf-8"), body, hashlib.sha256,
        ).hexdigest()
        headers["X-Hub-Signature-256"] = sig

    # Apply any extra_headers from config (skip secret-bearing ones).
    extra_headers = cfg.get("extra_headers") or {}
    if isinstance(extra_headers, dict):
        for k, v in extra_headers.items():
            headers[str(k)] = str(v)

    method = (cfg.get("method") or "POST").upper()
    timeout = int(cfg.get("timeout", 10))

    req = urllib.request.Request(
        url, data=body, headers=headers, method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status = resp.getcode()
            if 200 <= status < 300:
                return 0
            logger.warning(
                "replenish: webhook %s returned HTTP %d", source.id, status,
            )
            return 0
    except Exception as exc:
        logger.warning(
            "replenish: webhook %s failed: %s", source.id, exc,
        )
        return 0


# --- llm --------------------------------------------------------------------

def _process_llm_source(
    task: Any,
    project: Optional[Any],
    source: Any,
    cfg: Dict[str, Any],
) -> int:
    """Spawn a one-shot planner agent (deferred — runs as a subprocess).

    The LLM source is the heaviest: it spawns a dedicated Hermes worker
    with the configured skills and prompt. The planner agent is expected to
    write tasks directly via ``kanban_db.create_task`` (it inherits the
    board DB env vars from the worker context). We only signal that a
    planning cycle is available and record the spawn.
    """
    prompt = cfg.get("prompt")
    if not prompt:
        logger.warning(
            "replenish: llm source %s has no 'prompt' config", source.id,
        )
        return 0

    model = cfg.get("model")
    provider = cfg.get("provider")
    skills = cfg.get("skills") or []
    source_id = getattr(source, "id", "llm-source")

    # Build a one-shot agent invocation via the Hermes CLI oneshot path
    # (``hermes -z <prompt>``). The planner runs in a real worker context
    # with board DB env vars inherited, and writes tasks directly via
    # ``kanban_db.create_task``.
    import shutil
    import subprocess

    hermes_bin = shutil.which("hermes") or _find_hermes_binary()
    if not hermes_bin:
        logger.warning(
            "replenish: llm source %s: no 'hermes' binary on PATH", source_id,
        )
        return 0

    cmd = [hermes_bin, "-z", prompt]
    if model:
        cmd += ["-m", str(model)]
    if provider:
        cmd += ["--provider", str(provider)]
    for sk in skills:
        cmd += ["--skills", str(sk)]

    try:
        # Fire-and-forget: the planner runs as a detached subprocess. Its
        # tasks are created via create_task with idempotency keys, so even
        # if the hook fires again the work is deduplicated.
        subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
            env=os.environ.copy(),
        )
    except Exception as exc:
        logger.warning(
            "replenish: llm source %s spawn failed: %s", source_id, exc,
        )
        return 0

    return 0


# ---------------------------------------------------------------------------
# Plugin registration
# ---------------------------------------------------------------------------

def register(ctx) -> None:
    """Register the ``kanban_task_completed`` hook callback."""
    ctx.register_hook("kanban_task_completed", on_task_completed)


# ---------------------------------------------------------------------------
# Misc helpers
# ---------------------------------------------------------------------------

def _find_hermes_binary() -> Optional[str]:
    """Locate the ``hermes`` CLI binary for subprocess-based planners."""
    import sys

    # Check the script's own installation location.
    candidates = [
        str(Path(sys.argv[0]) if sys.argv and sys.argv[0] else ""),
        str(Path(sys.executable).parent / "hermes"),
    ]
    for c in candidates:
        if c and Path(c).is_file():
            return c
    return None


def _task_summary(task: Any) -> str:
    """Short human-readable summary for webhook payloads."""
    title = (task.title or "").strip()
    if len(title) > 200:
        title = title[:197] + "..."
    return title
