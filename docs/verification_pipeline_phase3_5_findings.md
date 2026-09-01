# Phase 3.5 — Verification Finding F-03

## Verdict: FAIL — VERIFIER BUG DISCOVERED

Phase 3.5 end-to-end validation discovered a genuine verifier bug. Per
the frozen scope, the bug is NOT fixed in this phase.

---

## Finding F-03 — FrozenInstanceError in `_parse_forbidden_symbols`

**Severity:** HIGH — breaks the contract loading path.

**Affected check (indirect):** `check_symbols_forbidden` — the failure
occurs during `ImplementationContract.load()` before any check runs.

**Affected module:** `src/janus/verification.py`, lines 301–327.

**Expected behavior:**

A contract YAML containing:

```yaml
forbidden_symbols:
  - symbol: "delete_goal"
    path: "src/janus/services"
    type: "function"
```

should load successfully via `ImplementationContract.load(...)`, producing
a `ForbiddenSymbolEntry` with the correct `symbol`, `path`, and `type`.

**Actual behavior:**

Loading such a contract raises:

```
dataclasses.FrozenInstanceError: cannot assign to field 'symbol'
```

at line 319 of `src/janus/verification.py`.

**Minimal reproduction:**

```python
from janus.verification import ImplementationContract

contract = ImplementationContract.load("contract.yaml")
# where contract.yaml contains the forbidden_symbols section above
# → FrozenInstanceError at _parse_forbidden_symbols line 319
```

**Why existing tests missed it:**

- All existing Phase 3 tests construct `ForbiddenSymbolEntry` directly
  via the constructor, bypassing `ImplementationContract.load()`.
- No existing test exercises the YAML contract loader with
  Phase 3 AST-format `forbidden_symbols`.
- The only contract YAML in the repo uses the legacy regex string format.

**Recommended fix (for remediation task):**

Construct `ForbiddenSymbolEntry` with all fields at creation time instead
of mutating after construction.

---

*Phase 3.5 validation: 2026-08-30. Verifier bug discovered before any
end-to-end scenario could run.*
