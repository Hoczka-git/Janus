# Verification Pipeline Phase 2 — Adversarial Review

**Reviewer:** Hermes Agent (adversarial review)
**Date:** 2026-08-30
**Scope:** Phase 2 implementation — `check_files_modify`, `check_files_unexpected_modified`, `check_files_untracked`
**Method:** Independent inspection + reproduction experiments + test coverage analysis

---

## 1. VERDICT

**FAIL — Phase 2 has blocking defects.**

The implementation passes all 73 tests, but those tests do not exercise the most critical behavioral gap: the use of `git diff --name-only` (working tree vs index) as the detection baseline instead of `git diff HEAD --name-only` (working tree vs HEAD).

Reproduction experiments confirm:

1. **Staged-only modifications are invisible** to all three Phase 2 checks.
2. **check_files_immutable** fails to detect staged modifications to immutable files.
3. **check_files_unexpected_modified** fails to detect staged unexpected modifications.
4. **check_files_modify** fails to detect a file that was modified AND staged (true negative).

These are not edge cases — they represent the normal Git workflow of `git add` followed by verification before commit.

---

## 2. Executive Summary

The Phase 2 implementation contains a **fundamental semantic error** in its Git baseline selection. All three new checks rely on `_git_tracked_modified_files()` which uses:

```python
subprocess.run(["git", "diff", "--name-only"], cwd=str(root), ...)
```

This command compares the **working tree against the INDEX (staging area)**. In Git terminology:

- `git diff` → working tree vs index (unstaged changes only)
- `git diff --cached` → index vs HEAD (staged changes only)
- `git diff HEAD` → working tree vs HEAD (staged + unstaged)

The implementation intends to detect "files that have been modified" — which conceptually means "files that differ from the committed state (HEAD)." But the actual check only detects files that differ from the index, missing any changes that have been `git add`-ed but not further modified.

This causes **false negatives** in all three Phase 2 checks when files are staged.

Additionally, the tests all use the pattern: modify file → run check (no `git add` in between). This means every test exercises only the unstaged code path. The staged code path is entirely untested.

---

## 3. Actual Implementation Inspected

### Files Read

| File | Lines | Bytes |
|------|-------|-------|
| `src/janus/verification.py` | 819 | 29,089 |
| `tests/test_verification_phase1.py` | 1,602 | 74,097 |
| `docs/verification_pipeline_mvp_spec.md` | 474 | 26,041 |
| `docs/phase2_evidence_report.md` | 184 | 7,014 |

### Key Implementation Functions

```python
# _git_tracked_modified_files (line 407-430)
# Uses: git diff --name-only
# Returns: set of relative paths
# Semantically: working tree vs INDEX (unstaged only)

# _git_untracked_files (line 433-456)
# Uses: git ls-files --others --exclude-standard
# Returns: set of untracked files (excludes ignored)
# Semantically: CORRECT

# _git_is_tracked (line 459-471)
# Uses: git ls-files --error-unmatch <path>
# Returns: True if file is in git index
# Semantically: CORRECT

# _git_has_diff (line 474-486)
# Uses: git diff -- <path>
# Returns: True if working tree differs from INDEX for <path>
# Semantically: working tree vs INDEX (unstaged only)

# check_files_modify (line 489-530)
# Logic: exists() AND is_tracked() AND has_diff()
# uses _git_has_diff → working tree vs INDEX

# check_files_unexpected_modified (line 533-572)
# Logic: modified_tracked - allowed_paths
# uses _git_tracked_modified_files → working tree vs INDEX

# check_files_immutable (line 630-668)
# Logic: git diff -- <path> is empty
# uses direct subprocess, not _git_has_diff
# but same semantics: working tree vs INDEX
```

---

## 4. Baseline Semantics Analysis

### 4.1 What Does the Implementation Consider "Modified"?

The implementation uses `git diff --name-only` (working tree vs index) and `git diff -- <path>` (working tree vs index for a specific path).

**Answer to the critical questions:**

| Question | Answer |
|----------|--------|
| Does it detect unstaged changes? | **YES** — `git diff --name-only` shows unstaged changes |
| Does it detect staged changes? | **NO** — `git diff --name-only` does NOT show staged-only changes |
| Does it detect both? | **NO** — only unstaged |
| What happens if a file is modified then staged? | **FALSE NEGATIVE** — check sees no modification |
| What happens if a file has both staged and unstaged modifications? | **PARTIAL** — only unstaged visible; staged invisible |
| What baseline is used? | **INDEX (staging area)**, not HEAD, not working tree |
| Is behavior consistent across checks? | **YES** — all three use the same wrong baseline |

### 4.2 Why This Is Wrong

The contract model says:
- `files.modify` — files that MUST be modified from their committed state
- `files.immutable` — files that MUST NOT be modified from their committed state
- "unexpected modified" — files modified from their committed state that aren't declared

All three concepts reference the **committed state (HEAD)** as the baseline. The implementation uses **INDEX** as the baseline instead.

### 4.3 The Specific Failure Paths

#### Path 1: `git add` after modification

```
HEAD:  "# original\n"
Index: "# original\n# modified\n"  (after git add)
Working tree: "# original\n# modified\n"  (matches index)

git diff --name-only → empty (working tree == index)
git diff HEAD --name-only → "src/existing.py" (working tree != HEAD)
```

The implementation sees `empty` → reports "NOT MODIFIED"
The correct check should see the file differs from HEAD → report "modified"

#### Path 2: Immutable file modified and staged

```
HEAD: "# Goals\n\n- Goal 1\n"
Index: "# Goals\n\n- Goal 1\n- Goal 2\n"  (after git add)
Working tree: "# Goals\n\n- Goal 1\n- Goal 2\n"  (matches index)

git diff -- data/goals.md → empty (working tree == index)
git diff --cached -- data/goals.md → shows diff (index != HEAD)
```

The implementation sees `empty` → reports "PASS" (no diff)
The correct check should see the file differs from HEAD → report "FAIL"

---

## 5. Finding Table

### Finding F1: Staged modifications not detected (BLOCKING)

| Field | Value |
|-------|-------|
| **ID** | F1 |
| **Severity** | **Blocking** |
| **Location** | `src/janus/verification.py` lines 407-430 (`_git_tracked_modified_files`), line 474-486 (`_git_has_diff`) |
| **Evidence** | Reproduction experiments TEST A, TEST B, TEST C, TEST D, TEST E |
| **Reproduction** | 1. Create git repo with initial commit<br>2. Modify a tracked file<br>3. `git add` the file (stage it)<br>4. Run `check_files_modify` / `check_files_unexpected_modified` / `check_files_immutable`<br>5. All three checks fail to detect the staged modification |
| **Expected behavior** | All three checks should detect modifications relative to HEAD (committed state), regardless of staging |
| **Actual behavior** | Only unstaged modifications detected; staged modifications invisible |
| **Recommended fix** | Replace `git diff --name-only` with `git diff HEAD --name-only` in `_git_tracked_modified_files()`. Replace `git diff -- <path>` with `git diff HEAD -- <path>` in `_git_has_diff()` and `check_files_immutable()` |

---

### Finding F2: check_files_immutable baseline wrong (BLOCKING)

| Field | Value |
|-------|-------|
| **ID** | F2 |
| **Severity** | **Blocking** |
| **Location** | `src/janus/verification.py` lines 648-661 (`check_files_immutable`) |
| **Evidence** | Reproduction experiment TEST C |
| **Reproduction** | 1. Create git repo, commit immutable file<br>2. Modify the file and `git add` it (stage)<br>3. Run `check_files_immutable`<br>4. Check returns PASS (empty diff) when it should FAIL |
| **Expected behavior** | Immutable file modified in index → FAIL |
| **Actual behavior** | PASS — `git diff -- <path>` compares working tree vs index, both match |
| **Recommended fix** | Use `git diff HEAD -- <path>` instead of `git diff -- <path>` |

---

### Finding F3: Staged unexpected modifications not detected (BLOCKING)

| Field | Value |
|-------|-------|
| **ID** | F3 |
| **Severity** | **Blocking** |
| **Location** | `src/janus/verification.py` lines 533-572 (`check_files_unexpected_modified`) |
| **Evidence** | Reproduction experiment TEST B |
| **Reproduction** | 1. Create repo with file a.py and b.py committed<br>2. Modify b.py (not in contract) and `git add` it<br>3. Run `check_files_unexpected_modified`<br>4. Returns PASS when it should FAIL |
| **Expected behavior** | b.py modified → FAIL reported |
| **Actual behavior** | PASS — staged modification invisible to `_git_tracked_modified_files()` |
| **Recommended fix** | Same as F1 — use `git diff HEAD --name-only` |

---

### Finding F4: check_files_modify fails for staged modify (BLOCKING)

| Field | Value |
|-------|-------|
| **ID** | F4 |
| **Severity** | **Blocking** |
| **Location** | `src/janus/verification.py` lines 489-530 (`check_files_modify`) |
| **Evidence** | Reproduction experiment TEST A |
| **Reproduction** | 1. Create repo, commit file<br>2. Modify file and `git add` it<br>3. Run `check_files_modify` with contract declaring that file as MODIFY<br>4. Returns FAIL "NOT MODIFIED (no diff)" — should PASS |
| **Expected behavior** | File is modified vs HEAD → PASS |
| **Actual behavior** | File matches index → FAIL (false negative) |
| **Recommended fix** | Same as F1 — use `git diff HEAD -- <path>` via `_git_has_diff()` |

---

### Finding F5: Tests don't cover staged modifications (BLOCKING)

| Field | Value |
|-------|-------|
| **ID** | F5 |
| **Severity** | **Blocking** |
| **Location** | `tests/test_verification_phase1.py` — all Phase 2 tests |
| **Evidence** | Code review of all 16 Phase 2 tests + reproduction |
| **Reproduction** | Every Phase 2 test follows: modify file → run check (NO `git add` between). Zero tests call `git add` before running a check. |
| **Expected behavior** | Tests should cover: staged-only modifications, mixed staged+unstaged, staged immutable violations |
| **Actual behavior** | All tests only exercise the unstaged code path. The staged code path is entirely untested. |
| **Recommended fix** | Add tests that stage modifications before running checks. At minimum: test_check_files_modify_with_staged_file, test_check_files_immutable_with_staged_modification, test_check_files_unexpected_modified_with_staged_file |

---

### Finding F6: No tests for deletions (HIGH)

| Field | Value |
|-------|-------|
| **ID** | F6 |
| **Severity** | **High** |
| **Location** | `tests/test_verification_phase1.py` |
| **Evidence** | Test inventory — no test deletes a tracked file |
| **Reproduction** | N/A — tests don't cover this scenario |
| **Expected behavior** | check_files_modify should FAIL for deleted file (file doesn't exist). check_files_unexpected_modified should detect deleted tracked files depending on contract semantics. |
| **Actual behavior** | Unknown — no test covers deletion |
| **Recommended fix** | Add test for deletion: file in MODIFY contract, file deleted from disk → should FAIL. File NOT in any contract, tracked file deleted → unclear if this should be "unexpected modification" |

---

### Finding F7: No tests for renames (HIGH)

| Field | Value |
|-------|-------|
| **ID** | F7 |
| **Severity** | **High** |
| **Location** | `tests/test_verification_phase1.py` |
| **Evidence** | Test inventory — no test renames a tracked file |
| **Expected behavior** | Renamed file: old name still tracked (as deletion), new name untracked. Contract declaring old name as MODIFY should FAIL (file doesn't exist at that path). Contract declaring old name as immutable → old name shows as deleted in diff? |
| **Actual behavior** | Unknown |
| **Recommended fix** | Add test for rename scenario. Document intended behavior for renames (are they "modifications"?). |

---

### Finding F8: Mixed staged + unstaged — partial detection (MEDIUM)

| Field | Value |
|-------|-------|
| **ID** | F8 |
| **Severity** | **Medium** |
| **Location** | `src/janus/verification.py` |
| **Evidence** | Reproduction experiment TEST D |
| **Reproduction** | File has both staged v2 and unstaged v3. check_files_modify PASSES because v3 is detected. But if v3 were reverted, only v2 remains and check would FAIL. |
| **Expected behavior** | File is modified vs HEAD (both staged and unstaged count) → should detect as modified regardless of staging state |
| **Actual behavior** | Only unstaged v3 detected. Staged v2 invisible. Check "works" only because there's also an unstaged change. |
| **Recommended fix** | Same as F1 — baseline should be HEAD, not index |

---

### Finding F9: No tests for repository without HEAD (MEDIUM)

| Field | Value |
|-------|-------|
| **ID** | F9 |
| **Severity** | **Medium** |
| **Location** | `tests/test_verification_phase1.py` |
| **Evidence** | One test (`test_phase2_no_git_repo_graceful`) tests no git repo at all, but no test tests a repo with `git init` but no initial commit |
| **Expected behavior** | With no HEAD, `git diff HEAD` fails. Behavior should be documented and tested. Current implementation: `git diff --name-only` returns empty set (working tree vs empty index = nothing). This means no modifications detected → potentially wrong. |
| **Actual behavior** | `git diff --name-only` returns empty when no commits exist (tested in TEST 8). Files added to index but not committed are not detected as modified. |
| **Recommended fix** | Document behavior for repos without commits. May need special handling. |

---

### Finding F10: Missing files declared as MODIFY not handled by unexpected_modified (LOW)

| Field | Value |
|-------|-------|
| **ID** | F10 |
| **Severity** | **Low** |
| **Location** | `src/janus/verification.py` lines 533-572 |
| **Evidence** | Code review |
| **Expected behavior** | If a file is declared in MODIFY but doesn't exist on disk, check_files_modify catches it (MISSING). But what if a tracked file is deleted? It shows in `git diff --name-only` as modified. If not in contract, it would be flagged as unexpected. If in MODIFY contract but deleted → check_files_modify FAILS (MISSING) AND it appears in unexpected_modified? No — it's in allowed_paths so not flagged as unexpected. But the overall result is confusing: MODIFY says "this file should be modified" but it's deleted. |
| **Actual behavior** | check_files_modify reports MISSING. check_files_unexpected_modified doesn't flag it (it's in allowed_paths). The two checks are consistent but the semantics are odd. |
| **Recommended fix** | Document behavior. Consider whether deleted files declared as MODIFY should be a distinct failure type. |

---

### Finding F11: check_files_untracked — no test for ignored files in mixed scenario (LOW)

| Field | Value |
|-------|-------|
| **ID** | F11 |
| **Severity** | **Low** |
| **Location** | `tests/test_verification_phase1.py` |
| **Evidence** | Test inventory |
| **Expected behavior** | Ignored files (e.g., *.pyc, __pycache__) should NOT appear as unexpected untracked. The implementation correctly uses `git ls-files --others --exclude-standard` which respects .gitignore. But no test covers this in a mixed scenario with other untracked files. |
| **Actual behavior** | Implementation is correct (uses --exclude-standard). Verifier test for git helpers confirms ignored files excluded. |
| **Recommended fix** | Optional: add explicit test for ignored files in mixed scenario for documentation. |

---

## 6. Git State Matrix

| Scenario | Unstaged | Staged | Detected by `git diff --name-only` (current impl) | Detected by `git diff HEAD --name-only` (correct) | Expected behavior |
|----------|----------|--------|-----------------------------------------------------|-----------------------------------------------------|-------------------|
| Normal modification | ✓ change | — | ✓ detected | ✓ detected | Detect as modified |
| Staged modification | — | ✓ change | ✗ NOT detected | ✓ detected | **Must** detect as modified |
| Mixed staged + unstaged | ✓ v3 | ✓ v2 | ✓ detects v3 only | ✓ detects both | Detect as modified (both count) |
| Deletion | ✓ deletion | — | ✓ detected (as delete) | ✓ detected | Depends on contract |
| Rename (git mv) | — | — | ✓ old as delete, new as untracked? | ✓ | Depends on contract |
| Rename (manual mv) | ✓ delete old | — | ✓ old as delete | ✓ old as delete | Old = deletion, new = untracked |
| MODIFY file, unchanged | — | — | ✗ not in diff | ✗ not in diff | Should FAIL (not modified) |
| MODIFY file, staged | — | ✓ change | ✗ NOT detected | ✓ detected | Should PASS (modified) — **BUG** |
| MODIFY file, deleted | ✓ deletion | — | ✓ detected | ✓ detected | Should FAIL (missing) |
| Immutable file, unstaged mod | ✓ change | — | ✓ detected | ✓ detected | Should FAIL — works correctly |
| Immutable file, staged mod | — | ✓ change | ✗ NOT detected | ✓ detected | Should FAIL — **BUG** |
| Unrelated file, unstaged | ✓ change | — | ✓ detected | ✓ detected | Should FAIL (unexpected) — works |
| Unrelated file, staged | — | ✓ change | ✗ NOT detected | ✓ detected | Should FAIL — **BUG** |

---

## 7. Check Interaction Analysis

### Case A: Contract: create: - new.py. Actual: new.py exists and is untracked

| Check | Expected | Actual (with implementation) |
|-------|----------|------------------------------|
| check_files_create | PASS (exists) | PASS |
| check_files_untracked | PASS (expected CREATE) | PASS |
| **Result** | **Consistent** | **Consistent** |

### Case B: Contract: modify: - existing.py. Actual: existing.py unchanged

| Check | Expected | Actual (with implementation) |
|-------|----------|------------------------------|
| check_files_modify | FAIL (not modified) | FAIL (NOT MODIFIED) |
| check_files_unexpected_modified | PASS (not modified, so not unexpected) | PASS |
| **Result** | **Consistent** | **Consistent** |

### Case C: Contract: modify: - existing.py. Actual: existing.py staged (modified + git add)

| Check | Expected | Actual (with implementation) |
|-------|----------|------------------------------|
| check_files_modify | PASS (modified vs HEAD) | **FAIL (NOT MODIFIED) — WRONG** |
| check_files_unexpected_modified | PASS (declared in modify) | PASS (not in modified_tracked, so not unexpected) |
| **Result** | **Should be consistent** | **Inconsistent: modify says FAIL, unexpected says PASS for same file** |

This is the most dangerous interaction: the two checks give contradictory results for the same file.

### Case D: Contract: immutable: - config.py. Actual: config.py staged modified

| Check | Expected | Actual (with implementation) |
|-------|----------|------------------------------|
| check_files_immutable | FAIL (modified) | **PASS (empty diff) — WRONG** |
| check_files_unexpected_modified | FAIL (modified, not in allowed) | **PASS (not in modified_tracked) — WRONG** |
| **Result** | **Should be FAIL** | **Both incorrectly PASS** |

### Case E: Actual: unrelated.py modified (unstaged). No contract entries.

| Check | Expected | Actual |
|-------|----------|--------|
| check_files_unexpected_modified | FAIL | FAIL |
| **Result** | **Consistent** | **Consistent** |

### Case F: Actual: tmp/debug.py untracked. Not in CREATE.

| Check | Expected | Actual |
|-------|----------|--------|
| check_files_untracked | FAIL | FAIL |
| **Result** | **Consistent** | **Consistent** |

### Interaction Summary

The checks are **consistent for unstaged changes** but **contradictory for staged changes**. The contradiction is: `check_files_modify` says a staged file is NOT modified, while `check_files_unexpected_modified` says the same staged file is NOT unexpected (because it's not in the modified set). This creates a state where a file could be declared MODIFY, actually modified and staged, and both checks would disagree about its status — one says "not modified" (FAIL), the other says "not unexpected" (PASS).

---

## 8. Test Coverage Gaps

| Gap | Severity | Description |
|-----|----------|-------------|
| Staged modifications | **Blocking** | Zero tests call `git add` before running a check. The entire staged code path is untested. |
| Mixed staged + unstaged | **Blocking** | No test creates a file with both staged and unstaged changes. |
| Deletions | **High** | No test deletes a tracked file. Behavior for deleted files in MODIFY/immutable/untracked checks unknown. |
| Renames | **High** | No test renames a tracked file. Git rename detection and how checks handle it untested. |
| Repository without HEAD | **Medium** | `test_phase2_no_git_repo_graceful` tests no repo at all, but no test for repo with `git init` and no commit. |
| Immutable file deleted | **Medium** | Immutable file deleted from disk — exists() check fails, but what should the result be? |
| MODIFY file deleted | **Medium** | File declared MODIFY but deleted — check_files_modify catches MISSING, but interaction with unexpected_modified unclear. |
| Empty repo, files in index | **Low** | Files added to index but no commit — current impl returns empty for all modification checks. |

### Classification of the 73 passing tests

The 73 passing tests cover:
- Contract loading: ✓ thorough
- CheckResult/VerificationReport: ✓ thorough
- check_files_create: ✓ thorough
- check_files_immutable: ✗ missing staged modification case
- check_commands: ✓ thorough
- check_files_modify: ✗ missing staged modification, deletion, rename
- check_files_unexpected_modified: ✗ missing staged modification
- check_files_untracked: ✓ mostly thorough (missing ignored files in mixed case)
- Git helpers: ✓ for unstaged behavior only
- Integration: ✗ all use unstaged-only scenarios

**A test suite with 73 passing tests has critical blind spots in the staged-modification path.**

---

## 9. Temporary Repository Test Validity

### What the tests do correctly

- Each test creates an isolated temporary directory via `tmp_path` pytest fixture
- Git is initialized with `git init -q`
- Git user.name and user.email are configured deterministically (`Test` / `test@test.com`)
- An initial commit is created before tests run
- Tests use `subprocess.run` with `capture_output=True` — real git commands, not mocks

### What the tests miss

- **No test exercises the staged code path.** Every test modifies a file and immediately runs the check. The `git add` step is missing.
- **Tests accidentally test only the unstaged path** — this is why all 73 tests pass despite the implementation bug. The tests validate that unstaged modifications work, but say nothing about staged modifications.
- **All temporary repos have an initial commit** — this is correct and matches the real Janus repository state. Good.

### Are tests accidentally inspecting the real repo?

No. The `tmp_path` fixture creates a fresh temporary directory for each test. The `cwd` parameter is explicitly set for all git commands. There's no leakage.

---

## 10. Recommended Fixes

### Blocking (must fix before Phase 3)

1. **F1/F2/F3/F4 — Fix the Git baseline**
   - In `_git_tracked_modified_files()`: change `git diff --name-only` to `git diff HEAD --name-only`
   - In `_git_has_diff()`: change `git diff -- <path>` to `git diff HEAD -- <path>`
   - In `check_files_immutable()`: change `git diff -- <path>` to `git diff HEAD -- <path>`
   - Update docstrings to state the baseline is HEAD

2. **F5 — Add staged modification tests**
   - `test_check_files_modify_with_staged_file`: modify + git add → should PASS
   - `test_check_files_immutable_with_staged_modification`: modify + git add → should FAIL
   - `test_check_files_unexpected_modified_with_staged_file`: modify + git add → should FAIL
   - `test_check_files_modify_mixed_staged_unstaged`: both staged and unstaged → should PASS

### Important (should fix)

3. **F6 — Add deletion tests**
   - `test_check_files_modify_deleted_file`: file in MODIFY, deleted → FAIL (MISSING)
   - `test_check_files_immutable_deleted_file`: immutable file deleted → ? (document behavior)
   - `test_check_files_unexpected_modified_deleted_file`: tracked file deleted, not in contract → ? (document behavior)

4. **F7 — Add rename tests**
   - `test_check_files_modify_renamed_file`: file renamed, old name in MODIFY → FAIL
   - Document intended behavior for renames

### Optional (nice to have)

5. **F9 — Test repository without commits**
   - Document and test behavior when `git diff HEAD` fails (no HEAD)

6. **F11 — Explicit ignored files test**
   - Add test ensuring .gitignore respected in mixed untracked scenario

---

## 11. Final Recommendation

**Phase 2 requires a fix before Phase 3.**

The implementation has a **fundamental baseline error** that causes all three Phase 2 checks to miss staged modifications. This is not a minor edge case — it's the difference between detecting a modification and not detecting it, and the normal Git workflow involves `git add` before verification.

The fix is small (change 3 Git command invocations), but it must be accompanied by tests that exercise the staged code path. Without those tests, the same bug could be reintroduced silently.

**Specific recommendation:**

1. Fix the baseline: `git diff --name-only` → `git diff HEAD --name-only`, `git diff -- <path>` → `git diff HEAD -- <path>`
2. Add 4-6 tests covering staged modifications, mixed staged+unstaged, deletions
3. Re-run full test suite to verify no regressions
4. Then proceed to Phase 3

---

## Appendix A: Reproduction Experiment Summary

All experiments used temporary directories (not the real Janus repo). Key results:

| Experiment | Result |
|------------|--------|
| Unstaged modification detected | ✓ Confirmed |
| Staged-only modification NOT detected | ✗ BUG CONFIRMED |
| Mixed staged+unstaged: only unstaged seen | ✗ BUG CONFIRMED |
| Deletion detected by `git diff --name-only` | ✓ Confirmed |
| Rename: old=tracked deleted, new=untracked | ✓ Confirmed |
| Expected CREATE untracked: correctly allowed | ✓ Confirmed |
| Ignored files excluded by ls-files --others --exclude-standard | ✓ Confirmed |
| No git repo: empty sets returned gracefully | ✓ Confirmed |
| No initial commit: `git diff --name-only` returns empty | ✓ Confirmed (potential issue) |

---

## Appendix B: Git Command Semantics Reference

```
git diff                          → working tree vs INDEX (unstaged changes)
git diff --cached                 → INDEX vs HEAD (staged changes)
git diff HEAD                     → working tree vs HEAD (all changes)
git diff -- <path>               → working tree vs INDEX for <path>
git diff --cached -- <path>      → INDEX vs HEAD for <path>
git diff HEAD -- <path>          → working tree vs HEAD for <path>
git ls-files --others --exclude-standard → untracked files (excludes ignored)
git ls-files --error-unmatch <path>     → exits 0 if path is tracked
```

The current implementation uses the first and fourth forms. It should use the third and sixth forms to compare against HEAD.

---

*End of review document.*
