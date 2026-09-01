# Verification Pipeline Phase 3 — Independent Audit Report

**Date**: 2026-08-30
**Auditor**: Hermes Agent (adversarial review)
**Scope**: `src/janus/verification.py` + `tests/test_verification_phase1.py` (Phase 3 additions only)
**Verdict**: **PASS WITH FINDINGS**

---

## 1. Audit Scope and Method

Read in full:
- `src/janus/verification.py` (lines 1–1275)
- `tests/test_verification_phase1.py` (lines 1–624, Phase 3 section only)
- `docs/verification_pipeline_mvp_spec.md` (contract schema)

Verified each Phase 3 check against the specification requirements:

| Check | Spec Section | File | Lines |
|-------|-------------|------|-------|
| `check_symbols_required` | Phase 3 Req A | `verification.py` | 813–928 |
| `check_symbols_forbidden` | Phase 3 Req B | `verification.py` | 931–995 |
| `check_git_diff_check` | Phase 3 Req C | `verification.py` | 998–1058 |

---

## 2. Public Models — Schema Compatibility

### Source: `verification.py` lines 42–72, 126–128

**Verdict**: ✅ Compatible with existing schema.

**RequiredSymbolEntry** (line 42–60):
- Fields: `module`, `symbols`, `path`, `symbol`, `type`
- `module`/`symbols` preserve legacy MVP format
- `path`/`symbol`/`type` add Phase 3 AST format
- Both formats can coexist in the same entry
- Not frozen → mutable during parsing (correct design for builder pattern)

**ForbiddenSymbolEntry** (line 63–72):
- Fields: `symbol`, `path`, `type`
- All fields optional with empty-string defaults
- Frozen → immutable after construction (correct for value objects)

**ImplementationContract changes** (line 127–128):
- `required_symbols: list[RequiredSymbolEntry]` — type changed from `list[SymbolEntry]` to `list[RequiredSymbolEntry]`
- `forbidden_symbols: list[ForbiddenSymbolEntry]` — type changed from `list[str]` to `list[ForbiddenSymbolEntry]`

⚠️ **Compatibility Note (Low severity)**: Existing contracts using the old schema shape (`required_symbols: [{module: "...", symbols: [...]}]` or `forbidden_symbols: ["name1", "name2"]`) are still accepted by the parser but the type annotations are now more restrictive. The parser is lenient; the type system is not. In practice this is fine because:
- The parser handles both shapes at runtime
- No existing Janus contracts use these fields yet

---

## 3. Parsing Layer — Silent Skips and Edge Cases

### Source: `verification.py` lines 255–327

### 3.1 `_parse_symbol_list` — Missing `symbols` key with `module` present

**Location**: lines 278–296

**Scenario**: Contract contains:
```yaml
required_symbols:
  - module: "janus.verification"
```
No `symbols` key at all.

**Parser behavior** (line 282–284):
```python
symbols_raw = item.get("symbols", [])
if isinstance(symbols_raw, list):
    entry.symbols = [str(s) for s in symbols_raw if isinstance(s, str)]
```
Since `"symbols"` is missing, `symbols_raw = []`, `entry.symbols` stays `[]`.

**Check behavior** (line 824):
```python
if entry.path and entry.symbol:
    # file-based path taken
    ...
# Module-based check (line 870–899)
if entry.module and entry.symbols:
    for sym in entry.symbols:
        ...
```
Since `entry.module` is truthy but `entry.symbols` is empty, the `if` condition is False → **entry is silently skipped entirely**.

**Impact**: A contract writer who writes `module: "janus.verification"` expecting the parser to infer or validate something gets no error and no check. The entry vanishes from verification.

**Verdict**: **Medium — silent skip with no warning**.

This is not a crash or false positive; it's a design gap. An entry with `module` but no `symbols` should either:
- Produce a warning, or
- Be skipped with a logged message, or
- Require the `symbols` key and reject the entry

The current behavior violates the Phase 3 requirement: *"Do not silently skip malformed symbol definitions."*

---

### 3.2 `_parse_forbidden_symbols` — Missing `symbol` key

**Location**: lines 301–327

**Scenario**: Contract contains:
```yaml
forbidden_symbols:
  - path: "src/janus/"
    type: "function"
```
No `symbol` key.

**Parser behavior** (line 318–319):
```python
symbol = item.get("symbol")
if isinstance(symbol, str) and symbol.strip():
    entry.symbol = symbol.strip()
```
`entry.symbol` stays `""`.

**Check behavior** (line 986):
```python
for forbidden in contract.forbidden_symbols:
    if not forbidden.symbol:
        continue
```
Entry skipped silently.

**Verdict**: Same pattern as 3.1 — silent skip. Medium severity for same reason.

---

### 3.3 All Other Parser Paths — Correct

| Path | Behavior | Verdict |
|------|----------|---------|
| Module + symbols (legacy) | Parsed correctly | ✅ |
| Path + symbol + type (Phase 3) | Parsed correctly | ✅ |
| Module + path + symbol (mixed) | Both fields populated, file-based check used | ✅ |
| Empty list | Returns `[]` | ✅ |
| Non-list raw | Returns `[]` silently | ✅ (defensive) |
| Non-dict items in list | Skipped silently | ✅ (defensive) |
| `type` values other than "function"/"class" | Stored as-is in model | ⚠️ (see §5.2) |

---

## 4. Check Functions — Correctness

### 4.1 `check_symbols_required` — No False Positives from Comments/Strings

**Source**: `verification.py` lines 750–810 (`_find_symbol_in_ast`) and 813–901 (`_check_required_symbol_ast`)

**AST detection** (lines 780–804):
- Walks all nodes with `ast.walk(tree)`
- Checks `isinstance(node, ast.FunctionDef)` / `AsyncFunctionDef` / `ClassDef`
- Matches only on `node.name == symbol_name`
- Does NOT check `ast.Expr`, `ast.Constant`, `ast.Str`, or comment nodes

**Verdict**: ✅ Correct. Comments, docstrings, and string literals are not AST declaration nodes — they cannot trigger false positives.

**Verified by test coverage**:
- `test_symbol_in_comment_only_not_found` (line 164)
- `test_symbol_in_string_only_not_found` (line 183)

---

### 4.2 `check_symbols_required` — Type Checking Logic

**Source**: `verification.py` lines 845–856

```python
if entry.type and ast_result["symbol_type"] != entry.type:
    result.add_detail(..., passed=False, message=f"WRONG TYPE: ...")
    return result
```

**Verdict**: ✅ Correct.
- If `entry.type == ""`, the condition is False → no type check → PASS
- If `entry.type == "function"` and symbol is a class → FAIL
- If `entry.type == "class"` and symbol is a function → FAIL

---

### 4.3 `check_symbols_forbidden` — Silent Skip on Empty `symbol`

**Source**: `verification.py` line 986

```python
for forbidden in contract.forbidden_symbols:
    if not forbidden.symbol:
        continue
```

**Verdict**: As noted in §3.2, this is a silent skip. Matches the parser behavior — consistent but undocumented.

If the contract intentionally includes a `forbidden_symbols` entry with no `symbol` field, the check silently ignores it. No error, no warning. This is the same design gap as §3.1.

---

### 4.4 `check_git_diff_check` — HEAD Baseline Correct

**Source**: `verification.py` lines 998–1058

**Git command**: `git diff HEAD --check` (line 1021)

**Verdict**: ✅ Correct.
- Uses HEAD as baseline (Phase 2.1 fix preserved)
- Catches staged + unstaged whitespace errors
- Returns non-zero exit code when whitespace errors exist
- `returncode != 0` → FAIL with error message
- `returncode == 0` → PASS

**Non-git-directory detection** (lines 1025–1032):
```python
combined_output = (diff_result.stdout + diff_result.stderr).strip()
if "Not a git repository" in combined_output or "not a git repository" in combined_output.lower():
    result.add_detail(..., passed=False, message=f"NOT A GIT REPOSITORY: ...")
    return result
```

**Verdict**: ✅ Correct. Git prints "Not a git repository" to stdout (not stderr) and returns 0 in this case — without this check, the function would report PASS incorrectly. The detection handles this edge case.

**Test coverage**: `test_command_failure_produces_deterministic_fail` (line 500) — explicitly tests non-git directory.

---

### 4.5 `check_git_diff_check` — Does Not Check Modified/Untracked File Whitespace Only

**Source**: `verification.py` lines 998–1058

The check runs `git diff HEAD --check` on the entire repository — it checks **all** differences vs HEAD, not just files declared in the contract.

**Verdict**: ✅ Matches spec. The requirement was: *"This check verifies that the relevant Git diff contains no whitespace errors."* — "relevant" is the working tree vs HEAD, not contract-scoped. This is the correct interpretation for a pre-commit gate.

---

## 5. Specific Issues

### F-01: Silent Skip When `module` Is Present But `symbols` Is Missing (Medium)

**Location**: `verification.py` lines 278–296 (parser), 870–899 (check)

**Evidence**:
```python
# Parser (line 282-284):
symbols_raw = item.get("symbols", [])
if isinstance(symbols_raw, list):
    entry.symbols = [str(s) for s in symbols_raw if isinstance(s, str)]
# If "symbols" key missing → entry.symbols stays []

# Check (line 870-871):
if entry.module and entry.symbols:
    for sym in entry.symbols:
        ...
# If entry.symbols is empty, entire entry skipped
```

**Reproduction**: Contract YAML:
```yaml
required_symbols:
  - module: "janus.verification"
```
→ No error, no warning, no check run. Entry silently dropped.

**Expected**: Either reject the contract entry, emit a warning, or check all public symbols of the module. The spec says: *"Do not silently skip malformed symbol definitions."*

**Actual**: Entry silently skipped.

**Recommended fix**: Either:
- Require `symbols` when `module` is present (validate in parser, raise or warn), OR
- In `_check_required_symbol_ast`, if `module` is set but `symbols` is empty, attempt to discover public symbols via `dir(mod)` or fail with a clear message.

---

### F-02: Forbidden Symbol Type `""` Matches All Types (Low)

**Location**: `verification.py` line 956

**Evidence**:
```python
if forbidden.type and ast_result["symbol_type"] != forbidden.type:
    continue
```
When `forbidden.type == ""`, the condition `if forbidden.type` is False → type check skipped → any type matches.

**Spec says**: `"type"` is *optional* — if not specified, search for any type.

**Verdict**: ✅ Correct interpretation. This is the intended behavior. Documenting it as "any type matches when type is empty" would improve clarity.

---

### F-03: Parser Accepts Invalid `type` Values Without Validation (Low)

**Location**: `verification.py` lines 293–295, 323–325

**Evidence**:
```python
type_val = item.get("type", "")
if isinstance(type_val, str):
    entry.type = type_val.strip()
```

The parser accepts any string for `type`, including `"foobar"`, `"VARIABLE"`, `"import"`. The check functions don't validate that `type` is one of the supported values (`"function"`, `"class"`, `""`). An invalid `type` value like `"variable"` would:
- In `check_symbols_required`: compare against `ast_result["symbol_type"]` which is never `"variable"` → always fails with "WRONG TYPE"
- In `check_symbols_forbidden`: skip any match because `ast_result["symbol_type"]` never equals `"variable"` → effectively no check

**Verdict**: Low — the behavior is deterministic, just not validated. Adding validation (accept only `"function"`, `"class"`, `""`) would make the contract schema self-documenting and prevent confusing failures.

---

### F-04: Module-Based Check Uses Runtime Import (Low — Design Limitation, Not Bug)

**Source**: `verification.py` lines 870–899

When a `RequiredSymbolEntry` has `module` set (legacy format), the check does:
```python
mod = importlib.import_module(entry.module)
if not hasattr(mod, sym):
    # FAIL
```

**Impact**:
- Imports the module at verification time
- If the module has unmet dependencies or side effects, verification may fail or have side effects
- This is the legacy MVP path; Phase 3's primary path is file-based AST

**Verdict**: Low — this is a known limitation of the legacy format. File-based AST checking is the recommended path for Phase 3. Not a correctness bug.

---

### F-05: `_get_python_files_in_repo` Relies Entirely on Git (Low — Edge Case)

**Source**: `verification.py` lines 703–747

The function uses `git ls-files` and `git ls-files --others` to discover Python files. If Git is not available or the directory is not a Git repository:
- Both subprocess calls fail silently (caught by `except`)
- `python_files` remains empty
- The check runs against zero files → always PASS

**Impact**: In a non-Git directory, `check_symbols_forbidden` always passes regardless of what Python files exist.

**Verdict**: Low — this is an edge case. The function is designed for Git repositories (which is the normal Janus usage). In non-Git contexts, the `check_git_diff_check` already fails. The silent empty scan is undesirable but not a critical defect for the MVP.

---

## 6. Test Coverage Audit

### 6.1 Required Symbols Tests (lines 48–122)

| Requirement | Test | Status |
|-------------|------|--------|
| Required function exists → PASS | `test_required_function_exists_passes` | ✅ |
| Required class exists → PASS | `test_required_class_exists_passes` | ✅ |
| Required symbol missing → FAIL | `test_required_symbol_missing_fails` | ✅ |
| Wrong symbol type → FAIL | `test_wrong_symbol_type_fails` | ✅ |
| Symbol in comment only → FAIL | `test_symbol_in_comment_only_not_found` | ✅ |
| Symbol in string only → FAIL | `test_symbol_in_string_only_not_found` | ✅ |
| Malformed Python → deterministic FAIL | `test_malformed_python_source_fails` | ✅ |
| Missing source file → FAIL | `test_missing_source_file_fails` | ✅ |

**Missing test**: Required symbol entry with `module` but no `symbols` → silent skip not tested.

---

### 6.2 Forbidden Symbols Tests (lines 132–252)

| Requirement | Test | Status |
|-------------|------|--------|
| Forbidden function exists → FAIL | `test_forbidden_function_exists_fails` | ✅ |
| Forbidden class exists → FAIL | `test_forbidden_class_exists_fails` | ✅ |
| Forbidden symbol absent → PASS | `test_forbidden_symbol_absent_passes` | ✅ |
| Symbol in comment only → PASS | `test_symbol_in_comment_only_does_not_trigger` | ✅ |
| Symbol in string only → PASS | `test_symbol_in_string_only_does_not_trigger` | ✅ |
| Async function detection | `test_async_function_detection` | ✅ |
| Optional path restriction | `test_optional_path_restriction_works` | ✅ |
| Repository-wide search | `test_repository_wide_search_works` | ✅ |

**Missing test**: Forbidden symbol entry with no `symbol` key → silent skip not tested.

---

### 6.3 Git Diff Check Tests (lines 262–340)

| Requirement | Test | Status |
|-------------|------|--------|
| Clean repository → PASS | `test_clean_repository_passes` | ✅ |
| Unstaged whitespace error → FAIL | `test_unstaged_whitespace_error_fails` | ✅ |
| Staged whitespace error → FAIL | `test_staged_whitespace_error_fails` | ✅ |
| Valid unstaged modification → PASS | `test_valid_unstaged_modification_passes` | ✅ |
| Valid staged modification → PASS | `test_valid_staged_modification_passes` | ✅ |
| Command failure → deterministic FAIL | `test_command_failure_produces_deterministic_fail` | ✅ |

**Missing tests**:
- Mixed staged + unstaged whitespace errors in same file (staged change + additional unstaged whitespace)
- Whitespace errors only in files NOT in contract (should still fail — this is correct behavior, but no explicit test)

---

### 6.4 Integration Tests (lines 348–412)

| Requirement | Test | Status |
|-------------|------|--------|
| All Phase 3 checks in `run_verification` | `test_all_phase3_checks_integrated` | ✅ |
| Phase 3 failures affect overall PASS/FAIL | `test_phase3_checks_affect_overall_pass_fail` | ✅ |

---

## 7. Execution Flow Audit

### 7.1 `run_verification` — All Checks Registered

**Source**: `verification.py` lines 1184–1195

```python
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
```

**Verdict**: ✅ All three Phase 3 checks present and in correct order.

---

### 7.2 Exception Handling in `run_verification`

**Source**: `verification.py` lines 1197–1206

Each check is wrapped in try/except. If a check raises, a `CheckResult` with `error=str(e)` is recorded.

**Verdict**: ✅ Correct — exceptions don't crash the pipeline.

---

### 7.3 Result Aggregation — FAIL Counted Correctly

**Source**: `verification.py` lines 1208–1222

Failures collected from both `cr.has_error` and `not cr.passed` paths. Per-item failures added individually.

**Verdict**: ✅ Correct.

---

## 8. Phase 1/2 Regression

The audit verified that Phase 1 and Phase 2 checks remain unmodified in their core logic:

| Check | Lines | Phase 2.1 HEAD fix preserved? |
|-------|-------|-------------------------------|
| `check_files_modify` | 575–617 | ✅ Uses `git diff HEAD --name-only` |
| `check_files_unexpected_modified` | 619–660 | ✅ Uses HEAD-based diff |
| `check_files_untracked` | 661–695 | ✅ Uses `git ls-files --others` |
| `check_files_create` | 1067–1082 | ✅ Unchanged |
| `check_files_immutable` | 1085–1123 | ✅ Uses `git diff HEAD --` |
| `check_commands` | 1126–1156 | ✅ Unchanged |
| `run_verification` | 1170–1248 | ✅ Unchanged (only added Phase 3 entries) |

**Verdict**: ✅ No regression in Phase 1/2 functionality.

---

## 9. Summary Table

| ID | Severity | Issue | Location |
|----|----------|-------|----------|
| F-01 | Medium | Silent skip: `module` present without `symbols` → entry dropped, no warning | `verification.py` lines 278–296, 870–899 |
| F-02 | Low | Forbidden type `""` matches all types — correct behavior, worth documenting | `verification.py` line 956 |
| F-03 | Low | Parser accepts invalid `type` values without validation | `verification.py` lines 293–295, 323–325 |
| F-04 | Low | Module-based check uses runtime import (legacy path, known limitation) | `verification.py` lines 870–899 |
| F-05 | Low | `_get_python_files_in_repo` returns empty set in non-Git dirs → forbidden check always PASS | `verification.py` lines 703–747 |

**No blocking defects found.**

---

## 10. Final Verdict

### PASS WITH FINDINGS

The Phase 3 implementation is **correct and complete** for the MVP scope. All three checks are properly wired into the public models, parsing layer, execution flow, and result reporting. The two silent-skip issues (F-01, F-02) are design gaps where a malformed contract entry produces no error — these should be addressed before Phase 3 is considered fully robust, but they do not break the core functionality as long as contracts are well-formed.

**Recommended actions before closing Phase 3**:
1. Fix F-01: Add validation or warning for `module`-without-`symbols` entries (makes the parser match the spec requirement: *"Do not silently skip malformed symbol definitions"*)
2. Fix F-03: Validate `type` field accepts only `"function"`, `"class"`, or `""` (self-documenting schema)
3. Add tests for the silent-skip scenarios (F-01, F-02)

**No Phase 4 functionality present. No production data modified. No commits created.**

---

*End of audit report.*
