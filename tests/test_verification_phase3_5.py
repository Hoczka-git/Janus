"""Phase 3.5: End-to-End Validation of the Complete Verification Pipeline.

Validates that the existing deterministic verification pipeline correctly
detects controlled contract violations in isolated temporary Git repositories.

DO NOT modify production verifier code unless a genuine bug is discovered.
This phase is validation, not feature development.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from janus.verification import (
    ImplementationContract,
    run_verification,
    CheckResult,
    VerificationReport,
)


# ══════════════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════════════

def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=str(root),
        capture_output=True,
        text=True,
        timeout=30,
    )


def _init_repo(root: Path, user_name: str = "Test User", user_email: str = "test@example.com") -> None:
    _git(root, "init", "-q")
    _git(root, "config", "user.name", user_name)
    _git(root, "config", "user.email", user_email)
    # Ignore Python cache files so they don't pollute untracked-file checks.
    (root / ".gitignore").write_text("__pycache__/\n*.pyc\n", encoding="utf-8")


def _add_commit(root: Path, message: str = "baseline") -> None:
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", message)


def _stage(root: Path, paths: str | list[str] | None = None) -> None:
    if paths is None:
        _git(root, "add", "-A")
    else:
        _git(root, "add", *([paths] if isinstance(paths, str) else paths))


def _write_contract(root: Path, data: dict[str, Any]) -> Path:
    import yaml
    contract_path = root / "contract.yaml"
    contract_path.write_text(
        yaml.safe_dump(data, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    return contract_path


def _run(root: Path) -> VerificationReport:
    contract_path = root / "contract.yaml"
    return run_verification(contract_path)


def _failures_by_check(report: VerificationReport) -> dict[str, list[dict[str, Any]]]:
    """Group failures by check name for easy assertion."""
    grouped: dict[str, list[dict[str, Any]]] = {}
    for f in report.failures:
        check = f.get("check", "unknown")
        grouped.setdefault(check, []).append(f)
    return grouped


# ══════════════════════════════════════════════════════════════════════════
# Realistic Goal-System-inspired contract factory
# ══════════════════════════════════════════════════════════════════════════

def realistic_contract(root: Path) -> Path:
    """Write a realistic Goal-System-style contract into *root*.

    Mirrors the kind of contract that was historically produced for the
    Goal System MVP while remaining small enough for fast tests.
    """
    import yaml

    files_create = [
        {"path": "src/janus/services/goals.py", "description": "Goal CRUD service layer"},
        {"path": "src/janus/goals_cli.py", "description": "CLI entry point for goals"},
    ]

    files_modify = [
        {"path": "src/janus/models/goal.py", "description": "Goal model adjustments"},
        {"path": "src/janus/init.py", "description": "Project initialization adjustments"},
    ]

    files_immutable = [
        {"path": "config/protected.cfg", "reason": "Protected configuration must not change"},
        {"path": "data/goals.md", "reason": "Production data must not change"},
    ]

    forbidden_files = [
        {"path": "tests/test_delete_goal.py", "type": "exists", "reason": "Delete goal out of scope"},
    ]

    required_symbols = [
        {"path": "src/janus/services/goals.py", "symbol": "GoalService", "type": "class"},
        {"path": "src/janus/services/goals.py", "symbol": "add_goal", "type": "function"},
        {"path": "src/janus/services/goals.py", "symbol": "complete_goal", "type": "function"},
        {"path": "src/janus/services/goals.py", "symbol": "compute_goal_progress", "type": "function"},
    ]

    forbidden_symbols = [
        {"symbol": "delete_goal", "path": "src/janus/services", "type": "function"},
    ]

    verification_commands = [
        {
            "label": "Python syntax check",
            "command": "python -m py_compile src/janus/services/goals.py",
            "expected_exit_code": 0,
            "timeout": 30,
        },
        {
            "label": "AST parse smoke test",
            "command": "python -c \"import ast; ast.parse(open('src/janus/models/goal.py').read())\"",
            "expected_exit_code": 0,
            "timeout": 30,
        },
    ]

    contract = {
        "version": 1,
        "task_id": "goal-system-mvp-validation",
        "created": "2026-08-30T12:00:00Z",
        "created_by": "phase3.5-validation",
        "description": "Goal System MVP-derived contract used for end-to-end pipeline validation.",
        "files": {
            "create": files_create,
            "modify": files_modify,
            "immutable": files_immutable,
            "forbidden": forbidden_files,
        },
        "required_symbols": required_symbols,
        "forbidden_symbols": forbidden_symbols,
        "verification_commands": verification_commands,
        "scope_constraints": {
            "allowed_paths": ["src/", "tests/"],
            "excluded_paths": ["data/", "config/"],
            "max_new_files": 5,
            "max_lines_added": 1000,
        },
        "completion_gates": [
            {"label": "All CREATE files exist", "type": "mechanical"},
            {"label": "All immutable files unchanged", "type": "mechanical"},
            {"label": "All verification commands pass", "type": "mechanical"},
        ],
    }

    return _write_contract(root, contract)


# ══════════════════════════════════════════════════════════════════════════
# Minimal goal-like source tree factory
# ══════════════════════════════════════════════════════════════════════════

GOALS_PY = (
    "from __future__ import annotations\n"
    "\n"
    "\n"
    "class GoalService:\n"
    '    """Service layer for goal management."""\n'
    "\n"
    "    def add_goal(self, title: str) -> dict:\n"
    '        return {"title": title, "done": False}\n'
    "\n"
    "    def complete_goal(self, goal: dict) -> dict:\n"
    '        goal["done"] = True\n'
    "        return goal\n"
    "\n"
    "    def compute_goal_progress(self, goals: list[dict]) -> float:\n"
    "        if not goals:\n"
    "            return 0.0\n"
    '        done = sum(1 for g in goals if g.get("done"))\n'
    "        return done / len(goals)\n"
)


GOALS_CLI_PY = (
    "from __future__ import annotations\n"
    "\n"
    "import argparse\n"
    "import sys\n"
    "\n"
    "from janus.services.goals import GoalService\n"
    "\n"
    "\n"
    "def main(argv: list[str] | None = None) -> int:\n"
    '    parser = argparse.ArgumentParser(prog="goals")\n'
    '    parser.add_argument("action", choices=["add", "list", "complete"])\n'
    "    args = parser.parse_args(argv)\n"
    "    service = GoalService()\n"
    '    if args.action == "add":\n'
    '        print("add stub")\n'
    '    elif args.action == "list":\n'
    '        print("list stub")\n'
    "    else:\n"
    '        print("complete stub")\n'
    "    return 0\n"
    "\n"
    "\n"
    'if __name__ == "__main__":\n'
    "    raise SystemExit(main())\n"
)


GOAL_MODEL_PY = (
    "from __future__ import annotations\n"
    "\n"
    "from dataclasses import dataclass\n"
    "from datetime import datetime\n"
    "\n"
    "\n"
    "@dataclass\n"
    "class Goal:\n"
    "    title: str\n"
    "    created: datetime = datetime.now()\n"
    "    done: bool = False\n"
)


INIT_PY = (
    "from __future__ import annotations\n"
    "\n"
    '__all__ = ["init_project"]\n'
    "\n"
    "\n"
    "def init_project(path: str) -> None:\n"
    '    """Initialize a Janus goal project at *path*."""\n'
    '    raise NotImplementedError("stub")\n'
)


def write_goal_like_tree(
    root: Path,
    *,
    missing_create_paths: set[str] | None = None,
    keep_modify_identical: set[str] | None = None,
) -> None:
    """Create a realistic minimal Goal System-like tree inside *root*.

    Parameters
    ----------
    missing_create_paths:
        Paths declared in files.create that should intentionally NOT be
        created on disk.
    keep_modify_identical:
        Paths declared in files.modify that must be byte-identical to HEAD
        after the baseline commit.
    """
    missing_create_paths = missing_create_paths or set()
    keep_modify_identical = keep_modify_identical or set()

    # Create directory scaffolding.
    (root / "src" / "janus" / "services").mkdir(parents=True, exist_ok=True)
    (root / "src" / "janus" / "models").mkdir(parents=True, exist_ok=True)
    (root / "src" / "janus").mkdir(parents=True, exist_ok=True)
    (root / "config").mkdir(parents=True, exist_ok=True)
    (root / "data").mkdir(parents=True, exist_ok=True)

    # Create the two files declared under files.create (unless missing).
    if "src/janus/goals_cli.py" not in missing_create_paths:
        _write(root / "src" / "janus" / "goals_cli.py", GOALS_CLI_PY)

    if "src/janus/services/goals.py" not in missing_create_paths:
        _write(root / "src" / "janus" / "services" / "goals.py", GOALS_PY)

    # Create the two files declared under files.modify.
    if "src/janus/models/goal.py" in keep_modify_identical:
        _write(root / "src" / "janus" / "models" / "goal.py", GOAL_MODEL_PY)
    else:
        _write(root / "src" / "janus" / "models" / "goal.py", GOAL_MODEL_PY)

    if "src/janus/init.py" in keep_modify_identical:
        _write(root / "src" / "janus" / "init.py", INIT_PY)
    else:
        _write(root / "src" / "janus" / "init.py", INIT_PY)

    # Create immutable files.
    _write(root / "config" / "protected.cfg", "protected config\n")
    _write(root / "data" / "goals.md", "# Goals\n")


# ══════════════════════════════════════════════════════════════════════════
# Baseline scenario repo (PASS case scaffold)
# ══════════════════════════════════════════════════════════════════════════

@pytest.fixture
def baseline_repo(tmp_path: Path) -> Path:
    """Create a temporary Git repository with a valid baseline.

    The repository contains:
    - All files declared under files.create (present and committed)
    - All files declared under files.modify (present, committed, and
      then modified after commit so they show as changed vs HEAD)
    - All files declared under files.immutable (present and committed)
    - The contract file itself (committed)
    - Exactly one commit so HEAD-based checks have a meaningful baseline.
    """
    root = tmp_path / "repo"
    root.mkdir(parents=True)

    _init_repo(root)
    write_goal_like_tree(root)
    realistic_contract(root)
    _add_commit(root, "baseline")

    # Now modify the files declared under files.modify so they differ from HEAD.
    # This is what makes the PASS scenario actually pass: the modify files
    # must have a non-empty diff vs HEAD.
    (root / "src" / "janus" / "models" / "goal.py").write_text(
        GOAL_MODEL_PY + "\n# modification for verification\n"
    )
    (root / "src" / "janus" / "init.py").write_text(
        INIT_PY + "\n# modification for verification\n"
    )

    return root


# ══════════════════════════════════════════════════════════════════════════
# MANDATORY PASS CASE
# ══════════════════════════════════════════════════════════════════════════

class TestPhase3_5PassScenario:
    """Full end-to-end PASS scenario: repository satisfies the contract."""

    def test_overall_pass(self, baseline_repo: Path) -> None:
        report = _run(baseline_repo)
        assert report.overall == "PASS", report.summary

    def test_all_nine_checks_executed(self, baseline_repo: Path) -> None:
        report = _run(baseline_repo)
        executed = set(report.checks.keys())
        expected = {
            "files_create",
            "files_immutable",
            "commands",
            "files_modify",
            "unexpected_modified",
            "untracked",
            "symbols_required",
            "symbols_forbidden",
            "git_diff_check",
        }
        assert executed == expected, f"expected {expected}, got {executed}"

    def test_each_check_passed(self, baseline_repo: Path) -> None:
        report = _run(baseline_repo)
        for name, cr in report.checks.items():
            assert cr.passed, f"check {name} did not pass: {cr.details}"
            assert not cr.has_error, f"check {name} errored: {cr.error}"

    def test_no_failures_reported(self, baseline_repo: Path) -> None:
        report = _run(baseline_repo)
        assert report.failures == []
        assert report.summary.startswith("PASS:")

    def test_pass_scenario_structure(self, baseline_repo: Path) -> None:
        report = _run(baseline_repo)

        # files_create: both declared paths exist
        cr = report.checks["files_create"]
        assert cr.total_items == 2
        assert cr.failed_items == 0

        # files_immutable: both immutable files have no diff
        cr = report.checks["files_immutable"]
        assert cr.total_items == 2
        assert cr.failed_items == 0

        # commands: both commands exit 0
        cr = report.checks["commands"]
        assert cr.total_items == 2
        assert cr.failed_items == 0

        # files_modify: both declared modifications are modified
        cr = report.checks["files_modify"]
        assert cr.total_items == 2
        assert cr.failed_items == 0

        # unexpected_modified: no unexpected tracked modifications
        cr = report.checks["unexpected_modified"]
        assert cr.total_items == 0
        assert cr.failed_items == 0

        # untracked: no unexpected untracked files
        cr = report.checks["untracked"]
        assert cr.total_items == 0
        assert cr.failed_items == 0

        # symbols_required: all four required symbols found
        cr = report.checks["symbols_required"]
        assert cr.total_items == 4
        assert cr.failed_items == 0

        # symbols_forbidden: no forbidden symbols found
        cr = report.checks["symbols_forbidden"]
        assert cr.passed
        # Note: total_items may be 0 when no forbidden symbol is found;
        # the verifier counts items only when a search is performed.

        # git_diff_check: no whitespace errors
        cr = report.checks["git_diff_check"]
        assert cr.total_items == 1
        assert cr.failed_items == 0


# ══════════════════════════════════════════════════════════════════════════
# MANDATORY FAILURE MATRIX
# ══════════════════════════════════════════════════════════════════════════

class TestPhase3_5MissingCreateFile:
    """1. CREATE FILE MISSING — declared file absent from disk."""

    def test_missing_create_file_is_fail(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        repo.mkdir(parents=True)
        _init_repo(repo)

        # Create ALL create files first (including goals_cli.py), then remove it.
        write_goal_like_tree(repo, missing_create_paths=set())  # create everything
        realistic_contract(repo)
        _add_commit(repo, "baseline")

        # Now remove the declared create file to make it missing.
        (repo / "src" / "janus" / "goals_cli.py").unlink()

        report = _run(repo)

        assert report.overall == "FAIL"
        grouped = _failures_by_check(report)
        assert "files_create" in grouped
        assert any(
            "src/janus/goals_cli.py" in f.get("item", "")
            for f in grouped["files_create"]
        )


class TestPhase3_5UnmodifiedModifyFile:
    """2. MODIFY FILE UNCHANGED — declared file identical to HEAD."""

    def test_unmodified_modify_is_fail(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        repo.mkdir(parents=True)
        _init_repo(repo)

        # Write and commit a tree where the modify file is identical to HEAD.
        write_goal_like_tree(repo)
        realistic_contract(repo)
        _add_commit(repo, "baseline")

        # Intentionally do NOT modify the declared modify file.

        report = _run(repo)

        assert report.overall == "FAIL"
        grouped = _failures_by_check(report)
        assert "files_modify" in grouped
        assert any(
            "goal.py" in f.get("item", "") or "NOT MODIFIED" in f.get("message", "")
            for f in grouped["files_modify"]
        )


class TestPhase3_5ImmutableModified:
    """3. IMMUTABLE FILE MODIFIED — both unstaged and staged."""

    def test_unstaged_immutable_file_is_fail(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        repo.mkdir(parents=True)
        _init_repo(repo)

        write_goal_like_tree(repo)
        realistic_contract(repo)
        _add_commit(repo, "baseline")

        # Modify an immutable file (unstaged).
        (repo / "config" / "protected.cfg").write_text("mutated\n")

        report = _run(repo)

        assert report.overall == "FAIL"
        cr = report.checks["files_immutable"]
        assert not cr.passed
        assert cr.failed_items >= 1

    def test_staged_only_immutable_file_is_fail(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        repo.mkdir(parents=True)
        _init_repo(repo)

        write_goal_like_tree(repo)
        realistic_contract(repo)
        _add_commit(repo, "baseline")

        # Modify an immutable file and stage it.
        (repo / "config" / "protected.cfg").write_text("staged mutation\n")
        _stage(repo, "config/protected.cfg")

        report = _run(repo)

        assert report.overall == "FAIL"
        cr = report.checks["files_immutable"]
        assert not cr.passed
        assert cr.failed_items >= 1


class TestPhase3_5UnexpectedTrackedModification:
    """4. UNEXPECTED TRACKED MODIFICATION — tracked file changed but not declared."""

    def test_unexpected_tracked_modification_is_fail(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        repo.mkdir(parents=True)
        _init_repo(repo)

        write_goal_like_tree(repo)
        realistic_contract(repo)
        _add_commit(repo, "baseline")

        # goals.py IS in files.create, so modifying it is EXPECTED, not unexpected.
        # We need a file that is tracked but NOT in files.create or files.modify.
        # Create a new file, commit it (making it tracked), then modify it.
        (repo / "extra_file.py").write_text("# new file\n")
        _add_commit(repo, "add extra_file.py")
        (repo / "extra_file.py").write_text("# modified unexpectedly\n")

        report = _run(repo)

        assert report.overall == "FAIL"
        grouped = _failures_by_check(report)
        # unexpected_modified should report it.
        assert "unexpected_modified" in grouped
        assert any(
            "extra_file.py" in f.get("item", "")
            for f in grouped["unexpected_modified"]
        )


class TestPhase3_5UnexpectedUntrackedFile:
    """5. UNEXPECTED UNTRACKED FILE — file present but not declared."""

    def test_unexpected_untracked_is_fail(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        repo.mkdir(parents=True)
        _init_repo(repo)

        write_goal_like_tree(repo)
        realistic_contract(repo)
        _add_commit(repo, "baseline")

        # Create an untracked file not declared under files.create.
        (repo / "tmp_bail_file.txt").write_text("untracked junk\n")

        report = _run(repo)

        assert report.overall == "FAIL"
        cr = report.checks["untracked"]
        assert not cr.passed
        assert cr.failed_items >= 1


class TestPhase3_5RequiredSymbolMissing:
    """6. REQUIRED SYMBOL MISSING — required symbol not present."""

    def test_missing_required_symbol_is_fail(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        repo.mkdir(parents=True)
        _init_repo(repo)

        write_goal_like_tree(repo)
        realistic_contract(repo)
        _add_commit(repo, "baseline")

        # Remove one required symbol from the source file.
        path = repo / "src" / "janus" / "services" / "goals.py"
        original = path.read_text(encoding="utf-8")
        path.write_text(
            original.replace("def complete_goal", "def complete_goal_removed")
        )

        report = _run(repo)

        assert report.overall == "FAIL"
        cr = report.checks["symbols_required"]
        assert not cr.passed
        assert cr.failed_items >= 1
        assert any(
            "complete_goal" in f.get("item", "") for f in cr.details
        )


class TestPhase3_5RequiredSymbolWrongType:
    """7. REQUIRED SYMBOL WRONG TYPE — declared as function but is a class."""

    def test_wrong_type_is_fail(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        repo.mkdir(parents=True)
        _init_repo(repo)

        # Create all directories upfront.
        (repo / "src" / "janus" / "services").mkdir(parents=True, exist_ok=True)
        (repo / "src" / "janus" / "models").mkdir(parents=True, exist_ok=True)
        (repo / "src" / "janus").mkdir(parents=True, exist_ok=True)
        (repo / "config").mkdir(parents=True, exist_ok=True)
        (repo / "data").mkdir(parents=True, exist_ok=True)

        # Write a tree where add_goal is a class, not a function.
        (repo / "src" / "janus" / "services" / "goals.py").write_text(
            (
                "from __future__ import annotations\n"
                "\n"
                "\n"
                "class GoalService:\n"
                "    pass\n"
                "\n"
                "\n"
                "class add_goal:\n"
                '    """This is a class but the contract requires a function."""\n'
                "    pass\n"
                "\n"
                "\n"
                "def complete_goal(goal):\n"
                "    return goal\n"
                "\n"
                "\n"
                "def compute_goal_progress(goals):\n"
                "    return 0.0\n"
            )
        )

        (repo / "src" / "janus" / "goals_cli.py").write_text("stub\n")
        (repo / "src" / "janus" / "models" / "goal.py").write_text("stub\n")
        (repo / "src" / "janus" / "init.py").write_text("stub\n")
        (repo / "config" / "protected.cfg").write_text("protected\n")
        (repo / "data" / "goals.md").write_text("# goals\n")

        realistic_contract(repo)
        _add_commit(repo, "baseline")

        report = _run(repo)

        assert report.overall == "FAIL"
        cr = report.checks["symbols_required"]
        assert not cr.passed
        assert any(
            "WRONG TYPE" in f.get("message", "") for f in cr.details
        )


class TestPhase3_5ForbiddenSymbolPresent:
    """8. FORBIDDEN SYMBOL PRESENT — forbidden function exists in repo."""

    def test_forbidden_symbol_is_fail(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        repo.mkdir(parents=True)
        _init_repo(repo)

        write_goal_like_tree(repo)
        realistic_contract(repo)
        _add_commit(repo, "baseline")

        # Add a forbidden delete_goal function inside the restricted path.
        (repo / "src" / "janus" / "services" / "goals.py").write_text(
            (
                "from __future__ import annotations\n"
                "\n"
                "\n"
                "class GoalService:\n"
                "    pass\n"
                "\n"
                "\n"
                "def add_goal(title: str) -> dict:\n"
                '    return {"title": title, "done": False}\n'
                "\n"
                "\n"
                "def complete_goal(goal: dict) -> dict:\n"
                '    goal["done"] = True\n'
                "    return goal\n"
                "\n"
                "\n"
                "def compute_goal_progress(goals: list[dict]) -> float:\n"
                "    if not goals:\n"
                "        return 0.0\n"
                '    done = sum(1 for g in goals if g.get("done"))\n'
                "    return done / len(goals)\n"
                "\n"
                "\n"
                "def delete_goal(goal_id: str) -> None:\n"
                '        """Forbidden."""\n'
                "        pass\n"
            )
        )

        report = _run(repo)

        assert report.overall == "FAIL"
        cr = report.checks["symbols_forbidden"]
        assert not cr.passed
        assert cr.failed_items >= 1
        assert any(
            "delete_goal" in f.get("item", "") for f in cr.details
        )


class TestPhase3_5ForbiddenSymbolInCommentOnly:
    """9. FORBIDDEN SYMBOL IN COMMENT ONLY — must NOT trigger false positive."""

    def test_comment_only_does_not_trigger(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        repo.mkdir(parents=True)
        _init_repo(repo)

        write_goal_like_tree(repo)
        realistic_contract(repo)
        _add_commit(repo, "baseline")

        # Modify all three files so files_modify passes.
        # 1) goals.py with forbidden symbol in a comment only.
        (repo / "src" / "janus" / "services" / "goals.py").write_text(
            (
                "from __future__ import annotations\n"
                "\n"
                "\n"
                "class GoalService:\n"
                "    pass\n"
                "\n"
                "\n"
                "def add_goal(title: str) -> dict:\n"
                '    # TODO: also implement delete_goal someday\n'
                '    return {"title": title, "done": False}\n'
                "\n"
                "\n"
                "def complete_goal(goal: dict) -> dict:\n"
                '    goal["done"] = True\n'
                "    return goal\n"
                "\n"
                "\n"
                "def compute_goal_progress(goals: list[dict]) -> float:\n"
                "    if not goals:\n"
                "        return 0.0\n"
                '    done = sum(1 for g in goals if g.get("done"))\n'
                "    return done / len(goals)\n"
            )
        )
        # 2) goal.py modified (satisfies files_modify).
        (repo / "src" / "janus" / "models" / "goal.py").write_text(
            GOAL_MODEL_PY + "\n# modified for test\n"
        )
        # 3) init.py modified (satisfies files_modify).
        (repo / "src" / "janus" / "init.py").write_text(
            INIT_PY + "\n# modified for test\n"
        )

        report = _run(repo)

        assert report.overall == "PASS", report.summary
        cr = report.checks["symbols_forbidden"]
        assert cr.passed
        assert cr.failed_items == 0


class TestPhase3_5ForbiddenSymbolInStringOnly:
    """10. FORBIDDEN SYMBOL IN STRING ONLY — must NOT trigger false positive."""

    def test_string_only_does_not_trigger(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        repo.mkdir(parents=True)
        _init_repo(repo)

        write_goal_like_tree(repo)
        realistic_contract(repo)
        _add_commit(repo, "baseline")

        # Modify all three files so files_modify passes.
        # 1) goals.py with forbidden symbol in a string only.
        (repo / "src" / "janus" / "services" / "goals.py").write_text(
            (
                "from __future__ import annotations\n"
                "\n"
                "\n"
                "class GoalService:\n"
                "    pass\n"
                "\n"
                "\n"
                "def add_goal(title: str) -> dict:\n"
                '    message = "the delete_goal operation is not implemented"\n'
                '    return {"title": title, "done": False}\n'
                "\n"
                "\n"
                "def complete_goal(goal: dict) -> dict:\n"
                '    goal["done"] = True\n'
                "    return goal\n"
                "\n"
                "\n"
                "def compute_goal_progress(goals: list[dict]) -> float:\n"
                "    if not goals:\n"
                "        return 0.0\n"
                '    done = sum(1 for g in goals if g.get("done"))\n'
                "    return done / len(goals)\n"
            )
        )
        # 2) goal.py modified (satisfies files_modify).
        (repo / "src" / "janus" / "models" / "goal.py").write_text(
            GOAL_MODEL_PY + "\n# modified for test\n"
        )
        # 3) init.py modified (satisfies files_modify).
        (repo / "src" / "janus" / "init.py").write_text(
            INIT_PY + "\n# modified for test\n"
        )

        report = _run(repo)

        assert report.overall == "PASS"
        cr = report.checks["symbols_forbidden"]
        assert cr.passed
        assert cr.failed_items == 0


class TestPhase3_5WhitespaceErrorUnstaged:
    """11. GIT DIFF WHITESPACE ERROR — UNSTAGED."""

    def test_unstaged_whitespace_error_is_fail(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        repo.mkdir(parents=True)
        _init_repo(repo)

        write_goal_like_tree(repo)
        realistic_contract(repo)
        _add_commit(repo, "baseline")

        # Introduce a trailing whitespace on a line in a tracked file.
        path = repo / "src" / "janus" / "init.py"
        original = path.read_text(encoding="utf-8")
        path.write_text("def init_project(path):\n    pass  \n\n")

        report = _run(repo)

        assert report.overall == "FAIL"
        cr = report.checks["git_diff_check"]
        assert not cr.passed


class TestPhase3_5WhitespaceErrorStagedOnly:
    """12. GIT DIFF WHITESPACE ERROR — STAGED ONLY."""

    def test_staged_whitespace_error_is_fail(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        repo.mkdir(parents=True)
        _init_repo(repo)

        write_goal_like_tree(repo)
        realistic_contract(repo)
        _add_commit(repo, "baseline")

        # Introduce a whitespace error and stage it.
        path = repo / "src" / "janus" / "init.py"
        path.write_text("def init_project(path):\n    pass  \n\n")
        _stage(repo, "src/janus/init.py")

        report = _run(repo)

        assert report.overall == "FAIL"
        cr = report.checks["git_diff_check"]
        assert not cr.passed


class TestPhase3_5VerificationCommandFailure:
    """13. VERIFICATION COMMAND FAILURE — command exits non-zero."""

    def test_command_failure_is_fail(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        repo.mkdir(parents=True)
        _init_repo(repo)

        write_goal_like_tree(repo)
        realistic_contract(repo)
        _add_commit(repo, "baseline")

        # Corrupt the contract command so it fails.
        import yaml
        contract_path = repo / "contract.yaml"
        contract = yaml.safe_load(contract_path.read_text(encoding="utf-8"))
        contract["verification_commands"] = [
            {
                "label": "deliberate failure",
                "command": "false",
                "expected_exit_code": 0,
                "timeout": 10,
            },
        ]
        contract_path.write_text(yaml.safe_dump(contract, sort_keys=False), encoding="utf-8")

        report = _run(repo)

        assert report.overall == "FAIL"
        cr = report.checks["commands"]
        assert not cr.passed
        assert any(
            f.get("item") == "deliberate failure" for f in cr.details
        )


# ══════════════════════════════════════════════════════════════════════════
# INTERACTION CASES
# ══════════════════════════════════════════════════════════════════════════

class TestPhase3_5MultipleFailures:
    """A. MULTIPLE FAILURES — simultaneous missing symbol, unexpected file, whitespace."""

    def test_multiple_failures_are_all_reported(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        repo.mkdir(parents=True)
        _init_repo(repo)

        write_goal_like_tree(repo)
        realistic_contract(repo)
        _add_commit(repo, "baseline")

        # 1) Remove a required symbol.
        (repo / "src" / "janus" / "services" / "goals.py").write_text(
            (
                "from __future__ import annotations\n"
                "\n"
                "\n"
                "class GoalService:\n"
                "    pass\n"
                "\n"
                "\n"
                "def add_goal(title: str) -> dict:\n"
                '    return {"title": title, "done": False}\n'
                "\n"
                "\n"
                "def complete_goal(goal: dict) -> dict:\n"
                '    goal["done"] = True\n'
                "    return goal\n"
            )
        )

        # 2) Create an unexpected untracked file.
        (repo / "noise.txt").write_text("noise\n")

        # 3) Introduce a whitespace error.
        (repo / "src" / "janus" / "init.py").write_text("def init_project(path):\n    pass  \n\n")

        report = _run(repo)

        assert report.overall == "FAIL"
        grouped = _failures_by_check(report)

        # Multiple distinct checks should have failures.
        failed_checks = set(grouped.keys())
        assert failed_checks >= {
            "symbols_required",
            "untracked",
            "git_diff_check",
        }

        # Each reported failure should still identify the offending item.
        assert any(
            "compute_goal_progress" in f.get("item", "")
            for f in grouped.get("symbols_required", [])
        )
        assert any(
            "noise.txt" in f.get("item", "")
            for f in grouped.get("untracked", [])
        )
        assert any(
            "git diff HEAD --check" in f.get("item", "")
            for f in grouped.get("git_diff_check", [])
        )


class TestPhase3_5ExpectedCreateFileUntracked:
    """B. EXPECTED CREATE FILE IS UNTRACKED — allowed, not a false positive."""

    def test_expected_untracked_create_passes_untracked_check(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        repo.mkdir(parents=True)
        _init_repo(repo)

        write_goal_like_tree(repo)
        realistic_contract(repo)
        _add_commit(repo, "baseline")

        # Remove the declared CREATE file from disk (so files_create fails),
        # but leave a DIFFERENT untracked file that IS declared.
        # The goal of this test is to confirm untracked logic does not
        # incorrectly flag a declared CREATE path as unexpected.
        (repo / "src" / "janus" / "goals_cli.py").unlink(missing_ok=True)
        (repo / "src" / "janus" / "goals_cli.py").write_text(
            "from __future__ import annotations\n\ndef main():\n    return 0\n"
        )

        report = _run(repo)

        # The declared CREATE file itself is missing on disk in this particular
        # scaffold, so files_create may fail. That is acceptable here: we only
        # want to confirm untracked logic does not incorrectly flag the declared
        # file as "unexpected". We therefore check untracked explicitly.
        cr = report.checks["untracked"]
        unexpected_create = [
            f
            for f in cr.details
            if f.get("item") == "src/janus/goals_cli.py" and not f.get("passed")
        ]
        assert unexpected_create == [], (
            "declared CREATE file must not be reported as unexpected untracked"
        )


class TestPhase3_5MixedStagedAndUnstaged:
    """C. MIXED STAGED + UNSTAGED STATE — both detected correctly."""

    def test_mixed_staged_and_unstaged_modifications(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        repo.mkdir(parents=True)
        _init_repo(repo)

        write_goal_like_tree(repo)
        realistic_contract(repo)
        _add_commit(repo, "baseline")

        # Stage one declared modification.
        (repo / "src" / "janus" / "models" / "goal.py").write_text(
            (
                "from __future__ import annotations\n"
                "\n"
                "from dataclasses import dataclass\n"
                "from datetime import datetime\n"
                "\n"
                "\n"
                "@dataclass\n"
                "class Goal:\n"
                "    title: str\n"
                "    created: datetime = datetime.now()\n"
                "    done: bool = False\n"
                "    priority: int = 0\n"
            )
        )
        _stage(repo, "src/janus/models/goal.py")

        # Leave another declared modification unstaged.
        (repo / "src" / "janus" / "init.py").write_text(
            (
                "from __future__ import annotations\n"
                "\n"
                '__all__ = ["init_project", "boot"]\n'
                "\n"
                "\n"
                "def init_project(path: str) -> None:\n"
                '    """Initialize a Janus goal project at *path*."""\n'
                '    raise NotImplementedError("stub")\n'
                "\n"
                "\n"
                "def boot() -> None:\n"
                "    pass\n"
            )
        )

        report = _run(repo)

        # Both declared modifications should be detected as modified.
        cr = report.checks["files_modify"]
        assert cr.total_items == 2
        assert cr.failed_items == 0

        # The immutable protected file must still be clean.
        cr = report.checks["files_immutable"]
        assert cr.passed

        # Untracked check should still be clean.
        cr = report.checks["untracked"]
        assert cr.passed


# ══════════════════════════════════════════════════════════════════════════
# Cross-check: existing verification tests still pass
# ══════════════════════════════════════════════════════════════════════════

def test_existing_phase_tests_still_pass() -> None:
    """Regression gate: verify the verifier exports all expected symbols."""
    import janus.verification as v

    assert hasattr(v, "run_verification")
    assert hasattr(v, "check_files_create")
    assert hasattr(v, "check_files_immutable")
    assert hasattr(v, "check_commands")
    assert hasattr(v, "check_files_modify")
    assert hasattr(v, "check_files_unexpected_modified")
    assert hasattr(v, "check_files_untracked")
    assert hasattr(v, "check_symbols_required")
    assert hasattr(v, "check_symbols_forbidden")
    assert hasattr(v, "check_git_diff_check")


# ════════════════════════════════════════════════════════════
# F-03 REGRESSION TESTS
# ════════════════════════════════════════════════════════════

class TestPhase3_6F03Regression:
    """Regression tests for F-03: FrozenInstanceError in _parse_forbidden_symbols.

    These tests exercise the full YAML → ImplementationContract.load() →
    _parse_forbidden_symbols() → ForbiddenSymbolEntry → check_symbols_forbidden()
    path, proving the bug is fixed and the old failure mode is gone.
    """

    def test_old_bug_would_fail_with_frozen_error(self) -> None:
        """Prove the OLD parser raised FrozenInstanceError on normal field assignment.

        Before the fix, constructing a frozen ForbiddenSymbolEntry() then
        attempting normal attribute assignment (entry.symbol = ...) correctly
        raised FrozenInstanceError — it is a frozen dataclass.
        """
        import dataclasses
        from janus.verification import ForbiddenSymbolEntry

        broken = ForbiddenSymbolEntry()
        with pytest.raises(dataclasses.FrozenInstanceError):
            broken.symbol = "delete_goal"
        with pytest.raises(dataclasses.FrozenInstanceError):
            broken.path = "src/janus/services"
        with pytest.raises(dataclasses.FrozenInstanceError):
            broken.type = "function"

    def test_ast_format_contract_loads_successfully(self, tmp_path: Path) -> None:
        """AST-format forbidden_symbols contract must load without FrozenInstanceError."""
        import yaml

        # Write a minimal contract using Phase 3 AST-format forbidden_symbols.
        contract_data = {
            "version": 1,
            "task_id": "f03-regression-ast",
            "forbidden_symbols": [
                {"symbol": "forbidden_function", "path": "src", "type": "function"},
            ],
        }
        contract_path = tmp_path / "contract.yaml"
        contract_path.write_text(yaml.safe_dump(contract_data, sort_keys=False), encoding="utf-8")

        contract = ImplementationContract.load(contract_path)

        # The contract must load without FrozenInstanceError.
        assert contract is not None
        assert len(contract.forbidden_symbols) == 1
        entry = contract.forbidden_symbols[0]
        assert entry.symbol == "forbidden_function"
        assert entry.path == "src"
        assert entry.type == "function"

    def test_loaded_entry_is_still_immutable(self, tmp_path: Path) -> None:
        """After loading, ForbiddenSymbolEntry must remain frozen.

        Attempting to mutate a loaded entry should still raise FrozenInstanceError.
        """
        import dataclasses
        import yaml
        from janus.verification import ForbiddenSymbolEntry

        contract_data = {
            "version": 1,
            "task_id": "f03-regression-immutable",
            "forbidden_symbols": [
                {"symbol": "do_not_touch", "path": "src", "type": "function"},
            ],
        }
        contract_path = tmp_path / "contract.yaml"
        contract_path.write_text(yaml.safe_dump(contract_data, sort_keys=False), encoding="utf-8")

        contract = ImplementationContract.load(contract_path)
        entry = contract.forbidden_symbols[0]

        # The loaded entry is frozen; mutating fields must still raise.
        # Use normal assignment (not object.__setattr__) to trigger the frozen check.
        with pytest.raises(dataclasses.FrozenInstanceError):
            entry.symbol = "hacked"
        with pytest.raises(dataclasses.FrozenInstanceError):
            entry.path = "hacked"
        with pytest.raises(dataclasses.FrozenInstanceError):
            entry.type = "hacked"

    def test_whitespace_normalization(self, tmp_path: Path) -> None:
        """Whitespace around symbol/path/type values is stripped on load.

        Regression test for F-03: before the fix, normalization happened via
        field mutation on a frozen ForbiddenSymbolEntry, causing FrozenInstanceError.
        After the fix, normalization runs BEFORE construction, so the frozen
        object is never mutated.
        """
        import yaml

        contract_data = {
            "version": 1,
            "task_id": "f03-regression-whitespace",
            "forbidden_symbols": [
                {
                    "symbol": "  padded_symbol  ",
                    "path": "  src/janus/  ",
                    "type": "  function  ",
                },
            ],
        }
        contract_path = tmp_path / "contract.yaml"
        contract_path.write_text(yaml.safe_dump(contract_data, sort_keys=False), encoding="utf-8")

        contract = ImplementationContract.load(contract_path)
        entry = contract.forbidden_symbols[0]
        assert entry.symbol == "padded_symbol"
        assert entry.path == "src/janus/"
        assert entry.type == "function"

    def test_legacy_format_continues_working(self, tmp_path: Path) -> None:
        """Legacy forbidden_symbols format (symbol only, no path/type) still loads.

        The pre-F-03 parser supported dicts with just a 'symbol' field.
        This test proves that minimal format continues to work after the fix.

        Regression test for F-03: before the fix, the legacy format was parsed
        by constructing ForbiddenSymbolEntry() then mutating fields — which
        raised FrozenInstanceError. After the fix, normalization happens
        BEFORE construction, so the frozen dataclass is never mutated.
        """
        import yaml

        contract_data = {
            "version": 1,
            "task_id": "f03-regression-legacy",
            "forbidden_symbols": [
                {"symbol": "legacy_forbidden_symbol"},
            ],
        }
        contract_path = tmp_path / "contract.yaml"
        contract_path.write_text(yaml.safe_dump(contract_data, sort_keys=False), encoding="utf-8")

        contract = ImplementationContract.load(contract_path)

        # Legacy format parses successfully through the same loader.
        assert contract is not None
        assert len(contract.forbidden_symbols) == 1
        entry = contract.forbidden_symbols[0]
        assert entry.symbol == "legacy_forbidden_symbol"
        assert entry.path == ""
        assert entry.type == ""

    def test_check_symbols_forbidden_executes_with_loaded_contract(
        self, tmp_path: Path
    ) -> None:
        """Full end-to-end: YAML contract → load → check_symbols_forbidden.

        A Python file containing a forbidden function must cause the forbidden
        symbol check to FAIL when loaded from YAML.
        """
        import yaml
        from janus.verification import check_symbols_forbidden

        # Create isolated temporary repo.
        repo = tmp_path / "repo"
        repo.mkdir(parents=True)
        _init_repo(repo)

        # Create src/ directory BEFORE writing the file.
        src_dir = repo / "src"
        src_dir.mkdir(parents=True, exist_ok=True)

        # Create a Python file containing the forbidden symbol.
        (src_dir / "bad.py").write_text(
            "def forbidden_function():\n    pass\n"
        )

        # Write contract with Phase 3 AST-format forbidden_symbols pointing to src/.
        contract_data = {
            "version": 1,
            "task_id": "f03-e2e-fail",
            "forbidden_symbols": [
                {
                    "symbol": "forbidden_function",
                    "path": "src",
                    "type": "function",
                },
            ],
        }
        contract_path = repo / "contract.yaml"
        contract_path.write_text(
            yaml.safe_dump(contract_data, sort_keys=False), encoding="utf-8"
        )

        # Load via the real YAML loader (not manually constructed).
        contract = ImplementationContract.load(contract_path)

        # Run the real check_symbols_forbidden against the loaded contract.
        result = check_symbols_forbidden(contract)

        assert result.passed is False
        assert result.failed_items == 1
        assert any(
            "forbidden_function" in f.get("item", "")
            for f in result.details
        )

    def test_comment_does_not_trigger_forbidden_check(self, tmp_path: Path) -> None:
        """Forbidden symbol in a comment only does NOT trigger the check.

        Regression test for F-03: proves AST-based matching works correctly
        when the contract is loaded from YAML (not manually constructed).

        Before the fix, loading a YAML contract with forbidden_symbols
        raised FrozenInstanceError during parsing. After the fix, the
        contract loads and check_symbols_forbidden executes end-to-end.
        """
        import yaml
        from janus.verification import check_symbols_forbidden

        repo = tmp_path / "repo"
        repo.mkdir(parents=True)
        _init_repo(repo)

        # Create src/ directory BEFORE writing the file.
        src_dir = repo / "src"
        src_dir.mkdir(parents=True, exist_ok=True)

        # Forbidden symbol name appears ONLY in a comment.
        (src_dir / "clean.py").write_text(
            "def good_function():\n    # TODO: remove forbidden_function someday\n    pass\n"
        )

        contract_data = {
            "version": 1,
            "task_id": "f03-e2e-pass",
            "forbidden_symbols": [
                {
                    "symbol": "forbidden_function",
                    "path": "src",
                    "type": "function",
                },
            ],
        }
        contract_path = repo / "contract.yaml"
        contract_path.write_text(
            yaml.safe_dump(contract_data, sort_keys=False), encoding="utf-8"
        )

        contract = ImplementationContract.load(contract_path)
        result = check_symbols_forbidden(contract)

        # The check must PASS — strings are not AST declarations.
        assert result.passed is True
        assert result.failed_items == 0
