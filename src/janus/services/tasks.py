"""Gated completion for Janus task service (ADR-004 Phase 5).

Wires Phase 3 (pre-completion verification) and Phase 4 (safe integration)
gates into ``complete_task()`` so a task cannot be marked done without
passing both gates, and produces the evidence artifacts specified by ADR-004.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Optional

from janus._log import emit
from janus.models.task import Task
from janus.integrations.markdown_tasks import (
    _parse_task_line,
    _format_task_line,
)
from janus.integrations.atomic_io import read_modify_write
from janus.integrations.data_protection import compute_content_hash
from janus.integrations.data_protection import protected_write, protected_append, compute_content_hash
from janus.verification import (
    VerificationReport,
    run_default_checks,
    run_verification,
)
from janus.integration import (
    integrate_task,
    IntegrationResult,
)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
TASKS_PATH = PROJECT_ROOT / "data" / "tasks.md"

logger = __import__("logging").getLogger(__name__)

# ---------------------------------------------------------------------------
# Gate result + structured errors
# ---------------------------------------------------------------------------


@dataclass
class CompletionGateResult:
    """Outcome of running the ADR-004 Phase 3 + Phase 4 gates.

    ``ok`` is True only when both gates passed (or were not applicable).
    On failure, ``blocked_reason`` carries a structured reason code and
    ``report`` carries the aggregated evidence.
    """

    ok: bool = False
    blocked_reason: Optional[str] = None
    blocked_message: Optional[str] = None
    pre_completion_report: Optional[VerificationReport] = None
    integration_result: Optional[IntegrationResult] = None
    integration_not_applicable: bool = False


class CompletionGateError(ValueError):
    """Raised by ``complete_task`` when a Phase 3/4 gate blocks completion.

    Carries a structured ``reason`` code and a human-readable ``message``
    so callers (CLI, Hermes sync listener) can surface an actionable error.
    """

    def __init__(self, reason: str, message: str) -> None:
        self.reason = reason
        super().__init__(message)


# ── Reason codes (mirror docs/design/sync_integration_workflow_design.md §5.1) ──

GATE_WORKING_TREE_NOT_CLEAN = "working_tree_not_clean"
GATE_TESTS_FAILED = "pre_completion_tests_failed"
GATE_DIFF_CHECK_FAILED = "pre_completion_diff_check_failed"
GATE_INTEGRATION_NOT_DONE = "integration_not_done"
GATE_INTEGRATION_FAILED = "integration_failed"
GATE_NO_GIT_REPO = "no_git_repo"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _find_git_root(path: Path) -> Optional[Path]:
    """Walk up from *path* looking for a ``.git`` directory.

    Returns the repository root, or ``None`` when *path* is not inside
    a git repository (e.g. a temporary test path).
    """
    candidate = path.resolve()
    for _ in range(10):
        if (candidate / ".git").is_dir():
            return candidate
        parent = candidate.parent
        if parent == candidate:
            break
        candidate = parent
    return None


def _has_origin_remote(root: Path) -> bool:
    """Return True if the repository has an ``origin`` remote."""
    out = _git_out(root, ["remote", "get-url", "origin"])
    return bool(out)


def _git_out(root: Path, args: list[str]) -> str:
    """stdout of a git command run in *root*, or ``""`` on any failure."""
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=30,
            stdin=subprocess.DEVNULL,
            env=dict(__import__("os").environ, GIT_TERMINAL_PROMPT="0"),
        )
        return proc.stdout.strip() if proc.returncode == 0 else ""
    except (subprocess.TimeoutExpired, OSError):
        return ""


def _current_branch(root: Path) -> Optional[str]:
    branch = _git_out(root, ["rev-parse", "--abbrev-ref", "HEAD"])
    if branch and branch != "HEAD":
        return branch
    return None


def _target_branch(root: Path) -> Optional[str]:
    """Resolve the target branch name per the sync-detection order."""
    from janus.git_sync import detect_target_branch

    return detect_target_branch(str(root))


def _head_sha(root: Path) -> Optional[str]:
    return _git_out(root, ["rev-parse", "HEAD"]) or None


def _remote_contains(root: Path, remote_branch: str, sha: str) -> bool:
    """Return True if *remote_branch* contains *sha*."""
    _git_out(root, ["fetch", "origin"])
    out = _git_out(root, ["branch", "-r", "--contains", sha])
    if not out:
        return False
    expected = remote_branch  # e.g. "origin/master"
    for line in out.splitlines():
        line = line.strip()
        if line == expected or line.endswith(expected):
            return True
    return False


def _write_report_json(path: Path, report_dict: dict[str, Any]) -> Path:
    """Write a JSON evidence artifact, creating parent dirs as needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report_dict, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return path


def _default_report_dir(root: Path) -> Path:
    return root / "reports"


def _write_pre_completion_report(
    report: VerificationReport, report_dir: Path
) -> Path:
    """Persist ``pre_completion_report.json`` for the evidence artifact."""
    return _write_report_json(
        report_dir / "pre_completion_report.json", report.to_dict()
    )


# ---------------------------------------------------------------------------
# Gate runner
# ---------------------------------------------------------------------------


def run_completion_gates(
    root: Optional[Path] = None,
    *,
    test_command: str = "uv run pytest tests/",
    integration_report_path: Optional[Path] = None,
) -> CompletionGateResult:
    """Run ADR-004 Phase 3 + Phase 4 gates and return the outcome.

    Phase 3 (pre-completion verification):
        - ``check_working_tree_clean``
        - ``check_git_diff_check``
        - ``check_tests_pass_after_rebase``

    Phase 4 (safe integration):
        - If the current branch's HEAD is already contained in the remote
          target branch, integration is considered done (no-op).
        - Otherwise, attempt integration via ``integrate_task``. On success
          the integration report is written and returned. On failure the
          gate blocks with ``GATE_INTEGRATION_FAILED``.

    When *root* is not inside a git repository both gates are skipped and
    the result reports ``integration_not_applicable=True`` — this keeps
    existing callers (e.g. tests that monkeypatch ``TASKS_PATH`` to a temp
    directory) working without change.

    Args:
        root: Workspace root. Defaults to ``PROJECT_ROOT``.
        test_command: Shell command used for the post-rebase / post-merge
            test suite.
        integration_report_path: Where to write ``integration_report.json``.
            Defaults to ``<root>/reports``.

    Returns:
        A ``CompletionGateResult``. Callers should check ``ok`` before
        proceeding with the markdown completion.
    """
    if root is None:
        root = PROJECT_ROOT

    git_root = _find_git_root(root)
    if git_root is None:
        return CompletionGateResult(
            ok=True,
            integration_not_applicable=True,
            pre_completion_report=None,
            integration_result=None,
        )

    report_dir = integration_report_path or _default_report_dir(git_root)

    # ── Phase 3: pre-completion verification ──────────────────────────────
    from janus.verification import DefaultCheckConfig

    pre_report = run_default_checks(
        DefaultCheckConfig(root=git_root, test_command=test_command)
    )
    if not pre_report.is_pass:
        # Pick the most specific reason from the failing checks.
        reason = GATE_WORKING_TREE_NOT_CLEAN
        message = "Pre-completion gate failed: working tree is not clean"
        for check_name, cr in pre_report.checks.items():
            if cr.has_error:
                reason = f"pre_completion_{check_name}_failed"
                message = f"Pre-completion gate failed: {check_name} errored"
                break
            if not cr.passed:
                if check_name == "working_tree_clean":
                    reason = GATE_WORKING_TREE_NOT_CLEAN
                    message = "Pre-completion gate failed: working tree is not clean"
                elif check_name == "tests_pass_after_rebase":
                    reason = GATE_TESTS_FAILED
                    message = "Pre-completion gate failed: tests did not pass after rebase"
                elif check_name == "git_diff_check":
                    reason = GATE_DIFF_CHECK_FAILED
                    message = "Pre-completion gate failed: git diff check failed"
                break

        return CompletionGateResult(
            ok=False,
            blocked_reason=reason,
            blocked_message=message,
            pre_completion_report=pre_report,
        )

    # ── Persist Phase 3 evidence artifact before Phase 4 ─────────────────
    _write_pre_completion_report(pre_report, report_dir)

    # ── Phase 4: safe integration ─────────────────────────────────────────
    branch = _current_branch(git_root)
    if branch is None:
        # Detached HEAD or no branch — integration not applicable in this
        # invocation; the caller is responsible for ensuring integration
        # happened through another path.
        return CompletionGateResult(
            ok=True,
            pre_completion_report=pre_report,
            integration_not_applicable=True,
            integration_result=None,
        )

    target = _target_branch(git_root)
    if target is None:
        return CompletionGateResult(
            ok=True,
            pre_completion_report=pre_report,
            integration_not_applicable=True,
            integration_result=None,
        )

    # No origin remote → integration can't be verified; skip.
    if not _has_origin_remote(git_root):
        return CompletionGateResult(
            ok=True,
            pre_completion_report=pre_report,
            integration_not_applicable=True,
            integration_result=None,
        )

    remote_branch = f"origin/{target}"
    head_sha = _head_sha(git_root)
    if head_sha and _remote_contains(git_root, remote_branch, head_sha):
        # Already integrated — carry the existing state as evidence.
        integration_result: IntegrationResult = IntegrationResult(
            success=True,
            reason=None,
            target_branch=target,
            task_branch=branch,
            task_commit=head_sha,
            merge_strategy="already_integrated",
            tests_passed=True,
            started_at=datetime.now(timezone.utc).isoformat(),
            completed_at=datetime.now(timezone.utc).isoformat(),
        )
        integration_result.report = {
            "success": True,
            "reason": None,
            "already_integrated": True,
            "target_branch": target,
            "task_branch": branch,
            "task_commit": head_sha,
            "tests_passed": True,
            "started_at": integration_result.started_at,
            "completed_at": integration_result.completed_at,
        }
        _write_report_json(
            report_dir / "integration_report.json", integration_result.report
        )
        integration_result.report_path = report_dir
        return CompletionGateResult(
            ok=True,
            pre_completion_report=pre_report,
            integration_result=integration_result,
        )

    # Not yet integrated — run the integration step.
    result = integrate_task(
        str(git_root),
        task_branch=branch,
        target_branch=target,
        test_command=test_command,
        report_path=report_dir,
    )
    if not result.success:
        return CompletionGateResult(
            ok=False,
            blocked_reason=GATE_INTEGRATION_FAILED,
            blocked_message=(
                f"Integration failed ({result.reason}): "
                f"{result.error or 'no detail'}"
            ),
            pre_completion_report=pre_report,
            integration_result=result,
        )

    _write_report_json(
        report_dir / "integration_report.json", result.report
    )
    result.report_path = report_dir
    return CompletionGateResult(
        ok=True,
        pre_completion_report=pre_report,
        integration_result=result,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def complete_task(title: str) -> Task:
    """Find an open task by exact title, run ADR-004 gates, mark it completed,
    and return it.

    Before flipping the checkbox the following gates run (when the task file
    lives inside a git repository; they are silently skipped for non-git
    paths so that existing callers and tests continue to work):

    1. **Phase 3 — pre-completion verification** — working tree clean,
       ``git diff --check``, and re-run of the test suite must all pass.
    2. **Phase 4 — safe integration** — the task branch must already be
       integrated into the remote target branch, or integration is attempted
       automatically. If integration fails the gate blocks.

    On success the following evidence artifacts are written:

    - ``<root>/reports/pre_completion_report.json`` — Phase 3 results.
    - ``<root>/reports/integration_report.json`` — Phase 4 results (or a
      minimal "already_integrated" report when the branch was already merged).

    The completion event emitted by :func:`janus._log.emit` carries structured
    metadata: ``commit_sha``, ``target_branch``, ``merge_strategy``,
    ``tests_passed``, ``pre_completion_report``, ``integration_report``.

    Raises:
        ValueError: if no matching open task is found, if multiple match,
            or if the matching task is already completed.
        CompletionGateError: if a Phase 3 or Phase 4 gate blocks completion.
            The ``reason`` attribute carries the structured reason code.
    """
    _validate_title(title)

    gate_result = run_completion_gates(root=TASKS_PATH.parent)
    if not gate_result.ok:
        raise CompletionGateError(
            reason=gate_result.blocked_reason or "unknown",
            message=gate_result.blocked_message or "Completion gate blocked",
        )

    raw_content = TASKS_PATH.read_text()
    lines = raw_content.splitlines()
    matches: list[int] = []

    for i, line in enumerate(lines):
        if not line.startswith("- [ ] "):
            continue
        content = line[len("- [ ] "):]
        task_title = content.split(" | ", 1)[0] if " | " in content else content
        if task_title == title:
            matches.append(i)

    if not matches:
        raise ValueError(f"Task not found: {title}")
    if len(matches) > 1:
        raise ValueError(f"Multiple open tasks found with title: {title}")

    idx = matches[0]
    line = lines[idx]
    lines[idx] = "- [x] " + line[len("- [ ] "):]

    content = "\n".join(lines) + "\n"
    read_modify_write(
        TASKS_PATH,
        lambda cur: content if compute_content_hash(cur) == compute_content_hash(raw_content) else cur,
        backup=True,
    )

    # ── Structured metadata for the completion event ──────────────────────
    commit_sha: Optional[str] = None
    target_branch: Optional[str] = None
    merge_strategy: Optional[str] = None
    tests_passed: Optional[bool] = None

    if gate_result.pre_completion_report is not None:
        commit_sha = _head_sha(_find_git_root(TASKS_PATH) or PROJECT_ROOT)
        tests_passed = gate_result.pre_completion_report.is_pass

    if gate_result.integration_result is not None:
        target_branch = gate_result.integration_result.target_branch
        merge_strategy = gate_result.integration_result.merge_strategy

    emit(
        logger,
        "service.task.mutated",
        trace_id=None,
        span_id="service",
        operation="complete",
        task_title=title,
        previous_state="todo",
        new_state="completed",
        new_progress=None,
        message=f"Task '{title}' completed",
        commit_sha=commit_sha,
        target_branch=target_branch,
        merge_strategy=merge_strategy,
        tests_passed=tests_passed,
        pre_completion_report=(
            gate_result.pre_completion_report.to_dict()
            if gate_result.pre_completion_report is not None
            else None
        ),
        integration_report=(
            gate_result.integration_result.report
            if gate_result.integration_result is not None
            else None
        ),
    )

    return Task(title=title)


def complete_janus_task(title: str, evidence: dict | None = None) -> Task:
    """Mark a Janus task complete with execution-feedback evidence.

    Called by the Hermes-side execution-feedback sync listener when a
    Kanban task that carries ``janus_domain: object: task`` linkage
    completes.

    Finds the open task by exact title, marks it completed (checkbox
    ``- [x]``), and records evidence metadata on the task line.
    The evidence dict (with keys ``task_id``, ``summary``,
    ``completed_at``, ``changed_files``, ``tests_passed``, ``pr_url``)
    is serialized into ``extra_metadata`` as ``janus_evidence_*`` fields.

    Idempotent: if the task is already completed, it is re-written with
    the new evidence (no error).

    Args:
        title: exact task title (open or completed).
        evidence: Evidence package dict.

    Returns:
        The completed Task.

    Raises:
        ValueError: if no matching task is found or multiple match.
    """
    _validate_title(title)

    raw_content = TASKS_PATH.read_text()
    lines = raw_content.splitlines()
    matches: list[int] = []

    for i, line in enumerate(lines):
        # Match both open (- [ ]) and completed (- [x]) tasks
        if not (line.startswith("- [ ] ") or line.startswith("- [x] ")):
            continue
        content = line[len("- [ ] "):] if line.startswith("- [ ] ") \
            else line[len("- [x] "):]
        task_title = content.split(" | ", 1)[0] if " | " in content else content
        if task_title == title:
            matches.append(i)

    if not matches:
        raise ValueError(f"Task not found: {title}")
    if len(matches) > 1:
        raise ValueError(f"Multiple open tasks found with title: {title}")

    idx = matches[0]
    task = _parse_task_line(lines[idx], idx + 1)
    # If already completed, _parse_task_line returns None; reconstruct from raw
    if task is None:
        content = lines[idx][len("- [x] "):]
        task_title = content.split(" | ", 1)[0] if " | " in content else content
        task = Task(title=task_title.strip())

    # Serialize evidence into extra_metadata
    ev = evidence or {}
    task.extra_metadata = task.extra_metadata or []
    # Remove any prior janus_evidence fields for idempotency
    task.extra_metadata = [
        m for m in task.extra_metadata if not m.startswith("janus_evidence_")
    ]
    if ev.get("task_id"):
        task.extra_metadata.append(f"janus_evidence_task_id: {ev['task_id']}")
    if ev.get("completed_at"):
        task.extra_metadata.append(f"janus_evidence_completed_at: {ev['completed_at']}")
    if ev.get("tests_passed") is not None:
        task.extra_metadata.append(
            f"janus_evidence_tests_passed: {ev['tests_passed']}"
        )
    if ev.get("pr_url"):
        task.extra_metadata.append(f"janus_evidence_pr_url: {ev['pr_url']}")
    if ev.get("changed_files"):
        for f in ev["changed_files"]:
            task.extra_metadata.append(f"janus_evidence_changed_file: {f}")

    # Format as completed
    line = f"- [x] {task.title}"
    parts = []
    if task.due_date is not None:
        parts.append(f"due: {task.due_date.isoformat()}")
    if task.priority != 1:
        parts.append(f"priority: {task.priority}")
    if task.state is not None:
        parts.append(f"state: {task.state}")
    if task.progress is not None:
        parts.append(f"progress: {task.progress}")
    if task.extra_metadata:
        parts.extend(task.extra_metadata)
    if parts:
        line += " | " + " | ".join(parts)
    lines[idx] = line

    content = "\n".join(lines) + "\n"
    read_modify_write(
        TASKS_PATH,
        lambda cur: content if compute_content_hash(cur) == compute_content_hash(raw_content) else cur,
        backup=True,
    )

    emit(
        logger,
        "service.task.mutated",
        trace_id=None,
        span_id="service",
        operation="complete_janus_task",
        task_title=title,
        previous_state="todo" if not lines[idx].startswith("- [x]") else "completed",
        new_state="completed",
        new_progress=None,
        message=f"Task '{title}' completed with Janus evidence",
    )

    return task


def _validate_title(title: str) -> None:
    if not title or not title.strip():
        raise ValueError("Task title cannot be empty")


def _validate_priority(priority: int) -> None:
    if priority < 1:
        raise ValueError("Priority must be >= 1")


def _validate_due_date(due_date: date | None) -> None:
    if due_date is not None:
        try:
            date.fromisoformat(due_date.isoformat())
        except ValueError:
            raise ValueError(f"Invalid due date: {due_date}")


def add_task(title: str, due_date: date | None = None, priority: int = 1) -> Task:
    """Validate input, create a Task, append it to data/tasks.md, and return it."""
    _validate_title(title)
    _validate_priority(priority)
    _validate_due_date(due_date)

    task = Task(title=title, due_date=due_date, priority=priority)
    _append_task(task)

    emit(
        logger,
        "service.task.mutated",
        trace_id=None,
        span_id="service",
        operation="add",
        task_title=title,
        previous_state=None,
        new_state=None,
        new_progress=None,
        message=f"Task '{title}' added",
    )

    return task


ALLOWED_STATES = frozenset({"todo", "in_progress", "blocked"})


def list_tasks() -> list[Task]:
    """Return all open (incomplete) tasks from data/tasks.md, in file order.

    Open tasks are those with an unchecked checkbox (``- [ ]``). Completed
    tasks (``- [x]``) are excluded and remain the sole responsibility of
    ``complete_task``.

    Uses the service-layer ``TASKS_PATH`` constant so that monkeypatching
    ``janus.services.tasks.TASKS_PATH`` (as tests and the CLI handler do) is
    respected.
    """
    from janus.integrations.markdown_tasks import load_tasks

    return load_tasks(TASKS_PATH)


def set_task_state(title: str, state: str) -> Task:
    """Update the state of an open task, preserving all other metadata.

    Args:
        title: exact task title to match
        state: one of 'todo', 'in_progress', 'blocked'

    Returns the updated Task.

    Raises:
        ValueError: if no matching open task found, if multiple match,
                     if the matching task is already completed, or if
                     the state value is invalid.
    """
    _validate_title(title)
    if state not in ALLOWED_STATES:
        raise ValueError(
            f"Invalid task state: {state!r}. "
            f"Allowed values: {', '.join(sorted(ALLOWED_STATES))}"
        )

    raw_content = TASKS_PATH.read_text()
    lines = raw_content.splitlines()
    matches: list[int] = []

    for i, line in enumerate(lines):
        if not line.startswith("- [ ] "):
            continue
        content = line[len("- [ ] "):]
        task_title = content.split(" | ", 1)[0] if " | " in content else content
        if task_title == title:
            matches.append(i)

    if not matches:
        raise ValueError(f"Task not found: {title}")
    if len(matches) > 1:
        raise ValueError(f"Multiple open tasks found with title: {title}")

    idx = matches[0]
    task = _parse_task_line(lines[idx], idx + 1)
    if task is None:
        raise ValueError(f"Task not found: {title}")

    task.state = state
    lines[idx] = _format_task_line(task)
    content = "\n".join(lines) + "\n"
    read_modify_write(
        TASKS_PATH,
        lambda cur: content if compute_content_hash(cur) == compute_content_hash(raw_content) else cur,
        backup=True,
    )

    emit(
        logger,
        "service.task.mutated",
        trace_id=None,
        span_id="service",
        operation="set_state",
        task_title=title,
        previous_state=None,
        new_state=state,
        new_progress=None,
        message=f"Task '{title}' state set to '{state}'",
    )

    return task


def set_task_progress(title: str, progress: int) -> Task:
    """Update the progress of an open task, preserving all other metadata.

    Progress must be an integer between 0 and 100 inclusive.
    Progress 100 does NOT automatically complete the task —
    completion still requires `janus task complete`.

    Args:
        title: exact task title to match
        progress: integer between 0 and 100

    Returns the updated Task.

    Raises:
        ValueError: if no matching open task found, if multiple match,
                     if the matching task is already completed, or if
                     progress is not an integer in [0, 100].
    """
    _validate_title(title)
    if not isinstance(progress, int) or not (0 <= progress <= 100):
        raise ValueError(
            f"Progress must be an integer between 0 and 100, got {progress!r}"
        )

    raw_content = TASKS_PATH.read_text()
    lines = raw_content.splitlines()
    matches: list[int] = []

    for i, line in enumerate(lines):
        if not line.startswith("- [ ] "):
            continue
        content = line[len("- [ ] "):]
        task_title = content.split(" | ", 1)[0] if " | " in content else content
        if task_title == title:
            matches.append(i)

    if not matches:
        raise ValueError(f"Task not found: {title}")
    if len(matches) > 1:
        raise ValueError(f"Multiple open tasks found with title: {title}")

    idx = matches[0]
    task = _parse_task_line(lines[idx], idx + 1)
    if task is None:
        raise ValueError(f"Task not found: {title}")

    task.progress = progress
    lines[idx] = _format_task_line(task)
    content = "\n".join(lines) + "\n"
    read_modify_write(
        TASKS_PATH,
        lambda cur: content if compute_content_hash(cur) == compute_content_hash(raw_content) else cur,
        backup=True,
    )

    emit(
        logger,
        "service.task.mutated",
        trace_id=None,
        span_id="service",
        operation="set_progress",
        task_title=title,
        previous_state=None,
        new_state=None,
        new_progress=progress,
        message=f"Task '{title}' progress set to {progress}%",
    )

    return task


def _append_task(task: Task) -> None:
    line = _format_task_line(task)
    read_modify_write(
        TASKS_PATH,
        lambda cur: cur + line + "\n",
        backup=True,
    )


def _format_task_line(task: Task) -> str:
    parts = [f"- [ ] {task.title}"]

    if task.due_date is not None:
        parts.append(f"due: {task.due_date.isoformat()}")

    if task.priority != 1:
        parts.append(f"priority: {task.priority}")

    if task.state is not None:
        parts.append(f"state: {task.state}")

    if task.progress is not None:
        parts.append(f"progress: {task.progress}")

    if task.extra_metadata:
        parts.extend(task.extra_metadata)

    if len(parts) > 1:
        return " | ".join(parts)

    return parts[0]
