# ══════════════════════════════════════════════════════════════════════
# Phase 3 Remediation Tests — F-01 and F-02
# ══════════════════════════════════════════════════════════════════════

from pathlib import Path
from janus.verification import (
    ImplementationContract,
    RequiredSymbolEntry,
    ForbiddenSymbolEntry,
    check_symbols_required,
    check_symbols_forbidden,
    check_git_diff_check,
    run_verification,
)

import subprocess


class TestF01MalformedModuleSymbolDefinitions:
    """F-01: Malformed module-based symbol definitions must not be silently skipped.

    When a module-based required_symbols entry has 'module' set but
    'symbols' is missing or empty, the check must FAIL deterministically
    with a clear error message.
    """

    def test_module_present_no_symbols_key_fails(self, tmp_path: Path) -> None:
        """FAIL: module present but 'symbols' key missing entirely."""
        contract = ImplementationContract(
            version=1, task_id="test",
            required_symbols=[RequiredSymbolEntry(
                module="janus.verification",
                # No 'symbols' key — should fail
            )],
            root=tmp_path,
        )
        result = check_symbols_required(contract)
        assert result.passed is False
        assert result.total_items == 1
        assert result.failed_items == 1
        assert "MALFORMED DEFINITION" in result.details[0]["message"]
        assert "no symbols defined" in result.details[0]["message"]

    def test_module_present_empty_symbols_list_fails(self, tmp_path: Path) -> None:
        """FAIL: module present but 'symbols' is an empty list."""
        contract = ImplementationContract(
            version=1, task_id="test",
            required_symbols=[RequiredSymbolEntry(
                module="janus.verification",
                symbols=[],
            )],
            root=tmp_path,
        )
        result = check_symbols_required(contract)
        assert result.passed is False
        assert result.total_items == 1
        assert result.failed_items == 1
        assert "MALFORMED DEFINITION" in result.details[0]["message"]

    def test_module_without_symbols_error_clear(self, tmp_path: Path) -> None:
        """Verify the error message clearly explains the requirement."""
        contract = ImplementationContract(
            version=1, task_id="test",
            required_symbols=[RequiredSymbolEntry(
                module="some.module",
            )],
            root=tmp_path,
        )
        result = check_symbols_required(contract)
        msg = result.details[0]["message"]
        assert "MALFORMED" in msg
        assert "module" in msg
        assert "symbols" in msg.lower()
        assert "non-empty" in msg.lower() or "no symbols" in msg.lower()

    def test_module_with_valid_symbols_still_works(self, tmp_path: Path) -> None:
        """Valid legacy module-based definitions still work correctly."""
        # Import check: janus.verification has run_verification
        contract = ImplementationContract(
            version=1, task_id="test",
            required_symbols=[RequiredSymbolEntry(
                module="janus.verification",
                symbols=["run_verification"],
            )],
            root=tmp_path,
        )
        result = check_symbols_required(contract)
        # run_verification exists in janus.verification → should PASS
        assert result.passed is True
        assert result.total_items == 1
        assert result.failed_items == 0


class TestF02ForbiddenSymbolTypeSemantics:
    """F-02: Document and test forbidden symbol type semantics.

    - No type or empty type: symbol is forbidden regardless of declaration type
    - type: "function": only matches FunctionDef and AsyncFunctionDef
    - type: "class": only matches ClassDef
    """

    def _make_repo_with_symbol(
        self, tmp_path: Path, content: str, rel_path: str = "src/test.py"
    ) -> Path:
        """Create a Git repo with a Python file containing a symbol."""
        subprocess.run(["git", "init", "-q"], cwd=str(tmp_path),
                       capture_output=True, timeout=10)
        subprocess.run(["git", "config", "user.email", "test@test.com"],
                       cwd=str(tmp_path), capture_output=True, timeout=10)
        subprocess.run(["git", "config", "user.name", "Test"],
                       cwd=str(tmp_path), capture_output=True, timeout=10)
        file_path = tmp_path / rel_path
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content)
        subprocess.run(["git", "add", "."], cwd=str(tmp_path),
                       capture_output=True, timeout=10)
        subprocess.run(["git", "commit", "-m", "init"], cwd=str(tmp_path),
                       capture_output=True, timeout=10)
        return tmp_path

    def test_no_type_forbids_any_declaration(self, tmp_path: Path) -> None:
        """No type → forbidden regardless of whether it's a function or class."""
        self._make_repo_with_symbol(
            tmp_path,
            "class BadClass:\n    pass\n"
        )
        contract = ImplementationContract(
            version=1, task_id="test",
            forbidden_symbols=[ForbiddenSymbolEntry(
                symbol="BadClass",
                # No type → any declaration type is forbidden
            )],
            root=tmp_path,
        )
        result = check_symbols_forbidden(contract)
        assert result.passed is False
        assert result.total_items == 1
        assert result.failed_items == 1

    def test_empty_type_forbids_any_declaration(self, tmp_path: Path) -> None:
        """Empty type string → forbidden regardless of declaration type."""
        self._make_repo_with_symbol(
            tmp_path,
            "def bad_function():\n    pass\n"
        )
        contract = ImplementationContract(
            version=1, task_id="test",
            forbidden_symbols=[ForbiddenSymbolEntry(
                symbol="bad_function",
                type="",  # Empty → any type forbidden
            )],
            root=tmp_path,
        )
        result = check_symbols_forbidden(contract)
        assert result.passed is False
        assert result.total_items == 1
        assert result.failed_items == 1

    def test_type_function_only_matches_functions(self, tmp_path: Path) -> None:
        """type: "function" only matches function/async function, not classes."""
        # Create a file with both a function and a class with the same name
        # (unusual but possible in Python — class shadows function)
        self._make_repo_with_symbol(
            tmp_path,
            "def deprecated_api():\n    pass\n"
        )
        contract = ImplementationContract(
            version=1, task_id="test",
            forbidden_symbols=[ForbiddenSymbolEntry(
                symbol="deprecated_api",
                type="function",
            )],
            root=tmp_path,
        )
        result = check_symbols_forbidden(contract)
        assert result.passed is False

    def test_type_function_does_not_match_classes(self, tmp_path: Path) -> None:
        """type: "function" does NOT match a class declaration."""
        self._make_repo_with_symbol(
            tmp_path,
            "class DeprecatedAPI:\n    pass\n"
        )
        contract = ImplementationContract(
            version=1, task_id="test",
            forbidden_symbols=[ForbiddenSymbolEntry(
                symbol="DeprecatedAPI",
                type="function",  # Looking for functions, not classes
            )],
            root=tmp_path,
        )
        result = check_symbols_forbidden(contract)
        # Function type should NOT match class → PASS (no forbidden found)
        assert result.passed is True
        assert result.total_items == 0
        assert result.failed_items == 0

    def test_type_class_only_matches_classes(self, tmp_path: Path) -> None:
        """type: "class" only matches ClassDef, not functions."""
        self._make_repo_with_symbol(
            tmp_path,
            "class ForbiddenClass:\n    pass\n"
        )
        contract = ImplementationContract(
            version=1, task_id="test",
            forbidden_symbols=[ForbiddenSymbolEntry(
                symbol="ForbiddenClass",
                type="class",
            )],
            root=tmp_path,
        )
        result = check_symbols_forbidden(contract)
        assert result.passed is False

    def test_type_class_does_not_match_functions(self, tmp_path: Path) -> None:
        """type: "class" does NOT match function declarations."""
        self._make_repo_with_symbol(
            tmp_path,
            "def forbidden_func():\n    pass\n"
        )
        contract = ImplementationContract(
            version=1, task_id="test",
            forbidden_symbols=[ForbiddenSymbolEntry(
                symbol="forbidden_func",
                type="class",  # Looking for classes, not functions
            )],
            root=tmp_path,
        )
        result = check_symbols_forbidden(contract)
        # Class type should NOT match function → PASS
        assert result.passed is True
        assert result.total_items == 0
        assert result.failed_items == 0

    def test_type_async_function_matches_async_functions(self, tmp_path: Path) -> None:
        """type: "function" matches async functions (they are functions)."""
        self._make_repo_with_symbol(
            tmp_path,
            "async def deprecated_async():\n    pass\n"
        )
        contract = ImplementationContract(
            version=1, task_id="test",
            forbidden_symbols=[ForbiddenSymbolEntry(
                symbol="deprecated_async",
                type="function",  # Async functions are functions
            )],
            root=tmp_path,
        )
        result = check_symbols_forbidden(contract)
        assert result.passed is False

    def test_type_class_does_not_match_async_functions(self, tmp_path: Path) -> None:
        """type: "class" does NOT match async functions."""
        self._make_repo_with_symbol(
            tmp_path,
            "async def deprecated_async():\n    pass\n"
        )
        contract = ImplementationContract(
            version=1, task_id="test",
            forbidden_symbols=[ForbiddenSymbolEntry(
                symbol="deprecated_async",
                type="class",  # Looking for classes only
            )],
            root=tmp_path,
        )
        result = check_symbols_forbidden(contract)
        # Class type should NOT match async function → PASS
        assert result.passed is True
        assert result.total_items == 0
        assert result.failed_items == 0


# ══════════════════════════════════════════════════════════════════════
# Original Phase 3 Tests (non-remediation)
# ══════════════════════════════════════════════════════════════════════

class TestCheckSymbolsRequired:
    """Tests for check_symbols_required — verify required symbols exist
    using AST-based detection."""

    def _make_contract_with_required_symbol(
        self, tmp_path: Path, symbol: str, symbol_type: str = ""
    ) -> tuple[Path, ImplementationContract]:
        """Create a minimal Python file with a symbol and a contract."""
        src_dir = tmp_path / "src"
        src_dir.mkdir(parents=True, exist_ok=True)
        py_file = src_dir / "example.py"
        if symbol_type == "class":
            py_file.write_text(f"class {symbol}:\n    pass\n")
        else:
            py_file.write_text(f"def {symbol}():\n    pass\n")
        contract = ImplementationContract(
            version=1, task_id="test",
            required_symbols=[RequiredSymbolEntry(
                path="src/example.py",
                symbol=symbol,
                type=symbol_type,
            )],
            root=tmp_path,
        )
        return tmp_path, contract

    def test_required_function_exists_passes(self, tmp_path: Path) -> None:
        """PASS: required function exists in Python file."""
        tmp_path, contract = self._make_contract_with_required_symbol(
            tmp_path, "my_function", "function"
        )
        result = check_symbols_required(contract)
        assert result.passed is True
        assert result.total_items == 1
        assert result.failed_items == 0

    def test_required_class_exists_passes(self, tmp_path: Path) -> None:
        """PASS: required class exists in Python file."""
        tmp_path, contract = self._make_contract_with_required_symbol(
            tmp_path, "MyClass", "class"
        )
        result = check_symbols_required(contract)
        assert result.passed is True
        assert result.total_items == 1
        assert result.failed_items == 0

    def test_required_symbol_missing_fails(self, tmp_path: Path) -> None:
        """FAIL: required symbol does not exist."""
        src_dir = tmp_path / "src"
        src_dir.mkdir(parents=True, exist_ok=True)
        (src_dir / "example.py").write_text("# empty file\n")
        contract = ImplementationContract(
            version=1, task_id="test",
            required_symbols=[RequiredSymbolEntry(
                path="src/example.py",
                symbol="nonexistent_function",
                type="function",
            )],
            root=tmp_path,
        )
        result = check_symbols_required(contract)
        assert result.passed is False
        assert result.total_items == 1
        assert result.failed_items == 1

    def test_wrong_symbol_type_fails(self, tmp_path: Path) -> None:
        """FAIL: symbol exists but has wrong type."""
        src_dir = tmp_path / "src"
        src_dir.mkdir(parents=True, exist_ok=True)
        (src_dir / "example.py").write_text("def my_func():\n    pass\n")
        contract = ImplementationContract(
            version=1, task_id="test",
            required_symbols=[RequiredSymbolEntry(
                path="src/example.py",
                symbol="my_func",
                type="class",  # Wrong type
            )],
            root=tmp_path,
        )
        result = check_symbols_required(contract)
        assert result.passed is False
        assert result.failed_items == 1

    def test_symbol_in_comment_only_not_found(self, tmp_path: Path) -> None:
        """FAIL: symbol name only in comment doesn't count."""
        src_dir = tmp_path / "src"
        src_dir.mkdir(parents=True, exist_ok=True)
        (src_dir / "example.py").write_text(
            "# This file has function foo in a comment\n"
            "# def foo():  # commented out\n"
            "x = 42\n"
        )
        contract = ImplementationContract(
            version=1, task_id="test",
            required_symbols=[RequiredSymbolEntry(
                path="src/example.py",
                symbol="foo",
                type="function",
            )],
            root=tmp_path,
        )
        result = check_symbols_required(contract)
        assert result.passed is False
        assert result.total_items == 1
        assert result.failed_items == 1

    def test_symbol_in_string_only_not_found(self, tmp_path: Path) -> None:
        """FAIL: symbol name only in string literal doesn't count."""
        src_dir = tmp_path / "src"
        src_dir.mkdir(parents=True, exist_ok=True)
        (src_dir / "example.py").write_text(
            '"""This docstring mentions bar"""\n'
            'x = "bar"\n'
            '# The string "bar" is not a def\n'
        )
        contract = ImplementationContract(
            version=1, task_id="test",
            required_symbols=[RequiredSymbolEntry(
                path="src/example.py",
                symbol="bar",
                type="function",
            )],
            root=tmp_path,
        )
        result = check_symbols_required(contract)
        assert result.passed is False
        assert result.total_items == 1
        assert result.failed_items == 1

    def test_malformed_python_source_fails(self, tmp_path: Path) -> None:
        """FAIL: malformed Python source produces deterministic failure."""
        src_dir = tmp_path / "src"
        src_dir.mkdir(parents=True, exist_ok=True)
        (src_dir / "broken.py").write_text(
            "def foo(\n    # syntax error - unclosed paren\n"
        )
        contract = ImplementationContract(
            version=1, task_id="test",
            required_symbols=[RequiredSymbolEntry(
                path="src/broken.py",
                symbol="foo",
                type="function",
            )],
            root=tmp_path,
        )
        result = check_symbols_required(contract)
        assert result.passed is False
        assert result.failed_items == 1
        assert "Syntax error" in result.details[0]["message"]

    def test_missing_source_file_fails(self, tmp_path: Path) -> None:
        """FAIL: referenced source file does not exist."""
        contract = ImplementationContract(
            version=1, task_id="test",
            required_symbols=[RequiredSymbolEntry(
                path="src/nonexistent.py",
                symbol="foo",
                type="function",
            )],
            root=tmp_path,
        )
        result = check_symbols_required(contract)
        assert result.passed is False
        assert result.total_items == 1
        assert result.failed_items == 1
        assert "MISSING FILE" in result.details[0]["message"]


class TestCheckSymbolsForbidden:
    """Tests for check_symbols_forbidden — verify forbidden symbols
    are absent using AST-based detection."""

    def _make_repo_with_python_file(
        self, tmp_path: Path, content: str, rel_path: str = "src/test.py"
    ) -> Path:
        """Create a Git repo with a Python file."""
        subprocess.run(["git", "init", "-q"], cwd=str(tmp_path),
                       capture_output=True, timeout=10)
        subprocess.run(["git", "config", "user.email", "test@test.com"],
                       cwd=str(tmp_path), capture_output=True, timeout=10)
        subprocess.run(["git", "config", "user.name", "Test"],
                       cwd=str(tmp_path), capture_output=True, timeout=10)
        file_path = tmp_path / rel_path
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content)
        subprocess.run(["git", "add", "."], cwd=str(tmp_path),
                       capture_output=True, timeout=10)
        subprocess.run(["git", "commit", "-m", "init"], cwd=str(tmp_path),
                       capture_output=True, timeout=10)
        return tmp_path

    def test_forbidden_function_exists_fails(self, tmp_path: Path) -> None:
        """FAIL: forbidden function exists in repository."""
        self._make_repo_with_python_file(
            tmp_path,
            "def delete_goal():\n    pass\n"
        )
        contract = ImplementationContract(
            version=1, task_id="test",
            forbidden_symbols=[ForbiddenSymbolEntry(
                symbol="delete_goal",
                type="function",
            )],
            root=tmp_path,
        )
        result = check_symbols_forbidden(contract)
        assert result.passed is False
        assert result.total_items == 1
        assert result.failed_items == 1

    def test_forbidden_class_exists_fails(self, tmp_path: Path) -> None:
        """FAIL: forbidden class exists in repository."""
        self._make_repo_with_python_file(
            tmp_path,
            "class DeprecatedFeature:\n    pass\n"
        )
        contract = ImplementationContract(
            version=1, task_id="test",
            forbidden_symbols=[ForbiddenSymbolEntry(
                symbol="DeprecatedFeature",
                type="class",
            )],
            root=tmp_path,
        )
        result = check_symbols_forbidden(contract)
        assert result.passed is False
        assert result.total_items == 1
        assert result.failed_items == 1

    def test_forbidden_symbol_absent_passes(self, tmp_path: Path) -> None:
        """PASS: forbidden symbol is absent from repository."""
        self._make_repo_with_python_file(
            tmp_path,
            "def good_function():\n    pass\n"
        )
        contract = ImplementationContract(
            version=1, task_id="test",
            forbidden_symbols=[ForbiddenSymbolEntry(
                symbol="bad_function",
                type="function",
            )],
            root=tmp_path,
        )
        result = check_symbols_forbidden(contract)
        assert result.passed is True
        assert result.total_items == 0
        assert result.failed_items == 0

    def test_symbol_in_comment_only_does_not_trigger(self, tmp_path: Path) -> None:
        """PASS: symbol in comment only does NOT trigger forbidden."""
        self._make_repo_with_python_file(
            tmp_path,
            "# This file mentions forbidden_func in a comment\n"
            "# def forbidden_func():  # commented out\n"
            "x = 42\n"
        )
        contract = ImplementationContract(
            version=1, task_id="test",
            forbidden_symbols=[ForbiddenSymbolEntry(
                symbol="forbidden_func",
                type="function",
            )],
            root=tmp_path,
        )
        result = check_symbols_forbidden(contract)
        assert result.passed is True
        assert result.total_items == 0
        assert result.failed_items == 0

    def test_symbol_in_string_only_does_not_trigger(self, tmp_path: Path) -> None:
        """PASS: symbol in string literal does NOT trigger forbidden."""
        self._make_repo_with_python_file(
            tmp_path,
            '"""Forbidden mention of secret_func"""\n'
            'x = "secret_func"\n'
            'print("secret_func")\n'
        )
        contract = ImplementationContract(
            version=1, task_id="test",
            forbidden_symbols=[ForbiddenSymbolEntry(
                symbol="secret_func",
                type="function",
            )],
            root=tmp_path,
        )
        result = check_symbols_forbidden(contract)
        assert result.passed is True
        assert result.total_items == 0
        assert result.failed_items == 0

    def test_async_function_detection(self, tmp_path: Path) -> None:
        """FAIL: async function is detected as a forbidden symbol."""
        self._make_repo_with_python_file(
            tmp_path,
            "async def deprecated_api():\n    pass\n"
        )
        contract = ImplementationContract(
            version=1, task_id="test",
            forbidden_symbols=[ForbiddenSymbolEntry(
                symbol="deprecated_api",
                type="function",  # Async functions are still functions
            )],
            root=tmp_path,
        )
        result = check_symbols_forbidden(contract)
        assert result.passed is False
        assert result.total_items == 1
        assert result.failed_items == 1

    def test_optional_path_restriction_works(self, tmp_path: Path) -> None:
        """FAIL: forbidden symbol found only when path restriction matches."""
        src_dir = tmp_path / "src"
        src_dir.mkdir(parents=True, exist_ok=True)
        (src_dir / "allowed.py").write_text("def bad_symbol():\n    pass\n")
        subprocess.run(["git", "init", "-q"], cwd=str(tmp_path),
                       capture_output=True, timeout=10)
        subprocess.run(["git", "config", "user.email", "test@test.com"],
                       cwd=str(tmp_path), capture_output=True, timeout=10)
        subprocess.run(["git", "config", "user.name", "Test"],
                       cwd=str(tmp_path), capture_output=True, timeout=10)
        subprocess.run(["git", "add", "."], cwd=str(tmp_path),
                       capture_output=True, timeout=10)
        subprocess.run(["git", "commit", "-m", "init"], cwd=str(tmp_path),
                       capture_output=True, timeout=10)

        # Only search src/allowed.py - should find it
        contract = ImplementationContract(
            version=1, task_id="test",
            forbidden_symbols=[ForbiddenSymbolEntry(
                symbol="bad_symbol",
                path="src/",
                type="function",
            )],
            root=tmp_path,
        )
        result = check_symbols_forbidden(contract)
        assert result.passed is False
        assert result.total_items == 1

    def test_repository_wide_search_works(self, tmp_path: Path) -> None:
        """FAIL: repository-wide search finds forbidden symbol anywhere."""
        (tmp_path / "subdir").mkdir(parents=True, exist_ok=True)
        (tmp_path / "subdir" / "deep.py").write_text(
            "def secret_impl():\n    pass\n"
        )
        (tmp_path / "other.py").write_text("x = 1\n")
        subprocess.run(["git", "init", "-q"], cwd=str(tmp_path),
                       capture_output=True, timeout=10)
        subprocess.run(["git", "config", "user.email", "test@test.com"],
                       cwd=str(tmp_path), capture_output=True, timeout=10)
        subprocess.run(["git", "config", "user.name", "Test"],
                       cwd=str(tmp_path), capture_output=True, timeout=10)
        subprocess.run(["git", "add", "."], cwd=str(tmp_path),
                       capture_output=True, timeout=10)
        subprocess.run(["git", "commit", "-m", "init"], cwd=str(tmp_path),
                       capture_output=True, timeout=10)

        contract = ImplementationContract(
            version=1, task_id="test",
            forbidden_symbols=[ForbiddenSymbolEntry(
                symbol="secret_impl",
                type="function",
            )],
            root=tmp_path,
        )
        result = check_symbols_forbidden(contract)
        assert result.passed is False
        assert result.total_items == 1


class TestCheckGitDiffCheck:
    """Tests for check_git_diff_check — verify no whitespace errors
    in Git diff using HEAD-based comparison (Phase 2.1 semantics)."""

    def _init_git_repo(self, tmp_path: Path) -> None:
        """Initialize a Git repo with user config and initial commit."""
        subprocess.run(["git", "init", "-q"], cwd=str(tmp_path),
                       capture_output=True, timeout=10)
        subprocess.run(["git", "config", "user.email", "test@test.com"],
                       cwd=str(tmp_path), capture_output=True, timeout=10)
        subprocess.run(["git", "config", "user.name", "Test"],
                       cwd=str(tmp_path), capture_output=True, timeout=10)
        (tmp_path / "README.md").write_text("# Test\n")
        subprocess.run(["git", "add", "."], cwd=str(tmp_path),
                       capture_output=True, timeout=10)
        subprocess.run(["git", "commit", "-m", "init"], cwd=str(tmp_path),
                       capture_output=True, timeout=10)

    def test_clean_repository_passes(self, tmp_path: Path) -> None:
        """PASS: clean repository has no whitespace errors."""
        self._init_git_repo(tmp_path)
        contract = ImplementationContract(
            version=1, task_id="test",
            root=tmp_path,
        )
        result = check_git_diff_check(contract)
        assert result.passed is True
        assert result.total_items == 1
        assert result.failed_items == 0

    def test_unstaged_whitespace_error_fails(self, tmp_path: Path) -> None:
        """FAIL: unstaged whitespace error (trailing whitespace) detected."""
        self._init_git_repo(tmp_path)
        (tmp_path / "test.py").write_text("def foo():\n    pass  \n")  # trailing ws
        subprocess.run(["git", "add", "test.py"], cwd=str(tmp_path),
                       capture_output=True, timeout=10)
        contract = ImplementationContract(
            version=1, task_id="test",
            root=tmp_path,
        )
        result = check_git_diff_check(contract)
        assert result.passed is False
        assert result.total_items == 1
        assert result.failed_items == 1

    def test_staged_whitespace_error_fails(self, tmp_path: Path) -> None:
        """FAIL: staged whitespace error detected (HEAD-based comparison)."""
        self._init_git_repo(tmp_path)
        src_dir = tmp_path / "src"
        src_dir.mkdir(parents=True, exist_ok=True)
        (src_dir / "mod.py").write_text("x = 1  \n")  # trailing whitespace

        # Stage the file
        subprocess.run(["git", "add", "src/mod.py"], cwd=str(tmp_path),
                       capture_output=True, timeout=10)
        # Commit so there's a HEAD
        subprocess.run(["git", "commit", "-m", "add mod"], cwd=str(tmp_path),
                       capture_output=True, timeout=10)

        # Now make another change that introduces whitespace error
        (src_dir / "mod.py").write_text("x = 2  \n")  # different trailing ws

        contract = ImplementationContract(
            version=1, task_id="test",
            root=tmp_path,
        )
        result = check_git_diff_check(contract)
        assert result.passed is False
        assert result.total_items == 1
        assert result.failed_items == 1

    def test_valid_unstaged_modification_passes(self, tmp_path: Path) -> None:
        """PASS: valid unstaged modification with no whitespace errors."""
        self._init_git_repo(tmp_path)
        (tmp_path / "test.py").write_text("def foo():\n    return 42\n")
        subprocess.run(["git", "add", "test.py"], cwd=str(tmp_path),
                       capture_output=True, timeout=10)
        subprocess.run(["git", "commit", "-m", "add"], cwd=str(tmp_path),
                       capture_output=True, timeout=10)
        # Modify without whitespace errors
        (tmp_path / "test.py").write_text("def foo():\n    return 99\n")
        contract = ImplementationContract(
            version=1, task_id="test",
            root=tmp_path,
        )
        result = check_git_diff_check(contract)
        assert result.passed is True
        assert result.total_items == 1
        assert result.failed_items == 0

    def test_valid_staged_modification_passes(self, tmp_path: Path) -> None:
        """PASS: valid staged modification with no whitespace errors."""
        self._init_git_repo(tmp_path)
        src_dir = tmp_path / "src"
        src_dir.mkdir(parents=True, exist_ok=True)
        (src_dir / "mod.py").write_text("x = 1\n")
        subprocess.run(["git", "add", "src/mod.py"], cwd=str(tmp_path),
                       capture_output=True, timeout=10)
        subprocess.run(["git", "commit", "-m", "add"], cwd=str(tmp_path),
                       capture_output=True, timeout=10)
        # Modify, then stage
        (src_dir / "mod.py").write_text("x = 2\n")
        subprocess.run(["git", "add", "src/mod.py"], cwd=str(tmp_path),
                       capture_output=True, timeout=10)
        contract = ImplementationContract(
            version=1, task_id="test",
            root=tmp_path,
        )
        result = check_git_diff_check(contract)
        assert result.passed is True
        assert result.total_items == 1
        assert result.failed_items == 0

    def test_command_failure_produces_deterministic_fail(self, tmp_path: Path) -> None:
        """FAIL: non-git directory produces deterministic failure."""
        # Don't initialize git — the command will fail
        (tmp_path / "test.py").write_text("x = 1\n")
        contract = ImplementationContract(
            version=1, task_id="test",
            root=tmp_path,
        )
        result = check_git_diff_check(contract)
        assert result.passed is False
        assert result.total_items == 1
        assert result.failed_items == 1
        # Should fail deterministically with a clear message
        msg = result.details[0]["message"]
        assert "NOT A GIT REPOSITORY" in msg or "GIT COMMAND FAILED" in msg


class TestPhase3Integration:
    """Integration tests that Phase 3 checks work together and integrate
    with run_verification."""

    def _init_git_repo(self, tmp_path: Path) -> None:
        subprocess.run(["git", "init", "-q"], cwd=str(tmp_path),
                       capture_output=True, timeout=10)
        subprocess.run(["git", "config", "user.email", "test@test.com"],
                       cwd=str(tmp_path), capture_output=True, timeout=10)
        subprocess.run(["git", "config", "user.name", "Test"],
                       cwd=str(tmp_path), capture_output=True, timeout=10)
        (tmp_path / "README.md").write_text("# Test\n")
        subprocess.run(["git", "add", "."], cwd=str(tmp_path),
                       capture_output=True, timeout=10)
        subprocess.run(["git", "commit", "-m", "init"], cwd=str(tmp_path),
                       capture_output=True, timeout=10)

    def test_all_phase3_checks_integrated(self, tmp_path: Path) -> None:
        """Verify all Phase 3 checks are registered in run_verification."""
        self._init_git_repo(tmp_path)
        (tmp_path / "src").mkdir(parents=True, exist_ok=True)
        (tmp_path / "src" / "app.py").write_text("def main():\n    pass\n")
        subprocess.run(["git", "add", "."], cwd=str(tmp_path),
                       capture_output=True, timeout=10)
        subprocess.run(["git", "commit", "-m", "add app"], cwd=str(tmp_path),
                       capture_output=True, timeout=10)

        # Create a contract with Phase 3 symbol checks
        contract_yaml = tmp_path / "contract.yaml"
        contract_yaml.write_text("""\
version: 1
task_id: test-phase3
description: Phase 3 integration test

files:
  create: []
  modify: []
  immutable: []
  forbidden: []

required_symbols:
  - path: src/app.py
    symbol: main
    type: function

forbidden_symbols: []

verification_commands: []

scope_constraints: {}

completion_gates: []
""")
        report = run_verification(str(contract_yaml))
        assert "symbols_required" in report.checks
        assert "symbols_forbidden" in report.checks
        assert "git_diff_check" in report.checks

        # Check symbols_required passed
        sr = report.checks["symbols_required"]
        assert sr.passed is True
        assert sr.total_items == 1

        # Check git_diff_check passed (clean repo)
        gd = report.checks["git_diff_check"]
        assert gd.passed is True

    def test_phase3_checks_affect_overall_pass_fail(self, tmp_path: Path) -> None:
        """Verify Phase 3 check failures affect overall VerificationReport."""
        self._init_git_repo(tmp_path)
        (tmp_path / "src").mkdir(parents=True, exist_ok=True)
        (tmp_path / "src" / "app.py").write_text("def main():\n    pass\n")
        subprocess.run(["git", "add", "."], cwd=str(tmp_path),
                       capture_output=True, timeout=10)
        subprocess.run(["git", "commit", "-m", "add app"], cwd=str(tmp_path),
                       capture_output=True, timeout=10)

        # Contract asks for a symbol that doesn't exist
        contract_yaml = tmp_path / "contract.yaml"
        contract_yaml.write_text("""\
version: 1
task_id: test-phase3-fail
description: Phase 3 failure test

files:
  create: []
  modify: []
  immutable: []
  forbidden: []

required_symbols:
  - path: src/app.py
    symbol: nonexistent
    type: function

forbidden_symbols: []

verification_commands: []

scope_constraints: {}

completion_gates: []
""")
        report = run_verification(str(contract_yaml))
        assert report.overall == "FAIL"
        assert report.checks["symbols_required"].passed is False

