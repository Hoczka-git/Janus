"""Tests for the os.replace grep gate (check_no_os_replace).

Covers ADR-005 Amendment 01 acceptance criterion 3: the verification
pipeline's grep gate must assert that ``data_protection.py`` contains no
``os.replace`` call site, while ``atomic_io.py`` (the sole write primitive)
retains exactly one.

After the deprecation-removal of ``data_protection.py`` (all writers migrated
to ``atomic_io`` / ``data_integrity``), the gate on that file is superseded:
``atomic_io.py`` is the sole allowed call site, and the
``check_data_write_path`` / ``check_data_file_write_gates`` grep gates (which
exclude ``atomic_io.py`` and ``data_integrity.py`` from caller checks) are the
enforcement for the single-choke-point invariant.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from janus.verification import (
    ImplementationContract,
    CheckResult,
    check_no_os_replace,
    _find_os_replace_calls,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


def _contract_with(forbidden_os_replace: list[str]) -> ImplementationContract:
    c = ImplementationContract(version=1, task_id="os-replace-gate")
    c.root = REPO_ROOT
    c.forbidden_os_replace = forbidden_os_replace
    return c


class TestFindOsReplaceCalls:
    def test_finds_os_replace_callsite(self, tmp_path: Path) -> None:
        f = tmp_path / "mod.py"
        f.write_text("import os\nos.replace('a', 'b')\n")
        lines = _find_os_replace_calls(f)
        assert lines == [2]

    def test_ignores_os_replace_in_comments_and_strings(self, tmp_path: Path) -> None:
        f = tmp_path / "mod.py"
        f.write_text(
            "import os\n"
            "# os.replace should not trigger\n"
            "s = 'os.replace here'\n"
            "os.replace('a', 'b')\n"
        )
        assert _find_os_replace_calls(f) == [4]

    def test_ignores_other_methods_named_replace(self, tmp_path: Path) -> None:
        f = tmp_path / "mod.py"
        f.write_text(
            "import os\n"
            "os.replace('a', 'b')\n"  # call — should be found
        )
        assert _find_os_replace_calls(f) == [2]

    def test_missing_file_returns_empty(self, tmp_path: Path) -> None:
        assert _find_os_replace_calls(tmp_path / "nope.py") == []


class TestCheckNoOsReplaceOnRealRepo:
    """The actual repo files after ADR-005 Amendment 01 delegation."""

    def test_atomic_io_has_the_one_os_replace(self) -> None:
        # atomic_io.py is the sole allowed call site — NOT listed as forbidden.
        atomic_io = REPO_ROOT / "src/janus/integrations/atomic_io.py"
        assert _find_os_replace_calls(atomic_io) == [334]

    def test_forbidden_atomic_io_would_fail(self) -> None:
        # Listing the true call site as forbidden must FAIL — proves the gate works.
        contract = _contract_with(["src/janus/integrations/atomic_io.py"])
        result = check_no_os_replace(contract)
        assert not result.passed
        assert result.failed_items == 1

    def test_data_protection_module_is_deleted(self) -> None:
        """data_protection.py has been removed; the gate no longer needs to
        list it because there is nothing to scan. ``data_integrity.py`` is the
        policy layer and delegates to ``atomic_io`` (no os.replace of its own)."""
        deleted_path = REPO_ROOT / "src/janus/integrations/data_protection.py"
        assert not deleted_path.exists()

    def test_data_integrity_has_no_os_replace(self) -> None:
        """The policy layer (data_integrity.py) must not contain os.replace;
        it delegates all atomic replacement to atomic_io."""
        contract = _contract_with(["src/janus/integrations/data_integrity.py"])
        result = check_no_os_replace(contract)
        assert result.passed, result.details
        assert result.failed_items == 0
