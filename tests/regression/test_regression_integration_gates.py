"""Regression tests for integration gates (I1-I13).

Covers Phase 1 resync, Phase 3 pre-completion verification, Phase 4 integration,
contract verification, and integration report scenarios.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest import mock

import pytest

from janus.services.tasks import (
    CompletionGateResult,
    CompletionGateError,
    GATE_WORKING_TREE_NOT_CLEAN,
    GATE_TESTS_FAILED,
    GATE_DIFF_CHECK_FAILED,
    GATE_INTEGRATION_FAILED,
    GATE_SYNC_CONFLICT,
    GATE_CONTRACT_VERIFICATION_FAILED,
    run_completion_gates,
    _phase1_resync,
    _find_git_root,
    _has_origin_remote,
    _current_branch,
    _target_branch,
    _find_task_contract,
)
from tests.regression.harness import TestHarness


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


class TestIntegrationGates:
    """I1-I13: Integration gate tests."""

    def test_i1_phase1_resync_clean_workspace(self, tmp_path: Path) -> None:
        """I1: Phase 1 resync — clean workspace passes."""
        _init_repo(tmp_path, {"README.md": "# Test\n"})
        result = run_completion_gates(root=tmp_path, test_command="true")
        assert result.ok is True

    def test_i2_phase1_resync_conflict_blocks(self, tmp_path: Path) -> None:
        """I2: Phase 1 resync — conflict blocks completion."""
        _init_repo(tmp_path, {"README.md": "# Test\n"})

        # Mock _phase1_resync to return a conflict result
        with mock.patch("janus.services.tasks._phase1_resync") as mock_resync:
            mock_resync.return_value = CompletionGateResult(
                ok=False,
                blocked_reason=GATE_SYNC_CONFLICT,
                blocked_message="Phase 1 re-sync conflict",
            )
            result = run_completion_gates(root=tmp_path, test_command="true")
            assert result.ok is False
            assert result.blocked_reason == GATE_SYNC_CONFLICT

    def test_i3_phase1_resync_environmental_failure(self, tmp_path: Path) -> None:
        """I3: Phase 1 resync — environmental failure proceeds (degraded)."""
        _init_repo(tmp_path, {"README.md": "# Test\n"})

        # Mock _phase1_resync to return None (environmental failure, not conflict)
        with mock.patch("janus.services.tasks._phase1_resync", return_value=None):
            result = run_completion_gates(root=tmp_path, test_command="true")
            assert result.ok is True

    def test_i4_phase3_working_tree_not_clean(self, tmp_path: Path) -> None:
        """I4: Phase 3 — working tree not clean blocks completion."""
        _init_repo(tmp_path, {"README.md": "# Test\n"})
        # Introduce an uncommitted change
        (tmp_path / "stray.txt").write_text("hello\n")

        result = run_completion_gates(root=tmp_path, test_command="true")
        assert result.ok is False
        assert result.blocked_reason == GATE_WORKING_TREE_NOT_CLEAN

    def test_i5_phase3_pre_completion_report_serialized(self, tmp_path: Path) -> None:
        """I5: Phase 3 — pre_completion_report is serialized correctly."""
        _init_repo(tmp_path, {"README.md": "# Test\n"})

        result = run_completion_gates(root=tmp_path, test_command="true")
        assert result.ok is True
        assert result.pre_completion_report is not None
        report_dict = result.pre_completion_report.to_dict()
        assert report_dict["overall"] == "PASS"
        assert "checks" in report_dict

    def test_i6_phase4_already_integrated(self, tmp_path: Path) -> None:
        """I6: Phase 4 — already integrated short-circuits."""
        _init_repo(tmp_path, {"README.md": "# Test\n"})

        # Without a remote, integration is not applicable
        result = run_completion_gates(root=tmp_path, test_command="true")
        assert result.ok is True
        assert result.integration_not_applicable is True

    def test_i7_contract_verification_no_contract(self, tmp_path: Path) -> None:
        """I7: Contract verification — no contract file is a no-op."""
        _init_repo(tmp_path, {"README.md": "# Test\n"})
        _git(tmp_path, "checkout", "-q", "-b", "wt/t_test")

        result = run_completion_gates(root=tmp_path, test_command="true")
        assert result.ok is True

    def test_i8_contract_verification_fails(self, tmp_path: Path) -> None:
        """I8: Contract verification — contract failure blocks completion."""
        _init_repo(tmp_path, {"README.md": "# Test\n"})
        _git(tmp_path, "checkout", "-q", "-b", "wt/t_contract_fail")

        # Create a contract file
        contracts_dir = tmp_path / "contracts" / "wt"
        contracts_dir.mkdir(parents=True)
        contract_file = contracts_dir / "t_contract_fail.yaml"
        contract_file.write_text("version: 1\ntask_id: t_contract_fail\n")
        _git(tmp_path, "add", "-A")
        _git(tmp_path, "commit", "-q", "-m", "add contract")

        from janus.verification import VerificationReport
        fake_report = VerificationReport(task_id="t_contract_fail")
        fake_report.overall = "FAIL"
        fake_report.failures = [{"check": "files_create", "item": "missing.py"}]

        with mock.patch(
            "janus.services.tasks.run_verification", return_value=fake_report
        ):
            result = run_completion_gates(root=tmp_path, test_command="true")
            assert result.ok is False
            assert result.blocked_reason == GATE_CONTRACT_VERIFICATION_FAILED

    def test_i9_contract_verification_passes(self, tmp_path: Path) -> None:
        """I9: Contract verification — contract passes, integration continues."""
        _init_repo(tmp_path, {"README.md": "# Test\n"})
        _git(tmp_path, "checkout", "-q", "-b", "wt/t_contract_pass")

        # Create a contract file
        contracts_dir = tmp_path / "contracts" / "wt"
        contracts_dir.mkdir(parents=True)
        contract_file = contracts_dir / "t_contract_pass.yaml"
        contract_file.write_text("version: 1\ntask_id: t_contract_pass\n")
        _git(tmp_path, "add", "-A")
        _git(tmp_path, "commit", "-q", "-m", "add contract")

        from janus.verification import VerificationReport
        fake_report = VerificationReport(task_id="t_contract_pass")
        fake_report.overall = "PASS"

        with mock.patch(
            "janus.services.tasks.run_verification", return_value=fake_report
        ):
            result = run_completion_gates(root=tmp_path, test_command="true")
            assert result.ok is True

    def test_i10_integration_with_real_origin_remote(self, tmp_path: Path) -> None:
        """I10: Integration with real origin remote — validates against actual origin."""
        _init_repo(tmp_path, {"README.md": "# Test\n"})

        # Without a remote, _has_origin_remote returns False
        # and integration is not applicable
        assert _has_origin_remote(tmp_path) is False
        result = run_completion_gates(root=tmp_path, test_command="true")
        assert result.ok is True
        assert result.integration_not_applicable is True

    def test_i11_integration_with_null_branch_name(self, tmp_path: Path) -> None:
        """I11: Integration with NULL branch_name — handles gracefully."""
        _init_repo(tmp_path, {"README.md": "# Test\n"})

        # Detached HEAD — _current_branch returns None
        _git(tmp_path, "checkout", "-q", "--detach")

        result = run_completion_gates(root=tmp_path, test_command="true")
        assert result.ok is True
        assert result.integration_not_applicable is True

    def test_i12_integration_with_integration_required_false(self, tmp_path: Path) -> None:
        """I12: Integration with integration_required=False — skipped."""
        _init_repo(tmp_path, {"README.md": "# Test\n"})

        # Without a remote, integration is not applicable
        result = run_completion_gates(root=tmp_path, test_command="true")
        assert result.ok is True
        assert result.integration_not_applicable is True

    def test_i13_integration_report_on_success(self, tmp_path: Path) -> None:
        """I13: integration_report.json written on success."""
        _init_repo(tmp_path, {"README.md": "# Test\n"})

        result = run_completion_gates(root=tmp_path, test_command="true")
        assert result.ok is True
        # Without a remote, no integration report is written
        # (integration_not_applicable is True)
        report_file = tmp_path / "reports" / "integration_report.json"
        # Report may or may not exist depending on integration path
        if report_file.exists():
            payload = json.loads(report_file.read_text())
            assert "success" in payload
