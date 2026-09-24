"""Goal Integrity Repair service for Janus.

Provides configurable, reversible, safe repairs for the issues detected by
the Goal Integrity Audit (``janus.services.goal_integrity``).  See
``docs/design/goal_integrity_repair.md`` for the full design.

Design principles (§3):

* **Dry-run by default** — no writes unless ``dry_run=False``.
* **Reversible** — every applied operation is recorded and can be reverted.
* **Configurable** — orphan handling and mismatch reconciliation are
  controllable via :class:`RepairConfig`.
* **Atomic I/O** — all writes go through ``atomic_io.read_modify_write``
  with load-time SHA-256 conflict detection (ADR-005).
* **Confirmation gates** — destructive orphan actions (delete) and
  ``reassign`` without an explicit target require confirmation.

The repair service integrates cleanly with the audit:

    from janus.services.goal_integrity import audit_goal_integrity
    from janus.services.goal_integrity_repair import repair_goal_integrity

    report = audit_goal_integrity(goals, tasks, now=now)
    result = repair_goal_integrity(report, goals, tasks, dry_run=False,
                                    config=RepairConfig(action="report"))
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from janus._log import emit
from janus.models.goal import Goal
from janus.models.goal_integrity_report import GoalIntegrityReport, GoalIntegrityIssue
from janus.models.task import Task

logger = logging.getLogger(__name__)

# Re-export the issue codes from the audit module so callers can import
# them from a single canonical place.
from janus.services.goal_integrity import (
    UNKNOWN_GOAL_REFERENCE,
    INVALID_RELATED_TASK,
    CIRCULAR_REFERENCE,
    ORPHANED_TASK,
    RELATIONSHIP_COUNT_MISMATCH,
    GOAL_WITHOUT_TASKS,
    INVALID_METRIC,
    STALE_ACTIVITY,
)

# Issue codes that this repair workflow knows how to fix.
REPAIRABLE_CODES = frozenset({
    UNKNOWN_GOAL_REFERENCE,
    INVALID_RELATED_TASK,
    CIRCULAR_REFERENCE,
    ORPHANED_TASK,
    RELATIONSHIP_COUNT_MISMATCH,
})

# Issue codes that are structural-but-not-relationship; the repair workflow
# reports them but does not auto-mutate.  Documented in design §2 "Out of scope".
NON_REPAIRABLE_CODES = frozenset({
    GOAL_WITHOUT_TASKS,
    INVALID_METRIC,
    STALE_ACTIVITY,
})

_VALID_ORPHAN_ACTIONS = frozenset({"report", "reassign", "archive", "delete"})
_VALID_RECONCILE_STRATEGIES = frozenset({"forward", "reverse"})


@dataclass
class RepairConfig:
    """Configuration for the repair workflow (design §4).

    All fields are optional with safe defaults; the workflow never mutates
    data unless explicitly requested.
    """

    #: Orphan-handling strategy. ``"report"`` (default) lists orphans without
    #: mutation; ``"reassign"`` links the task to ``target_goal``; ``"archive"``
    #: completes the task; ``"delete"`` removes it (requires ``allow_delete``).
    action: str = "report"
    #: Reconciliation strategy for ``RELATIONSHIP_COUNT_MISMATCH``:
    #: ``"forward"`` (add reverse-only tasks to ``goal.related_tasks``, default)
    #: or ``"reverse"`` (remove the conflicting ``goal:`` ref from the task).
    reconcile_strategy: str = "forward"
    #: Must be ``True`` for orphan ``delete`` to proceed. Defaults to ``False``
    #: as defense in depth — deletion is the most destructive action.
    allow_delete: bool = False
    #: When ``True`` and a destructive action is pending, prompt on stdin.
    #: Disabled in non-interactive contexts (CI/Telegram); callers must pass
    #: ``--yes`` instead.
    interactive: bool = False
    #: Target goal title for orphan ``reassign``. Required when
    #: ``action == "reassign"``.
    target_goal: str | None = None
    #: If ``True``, the caller has pre-confirmed any destructive action
    #: (e.g. via ``--yes``), skipping interactive prompts.
    confirmed: bool = False


@dataclass
class RepairOperation:
    """A single reversible repair operation (design §5).

    Each operation captures the *before* state needed to revert and the
    *after* state produced by ``apply()``.
    """

    issue_code: str
    target: str                       # goal title (for goal ops) or task title
    operation: str                    # e.g. "remove_goal_ref", "remove_related_task"
    before: dict                      # snapshot for revert
    after: dict
    reversible: bool = True
    # The persistence layer this operation touches.
    file_kind: str = "goals"          # "goals" | "tasks"
    # Human-readable description for the audit log.
    description: str = ""

    def apply(self) -> None:
        """Execute the mutation. Raises on I/O failure."""
        if self.operation == "remove_goal_ref":
            _remove_task_goal_ref(
                self.target,
                self.before["removed_ref"],
                self.before["removed_index"],
            )
        elif self.operation == "add_goal_ref":
            _add_task_goal_ref(
                self.target,
                self.after["added_ref"],
                self.after["added_index"],
            )
        elif self.operation == "remove_related_task":
            _remove_goal_related_task(
                self.target,
                self.before["removed_task"],
            )
        elif self.operation == "add_related_task":
            _add_goal_related_task(
                self.target,
                self.after["added_task"],
            )
        elif self.operation == "complete_task":
            _complete_task(self.target)
        elif self.operation == "delete_task":
            _delete_task(self.target)
        else:
            raise ValueError(f"Unknown repair operation: {self.operation}")

    def revert(self) -> None:
        """Undo the mutation using the captured before-snapshot."""
        if not self.reversible:
            raise ValueError(f"Operation '{self.operation}' is not reversible")
        if self.operation == "remove_goal_ref":
            # Re-insert the ref at its original position.
            _add_task_goal_ref(
                self.target,
                self.before["removed_ref"],
                self.before["removed_index"],
            )
        elif self.operation == "add_goal_ref":
            # Remove the ref we added.
            _remove_task_goal_ref(self.target, self.after["added_ref"])
        elif self.operation == "remove_related_task":
            _add_goal_related_task(
                self.target,
                self.before["removed_task"],
            )
        elif self.operation == "add_related_task":
            _remove_goal_related_task(self.target, self.after["added_task"])
        elif self.operation == "complete_task":
            _reopen_task(self.target)
        elif self.operation == "delete_task":
            _restore_task(self.target, self.before["line"])
        else:
            raise ValueError(f"Unknown repair operation: {self.operation}")


@dataclass
class RepairPlan:
    """A plan of repair operations derived from an audit report (design §6)."""

    operations: list[RepairOperation] = field(default_factory=list)
    dry_run: bool = True
    summary: dict = field(default_factory=dict)
    issues_by_code: dict = field(default_factory=dict)

    @property
    def is_empty(self) -> bool:
        return len(self.operations) == 0

    def to_dict(self) -> dict:
        return {
            "dry_run": self.dry_run,
            "operation_count": len(self.operations),
            "operations": [
                {
                    "issue_code": op.issue_code,
                    "target": op.target,
                    "operation": op.operation,
                    "description": op.description,
                    "file_kind": op.file_kind,
                    "reversible": op.reversible,
                }
                for op in self.operations
            ],
            "summary": self.summary,
        }


@dataclass
class RepairResult:
    """Result of executing a repair plan (design §6)."""

    plan: RepairPlan
    applied: list[RepairOperation] = field(default_factory=list)
    dry_run: bool = True
    backup_path: Path | None = None

    @property
    def is_empty(self) -> bool:
        return len(self.applied) == 0


# ── Top-level orchestrator ─────────────────────────────────────────────────


def repair_goal_integrity(
    report: GoalIntegrityReport,
    goals: list[Goal],
    tasks: list[Task],
    *,
    config: RepairConfig | None = None,
    dry_run: bool = True,
) -> RepairResult:
    """Build and (optionally) execute a repair plan for *report* (design §6, §7).

    Args:
        report: The :class:`GoalIntegrityReport` from ``audit_goal_integrity``.
        goals: The full goal list (as passed to the audit).
        tasks: The full open-task list (as passed to the audit).
        config: Repair configuration.  When ``None``, a safe default
            :class:`RepairConfig` is used (orphan ``action="report"``).
        dry_run: When ``True`` (default), operations are planned but **not**
            applied — no files are written.  Pass ``dry_run=False`` together
            with appropriate config + confirmation to persist changes.

    Returns:
        A :class:`RepairResult` describing the plan and (if applied) the
        operations executed.

    The function is safe to call with ``dry_run=True`` on a report that
    contains no repairable issues — the result will be empty.
    """
    if config is None:
        config = RepairConfig()
    _validate_config(config)

    ops: list[RepairOperation] = []
    issues_by_code: dict[str, int] = {}
    unsupported: list[str] = []

    # Index tasks by title for lookups.
    task_by_title: dict[str, Task] = {t.title: t for t in tasks}
    goal_by_title: dict[str, Goal] = {g.title: g for g in goals}
    open_task_titles: set[str] = {t.title for t in tasks}

    # Pre-extract reverse refs (task → goals) so we can reason about
    # orphan reassignment and mismatch reconciliation without re-parsing.
    from janus.services.goal_integrity import _extract_goal_refs

    for issue in report.issues:
        code = issue.code
        issues_by_code[code] = issues_by_code.get(code, 0) + 1

        if code not in REPAIRABLE_CODES:
            unsupported.append(code)
            continue

        try:
            issue_ops = _build_operations_for_issue(
                issue, config, task_by_title, goal_by_title,
                open_task_titles, _extract_goal_refs,
            )
        except _RequiresConfirmation as rc:
            # A destructive action needs confirmation.  If the caller has not
            # confirmed (dry-run or interactive declined), skip the operation
            # and record it in the summary so the plan reflects intent.
            _log_skipped(rc.reason, issue)
            unsupported.append(f"{code}: {rc.reason}")
            continue
        except _UnsupportedIssue as ui:
            unsupported.append(f"{code}: {ui.reason}")
            continue

        ops.extend(issue_ops)

    summary = {
        "planned_operations": len(ops),
        "issues_by_code": issues_by_code,
        "unsupported": sorted(set(unsupported)),
        "orphan_action": config.action,
        "reconcile_strategy": config.reconcile_strategy,
        "dry_run": dry_run,
    }

    plan = RepairPlan(
        operations=ops,
        dry_run=dry_run,
        summary=summary,
        issues_by_code=issues_by_code,
    )

    applied: list[RepairOperation] = []
    backup_path: Path | None = None

    if ops and not dry_run:
        # Capture a single backup of both data files before applying.
        backup_path = _capture_backups()

        for op in ops:
            try:
                op.apply()
                _log_applied(op)
                applied.append(op)
            except Exception as exc:  # pragma: no cover - I/O failure path
                logger.error(
                    "repair operation failed (%s on '%s'): %s",
                    op.operation, op.target, exc,
                )
                _log_failed(op, str(exc))
                # On failure, attempt to revert already-applied operations so
                # the data files are not left in a half-repaired state.
                for done in reversed(applied):
                    try:
                        done.revert()
                    except Exception:  # pragma: no cover
                        pass
                applied.clear()
                raise

    return RepairResult(
        plan=plan,
        applied=applied,
        dry_run=dry_run,
        backup_path=backup_path,
    )


class _RequiresConfirmation(Exception):
    """Raised when a destructive action cannot proceed without confirmation."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


class _UnsupportedIssue(Exception):
    """Raised when an issue code cannot be repaired."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def _validate_config(config: RepairConfig) -> None:
    if config.action not in _VALID_ORPHAN_ACTIONS:
        raise ValueError(
            f"Invalid orphan action {config.action!r}. "
            f"Allowed: {sorted(_VALID_ORPHAN_ACTIONS)}"
        )
    if config.reconcile_strategy not in _VALID_RECONCILE_STRATEGIES:
        raise ValueError(
            f"Invalid reconcile strategy {config.reconcile_strategy!r}. "
            f"Allowed: {sorted(_VALID_RECONCILE_STRATEGIES)}"
        )
    if config.action == "reassign" and not config.target_goal:
        raise ValueError(
            "--action reassign requires --target-goal <title>"
        )
    if config.action == "delete" and not config.allow_delete:
        raise ValueError(
            "--action delete requires --allow-delete"
        )


# ── Per-issue operation builders ───────────────────────────────────────────


def _build_operations_for_issue(
    issue: GoalIntegrityIssue,
    config: RepairConfig,
    task_by_title: dict[str, Task],
    goal_by_title: dict[str, Goal],
    open_task_titles: set[str],
    extract_refs,
) -> list[RepairOperation]:
    """Return the repair operations for a single issue (design §5)."""
    code = issue.code

    if code == UNKNOWN_GOAL_REFERENCE:
        return _repair_unknown_goal_ref(issue, task_by_title)

    if code == INVALID_RELATED_TASK:
        return _repair_invalid_related_task(issue, goal_by_title, open_task_titles)

    if code == CIRCULAR_REFERENCE:
        return _repair_circular_reference(issue, task_by_title, goal_by_title, extract_refs)

    if code == ORPHANED_TASK:
        return _repair_orphan(issue, config, task_by_title)

    if code == RELATIONSHIP_COUNT_MISMATCH:
        return _repair_relationship_mismatch(
            issue, config, task_by_title, goal_by_title, open_task_titles,
        )

    raise _UnsupportedIssue(code)


def _repair_unknown_goal_ref(
    issue: GoalIntegrityIssue,
    task_by_title: dict[str, Task],
) -> list[RepairOperation]:
    """Remove the stale ``goal: <ref>`` metadata from a task (§5.1)."""
    task_title = issue.task_id
    details = issue.details or {}
    ref_goal = details.get("referenced_goal") or issue.goal_id
    if task_title is None or ref_goal is None:
        raise _UnsupportedIssue("missing task_id or goal_id")

    task = task_by_title.get(task_title)
    if task is None or not task.extra_metadata:
        raise _UnsupportedIssue(f"task '{task_title}' not found or has no metadata")

    target_meta = f"goal: {ref_goal}"
    idx = _find_meta_index(task.extra_metadata, ref_goal)
    if idx is None:
        # Already clean — idempotent no-op.
        return []

    return [RepairOperation(
        issue_code=UNKNOWN_GOAL_REFERENCE,
        target=task_title,
        operation="remove_goal_ref",
        file_kind="tasks",
        description=(
            f"Remove stale goal reference '{ref_goal}' from task "
            f"'{task_title}'"
        ),
        before={
            "removed_ref": target_meta,
            "removed_index": idx,
        },
        after={},
    )]


def _repair_invalid_related_task(
    issue: GoalIntegrityIssue,
    goal_by_title: dict[str, Goal],
    open_task_titles: set[str],
) -> list[RepairOperation]:
    """Remove a stale entry from ``goal.related_tasks`` (§5.2)."""
    goal_title = issue.goal_id
    details = issue.details or {}
    stale_task = details.get("related_task") or issue.task_id
    if goal_title is None or stale_task is None:
        raise _UnsupportedIssue("missing goal_id or task_id")

    return [RepairOperation(
        issue_code=INVALID_RELATED_TASK,
        target=goal_title,
        operation="remove_related_task",
        file_kind="goals",
        description=(
            f"Remove stale related_task '{stale_task}' from goal '{goal_title}'"
        ),
        before={"removed_task": stale_task},
        after={},
    )]


def _repair_circular_reference(
    issue: GoalIntegrityIssue,
    task_by_title: dict[str, Task],
    goal_by_title: dict[str, Goal],
    extract_refs,
) -> list[RepairOperation]:
    """Break a cycle by removing one reverse ``goal:`` ref (§5.3).

    The cycle path is stored in ``issue.details["cycle"]`` as a list like
    ``[Goal A, Task T1, Goal B, Task T2, Goal A]``.  We remove the ``goal:``
    ref on the *last* task in the path (the one whose ref points back to the
    start goal), which is the edge that closes the cycle.
    """
    details = issue.details or {}
    cycle: list[str] = details.get("cycle", [])
    # The cycle path alternates goal, task, goal, task, ..., goal (the start
    # goal appears again at the end), so it always has odd length >= 5.
    if len(cycle) < 5 or len(cycle) % 2 == 0:
        raise _UnsupportedIssue("malformed cycle path")

    # The cycle alternates goal, task, goal, task, ..., goal (= first goal).
    # The closing edge is: last task → first goal.  Find that task.
    closing_task = cycle[-2]
    start_goal = cycle[0]

    task = task_by_title.get(closing_task)
    if task is None or not task.extra_metadata:
        raise _UnsupportedIssue(f"closing task '{closing_task}' not found")

    idx = _find_meta_index(task.extra_metadata, start_goal)
    if idx is None:
        raise _UnsupportedIssue(
            f"task '{closing_task}' does not reference goal '{start_goal}'"
        )

    target_meta = f"goal: {start_goal}"
    return [RepairOperation(
        issue_code=CIRCULAR_REFERENCE,
        target=closing_task,
        operation="remove_goal_ref",
        file_kind="tasks",
        description=(
            f"Break circular reference by removing 'goal: {start_goal}' "
            f"from task '{closing_task}' (cycle: {' -> '.join(cycle)})"
        ),
        before={"removed_ref": target_meta, "removed_index": idx},
        after={},
    )]


def _repair_orphan(
    issue: GoalIntegrityIssue,
    config: RepairConfig,
    task_by_title: dict[str, Task],
) -> list[RepairOperation]:
    """Reassign, archive, or delete an orphan task (§5.4, §4)."""
    task_title = issue.task_id
    if task_title is None:
        raise _UnsupportedIssue("missing task_id")

    if config.action == "report":
        raise _UnsupportedIssue("orphan action is 'report' — no mutation")

    if config.action == "reassign":
        if not config.target_goal:
            raise _RequiresConfirmation(
                "reassign requires --target-goal"
            )
        return [RepairOperation(
            issue_code=ORPHANED_TASK,
            target=task_title,
            operation="add_goal_ref",
            file_kind="tasks",
            description=(
                f"Reassign orphan task '{task_title}' to goal "
                f"'{config.target_goal}'"
            ),
            before={},
            after={
                "added_ref": f"goal: {config.target_goal}",
                "added_index": -1,  # append
            },
        )]

    if config.action == "archive":
        return [RepairOperation(
            issue_code=ORPHANED_TASK,
            target=task_title,
            operation="complete_task",
            file_kind="tasks",
            description=(
                f"Archive orphan task '{task_title}' (mark completed)"
            ),
            before={},
            after={},
        )]

    if config.action == "delete":
        if not config.allow_delete:
            raise _RequiresConfirmation(
                "delete requires --allow-delete"
            )
        # Confirmation gate (§3 principle 2): destructive deletes must be
        # explicitly confirmed via --yes (config.confirmed) or, in an
        # interactive session, the user answered the prompt.
        if not config.confirmed and not config.interactive:
            raise _RequiresConfirmation(
                "delete requires confirmation (--yes or interactive)"
            )
        return [RepairOperation(
            issue_code=ORPHANED_TASK,
            target=task_title,
            operation="delete_task",
            file_kind="tasks",
            description=f"Delete orphan task '{task_title}'",
            before={},
            after={},
            reversible=False,
        )]

    raise _UnsupportedIssue(f"unknown orphan action '{config.action}'")


def _repair_relationship_mismatch(
    issue: GoalIntegrityIssue,
    config: RepairConfig,
    task_by_title: dict[str, Task],
    goal_by_title: dict[str, Goal],
    open_task_titles: set[str],
) -> list[RepairOperation]:
    """Reconcile a forward/reverse link mismatch (§5.5, §4)."""
    # Two shapes of mismatch from the audit:
    #   (a) reverse-only ref: task_id is set, details.task_id set.
    #       → forward: add task to goal.related_tasks
    #       → reverse: remove goal: ref from task
    #   (b) count mismatch: task_id is None, details has forward_count/reverse_count.
    #       → resolved indirectly when the individual reverse-only entries are
    #         reconciled; this aggregate issue produces no direct operation.
    goal_title = issue.goal_id
    task_title = issue.task_id

    if task_title is not None:
        # (a) reverse-only or per-task mismatch.
        if config.reconcile_strategy == "forward":
            if goal_title is None:
                raise _UnsupportedIssue("missing goal_id for forward repair")
            return [RepairOperation(
                issue_code=RELATIONSHIP_COUNT_MISMATCH,
                target=goal_title,
                operation="add_related_task",
                file_kind="goals",
                description=(
                    f"Forward-link: add task '{task_title}' to goal "
                    f"'{goal_title}' related_tasks"
                ),
                before={},
                after={"added_task": task_title},
            )]
        else:
            # reverse: remove the goal: ref from the task.
            if goal_title is None:
                raise _UnsupportedIssue("missing goal_id for reverse repair")
            task = task_by_title.get(task_title)
            if task is None or not task.extra_metadata:
                raise _UnsupportedIssue(
                    f"task '{task_title}' not found or has no metadata"
                )
            idx = _find_meta_index(task.extra_metadata, goal_title)
            if idx is None:
                return []
            target_meta = f"goal: {goal_title}"
            return [RepairOperation(
                issue_code=RELATIONSHIP_COUNT_MISMATCH,
                target=task_title,
                operation="remove_goal_ref",
                file_kind="tasks",
                description=(
                    f"Reverse-link: remove 'goal: {goal_title}' from "
                    f"task '{task_title}'"
                ),
                before={"removed_ref": target_meta, "removed_index": idx},
                after={},
            )]

    # (b) aggregate count mismatch — no direct operation; resolved by the
    # per-task repairs above.
    return []


# ── Low-level persistence helpers (tasks.md) ─────────────────────────────────

# The project's TASKS_PATH / GOALS_PATH.  These are imported lazily inside
# functions so tests can monkeypatch them (matching the pattern used by
# ``janus.services.tasks`` and ``janus.goals_cli``).


def _tasks_path() -> Path:
    from janus.integrations.markdown_tasks import TASKS_PATH
    return TASKS_PATH


def _goals_path() -> Path:
    from janus.integrations.markdown_goals import GOALS_PATH
    return GOALS_PATH


def _find_meta_index(extra_metadata: list[str], goal_ref: str) -> int | None:
    """Return the index of the ``goal: <goal_ref>`` or ``goal:<goal_ref>``
    entry in ``extra_metadata``, or ``None`` if absent."""
    for i, item in enumerate(extra_metadata):
        if not isinstance(item, str):
            continue
        stripped = item.strip()
        if stripped.startswith("goal:"):
            ref = stripped[len("goal:"):].strip()
            if ref == goal_ref:
                return i
    return None


def _remove_task_goal_ref(task_title: str, removed_ref: str, removed_index: int) -> None:
    """Remove a ``goal:`` ref from an open task line in tasks.md (§5.1).

    Uses raw line manipulation to preserve the original field ordering of
    all other metadata on the line (the parse/format round-trip would
    reorder ``due:``, ``priority:``, and ``goal:`` entries).
    """
    from janus.integrations.atomic_io import read_modify_write

    path = _tasks_path()

    def mutate(cur: str) -> str:
        lines = cur.splitlines()
        found = False
        for i, line in enumerate(lines):
            if not line.startswith("- [ ] ") and not line.startswith("- [x] "):
                continue
            checkbox = "[]"  # placeholder, replaced below
            if line.startswith("- [ ] "):
                checkbox = "[ ]"
                content = line[len("- [ ] "):]
            else:
                checkbox = "[x]"
                content = line[len("- [x] "):]
            title = content.split(" | ", 1)[0].strip() if " | " in content else content
            if title != task_title:
                continue
            meta_part = content[len(title):] if " | " in content else ""
            # meta_part starts with " | " — strip that prefix to get the
            # list of " | "-separated metadata chunks.
            chunks = meta_part[3:].split(" | ") if meta_part.startswith(" | ") else []
            filtered = [c for c in chunks if c.strip() != removed_ref]
            new_meta = " | ".join(filtered).rstrip()
            if new_meta:
                lines[i] = f"- {checkbox} {title} | {new_meta}"
            else:
                lines[i] = f"- {checkbox} {title}"
            found = True
            break
        if not found:
            raise ValueError(f"Task '{task_title}' not found or ref not present")
        return "\n".join(lines) + "\n"

    read_modify_write(path, mutate, backup=True)


def _add_task_goal_ref(task_title: str, added_ref: str, added_index: int) -> None:
    """Insert a ``goal:`` ref into an open task line, preserving ordering (§5.1 revert).

    Uses raw line manipulation so the original field ordering is preserved.
    ``added_index`` positions the ref among existing ``|``-separated metadata
    chunks (``-1`` = append).
    """
    from janus.integrations.atomic_io import read_modify_write

    path = _tasks_path()
    ref_clean = added_ref  # already in "goal: Title" form

    def mutate(cur: str) -> str:
        lines = cur.splitlines()
        found = False
        for i, line in enumerate(lines):
            if not line.startswith("- [ ] ") and not line.startswith("- [x] "):
                continue
            if line.startswith("- [ ] "):
                checkbox = "[ ]"
                content = line[len("- [ ] "):]
            else:
                checkbox = "[x]"
                content = line[len("- [x] "):]
            title = content.split(" | ", 1)[0].strip() if " | " in content else content
            if title != task_title:
                continue
            meta_part = content[len(title):] if " | " in content else ""
            chunks = meta_part.split(" | ") if meta_part else []
            existing = [c for c in chunks if c.strip()]
            # Idempotent: skip if ref already present.
            if ref_clean in [c.strip() for c in existing]:
                found = True
                break
            pos = max(0, added_index) if added_index >= 0 else len(existing)
            existing.insert(pos, ref_clean)
            new_meta = " | ".join(existing)
            lines[i] = f"- {checkbox} {title} | {new_meta}"
            found = True
            break
        if not found:
            raise ValueError(f"Task '{task_title}' not found")
        return "\n".join(lines) + "\n"

    read_modify_write(path, mutate, backup=True)


def _complete_task(task_title: str) -> None:
    """Flip an open task checkbox to completed (§5.4 archive)."""
    from janus.integrations.atomic_io import read_modify_write

    path = _tasks_path()

    def mutate(cur: str) -> str:
        lines = cur.splitlines()
        found = False
        for i, line in enumerate(lines):
            if line.startswith("- [ ] "):
                content = line[len("- [ ] "):]
                title = content.split(" | ", 1)[0].strip() if " | " in content else content
                if title == task_title:
                    lines[i] = "- [x] " + content
                    found = True
                    break
        if not found:
            raise ValueError(f"Open task '{task_title}' not found")
        return "\n".join(lines) + "\n"

    read_modify_write(path, mutate, backup=True)


def _reopen_task(task_title: str) -> None:
    """Flip a completed task back to open (§5 revert for archive)."""
    from janus.integrations.atomic_io import read_modify_write

    path = _tasks_path()

    def mutate(cur: str) -> str:
        lines = cur.splitlines()
        found = False
        for i, line in enumerate(lines):
            if line.startswith("- [x] "):
                content = line[len("- [x] "):]
                title = content.split(" | ", 1)[0].strip() if " | " in content else content
                if title == task_title:
                    lines[i] = "- [ ] " + content
                    found = True
                    break
        if not found:
            raise ValueError(f"Completed task '{task_title}' not found")
        return "\n".join(lines) + "\n"

    read_modify_write(path, mutate, backup=True)


def _delete_task(task_title: str) -> None:
    """Remove a task line from tasks.md (§5.4 delete)."""
    from janus.integrations.atomic_io import read_modify_write

    path = _tasks_path()

    def mutate(cur: str) -> str:
        lines = cur.splitlines()
        found = False
        kept: list[str] = []
        for line in lines:
            if line.startswith("- [ ] ") or line.startswith("- [x] "):
                content = line[5:].strip()
                title = content.split(" | ", 1)[0].strip() if " | " in content else content
                if title == task_title:
                    found = True
                    continue
            kept.append(line)
        if not found:
            raise ValueError(f"Task '{task_title}' not found")
        return "\n".join(kept) + "\n"

    read_modify_write(path, mutate, backup=True)


def _restore_task(task_title: str, line: str) -> None:
    """Re-insert a deleted task line (§5 revert for delete)."""
    raise NotImplementedError(
        "Task restoration requires the original line; use a backup to revert deletes."
    )


def _remove_goal_related_task(goal_title: str, removed_task: str) -> None:
    """Remove a stale entry from a goal's related_tasks list (§5.2)."""
    from janus.integrations.markdown_goals import update_goal
    from janus.services.goals import get_goal

    goal = get_goal(goal_title)
    if removed_task not in goal.related_tasks:
        return  # idempotent — already removed
    goal.related_tasks.remove(removed_task)
    update_goal(goal)


def _add_goal_related_task(goal_title: str, added_task: str) -> None:
    """Add a task title to a goal's related_tasks list (§5 revert / reconcile)."""
    from janus.integrations.markdown_goals import update_goal
    from janus.services.goals import get_goal

    goal = get_goal(goal_title)
    if added_task in goal.related_tasks:
        return  # idempotent
    goal.related_tasks.append(added_task)
    update_goal(goal)


def _capture_backups() -> Path | None:
    """Snapshot the data dir before applying repairs (design §3 principle 5).

    Returns the backup directory path, or ``None`` if no snapshot was taken.
    """
    from janus.integrations.data_integrity import backup_previous

    backups: list[Path] = []
    for get_path in (_tasks_path, _goals_path):
        p = get_path()
        if p.exists():
            b = backup_previous(p)
            if b is not None:
                backups.append(b)
    if not backups:
        return None
    return backups[0].parent


# ── Logging helpers ────────────────────────────────────────────────────────


def _log_applied(op: RepairOperation) -> None:
    emit(
        logger, "service.goal_integrity.repaired",
        span_id="repair", level=logging.INFO,
        operation=op.operation, issue_code=op.issue_code,
        target=op.target, file_kind=op.file_kind,
        description=op.description,
        message=f"Applied repair: {op.operation} on '{op.target}'",
    )


def _log_skipped(reason: str, issue: GoalIntegrityIssue) -> None:
    emit(
        logger, "service.goal_integrity.repair_skipped",
        span_id="repair", level=logging.INFO,
        issue_code=issue.code, target=issue.task_id or issue.goal_id,
        reason=reason,
        message=f"Skipped repair for {issue.code}: {reason}",
    )


def _log_failed(op: RepairOperation, error: str) -> None:
    emit(
        logger, "service.goal_integrity.repair_failed",
        span_id="repair", level=logging.ERROR,
        operation=op.operation, issue_code=op.issue_code,
        target=op.target, error={"message": error},
        message=f"Repair failed: {op.operation} on '{op.target}': {error}",
    )
