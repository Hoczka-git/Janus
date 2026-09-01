# Verification Phase 2.1 — Adversarial Re-Review

**Reviewer:** Hermes Agent (adversarial re-review)
**Date:** 2026-08-30
**Scope:** Git baseline fix verification — `git diff HEAD` vs `git diff`
**Method:** Independent reproduction + code inspection + test adequacy analysis

---

## 1. VERDICT

**PASS — Phase 2.1 correctly closes all blocking defects.**

The implementation now uses HEAD-based Git comparison (`git diff HEAD`) in all three affected functions. Independent reproduction confirms all four Git states (clean, unstaged, staged-only, mixed) are correctly detected. The new tests genuinely exercise the staged code path, would have failed under the old implementation, and no regressions are introduced.

---

## 2. Summary of Previous Phase 2 Blocking Defects

The Phase 2 adversarial review (`docs/verification_pipeline_phase2_review.md`) identified four blocking defects:

| Finding | Defect |
|---------|--------|
| F1 | `_git_tracked_modified_files()` uses `git diff --name-only` (index-based) → staged-only modifications invisible |
| F2 | `check_files_immutable()` uses `git diff -- <path>` (index-based) → staged immutable violations pass |
| F3 | `check_files_unexpected_modified()` uses index-based detection → staged unexpected modifications pass |
| F4 | No tests cover staged modifications — entire staged code path untested |

The Phase 2.1 implementation report claims all four were fixed by changing three Git commands to use `HEAD` baseline.

---

## 3. Independent Git State Matrix

Created temporary Git repository outside the project and independently verified all four states:

| Git State | HEAD vs INDEX | INDEX vs WORKTREE | `_git_tracked_modified_files()` (new impl) | Expected | Correct? |
|-----------|---------------|-------------------|---------------------------------------------|----------|----------|
| **Clean** | HEAD == INDEX | INDEX == WORKTREE | `set()` (empty) | empty set | ✓ |
| **Unstaged** | HEAD == INDEX | INDEX != WORKTREE | `{'src/foo.py'}` | `{'src/foo.py'}` | ✓ |
| **Staged-only** | HEAD != INDEX | INDEX == WORKTREE | `{'src/foo.py'}` | `{'src/foo.py'}` | ✓ |
| **Mixed** | HEAD != INDEX | INDEX != WORKTREE | `{'src/foo.py'}` | `{'src/foo.py'}` | ✓ |

**Critical finding — State 3 (Staged-only):**

```
git diff --name-only (old impl):          ''
git diff HEAD --name-only (new impl):     'src/foo.py'
git diff --cached --name-only:            'src/foo.py'

_git_tracked_modified_files:              {'src/foo.py'}  ← CORRECT
```

The old implementation returned empty for staged-only state. The new implementation correctly detects it.

---

## 4. Per-Function Analysis

### 4.1 `_git_tracked_modified_files()` (line 407-431)

```python
["git", "diff", "HEAD", "--name-only"]
```

**Correct.** Uses `git diff HEAD` which compares working tree + index against HEAD. Detects both staged and unstaged changes.

**Independent verification:** All four Git states produce correct output (see §3).

---

### 4.2 `_git_has_diff()` (line 475-491)

```python
["git", "diff", "HEAD", "--", rel_path]
```

**Correct.** Uses `git diff HEAD -- <path>` which compares the given path against HEAD. The `--` separator ensures the path is treated as a file path, not a revision. Works correctly with relative paths (which is what the contract uses throughout).

**Path handling:** `rel_path` is a string like `"src/foo.py"`. Git handles paths with spaces correctly when separated by `--`. No path-related bug identified.

---

### 4.3 `check_files_modify()` (line 494-535)

Delegates to `_git_has_diff()` which uses HEAD baseline.

**Logic:**
1. Check file exists → `full_path.exists()`
2. Check file is tracked → `_git_is_tracked()`
3. Check file differs from HEAD → `_git_has_diff()` (now HEAD-based)

**Correct.** A staged-only MODIFY file now correctly passes (detected as modified vs HEAD).

---

### 4.4 `check_files_immutable()` (line 635-673)

```python
["git", "diff", "HEAD", "--", str(full_path)]
```

**Correct.** Uses HEAD baseline. A staged-only modification to an immutable file now correctly fails.

**Independent verification:** Test `test_immutable_file_staged_modified` passes — staged immutable violation correctly detected.

---

### 4.5 `check_files_unexpected_modified()` (line 538-577)

Delegates to `_git_tracked_modified_files()` which uses HEAD baseline.

**Correct.** Staged-only unexpected modifications now correctly detected.

**Independent verification:** Test `test_staged_unexpected_modified` passes — staged unexpected correctly fails.

---

## 5. Remaining Blind Spots Search

Searched `src/janus/verification.py` for any remaining `git diff` usage without explicit `HEAD` baseline:

```
Line  8:  "git_diff_check" — comment about deferred Phase 3 check (NOT a baseline issue)
Line 165: "git diff matching" — comment for path conversion function (NOT a git command)
Line 410: "git diff HEAD --name-only" — docstring (CORRECT)
Line 416: ["git", "diff", "HEAD", "--name-only"] — actual command (CORRECT)
Line 475: "git diff HEAD -- <path>" — docstring (CORRECT)
Line 478: "git diff HEAD -- <path>" — docstring (CORRECT)
Line 483: ["git", "diff", "HEAD", "--", rel_path] — actual command (CORRECT)
Line 500: "git diff (staged or unstaged changes vs HEAD)" — comment (CORRECT)
Line 528: _git_has_diff(contract.root, rel_path) — call to fixed function (CORRECT)
Line 636: "git diff" — docstring (NOT a git command)
Line 655: ["git", "diff", "HEAD", "--", str(full_path)] — actual command (CORRECT)
Line 740: "check_git_diff_check" — comment about deferred Phase 3 check (NOT a baseline issue)
```

**Finding: No remaining `git diff` usage without HEAD baseline in modification-checking logic.**

All three production Git commands now use `HEAD`. No staged-change blind spots remain in the current implementation.

---

## 6. Test Adequacy Analysis

### 6.1 Do the new tests create genuine staged states?

All 7 new tests use `subprocess.run(["git", "add", ...])` to create staged states. Independent verification confirms:

| Test | Creates staged state? | Would old impl fail? |
|------|----------------------|---------------------|
| `test_declared_modify_file_staged_only` | Yes — `git add` after modification, working tree matches index | **Yes** — old impl returns empty set → `passed=False` (NOT MODIFIED) |
| `test_declared_modify_file_mixed_staged_unstaged` | Yes — stage v2, then add v3 unstaged | **No** — old impl sees v3 (unstaged) → passes accidentally |
| `test_declared_modify_file_staged_then_reverted` | Yes — stage, then `git checkout --` to revert working tree | **Yes** — old impl returns empty (index==worktree) → `passed=False` |
| `test_immutable_file_staged_modified` | Yes — `git add` after modification | **Yes** — old impl returns empty → `passed=True` (should be FAIL) |
| `test_immutable_file_mixed_staged_unstaged` | Yes — stage + unstaged | **No** — old impl sees unstaged → fails anyway |
| `test_staged_unexpected_modified` | Yes — `git add` after modification | **Yes** — old impl returns empty → `passed=True` (should be FAIL) |
| `test_mixed_staged_unstaged_unexpected` | Yes — stage + unstaged | **No** — old impl sees unstaged → fails anyway |

**3 of 7 new tests would have FAILED under the old implementation** — these genuinely exercise the staged code path that was previously invisible.

**4 of 7 new tests pass under both old and new implementations** — these test mixed states where unstaged changes exist and would have been detected by the old implementation. They still add value by explicitly testing mixed states.

### 6.2 False-positive tests?

**No false-positive tests identified.** All 7 new tests:
- Require HEAD-based detection to pass (for staged-only tests)
- Require detection of staged changes (for immutable/unexpected failure tests)
- Actually create staged states via `git add`

---

## 7. Regression Check

Verified that HEAD-based comparison does not introduce incorrect behavior for:

### 7.1 Untracked files
**Not affected.** `_git_untracked_files()` uses `git ls-files --others --exclude-standard`, independent of HEAD.

### 7.2 Files that do not exist
**Not affected.** `check_files_modify()` checks `exists()` BEFORE calling `_git_has_diff()`. Missing files still fail with "MISSING" message.

### 7.3 Clean tracked files
**Not affected.** HEAD == INDEX == WORKTREE → `git diff HEAD` returns empty → correct.

### 7.4 Already committed files
**Not affected.** HEAD == INDEX == WORKTREE → `git diff HEAD` returns empty → correct.

### 7.5 Existing tests still pass
**Confirmed.** 73/73 original tests pass (no regressions). Full suite: 539/539.

---

## 8. Scope Compliance

| Constraint | Status |
|------------|--------|
| No implementation changes beyond baseline fix | ✓ Only 3 Git commands changed |
| No test changes beyond 7 new tests | ✓ No existing tests modified |
| No Phase 3 work | ✓ `check_symbols_required`, `check_symbols_forbidden`, `check_git_diff_check` remain deferred |
| No commits | ✓ `git status` shows uncommitted changes only |
| No production data modified | ✓ `data/` files not touched by this task |
| No contract schema changes | ✓ Schema unchanged |
| No CLI changes | ✓ CLI unchanged |

---

## 9. Independent Reproduction Evidence

### 9.1 Complete Git state matrix reproduction

```python
# State 3 (Staged-only) — THE CRITICAL FIX
f.write_text("hello\nworld\n")
git("add", "src/foo.py", cwd=repo)

out_old, _ = git("diff", "--name-only", cwd=repo)        # → ''
out_new, _ = git("diff", "HEAD", "--name-only", cwd=repo) # → 'src/foo.py'

modified = _git_tracked_modified_files(repo)              # → {'src/foo.py'}
```

**Old implementation:** `git diff --name-only` returns empty. `_git_tracked_modified_files` returns empty set.
**New implementation:** `git diff HEAD --name-only` returns `'src/foo.py'`. `_git_tracked_modified_files` returns `{'src/foo.py'}`.

### 9.2 Full test results

```
80 passed in 4.81s (targeted verification tests)
539 passed in 5.73s (full suite)
```

All 7 new staged-modification tests pass. All 73 original tests pass. Zero regressions.

---

## 10. Final Recommendation

**Phase 2.1 is safe to close. Proceed to Phase 3.**

The implementation correctly fixes all four blocking defects:

1. ✅ `_git_tracked_modified_files()` — uses `git diff HEAD --name-only`
2. ✅ `_git_has_diff()` — uses `git diff HEAD -- <path>`
3. ✅ `check_files_immutable()` — uses `git diff HEAD -- <path>`
4. ✅ 7 new tests cover staged code path (3 would have failed under old impl)

**No remaining staged-change blind spots identified.** All `git diff` invocations in modification-checking logic now use HEAD baseline.

**Start Phase 3 when ready.**

---

*End of re-review.*
