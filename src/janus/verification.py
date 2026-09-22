"""Verification Pipeline for Janus — Phase 1 implementation.

Provides contract loading, verification result models, and verification checks
plus an execution framework that aggregates results into overall PASS/FAIL.

Implemented checks:
- files_create
- files_immutable
- commands
- files_modify
- unexpected_modified
- untracked
- symbols_required
- symbols_forbidden
- os_replace
- git_diff_check
- data_write_path
- data_file_write_gates

Also provides default-on deterministic pre-completion checks:
- working_tree_clean
- git_diff_check
- tests_pass_after_rebase
"""

from __future__ import annotations

import ast
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

# ──────────────────────────────────────────────────────────────────────
# Modules excluded from the data-write-path grep gates.
#
# These are the policy-layer homes (``data_integrity`` owns the legacy
# ``protected_write``/``protected_append`` definitions and their internal
# ``atomic_write``/``backup_previous`` calls) and the primitive
# (``atomic_io``).  The gates must not flag these modules themselves — they
# exist to catch stray *caller* sites that bypass ``atomic_io``.
# (ADR-005 Amendment 01; ``data_protection.py`` was deleted once all writers
# migrated to ``atomic_io`` / ``data_integrity``.)
_WRITE_PATH_EXCEPTIONS: frozenset[str] = frozenset(
    {"atomic_io.py", "data_integrity.py"}
)


def _is_write_path_module(py_file: Path) -> bool:
    """True if *py_file* is a real caller module (not a primitive/shim)."""
    return py_file.name not in _WRITE_PATH_EXCEPTIONS


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
    """A required symbol entry.

    Supports both module-based import checking and file-based AST checking.

    Module-based format:
        module: "janus.verification"
        symbols: ["run_verification", "CheckResult"]

    File-based format:
        path: "src/example.py"
        symbol: "my_function"
        type: "function"
    """

    module: str = ""
    symbols: list[str] = field(default_factory=list)
    path: str = ""
    symbol: str = ""
    type: str = ""  # "function", "class", or ""


@dataclass(frozen=True)
class ForbiddenSymbolEntry:
    """A forbidden symbol entry for AST-based detection."""

    symbol: str = ""
    path: str = ""
    type: str = ""  # "function", "class", or "" for any


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
class DefaultCheckConfig:
    """Configuration for default-on deterministic pre-completion checks."""

    enabled: bool = True
    run_working_tree_clean: bool = True
    run_git_diff_check: bool = True
    run_tests_after_rebase: bool = True
    test_command: str = "uv run pytest tests/"
    test_timeout: int = 600
    root: Path = field(default_factory=lambda: Path.cwd())

    @classmethod
    def from_dict(
        cls,
        data: dict[str, Any] | None,
    ) -> "DefaultCheckConfig":
        """Build a config from a dict."""

        if not data or not isinstance(data, dict):
            return cls()

        return cls(
            enabled=data.get("enabled", True),
            run_working_tree_clean=data.get(
                "run_working_tree_clean",
                True,
            ),
            run_git_diff_check=data.get(
                "run_git_diff_check",
                True,
            ),
            run_tests_after_rebase=data.get(
                "run_tests_after_rebase",
                True,
            ),
            test_command=data.get(
                "test_command",
                "uv run pytest tests/",
            ),
            test_timeout=int(data.get("test_timeout", 600)),
            root=Path(data["root"])
            if "root" in data
            else Path.cwd(),
        )


@dataclass
class ImplementationContract:
    """A loaded and validated implementation contract.

    All paths are relative to the workspace root where the contract file lives.
    """

    version: int
    task_id: str
    created: str = ""
    created_by: str = ""
    description: str = ""

    files_create: list[ContractFileEntry] = field(default_factory=list)
    files_modify: list[ContractFileEntry] = field(default_factory=list)
    files_immutable: list[ContractFileEntry] = field(default_factory=list)
    files_forbidden: list[ForbiddenFileEntry] = field(default_factory=list)

    required_symbols: list[RequiredSymbolEntry] = field(default_factory=list)
    forbidden_symbols: list[ForbiddenSymbolEntry] = field(default_factory=list)

    forbidden_os_replace: list[str] = field(default_factory=list)

    verification_commands: list[VerificationCommand] = field(
        default_factory=list
    )

    scope_constraints: ScopeConstraints = field(
        default_factory=ScopeConstraints
    )

    completion_gates: list[VerificationGate] = field(
        default_factory=list
    )

    root: Path = field(default_factory=lambda: Path.cwd())

    @classmethod
    def load(cls, path: str | Path) -> "ImplementationContract":
        """Load a YAML contract file and validate required fields."""

        path = Path(path)

        if not path.exists():
            raise FileNotFoundError(
                f"Contract file not found: {path}"
            )

        if not path.is_file():
            raise ValueError(
                f"Contract path is not a file: {path}"
            )

        with open(path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f)

        if not isinstance(raw, dict):
            raise ValueError("Contract must be a YAML mapping")

        version = raw.get("version")
        if not isinstance(version, int):
            raise ValueError(
                f"Contract 'version' must be an integer, got: {version!r}"
            )

        task_id = raw.get("task_id")
        if not isinstance(task_id, str) or not task_id.strip():
            raise ValueError(
                "Contract 'task_id' must be a non-empty string"
            )

        root = path.parent.resolve()

        return cls(
            version=version,
            task_id=task_id.strip(),
            created=str(raw.get("created", "")),
            created_by=str(raw.get("created_by", "")),
            description=str(raw.get("description", "")),
            files_create=_parse_file_list(
                raw.get("files", {}).get("create", [])
            ),
            files_modify=_parse_file_list(
                raw.get("files", {}).get("modify", [])
            ),
            files_immutable=_parse_file_list(
                raw.get("files", {}).get("immutable", [])
            ),
            files_forbidden=_parse_forbidden_list(
                raw.get("files", {}).get("forbidden", [])
            ),
            required_symbols=_parse_symbol_list(
                raw.get("required_symbols", [])
            ),
            forbidden_symbols=_parse_forbidden_symbols(
                raw.get("forbidden_symbols", [])
            ),
            forbidden_os_replace=_parse_str_list(
                raw.get("forbidden_os_replace", [])
            ),
            verification_commands=_parse_command_list(
                raw.get("verification_commands", [])
            ),
            scope_constraints=_parse_scope(
                raw.get("scope_constraints", {})
            ),
            completion_gates=_parse_gate_list(
                raw.get("completion_gates", [])
            ),
            root=root,
        )

    def get_create_paths(self) -> list[Path]:
        """Return fully-resolved paths for all files in create list."""

        return [
            self.root / entry.path
            for entry in self.files_create
        ]

    def get_modify_paths(self) -> list[Path]:
        """Return fully-resolved paths for all files in modify list."""

        return [
            self.root / entry.path
            for entry in self.files_modify
        ]

    def get_immutable_paths(self) -> list[Path]:
        """Return fully-resolved paths for all files in immutable list."""

        return [
            self.root / entry.path
            for entry in self.files_immutable
        ]

    def get_relative_diff_name(
        self,
        absolute_path: Path,
    ) -> str | None:
        """Convert an absolute path to a relative path."""

        try:
            return str(
                absolute_path.resolve().relative_to(
                    self.root.resolve()
                )
            )
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

        result.append(
            ContractFileEntry(
                path=path.strip(),
                description=str(
                    item.get("description", "")
                ),
            )
        )

    return result


def _parse_forbidden_list(
    raw: Any,
) -> list[ForbiddenFileEntry]:
    """Parse the forbidden files list."""

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

        result.append(
            ForbiddenFileEntry(
                path=path.strip(),
                description=str(
                    item.get("description", "")
                ),
                reason=str(
                    item.get("reason", "")
                ),
                type=ftype,
            )
        )

    return result


def _parse_symbol_list(
    raw: Any,
) -> list[RequiredSymbolEntry]:
    """Parse the required_symbols list."""

    if not isinstance(raw, list):
        return []

    result = []

    for item in raw:
        if not isinstance(item, dict):
            continue

        entry = RequiredSymbolEntry()

        module = item.get("module")

        if isinstance(module, str) and module.strip():
            entry.module = module.strip()

            symbols_raw = item.get("symbols", [])

            if isinstance(symbols_raw, list):
                entry.symbols = [
                    str(s)
                    for s in symbols_raw
                    if isinstance(s, str)
                ]

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


def _parse_forbidden_symbols(
    raw: Any,
) -> list[ForbiddenSymbolEntry]:
    """Parse the forbidden_symbols list."""

    if not isinstance(raw, list):
        return []

    result = []

    for item in raw:
        if not isinstance(item, dict):
            continue

        module = item.get("module")
        symbols_list = item.get("symbols")

        if (
            isinstance(module, str)
            and module.strip()
            and isinstance(symbols_list, list)
        ):
            path = module.strip()

            for sym_item in symbols_list:
                if not isinstance(sym_item, dict):
                    continue

                sym_raw = sym_item.get("symbol", "")

                if (
                    not isinstance(sym_raw, str)
                    or not sym_raw.strip()
                ):
                    continue

                symbol = sym_raw.strip()

                type_val = sym_item.get("type", "")

                if not isinstance(type_val, str):
                    type_val = ""

                result.append(
                    ForbiddenSymbolEntry(
                        symbol=symbol,
                        path=path,
                        type=type_val.strip(),
                    )
                )

            continue

        symbol_raw = item.get("symbol", "")

        if (
            not isinstance(symbol_raw, str)
            or not symbol_raw.strip()
        ):
            continue

        symbol = symbol_raw.strip()

        path = item.get("path", "")

        if not isinstance(path, str):
            path = ""

        type_val = item.get("type", "")

        if not isinstance(type_val, str):
            type_val = ""

        result.append(
            ForbiddenSymbolEntry(
                symbol=symbol,
                path=path.strip(),
                type=type_val.strip(),
            )
        )

    return result


def _parse_str_list(raw: Any) -> list[str]:
    """Parse a YAML list of strings."""

    if not isinstance(raw, list):
        return []

    return [
        str(item)
        for item in raw
        if isinstance(item, str)
    ]


def _parse_command_list(
    raw: Any,
) -> list[VerificationCommand]:
    """Parse verification_commands."""

    if not isinstance(raw, list):
        return []

    result = []

    for item in raw:
        if not isinstance(item, dict):
            continue

        label = item.get("label")
        command = item.get("command")

        if (
            not isinstance(label, str)
            or not label.strip()
        ):
            continue

        if (
            not isinstance(command, str)
            or not command.strip()
        ):
            continue

        result.append(
            VerificationCommand(
                label=label.strip(),
                command=command.strip(),
                expected_exit_code=int(
                    item.get("expected_exit_code", 0)
                ),
                timeout=int(
                    item.get("timeout", 300)
                ),
            )
        )

    return result


def _parse_scope(raw: Any) -> ScopeConstraints:
    """Parse scope_constraints."""

    if not isinstance(raw, dict):
        return ScopeConstraints()

    allowed = raw.get("allowed_paths", [])
    excluded = raw.get("excluded_paths", [])

    if not isinstance(allowed, list):
        allowed = []

    if not isinstance(excluded, list):
        excluded = []

    return ScopeConstraints(
        allowed_paths=[
            str(p)
            for p in allowed
            if isinstance(p, str)
        ],
        excluded_paths=[
            str(p)
            for p in excluded
            if isinstance(p, str)
        ],
        max_new_files=(
            int(raw["max_new_files"])
            if (
                "max_new_files" in raw
                and isinstance(
                    raw["max_new_files"],
                    (int, float),
                )
            )
            else None
        ),
        max_lines_added=(
            int(raw["max_lines_added"])
            if (
                "max_lines_added" in raw
                and isinstance(
                    raw["max_lines_added"],
                    (int, float),
                )
            )
            else None
        ),
    )


def _parse_gate_list(
    raw: Any,
) -> list[VerificationGate]:
    """Parse completion_gates."""

    if not isinstance(raw, list):
        return []

    result = []

    for item in raw:
        if not isinstance(item, dict):
            continue

        label = item.get("label")

        if (
            not isinstance(label, str)
            or not label.strip()
        ):
            continue

        result.append(
            VerificationGate(
                label=label.strip(),
                type=str(
                    item.get(
                        "type",
                        "mechanical",
                    )
                ),
            )
        )

    return result


# ──────────────────────────────────────────────────────────────────────
# Verification result models
# ──────────────────────────────────────────────────────────────────────


@dataclass
class CheckResult:
    """Result of a single check function."""

    check_name: str
    passed: bool = True
    total_items: int = 0
    failed_items: int = 0
    details: list[dict[str, Any]] = field(
        default_factory=list
    )
    error: str = ""

    @property
    def has_error(self) -> bool:
        """True if the check function encountered an error."""

        return bool(self.error)

    def add_detail(
        self,
        item: str,
        passed: bool,
        message: str = "",
    ) -> None:
        """Add a detail entry."""

        self.total_items += 1

        if not passed:
            self.failed_items += 1
            self.passed = False

        self.details.append(
            {
                "item": item,
                "passed": passed,
                "message": message,
            }
        )

    def set_error(self, message: str) -> None:
        """Mark the check as having encountered an error."""

        self.passed = False
        self.error = message


@dataclass
class VerificationReport:
    """Aggregated verification report."""

    task_id: str
    overall: str = "PASS"
    checks: dict[str, CheckResult] = field(
        default_factory=dict
    )
    summary: str = ""
    failures: list[dict[str, Any]] = field(
        default_factory=list
    )
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
        """Return 0 for PASS and 1 for FAIL."""

        return 0 if self.is_pass else 1


# ──────────────────────────────────────────────────────────────────────
# Git helpers
# ──────────────────────────────────────────────────────────────────────


def _git_tracked_modified_files(
    root: Path,
) -> set[str]:
    """Return tracked files modified against HEAD."""

    try:
        result = subprocess.run(
            [
                "git",
                "diff",
                "HEAD",
                "--name-only",
            ],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=30,
        )

        if result.returncode != 0:
            return set()

        return {
            line.strip()
            for line in result.stdout.strip().splitlines()
            if line.strip()
        }

    except (subprocess.TimeoutExpired, OSError):
        return set()


def _git_untracked_files(root: Path) -> set[str]:
    """Return untracked files."""

    try:
        result = subprocess.run(
            [
                "git",
                "ls-files",
                "--others",
                "--exclude-standard",
            ],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=30,
        )

        if result.returncode != 0:
            return set()

        return {
            line.strip()
            for line in result.stdout.strip().splitlines()
            if line.strip()
        }

    except (subprocess.TimeoutExpired, OSError):
        return set()


def _git_is_tracked(
    root: Path,
    rel_path: str,
) -> bool:
    """Check if a relative path is tracked."""

    try:
        result = subprocess.run(
            [
                "git",
                "ls-files",
                "--error-unmatch",
                rel_path,
            ],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=10,
        )

        return result.returncode == 0

    except (subprocess.TimeoutExpired, OSError):
        return False


def _git_has_diff(
    root: Path,
    rel_path: str,
) -> bool:
    """Check if a tracked file differs from HEAD."""

    try:
        result = subprocess.run(
            [
                "git",
                "diff",
                "HEAD",
                "--",
                rel_path,
            ],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=10,
        )

        return bool(result.stdout.strip())

    except (subprocess.TimeoutExpired, OSError):
        return False


# ──────────────────────────────────────────────────────────────────────
# File checks
# ──────────────────────────────────────────────────────────────────────


def check_files_create(
    contract: ImplementationContract,
) -> CheckResult:
    """Check that all files listed in files.create exist."""

    result = CheckResult(
        check_name="check_files_create"
    )

    for entry in contract.files_create:
        full_path = contract.root / entry.path
        exists = full_path.exists()

        result.add_detail(
            item=entry.path,
            passed=exists,
            message=(
                "exists"
                if exists
                else f"MISSING: {full_path}"
            ),
        )

    return result


def check_files_immutable(
    contract: ImplementationContract,
) -> CheckResult:
    """Check that immutable files have zero git diff."""

    result = CheckResult(
        check_name="check_files_immutable"
    )

    for entry in contract.files_immutable:
        full_path = contract.root / entry.path

        if not full_path.exists():
            result.add_detail(
                item=entry.path,
                passed=False,
                message=f"FILE NOT FOUND: {full_path}",
            )
            continue

        try:
            diff_result = subprocess.run(
                [
                    "git",
                    "diff",
                    "HEAD",
                    "--",
                    str(full_path),
                ],
                cwd=str(contract.root),
                capture_output=True,
                text=True,
                timeout=30,
            )

            has_diff = bool(
                diff_result.stdout.strip()
            )

            result.add_detail(
                item=entry.path,
                passed=not has_diff,
                message=(
                    "empty"
                    if not has_diff
                    else (
                        f"HAS DIFF: "
                        f"{diff_result.stdout[:200]}"
                    )
                ),
            )

        except (subprocess.TimeoutExpired, OSError) as e:
            result.add_detail(
                item=entry.path,
                passed=False,
                message=f"ERROR: {e}",
            )

    return result


def check_files_modify(
    contract: ImplementationContract,
) -> CheckResult:
    """Check that every files.modify entry was modified."""

    result = CheckResult(
        check_name="check_files_modify"
    )

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

        if not _git_is_tracked(
            contract.root,
            rel_path,
        ):
            result.add_detail(
                item=rel_path,
                passed=False,
                message=f"NOT TRACKED: {rel_path}",
            )
            continue

        has_diff = _git_has_diff(
            contract.root,
            rel_path,
        )

        result.add_detail(
            item=rel_path,
            passed=has_diff,
            message=(
                "modified"
                if has_diff
                else "NOT MODIFIED (no diff)"
            ),
        )

    return result


def check_files_unexpected_modified(
    contract: ImplementationContract,
) -> CheckResult:
    """Detect unexpected tracked modifications."""

    result = CheckResult(
        check_name="check_files_unexpected_modified"
    )

    allowed_paths: set[str] = set()

    for entry in contract.files_create:
        allowed_paths.add(entry.path)

    for entry in contract.files_modify:
        allowed_paths.add(entry.path)

    modified_tracked = _git_tracked_modified_files(
        contract.root
    )

    unexpected = modified_tracked - allowed_paths

    for rel_path in sorted(unexpected):
        result.add_detail(
            item=rel_path,
            passed=False,
            message=(
                f"UNEXPECTED MODIFICATION: "
                f"{rel_path}"
            ),
        )

    return result


def check_files_untracked(
    contract: ImplementationContract,
) -> CheckResult:
    """Detect unexpected untracked files."""

    result = CheckResult(
        check_name="check_files_untracked"
    )

    allowed_untracked: set[str] = set()

    for entry in contract.files_create:
        allowed_untracked.add(entry.path)

    actual_untracked = _git_untracked_files(
        contract.root
    )

    unexpected = (
        actual_untracked - allowed_untracked
    )

    for rel_path in sorted(unexpected):
        result.add_detail(
            item=rel_path,
            passed=False,
            message=(
                f"UNEXPECTED UNTRACKED: "
                f"{rel_path}"
            ),
        )

    return result


# ──────────────────────────────────────────────────────────────────────
# Data write path checks
# ──────────────────────────────────────────────────────────────────────


def check_data_write_path(
    contract: ImplementationContract,
) -> CheckResult:
    """Check that service/integration modules don't use protected_write."""

    result = CheckResult(
        check_name="check_data_write_path"
    )

    root = contract.root

    scan_dirs = [
        root / "src" / "janus" / "services",
        root / "src" / "janus" / "integrations",
    ]

    pattern = re.compile(
        r"\bprotected_write\s*\("
    )

    for scan_dir in scan_dirs:
        if not scan_dir.exists():
            continue

        for py_file in sorted(
            scan_dir.glob("*.py")
        ):
            if not _is_write_path_module(py_file):
                continue

            try:
                content = py_file.read_text(
                    encoding="utf-8"
                )
            except (OSError, UnicodeDecodeError):
                continue

            if pattern.search(content):
                rel = py_file.relative_to(root)

                result.add_detail(
                    item=str(rel),
                    passed=False,
                    message=(
                        f"protected_write call "
                        f"found in {rel}"
                    ),
                )

    return result


def check_data_file_write_gates(
    contract: ImplementationContract,
) -> CheckResult:
    """Check for direct writes to data files."""

    result = CheckResult(
        check_name="check_data_file_write_gates"
    )

    root = contract.root

    scan_dirs = [
        root / "src" / "janus" / "services",
        root / "src" / "janus" / "integrations",
    ]

    write_text_pattern = re.compile(
        r"\b\w+\.write_text\s*\("
    )

    append_open_pattern = re.compile(
        r"\.open\s*\(\s*[\"']a[\"']\s*\)"
    )

    for scan_dir in scan_dirs:
        if not scan_dir.exists():
            continue

        for py_file in sorted(
            scan_dir.glob("*.py")
        ):
            if not _is_write_path_module(py_file):
                continue

            try:
                content = py_file.read_text(
                    encoding="utf-8"
                )
            except (OSError, UnicodeDecodeError):
                continue

            violations: list[str] = []

            for match in write_text_pattern.finditer(
                content
            ):
                line_start = (
                    content.rfind(
                        "\n",
                        0,
                        match.start(),
                    )
                    + 1
                )

                line_end = content.find(
                    "\n",
                    match.end(),
                )

                if line_end == -1:
                    line_end = len(content)

                line = content[
                    line_start:line_end
                ].strip()

                violations.append(
                    f"write_text: {line}"
                )

            for match in append_open_pattern.finditer(
                content
            ):
                line_start = (
                    content.rfind(
                        "\n",
                        0,
                        match.start(),
                    )
                    + 1
                )

                line_end = content.find(
                    "\n",
                    match.end(),
                )

                if line_end == -1:
                    line_end = len(content)

                line = content[
                    line_start:line_end
                ].strip()

                violations.append(
                    f"open('a'): {line}"
                )

            if violations:
                rel = py_file.relative_to(root)

                result.add_detail(
                    item=str(rel),
                    passed=False,
                    message=(
                        f"Direct data/ write in "
                        f"{rel}: "
                        + "; ".join(violations)
                    ),
                )

    return result


# ──────────────────────────────────────────────────────────────────────
# Command checks
# ──────────────────────────────────────────────────────────────────────


def check_commands(
    contract: ImplementationContract,
) -> CheckResult:
    """Run verification commands."""

    result = CheckResult(
        check_name="check_commands"
    )

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

            exit_ok = (
                proc.returncode
                == cmd.expected_exit_code
            )

            result.add_detail(
                item=cmd.label,
                passed=exit_ok,
                message=(
                    f"exit {proc.returncode} "
                    f"(expected "
                    f"{cmd.expected_exit_code})"
                ),
            )

        except subprocess.TimeoutExpired:
            result.add_detail(
                item=cmd.label,
                passed=False,
                message=(
                    f"TIMEOUT after "
                    f"{cmd.timeout}s"
                ),
            )

        except OSError as e:
            result.add_detail(
                item=cmd.label,
                passed=False,
                message=f"ERROR: {e}",
            )

    return result


# ──────────────────────────────────────────────────────────────────────
# Symbol verification
# ──────────────────────────────────────────────────────────────────────


def _get_python_files_in_repo(
    root: Path,
) -> list[Path]:
    """Get tracked and untracked Python files."""

    python_files: set[Path] = set()

    try:
        result = subprocess.run(
            [
                "git",
                "ls-files",
                "*.py",
            ],
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

    try:
        result = subprocess.run(
            [
                "git",
                "ls-files",
                "--others",
                "--exclude-standard",
                "*.py",
            ],
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


def _find_symbol_in_ast(
    file_path: Path,
    symbol_name: str,
) -> dict[str, Any]:
    """Find a symbol using AST parsing."""

    try:
        source = file_path.read_text(
            encoding="utf-8"
        )
    except (OSError, UnicodeDecodeError) as e:
        return {
            "found": False,
            "symbol_type": "",
            "message": (
                f"Cannot read file: {e}"
            ),
        }

    try:
        tree = ast.parse(
            source,
            filename=str(file_path),
        )
    except SyntaxError as e:
        return {
            "found": False,
            "symbol_type": "",
            "message": (
                f"Syntax error in "
                f"{file_path}: {e}"
            ),
        }

    for node in ast.walk(tree):
        if isinstance(
            node,
            ast.FunctionDef,
        ):
            if node.name == symbol_name:
                return {
                    "found": True,
                    "symbol_type": "function",
                    "message": (
                        f"Found function "
                        f"'{symbol_name}' at "
                        f"line {node.lineno}"
                    ),
                }

        elif isinstance(
            node,
            ast.AsyncFunctionDef,
        ):
            if node.name == symbol_name:
                return {
                    "found": True,
                    "symbol_type": "function",
                    "message": (
                        f"Found async function "
                        f"'{symbol_name}' at "
                        f"line {node.lineno}"
                    ),
                }

        elif isinstance(
            node,
            ast.ClassDef,
        ):
            if node.name == symbol_name:
                return {
                    "found": True,
                    "symbol_type": "class",
                    "message": (
                        f"Found class "
                        f"'{symbol_name}' at "
                        f"line {node.lineno}"
                    ),
                }

    return {
        "found": False,
        "symbol_type": "",
        "message": (
            f"Symbol '{symbol_name}' "
            f"not found in {file_path}"
        ),
    }


def _check_required_symbol_ast(
    contract: ImplementationContract,
    entry: RequiredSymbolEntry,
) -> CheckResult:
    """Check a required symbol."""

    result = CheckResult(
        check_name="check_symbols_required"
    )

    if entry.path and entry.symbol:
        full_path = (
            contract.root / entry.path
        )

        if not full_path.exists():
            result.add_detail(
                item=(
                    f"{entry.path}:"
                    f"{entry.symbol}"
                ),
                passed=False,
                message=(
                    f"MISSING FILE: "
                    f"{full_path}"
                ),
            )
            return result

        if full_path.suffix != ".py":
            result.add_detail(
                item=(
                    f"{entry.path}:"
                    f"{entry.symbol}"
                ),
                passed=False,
                message=(
                    f"NOT A PYTHON FILE: "
                    f"{full_path}"
                ),
            )
            return result

        ast_result = _find_symbol_in_ast(
            full_path,
            entry.symbol,
        )

        if not ast_result["found"]:
            result.add_detail(
                item=(
                    f"{entry.path}:"
                    f"{entry.symbol}"
                ),
                passed=False,
                message=ast_result["message"],
            )
            return result

        if (
            entry.type
            and ast_result["symbol_type"]
            != entry.type
        ):
            result.add_detail(
                item=(
                    f"{entry.path}:"
                    f"{entry.symbol}"
                ),
                passed=False,
                message=(
                    f"WRONG TYPE: expected "
                    f"{entry.type}, found "
                    f"{ast_result['symbol_type']}"
                ),
            )
            return result

        result.add_detail(
            item=(
                f"{entry.path}:"
                f"{entry.symbol}"
            ),
            passed=True,
            message=ast_result["message"],
        )

        return result

    if entry.module:
        if not entry.symbols:
            result.add_detail(
                item=(
                    f"{entry.module}:"
                    f"(no symbols)"
                ),
                passed=False,
                message=(
                    f"MALFORMED DEFINITION: "
                    f"module '{entry.module}' "
                    f"has no symbols defined. "
                    f"module-based symbol "
                    f"definitions require a "
                    f"non-empty 'symbols' list."
                ),
            )
            return result

        for sym in entry.symbols:
            try:
                import importlib

                mod = importlib.import_module(
                    entry.module
                )

                if not hasattr(mod, sym):
                    result.add_detail(
                        item=(
                            f"{entry.module}."
                            f"{sym}"
                        ),
                        passed=False,
                        message=(
                            f"SYMBOL NOT FOUND: "
                            f"{entry.module}.{sym}"
                        ),
                    )
                else:
                    result.add_detail(
                        item=(
                            f"{entry.module}."
                            f"{sym}"
                        ),
                        passed=True,
                        message=(
                            f"Found symbol {sym} "
                            f"in {entry.module}"
                        ),
                    )

            except ImportError as e:
                result.add_detail(
                    item=(
                        f"{entry.module}."
                        f"{sym}"
                    ),
                    passed=False,
                    message=f"IMPORT ERROR: {e}",
                )

            except Exception as e:
                result.add_detail(
                    item=(
                        f"{entry.module}."
                        f"{sym}"
                    ),
                    passed=False,
                    message=f"ERROR: {e}",
                )

    return result


def check_symbols_required(
    contract: ImplementationContract,
) -> CheckResult:
    """Check required symbols."""

    result = CheckResult(
        check_name="check_symbols_required"
    )

    for entry in contract.required_symbols:
        sub_result = _check_required_symbol_ast(
            contract,
            entry,
        )

        result.total_items += (
            sub_result.total_items
        )
        result.failed_items += (
            sub_result.failed_items
        )

        if not sub_result.passed:
            result.passed = False

        result.details.extend(
            sub_result.details
        )

    return result


def _find_forbidden_symbol_in_repo(
    contract: ImplementationContract,
    forbidden: ForbiddenSymbolEntry,
) -> CheckResult:
    """Search repository for a forbidden symbol."""

    result = CheckResult(
        check_name="check_symbols_forbidden"
    )

    python_files = _get_python_files_in_repo(
        contract.root
    )

    for py_file in python_files:
        if forbidden.path:
            try:
                rel = py_file.resolve().relative_to(
                    contract.root.resolve()
                )

                if not str(rel).startswith(
                    forbidden.path
                ):
                    continue

            except ValueError:
                continue

        ast_result = _find_symbol_in_ast(
            py_file,
            forbidden.symbol,
        )

        if ast_result["found"]:
            if (
                forbidden.type
                and ast_result["symbol_type"]
                != forbidden.type
            ):
                continue

            result.add_detail(
                item=(
                    f"{py_file}:"
                    f"{forbidden.symbol}"
                ),
                passed=False,
                message=(
                    "FORBIDDEN SYMBOL FOUND: "
                    f"{ast_result['message']}"
                ),
            )

    return result


def check_symbols_forbidden(
    contract: ImplementationContract,
) -> CheckResult:
    """Check that forbidden symbols don't exist."""

    result = CheckResult(
        check_name="check_symbols_forbidden"
    )

    for forbidden in contract.forbidden_symbols:
        if not forbidden.symbol:
            continue

        sub_result = (
            _find_forbidden_symbol_in_repo(
                contract,
                forbidden,
            )
        )

        result.total_items += (
            sub_result.total_items
        )
        result.failed_items += (
            sub_result.failed_items
        )

        if not sub_result.passed:
            result.passed = False

        result.details.extend(
            sub_result.details
        )

    return result


# ──────────────────────────────────────────────────────────────────────
# Git diff / conflict-marker detection
# ──────────────────────────────────────────────────────────────────────


_CONFLICT_PATTERNS: tuple[str, ...] = (
    "<<<<<<<",
    "=======",
    ">>>>>>>",
)


def _git_diff_conflict_markers(
    root: Path,
) -> list[tuple[str, int]]:
    """Find conflict markers in files changed against HEAD."""

    try:
        diff_result = subprocess.run(
            [
                "git",
                "diff",
                "HEAD",
                "--name-only",
            ],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=30,
        )

        if diff_result.returncode != 0:
            return []

        changed_files = [
            f
            for f in diff_result.stdout.strip().splitlines()
            if f.strip()
        ]

    except (subprocess.TimeoutExpired, OSError):
        return []

    markers: list[tuple[str, int]] = []

    for rel_path in changed_files:
        full_path = root / rel_path

        try:
            lines = full_path.read_text(
                encoding="utf-8",
                errors="replace",
            ).splitlines()
        except OSError:
            continue

        for i, line in enumerate(
            lines,
            start=1,
        ):
            stripped = line.lstrip()

            for marker in _CONFLICT_PATTERNS:
                if stripped.startswith(marker):
                    markers.append(
                        (rel_path, i)
                    )
                    break

    return markers


def check_git_diff_check(
    contract: ImplementationContract,
) -> CheckResult:
    """Check git diff for whitespace errors and conflict markers."""

    result = CheckResult(
        check_name="check_git_diff_check"
    )

    try:
        diff_result = subprocess.run(
            [
                "git",
                "diff",
                "HEAD",
                "--check",
            ],
            cwd=str(contract.root),
            capture_output=True,
            text=True,
            timeout=30,
        )

        combined_output = (
            diff_result.stdout
            + diff_result.stderr
        ).strip()

        if (
            "Not a git repository"
            in combined_output
            or "not a git repository"
            in combined_output.lower()
        ):
            result.add_detail(
                item="git diff HEAD --check",
                passed=False,
                message=(
                    "NOT A GIT REPOSITORY: "
                    f"{combined_output[:500]}"
                ),
            )
            return result

        conflict_markers = (
            _git_diff_conflict_markers(
                contract.root
            )
        )

        if diff_result.returncode != 0:
            error_output = (
                combined_output
                if combined_output
                else "unknown whitespace error"
            )

            message = (
                f"WHITESPACE ERRORS: "
                f"{error_output[:500]}"
            )

            if conflict_markers:
                message += (
                    "\nCONFLICT MARKERS in diff: "
                    + "; ".join(
                        f"{rel}:{lineno}"
                        for rel, lineno
                        in conflict_markers[:10]
                    )
                )

            result.add_detail(
                item="git diff HEAD --check",
                passed=False,
                message=message,
            )

        else:
            if conflict_markers:
                result.add_detail(
                    item="git diff HEAD --check",
                    passed=False,
                    message=(
                        "CONFLICT MARKERS in diff: "
                        + "; ".join(
                            f"{rel}:{lineno}"
                            for rel, lineno
                            in conflict_markers[:10]
                        )
                    ),
                )
            else:
                result.add_detail(
                    item="git diff HEAD --check",
                    passed=True,
                    message=(
                        "no whitespace errors; "
                        "no conflict markers"
                    ),
                )

    except (
        subprocess.TimeoutExpired,
        OSError,
    ) as e:
        result.add_detail(
            item="git diff HEAD --check",
            passed=False,
            message=(
                f"GIT COMMAND FAILED: {e}"
            ),
        )

    return result


# ──────────────────────────────────────────────────────────────────────
# ADR-005 Amendment 01: os.replace enforcement
# ──────────────────────────────────────────────────────────────────────


def _find_os_replace_calls(
    file_path: Path,
) -> list[int]:
    """Find line numbers of os.replace(...) call sites."""

    try:
        source = file_path.read_text(
            encoding="utf-8"
        )
    except (OSError, UnicodeDecodeError):
        return []

    try:
        tree = ast.parse(
            source,
            filename=str(file_path),
        )
    except SyntaxError:
        return []

    lines: list[int] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func

            if (
                isinstance(func, ast.Attribute)
                and func.attr == "replace"
                and isinstance(
                    func.value,
                    ast.Name,
                )
                and func.value.id == "os"
            ):
                lines.append(node.lineno)

    return lines


def check_no_os_replace(
    contract: ImplementationContract,
) -> CheckResult:
    """Assert that forbidden files contain no os.replace call site."""

    result = CheckResult(
        check_name="check_no_os_replace"
    )

    forbidden_files: list[str] = getattr(
        contract,
        "forbidden_os_replace",
        [],
    )

    for rel_path in forbidden_files:
        full_path = (
            contract.root / rel_path
        )

        if not full_path.exists():
            result.add_detail(
                item=rel_path,
                passed=False,
                message=(
                    f"FILE NOT FOUND: "
                    f"{full_path}"
                ),
            )
            continue

        calls = _find_os_replace_calls(
            full_path
        )

        if calls:
            result.add_detail(
                item=rel_path,
                passed=False,
                message=(
                    "os.replace call site(s) "
                    "at line(s) "
                    + ", ".join(
                        str(n)
                        for n in calls
                    )
                ),
            )
        else:
            result.add_detail(
                item=rel_path,
                passed=True,
                message=(
                    "no os.replace call site"
                ),
            )

    return result


# ──────────────────────────────────────────────────────────────────────
# Default-on deterministic pre-completion checks
# ──────────────────────────────────────────────────────────────────────


_CONFLICT_PREFIXES: tuple[str, ...] = (
    "<<<<<<<",
    ">>>>>>>",
    "=======",
)


def check_working_tree_clean(
    root: Path | None = None,
) -> CheckResult:
    """Check that the working tree has no uncommitted changes."""

    if root is None:
        root = Path.cwd()

    result = CheckResult(
        check_name="check_working_tree_clean"
    )

    root = Path(root)

    try:
        status_result = subprocess.run(
            [
                "git",
                "status",
                "--porcelain",
            ],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=30,
        )

    except (
        subprocess.TimeoutExpired,
        OSError,
    ) as e:
        result.add_detail(
            item="git status --porcelain",
            passed=False,
            message=(
                f"GIT COMMAND FAILED: {e}"
            ),
        )
        return result

    combined = (
        status_result.stdout
        + status_result.stderr
    ).strip()

    if "not a git repository" in combined.lower():
        result.add_detail(
            item="git status --porcelain",
            passed=False,
            message=(
                f"NOT A GIT REPOSITORY: "
                f"{combined[:500]}"
            ),
        )
        return result

    if (
        status_result.returncode != 0
        and not combined
    ):
        result.add_detail(
            item="git status --porcelain",
            passed=False,
            message=(
                "GIT COMMAND FAILED "
                f"(rc={status_result.returncode})"
            ),
        )
        return result

    if not combined:
        result.add_detail(
            item="working tree",
            passed=True,
            message="working tree is clean",
        )
        return result

    for line in combined.splitlines():
        line = line.strip()

        if not line:
            continue

        status_code = (
            line[:2]
            if len(line) >= 2
            else "?"
        )

        path = (
            line[3:]
            if len(line) >= 3
            else line
        )

        result.add_detail(
            item=path,
            passed=False,
            message=(
                f"UNCLEAN: status "
                f"'{status_code}' — {line}"
            ),
        )

    return result


def check_tests_pass_after_rebase(
    test_command: str = "uv run pytest tests/",
    root: Path | None = None,
    timeout: int = 600,
) -> CheckResult:
    """Re-run the full test suite after final rebase."""

    if root is None:
        root = Path.cwd()

    root = Path(root)

    result = CheckResult(
        check_name="check_tests_pass_after_rebase"
    )

    try:
        proc = subprocess.run(
            test_command,
            shell=True,
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=timeout,
        )

        passed = proc.returncode == 0

        snippet = (
            proc.stdout + proc.stderr
        ).strip()

        if len(snippet) > 2000:
            snippet = snippet[-2000:]

        result.add_detail(
            item=test_command,
            passed=passed,
            message=(
                f"exit {proc.returncode} "
                f"(0 = pass)"
                + (
                    f"\n--- output ---\n{snippet}"
                    if not passed
                    else ""
                )
            ),
        )

    except subprocess.TimeoutExpired:
        result.add_detail(
            item=test_command,
            passed=False,
            message=(
                f"TIMEOUT after {timeout}s"
            ),
        )

    except OSError as e:
        result.add_detail(
            item=test_command,
            passed=False,
            message=f"COMMAND FAILED: {e}",
        )

    return result


_DEFAULT_CHECKS: dict[str, Any] = {
    "working_tree_clean": (
        lambda config, root:
        check_working_tree_clean(root)
    ),
    "git_diff_check": (
        lambda config, root:
        check_git_diff_check(
            _contract_for_root(root)
        )
    ),
    "tests_pass_after_rebase": (
        lambda config, root:
        check_tests_pass_after_rebase(
            config.test_command,
            root,
            config.test_timeout,
        )
    ),
}


def _contract_for_root(
    root: Path,
) -> ImplementationContract:
    """Build a minimal contract pointing at root."""

    return ImplementationContract(
        version=1,
        task_id="default-pre-completion",
        root=Path(root),
    )


def run_default_checks(
    config: DefaultCheckConfig | None = None,
) -> VerificationReport:
    """Run default-on pre-completion checks."""

    if config is None:
        config = DefaultCheckConfig()

    report = VerificationReport(
        task_id="default-pre-completion"
    )

    if not config.enabled:
        report.summary = (
            "default checks disabled"
        )

        from datetime import (
            datetime,
            timezone,
        )

        report.generated_at = (
            datetime.now(
                timezone.utc
            ).isoformat()
        )

        return report

    root = config.root

    order = [
        "working_tree_clean",
        "git_diff_check",
        "tests_pass_after_rebase",
    ]

    for name in order:
        if (
            name == "working_tree_clean"
            and not config.run_working_tree_clean
        ):
            continue

        if (
            name == "git_diff_check"
            and not config.run_git_diff_check
        ):
            continue

        if (
            name == "tests_pass_after_rebase"
            and not config.run_tests_after_rebase
        ):
            continue

        check_fn = _DEFAULT_CHECKS[name]

        try:
            cr = check_fn(
                config,
                root,
            )

            report.checks[name] = cr

        except Exception as e:
            report.checks[name] = CheckResult(
                check_name=name,
                passed=False,
                error=str(e),
            )

    failed_checks = []

    for name, cr in report.checks.items():
        if cr.has_error:
            failed_checks.append(
                {
                    "check": name,
                    "error": cr.error,
                }
            )

        elif not cr.passed:
            for detail in cr.details:
                if not detail["passed"]:
                    failed_checks.append(
                        {
                            "check": name,
                            "item": detail["item"],
                            "message": detail["message"],
                        }
                    )

    report.failures = failed_checks

    report.overall = (
        "FAIL"
        if failed_checks
        else "PASS"
    )

    total_items = sum(
        cr.total_items
        for cr in report.checks.values()
    )

    total_failed = sum(
        cr.failed_items
        for cr in report.checks.values()
    )

    total_errors = sum(
        1
        for cr in report.checks.values()
        if cr.has_error
    )

    check_count = len(report.checks)

    if report.is_pass:
        report.summary = (
            f"PASS: {check_count} "
            f"default checks, "
            f"{total_items} items, "
            f"0 failures"
        )
    else:
        report.summary = (
            f"FAIL: {check_count} "
            f"default checks, "
            f"{total_items} items, "
            f"{total_failed} failures, "
            f"{total_errors} errors"
        )

    from datetime import (
        datetime,
        timezone,
    )

    report.generated_at = (
        datetime.now(
            timezone.utc
        ).isoformat()
    )

    return report


def run_default_checks_cli(
    config: DefaultCheckConfig | None = None,
) -> int:
    """CLI entry point for default-on checks."""

    report = run_default_checks(config)

    import json

    print(
        json.dumps(
            report.to_dict(),
            indent=2,
        )
    )

    return report.exit_code()


# ──────────────────────────────────────────────────────────────────────
# Execution framework
# ──────────────────────────────────────────────────────────────────────


def run_verification(
    contract_path: str | Path,
) -> VerificationReport:
    """Run all implemented checks against a contract."""

    contract = ImplementationContract.load(
        contract_path
    )

    report = VerificationReport(
        task_id=contract.task_id
    )

    checks = [
        (
            "files_create",
            check_files_create,
        ),
        (
            "files_immutable",
            check_files_immutable,
        ),
        (
            "data_write_path",
            check_data_write_path,
        ),
        (
            "data_file_write_gates",
            check_data_file_write_gates,
        ),
        (
            "commands",
            check_commands,
        ),
        (
            "files_modify",
            check_files_modify,
        ),
        (
            "unexpected_modified",
            check_files_unexpected_modified,
        ),
        (
            "untracked",
            check_files_untracked,
        ),
        (
            "symbols_required",
            check_symbols_required,
        ),
        (
            "symbols_forbidden",
            check_symbols_forbidden,
        ),
        (
            "os_replace",
            check_no_os_replace,
        ),
        (
            "git_diff_check",
            check_git_diff_check,
        ),
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

    failed_checks = []

    for name, cr in report.checks.items():
        if cr.has_error:
            failed_checks.append(
                {
                    "check": name,
                    "error": cr.error,
                }
            )

        elif not cr.passed:
            for detail in cr.details:
                if not detail["passed"]:
                    failed_checks.append(
                        {
                            "check": name,
                            "item": detail["item"],
                            "message": detail["message"],
                        }
                    )

    report.failures = failed_checks

    report.overall = (
        "FAIL"
        if failed_checks
        else "PASS"
    )

    total_items = sum(
        cr.total_items
        for cr in report.checks.values()
    )

    total_failed = sum(
        cr.failed_items
        for cr in report.checks.values()
    )

    total_errors = sum(
        1
        for cr in report.checks.values()
        if cr.has_error
    )

    check_count = len(report.checks)

    if report.is_pass:
        report.summary = (
            f"PASS: {check_count} checks, "
            f"{total_items} items, "
            f"0 failures"
        )
    else:
        report.summary = (
            f"FAIL: {check_count} checks, "
            f"{total_items} items, "
            f"{total_failed} failures, "
            f"{total_errors} errors"
        )

    from datetime import (
        datetime,
        timezone,
    )

    report.generated_at = (
        datetime.now(
            timezone.utc
        ).isoformat()
    )

    return report


def run_verification_cli(
    contract_path: str | Path,
) -> int:
    """CLI entry point."""

    report = run_verification(
        contract_path
    )

    import json

    print(
        json.dumps(
            report.to_dict(),
            indent=2,
        )
    )

    return report.exit_code()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(
            "Usage: python -m janus.verification "
            "<contract.yaml>",
            file=sys.stderr,
        )
        sys.exit(1)

    sys.exit(
        run_verification_cli(sys.argv[1])
    )