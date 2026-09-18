"""Tests for the repository integration primitive (integration.py).

These tests create real temporary git repositories with remotes and branches
to exercise the integrate_branch / integrate_task primitives end-to-end,
covering:

  - Fast-forward merge (task branch ahead of target, no divergence).
  - Controlled merge fallback (--no-ff) when local target has diverged.
  - Merge conflict → abort → INTEGRATION_CONFLICT, rollback preserved.
  - Post-merge test failure → rollback → POST_INTEGRATION_TEST_FAILURE.
  - Push failure → TARGET_PUSH_FAILED.
  - Remote containment check passes on success.
  - Target branch not integrated → TARGET_NOT_INTEGRATED.
  - Report file generation (integration_report.json).
  - Detached HEAD → INTEGRATION_SETUP_FAILED.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from janus.integration import (
    INTEGRATION_CONFLICT,
    INTEGRATION_SETUP_FAILED,
    POST_INTEGRATION_TEST_FAILURE,
    TARGET_CONTAINS_CHECK_FAILED,
    TARGET_NOT_INTEGRATED,
    TARGET_PUSH_FAILED,
    integrate_branch,
)


# ── Helpers ──────────────────────────────────────────────────────────────────


def _git(cwd: str, *args: str) -> subprocess.CompletedProcess:
    """Run a git command in cwd, returning the CompletedProperty."""
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdin=subprocess.DEVNULL,
        env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
        timeout=30,
        check=False,
    )


def _git_ok(cwd: str, *args: str) -> str:
    result = _git(cwd, *args)
    assert result.returncode == 0, (
        f"git {args} failed: {result.stderr.strip()}"
    )
    return result.stdout.strip()


def _make_remote(tmp_path: Path, name: str = "origin") -> str:
    """Create a bare git repo to act as a remote."""
    remote_dir = tmp_path / f"remote-{name}"
    remote_dir.mkdir()
    _git_ok(str(remote_dir), "init", "--bare", "--initial-branch=master")
    return str(remote_dir)


def _init_repo(tmp_path: Path, default_branch: str = "master") -> str:
    """Create a local repo with an initial commit on the default branch."""
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    _git_ok(str(repo_dir), "init", "--initial-branch", default_branch)
    _git_ok(str(repo_dir), "config", "user.email", "test@test.com")
    _git_ok(str(repo_dir), "config", "user.name", "Test User")
    (repo_dir / "file.txt").write_text("initial\n")
    _git_ok(str(repo_dir), "add", "file.txt")
    _git_ok(str(repo_dir), "commit", "-m", "initial commit")
    return str(repo_dir)


def _setup_remote_origin(cwd: str, remote_path: str) -> None:
    """Add a remote named 'origin' and push the default branch."""
    _git_ok(cwd, "remote", "add", "origin", remote_path)
    _git_ok(cwd, "fetch", "origin")
    _git_ok(cwd, "branch", "-M", "master")
    _git_ok(cwd, "push", "-u", "origin", "master")


def _commit(cwd: str, message: str, content: str = "hello\n", filename: str = "file.txt") -> str:
    """Create or modify a file and commit it. Returns the new HEAD SHA."""
    fpath = Path(cwd) / filename
    fpath.write_text(content)
    _git_ok(cwd, "add", filename)
    _git_ok(cwd, "commit", "-m", message)
    return _git_ok(cwd, "rev-parse", "HEAD")


def _checkout_branch(cwd: str, branch: str, base: str = "master") -> None:
    """Create and checkout a branch from base."""
    _git_ok(cwd, "checkout", base)
    _git_ok(cwd, "checkout", "-b", branch)


# ── Integration: fast-forward success ─────────────────────────────────────────


class TestFastForwardMerge:
    def test_fast_forward_merge_success(self, tmp_path):
        """Task branch is ahead of target → ff-only merge succeeds."""
        repo = _init_repo(tmp_path)
        remote = _make_remote(tmp_path)
        _setup_remote_origin(repo, remote)

        # Create task branch with a commit
        _checkout_branch(repo, "wt/task")
        _commit(repo, "task: add feature", content="feature\n", filename="feature.py")
        _git_ok(repo, "push", "origin", "wt/task")

        result = integrate_branch(repo, test_command=None)
        assert result.success is True
        assert result.reason is None
        assert result.merge_strategy == "fast_forward"
        assert result.target_branch == "master"
        assert result.task_branch == "wt/task"
        assert result.target_after is not None
        assert result.remote_contains is True
        assert result.push_succeeded is True

    def test_fast_forward_with_test_command(self, tmp_path):
        """Post-merge test command runs and passes → integration succeeds."""
        repo = _init_repo(tmp_path)
        remote = _make_remote(tmp_path)
        _setup_remote_origin(repo, remote)

        _checkout_branch(repo, "wt/task")
        _commit(repo, "task: add feature", content="feature\n", filename="feature.py")
        _git_ok(repo, "push", "origin", "wt/task")

        result = integrate_branch(repo, test_command="true")
        assert result.success is True
        assert result.tests_passed is True
        assert result.test_command == "true"


# ── Integration: controlled merge fallback (--no-ff) ──────────────────────────


class TestControlledMerge:
    def test_merge_fallback_when_local_target_diverged(self, tmp_path):
        """When the local target branch has unpushed commits, --ff-only fails
        and the controlled --no-ff merge path is taken."""
        repo = _init_repo(tmp_path)
        remote = _make_remote(tmp_path)
        _setup_remote_origin(repo, remote)

        # Task branch with a commit that doesn't conflict
        _checkout_branch(repo, "wt/task")
        _commit(repo, "task: add feature", content="feature\n", filename="feature.py")
        _git_ok(repo, "push", "origin", "wt/task")

        # On master, add an unpushed commit to the LOCAL target (not pushed
        # to origin).  This makes local master diverge from origin/master.
        _git_ok(repo, "checkout", "master")
        _commit(repo, "local: target-only change", content="local\n", filename="local.txt")

        # Fetch so origin refs are current, then checkout task branch
        # The task branch contains origin/master but NOT local master's new commit.
        _git_ok(repo, "fetch", "origin")

        result = integrate_branch(repo, task_branch="wt/task", test_command=None)
        assert result.success is True
        # ff-only should fail (local master has commit D not on origin/wt/task)
        # → --no-ff merge is used
        assert result.merge_strategy == "merge"
        assert result.merge_commit is not None


# ── Integration: merge conflict ────────────────────────────────────────────────


class TestIntegrationConflict:
    def test_merge_conflict_aborts_and_blocks(self, tmp_path):
        """A merge conflict during --no-ff aborts and returns INTEGRATION_CONFLICT."""
        repo = _init_repo(tmp_path)
        remote = _make_remote(tmp_path)
        _setup_remote_origin(repo, remote)

        # Task branch modifies conf.txt
        _checkout_branch(repo, "wt/task")
        Path(repo, "conf.txt").write_text("line1\ntask line2\nline3\n")
        _git_ok(repo, "add", "conf.txt")
        _git_ok(repo, "commit", "-m", "task: modify conf")
        _git_ok(repo, "push", "origin", "wt/task")

        # Add an unpushed LOCAL commit to master that conflicts with the task
        # branch's change to conf.txt.  This makes --ff-only fail (local master
        # has a commit origin/wt/task doesn't), triggering --no-ff, which then
        # conflicts.
        _git_ok(repo, "checkout", "master")
        Path(repo, "conf.txt").write_text("line1\nmaster line2\nline3\n")
        _git_ok(repo, "add", "conf.txt")
        _git_ok(repo, "commit", "-m", "master: conflicting change")

        _git_ok(repo, "fetch", "origin")

        result = integrate_branch(repo, task_branch="wt/task", test_command=None)
        assert result.success is False
        assert result.reason == INTEGRATION_CONFLICT
        assert "conf.txt" in result.conflicts
        assert result.error is not None

        # Target should be restored (merge aborted) — no "Merge task branch" commit
        log = _git_ok(repo, "log", "--oneline")
        assert "Merge task branch" not in log

    def test_merge_conflict_report_written(self, tmp_path):
        """The report is written even on conflict."""
        repo = _init_repo(tmp_path)
        remote = _make_remote(tmp_path)
        _setup_remote_origin(repo, remote)

        _checkout_branch(repo, "wt/task")
        Path(repo, "conf.txt").write_text("line1\ntask line2\nline3\n")
        _git_ok(repo, "add", "conf.txt")
        _git_ok(repo, "commit", "-m", "task: modify conf")
        _git_ok(repo, "push", "origin", "wt/task")

        _git_ok(repo, "checkout", "master")
        Path(repo, "conf.txt").write_text("line1\nmaster line2\nline3\n")
        _git_ok(repo, "add", "conf.txt")
        _git_ok(repo, "commit", "-m", "master: conflicting change")

        _git_ok(repo, "fetch", "origin")

        report_dir = tmp_path / "reports"
        result = integrate_branch(repo, task_branch="wt/task", test_command=None, report_path=report_dir)

        assert result.reason == INTEGRATION_CONFLICT
        report_file = report_dir / "integration_report.json"
        assert report_file.exists()
        report = json.loads(report_file.read_text())
        assert report["success"] is False
        assert report["reason"] == INTEGRATION_CONFLICT
        assert "conf.txt" in report["conflicts"]
        assert report["merge_strategy"] == "merge"


# ── Integration: post-merge test failure ──────────────────────────────────────


class TestPostMergeTestFailure:
    def test_post_merge_test_failure_rolls_back(self, tmp_path):
        """Post-merge test failure triggers rollback and POST_INTEGRATION_TEST_FAILURE."""
        repo = _init_repo(tmp_path)
        remote = _make_remote(tmp_path)
        _setup_remote_origin(repo, remote)

        # Record the target commit before integration
        _git_ok(repo, "checkout", "master")
        pre_merge_target = _git_ok(repo, "rev-parse", "master")

        _checkout_branch(repo, "wt/task")
        _commit(repo, "task: add feature", content="feature\n", filename="feature.py")
        _git_ok(repo, "push", "origin", "wt/task")

        result = integrate_branch(repo, test_command="false")
        assert result.success is False
        assert result.reason == POST_INTEGRATION_TEST_FAILURE
        assert result.tests_passed is False

        # Target should be rolled back to pre-merge state
        _git_ok(repo, "checkout", "master")
        post_rollback = _git_ok(repo, "rev-parse", "master")
        assert post_rollback == pre_merge_target, (
            "Target should be rolled back to pre-merge SHA after test failure"
        )

    def test_post_merge_test_failure_report(self, tmp_path):
        """Report is written on test failure with the right reason code."""
        repo = _init_repo(tmp_path)
        remote = _make_remote(tmp_path)
        _setup_remote_origin(repo, remote)

        _checkout_branch(repo, "wt/task")
        _commit(repo, "task work")
        _git_ok(repo, "push", "origin", "wt/task")

        report_dir = tmp_path / "reports"
        result = integrate_branch(repo, test_command="false", report_path=report_dir)

        assert result.reason == POST_INTEGRATION_TEST_FAILURE
        report_file = report_dir / "integration_report.json"
        assert report_file.exists()
        report = json.loads(report_file.read_text())
        assert report["tests_passed"] is False
        assert report["reason"] == POST_INTEGRATION_TEST_FAILURE


# ── Integration: target not integrated (stale) ────────────────────────────────


class TestTargetNotIntegrated:
    def test_stale_task_branch_blocked(self, tmp_path):
        """If the task branch is behind target, TARGET_NOT_INTEGRATED is returned."""
        repo = _init_repo(tmp_path)
        remote = _make_remote(tmp_path)
        _setup_remote_origin(repo, remote)

        # Create task branch, push it
        _checkout_branch(repo, "wt/task")
        _commit(repo, "task: early commit", content="task\n", filename="task.txt")
        _git_ok(repo, "push", "origin", "wt/task")

        # Advance target (master) on the remote — task branch is now behind
        _git_ok(repo, "checkout", "master")
        _commit(repo, "target: late commit", content="target\n", filename="target.txt")
        _git_ok(repo, "push", "origin", "master")

        # Fetch so integration sees the updated remote
        _git_ok(repo, "fetch", "origin")

        result = integrate_branch(repo, task_branch="wt/task", test_command=None)
        assert result.success is False
        assert result.reason == TARGET_NOT_INTEGRATED
        assert result.error is not None
        assert "target" in (result.error or "").lower() or "sync" in (result.error or "").lower()


# ── Integration: setup failures ───────────────────────────────────────────────


class TestSetupFailures:
    def test_detached_head_fails(self, tmp_path):
        """Integration on detached HEAD fails with INTEGRATION_SETUP_FAILED."""
        repo = _init_repo(tmp_path)
        remote = _make_remote(tmp_path)
        _setup_remote_origin(repo, remote)

        _checkout_branch(repo, "wt/task")
        _commit(repo, "task work")
        _git_ok(repo, "push", "origin", "wt/task")

        # Detach HEAD — detect_task_branch will return None
        _git_ok(repo, "checkout", "master")
        _git_ok(repo, "checkout", "--detach", "HEAD")
        _git_ok(repo, "fetch", "origin")

        # With no explicit task_branch, the detached HEAD is detected
        result = integrate_branch(repo, test_command=None)
        assert result.success is False
        assert result.reason == INTEGRATION_SETUP_FAILED
        assert "detached" in (result.error or "").lower()


# ── Integration: report generation ───────────────────────────────────────────


class TestReportGeneration:
    def test_report_written_on_success(self, tmp_path):
        """integration_report.json is written on successful integration."""
        repo = _init_repo(tmp_path)
        remote = _make_remote(tmp_path)
        _setup_remote_origin(repo, remote)

        _checkout_branch(repo, "wt/task")
        _commit(repo, "task: add feature", content="feature\n", filename="feature.py")
        _git_ok(repo, "push", "origin", "wt/task")

        report_dir = tmp_path / "reports"
        result = integrate_branch(repo, test_command=None, report_path=report_dir)

        assert result.success is True
        report_file = Path(report_dir) / "integration_report.json"
        assert report_file.exists()
        report = json.loads(report_file.read_text())
        assert report["success"] is True
        assert report["merge_strategy"] == "fast_forward"
        assert report["target_branch"] == "master"
        assert report["task_branch"] == "wt/task"
        assert report["push_succeeded"] is True
        assert report["remote_contains"] is True

    def test_report_written_on_failure(self, tmp_path):
        """integration_report.json is written even on failure."""
        repo = _init_repo(tmp_path)
        remote = _make_remote(tmp_path)
        _setup_remote_origin(repo, remote)

        _checkout_branch(repo, "wt/task")
        _commit(repo, "task work")
        _git_ok(repo, "push", "origin", "wt/task")

        report_dir = tmp_path / "reports"
        result = integrate_branch(repo, test_command="false", report_path=report_dir)

        report_file = Path(report_dir) / "integration_report.json"
        assert report_file.exists()
        report = json.loads(report_file.read_text())
        assert report["success"] is False
        assert report["reason"] == POST_INTEGRATION_TEST_FAILURE

    def test_report_dict_always_populated(self, tmp_path):
        """The result.report dict is always populated regardless of path."""
        repo = _init_repo(tmp_path)
        remote = _make_remote(tmp_path)
        _setup_remote_origin(repo, remote)

        _checkout_branch(repo, "wt/task")
        _commit(repo, "task work")
        _git_ok(repo, "push", "origin", "wt/task")

        result = integrate_branch(repo, test_command=None, report_path=None)
        assert result.report
        assert "success" in result.report
        assert "reason" in result.report
        assert "merge_strategy" in result.report


# ── Integration: remote containment ───────────────────────────────────────────


class TestRemoteContainment:
    def test_remote_contains_check_passes(self, tmp_path):
        """After push, the remote target branch contains the task commit."""
        repo = _init_repo(tmp_path)
        remote = _make_remote(tmp_path)
        _setup_remote_origin(repo, remote)

        _checkout_branch(repo, "wt/task")
        task_commit = _commit(repo, "task: add feature", content="feature\n", filename="feature.py")
        _git_ok(repo, "push", "origin", "wt/task")

        result = integrate_branch(repo, test_command=None)
        assert result.success is True
        assert result.remote_contains is True

        # Independently verify the remote contains the commit
        _git_ok(repo, "fetch", "origin")
        branches = _git_ok(repo, "branch", "-r", "--contains", task_commit)
        assert "origin/master" in branches


# ── Integration: fast-forward no-op (already integrated) ──────────────────────


class TestEdgeCases:
    def test_integrate_branch_already_contains_target(self, tmp_path):
        """Task branch with same content as target → ff succeeds (no-op)."""
        repo = _init_repo(tmp_path)
        remote = _make_remote(tmp_path)
        _setup_remote_origin(repo, remote)

        # Task branch with no new commits (just branched from master and pushed)
        _checkout_branch(repo, "wt/task")
        _git_ok(repo, "push", "origin", "wt/task")
        _git_ok(repo, "fetch", "origin")

        result = integrate_branch(repo, task_branch="wt/task", test_command=None)
        # Git says "Already up to date" and exits 0
        assert result.success is True


# ── Integration: push failure ─────────────────────────────────────────────────


class TestPushFailure:
    def test_push_failure_returns_reason(self, tmp_path):
        """If the target push fails, TARGET_PUSH_FAILED is returned.

        We simulate push failure by making the remote bare repo read-only
        (removing write permission) after it has been set up.  The fetch
        succeeds (read-only access), but the push is rejected.
        """
        repo = _init_repo(tmp_path)
        remote = _make_remote(tmp_path)
        _setup_remote_origin(repo, remote)

        _checkout_branch(repo, "wt/task")
        _commit(repo, "task: add feature", content="feature\n", filename="feature.py")
        _git_ok(repo, "push", "origin", "wt/task")

        # Make the remote read-only so pushes fail but fetches work
        remote_dir = Path(remote)
        # Remove write permission from the remote directory
        os.chmod(str(remote_dir), 0o555)

        result = integrate_branch(repo, test_command=None)
        assert result.success is False
        assert result.reason == TARGET_PUSH_FAILED
        assert result.error is not None
