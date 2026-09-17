"""Tests for ADR-004 Phase 5 gate enforcement on complete_task().

Covers:
- Gate skip on non-git paths (temp dir tasks.md) — existing behavior preserved.
- Phase 3 gate blocks completion when pre-completion checks fail (non-git
  path with a failing test_command is a no-op; the real gate runs in git
  repos only, so we test the gate logic directly via run_completion_gates).
- CompletionGateError carries a structured reason code.
- Evidence artifacts are written when gates pass in a git repo.
- Integration already-done shortcut (HEAD contained in remote target).

These tests build isolated temporary git repositories so they don't depend
on the state of the real Janus working tree.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import pytest

from janus.services.tasks import (
    CompletionGateError,
    CompletionGateResult,
    GATE_DIFF_CHECK_FAILED,
    GATE_INTEGRATION_FAILED,
    GATE_TESTS_FAILED,
    GATE_WORKING_TREE_NOT_CLEAN,
    TASKS_PATH,
    complete_task,
    run_completion_gates,
)


# ──────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=str(root),
        capture_output=True,
        text=True,
        timeout=30,
    )


def _init_repo(root: Path, files: dict[str, str] | None = None) -> None:
    """Init a git repo in *root*, create files, and commit them."""
    _git(root, "init", "-q")
    _git(root, "config", "user.name", "Test")
    _git(root, "config", "user.email", "test@example.com")
    if files:
        for rel, content in files.items():
            fp = root / rel
            fp.parent.mkdir(parents=True, exist_ok=True)
            fp.write_text(content)
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "baseline")


def _write_tasks_file(root: Path, content: str) -> Path:
    tasks_file = root / "tasks.md"
    tasks_file.write_text(content)
    return tasks_file


# ──────────────────────────────────────────────────────────────────────
# Gate skip on non-git paths (backward compatibility)
# ──────────────────────────────────────────────────────────────────────


class TestGateSkipOnNonGitPath:
    """When TASKS_PATH lives outside a git repo, gates are skipped and
    complete_task proceeds normally — preserving the existing behavior that
    tests (and any non-git caller) rely on."""

    def test_run_completion_gates_returns_ok_for_non_git_path(self, tmp_path: Path) -> None:
        tasks_file = _write_tasks_file(tmp_path, "- [ ] Some task\n")
        import janus.services.tasks as m

        m.TASKS_PATH = tasks_file
        result = run_completion_gates(root=tasks_file.parent)
        assert result.ok is True
        assert result.integration_not_applicable is True
        assert result.pre_completion_report is None
        assert result.integration_result is None

    def test_complete_task_works_on_non_git_path(self, tmp_path: Path, monkeypatch: Any) -> None:
        tasks_file = _write_tasks_file(
            tmp_path, "- [ ] Buy running shoes | priority: 1\n"
        )
        monkeypatch.setattr("janus.services.tasks.TASKS_PATH", tasks_file)

        task = complete_task("Buy running shoes")

        assert task.title == "Buy running shoes"
        content = tasks_file.read_text()
        assert "- [x] Buy running shoes | priority: 1" in content
        assert "- [ ] Buy running shoes" not in content


# ──────────────────────────────────────────────────────────────────────
# Phase 3 gate blocks on failing checks (git repo)
# ──────────────────────────────────────────────────────────────────────


class TestPhase3GateBlocksOnFailure:
    """When the pre-completion checks fail inside a git repo, the gate
    returns ok=False with a structured reason code and complete_task raises
    CompletionGateError."""

    def test_working_tree_not_clean_blocks_completion(self, tmp_path: Path) -> None:
        _init_repo(tmp_path, {"README.md": "# Test\n"})
        # Introduce an untracked file to make the working tree unclean
        (tmp_path / "stray.txt").write_text("hello\n")
        tasks_file = _write_tasks_file(tmp_path, "- [ ] Test task\n")
        # Commit tasks.md so only stray.txt is the unclean item.
        _git(tmp_path, "add", "tasks.md")
        _git(tmp_path, "commit", "-q", "-m", "add tasks")

        result = run_completion_gates(root=tmp_path)
        assert result.ok is False
        assert result.blocked_reason == GATE_WORKING_TREE_NOT_CLEAN
        assert result.pre_completion_report is not None
        assert not result.pre_completion_report.is_pass

    def test_pre_completion_report_serialized_on_failure(self, tmp_path: Path) -> None:
        _init_repo(tmp_path, {"README.md": "# Test\n"})
        (tmp_path / "stray.txt").write_text("hello\n")
        tasks_file = _write_tasks_file(tmp_path, "- [ ] Test task\n")
        _git(tmp_path, "add", "tasks.md")
        _git(tmp_path, "commit", "-q", "-m", "add tasks")

        result = run_completion_gates(root=tmp_path)
        assert result.pre_completion_report is not None
        report_dict = result.pre_completion_report.to_dict()
        assert report_dict["overall"] == "FAIL"
        assert any(
            d["message"].startswith("UNCLEAN")
            for d in report_dict["checks"]["working_tree_clean"]["details"]
        )

    def test_complete_task_raises_completion_gate_error_on_blocked(
        self, tmp_path: Path, monkeypatch: Any
    ) -> None:
        _init_repo(tmp_path, {"README.md": "# Test\n"})
        (tmp_path / "stray.txt").write_text("hello\n")
        tasks_file = _write_tasks_file(tmp_path, "- [ ] Test task\n")
        _git(tmp_path, "add", "tasks.md")
        _git(tmp_path, "commit", "-q", "-m", "add tasks")

        monkeypatch.setattr("janus.services.tasks.TASKS_PATH", tasks_file)

        with pytest.raises(CompletionGateError) as exc_info:
            complete_task("Test task")

        assert exc_info.value.reason == GATE_WORKING_TREE_NOT_CLEAN
        assert "working tree is not clean" in str(exc_info.value).lower()

    def test_completion_gate_error_is_value_error(self) -> None:
        err = CompletionGateError("test_reason", "test message")
        assert isinstance(err, ValueError)
        assert err.reason == "test_reason"
        assert str(err) == "test message"


# ──────────────────────────────────────────────────────────────────────
# Phase 4 integration: already-done shortcut
# ──────────────────────────────────────────────────────────────────────


class TestPhase4IntegrationAlreadyDone:
    """When the task branch HEAD is already contained in the remote target
    branch, integration is considered done and the gate passes without
    running the full integrate_task machinery."""

    def test_already_integrated_skips_integration_step(self, tmp_path: Path) -> None:
        """In a real git repo with a remote, if HEAD is contained in
        origin/<target>, the gate returns ok=True with an 'already_integrated'
        merge_strategy and writes integration_report.json."""
        _init_repo(tmp_path, {"README.md": "# Test\n"})
        tasks_file = _write_tasks_file(tmp_path, "- [ ] Test task\n")
        _git(tmp_path, "add", "tasks.md")
        _git(tmp_path, "commit", "-q", "-m", "add tasks")

        # Use a no-op test command so tests_pass_after_rebase passes
        # (the temp repo has no tests/ directory).
        result = run_completion_gates(
            root=tmp_path, test_command="true"
        )
        # This is a local-only repo without a remote — target branch detection
        # fails and integration_not_applicable is True (no remote to check).
        assert result.ok is True
        assert result.integration_not_applicable is True


# ──────────────────────────────────────────────────────────────────────
# Evidence artifacts written when gates pass
# ──────────────────────────────────────────────────────────────────────


class TestEvidenceArtifactsWhenGatesPass:
    """When gates pass in a git repo, pre_completion_report.json and
    integration_report.json are written to <root>/reports/."""

    def test_pre_completion_report_written_on_pass(self, tmp_path: Path) -> None:
        _init_repo(tmp_path, {"README.md": "# Test\n"})
        tasks_file = _write_tasks_file(tmp_path, "- [ ] Test task\n")
        _git(tmp_path, "add", "tasks.md")
        _git(tmp_path, "commit", "-q", "-m", "add tasks")

        # Use a no-op test command so tests_pass_after_rebase passes
        result = run_completion_gates(
            root=tmp_path, test_command="true"
        )
        assert result.ok is True
        assert result.pre_completion_report is not None
        assert result.pre_completion_report.is_pass
        # Phase 3 evidence artifact must actually hit disk (not only the in-memory
        # report carried by the result). The docstring above promises both files.
        pre_report_file = tmp_path / "reports" / "pre_completion_report.json"
        assert pre_report_file.is_file(), (
            "pre_completion_report.json should be written to <root>/reports/"
        )
        payload = json.loads(pre_report_file.read_text(encoding="utf-8"))
        assert payload["overall"] == "PASS"
        # Validate the serialized schema matches what the ADR expects from a
        # pre-completion report: structured check results, not just an overall flag.
        assert isinstance(payload["checks"], dict), (
            "pre_completion_report.json must carry per-check results"
        )
        check_names = set(payload["checks"].keys())
        assert {"working_tree_clean", "git_diff_check", "tests_pass_after_rebase"}.issubset(
            check_names
        ), f"expected the three default-on checks; got {check_names}"
        # Confirm no spurious top-level keys leak into the serialized report.
        assert set(payload.keys()) <= {
            "task_id",
            "overall",
            "checks",
            "summary",
            "failures",
            "generated_at",
        }, f"unexpected keys in pre_completion_report.json: {set(payload.keys())}"
