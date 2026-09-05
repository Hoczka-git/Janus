# Phase 3 — Adversarial Verification Workflow

**Status:** Workflow documentation (describes the implemented Phase 3 deterministic checks and the adversarial end-to-end validation process)
**Date:** 2026-09-01
**Author:** Hermes Agent (implementer)
**Sources:** `docs/verification_pipeline_design.md`, `docs/verification_pipeline_mvp_spec.md`, `docs/verification_pipeline_phase2_1_report.md`, `docs/verification_pipeline_phase3_audit.md`, `docs/verification_pipeline_phase3_5_report.md`, `docs/verification_pipeline_phase3_5_findings.md`, `docs/verification_pipeline_phase3_6_report.md`, `docs/verification_pipeline_adversarial_validation.md`

---

## Table of Contents

1. [Purpose and Scope](#1-purpose-and-scope)
2. [Entry Criteria](#2-entry-criteria)
3. [Step-by-Step Workflow](#3-step-by-step-workflow)
4. [Adversarial Checks Performed](#4-adversarial-checks-performed)
5. [Tools and Scripts Used](#5-tools-and-scripts-used)
6. [Expected Outputs and Artifacts](#6-expected-outputs-and-artifacts)
7. [Exit Criteria](#7-exit-criteria)
8. [Relationship to Other Phases](#8-relationship-to-other-phases)

---

## 1. Purpose and Scope

### Purpose

Phase 3 introduces the adversarial verification workflow for the Janus Verification Pipeline.
Its purpose is to validate that the deterministic verification checks added in Phase 3 —
**`check_symbols_required`**, **`check_symbols_forbidden`**, and **`check_git_diff_check`** —
function correctly and cannot be fooled by plausible but incorrect contract inputs. This is
done by running the complete pipeline end-to-end against a battery of controlled test
scenarios in isolated temporary Git repositories.

The Phase 3 checks themselves provide **mechanical, AST-based (not LLM-based) validation** of
implementation contracts, preventing agents from incorrectly claiming completion
[verification_pipeline_mvp_spec.md §4.1]. The adversarial workflow described here validates
that those checks are correct, robust, and behave as specified across all supported contract
formats [verification_pipeline_phase3_audit.md §1].

### Scope

**In scope:**
- The three Phase 3 check functions: `check_symbols_required`, `check_symbols_forbidden`,
  `check_git_diff_check`.
- Their integration into `run_verification()` and the overall PASS/FAIL aggregation.
- The adversarial end-to-end validation process (31 scenarios) that exercises the full
  `YAML → ImplementationContract.load() → parsed contract → run_verification() → VerificationReport`
  boundary [verification_pipeline_adversarial_validation.md §2].
- The F-03 bugfix (frozen dataclass mutation in `_parse_forbidden_symbols`) and its regression
  coverage [verification_pipeline_phase3_5_findings.md, verification_pipeline_phase3_6_report.md].

**Out of scope:**
- Adversarial review by a separate LLM agent (described as Stage 4 in the design doc but
  **not implemented** — Phase 3 uses deterministic checks only).
- Automated contract generation from task descriptions.
- Pipeline automation into the conversation loop (`conversation_loop.py` is not modified).
- Phase 4 functionality (no Phase 4 code, tests, or architecture exist).

---

## 2. Entry Criteria

Before the Phase 3 adversarial verification workflow can begin, the following must be true:

1. **Phase 2 complete:** All Phase 1 and Phase 2 checks (`check_files_create`,
   `check_files_immutable`, `check_commands`, `check_files_modify`,
   `check_files_unexpected_modified`, `check_files_untracked`) are implemented and passing in
   `tests/test_verification_phase1.py` [verification_pipeline_phase2_1_report.md §9].

2. **Phase 2.1 complete:** All Git-diff commands use `HEAD`-based comparison (not index-based),
   so staged-only modifications are correctly detected [verification_pipeline_phase2_1_report.md
   §1–3]. This fix is critical for Phase 3 because `check_git_diff_check` relies on the same
   HEAD baseline [verification_pipeline_phase3_audit.md §4].

3. **Phase 3 checks present:** The three new check functions are wired into
   `run_verification()` in `src/janus/verification.py` [verification_pipeline_phase3_audit.md
   §7.1, lines 1184–1195].

4. **Existing Phase 3 tests present:** `tests/test_verification_phase3_5.py` exists with the
   Phase 3.5 end-to-end validation suite [verification_pipeline_phase3_5_report.md §3].

5. **No production data changes:** Entry requires that the verification pipeline code has not
   modified any production data files (`data/` paths) [verification_pipeline_phase3_5_report.md
   §5: "No production data changes"].

---

## 3. Step-by-Step Workflow

### Step 1: Verify Phase 2.1 Baseline

Confirm that the HEAD-based Git baseline fix from Phase 2.1 is in place. This is a prerequisite
because `check_git_diff_check` uses `git diff HEAD --check`, and if the baseline were still
index-based, staged-only whitespace errors would be missed [verification_pipeline_phase3_audit.md
§4.3, §4.4].

**Check:** In `src/janus/verification.py`, confirm `check_git_diff_check` uses
`git diff HEAD --check` (not `git diff --check`).

### Step 2: Confirm Phase 3 Checks Are Wired In

Confirm that `run_verification()` includes all three Phase 3 checks in its check list:

```python
checks = [
    ("files_create", check_files_create),
    ("files_immutable", check_files_immutable),
    ("commands", check_commands),
    ("files_modify", check_files_modify),
    ("unexpected_modified", check_files_unexpected_modified),
    ("untracked", check_files_untracked),
    ("symbols_required", check_symbols_required),       # Phase 3
    ("symbols_forbidden", check_symbols_forbidden),     # Phase 3
    ("git_diff_check", check_git_diff_check),            # Phase 3
]
```

[verification_pipeline_phase3_audit.md §7.1, verification_pipeline_design.md §4.1]

### Step 3: Run Phase 3 Unit Tests

Run the existing Phase 3 unit tests that test each check function in isolation:

```
uv run pytest tests/test_verification_phase1.py -v --tb=short
```

**Expected:** All tests pass (80/80 after Phase 2.1 additions, including Phase 3 tests)
[verification_pipeline_phase2_1_report.md §4].

### Step 4: Run Phase 3.5 End-to-End Adversarial Validation

Run the full Phase 3.5 adversarial validation suite, which exercises the complete
`YAML → load → verify` path through real temporary Git repositories:

```
uv run pytest tests/test_verification_phase3_5.py -v --tb=short
```

The test matrix covers [verification_pipeline_adversarial_validation.md §3–§8]:

| Category | Scenarios | What it validates |
|----------|-----------|-------------------|
| 1. Required symbols (formats) | 4 | Both file-based AST and module-based legacy formats parse and verify correctly; mixed entries work; wrong types fail |
| 2. Forbidden symbols (formats) | 4 | Path-restricted + typed detection works; comment-only and string-only occurrences do NOT trigger |
| 3. Module-based definitions | 2 | Multiple symbols in one module; one missing symbol correctly fails |
| 4. Multiple modules | 1 | Two different modules in `required_symbols` parse and verify |
| 5. Multiple symbols | 1 | Symbols spanning multiple files with 2 files |
| 6. Mixed required/forbidden | 2 | Both checks execute independently with correct combined results |
| 7. Type semantics (YAML) | 7 | Empty type = any; async functions match `"function"`; wrong type fails; missing type = any |
| 8. Malformed contracts | 12 | Mandatory field validation; malformed entries; module-without-symbols; scope constraints; edge cases |

### Step 5: Run Full Test Suite

Run the entire test suite to confirm no regressions:

```
uv run pytest tests/ -v --tb=short
```

**Expected (post-F-03 fix):** 525/525 passing [verification_pipeline_phase3_6_report.md §2.3].

### Step 6: Verify git diff --check

```
git diff --check
```

**Expected:** Exit code 0, no whitespace errors [verification_pipeline_phase3_6_report.md §2.4].

### Step 7: Validate No Unauthorized Changes

Confirm via `git status` that no production data files, no commits, and no Phase 4 functionality
were introduced [verification_pipeline_phase3_5_report.md §5, verification_pipeline_phase3_6_report.md
§8].

---

## 4. Adversarial Checks Performed

### 4.1 Required Symbol Checks (`check_symbols_required`)

`check_symbols_required` is an **AST-based** check — it walks the Python AST
(`ast.FunctionDef`, `ast.AsyncFunctionDef`, `ClassDef`) and matches on `node.name`, not on
textual patterns. This prevents false positives from comments, docstrings, and string
literals [verification_pipeline_phase3_audit.md §4.1, lines 750–810, 813–901].

**Adversarial scenarios validated:**

| Scenario | Method | Expected | Actual | Source |
|----------|--------|----------|--------|--------|
| Symbol in comment only | `test_symbol_in_comment_only_not_found` | Not found (FAIL) | Not found (FAIL) | [test_verification_phase1.py:164] |
| Symbol in string only | `test_symbol_in_string_only_not_found` | Not found (FAIL) | Not found (FAIL) | [test_verification_phase1.py:183] |
| Wrong symbol type | `test_wrong_symbol_type_fails` | FAIL | FAIL | [test_verification_phase1.py:122] |
| Malformed Python source | `test_malformed_python_source_fails` | FAIL | FAIL | [test_verification_phase1.py:132] |
| Missing source file | `test_missing_source_file_fails` | FAIL | FAIL | [test_verification_phase3_5.py:8b] |
| Required symbol points to non-Python file (.md) | Test 8l | FAIL | FAIL | [verification_pipeline_adversarial_validation.md §8l] |
| Async function matches `"function"` type | Test 7e, 7g | PASS | PASS | [verification_pipeline_adversarial_validation.md §7] |

**Key finding:** `AsyncFunctionDef` is correctly treated as type `"function"` — async functions
match a `"function"` type requirement [verification_pipeline_adversarial_validation.md §7,
"Critical findings"].

### 4.2 Forbidden Symbol Checks (`check_symbols_forbidden`)

`check_symbols_forbidden` also uses AST-based detection. It only matches actual AST declaration
nodes, so comments and string literals do not trigger the check [verification_pipeline_phase3_audit.md
§4.1].

**Adversarial scenarios validated:**

| Scenario | Method | Expected | Actual | Source |
|----------|--------|----------|--------|--------|
| Forbidden function present | `test_forbidden_function_exists_fails` | FAIL | FAIL | [test_verification_phase1.py:132] |
| Forbidden class present | `test_forbidden_class_exists_fails` | FAIL | FAIL | [test_verification_phase1.py:140] |
| Forbidden absent | `test_forbidden_symbol_absent_passes` | PASS | PASS | [test_verification_phase1.py:153] |
| Symbol in comment only | `test_symbol_in_comment_only_does_not_trigger` | PASS (no trigger) | PASS | [test_verification_phase1.py:170] |
| Symbol in string only | `test_symbol_in_string_only_does_not_trigger` | PASS (no trigger) | PASS | [test_verification_phase1.py:188] |
| Async function detection | `test_async_function_detection` | FAIL | FAIL | [test_verification_phase1.py:196] |
| Optional path restriction | `test_optional_path_restriction_works` | FAIL (inside path), PASS (outside) | FAIL | [test_verification_phase1.py:210] |
| Forbidden outside path restriction | Test 8o | PASS | PASS | [verification_pipeline_adversarial_validation.md §8o] |

### 4.3 Git Diff Check (`check_git_diff_check`)

`check_git_diff_check` runs `git diff HEAD --check` and reports whitespace errors (trailing
whitespace, missing newlines at end of file, etc.) [verification_pipeline_phase3_audit.md §4.4,
lines 998–1058].

**Adversarial scenarios validated:**

| Scenario | Method | Expected | Actual | Source |
|----------|--------|----------|--------|--------|
| Clean repository | `test_clean_repository_passes` | PASS | PASS | [test_verification_phase1.py:262] |
| Unstaged whitespace error | `test_unstaged_whitespace_error_fails` | FAIL | FAIL | [test_verification_phase1.py:275] |
| Staged whitespace error | `test_staged_whitespace_error_fails` | FAIL | FAIL | [test_verification_phase1.py:288] |
| Non-git directory | `test_command_failure_produces_deterministic_fail` | FAIL | FAIL | [test_verification_phase1.py:500] |

**Key finding:** The check runs against the **entire repository working tree vs HEAD**, not
just contract-scoped files. This is the correct interpretation for a pre-commit gate
[verification_pipeline_phase3_audit.md §4.5].

**Edge case:** In non-git directories, `git diff HEAD --check` prints "Not a git repository"
to **stdout** (not stderr) and returns exit code 0. Without explicit detection, this would
produce a false PASS [verification_pipeline_phase3_audit.md §4.4, lines 1025–1032]. The check
explicitly detects this case and reports FAIL.

### 4.4 Contract Loading and Parsing Adversarial Checks

The Phase 3.5 adversarial validation independently exercises the full YAML parsing path — it does
**not** trust existing unit tests but instead creates realistic temporary Git repositories and
runs them through `ImplementationContract.load()` → `run_verification()` [verification_pipeline_adversarial_validation.md
§2].

**Malformed contract scenarios validated (12 scenarios, test section 8):**

| # | Scenario | Expected | Actual | Source |
|---|----------|----------|--------|--------|
| 8a | `version: "not-an-integer"` | ValueError | ValueError | [verification_pipeline_adversarial_validation.md §8a] |
| 8a | Missing `task_id` | ValueError | ValueError | [verification_pipeline_adversarial_validation.md §8a] |
| 8a | List instead of mapping | ValueError | ValueError | [verification_pipeline_adversarial_validation.md §8a] |
| 8a | `task_id: "   "` (whitespace only) | ValueError | ValueError | [verification_pipeline_adversarial_validation.md §8a] |
| 8e | Symbol entry with path but no `symbol` field | Skipped, PASS | Skipped, PASS | [verification_pipeline_adversarial_validation.md §8e] |
| 8f | Forbidden entry with whitespace-only `symbol` | Skipped, PASS | Skipped, PASS | [verification_pipeline_adversarial_validation.md §8e] |
| 8g | Forbidden entry missing `symbol` key | Skipped, PASS | Skipped, PASS | [verification_pipeline_adversarial_validation.md §8e] |
| 8h | File entry without `path` field | Skipped, PASS | Skipped, PASS | [verification_pipeline_adversarial_validation.md §8e] |
| 8i | Verification command with whitespace-only `command` | Skipped, PASS | Skipped, PASS | [verification_pipeline_adversarial_validation.md §8e] |
| 8h | Module without symbols list | FAIL (clear error message) | FAIL | [verification_pipeline_adversarial_validation.md §8h] |
| 8k | `max_new_files: "unlimited"` (non-integer) | PASS (defaulted to None) | PASS | [verification_pipeline_adversarial_validation.md §8k] |
| 8l | Forbidden symbol but no Python files in repo | PASS | PASS | [verification_pipeline_adversarial_validation.md §8l] |
| 8m | Required symbol points to non-Python file (.md) | FAIL | FAIL | [verification_pipeline_adversarial_validation.md §8l] |
| 8n | Required symbol file does not exist | FAIL | FAIL | [verification_pipeline_adversarial_validation.md §8l] |

**Finding: 31/31 scenarios passed as expected — NO DEFECTS FOUND** [verification_pipeline_adversarial_validation.md §6].

---

## 5. Tools and Scripts Used

### 5.1 Primary Implementation File

| Component | File | Lines | Purpose |
|-----------|------|-------|---------|
| Check functions | `src/janus/verification.py` | 813–928, 931–995, 998–1058 | The three Phase 3 check implementations |
| Execution entry point | `src/janus/verification.py` | 1231–1291 | `run_verification()` — loads contract, runs all 9 checks, aggregates results |
| Exception handling | `src/janus/verification.py` | 1265–1274 | Each check wrapped in try/except; exceptions recorded without crashing |
| Result aggregation | `src/janus/verification.py` | 1276–1291 | Collects failures from `has_error` and `not passed` paths |

### 5.2 Test Files

| File | Purpose |
|------|---------|
| `tests/test_verification_phase1.py` | Unit tests for all 9 check functions, including Phase 3 tests (symbols_required, symbols_forbidden, git_diff_check) |
| `tests/test_verification_phase3_5.py` | Phase 3.5 end-to-end adversarial validation suite; also contains the 7 F-03 regression tests (`TestPhase3_6F03Regression`) |

### 5.3 Trigger Command

The verification pipeline is triggered via `janus verify-contract`, which calls
`run_verification()` [research findings summary, source reference].

### 5.4 Git Baseline Commands

All Phase 3 Git operations use HEAD-based comparison (inherited from Phase 2.1 fix):

| Function | Command |
|----------|---------|
| `check_git_diff_check` | `git diff HEAD --check` |
| `check_files_modify` | `git diff HEAD --name-only` |
| `check_files_unexpected_modified` | `git diff HEAD --name-only` |
| `check_files_untracked` | `git ls-files --others` |
| `check_files_immutable` | `git diff HEAD -- <path>` |

[verification_pipeline_phase3_audit.md §8, verification_pipeline_phase2_1_report.md §2]

---

## 6. Expected Outputs and Artifacts

### 6.1 Verification Report (`VerificationReport`)

`run_verification()` produces a `VerificationReport` with:

- `task_id` — from the loaded contract
- `overall` — "PASS" or "FAIL" (exit code 0 on PASS, 1 on FAIL)
- `checks` — dictionary of 9 `CheckResult` objects, one per check function
- `summary` — human-readable one-line summary
- `failures` — list of failed items (only present if FAIL)

[verification_pipeline_mvp_spec.md §4.3]

### 6.2 Per-Check Results (`CheckResult`)

Each `CheckResult` includes:
- `check_name` — identifier for the check
- `passed` — boolean
- `has_error` — boolean (set if the check raised an exception)
- `error` — error string (if exception occurred)
- `details` — list of per-item results (each with `item`, `passed`, `message`)
- `failed_items` / `total_items` — counts
- `summary` — human-readable one-line summary

### 6.3 Test Artifacts

| Artifact | Location | Content |
|----------|----------|---------|
| Phase 3 unit test results | `tests/test_verification_phase1.py` | 36 tests (Phase 1 + Phase 3 checks) |
| Phase 3.5 adversarial validation results | `tests/test_verification_phase3_5.py` | 30 tests (23 Phase 3.5 + 7 F-03 regression) |
| Adversarial validation report | `docs/verification_pipeline_adversarial_validation.md` | Full 31-scenario results matrix |
| F-03 findings detail | `docs/verification_pipeline_phase3_5_findings.md` | FrozenInstanceError bug discovery |
| Phase 3.5 report | `docs/verification_pipeline_phase3_5_report.md` | Report of the bug discovery that blocked Phase 3.5 |
| Phase 3.6 remediation report | `docs/verification_pipeline_phase3_6_report.md` | F-03 fix + regression verification |
| Phase 3 audit report | `docs/verification_pipeline_phase3_audit.md` | Independent audit of Phase 3 implementation |

### 6.4 Git Status

Per the frozen scope of Phase 3:
- **No commits created** [verification_pipeline_phase3_5_report.md §5, §6]
- **No production data files modified** [verification_pipeline_phase3_5_report.md §5]
- **No Phase 4 functionality introduced** [verification_pipeline_phase3_6_report.md §8]

---

## 7. Exit Criteria

The Phase 3 adversarial verification workflow is complete when ALL of the following are true:

1. **All three Phase 3 checks are implemented** in `src/janus/verification.py` and wired into
   `run_verification()` [verification_pipeline_phase3_audit.md §7.1].

2. **All Phase 3 unit tests pass** — `tests/test_verification_phase1.py` (36/36)
   [verification_pipeline_phase3_6_report.md §2.2].

3. **Full adversarial validation passes** — `tests/test_verification_phase3_5.py` (30/30
   including F-03 regression tests) [verification_pipeline_phase3_6_report.md §2.1].

4. **Full test suite passes with no regressions** — 525/525
   [verification_pipeline_phase3_6_report.md §2.3].

5. **`git diff --check` passes** — no whitespace errors introduced
   [verification_pipeline_phase3_6_report.md §2.4].

6. **F-03 is fixed** — `_parse_forbidden_symbols` constructs `ForbiddenSymbolEntry` with all
   fields at creation time; no post-construction mutation of frozen dataclass fields
   [verification_pipeline_phase3_6_report.md §8].

7. **`ForbiddenSymbolEntry` remains frozen** — mutation after construction still raises
   `FrozenInstanceError` [verification_pipeline_phase3_6_report.md §3, test
   `test_loaded_entry_is_still_immutable`].

8. **No unauthorized changes** — no commits, no production data modifications, no Phase 4
   code [verification_pipeline_phase3_5_report.md §5, verification_pipeline_phase3_6_report.md §8].

9. **End-to-end YAML workflow validated** — `ImplementationContract.load()` succeeds with
   both flat and nested `forbidden_symbols` formats, and `check_symbols_forbidden()` correctly
   detects forbidden symbols and ignores comment-only occurrences
   [verification_pipeline_phase3_6_report.md §2.6, §4].

---

## 8. Relationship to Other Phases

### Phase 2 → Phase 3

Phase 2 implemented the file-level and command-level checks: `check_files_create`,
`check_files_immutable`, `check_files_modify`, `check_files_unexpected_modified`,
`check_files_untracked`, and `check_commands` [verification_pipeline_mvp_spec.md §4.1].

**Phase 2.1** was a critical bugfix that changed all Git-diff commands from index-based
(`git diff`) to HEAD-based (`git diff HEAD`) comparison. This fix is essential for Phase 3
because `check_git_diff_check` relies on the same HEAD baseline — without it, staged-only
whitespace errors would be silently missed
[verification_pipeline_phase2_1_report.md §1, §2.2–2.3; verification_pipeline_phase3_audit.md §4.3].

**Phase 3** adds three new checks to the existing pipeline:
- `check_symbols_required` — AST-based verification that required public API symbols exist
- `check_symbols_forbidden` — AST-based verification that forbidden symbols (e.g.,
  `delete_goal`) do not exist
- `check_git_diff_check` — `git diff HEAD --check` for whitespace errors

All three checks follow the same deterministic, no-LLM philosophy established in Phase 2
[verification_pipeline_mvp_spec.md §4.1, §4.4].

### Phase 3.5 (Adversarial Validation)

Phase 3.5 was designed as an **independent adversarial end-to-end validation** of the full
pipeline. It does NOT trust the existing Phase 3 unit tests but instead exercises the real
`YAML → ImplementationContract.load() → run_verification()` path through isolated temporary
Git repositories [verification_pipeline_adversarial_validation.md §2].

**Outcome:** Phase 3.5 **discovered verifier bug F-03** — a `FrozenInstanceError` in
`_parse_forbidden_symbols` caused by attempting to mutate frozen `ForbiddenSymbolEntry`
fields after construction. All 22 end-to-end scenarios were blocked at contract load time
[verification_pipeline_phase3_5_report.md §3, §6].

### Phase 3.6 (F-03 Remediation)

Phase 3.6 fixed F-03 by rewriting `_parse_forbidden_symbols` to:
1. Handle both the flat AST format (`{"symbol": ..., "path": ..., "type": ...}`) and the
   nested module-based format (`{"module": ..., "symbols": [...]}`).
2. Construct `ForbiddenSymbolEntry` with all fields at creation time, eliminating all
   post-construction mutation.

**Key constraint:** `ForbiddenSymbolEntry` remained `@dataclass(frozen=True)` — immutability
was preserved; the fix eliminated the mutation, not the freezing
[verification_pipeline_phase3_6_report.md §4, §5].

**Regression tests:** 7 new tests in `TestPhase3_6F03Regression` were added, including
`test_loaded_entry_is_still_immutable` which explicitly verifies that frozen behavior is
preserved after loading [verification_pipeline_phase3_6_report.md §3].

**Re-validation:** After F-03 fix, the full Phase 3.5 adversarial validation was re-run:
**31/31 scenarios passed as expected — NO DEFECTS FOUND**
[verification_pipeline_adversarial_validation.md §6].

### Phase 3 → Phase 4

Phase 4 is **not yet implemented**. The design document describes Stage 4 as an
"Adversarial Review Gate" using a separate verification actor (different LLM instance or
human reviewer) to check correctness, test quality, security, and contract completeness
[verification_pipeline_design.md §5, §6]. This remains a future stage — Phase 3 covers only
the deterministic, AST-based checks, which are sufficient to catch the most common failure
modes without LLM judgment [verification_pipeline_design.md §4.1, §4.2].

### Phase 1/2 Regression — Confirmed No Regression

The Phase 3 audit confirmed that all Phase 1 and Phase 2 checks remain unmodified in their
core logic, with the HEAD-baseline fix from Phase 2.1 preserved:

| Check | Lines | Phase 2.1 HEAD fix preserved? |
|-------|-------|-------------------------------|
| `check_files_modify` | 575–617 | ✅ Uses `git diff HEAD --name-only` |
| `check_files_unexpected_modified` | 619–660 | ✅ Uses HEAD-based diff |
| `check_files_untracked` | 661–695 | ✅ Uses `git ls-files --others` |
| `check_files_create` | 1067–1082 | ✅ Unchanged |
| `check_files_immutable` | 1085–1123 | ✅ Uses `git diff HEAD --` |
| `check_commands` | 1126–1156 | ✅ Unchanged |
| `run_verification` | 1170–1248 | ✅ Unchanged (only added Phase 3 entries) |

[verification_pipeline_phase3_audit.md §8, §10]

---

## Appendix A: Phase 3 Check Function Reference

### `check_symbols_required`
- **Location:** `src/janus/verification.py`, lines 813–928
- **Models:** `RequiredSymbolEntry` (non-frozen dataclass, lines 42–60), `SymbolEntry` (line 75–79)
- **Mechanism:** AST-based. Walks `ast.FunctionDef`, `ast.AsyncFunctionDef`, `ClassDef` in Python source files or imports modules for runtime `hasattr` check.
- **Formats supported:** File-based AST (`path` + `symbol` + optional `type`), module-based legacy (`module` + `symbols` list)

### `check_symbols_forbidden`
- **Location:** `src/janus/verification.py`, lines 931–995
- **Models:** `ForbiddenSymbolEntry` (frozen dataclass, lines 63–72)
- **Mechanism:** AST-based. Uses `_get_python_files_in_repo()` (lines 703–747) which relies on `git ls-files` to discover Python files.
- **Formats supported:** Flat (`{"symbol": ..., "path": ..., "type": ...}`) and nested module-based (`{"module": ..., "symbols": [{"symbol": ..., "type": ...}]}`)
- **Known limitation:** In non-git directories, `_get_python_files_in_repo` returns empty → check always PASS (mitigated by `check_git_diff_check` also failing) [verification_pipeline_phase3_audit.md §5]

### `check_git_diff_check`
- **Location:** `src/janus/verification.py`, lines 998–1058
- **Command:** `git diff HEAD --check`
- **Edge case:** Detects "Not a git repository" printed to stdout (exit code 0) and reports FAIL [verification_pipeline_phase3_audit.md §4.4]

---

## Appendix B: Test Count Summary

| Test Suite | Tests | Status |
|------------|-------|--------|
| `tests/test_verification_phase1.py` | 36 | ✅ All pass |
| `tests/test_verification_phase3_5.py` | 30 (23 Phase 3.5 + 7 F-03 regression) | ✅ All pass |
| Full suite (`tests/`) | 525 | ✅ All pass |

[verification_pipeline_phase3_6_report.md §2]

---

## Appendix C: Sources

All source references are to the research findings artifacts cited inline above. The primary
sources are:

1. `docs/verification_pipeline_design.md` — Multi-stage verification pipeline design (phases 0–6)
2. `docs/verification_pipeline_mvp_spec.md` — MVEP implementation specification (contract schema, 9 check functions, PASS/FAIL semantics)
3. `docs/verification_pipeline_phase2_1_report.md` — Phase 2.1 Git baseline fix (HEAD-based comparison)
4. `docs/verification_pipeline_phase3_audit.md` — Phase 3 independent audit (PASS WITH FINDINGS)
5. `docs/verification_pipeline_phase3_5_report.md` — Phase 3.5 adversarial validation (FAILED: F-03 discovered)
6. `docs/verification_pipeline_phase3_5_findings.md` — F-03 finding detail (FrozenInstanceError)
7. `docs/verification_pipeline_phase3_6_report.md` — Phase 3.6 F-03 remediation (30/30 + 36/36 + 525/525)
8. `docs/verification_pipeline_adversarial_validation.md` — Independent 31-scenario adversarial validation (NO DEFECTS FOUND)
9. `src/janus/verification.py` — Implementation (lines 42–1334)
10. `tests/test_verification_phase1.py` — Unit tests (lines 1–624, Phase 3 section)
11. `tests/test_verification_phase3_5.py` — End-to-end + F-03 regression tests (lines 1–1375)

---

*This document describes the Phase 3 adversarial verification workflow as implemented and validated. It is suitable for inclusion in the project's documentation.*
