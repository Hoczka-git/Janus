"""Verification Pipeline for Janus — Phase 1 implementation.

Provides contract loading, verification result models, and the first three
check functions (files_create, files_immutable, commands) plus an execution
framework that aggregates results into overall PASS/FAIL.

Remaining checks (files_modify, unexpected_modified, untracked,
symbols_required, symbols_forbidden, git_diff_check) are deferred to
later phases.
"""

from __future__ import annotations

import subprocess
import sys
import ast
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


# ──────────────────────────────────────────────────────────────────────
# Contract models
# ──────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ContractFileEntry:
    """A single file entry in the contract's create/modify/immutable/forbidden lists."""
    path: str
    description: str = ""
    reason: str = ""


@dataclass(frozen=True)
class ForbiddenFileEntry(ContractFileEntry):
    """A forbidden file entry with required type field."""
    type: str = "exists"  # "exists" or "modified"


@dataclass
class RequiredSymbolEntry:
    """A required symbol entry — supports both module-based import checking
    and file-based AST checking.

    Module-based (original MVP format):
        module: "janus.verification"
        symbols: ["run_verification", "CheckResult"]

    File-based (Phase 3 AST format):
        path: "src/example.py"
        symbol: "my_function"
        type: "function"   # optional: "function", "class", or "" for any
    """
    module: str = ""
    symbols: list[str] = field(default_factory=list)
    path: str = ""
    symbol: str = ""
    type: str = ""  # "function", "class", or ""


@dataclass(frozen=True)
class ForbiddenSymbolEntry:
    """A forbidden symbol entry for AST-based detection.

    Detects actual Python AST declarations (FunctionDef, ClassDef, etc.)
    rather than arbitrary textual occurrences.
    """
    symbol: str = ""
    path: str = ""   # optional path restriction; empty = search all repo Python files
    type: str = ""   # "function", "class", or "" for any


@dataclass(frozen=True)
class SymbolEntry:
    """A module + list of required symbols."""
    module: str
    symbols: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class VerificationCommand:
    """A command to run and check exit code."""
    label: str
    command: str
    expected_exit_code: int = 0
    timeout: int = 300


@dataclass(frozen=True)
class ScopeConstraints:
    """Scope constraints for the verification."""
    allowed_paths: list[str] = field(default_factory=list)
    excluded_paths: list[str] = field(default_factory=list)
    max_new_files: int | None = None
    max_lines_added: int | None = None


@dataclass(frozen=True)
class VerificationGate:
    """A single completion gate."""
    label: str
    type: str = "mechanical"  # "mechanical" or "human"


@dataclass
class ImplementationContract:
    """A loaded and validated implementation contract.

    All paths are relative to the workspace root (where the contract file lives).
    """

    version: int
    task_id: str
    created: str = ""
    created_by: str = ""
    description: str = ""

    # File lists
    files_create: list[ContractFileEntry] = field(default_factory=list)
    files_modify: list[ContractFileEntry] = field(default_factory=list)
    files_immutable: list[ContractFileEntry] = field(default_factory=list)
    files_forbidden: list[ForbiddenFileEntry] = field(default_factory=list)

    # Symbols
    required_symbols: list[RequiredSymbolEntry] = field(default_factory=list)
    forbidden_symbols: list[ForbiddenSymbolEntry] = field(default_factory=list)

    # Commands
    verification_commands: list[VerificationCommand] = field(default_factory=list)

    # Scope
    scope_constraints: ScopeConstraints = field(default_factory=ScopeConstraints)

    # Gates
    completion_gates: list[VerificationGate] = field(default_factory=list)

    # Workspace root (where the contract file lives)
    root: Path = field(default_factory=lambda: Path.cwd())

    @classmethod
    def load(cls, path: str | Path) -> ImplementationContract:
        """Load a YAML contract file and validate required fields."""
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Contract file not found: {path}")
        if not path.is_file():
            raise ValueError(f"Contract path is not a file: {path}")

        with open(path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f)

        if not isinstance(raw, dict):
            raise ValueError("Contract must be a YAML mapping")

        # Validate required fields
        version = raw.get("version")
        if not isinstance(version, int):
            raise ValueError(f"Contract 'version' must be an integer, got: {version!r}")

        task_id = raw.get("task_id")
        if not isinstance(task_id, str) or not task_id.strip():
            raise ValueError("Contract 'task_id' must be a non-empty string")

        root = path.parent.resolve()

        return cls(
            version=version,
            task_id=task_id.strip(),
            created=str(raw.get("created", "")),
            created_by=str(raw.get("created_by", "")),
            description=str(raw.get("description", "")),
            files_create=_parse_file_list(raw.get("files", {}).get("create", [])),
            files_modify=_parse_file_list(raw.get("files", {}).get("modify", [])),
            files_immutable=_parse_file_list(raw.get("files", {}).get("immutable", [])),
            files_forbidden=_parse_forbidden_list(raw.get("files", {}).get("forbidden", [])),
            required_symbols=_parse_symbol_list(raw.get("required_symbols", [])),
            forbidden_symbols=_parse_forbidden_symbols(raw.get("forbidden_symbols", [])),
            verification_commands=_parse_command_list(raw.get("verification_commands", [])),
            scope_constraints=_parse_scope(raw.get("scope_constraints", {})),
            completion_gates=_parse_gate_list(raw.get("completion_gates", [])),
            root=root,
        )

    def get_create_paths(self) -> list[Path]:
        """Return fully-resolved paths for all files in the create list."""
        return [self.root / entry.path for entry in self.files_create]

    def get_modify_paths(self) -> list[Path]:
        """Return fully-resolved paths for all files in the modify list."""
        return [self.root / entry.path for entry in self.files_modify]

    def get_immutable_paths(self) -> list[Path]:
        """Return fully-resolved paths for all files in the immutable list."""
        return [self.root / entry.path for entry in self.files_immutable]

    def get_relative_diff_name(self, absolute_path: Path) -> str | None:
        """Convert an absolute path to a relative path for git diff matching.

        Returns the relative path string if the absolute path is under the
        contract root, or None if it's outside the workspace.
        """
        try:
            return str(absolute_path.resolve().relative_to(self.root.resolve()))
        except ValueError:
            return None


# ──────────────────────────────────────────────────────────────────────
# Internal parsing helpers
# ──────────────────────────────────────────────────────────────────────

def _parse_file_list(raw: Any) -> list[ContractFileEntry]:
    """Parse a list of file entries from the contract."""
    if not isinstance(raw, list):
        return []
    result = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        path = item.get("path")
        if not isinstance(path, str) or not path.strip():
            continue
        result.append(ContractFileEntry(
            path=path.strip(),
            description=str(item.get("description", "")),
        ))
    return result


def _parse_forbidden_list(raw: Any) -> list[ForbiddenFileEntry]:
    """Parse the forbidden files list, requiring 'type' field."""
    if not isinstance(raw, list):
        return []
    result = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        path = item.get("path")
        if not isinstance(path, str) or not path.strip():
            continue
        ftype = str(item.get("type", "exists"))
        if ftype not in ("exists", "modified"):
            ftype = "exists"
        result.append(ForbiddenFileEntry(
            path=path.strip(),
            description=str(item.get("description", "")),
            reason=str(item.get("reason", "")),
            type=ftype,
        ))
    return result


def _parse_symbol_list(raw: Any) -> list[RequiredSymbolEntry]:
    """Parse the required_symbols list.

    Supports both legacy module-based format:
        - module: "janus.verification"
          symbols: ["run_verification", "CheckResult"]

    And Phase 3 file-based AST format:
        - path: "src/example.py"
          symbol: "my_function"
          type: "function"   # optional

    Also supports mixed format where entries may have either or both.
    """
    if not isinstance(raw, list):
        return []
    result = []
    for item in raw:
        if not isinstance(item, dict):
            continue

        entry = RequiredSymbolEntry()

        # Module-based symbols (legacy format)
        module = item.get("module")
        if isinstance(module, str) and module.strip():
            entry.module = module.strip()
            symbols_raw = item.get("symbols", [])
            if isinstance(symbols_raw, list):
                entry.symbols = [str(s) for s in symbols_raw if isinstance(s, str)]

        # File-based symbols (Phase 3 AST format)
        path = item.get("path")
        if isinstance(path, str) and path.strip():
            entry.path = path.strip()
            symbol = item.get("symbol")
            if isinstance(symbol, str) and symbol.strip():
                entry.symbol = symbol.strip()
            type_val = item.get("type", "")
            if isinstance(type_val, str):
                entry.type = type_val.strip()

        result.append(entry)
    return result


def _parse_forbidden_symbols(raw: Any) -> list[ForbiddenSymbolEntry]:
    """Parse the forbidden_symbols list for Phase 3 AST-based detection.

    Supports two formats:

    Flat file-based format (one entry per dict):
        - symbol: "delete_goal"
          path: "src/janus/"      # optional path restriction
          type: "function"        # optional: "function", "class", or "" for any

    Nested module-based format (one entry per symbol in symbols list):
        - module: "src/example.py"
          symbols:
            - symbol: "forbidden_function"
              type: "function"

    Each symbol in the nested format produces its own ForbiddenSymbolEntry.
    The module value is used as the path restriction for each entry.
    Mixed lists (both formats in the same list) are supported.
    """
    if not isinstance(raw, list):
        return []
    result = []
    for item in raw:
        if not isinstance(item, dict):
            continue

        # Nested module-based format: expand each symbol in the symbols list.
        module = item.get("module")
        symbols_list = item.get("symbols")
        if isinstance(module, str) and module.strip() and isinstance(symbols_list, list):
            path = module.strip()
            for sym_item in symbols_list:
                if not isinstance(sym_item, dict):
                    continue
                sym_raw = sym_item.get("symbol", "")
                if not isinstance(sym_raw, str) or not sym_raw.strip():
                    continue
                symbol = sym_raw.strip()
                type_val = sym_item.get("type", "")
                if not isinstance(type_val, str):
                    type_val = ""
                type_val = type_val.strip()
                result.append(ForbiddenSymbolEntry(
                    symbol=symbol,
                    path=path,
                    type=type_val,
                ))
            continue

        # Flat file-based format: one entry per dict.
        symbol_raw = item.get("symbol", "")
        if not isinstance(symbol_raw, str) or not symbol_raw.strip():
            continue

        symbol = symbol_raw.strip()
        path = item.get("path", "")
        if not isinstance(path, str):
            path = ""
        path = path.strip()

        type_val = item.get("type", "")
        if not isinstance(type_val, str):
            type_val = ""
        type_val = type_val.strip()

        result.append(ForbiddenSymbolEntry(
            symbol=symbol,
            path=path,
            type=type_val,
        ))
    return result


def _parse_command_list(raw: Any) -> list[VerificationCommand]:
    """Parse the verification_commands list."""
    if not isinstance(raw, list):
        return []
    result = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        label = item.get("label")
        command = item.get("command")
        if not isinstance(label, str) or not label.strip():
            continue
        if not isinstance(command, str) or not command.strip():
            continue
        result.append(VerificationCommand(
            label=label.strip(),
            command=command.strip(),
            expected_exit_code=int(item.get("expected_exit_code", 0)),
            timeout=int(item.get("timeout", 300)),
        ))
    return result


def _parse_scope(raw: Any) -> ScopeConstraints:
    """Parse the scope_constraints block."""
    if not isinstance(raw, dict):
        return ScopeConstraints()
    allowed = raw.get("allowed_paths", [])
    excluded = raw.get("excluded_paths", [])
    if not isinstance(allowed, list):
        allowed = []
    if not isinstance(excluded, list):
        excluded = []
    return ScopeConstraints(
        allowed_paths=[str(p) for p in allowed if isinstance(p, str)],
        excluded_paths=[str(p) for p in excluded if isinstance(p, str)],
        max_new_files=int(raw["max_new_files"]) if "max_new_files" in raw and isinstance(raw["max_new_files"], (int, float)) else None,
        max_lines_added=int(raw["max_lines_added"]) if "max_lines_added" in raw and isinstance(raw["max_lines_added"], (int, float)) else None,
    )


def _parse_gate_list(raw: Any) -> list[VerificationGate]:
    """Parse the completion_gates list."""
    if not isinstance(raw, list):
        return []
    result = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        label = item.get("label")
        if not isinstance(label, str) or not label.strip():
            continue
        result.append(VerificationGate(
            label=label.strip(),
            type=str(item.get("type", "mechanical")),
        ))
    return result


# ──────────────────────────────────────────────────────────────────────
# Verification result models
# ──────────────────────────────────────────────────────────────────────

@dataclass
class CheckResult:
    """Result of a single check function.

    Attributes:
        check_name: Name of the check function (e.g. "check_files_create").
        passed: True if the check passed (no failures detected).
        total_items: Total number of items checked.
        failed_items: Number of items that failed.
        details: List of detail dicts for each item checked.
        error: Optional error message if the check itself failed to run.
    """
    check_name: str
    passed: bool = True
    total_items: int = 0
    failed_items: int = 0
    details: list[dict[str, Any]] = field(default_factory=list)
    error: str = ""

    @property
    def has_error(self) -> bool:
        """True if the check function itself encountered an error."""
        return bool(self.error)

    def add_detail(self, item: str, passed: bool, message: str = "") -> None:
        """Add a detail entry for a single item checked."""
        self.total_items += 1
        if not passed:
            self.failed_items += 1
            self.passed = False
        self.details.append({
            "item": item,
            "passed": passed,
            "message": message,
        })

    def set_error(self, message: str) -> None:
        """Mark the check as having encountered an error."""
        self.passed = False
        self.error = message


@dataclass
class VerificationReport:
    """Aggregated verification report from running all checks.

    Produced by run_verification(). Contains per-check results and an
    overall PASS/FAIL determination.
    """
    task_id: str
    overall: str = "PASS"  # "PASS" or "FAIL"
    checks: dict[str, CheckResult] = field(default_factory=dict)
    summary: str = ""
    failures: list[dict[str, Any]] = field(default_factory=list)
    generated_at: str = ""

    @property
    def is_pass(self) -> bool:
        return self.overall == "PASS"

    @property
    def is_fail(self) -> bool:
        return self.overall == "FAIL"

    def to_dict(self) -> dict[str, Any]:
        """Convert to a JSON-serializable dict."""
        return {
            "task_id": self.task_id,
            "overall": self.overall,
            "checks": {
                name: {
                    "check_name": cr.check_name,
                    "passed": cr.passed,
                    "total_items": cr.total_items,
                    "failed_items": cr.failed_items,
                    "details": cr.details,
                    "error": cr.error,
                }
                for name, cr in self.checks.items()
            },
            "summary": self.summary,
            "failures": self.failures,
            "generated_at": self.generated_at,
        }

    def exit_code(self) -> int:
        """Return the exit code for this report: 0 for PASS, 1 for FAIL."""
        return 0 if self.is_pass else 1


# ──────────────────────────────────────────────────────────────────────
# Check functions (Phase 1: files_create, files_immutable, commands)
# Phase 2: files_modify, unexpected_modified, untracked
# ──────────────────────────────────────────────────────────────────────

def _git_tracked_modified_files(root: Path) -> set[str]:
    """Return relative paths of tracked files with modifications vs HEAD.

    Uses 'git diff HEAD --name-only' which lists files that differ from
    the committed state (HEAD) — including both staged and unstaged changes.
    Returns a set of relative path strings.
    """
    try:
        result = subprocess.run(
            ["git", "diff", "HEAD", "--name-only"],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            return set()
        paths = set()
        for line in result.stdout.strip().splitlines():
            line = line.strip()
            if line:
                paths.add(line)
        return paths
    except (subprocess.TimeoutExpired, OSError):
        return set()


def _git_untracked_files(root: Path) -> set[str]:
    """Return relative paths of untracked files in working tree.

    Uses 'git ls-files --others --exclude-standard' which lists untracked
    files excluding ignored ones. Returns a set of relative path strings.
    """
    try:
        result = subprocess.run(
            ["git", "ls-files", "--others", "--exclude-standard"],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            return set()
        paths = set()
        for line in result.stdout.strip().splitlines():
            line = line.strip()
            if line:
                paths.add(line)
        return paths
    except (subprocess.TimeoutExpired, OSError):
        return set()


def _git_is_tracked(root: Path, rel_path: str) -> bool:
    """Check if a relative path is tracked by git."""
    try:
        result = subprocess.run(
            ["git", "ls-files", "--error-unmatch", rel_path],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


def _git_has_diff(root: Path, rel_path: str) -> bool:
    """Check if a tracked file differs from HEAD (staged or unstaged).

    Uses 'git diff HEAD -- <path>' which compares the working tree against
    the committed state (HEAD), detecting both staged and unstaged changes.
    """
    try:
        result = subprocess.run(
            ["git", "diff", "HEAD", "--", rel_path],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=10,
        )
        return bool(result.stdout.strip())
    except (subprocess.TimeoutExpired, OSError):
        return False


def check_files_modify(contract: ImplementationContract) -> CheckResult:
    """Check that every file listed in files.modify was actually modified.

    A file is 'modified' if:
    - It exists on disk
    - It is tracked by git
    - It has a non-empty git diff (staged or unstaged changes vs HEAD)

    PASS: Every file.modify entry is modified.
    FAIL: One or more files.modify entries are missing, untracked, or unmodified.

    Note: A missing file is a FAIL (not just 'not modified').
    """
    result = CheckResult(check_name="check_files_modify")
    for entry in contract.files_modify:
        full_path = contract.root / entry.path
        rel_path = entry.path

        if not full_path.exists():
            result.add_detail(
                item=rel_path,
                passed=False,
                message=f"MISSING: {full_path}",
            )
            continue

        if not _git_is_tracked(contract.root, rel_path):
            result.add_detail(
                item=rel_path,
                passed=False,
                message=f"NOT TRACKED: {rel_path}",
            )
            continue

        has_diff = _git_has_diff(contract.root, rel_path)
        result.add_detail(
            item=rel_path,
            passed=has_diff,
            message="modified" if has_diff else "NOT MODIFIED (no diff)",
        )

    return result


def check_files_unexpected_modified(contract: ImplementationContract) -> CheckResult:
    """Detect tracked files modified in the working tree that are NOT declared
    as allowed to change.

    Allowed changed files:
    - files.create (new files — they will show as untracked initially, but
      if somehow tracked and modified, they're allowed)
    - files.modify (explicitly declared modifications)

    Everything else that appears as a tracked modified file is unexpected.

    PASS: No tracked files outside files.create + files.modify are modified.
    FAIL: One or more unexpected tracked files are modified.

    This check does NOT report files.create entries as unexpected even if
    they somehow appear in tracked modifications — they are allowed by design.
    """
    result = CheckResult(check_name="check_files_unexpected_modified")

    # Build the set of allowed paths (both create and modify)
    allowed_paths: set[str] = set()
    for entry in contract.files_create:
        allowed_paths.add(entry.path)
    for entry in contract.files_modify:
        allowed_paths.add(entry.path)

    # Get actually modified tracked files
    modified_tracked = _git_tracked_modified_files(contract.root)

    # Find unexpected modifications
    unexpected = modified_tracked - allowed_paths

    for rel_path in sorted(unexpected):
        result.add_detail(
            item=rel_path,
            passed=False,
            message=f"UNEXPECTED MODIFICATION: {rel_path}",
        )

    return result


def check_files_untracked(contract: ImplementationContract) -> CheckResult:
    """Detect untracked files that are NOT declared under files.create.

    Expected CREATE files may legitimately be untracked before commit.
    They are allowed and do NOT count as unexpected.

    Any other untracked file is unexpected and causes FAIL.

    PASS: All untracked files are in files.create.
    FAIL: One or more untracked files are not in files.create.

    Note: If a file is in files.create but MISSING from disk, that's
    already caught by check_files_create — this check only cares about
    the untracked-file policy.
    """
    result = CheckResult(check_name="check_files_untracked")

    # Build the set of expected (allowed) untracked paths = files.create
    allowed_untracked: set[str] = set()
    for entry in contract.files_create:
        allowed_untracked.add(entry.path)

    # Get actual untracked files
    actual_untracked = _git_untracked_files(contract.root)

    # Find unexpected untracked files
    unexpected = actual_untracked - allowed_untracked

    for rel_path in sorted(unexpected):
        result.add_detail(
            item=rel_path,
            passed=False,
            message=f"UNEXPECTED UNTRACKED: {rel_path}",
        )

    return result


# ══════════════════════════════════════════════════════════════════════
# Phase 3: Symbol Verification and Git Diff Check
# ══════════════════════════════════════════════════════════════════════

def _get_python_files_in_repo(root: Path) -> list[Path]:
    """Get all Python files in the repository, excluding .git and __pycache__.

    Traverses from root using git ls-files for tracked Python files plus
    untracked Python files. Excludes .git, .venv, __pycache__ directories.
    """
    python_files: set[Path] = set()

    # Use git ls-files to get tracked Python files
    try:
        result = subprocess.run(
            ["git", "ls-files", "*.py"],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            for line in result.stdout.strip().splitlines():
                if line.strip():
                    fp = root / line.strip()
                    if fp.exists():
                        python_files.add(fp)
    except (subprocess.TimeoutExpired, OSError):
        pass

    # Also add untracked Python files via git ls-files --others
    try:
        result = subprocess.run(
            ["git", "ls-files", "--others", "--exclude-standard", "*.py"],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            for line in result.stdout.strip().splitlines():
                if line.strip():
                    fp = root / line.strip()
                    if fp.exists():
                        python_files.add(fp)
    except (subprocess.TimeoutExpired, OSError):
        pass

    return sorted(python_files)


def _find_symbol_in_ast(file_path: Path, symbol_name: str) -> dict[str, Any]:
    """Find a symbol in a Python file using AST parsing.

    Returns a dict with:
        - found: bool
        - symbol_type: str ("function", "class", or "other")
        - message: str (explanation)

    Does NOT match symbols in comments, docstrings, or string literals.
    Only matches actual AST declarations: FunctionDef, AsyncFunctionDef,
    ClassDef.
    """
    try:
        source = file_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        return {
            "found": False,
            "symbol_type": "",
            "message": f"Cannot read file: {e}",
        }

    try:
        tree = ast.parse(source, filename=str(file_path))
    except SyntaxError as e:
        return {
            "found": False,
            "symbol_type": "",
            "message": f"Syntax error in {file_path}: {e}",
        }

    for node in ast.walk(tree):
        # Check FunctionDef
        if isinstance(node, ast.FunctionDef):
            if node.name == symbol_name:
                return {
                    "found": True,
                    "symbol_type": "function",
                    "message": f"Found function '{symbol_name}' at line {node.lineno}",
                }
        # Check AsyncFunctionDef
        elif isinstance(node, ast.AsyncFunctionDef):
            if node.name == symbol_name:
                return {
                    "found": True,
                    "symbol_type": "function",
                    "message": f"Found async function '{symbol_name}' at line {node.lineno}",
                }
        # Check ClassDef
        elif isinstance(node, ast.ClassDef):
            if node.name == symbol_name:
                return {
                    "found": True,
                    "symbol_type": "class",
                    "message": f"Found class '{symbol_name}' at line {node.lineno}",
                }

    return {
        "found": False,
        "symbol_type": "",
        "message": f"Symbol '{symbol_name}' not found in {file_path}",
    }


def _check_required_symbol_ast(contract: ImplementationContract,
                                entry: RequiredSymbolEntry) -> CheckResult:
    """Check a single required symbol entry using AST parsing.

    Handles both file-based (path + symbol) and module-based formats.
    For file-based: uses AST to find the symbol in the specified file.
    For module-based: attempts to import and check (may be deferred).
    """
    result = CheckResult(check_name="check_symbols_required")

    # File-based check (Phase 3 primary path)
    if entry.path and entry.symbol:
        full_path = contract.root / entry.path
        if not full_path.exists():
            result.add_detail(
                item=f"{entry.path}:{entry.symbol}",
                passed=False,
                message=f"MISSING FILE: {full_path}",
            )
            return result

        if not full_path.suffix == ".py":
            result.add_detail(
                item=f"{entry.path}:{entry.symbol}",
                passed=False,
                message=f"NOT A PYTHON FILE: {full_path}",
            )
            return result

        ast_result = _find_symbol_in_ast(full_path, entry.symbol)
        if not ast_result["found"]:
            result.add_detail(
                item=f"{entry.path}:{entry.symbol}",
                passed=False,
                message=ast_result["message"],
            )
            return result

        # Check symbol type if specified
        if entry.type and ast_result["symbol_type"] != entry.type:
            result.add_detail(
                item=f"{entry.path}:{entry.symbol}",
                passed=False,
                message=(
                    f"WRONG TYPE: expected {entry.type}, "
                    f"found {ast_result['symbol_type']}"
                ),
            )
            return result

        result.add_detail(
            item=f"{entry.path}:{entry.symbol}",
            passed=True,
            message=ast_result["message"],
        )
        return result

    # Module-based check (legacy format — attempt import)
    # A module-based entry MUST have a non-empty symbols list.
    # If module is set but symbols is missing/empty, fail deterministically.
    if entry.module:
        if not entry.symbols:
            result.add_detail(
                item=f"{entry.module}:(no symbols)",
                passed=False,
                message=(
                    f"MALFORMED DEFINITION: module '{entry.module}' "
                    f"has no symbols defined. "
                    f"module-based symbol definitions require a non-empty 'symbols' list."
                ),
            )
            return result

        for sym in entry.symbols:
            try:
                import importlib
                mod = importlib.import_module(entry.module)
                if not hasattr(mod, sym):
                    result.add_detail(
                        item=f"{entry.module}.{sym}",
                        passed=False,
                        message=f"SYMBOL NOT FOUND: {entry.module}.{sym}",
                    )
                else:
                    result.add_detail(
                        item=f"{entry.module}.{sym}",
                        passed=True,
                        message=f"Found symbol {sym} in {entry.module}",
                    )
            except ImportError as e:
                result.add_detail(
                    item=f"{entry.module}.{sym}",
                    passed=False,
                    message=f"IMPORT ERROR: {e}",
                )
            except Exception as e:
                result.add_detail(
                    item=f"{entry.module}.{sym}",
                    passed=False,
                    message=f"ERROR: {e}",
                )

    return result


def check_symbols_required(contract: ImplementationContract) -> CheckResult:
    """Check that all required symbols exist using AST-based detection.

    For file-based symbols: parses the Python file with AST and verifies
    the symbol exists as a FunctionDef, AsyncFunctionDef, or ClassDef.
    Comments, docstrings, and string literals do NOT count.

    For module-based symbols: attempts to import the module and verify
    the attribute exists (legacy MVP format).

    PASS: Every required symbol is found with correct type.
    FAIL: One or more required symbols are missing or wrong type.
    """
    result = CheckResult(check_name="check_symbols_required")

    for entry in contract.required_symbols:
        sub_result = _check_required_symbol_ast(contract, entry)
        # Merge sub_result into main result
        result.total_items += sub_result.total_items
        result.failed_items += sub_result.failed_items
        if not sub_result.passed:
            result.passed = False
        result.details.extend(sub_result.details)

    return result


def _find_forbidden_symbol_in_repo(contract: ImplementationContract,
                                     forbidden: ForbiddenSymbolEntry) -> CheckResult:
    """Search repository Python files for a forbidden symbol using AST.

    If path is specified, only search files under that path.
    Otherwise, search all Python files in the repository.
    """
    result = CheckResult(check_name="check_symbols_forbidden")

    python_files = _get_python_files_in_repo(contract.root)

    for py_file in python_files:
        # Apply path filter if specified
        if forbidden.path:
            try:
                rel = py_file.resolve().relative_to(contract.root.resolve())
                if not str(rel).startswith(forbidden.path):
                    continue
            except ValueError:
                continue

        ast_result = _find_symbol_in_ast(py_file, forbidden.symbol)

        if ast_result["found"]:
            # Check type if specified
            if forbidden.type and ast_result["symbol_type"] != forbidden.type:
                continue

            result.add_detail(
                item=f"{py_file}:{forbidden.symbol}",
                passed=False,
                message=(
                    f"FORBIDDEN SYMBOL FOUND: {ast_result['message']}"
                ),
            )

    return result


def check_symbols_forbidden(contract: ImplementationContract) -> CheckResult:
    """Check that no forbidden symbols exist in the repository using AST.

    Searches all Python files in the repository (tracked + untracked).
    Uses AST parsing to find actual declarations only — comments, strings,
    and docstrings do NOT trigger false positives.

    If a path is specified in the contract, only files under that path
    are searched.

    PASS: No forbidden symbols found.
    FAIL: One or more forbidden symbols found.
    """
    result = CheckResult(check_name="check_symbols_forbidden")

    for forbidden in contract.forbidden_symbols:
        if not forbidden.symbol:
            continue
        sub_result = _find_forbidden_symbol_in_repo(contract, forbidden)
        result.total_items += sub_result.total_items
        result.failed_items += sub_result.failed_items
        if not sub_result.passed:
            result.passed = False
        result.details.extend(sub_result.details)

    return result


def check_git_diff_check(contract: ImplementationContract) -> CheckResult:
    """Check that the Git diff has no whitespace errors.

    Uses 'git diff HEAD --check' which compares the complete current
    repository state (working tree + index) against HEAD. This catches:
    - Unstaged whitespace errors
    - Staged whitespace errors
    - Mixed staged + unstaged whitespace errors

    This is the HEAD-based equivalent of Phase 2.1's fix: using
    'git diff HEAD' instead of 'git diff' ensures staged-only changes
    are not invisible.

    PASS: No whitespace errors.
    FAIL: Whitespace errors detected or Git command fails.
    """
    result = CheckResult(check_name="check_git_diff_check")

    try:
        diff_result = subprocess.run(
            ["git", "diff", "HEAD", "--check"],
            cwd=str(contract.root),
            capture_output=True,
            text=True,
            timeout=30,
        )

        # Check if we're outside a git repository — git prints a warning
        # to stdout and returns 0, but the command didn't execute successfully.
        combined_output = (diff_result.stdout + diff_result.stderr).strip()
        if "Not a git repository" in combined_output or "not a git repository" in combined_output.lower():
            result.add_detail(
                item="git diff HEAD --check",
                passed=False,
                message=f"NOT A GIT REPOSITORY: {combined_output[:500]}",
            )
            return result

        if diff_result.returncode != 0:
            # Whitespace errors found
            error_output = combined_output if combined_output else "unknown whitespace error"
            result.add_detail(
                item="git diff HEAD --check",
                passed=False,
                message=f"WHITESPACE ERRORS: {error_output[:500]}",
            )
        else:
            result.add_detail(
                item="git diff HEAD --check",
                passed=True,
                message="no whitespace errors",
            )

    except (subprocess.TimeoutExpired, OSError) as e:
        result.add_detail(
            item="git diff HEAD --check",
            passed=False,
            message=f"GIT COMMAND FAILED: {e}",
        )

    return result


# ══════════════════════════════════════════════════════════════════════
# Check functions (Phase 1: files_create, files_immutable, commands)
# Phase 2: files_modify, unexpected_modified, untracked
# Phase 3: symbols_required, symbols_forbidden, git_diff_check
# ──────────────────────────────────────────────────────────────────────

def check_files_create(contract: ImplementationContract) -> CheckResult:
    """Check that all files listed in files.create exist on disk.

    PASS: Every path in files.create exists.
    FAIL: One or more paths in files.create are missing.
    """
    result = CheckResult(check_name="check_files_create")
    for entry in contract.files_create:
        full_path = contract.root / entry.path
        exists = full_path.exists()
        result.add_detail(
            item=entry.path,
            passed=exists,
            message="exists" if exists else f"MISSING: {full_path}",
        )
    return result


def check_files_immutable(contract: ImplementationContract) -> CheckResult:
    """Check that all files listed in files.immutable have zero git diff.

    PASS: Every immutable file has no diff.
    FAIL: One or more immutable files have a non-empty diff.
    """
    result = CheckResult(check_name="check_files_immutable")
    for entry in contract.files_immutable:
        full_path = contract.root / entry.path
        if not full_path.exists():
            # File doesn't exist — can't check diff, but flag as error
            result.add_detail(
                item=entry.path,
                passed=False,
                message=f"FILE NOT FOUND: {full_path}",
            )
            continue

        try:
            diff_result = subprocess.run(
                ["git", "diff", "HEAD", "--", str(full_path)],
                cwd=str(contract.root),
                capture_output=True,
                text=True,
                timeout=30,
            )
            has_diff = bool(diff_result.stdout.strip())
            result.add_detail(
                item=entry.path,
                passed=not has_diff,
                message="empty" if not has_diff else f"HAS DIFF: {diff_result.stdout[:200]}",
            )
        except (subprocess.TimeoutExpired, OSError) as e:
            result.add_detail(
                item=entry.path,
                passed=False,
                message=f"ERROR: {e}",
            )
    return result


def check_commands(contract: ImplementationContract) -> CheckResult:
    """Run each verification command and check its exit code.

    PASS: Every command exits with expected_exit_code.
    FAIL: One or more commands exit with wrong code or timeout.
    """
    result = CheckResult(check_name="check_commands")
    for cmd in contract.verification_commands:
        try:
            proc = subprocess.run(
                cmd.command,
                shell=True,
                cwd=str(contract.root),
                capture_output=True,
                text=True,
                timeout=cmd.timeout,
            )
            exit_ok = proc.returncode == cmd.expected_exit_code
            result.add_detail(
                item=cmd.label,
                passed=exit_ok,
                message=(
                    f"exit {proc.returncode} (expected {cmd.expected_exit_code})"
                    if exit_ok
                    else f"exit {proc.returncode} (expected {cmd.expected_exit_code})"
                ),
            )
        except subprocess.TimeoutExpired:
            result.add_detail(
                item=cmd.label,
                passed=False,
                message=f"TIMEOUT after {cmd.timeout}s",
            )
        except OSError as e:
            result.add_detail(
                item=cmd.label,
                passed=False,
                message=f"ERROR: {e}",
            )
    return result


# ──────────────────────────────────────────────────────────────────────
# Execution framework
# ──────────────────────────────────────────────────────────────────────

def run_verification(contract_path: str | Path) -> VerificationReport:
    """Run all implemented checks against a contract and produce a report.

    This is the main entry point for the verification pipeline. It loads the
    contract, runs all implemented check functions, aggregates results, and
    returns a VerificationReport with overall PASS/FAIL.

    Implemented checks (Phase 1 + Phase 2 + Phase 3):
    - check_files_create
    - check_files_immutable
    - check_commands
    - check_files_modify
    - check_files_unexpected_modified
    - check_files_untracked
    - check_symbols_required
    - check_symbols_forbidden
    - check_git_diff_check
    """
    contract = ImplementationContract.load(contract_path)
    report = VerificationReport(task_id=contract.task_id)

    # Run all implemented checks
    checks = [
        ("files_create", check_files_create),
        ("files_immutable", check_files_immutable),
        ("commands", check_commands),
        ("files_modify", check_files_modify),
        ("unexpected_modified", check_files_unexpected_modified),
        ("untracked", check_files_untracked),
        ("symbols_required", check_symbols_required),
        ("symbols_forbidden", check_symbols_forbidden),
        ("git_diff_check", check_git_diff_check),
    ]

    for check_name, check_fn in checks:
        try:
            cr = check_fn(contract)
            report.checks[check_name] = cr
        except Exception as e:
            report.checks[check_name] = CheckResult(
                check_name=check_name,
                passed=False,
                error=str(e),
            )

    # Aggregate: collect failures
    failed_checks = []
    for name, cr in report.checks.items():
        if cr.has_error:
            failed_checks.append({
                "check": name,
                "error": cr.error,
            })
        elif not cr.passed:
            for detail in cr.details:
                if not detail["passed"]:
                    failed_checks.append({
                        "check": name,
                        "item": detail["item"],
                        "message": detail["message"],
                    })

    report.failures = failed_checks
    report.overall = "FAIL" if failed_checks else "PASS"

    # Build summary
    total_items = sum(cr.total_items for cr in report.checks.values())
    total_failed = sum(cr.failed_items for cr in report.checks.values())
    total_errors = sum(1 for cr in report.checks.values() if cr.has_error)
    check_count = len(report.checks)

    if report.is_pass:
        report.summary = (
            f"PASS: {check_count} checks, {total_items} items, "
            f"0 failures"
        )
    else:
        report.summary = (
            f"FAIL: {check_count} checks, {total_items} items, "
            f"{total_failed} failures, {total_errors} errors"
        )

    from datetime import datetime, timezone
    report.generated_at = datetime.now(timezone.utc).isoformat()

    return report


def run_verification_cli(contract_path: str | Path) -> int:
    """CLI entry point: run verification and print JSON report.

    Returns the exit code (0 for PASS, 1 for FAIL).
    """
    report = run_verification(contract_path)
    import json
    print(json.dumps(report.to_dict(), indent=2))
    return report.exit_code()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python -m janus.verification <contract.yaml>", file=sys.stderr)
        sys.exit(1)
    sys.exit(run_verification_cli(sys.argv[1]))
