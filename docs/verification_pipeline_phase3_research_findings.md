# Phase 3 Adversarial Verification Workflow — Research Findings

**Date:** 2026-09-01
**Researcher:** Hermes Agent (researcher profile)
**Task:** t_10915fb8 — Research existing Phase 3 adversarial verification workflow
**Status:** Discovery complete

---

## 1. Question Investigated

What is the Phase 3 adversarial verification workflow in the Janus repository? Specifically:
- What triggers Phase 3?
- What adversarial checks are performed?
- What tools/scripts are involved?
- What outputs are produced?
- How does it fit into the broader verification pipeline?

---

## 2. Scope and Constraints

- **In scope:** `src/janus/verification.py` (the verification pipeline), `tests/test_verification_phase1.py` and `tests/test_verification_phase3_5.py` (Phase 3 tests), and all related docs in `docs/`.
- **Out of scope:** Phase 4 functionality (not yet implemented), production data files, unrelated Janus features (goals, tasks, workouts).
- **Constraint:** Discovery only — no code changes, no final documentation.

---

## 3. Evidence Examined

### Primary Source Code
- `src/janus/verification.py` (1334 lines) — the complete verification pipeline implementation
- `tests/test_verification_phase1.py` (883 lines) — Phase 3 unit + integration tests (lines 1–624 are Phase 3)
- `tests/test_verification_phase3_5.py` (1375 lines) — Phase 3.5 end-to-end validation suite

### Design and Report Documents
- `docs/verification_pipeline_design.md` (1616 lines) — full pipeline design (Stages 0–6)
- `docs/verification_pipeline_phase3_audit.md` (501 lines) — independent adversarial audit of Phase 3
- `docs/verification_pipeline_phase3_5_report.md` (263 lines) — Phase 3.5 validation report (F-03 discovery)
- `docs/verification_pipeline_phase3_5_findings.md` (69 lines) — F-03 finding detail
- `docs/verification_pipeline_phase3_6_report.md` (238 lines) — F-03 remediation report
- `docs/verification_pipeline_adversarial_validation.md` (222 lines) — post-Phase 3.5 adversarial validation (31 scenarios)

---

## 4. Current State

### 4.1 What "Phase 3" Is

Phase 3 is the third implementation increment of the Janus verification pipeline. It adds three deterministic check functions that use AST-based analysis and git diff validation:

| Check | Function | Lines | Purpose |
|-------|----------|-------|---------|
| Required symbols | `check_symbols_required()` | 963–987 | Verify required Python symbols (functions, classes, async functions) exist via AST parsing |
| Forbidden symbols | `check_symbols_forbidden()` | 1029–1054 | Verify forbidden Python symbols do NOT exist via AST parsing |
| Git diff whitespace | `check_git_diff_check()` | 1057–1117 | Verify `git diff HEAD --check` reports no whitespace errors |

### 4.2 What Triggers Phase 3

Phase 3 checks are **not triggered separately** — they run as part of the unified `run_verification()` pipeline (line 1231). The pipeline is invoked by:

1. **CLI:** `janus verify-contract <file>` → `run_verification_cli()` (line 1319)
2. **Programmatic:** `run_verification(contract_path)` (line 1231) — loads YAML contract, runs all 9 checks, returns `VerificationReport`

The 9 checks (Phase 1 + 2 + 3) run sequentially inside `run_verification()`:
```python
checks = [
    ("files_create", check_files_create),
    ("files_immutable", check_files_immutable),
    ("commands", check_commands),
    ("files_modify", check_files_modify),
    ("unexpected_modified", check_files_unexpected_modified),
    ("untracked", check_files_untracked),
    ("symbols_required", check_symbols_required),       # Phase 3
    ("symbols_forbidden", check_symbols_forbidden),       # Phase 3
    ("git_diff_check", check_git_diff_check),             # Phase 3
]
```

### 4.3 Adversarial Checks Performed

The Phase 3 checks are **deterministic mechanical checks**, not LLM-based adversarial review. The "adversarial" aspect comes from the **validation methodology** (Phase 3.5), not the checks themselves.

#### Check 1: `check_symbols_required` (AST-based required symbol detection)
- **What it does:** Parses Python files using `ast.parse()` and walks AST nodes to find `FunctionDef`, `AsyncFunctionDef`, and `ClassDef` declarations.
- **Contract format:** File-based (`path` + `symbol` + `type`) or module-based (`module` + `symbols` legacy format).
- **False-positive safety:** Only matches actual AST declarations — comments, docstrings, and string literals do NOT trigger matches.
- **Type checking:** If `type` is specified (`"function"` or `"class"`), the check verifies the symbol is the correct kind. Empty/missing type = any type matches.

#### Check 2: `check_symbols_forbidden` (AST-based forbidden symbol detection)
- **What it does:** Searches all Python files in the repo (tracked + untracked) for forbidden symbol declarations.
- **Path restriction:** If `path` is specified, only searches files under that path.
- **Type filtering:** Same type semantics as required symbols.
- **False-positive safety:** Same AST-based matching — comments/strings ignored.

#### Check 3: `check_git_diff_check` (whitespace error detection)
- **What it does:** Runs `git diff HEAD --check` to detect whitespace errors in the complete diff vs HEAD.
- **Scope:** All differences vs HEAD (not contract-scoped) — catches both staged and unstaged whitespace errors.
- **Non-git safety:** Detects "Not a git repository" in output and fails explicitly.

### 4.4 Tools and Scripts Involved

| Tool/Script | Location | Role |
|-------------|----------|------|
| `run_verification()` | `verification.py:1231` | Main entry point — loads contract, runs all checks, produces report |
| `run_verification_cli()` | `verification.py:1319` | CLI wrapper — prints JSON report to stdout |
| `ImplementationContract.load()` | `verification.py:142` | YAML contract loader with validation |
| `_find_symbol_in_ast()` | `verification.py:795` | Core AST parser — finds symbols in Python files |
| `_get_python_files_in_repo()` | `verification.py:748` | Discovers Python files via `git ls-files` |
| `_parse_symbol_list()` | `verification.py:255` | Parses required_symbols from YAML |
| `_parse_forbidden_symbols()` | `verification.py:301` | Parses forbidden_symbols from YAML (flat + nested formats) |
| `ast` (stdlib) | Python stdlib | AST parsing for symbol detection |
| `subprocess` (stdlib) | Python stdlib | Git command execution |
| `yaml` (PyYAML) | External dep | YAML contract parsing |
| `janus verify-contract` | CLI subcommand | User-facing command to run verification |

### 4.5 Outputs Produced

The pipeline produces a `VerificationReport` dataclass containing:

```python
@dataclass
class VerificationReport:
    task_id: str              # From contract
    overall: str              # "PASS" or "FAIL"
    checks: dict[str, CheckResult]  # Per-check results
    summary: str              # Human-readable summary
    failures: list[dict]      # Flat list of all failures
    generated_at: str         # ISO timestamp
```

Each `CheckResult` contains:
- `check_name`: Name of the check function
- `passed`: Boolean
- `total_items`: Number of items checked
- `failed_items`: Number that failed
- `details`: List of per-item detail dicts (`item`, `passed`, `message`)
- `error`: Error message if the check itself failed

The CLI outputs a JSON-serialized version of this report to stdout, with exit code 0 (PASS) or 1 (FAIL).

### 4.6 How Phase 3 Fits into the Broader Pipeline

The verification pipeline design defines 7 stages (0–6):

| Stage | Name | Phase 3's Role |
|-------|------|----------------|
| 0 | Task Assignment | Contract creation (human + system) |
| 1 | Implementation | Agent implements per contract |
| 2 | Mechanical Verification | Phase 1 checks (files_create, files_immutable, commands) |
| 3 | Contract Verification | Phase 2 checks (files_modify, unexpected_modified, untracked) |
| 4 | Adversarial Review | **Phase 3 checks** (symbols_required, symbols_forbidden, git_diff_check) |
| 5 | Human Approval | Human reviews evidence package |
| 6 | Commit | Agent/human commits after approval |

Phase 3 corresponds to **Stage 4 (Adversarial Review Gate)** in the design doc, though in practice all 9 checks run together in `run_verification()` without separate gating.

---

## 5. Important Findings

### 5.1 F-03 Bug (FrozenInstanceError) — FIXED

**Discovery:** Phase 3.5 validation discovered that `_parse_forbidden_symbols()` mutated a frozen `ForbiddenSymbolEntry` dataclass after construction, raising `FrozenInstanceError` for any contract using the Phase 3 AST `forbidden_symbols` format.

**Fix (Phase 3.6):** The parser was rewritten to normalize values BEFORE constructing the frozen entry. Both flat and nested module-based formats now work correctly.

**Status:** Fixed and covered by 7 regression tests in `TestPhase3_6F03Regression`.

### 5.2 F-01 Finding (Silent Skip on Malformed Module Symbols) — FIXED

**Discovery:** When a `required_symbols` entry had `module` set but no `symbols` key, the entry was silently skipped — no error, no warning.

**Fix:** Added explicit check in `_check_required_symbol_ast()` that fails with "MALFORMED DEFINITION" message when `module` is set but `symbols` is empty.

**Status:** Fixed and covered by `TestF01MalformedModuleSymbolDefinitions` (4 tests).

### 5.3 F-02 Finding (Type Semantics) — DOCUMENTED + TESTED

**Discovery:** Empty/missing `type` field correctly matches any declaration type. This is intended behavior but was undocumented.

**Status:** Documented and covered by `TestF02ForbiddenSymbolTypeSemantics` (8 tests).

### 5.4 Adversarial Validation (Post-Phase 3.5) — PASSED

An independent adversarial validation exercised 31 scenarios across the full YAML → load → verify boundary. **All 31 scenarios passed.** No F-04 defect was found.

Key validations:
- Required/forbidden symbols in supported formats (flat, nested, mixed)
- Type semantics through YAML (empty, omitted, function, class, async)
- Malformed contract handling (12 scenarios)
- Comment/string-only false-positive prevention

### 5.5 Remaining Known Limitations (Not Defects)

| ID | Severity | Issue |
|----|----------|-------|
| F-03 (original) | Low | Parser accepts invalid `type` values without validation |
| F-04 | Low | Module-based check uses runtime import (legacy path) |
| F-05 | Low | `_get_python_files_in_repo` returns empty set in non-Git dirs |

---

## 6. Alternatives Considered

Not applicable — this is a discovery task, not a design task.

---

## 7. Recommendation

The Phase 3 adversarial verification workflow is **implemented, validated, and operational**. The three Phase 3 checks (symbols_required, symbols_forbidden, git_diff_check) are:

1. **Correct** — AST-based detection avoids false positives from comments/strings
2. **Tested** — 30+ tests in Phase 3.5 suite + 12 remediation tests + 31 adversarial scenarios
3. **Integrated** — All 9 checks run through `run_verification()` with deterministic PASS/FAIL output

**Next step:** The pipeline is ready for production use. The remaining low-severity findings (F-03 invalid type validation, F-04 runtime import, F-05 non-Git handling) can be addressed as incremental improvements but are not blocking.

---

## 8. Remaining Uncertainty

- **Phase 4 status:** No Phase 4 functionality exists. The design doc mentions Stage 4 (Adversarial Review) as a separate gate with a different agent instance or prompt, but this is not yet implemented. The current "adversarial" aspect is the deterministic mechanical checks, not a separate LLM-based review.
- **Contract format evolution:** The `required_symbols` and `forbidden_symbols` fields support both legacy (module-based) and Phase 3 (file-based AST) formats. The coexistence is intentional but may cause confusion for contract authors.

---

## 9. References

| File | Lines | Content |
|------|-------|---------|
| `src/janus/verification.py` | 1–1334 | Complete verification pipeline |
| `src/janus/verification.py` | 748–792 | `_get_python_files_in_repo()` |
| `src/janus/verification.py` | 795–855 | `_find_symbol_in_ast()` |
| `src/janus/verification.py` | 858–960 | `_check_required_symbol_ast()` |
| `src/janus/verification.py` | 963–987 | `check_symbols_required()` |
| `src/janus/verification.py` | 990–1026 | `_find_forbidden_symbol_in_repo()` |
| `src/janus/verification.py` | 1029–1054 | `check_symbols_forbidden()` |
| `src/janus/verification.py` | 1057–1117 | `check_git_diff_check()` |
| `src/janus/verification.py` | 1231–1316 | `run_verification()` |
| `tests/test_verification_phase1.py` | 1–280 | F-01/F-02 remediation tests |
| `tests/test_verification_phase1.py` | 277–883 | Phase 3 unit + integration tests |
| `tests/test_verification_phase3_5.py` | 1–1375 | Phase 3.5 end-to-end validation (30 tests) |
| `docs/verification_pipeline_design.md` | 1–1616 | Full pipeline design (Stages 0–6) |
| `docs/verification_pipeline_phase3_audit.md` | 1–501 | Independent adversarial audit |
| `docs/verification_pipeline_phase3_5_report.md` | 1–263 | F-03 discovery report |
| `docs/verification_pipeline_phase3_6_report.md` | 1–238 | F-03 remediation report |
| `docs/verification_pipeline_adversarial_validation.md` | 1–222 | Post-Phase 3.5 adversarial validation (31 scenarios) |
