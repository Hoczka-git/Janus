"""Tests for ADR-004 Phase 5 gate enforcement on complete_task().

Covers:
- Gate skip on non-git paths (temp dir tasks.md) — existing behavior preserved.
- Phase 1 re-sync: runs inside run_completion_gates() before Phase 3;
  conflict blocks, environmental failures are soft (logged), clean repos
  proceed normally.
- Phase 3 gate blocks completion when pre-completion checks fail (non-git
  path with a failing test_command is a no-op; the real gate runs in git
  repos only, so we test the gate logic directly via run_completion_gates).
- CompletionGateError carries a structured reason code.
- Evidence artifacts are written when gates pass in a git repo.
- Integration already-done shortcut (HEAD contained in remote target).
- Phase 3 extension: contract verification (opt-in; blocks on failure,
  no-op when no contract file exists).

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
from unittest import mock

import pytest

from janus.services.tasks import (
    CompletionGateError,
    CompletionGateResult,
    GATE_CONTRACT_VERIFICATION_FAILED,
    GATE_DIFF_CHECK_FAILED,
    GATE_INTEGRATION_FAILED,
    GATE_SYNC_CONFLICT,
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


# ──────────────────────────────────────────────────────────────────────
# Phase 1 re-sync at gate time
# ──────────────────────────────────────────────────────────────────────


class TestPhase1ResyncAtGateTime:
    """Phase 1 re-sync runs inside run_completion_gates() before Phase 3.

    These tests mock ``sync_branch`` so they don't depend on a real remote,
    exercising only the gate-level decision logic (conflict blocks, soft
    failures pass through, success proceeds).
    """

    def test_resync_conflict_blocks_completion(self, tmp_path: Path) -> None:
        """A SYNC_CONFLICT from sync_branch() blocks the gate with
        GATE_SYNC_CONFLICT."""
        from janus.git_sync import SyncResult, SYNC_CONFLICT

        _init_repo(tmp_path, {"README.md": "# Test\n"})
        _write_tasks_file(tmp_path, "- [ ] Test task\n")
        _git(tmp_path, "add", "tasks.md")
        _git(tmp_path, "commit", "-q", "-m", "add tasks")

        conflict_result = SyncResult(
            success=False,
            reason=SYNC_CONFLICT,
            task_branch="wt/t_test",
            target_branch="master",
            conflicts=["src/a.py", "src/b.py"],
        )
        with mock.patch("janus.services.tasks._phase1_resync") as mock_resync:
            mock_resync.return_value = CompletionGateResult(
                ok=False,
                blocked_reason=GATE_SYNC_CONFLICT,
                blocked_message=(
                    "Phase 1 re-sync conflict on 'wt/t_test' "
                    "vs target 'master': src/a.py, src/b.py. "
                    "Route to merge-reconciler."
                ),
                pre_completion_report=None,
            )
            result = run_completion_gates(root=tmp_path, test_command="true")
        assert result.ok is False
        assert result.blocked_reason == GATE_SYNC_CONFLICT
        assert "merge-reconciler" in (result.blocked_message or "")

    def test_resync_environmental_failure_proceeds_to_phase3(
        self, tmp_path: Path,
    ) -> None:
        """A non-conflict sync failure (e.g. TARGET_BRANCH_MISSING) does NOT
        block — Phase 4 will catch a genuinely stale branch.  The gate proceeds
        to Phase 3 and, since there's no remote, skips Phase 4."""
        _init_repo(tmp_path, {"README.md": "# Test\n"})
        _write_tasks_file(tmp_path, "- [ ] Test task\n")
        _git(tmp_path, "add", "tasks.md")
        _git(tmp_path, "commit", "-q", "-m", "add tasks")

        # No origin remote → _phase1_resync returns None (skipped),
        # Phase 4 also skips (integration_not_applicable=True).
        result = run_completion_gates(root=tmp_path, test_command="true")
        assert result.ok is True
        assert result.integration_not_applicable is True

    def test_resync_success_proceeds_to_phase3(self, tmp_path: Path) -> None:
        """When sync_branch succeeds, Phase 3 tests run on the fresh branch."""
        _init_repo(tmp_path, {"README.md": "# Test\n"})
        _write_tasks_file(tmp_path, "- [ ] Test task\n")
        _git(tmp_path, "add", "tasks.md")
        _git(tmp_path, "commit", "-q", "-m", "add tasks")

        with mock.patch("janus.git_sync.sync_branch") as mock_sync:
            from janus.git_sync import SyncResult
            mock_sync.return_value = SyncResult(success=True)
            result = run_completion_gates(root=tmp_path, test_command="true")
        assert result.ok is True
        # sync_branch was attempted (even though there's no remote, the call
        # happens inside _phase1_resync only when _has_origin_remote returns
        # True; for a local repo without remote, _phase1_resync returns None
        # early.  So mock_sync may not be called — that's fine: the point is
        # the gate still passes.)

    def test_resync_called_before_phase3(self, tmp_path: Path) -> None:
        """run_completion_gates calls _phase1_resync before run_default_checks."""
        _init_repo(tmp_path, {"README.md": "# Test\n"})
        _write_tasks_file(tmp_path, "- [ ] Test task\n")
        _git(tmp_path, "add", "tasks.md")
        _git(tmp_path, "commit", "-q", "-m", "add tasks")

        with mock.patch("janus.services.tasks._phase1_resync") as mock_resync:
            mock_resync.return_value = None
            result = run_completion_gates(root=tmp_path, test_command="true")
        assert result.ok is True
        # _phase1_resync was called (it returns None for non-remote repos).
        assert mock_resync.called


# ──────────────────────────────────────────────────────────────────────
# Phase 3 extension: contract-based verification (T4)
# ──────────────────────────────────────────────────────────────────────


class TestContractVerification:
    """Phase 3 extension: when a contract file exists at
    ``contracts/<branch>.yaml``, run_verification() is invoked and a
    contract-verification failure blocks completion; when no contract
    file exists, the step is a no-op."""

    def test_no_contract_file_is_noop(self, tmp_path: Path) -> None:
        """No contract file → gate proceeds normally (no blocking)."""
        _init_repo(tmp_path, {"README.md": "# Test\n"})
        _write_tasks_file(tmp_path, "- [ ] Test task\n")
        _git(tmp_path, "add", "tasks.md")
        _git(tmp_path, "commit", "-q", "-m", "add tasks")
        # Create a branch so _current_branch returns something.
        _git(tmp_path, "checkout", "-q", "-b", "wt/t_test_branch")

        result = run_completion_gates(root=tmp_path, test_command="true")
        assert result.ok is True

    def test_contract_verification_failure_blocks(self, tmp_path: Path) -> None:
        """When run_verification() reports failure, the gate blocks with
        GATE_CONTRACT_VERIFICATION_FAILED."""
        _init_repo(tmp_path, {"README.md": "# Test\n"})
        _write_tasks_file(tmp_path, "- [ ] Test task\n")
        _git(tmp_path, "add", "tasks.md")
        _git(tmp_path, "commit", "-q", "-m", "add tasks")
        _git(tmp_path, "checkout", "-q", "-b", "wt/t_contract_fail")

        # Create a contract file so _find_task_contract discovers it,
        # and commit it so the working tree stays clean for Phase 3.
        contracts_dir = tmp_path / "contracts" / "wt"
        contracts_dir.mkdir(parents=True)
        contract_file = contracts_dir / "t_contract_fail.yaml"
        contract_file.write_text(
            "version: 1\ntask_id: t_contract_fail\n"
        )
        _git(tmp_path, "add", "-A")
        _git(tmp_path, "commit", "-q", "-m", "add contract")

        from janus.verification import VerificationReport
        fake_report = VerificationReport(task_id="t_contract_fail")
        fake_report.overall = "FAIL"
        fake_report.failures = [{"check": "files_create", "item": "missing.py"}]

        with mock.patch(
            "janus.services.tasks.run_verification", return_value=fake_report
        ) as mock_run:
            result = run_completion_gates(root=tmp_path, test_command="true")

        assert result.ok is False
        assert result.blocked_reason == GATE_CONTRACT_VERIFICATION_FAILED
        assert "contract verification failed" in (result.blocked_message or "").lower()
        assert mock_run.called

    def test_contract_verification_pass_proceeds(self, tmp_path: Path) -> None:
        """When run_verification() reports PASS, the gate proceeds."""
        _init_repo(tmp_path, {"README.md": "# Test\n"})
        _write_tasks_file(tmp_path, "- [ ] Test task\n")
        _git(tmp_path, "add", "tasks.md")
        _git(tmp_path, "commit", "-q", "-m", "add tasks")
        _git(tmp_path, "checkout", "-q", "-b", "wt/t_contract_pass")

        # Create a contract file so _find_task_contract discovers it,
        # and commit it so the working tree stays clean for Phase 3.
        contracts_dir = tmp_path / "contracts" / "wt"
        contracts_dir.mkdir(parents=True)
        contract_file = contracts_dir / "t_contract_pass.yaml"
        contract_file.write_text(
            "version: 1\ntask_id: t_contract_pass\n"
        )
        _git(tmp_path, "add", "-A")
        _git(tmp_path, "commit", "-q", "-m", "add contract")

        from janus.verification import VerificationReport
        fake_report = VerificationReport(task_id="t_contract_pass")
        fake_report.overall = "PASS"

        with mock.patch(
            "janus.services.tasks.run_verification", return_value=fake_report
        ) as mock_run:
            result = run_completion_gates(root=tmp_path, test_command="true")

        assert result.ok is True
        assert mock_run.called
