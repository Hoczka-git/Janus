"""Tests for the default-on deterministic pre-completion checks (ADR-004 Phase 3).

Covers:
- check_working_tree_clean (AC #1)
- check_git_diff_check conflict-marker detection (AC #2)
- check_tests_pass_after_rebase (AC #3)
- run_default_checks orchestration (AC #4)
- DefaultCheckConfig configuration (AC #4)
- Existing contract-based checks still work (AC #5)

These tests build isolated temporary Git repositories so they don't depend
on the state of the real Janus working tree.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

from janus.verification import (
    CheckResult,
    DefaultCheckConfig,
    ImplementationContract,
    VerificationReport,
    check_files_create,
    check_git_diff_check,
    check_tests_pass_after_rebase,
    check_working_tree_clean,
    run_default_checks,
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


# ──────────────────────────────────────────────────────────────────────
# AC #1 — working tree clean (git status --porcelain == empty)
# ──────────────────────────────────────────────────────────────────────

class TestWorkingTreeClean:

    def test_clean_tree_passes(self, tmp_path: Path) -> None:
        _init_repo(tmp_path, {"README.md": "# Test\n"})
        result = check_working_tree_clean(tmp_path)
        assert result.passed is True
        assert result.total_items == 1
        assert result.failed_items == 0
        assert result.details[0]["passed"] is True

    def test_untracked_file_fails(self, tmp_path: Path) -> None:
        _init_repo(tmp_path, {"README.md": "# Test\n"})
        (tmp_path / "stray.txt").write_text("hello\n")
        result = check_working_tree_clean(tmp_path)
        assert result.passed is False
        assert result.failed_items == 1
        assert "stray.txt" in result.details[0]["item"]

    def test_modified_file_fails(self, tmp_path: Path) -> None:
        _init_repo(tmp_path, {"README.md": "# Test\n"})
        (tmp_path / "README.md").write_text("# Test modified\n")
        result = check_working_tree_clean(tmp_path)
        assert result.passed is False
        assert result.failed_items == 1

    def test_staged_file_fails(self, tmp_path: Path) -> None:
        _init_repo(tmp_path, {"README.md": "# Test\n"})
        (tmp_path / "staged.py").write_text("x = 1\n")
        _git(tmp_path, "add", "staged.py")
        result = check_working_tree_clean(tmp_path)
        assert result.passed is False
        result.failed_items >= 1

    def test_non_git_directory_fails(self, tmp_path: Path) -> None:
        # No git init — should fail deterministically.
        result = check_working_tree_clean(tmp_path)
        assert result.passed is False
        assert "NOT A GIT REPOSITORY" in result.details[0]["message"]

    def test_defaults_to_cwd(self, tmp_path: Path, monkeypatch) -> None:
        _init_repo(tmp_path, {"README.md": "# Test\n"})
        monkeypatch.chdir(tmp_path)
        result = check_working_tree_clean()


# ──────────────────────────────────────────────────────────────────────
# AC #2 — git diff --check + conflict markers
# ──────────────────────────────────────────────────────────────────────

class TestGitDiffCheckConflictMarkers:

    def test_clean_diff_passes(self, tmp_path: Path) -> None:
        _init_repo(tmp_path, {"src.py": "def foo():\n    pass\n"})
        contract = ImplementationContract(version=1, task_id="t", root=tmp_path)
        result = check_git_diff_check(contract)
        assert result.passed is True

    def test_whitespace_error_fails(self, tmp_path: Path) -> None:
        _init_repo(tmp_path, {"src.py": "def foo():\n    pass\n"})
        (tmp_path / "src.py").write_text("def foo():\n    pass  \n")
        contract = ImplementationContract(version=1, task_id="t", root=tmp_path)
        result = check_git_diff_check(contract)
        assert result.passed is False
        assert "WHITESPACE" in result.details[0]["message"]

    def test_conflict_markers_fail(self, tmp_path: Path) -> None:
        _init_repo(tmp_path, {"src.py": "def foo():\n    pass\n"})
        # Introduce conflict markers in a modified file.
        (tmp_path / "src.py").write_text(
            "def foo():\n"
            "<<<<<<< HEAD\n"
            "    return 1\n"
            "=======\n"
            "    return 2\n"
            ">>>>>>> branch\n"
        )
        contract = ImplementationContract(version=1, task_id="t", root=tmp_path)
        result = check_git_diff_check(contract)
        assert result.passed is False
        assert "CONFLICT MARKERS" in result.details[0]["message"]

    def test_no_whitespace_no_conflict_markers_passes(self, tmp_path: Path) -> None:
        _init_repo(tmp_path, {"src.py": "def foo():\n    pass\n"})
        contract = ImplementationContract(version=1, task_id="t", root=tmp_path)
        result = check_git_diff_check(contract)
        assert result.passed is True
        assert "no conflict markers" in result.details[0]["message"]


# ──────────────────────────────────────────────────────────────────────
# AC #3 — tests pass after rebase
# ──────────────────────────────────────────────────────────────────────

class TestTestsPassAfterRebase:

    def test_passing_tests(self, tmp_path: Path) -> None:
        _init_repo(tmp_path, {"test_dummy.py": "def test_ok():\n    assert True\n"})
        result = check_tests_pass_after_rebase(
            test_command="python -m pytest test_dummy.py -q",
            root=tmp_path,
            timeout=60,
        )
        assert result.passed is True
        assert result.total_items == 1
        assert result.details[0]["message"].startswith("exit 0")

    def test_failing_tests(self, tmp_path: Path) -> None:
        _init_repo(tmp_path, {"test_fail.py": "def test_fail():\n    assert False\n"})
        result = check_tests_pass_after_rebase(
            test_command="python -m pytest test_fail.py -q",
            root=tmp_path,
            timeout=60,
        )
        assert result.passed is False
        assert "exit 1" in result.details[0]["message"]

    def test_nonexistent_command_fails(self, tmp_path: Path) -> None:
        _init_repo(tmp_path, {"README.md": "# Test\n"})
        result = check_tests_pass_after_rebase(
            test_command="this-command-does-not-exist",
            root=tmp_path,
            timeout=60,
        )
        assert result.passed is False


# ──────────────────────────────────────────────────────────────────────
# AC #4 — default-on orchestration + configuration
# ──────────────────────────────────────────────────────────────────────

class TestRunDefaultChecks:

    def _setup_passing_repo(self, tmp_path: Path) -> Path:
        """A repo where all three default checks would pass (mock tests)."""
        _init_repo(tmp_path, {"README.md": "# Test\n"})
        return tmp_path

    def test_all_checks_pass_with_mock_test_command(self, tmp_path: Path) -> None:
        """Use a trivial command in place of the full test suite."""
        self._setup_passing_repo(tmp_path)
        config = DefaultCheckConfig(
            root=tmp_path,
            test_command="true",   # always exits 0
            test_timeout=30,
        )
        report = run_default_checks(config)
        assert report.overall == "PASS"
        assert "working_tree_clean" in report.checks
        assert "git_diff_check" in report.checks
        assert "tests_pass_after_rebase" in report.checks
        for cr in report.checks.values():
            assert cr.passed

    def test_untracked_file_detected_by_default_checks(self, tmp_path: Path) -> None:
        self._setup_passing_repo(tmp_path)
        (tmp_path / "stray.txt").write_text("oops\n")
        config = DefaultCheckConfig(
            root=tmp_path,
            test_command="true",
            test_timeout=30,
        )
        report = run_default_checks(config)
        assert report.overall == "FAIL"
        failures = _failures_by_check(report)
        assert "working_tree_clean" in failures

    def test_failing_test_detected_by_default_checks(self, tmp_path: Path) -> None:
        self._setup_passing_repo(tmp_path)
        config = DefaultCheckConfig(
            root=tmp_path,
            test_command="false",  # exits 1
            test_timeout=30,
        )
        report = run_default_checks(config)
        assert report.overall == "FAIL"
        assert report.checks["tests_pass_after_rebase"].passed is False

    def test_default_config_has_all_enabled(self) -> None:
        config = DefaultCheckConfig()
        assert config.enabled is True
        assert config.run_working_tree_clean is True
        assert config.run_git_diff_check is True
        assert config.run_tests_after_rebase is True

    def test_from_dict_defaults(self) -> None:
        config = DefaultCheckConfig.from_dict(None)
        assert config.enabled is True
        assert config.test_command == "uv run pytest tests/"

    def test_from_dict_partial_override(self) -> None:
        config = DefaultCheckConfig.from_dict({
            "run_tests_after_rebase": False,
            "test_command": "true",
        })
        assert config.run_tests_after_rebase is False
        assert config.test_command == "true"

    def test_config_disable_all_skips_all(self, tmp_path: Path) -> None:
        config = DefaultCheckConfig(
            enabled=False,
            root=tmp_path,
            test_command="true",
        )
        report = run_default_checks(config)
        assert report.checks == {}
        assert report.is_pass

    def test_config_disable_individual_checks(self, tmp_path: Path) -> None:
        """Disabling individual checks means they don't appear in the report."""
        self._setup_passing_repo(tmp_path)
        config = DefaultCheckConfig(
            root=tmp_path,
            run_tests_after_rebase=False,
            test_command="false",  # would fail, but we disabled it
            test_timeout=30,
        )
        report = run_default_checks(config)
        assert "tests_pass_after_rebase" not in report.checks
        assert report.is_pass


# ──────────────────────────────────────────────────────────────────────
# AC #5 — existing contract-based checks still work
# ──────────────────────────────────────────────────────────────────────

class TestContractChecksStillWork:

    def test_check_files_create_still_passes(self, tmp_path: Path) -> None:
        _init_repo(tmp_path, {"src/app.py": "def main():\n    pass\n"})
        from janus.verification import ContractFileEntry
        contract = ImplementationContract(
            version=1,
            task_id="t",
            root=tmp_path,
            files_create=[ContractFileEntry(path="src/app.py")],
        )
        result = check_files_create(contract)
        assert result.passed is True

    def test_check_files_create_still_fails(self, tmp_path: Path) -> None:
        _init_repo(tmp_path, {"README.md": "# Test\n"})
        from janus.verification import ContractFileEntry
        contract = ImplementationContract(
            version=1,
            task_id="t",
            root=tmp_path,
            files_create=[ContractFileEntry(path="src/missing.py")],
        )
        result = check_files_create(contract)
        assert result.passed is False


# ──────────────────────────────────────────────────────────────────────
# Helper for test assertions
# ──────────────────────────────────────────────────────────────────────

def _failures_by_check(report: VerificationReport) -> dict[str, list[dict[str, Any]]]:
    """Group report failures by check name."""
    grouped: dict[str, list[dict[str, Any]]] = {}
    for f in report.failures:
        check = f.get("check", "unknown")
        grouped.setdefault(check, []).append(f)
    return grouped
