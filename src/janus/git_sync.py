"""Repository synchronization primitive for task branches.

Implements Phase 1 (Pre-Implementation Sync) of the safe sync-and-integrate
workflow (see docs/sync_integration_workflow_design.md, §4.1).

Brings a task branch up to date against the current target branch before
implementation begins, using rebase (not merge) to keep history linear and
integration fast-forward-friendly.

This module is narrowly scoped to the *sync* primitive only. It does not
orchestrate the full workflow (verification, integration, completion gating).
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


# ── Reason codes (mirror docs/sync_integration_workflow_design.md §5.1) ──────

# Target branch not found on the remote or locally.
TARGET_BRANCH_MISSING = "target_branch_missing"
# Rebase produced conflicts the primitive must not auto-resolve.
SYNC_CONFLICT = "sync_conflict"
# Force-push was rejected (e.g. by --force-with-lease lease check).
SYNC_PUSH_FAILED = "sync_push_failed"
# Rebase did not produce the expected linear history (diverged unexpectedly).
REBASE_DIVERGED = "rebase_diverged_unexpectedly"
# Everything was already up to date; no changes needed.
ALREADY_UP_TO_DATE = "already_up_to_date"


# ── Result model ─────────────────────────────────────────────────────────────


@dataclass
class SyncResult:
    """Outcome of a repository synchronization attempt.

    ``success`` is True only when the task branch was rebased onto the target
    and pushed successfully (or was already up to date). On failure, ``reason``
    carries a structured code from the module-level ``*_REASON`` constants and
    ``error`` holds the human-readable output (git stderr / status text).
    """

    success: bool = False
    reason: Optional[str] = None
    target_branch: Optional[str] = None
    task_branch: Optional[str] = None
    merge_base: Optional[str] = None
    target_commit: Optional[str] = None
    conflicts: list[str] = field(default_factory=list)
    error: Optional[str] = None


# ── Git helpers ──────────────────────────────────────────────────────────────

_GIT_TIMEOUT = 60


def _run_git(
    cwd: str,
    args: list[str],
    *,
    timeout: int = _GIT_TIMEOUT,
) -> tuple[int, str, str]:
    """Run a git command non-interactively. Returns (returncode, stdout, stderr).

    Mirrors the pattern in ``hermes_cli/web_git.py:_git``: stdin is nulled and
    ``GIT_TERMINAL_PROMPT=0`` is set so that a credential prompt from fetch/push
    fails fast instead of hanging.
    """
    env = dict(os.environ)
    env["GIT_TERMINAL_PROMPT"] = "0"
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            stdin=subprocess.DEVNULL,
            env=env,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        return 1, "", str(exc)
    return proc.returncode, proc.stdout, proc.stderr


def _git_ok(cwd: str, args: list[str]) -> str:
    """Run a git command, raising RuntimeError with stderr on failure."""
    code, out, err = _run_git(cwd, args)
    if code != 0:
        raise RuntimeError(err.strip() or f"git {' '.join(args)} failed")
    return out.strip()


def _git_out(cwd: str, args: list[str]) -> str:
    """stdout of a git command, or ``""`` on any failure."""
    code, out, _ = _run_git(cwd, args)
    return out.strip() if code == 0 else ""


def _git_conflict_ok(cwd: str, args: list[str]) -> tuple[int, str, str]:
    """Run a git command that may return non-zero due to conflicts.

    Unlike ``_git_ok``, a non-zero return from a rebase that ends in conflict
    is NOT a hard failure — the caller inspects the exit code and output to
    determine whether conflicts occurred.
    """
    return _run_git(cwd, args)


# ── Target branch detection ──────────────────────────────────────────────────


def detect_target_branch(cwd: str) -> Optional[str]:
    """Resolve the repository's target (trunk) branch name.

    Resolution order per docs/sync_integration_workflow_design.md §3:
      1. ``origin/HEAD`` (symbolic ref to remote default)
      2. local ``main``
      3. local ``master``
      4. ``refs/remotes/origin/main``
      5. ``refs/remotes/origin/master``

    Returns the branch name (without ``origin/`` prefix) or ``None`` if no
    candidate ref exists. Callers should treat ``None`` as
    ``TARGET_BRANCH_MISSING``.
    """
    # 1. origin/HEAD symbolic ref
    head = _git_out(cwd, ["rev-parse", "--abbrev-ref", "origin/HEAD"])
    if head and head != "origin/HEAD":
        # e.g. "origin/master" → "master"
        if "/" in head:
            return head.split("/", 1)[1]
        return head

    # 2-5. Explicit ref checks
    candidates = [
        ("refs/heads/main", "main"),
        ("refs/heads/master", "master"),
        ("refs/remotes/origin/main", "main"),
        ("refs/remotes/origin/master", "master"),
    ]
    for ref, name in candidates:
        code, _, _ = _run_git(cwd, ["rev-parse", "--verify", "--quiet", ref])
        if code == 0:
            return name

    return None


def detect_task_branch(cwd: str) -> Optional[str]:
    """Return the current branch name, or ``None`` if detached HEAD."""
    branch = _git_out(cwd, ["rev-parse", "--abbrev-ref", "HEAD"])
    if branch and branch != "HEAD":
        return branch
    return None


# ── Core sync primitive ──────────────────────────────────────────────────────


def fetch_target(cwd: str, target_branch: str) -> tuple[bool, str]:
    """Fetch the remote target branch.

    Returns (success, error_message). On success, ``origin/<target_branch>``
    is updated to the latest remote state.
    """
    code, _, err = _git_conflict_ok(
        cwd, ["fetch", "origin", target_branch]
    )
    if code != 0:
        return False, err.strip()
    return True, ""


def merge_base_exists(cwd: str, task_branch: str, target_ref: str) -> bool:
    """Return True if a merge-base exists between task and target."""
    base = _git_out(cwd, ["merge-base", task_branch, target_ref])
    return bool(base)


def is_branch_stale(cwd: str, task_branch: str, target_ref: str) -> bool:
    """Detect whether the task branch has fallen behind the target branch.

    The branch is stale when ``merge-base <task> <target>`` is an ancestor of
    ``<target>`` but NOT an ancestor of ``<task>`` — i.e. the target has
    commits the task branch does not.
    """
    base = _git_out(cwd, ["merge-base", task_branch, target_ref])
    if not base:
        return True  # no common base — treat as stale/diverged

    # If base == target tip, target hasn't advanced past the merge point.
    target_tip = _git_out(cwd, ["rev-parse", target_ref])
    if base == target_tip:
        return False  # target hasn't moved since the merge point

    # If base is an ancestor of the task branch, the task branch already
    # contains everything up to the merge point. Staleness means the target
    # tip is NOT an ancestor of the task branch (task is behind target).
    task_tip = _git_out(cwd, ["rev-parse", task_branch])
    if base == task_tip:
        return False  # task branch hasn't moved at all — no rebase needed
        # (but if target advanced, this should be caught below)

    # Check if target_tip is an ancestor of task_tip.
    # If yes, task already contains target's latest → not stale.
    # If no, task is behind → stale.
    code, _, _ = _run_git(
        cwd,
        ["merge-base", "--is-ancestor", target_tip, task_tip],
    )
    if code == 0:
        return False  # target tip is in task's history → up to date
    return True


def _get_conflicted_files(cwd: str) -> list[str]:
    """Return the set of currently conflicted (unmerged) file paths."""
    out = _git_out(cwd, ["diff", "--name-only", "--diff-filter=U"])
    if not out:
        return []
    return out.splitlines()


def abort_rebase(cwd: str) -> None:
    """Abort an in-progress rebase to restore a clean state."""
    _run_git(cwd, ["rebase", "--abort"])


def rebase_onto_target(
    cwd: str,
    task_branch: str,
    target_ref: str,
) -> tuple[int, str]:
    """Rebase the task branch onto the target ref.

    Returns (returncode, stderr). A non-zero return code with conflict text
    indicates the rebase stopped on conflicts.
    """
    code, _, err = _git_conflict_ok(cwd, ["rebase", target_ref])
    return code, err


def force_push(cwd: str, task_branch: str) -> tuple[bool, str]:
    """Force-push the task branch with lease protection.

    Returns (success, error_message).
    """
    code, _, err = _git_conflict_ok(
        cwd, ["push", "origin", task_branch, "--force-with-lease"]
    )
    if code != 0:
        return False, err.strip()
    return True, ""


def sync_branch(
    cwd: str,
    target_branch: Optional[str] = None,
) -> SyncResult:
    """Synchronize a task branch against the current target branch.

    Implements Phase 1 (Pre-Implementation Sync):

    1. Detect the target branch (configurable or auto-detected).
    2. Fetch the remote target branch.
    3. Detect staleness via ``git merge-base``.
    4. If stale, rebase the task branch onto the target.
       If the rebase produces conflicts, abort and return a
       ``SYNC_CONFLICT`` result (do NOT auto-resolve).
    5. Force-push the rebased branch (``--force-with-lease``).

    Args:
        cwd: Path to the repository (or worktree) to sync.
        target_branch: Explicit target branch name. If ``None``, it is
            auto-detected via :func:`detect_target_branch`.

    Returns:
        A :class:`SyncResult` with the outcome.

    Failure modes (per docs/sync_integration_workflow_design.md §5.1):
        * ``TARGET_BRANCH_MISSING`` — the target branch could not be found.
        * ``SYNC_CONFLICT`` — the rebase produced conflicts.
        * ``SYNC_PUSH_FAILED`` — the force-push was rejected.
        * ``REBASE_DIVERGED`` — the rebase exited unexpectedly.
        * ``ALREADY_UP_TO_DATE`` — no rebase was needed (success, no-op).
    """
    cwd_str = str(cwd)

    # ── 1. Resolve the target branch ─────────────────────────────────────
    if target_branch is None:
        target_branch = detect_target_branch(cwd_str)

    if not target_branch:
        return SyncResult(
            success=False,
            reason=TARGET_BRANCH_MISSING,
            error="No target branch could be detected or provided",
        )

    task_branch = detect_task_branch(cwd_str)
    if not task_branch:
        return SyncResult(
            success=False,
            reason=TARGET_BRANCH_MISSING,
            error="Cannot sync in detached HEAD state",
        )

    target_ref = f"origin/{target_branch}"

    # ── 2. Fetch the remote target branch ───────────────────────────────
    ok, fetch_err = fetch_target(cwd_str, target_branch)
    if not ok:
        # Distinguish "branch doesn't exist on remote" from other fetch errors.
        if "couldn't find" in fetch_err.lower() or "not found" in fetch_err.lower():
            return SyncResult(
                success=False,
                reason=TARGET_BRANCH_MISSING,
                target_branch=target_branch,
                task_branch=task_branch,
                error=f"Remote branch '{target_ref}' not found: {fetch_err}",
            )
        return SyncResult(
            success=False,
            reason=TARGET_BRANCH_MISSING,
            target_branch=target_branch,
            task_branch=task_branch,
            error=f"Fetch failed: {fetch_err}",
        )

    # Record pre-sync commits for the result.
    merge_base = _git_out(cwd_str, ["merge-base", task_branch, target_ref])
    target_commit = _git_out(cwd_str, ["rev-parse", target_ref])

    # ── 3. Detect staleness ─────────────────────────────────────────────
    if not is_branch_stale(cwd_str, task_branch, target_ref):
        return SyncResult(
            success=True,
            reason=ALREADY_UP_TO_DATE,
            target_branch=target_branch,
            task_branch=task_branch,
            merge_base=merge_base,
            target_commit=target_commit,
            error=None,
        )

    # ── 4. Rebase onto target ───────────────────────────────────────────
    code, rebase_err = rebase_onto_target(cwd_str, task_branch, target_ref)

    if code != 0:
        # Check if this is a conflict (git sets exit code 1 and prints
        # conflict markers / instructions).
        if "Conflict" in rebase_err or "conflict" in rebase_err.lower() or "CONFLICT" in rebase_err:
            conflicts = _get_conflicted_files(cwd_str)
            abort_rebase(cwd_str)
            return SyncResult(
                success=False,
                reason=SYNC_CONFLICT,
                target_branch=target_branch,
                task_branch=task_branch,
                merge_base=merge_base,
                conflicts=conflicts,
                error=rebase_err.strip(),
            )
        # Non-conflict rebase failure — diverged unexpectedly.
        abort_rebase(cwd_str)
        return SyncResult(
            success=False,
            reason=REBASE_DIVERGED,
            target_branch=target_branch,
            task_branch=task_branch,
            merge_base=merge_base,
            error=rebase_err.strip(),
        )

    # └─ Rebase succeeded; verify the rebase produced the expected result ─┘
    new_base = _git_out(cwd_str, ["merge-base", task_branch, target_ref])
    if new_base != target_commit:
        # The merge-base after rebase should equal the target tip.
        # If it doesn't, something diverged unexpectedly.
        abort_rebase(cwd_str)
        return SyncResult(
            success=False,
            reason=REBASE_DIVERGED,
            target_branch=target_branch,
            task_branch=task_branch,
            merge_base=merge_base,
            error=(
                f"Rebase completed but merge-base ({new_base}) does not "
                f"match target tip ({target_commit})"
            ),
        )

    # ── 5. Force-push with lease ────────────────────────────────────────
    ok, push_err = force_push(cwd_str, task_branch)
    if not ok:
        # Abort the rebase state isn't needed (rebase succeeded), but we
        # leave the local rebase intact for the caller to inspect.
        return SyncResult(
            success=False,
            reason=SYNC_PUSH_FAILED,
            target_branch=target_branch,
            task_branch=task_branch,
            merge_base=new_base,
            target_commit=target_commit,
            error=f"Force-push failed: {push_err}",
        )

    return SyncResult(
        success=True,
        reason=None,
        target_branch=target_branch,
        task_branch=task_branch,
        merge_base=new_base,
        target_commit=target_commit,
        error=None,
    )
