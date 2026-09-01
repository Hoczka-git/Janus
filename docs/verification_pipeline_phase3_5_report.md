# Phase 3.5 End-to-End Validation — FAILED: Verifier Bug Discovered

**Verdict: FAIL — VERIFIER BUG DISSCOVERED (F-03)**

**Date:** 2026-08-30

---

## Summary

Phase 3.5 was designed to validate the complete existing deterministic
verification pipeline end-to-end using a realistic Goal-System-derived
contract. Before a single end-to-end scenario could run, the validation
uncovered a genuine verifier bug that breaks contract loading for any
contract using the Phase 3 AST-based `forbidden_symbols` format.

Per the frozen scope, the bug was NOT fixed during Phase 3.5. It is
documented here for a separate remediation task.

---

## Verifier Bug F-03 — FrozenInstanceError in `_parse_forbidden_symbols`

**Location:** `src/janus/verification.py`, lines 301–327

**Type:** Frozen dataclass mutation after construction

**Severity:** HIGH — blocks the entire contract loading path for any
contract that uses `forbidden_symbols` with the Phase 3 AST format.

### Expected behavior

A contract YAML such as:

```yaml
version: 1
task_id: "goal-system-mvp-validation"
forbidden_symbols:
  - symbol: "delete_goal"
    path: "src/janus/services"
    type: "function"
```

should load successfully via `ImplementationContract.load(...)`, producing
a `ForbiddenSymbolEntry` with:

- `symbol = "delete_goal"`
- `path = "src/janus/services"`
- `type = "function"`

### Actual behavior

Loading such a contract raises:

```
dataclasses.FrozenInstanceError: cannot assign to field 'symbol'
```

Traceback (most recent call last):

```
src/janus/verification.py:179: in load
    forbidden_symbols=_parse_forbidden_symbols(...),
src/janus/verification.py:319: in _parse_forbidden_symbols
    entry.symbol = symbol.strip()
```

### Root cause

`ForbiddenSymbolEntry` is declared as a frozen dataclass:

```python
@dataclass(frozen=True)
class ForbiddenSymbolEntry:
    symbol: str = ""
    path: str = ""   # optional path restriction
    type: str = ""   # "function", "class", or "" for any
```

But `_parse_forbidden_symbols` constructs an empty instance and then
attempts to mutate its fields:

```python
entry = ForbiddenSymbolEntry()       # line 316 — frozen instance
entry.symbol = symbol.strip()        # line 319 — raises FrozenInstanceError
entry.path = path.strip()            # line 322
entry.type = type_val.strip()        # line 325
```

Post-construction field assignment on a frozen dataclass is rejected by
the runtime. The bug triggers on the very first non-empty `symbol` field
encountered — i.e., any contract with a non-trivial `forbidden_symbols`
section.

### Minimal reproduction

```python
from janus.verification import ImplementationContract

contract = ImplementationContract.load("contract.yaml")
# where contract.yaml contains:
#
# version: 1
# task_id: "repro"
# forbidden_symbols:
#   - symbol: "delete_goal"
#     path: "src/janus/services"
#     type: "function"
```

Result: `FrozenInstanceError` at line 319.

A contract without `forbidden_symbols`, or with an empty list, loads
without error. The crash is specific to the Phase 3 AST-based
`forbidden_symbols` format.

### Why existing tests missed it

- Every existing Phase 3 test in `tests/test_verification_phase1.py`
  constructs `ForbiddenSymbolEntry` **directly via the constructor**, never
  through the YAML contract loader:

  ```python
  ForbiddenSymbolEntry(symbol="BadClass", type="")
  ```

- No existing test exercises `ImplementationContract.load()` with a
  `forbidden_symbols` section that contains `path` or `type` fields.
- The only contract YAML shipped in the repository
  (`docs/examples/contract_phase1.yaml`) uses the legacy regex string
  format:

  ```yaml
  forbidden_symbols:
    - "\bdelete_goal\b"
  ```

  which is parsed by `_parse_forbidden_list`, not
  `_parse_forbidden_symbols`.
- The `_parse_forbidden_symbols` function was added during Phase 3 but
  was never covered by an end-to-end contract-loading test.

### Recommended fix (for remediation task)

Construct the entry with all fields at creation time, matching the pattern
already used successfully by `_parse_symbol_list`, `_parse_file_list`, and
`_parse_forbidden_list`:

```python
def _parse_forbidden_symbols(raw: Any) -> list[ForbiddenSymbolEntry]:
    if not isinstance(raw, list):
        return []
    result = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        symbol = item.get("symbol", "")
        path = item.get("path", "")
        type_val = item.get("type", "")
        if isinstance(symbol, str) and symbol.strip():
            result.append(ForbiddenSymbolEntry(
                symbol=symbol.strip(),
                path=path.strip() if isinstance(path, str) else "",
                type=type_val.strip() if isinstance(type_val, str) else "",
            ))
    return result
```

---

## Impact on Phase 3.5 Validation

Because the bug breaks `ImplementationContract.load()` for any contract
using `forbidden_symbols`, the complete end-to-end validation scenarios
cannot run through the real `run_verification()` path. All 22 Phase 3.5
scenarios that rely on `realistic_contract()` fail at contract load time
with the same `FrozenInstanceError`.

The single passing test (`test_existing_phase_tests_still_pass`) only
asserts that the verifier module exports the expected symbols — it does not
exercise contract loading or any verification check.

---

## Files Created During Phase 3.5

| File | Purpose |
|------|---------|
| `tests/test_verification_phase3_5.py` | End-to-end validation test suite (23 tests) |
| `docs/verification_pipeline_phase3_5_report.md` | This validation report |
| `docs/verification_pipeline_phase3_5_findings.md` | Finding F-03 detail |

## Test Results

| Suite | Result |
|-------|--------|
| Phase 3.5 targeted tests | **1/23 passed, 22 failed** |
| Existing verification tests | NOT EXECUTED (blocked by verifier bug) |
| Full test suite | NOT EXECUTED (blocked by verifier bug) |
| `git diff --check` | NOT RUN (no production changes to check) |
| `git status` | 3 untracked files (tests + 2 docs) |

**Failure breakdown:** All 22 failed scenarios fail with the same
`FrozenInstanceError` at contract load time. No scenario reached any
verification check.

### Detailed failure matrix (blocked by verifier bug)

| # | Scenario | Expected | Actual | Status |
|---|----------|----------|--------|--------|
| 1 | Missing CREATE file | FAIL | Blocked by F-03 | — |
| 2 | Unchanged MODIFY file | FAIL | Blocked by F-03 | — |
| 3a | Unstaged IMMUTABLE modification | FAIL | Blocked by F-03 | — |
| 3b | Staged IMMUTABLE modification | FAIL | Blocked by F-03 | — |
| 4 | Unexpected tracked modification | FAIL | Blocked by F-03 | — |
| 5 | Unexpected untracked file | FAIL | Blocked by F-03 | — |
| 6 | Missing required symbol | FAIL | Blocked by F-03 | — |
| 7 | Wrong required symbol type | FAIL | Blocked by F-03 | — |
| 8 | Forbidden symbol present | FAIL | Blocked by F-03 | — |
| 9 | Forbidden in comment only | PASS (no trigger) | Blocked by F-03 | — |
| 10 | Forbidden in string only | PASS (no trigger) | Blocked by F-03 | — |
| 11 | Unstaged whitespace error | FAIL | Blocked by F-03 | — |
| 12 | Staged whitespace error | FAIL | Blocked by F-03 | — |
| 13 | Verification command failure | FAIL | Blocked by F-03 | — |
| A | Multiple simultaneous failures | FAIL | Blocked by F-03 | — |
| B | Expected CREATE untracked allowed | PASS | Blocked by F-03 | — |
| C | Mixed staged + unstaged | PASS | Blocked by F-03 | — |
| — | Complete valid PASS scenario | PASS | Blocked by F-03 | — |

---

## Confirmations

- **No real repository files were used as mutation targets.** All Git
  mutations occurred inside temporary repositories created by pytest.
- **No `data/` files were changed.** The temporary repositories are
  completely isolated from the real Janus workspace.
- **No production verifier code was modified.** The F-03 bug was
  discovered in existing code; it was NOT introduced during Phase 3.5.
- **No Phase 4 functionality was implemented.** No Phase 4 code, tests,
  or contracts exist.
- **No commit was created.** All created files are untracked.

---

## Next Steps (outside Phase 3.5 scope)

1. **Remediation task:** Fix `_parse_forbidden_symbols` so it constructs
   `ForbiddenSymbolEntry` with all fields at creation time.
2. **Re-review:** After remediation, re-run the complete Phase 3.5
   validation suite to confirm all 23 scenarios pass.
3. **Do NOT merge the Phase 3.5 tests** to the shared baseline until the
   verifier bug is resolved and the full suite passes.

---

## STOP

Per the failure discovery rule, Phase 3.5 validation stops here. The bug
is documented, not fixed. The test suite is preserved but cannot pass
until the verifier is remediated and re-reviewed.

**No further Phase 3.5 work should proceed until F-03 is resolved.**
