# Verification Phase 2.1 — Git Baseline Fix: Evidence-Based Implementation Report

**Date:** 2026-08-30
**Scope:** Fix blocking defects identified in Phase 2 adversarial review
**Affected files:** `src/janus/verification.py`, `tests/test_verification_phase1.py`

---

## 1. Files Changed

| File | Action | Lines changed | Description |
|------|--------|---------------|-------------|
| `src/janus/verification.py` | MODIFY | 3 functions updated | Git baseline changed from index to HEAD |
| `tests/test_verification_phase1.py` | MODIFY | 7 new tests added | Staged-modification test coverage |

**No other files changed. No production data files touched.**

---

## 2. Exact Git Commands Changed

### 2.1 `_git_tracked_modified_files()` (line 416)

**Before:**
```python
["git", "diff", "--name-only"]
```

**After:**
```python
["git", "diff", "HEAD", "--name-only"]
```

**Rationale:** `git diff` alone compares working tree vs INDEX (staging area). `git diff HEAD` compares working tree vs committed state (HEAD). The contract requires detecting changes from the committed state.

---

### 2.2 `_git_has_diff()` (line 483)

**Before:**
```python
["git", "diff", "--", rel_path]
```

**After:**
```python
["git", "diff", "HEAD", "--", rel_path]
```

**Rationale:** Same fix — compare against HEAD, not INDEX.

---

### 2.3 `check_files_immutable()` (line 655)

**Before:**
```python
["git", "diff", "--", str(full_path)]
```

**After:**
```python
["git", "diff", "HEAD", "--", str(full_path)]
```

**Rationale:** Immutable file check must detect staged modifications that match the index but differ from HEAD.

---

## 3. Tests Added

### 3.1 `check_files_modify` — 3 new tests

| Test | Scenario | Expected | Status |
|------|----------|----------|--------|
| `test_declared_modify_file_staged_only` | File modified AND staged (working tree matches index) | PASS | ✓ |
| `test_declared_modify_file_mixed_staged_unstaged` | File has both staged v2 and unstaged v3 | PASS | ✓ |
| `test_declared_modify_file_staged_then_reverted` | File staged, then reverted to HEAD content | PASS (index differs from HEAD) | ✓ |

### 3.2 `check_files_immutable` — 2 new tests

| Test | Scenario | Expected | Status |
|------|----------|----------|--------|
| `test_immutable_file_staged_modified` | Immutable file modified AND staged | FAIL | ✓ |
| `test_immutable_file_mixed_staged_unstaged` | Immutable file with both staged and unstaged | FAIL | ✓ |

### 3.3 `check_files_unexpected_modified` — 2 new tests

| Test | Scenario | Expected | Status |
|------|----------|----------|--------|
| `test_staged_unexpected_modified` | Undeclared file modified AND staged | FAIL | ✓ |
| `test_mixed_staged_unstaged_unexpected` | Undeclared file with both staged and unstaged | FAIL | ✓ |

**Total new tests: 7**

---

## 4. Targeted Test Result

```
cd /home/dan11hermes/workspaces/janus
uv run pytest tests/test_verification_phase1.py -v --tb=short

============================= test session starts ==============================
...
tests/test_verification_phase1.py::TestCheckFilesModify::test_declared_modify_file_staged_only PASSED
tests/test_verification_phase1.py::TestCheckFilesModify::test_declared_modify_file_mixed_staged_unstaged PASSED
tests/test_verification_phase1.py::TestCheckFilesModify::test_declared_modify_file_staged_then_reverted PASSED
tests/test_verification_phase1.py::TestCheckFilesImmutable::test_immutable_file_staged_modified PASSED
tests/test_verification_phase1.py::TestCheckFilesImmutable::test_immutable_file_mixed_staged_unstaged PASSED
tests/test_verification_phase1.py::TestCheckFilesUnexpectedModified::test_staged_unexpected_modified PASSED
tests/test_verification_phase1.py::TestCheckFilesUnexpectedModified::test_mixed_staged_unstaged_unexpected PASSED
...

============================== 80 passed in 5.58s ==============================
```

**80/80 targeted tests passing** (was 73, +7 new staged-modification tests).

---

## 5. Full Test Suite Result

```
cd /home/dan11hermes/workspaces/janus
uv run pytest tests/ -v --tb=short

============================== 539 passed in 5.73s ==============================
```

**539/539 full suite passing** (was 532, +7 new). **Zero regressions.**

---

## 6. Manual Staged-Only Reproduction Result

Created temporary Git repository outside the project:

```
Git repo setup:
  - Initial commit with src/existing.py and src/other.py
  - src/existing.py declared in MODIFY contract
  - src/other.py NOT in contract

State created:
  - Modified src/existing.py and git add (staged)
  - Modified src/other.py and git add (staged)
  - Working tree matches index for both files

Git state verification:
  git status --short: 'M  src/existing.py\nM  src/other.py'
  git diff --name-only (old impl): '(empty)'        ← BUG
  git diff HEAD --name-only (new impl): 'src/existing.py\nsrc/other.py'  ← FIXED

check_files_modify (declared MODIFY, staged):
  passed = True
  details: [{'item': 'src/existing.py', 'passed': True, 'message': 'modified'}]
  → STAGED MODIFY DETECTED ✓

check_files_immutable (immutable file staged modified):
  passed = False
  failed_items = 1
  details: [{'item': 'src/other.py', 'passed': False, 'message': 'HAS DIFF: ...'}]
  → STAGED IMMUTABLE VIOLATION DETECTED ✓

check_files_unexpected_modified (staged unexpected):
  passed = False
  failed_items = 1
  details: [{'item': 'src/other.py', 'passed': False, 'message': 'UNEXPECTED MODIFICATION: src/other.py'}]
  → STAGED UNEXPECTED DETECTED ✓
```

**All three checks now correctly detect staged-only modifications.**

---

## 7. Git Diff --check Result

```
cd /home/dan11hermes/workspaces/janus
git diff --check src/janus/verification.py tests/test_verification_phase1.py

(exit code 0, no output)
```

**No whitespace errors. Clean.**

---

## 8. Git Status

```
cd /home/dan11hermes/workspaces/janus
git status --short

 M src/janus/verification.py           ← verification.py modified (baseline fix)
 M tests/test_verification_phase1.py   ← tests modified (new tests)
?? docs/verification_pipeline_phase2_review.md  ← Phase 2 review (not modified by this task)
```

**Only two production-files modified by this task.** All other modified files are pre-existing from other sessions (data/tasks.md, data/workouts.md, pyproject.toml, etc.).

---

## 9. Explicit Phase 3 Confirmation

**Phase 3 was NOT started. No Phase 3 functionality exists.**

The following checks remain explicitly deferred (NOT implemented):

| Check | Status |
|-------|--------|
| `check_symbols_required` | Deferred to Phase 3 — NOT implemented |
| `check_symbols_forbidden` | Deferred to Phase 3 — NOT implemented |
| `check_git_diff_check` | Deferred to Phase 3 — NOT implemented |

**No contract schema changes. No CLI changes. No new verification phases.**

---

## 10. Definition of Done — Verified

| Requirement | Evidence |
|-------------|----------|
| All three Git paths use HEAD-based comparison | `git diff HEAD --name-only` and `git diff HEAD -- <path>` in all three functions |
| Staged-only modifications detected | Manual reproduction + test_staged_unexpected_modified both confirm |
| Mixed staged + unstaged detected | test_mixed_staged_unstaged_unexpected + immutable variant |
| Staged immutable modifications fail | test_immutable_file_staged_modified passes |
| Staged unexpected modifications fail | test_staged_unexpected_modified passes |
| Declared MODIFY files changed only in INDEX pass | test_declared_modify_file_staged_only passes |
| Existing tests remain green | 73/73 original tests still pass (no regressions) |
| Full test suite passes | 539/539 |
| No Phase 3 functionality | Only 6 checks in run_verification, 3 deferred |
| No production data modified | git status shows no data/ changes from this task |
| No commit created | git status shows uncommitted changes only |

---

*End of report.*
