"""Repository integration primitive for task branches (Phase 4).

Implements the Safe Integration phase of the safe sync-and-integrate workflow
(see docs/design/sync_integration_workflow_design.md, §4.4 and §5.1).

Brings a task branch into the target branch atomically: fast-forward attempt
first, controlled merge fallback, post-merge verification, push, and remote
containment check.  Every failure path returns a structured reason code that
the completion path (Phase 5) surfaces via ``kanban_block``.

This module is narrowly scoped to the *integration* primitive only.  It does
not perform Phase 1 sync, Phase 3 pre-completion verification, or call
``kanban_block`` / ``kanban_complete`` itself — those are the responsibility
of the caller (the completion flow / Phase 5 gating), which inspects the
:class:`IntegrationResult` fields below and invokes the appropriate Kanban
transition.
"""
from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from janus.git_sync import (
    _GIT_TIMEOUT,
    _git_out,
    _run_git,
    detect_target_branch,
    detect_task_branch,
)
from janus.integrations.atomic_io import atomic_write

# ── Reason codes (mirror docs/design/sync_integration_workflow_design.md §5.1 ──

# The task branch does not contain the latest target commit (merge-base check).
TARGET_NOT_INTEGRATED = "target_not_integrated"
# Fast-forward merge failed and the controlled --no-ff merge produced conflicts.
INTEGRATION_CONFLICT = "integration_conflict"
# Post-merge test suite failed on the target branch; integration was rolled back.
POST_INTEGRATION_TEST_FAILURE = "post_integration_test_failure"
# Pushing the target branch to the remote failed.
TARGET_PUSH_FAILED = "target_push_failed"
# The remote target branch does not contain the task commit after push.
TARGET_CONTAINS_CHECK_FAILED = "target_contains_check_failed"
# The merge operation itself failed for a non-conflict reason.
MERGE_FAILED = "merge_failed"
# No integration was needed (task branch is already integrated or empty).
NOTHING_TO_INTEGRATE = "nothing_to_integrate"
# The task branch could not be found or the working directory is not a repo.
INTEGRATION_SETUP_FAILED = "integration_setup_failed"


# ── Result model ─────────────────────────────────────────────────────────────


@dataclass
class IntegrationResult:
    """Outcome of a repository integration attempt.

    ``success`` is True only when the task branch was integrated into the
    target, the post-merge test suite passed, the target was pushed, and
    remote containment was verified.

    On failure, ``reason`` carries a structured code from the module-level
    *_REASON constants above and ``error`` holds the human-readable output.
    The caller (Phase 5 completion flow) maps ``reason`` to a ``kanban_block``
    reason string.
    """

    success: bool = False
    reason: Optional[str] = None
    error: Optional[str] = None

    # Branch / commit context
    target_branch: Optional[str] = None
    task_branch: Optional[str] = None
    task_commit: Optional[str] = None
    target_before: Optional[str] = None
    target_after: Optional[str] = None

    # Merge details
    merge_strategy: Optional[str] = None  # "fast_forward" | "merge" | None
    merge_commit: Optional[str] = None
    conflicts: list[str] = field(default_factory=list)

    # Test / verification details
    tests_passed: bool = False
    test_command: Optional[str] = None
    test_output: Optional[str] = None

    # Push / remote verification
    push_succeeded: bool = False
    remote_contains: bool = False

    # Timestamps
    started_at: str = ""
    completed_at: str = ""

    # Full report dict (serialised to integration_report.json)
    report: dict[str, Any] = field(default_factory=dict)

    @property
    def report_path(self) -> Optional[Path]:
        """If set, the directory where ``integration_report.json`` was written."""
        return self._report_path if hasattr(self, "_report_path") else None

    @report_path.setter
    def report_path(self, value: Optional[Path]) -> None:
        self._report_path = value


# ── Git helpers (reuse patterns from git_sync._run_git) ──────────────────────


def _git_ok(cwd: str, args: list[str], timeout: int = _GIT_TIMEOUT) -> str:
    """Run a git command, raising RuntimeError with stderr on failure."""
    code, out, err = _run_git(cwd, args, timeout=timeout)
    if code != 0:
        raise RuntimeError(err.strip() or f"git {' '.join(args)} failed")
    return out.strip()


def _abort_merge(cwd: str) -> None:
    """Abort an in-progress merge to restore a clean target state."""
    _run_git(cwd, ["merge", "--abort"])


def _get_current_sha(cwd: str) -> Optional[str]:
    """Return the current HEAD SHA, or None if there is no commit."""
    return _git_out(cwd, ["rev-parse", "HEAD"]) or None


def _has_commits(cwd: str, branch: str) -> bool:
    """Return True if *branch* has at least one commit."""
    code, _, _ = _run_git(cwd, ["rev-parse", "--verify", branch])
    return code == 0


def _commits_behind(cwd: str, task_ref: str, target_ref: str) -> int:
    """Return the number of commits on *target* that are NOT on *task*.

    Uses ``git rev-list --count <task>..<target>`` — if the task branch
    already contains the target tip this is 0 (i.e. not stale / integrated).
    """
    code, out, _ = _run_git(cwd, ["rev-list", "--count", f"{task_ref}..{target_ref}"])
    if code != 0:
        return -1
    try:
        return int(out.strip())
    except ValueError:
        return -1


# ── Core integration primitive ───────────────────────────────────────────────


def integrate_branch(
    cwd: str,
    *,
    task_branch: Optional[str] = None,
    target_branch: Optional[str] = None,
    test_command: Optional[str] = None,
    report_path: Optional[str | Path] = None,
    remote_name: str = "origin",
) -> IntegrationResult:
    """Integrate a task branch into the target branch (Phase 4).

    Implements the Safe Integration workflow:

    1. Verify the task branch contains the latest target (merge-base check).
    2. Attempt fast-forward merge (``--ff-only``) on the target branch.
    3. If FF fails, controlled merge (``--no-ff``).  Conflicts → abort →
       :data:`INTEGRATION_CONFLICT`.
    4. Run the post-merge test suite on the target.  Failure → rollback
       (``git reset --hard <pre-merge-sha>``) →
       :data:`POST_INTEGRATION_TEST_FAILURE`.
    5. Push the target branch.  Failure → :data:`TARGET_PUSH_FAILED`.
    6. Verify the remote target contains the task commit
       (``git branch -r --contains``).  Failure →
       :data:`TARGET_CONTAINS_CHECK_FAILED`.

    Args:
        cwd: Path to the **main checkout** (NOT the task worktree).  Integration
            happens in the default workdir per design §6.
        task_branch: The task branch name.  Auto-detected if ``None``.
        target_branch: The target (trunk) branch name.  Auto-detected if ``None``.
        test_command: Shell command to run for post-merge verification (e.g.
            ``"uv run pytest tests/ -v"``).  If ``None``, the test step is
            skipped (no verification) — callers should supply the contract's
            verification command.
        report_path: Directory in which to write ``integration_report.json``.
            If ``None``, no report file is written (but the result still carries
            the full ``report`` dict).
        remote_name: Name of the git remote (default ``origin``).

    Returns:
        An :class:`IntegrationResult` with the outcome.  The caller is
        responsible for calling ``kanban_block`` with ``result.reason`` on
        failure, or ``kanban_complete`` on success.
    """
    now = datetime.now(timezone.utc).isoformat()
    result = IntegrationResult(started_at=now)

    cwd_str = str(cwd)

    # ── 1. Resolve branches ──────────────────────────────────────────
    if target_branch is None:
        target_branch = detect_target_branch(cwd_str)

    if not target_branch:
        result.reason = INTEGRATION_SETUP_FAILED
        result.error = "No target branch could be detected or provided"
        result.completed_at = datetime.now(timezone.utc).isoformat()
        _write_report(result, report_path, task_branch, target_branch)
        return result

    if task_branch is None:
        task_branch = detect_task_branch(cwd_str)

    if not task_branch:
        result.reason = INTEGRATION_SETUP_FAILED
        result.error = "Cannot integrate in detached HEAD state (no task branch)"
        result.target_branch = target_branch
        result.completed_at = datetime.now(timezone.utc).isoformat()
        _write_report(result, report_path, None, target_branch)
        return result

    result.target_branch = target_branch
    result.task_branch = task_branch

    # ── Fetch the latest remote state ────────────────────────────────
    fetch_ok, fetch_err = _fetch_remote(cwd_str, remote_name)
    if not fetch_ok:
        result.reason = TARGET_PUSH_FAILED  # fetch failure is a push-side issue
        result.error = f"Fetch failed: {fetch_err}"
        result.completed_at = datetime.now(timezone.utc).isoformat()
        _write_report(result, report_path, task_branch, target_branch)
        return result

    # ── 2. Verify task branch contains latest target ─────────────────
    target_ref = f"{remote_name}/{target_branch}"
    task_commit = _git_out(cwd_str, ["rev-parse", task_branch])
    target_commit = _git_out(cwd_str, ["rev-parse", target_ref])

    result.task_commit = task_commit
    result.target_before = target_commit

    if not task_commit or not target_commit:
        result.reason = INTEGRATION_SETUP_FAILED
        result.error = (
            f"Could not resolve task_branch ({task_branch}) or "
            f"target_ref ({target_ref}) to a commit"
        )
        result.completed_at = datetime.now(timezone.utc).isoformat()
        _write_report(result, report_path, task_branch, target_branch)
        return result

    if _commits_behind(cwd_str, f"{remote_name}/{task_branch}", target_ref) > 0:
        result.reason = TARGET_NOT_INTEGRATED
        result.error = (
            f"Task branch '{task_branch}' does not contain the latest target "
            f"'{target_branch}'. Re-sync (rebase onto target) before integration."
        )
        result.completed_at = datetime.now(timezone.utc).isoformat()
        _write_report(result, report_path, task_branch, target_branch)
        return result

    # ── 3. Checkout target and attempt fast-forward merge ────────────
    # Switch to (or create) the local target branch at the remote tip.
    checkout_target(cwd_str, target_branch, target_ref)

    pre_merge_sha = _get_current_sha(cwd_str)
    result.target_before = pre_merge_sha

    # Attempt fast-forward only first.
    ff_code, _, ff_err = _run_git(
        cwd_str, ["merge", "--ff-only", f"{remote_name}/{task_branch}"]
    )

    if ff_code == 0:
        result.merge_strategy = "fast_forward"
        result.merge_commit = _get_current_sha(cwd_str)
    else:
        # FF not possible — target has diverged; try controlled merge (--no-ff).
        merge_code, merge_out, merge_err = _run_git(
            cwd_str,
            ["merge", "--no-ff", "--no-edit", f"{remote_name}/{task_branch}",
             "-m", f"Merge task branch {task_branch} into {target_branch}"],
        )
        # git writes CONFLICT notices to stdout, errors to stderr; check both.
        merge_text = (merge_out or "") + " " + (merge_err or "")

        if merge_code != 0:
            # Check if this is a conflict or another merge error.
            if _is_merge_conflict(merge_text):
                conflicts = _get_conflicted_files(cwd_str)
                _abort_merge(cwd_str)
                result.merge_strategy = "merge"
                result.reason = INTEGRATION_CONFLICT
                result.conflicts = conflicts
                result.error = merge_text.strip()
                result.completed_at = datetime.now(timezone.utc).isoformat()
                _write_report(result, report_path, task_branch, target_branch)
                return result
            else:
                _abort_merge(cwd_str)
                result.merge_strategy = "merge"
                result.reason = MERGE_FAILED
                result.error = merge_text.strip()
                result.completed_at = datetime.now(timezone.utc).isoformat()
                _write_report(result, report_path, task_branch, target_branch)
                return result
        else:
            result.merge_strategy = "merge"
            result.merge_commit = _get_current_sha(cwd_str)

    result.target_after = _get_current_sha(cwd_str)

    # ── 4. Post-merge test suite ──────────────────────────────────────
    tests_passed, test_output = _run_post_merge_tests(cwd_str, test_command)
    result.test_command = test_command
    result.test_output = test_output
    result.tests_passed = tests_passed

    if not tests_passed:
        # Roll back the target branch to its pre-merge state.
        if pre_merge_sha:
            _rollback_target(cwd_str, pre_merge_sha)
            result.target_after = pre_merge_sha
        result.reason = POST_INTEGRATION_TEST_FAILURE
        result.error = "Post-merge tests failed; integration rolled back"
        result.completed_at = datetime.now(timezone.utc).isoformat()
        _write_report(result, report_path, task_branch, target_branch)
        return result

    # ── 5. Push the target branch ────────────────────────────────────
    push_ok, push_err = _push_target(cwd_str, target_branch, remote_name)
    result.push_succeeded = push_ok

    if not push_ok:
        result.reason = TARGET_PUSH_FAILED
        result.error = f"Push failed: {push_err}"
        result.completed_at = datetime.now(timezone.utc).isoformat()
        _write_report(result, report_path, task_branch, target_branch)
        return result

    # ── 6. Remote containment verification ────────────────────────────
    # Confirm the remote target branch contains the task commit.
    remote_contains = _verify_remote_contains(
        cwd_str, remote_name, target_branch, task_commit
    )
    result.remote_contains = remote_contains

    if not remote_contains:
        result.reason = TARGET_CONTAINS_CHECK_FAILED
        result.error = (
            f"Remote '{remote_name}/{target_branch}' does not contain "
            f"task commit {task_commit}"
        )
        result.completed_at = datetime.now(timezone.utc).isoformat()
        _write_report(result, report_path, task_branch, target_branch)
        return result

    # ── Success ──────────────────────────────────────────────────────
    result.success = True
    result.completed_at = datetime.now(timezone.utc).isoformat()
    _write_report(result, report_path, task_branch, target_branch)
    return result


# ── Sub-steps ────────────────────────────────────────────────────────────────


def _fetch_remote(cwd: str, remote_name: str) -> tuple[bool, str]:
    """Fetch from the remote so refs are current. Returns (success, error)."""
    code, _, err = _run_git(cwd, ["fetch", remote_name])
    if code != 0:
        return False, err.strip()
    return True, ""


def checkout_target(cwd: str, target_branch: str, target_ref: str) -> None:
    """Ensure the local target branch is checked out and at the remote tip.

    If the local branch doesn't exist, create it from the remote ref.
    If it exists, check it out as-is (the caller is responsible for ensuring
    it's up to date — in the normal flow the local target is a fresh checkout
    from the remote, so it equals ``origin/<target_branch>``).

    We deliberately do NOT ``git branch -f`` the local target: that would
    discard any unpushed work on the target branch, which is not safe.
    """
    # Check if the local target branch exists.
    code, _, _ = _run_git(cwd, ["rev-parse", "--verify", target_branch])
    if code != 0:
        # Local branch doesn't exist — create from remote ref.
        _git_ok(cwd, ["branch", target_branch, target_ref])
    _git_ok(cwd, ["checkout", target_branch])


def _is_merge_conflict(merge_stderr: str) -> bool:
    """Detect whether a merge failure was due to conflicts (vs. other error)."""
    if not merge_stderr:
        return False
    lower = merge_stderr.lower()
    return (
        "conflict" in lower
        or "CONFLICT" in merge_stderr
        or "Resolve all conflicts" in merge_stderr
        or "fix conflicts" in lower
    )


def _get_conflicted_files(cwd: str) -> list[str]:
    """Return the set of currently conflicted (unmerged) file paths."""
    out = _git_out(cwd, ["diff", "--name-only", "--diff-filter=U"])
    if not out:
        return []
    return out.splitlines()


def _run_post_merge_tests(cwd: str, test_command: Optional[str]) -> tuple[bool, Optional[str]]:
    """Run the post-merge test suite. Returns (passed, output).

    If ``test_command`` is None, tests are considered skipped (returned as
    passed=True with no output) — the caller should always supply a command
    for real integration.
    """
    if not test_command:
        return True, None

    env = dict(os.environ)
    env["GIT_TERMINAL_PROMPT"] = "0"
    try:
        proc = subprocess.run(
            test_command,
            shell=True,
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=_GIT_TIMEOUT * 5,
            stdin=subprocess.DEVNULL,
            env=env,
        )
        output = (proc.stdout or "") + (proc.stderr or "")
        return proc.returncode == 0, output
    except subprocess.TimeoutExpired:
        return False, "TIMEOUT"
    except OSError as exc:
        return False, str(exc)


def _rollback_target(cwd: str, pre_merge_sha: str) -> None:
    """Reset the target branch hard to the pre-merge SHA."""
    _git_ok(cwd, ["reset", "--hard", pre_merge_sha])


def _push_target(cwd: str, target_branch: str, remote_name: str) -> tuple[bool, str]:
    """Push the target branch to the remote. Returns (success, error)."""
    code, _, err = _run_git(cwd, ["push", remote_name, target_branch])
    if code != 0:
        return False, err.strip()
    return True, ""


def _verify_remote_contains(
    cwd: str,
    remote_name: str,
    target_branch: str,
    task_commit: str,
) -> bool:
    """Verify the remote target branch contains the task commit.

    Uses ``git branch -r --contains <sha>`` after a fetch and checks that
    ``<remote>/<target_branch>`` appears in the output.
    """
    code, out, _ = _run_git(cwd, ["fetch", remote_name])
    if code != 0:
        return False
    code, out, _ = _run_git(
        cwd, ["branch", "-r", "--contains", task_commit]
    )
    if code != 0:
        return False
    expected = f"{remote_name}/{target_branch}"
    for line in out.splitlines():
        if line.strip() == expected or line.strip().endswith(expected):
            return True
    return False


# ── Report serialisation ─────────────────────────────────────────────────────


def _write_report(
    result: IntegrationResult,
    report_path: Optional[str | Path],
    task_branch: Optional[str],
    target_branch: Optional[str],
) -> None:
    """Populate ``result.report`` and write ``integration_report.json`` if requested."""
    report: dict[str, Any] = {
        "success": result.success,
        "reason": result.reason,
        "error": result.error,
        "target_branch": target_branch,
        "task_branch": task_branch,
        "task_commit": result.task_commit,
        "target_before": result.target_before,
        "target_after": result.target_after,
        "merge_strategy": result.merge_strategy,
        "merge_commit": result.merge_commit,
        "conflicts": result.conflicts,
        "tests_passed": result.tests_passed,
        "test_command": result.test_command,
        "push_succeeded": result.push_succeeded,
        "remote_contains": result.remote_contains,
        "started_at": result.started_at,
        "completed_at": result.completed_at,
    }
    result.report = report

    if report_path is not None:
        path = Path(report_path)
        path.mkdir(parents=True, exist_ok=True)
        report_file = path / "integration_report.json"
        atomic_write(
            report_file,
            json.dumps(report, indent=2, ensure_ascii=False),
        )
        result._report_path = report_file  # type: ignore[attr-defined]


# ── Convenience: run integration with a default test command ─────────────────


def integrate_task(
    cwd: str,
    *,
    task_branch: Optional[str] = None,
    target_branch: Optional[str] = None,
    test_command: str = "uv run pytest tests/ -v",
    report_path: Optional[str | Path] = None,
    remote_name: str = "origin",
) -> IntegrationResult:
    """Convenience wrapper around :func:`integrate_branch` with a default
    test command.

    This is the primary entry point for the completion flow (Phase 5).
    """
    return integrate_branch(
        cwd,
        task_branch=task_branch,
        target_branch=target_branch,
        test_command=test_command,
        report_path=report_path,
        remote_name=remote_name,
    )
