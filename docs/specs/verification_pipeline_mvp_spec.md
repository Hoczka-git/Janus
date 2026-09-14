# Verification Pipeline Milestone 1 — Implementation Specification

**Status:** Design consolidation (implementation blueprint, NOT implemented)
**Date:** 2026-08-30
**Source:** docs/verification_pipeline_design.md + docs/verification_pipeline_review.md
**Scope:** Milestone 1 — Minimum Viable Verification (MVV)
**Hard constraints:** ≤500 lines, no production code changes, no implementation, no commits, no multi-agent, no assumed agent spawning

---

## 1. Problem Being Solved

The Janus Goal System MVP agent claimed 100% complete. Independent review found ~15–20%. Root cause: no mechanical gate between "agent says done" and "human reviews."

**Failure modes this MVP prevents:**
1. Missing files claimed to exist
2. Partially implemented files claimed complete
3. Tests not written for new code (suite still green)
4. Untracked implementation files invisible to reviewer
5. Production data files modified during testing
6. Scope creep — files changed outside allowed scope
7. Forbidden symbols (e.g., `delete_goal`) introduced

**Failure modes this MVP does NOT prevent (future stages):**
- Semantic bugs (tests pass but test wrong behavior)
- Test quality assessment
- Security review
- Contract completeness review
- Integration correctness beyond what tests cover

---

## 2. Final MVP Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    MILESTONE 1 ARCHITECTURE                      │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  Stage 0: Contract Creation (human or human+agent draft)        │
│  ↓                                                               │
│  Stage 1: Implementation (agent works per frozen contract)        │
│  ↓                                                               │
│  Stage 2: Deterministic Verification (SCRIPT, not agent)          │
│    ┌─────────────────────────────────────────────────────────┐    │
│    │ verify_contract.py — reads contract, checks workspace   │    │
│    │ • Files existence (CREATE)                              │    │
│    │ • Files modified (MODIFY)                              │    │
│    │ • Immutable files unchanged                              │    │
│    │ • Unexpected modified files detected                     │    │
│    │ • Unexpected untracked files detected                    │    │
│    │ • Required symbols importable                           │    │
│    │ • Forbidden symbols absent                               │    │
│    │ • git diff --check passes                               │    │
│    │ • Verification commands pass                              │    │
│    │ Output: structured JSON report + exit code               │    │
│    └─────────────────────────────────────────────────────────┘    │
│                              ↓                                    │
│  Stage 3: Human Review (human reads evidence, decides)           │
│    ┌─────────────────────────────────────────────────────────┐    │
│    │ Evidence package:                                        │    │
│    │ • Contract (what was agreed)                             │    │
│    │ • Verification report (PASS/FAIL + details)              │    │
│    │ • git diff (what actually changed)                      │    │
│    └─────────────────────────────────────────────────────────┘    │
│                              ↓                                    │
│  Stage 4: Human Approval → Commit (if approved)                  │
│                                                                  │
│  NOTE: No adversarial review agent in Milestone 1.               │
│  No multi-agent orchestration. No assumed Hermes spawning.        │
└─────────────────────────────────────────────────────────────────┘
```

**Key design decisions (from review findings):**
- Single deterministic script, not multi-agent — avoids unproven spawning assumption (Review F4)
- 9 check functions (8 from design + `check_untracked_files` added per Review F2)
- Script integrates with existing `verification_evidence.py` for recording results
- Prompt update is acknowledged as a behavior change, not hidden (Review F3)

---

## 3. Exact Contract Schema (YAML)

```yaml
# implementation_contract.yaml
# Frozen agreement. DO NOT MODIFY during implementation.
version: 1
task_id: "<unique-slug-or-uuid>"
created: "<ISO-8601-timestamp>"
created_by: "<human-or-system>"

description: "<human-readable task description>"

# ──────────────────────────────────────────────────────────────
# FILES
# ──────────────────────────────────────────────────────────────

files:
  # Files that MUST be created (new files)
  create:
    - path: "src/example/new_module.py"
      description: "Optional description"
      # Optional: public API symbols that must exist in this file
      public_api:
        - "function_one"
        - "ClassTwo"

  # Files that MUST be modified (existing files)
  modify:
    - path: "src/example/existing.py"
      description: "Optional description"

  # Files that must NOT be modified (immutable)
  immutable:
    - path: "data/goals.md"
      reason: "Production data — do not touch"

  # Files that must NOT exist (forbidden)
  # 'type' distinguishes: 'exists' = file must not be on disk at all
  #                     'modified' = file may exist but must not be changed
  forbidden:
    - path: "src/example/delete_goal.py"
      type: exists        # must not exist on disk
      reason: "Out of scope"
    - path: "src/example/existing.py"
      type: modified      # may exist but must not appear in git diff
      reason: "Should not be touched"

# ──────────────────────────────────────────────────────────────
# SYMBOLS
# ──────────────────────────────────────────────────────────────

required_symbols:
  - module: "janus.services.goals"
    symbols:
      - "add_goal"
      - "get_goal"

forbidden_symbols:
  - "\\bdelete_goal\\b"
  - "\\bDeleteGoal\\b"

# ──────────────────────────────────────────────────────────────
# VERIFICATION COMMANDS
# ──────────────────────────────────────────────────────────────

verification_commands:
  - label: "Full test suite"
    command: "uv run pytest tests/ -v"
    expected_exit_code: 0
    timeout: 300          # seconds, optional, default 300

  - label: "Git diff check"
    command: "git diff --check"
    expected_exit_code: 0

  # Commands use RELATIVE paths from workspace root, not absolute paths

# ──────────────────────────────────────────────────────────────
# SCOPE CONSTRAINTS
# ──────────────────────────────────────────────────────────────

scope_constraints:
  allowed_paths:
    - "src/janus/"
    - "tests/"
  excluded_paths:
    - "data/"
  max_new_files: 10       # sanity check, optional
  max_lines_added: 2000   # sanity check, optional

# ──────────────────────────────────────────────────────────────
# COMPLETION GATES
# ──────────────────────────────────────────────────────────────

completion_gates:
  - label: "All CREATE files exist"
    type: mechanical
  - label: "All MODIFY files in git diff"
    type: mechanical
  - label: "All immutable files unchanged"
    type: mechanical
  - label: "No unexpected modified files"
    type: mechanical
  - label: "No unexpected untracked files"
    type: mechanical
  - label: "All required symbols importable"
    type: mechanical
  - label: "No forbidden symbols found"
    type: mechanical
  - label: "git diff --check passes"
    type: mechanical
  - label: "All verification commands pass"
    type: mechanical
  - label: "Human approval obtained"
    type: human

# ──────────────────────────────────────────────────────────────
# EVIDENCE (populated by verifier, NOT by implementor)
# ──────────────────────────────────────────────────────────────

evidence:
  report: "reports/verify_<task_id>_<timestamp>.json"
```

**Schema notes:**
- All paths are relative to workspace root (where contract lives)
- `files.forbidden.type` is REQUIRED: `exists` or `modified`
- `verification_commands` use relative paths, not absolute
- `required_symbols` uses Python module.path notation (e.g., `janus.services.goals`)
- `forbidden_symbols` are regex patterns matched with `rg`

---

## 4. Exact Verifier Responsibilities

**File:** `agent/verify_contract.py` (new)
**CLI:** `hermes verify-contract <contract_path>` (new subcommand)

The verifier is a SINGLE deterministic Python script. It does NOT use LLM judgment. It does NOT spawn agents. It does NOT modify the workspace.

### 4.1 Check Functions (9 total)

| # | Function | What it checks | PASS condition |
|---|----------|----------------|---------------|
| 1 | `check_files_create` | Every path in `files.create` exists on disk | `os.path.exists()` for each |
| 2 | `check_files_modify` | Every path in `files.modify` appears in `git diff --name-only` | Path in diff output |
| 3 | `check_files_immutable` | Every path in `files.immutable` has zero diff | `git diff -- <path>` empty |
| 4 | `check_files_unexpected_modified` | No files in `git diff --name-only` are outside `scope_constraints.allowed_paths` or inside `excluded_paths` | All modified files within scope |
| 5 | `check_files_untracked` | `git status --short` untracked files cross-referenced against `files.create`. Unexpected untracked files reported separately. | No untracked files beyond expected CREATE set |
| 6 | `check_symbols_required` | Every symbol in `required_symbols` is importable via `python -c "from module import symbol"` | Each returns exit 0 |
| 7 | `check_symbols_forbidden` | Every pattern in `forbidden_symbols` returns no matches via `rg -n pattern src/ tests/` | `rg` exits non-zero |
| 8 | `check_git_diff_check` | `git diff --check` exits 0 | No whitespace errors |
| 9 | `check_commands` | Every command in `verification_commands` exits with `expected_exit_code` | Exit code matches |

### 4.2 Untracked File Logic (clarified)

```
actual_untracked = git status --short | grep "^??" | extract paths
expected_untracked = {entry.path for entry in files.create}

unexpected = actual_untracked - expected_untracked
missing_from_create = expected_untracked - actual_untracked

# PASS if unexpected is empty AND missing_from_create is empty
# FAIL if unexpected is non-empty (report as "unexpected untracked files")
# NOTE: expected CREATE files that are untracked are NORMAL before commit
```

**Rationale:** Before commit, `files.create` entries are untracked (they're new files). The verifier does NOT require them to be staged. It only flags files that are untracked AND not in the expected CREATE set.

### 4.3 Output Format

```json
{
  "task_id": "<from contract>",
  "overall": "PASS" or "FAIL",
  "checks": {
    "files_create": {"passed": N, "failed": N, "details": [...]},
    "files_modify": {"passed": N, "failed": N, "details": [...]},
    "files_immutable": {"passed": N, "failed": N, "details": [...]},
    "files_unexpected_modified": {"passed": true/false, "details": [...]},
    "files_untracked": {"passed": true/false, "unexpected": [...], "details": [...]},
    "symbols_required": {"passed": N, "failed": N, "details": [...]},
    "symbols_forbidden": {"passed": true/false, "details": [...]},
    "git_diff_check": {"passed": true/false, "details": [...]},
    "commands": {"passed": N, "failed": N, "details": [...]}
  },
  "summary": "<human-readable one-line summary>",
  "failures": [...],  # only present if overall == "FAIL"
  "generated_at": "<ISO-8601>"
}
```

Exit code: 0 if `overall == "PASS"`, 1 if `overall == "FAIL"`.

### 4.4 Integration with Existing Hermes Infrastructure

| Existing component | How MVP uses it |
|-------------------|-----------------|
| `agent/verification_evidence.py` | Verifier calls `record_verify_run()` after running, recording PASS/FAIL status to SQLite ledger. This makes verification evidence available to the existing verify-on-stop nudge. |
| `agent/verification_stop.py` | No changes needed. The existing nudge logic already checks `verification_evidence.py` for recent passing verification. If the verifier records a passing run, the nudge is suppressed. |
| `hermes_cli/subcommands/verify.py` | No changes. The MVP adds a SEPARATE subcommand `verify-contract`, not a modification of `verify`. |
| `agent/coding_context.py` | Not used by MVP. The verifier operates on explicit contract paths, not auto-detected facts. |

**No changes to:** `conversation_loop.py`, `run_agent.py`, `agent_init.py`, `verify/runner.py`, `verify/recipes.py`.

---

## 5. PASS/FAIL Semantics

- **PASS:** All 9 check functions return no failures. `overall = "PASS"`. Exit code 0.
- **FAIL:** Any check function returns at least one failure. `overall = "FAIL"`. Exit code 1. `failures` list populated with details.
- **Gate strictness:** ALL-or-Nothing. One missing file = FAIL. One forbidden symbol = FAIL. One command failing = FAIL. No "close enough."
- **Report always produced:** Even on FAIL, the full JSON report is written. The human reviewer sees exactly what passed and what failed.

---

## 6. Expected Integration Points with Existing Hermes Code

| File | Change type | Description |
|------|-------------|-------------|
| `hermes_cli/subcommands/verify_contract.py` | NEW | CLI entry point. Parses `--contract` arg, calls `run_verification()`, prints JSON report, exits with code. Follows pattern of `verify.py`. |
| `agent/verify_contract.py` | NEW | Core verification script. 9 check functions + consolidation + CLI. ~400–600 lines. Uses `subprocess`, `pathlib`, `json`, `yaml` (pyyaml). |
| `agent/verification_evidence.py` | NO CHANGE | Existing. Verifier CALLS `record_verify_run()` but does not modify the module. |
| `hermes_cli/subcommands/verify.py` | NO CHANGE | Existing. Separate subcommand, no modification. |
| `agent/verification_stop.py` | NO CHANGE | Existing. Benefits passively from verifier recording evidence. |
| `agent/agent_init.py` | MODIFIED (prompt only) | Add instructons to implementor prompt: (1) require contract before starting, (2) do NOT claim completion until verifier passes, (3) report "implementation complete, awaiting verification" instead of "ready for review." This IS a behavior change — acknowledge it. |
| `conversation_loop.py` | NO CHANGE | No loop changes in Milestone 1. |
| `run_agent.py` | NO CHANGE | No changes. |

---

## 7. Minimal File-Level Implementation Map

```
New files (3):
  hermes_cli/subcommands/verify_contract.py   — CLI entry point (~50 lines)
  agent/verify_contract.py                     — core verifier (~400–600 lines)
  docs/examples/contract_feature.yaml          — example feature contract
  docs/examples/contract_bugfix.yaml          — example bugfix contract
  docs/contract_schema.md                      — formal schema specification (optional, can be section of this doc)

Modified files (1):
  agent/agent_init.py                         — prompt update only (acknowledged behavior change)

No changes to:
  agent/verification_evidence.py               — used, not modified
  agent/verification_stop.py                   — used, not modified
  hermes_cli/subcommands/verify.py            — separate, not modified
  agent/verify/runner.py                      — not used by MVP
  agent/verify/recipes.py                     — not used by MVP
  conversation_loop.py                         — no changes
  run_agent.py                                — no changes
```

**Total new code:** ~500–700 lines across 2 Python files + 2 example YAML files.

---

## 8. Test Strategy

### 8.1 Verifier Tests (test the verifier itself)

| Test | What it does |
|------|-------------|
| `test_check_files_create_pass` | Contract with existing files → PASS |
| `test_check_files_create_fail` | Contract with missing file → FAIL |
| `test_check_files_modify_pass` | Contract with modified file in diff → PASS |
| `test_check_files_modify_fail` | Contract with unmodified file not in diff → FAIL |
| `test_check_files_immutable_pass` | Contract with unmodified immutable file → PASS |
| `test_check_files_immutable_fail` | Contract with modified immutable file → FAIL |
| `test_check_files_unexpected_modified_pass` | Only allowed paths modified → PASS |
| `test_check_files_unexpected_modified_fail` | File outside allowed path modified → FAIL |
| `test_check_files_untracked_pass` | Only expected CREATE files untracked → PASS |
| `test_check_files_untracked_fail` | Unexpected untracked file present → FAIL |
| `test_check_symbols_required_pass` | Required symbols importable → PASS |
| `test_check_symbols_required_fail` | Required symbol missing → FAIL |
| `test_check_symbols_forbidden_pass` | No forbidden symbols → PASS |
| `test_check_symbols_forbidden_fail` | Forbidden symbol present → FAIL |
| `test_check_git_diff_check_pass` | Clean diff → PASS |
| `test_check_git_diff_check_fail` | Whitespace error in diff → FAIL |
| `test_check_commands_pass` | Commands exit with expected code → PASS |
| `test_check_commands_fail` | Command exits with wrong code → FAIL |
| `test_overall_pass` | All checks pass → overall PASS, exit 0 |
| `test_overall_fail` | One check fails → overall FAIL, exit 1 |
| `test_untracked_expected_create_allowed` | Expected CREATE file is untracked → NOT a failure |

**Test approach:** Use temp git repos (git init in temp dir) with controlled file states. Mock `subprocess.run` where needed for speed, but have at least one integration test that runs real git commands.

### 8.2 Contract Schema Tests

| Test | What it does |
|------|-------------|
| `test_contract_load_yaml` | Valid YAML contract loads without error |
| `test_contract_load_json` | Valid JSON contract loads without error (if JSON support added) |
| `test_contract_missing_version` | Contract without version field → error or default |
| `test_contract_missing_task_id` | Contract without task_id → error |

### 8.3 Example Contract Tests

| Test | What it does |
|------|-------------|
| `test_example_contract_feature` | Load `contract_feature.yaml`, run verifier against a temp workspace that matches it → PASS |
| `test_example_contract_bugfix` | Load `contract_bugfix.yaml`, run verifier against a temp workspace that matches it → PASS |

---

## 9. Explicit Non-Goals

These are NOT in Milestone 1. They are future stages or rejected.

| Non-goal | Why excluded |
|----------|-------------|
| Adversarial review agent (Stage 4 from design doc) | Requires verified Hermes spawning capability + model quality analysis. Not available for M1. |
| Automated contract generation from task description | Speculative. Requires AI-quality contract drafting. Future. |
| Pipeline automation into conversation loop | Modifies conversation_loop.py. Excluded per "no production code changes" constraint for M1. |
| Verification history tracking | Requires pipeline_registry.py + DB changes. Future. |
| CI integration | Requires CI system coupling. Future/optional. |
| Coverage tool integration (pytest --cov) | Nice-to-have. Not needed for M1 mechanical gate. |
| Multi-agent orchestration | Explicitly excluded by constraint 5. |
| Assumed Hermes agent spawning | Explicitly excluded by constraint 6. |
| JSON contract format | YAML only for M1. JSON can be added later if needed. |
| Pre-commit hook integration | The verifier is a CLI tool run by the agent/human. Git hooks are a future integration option. |
| Secrets scanning, debug code scanning | Listed as future additions in review F1. Not in M1. |

---

## 10. Implementation Order

| Step | What | Depends on |
|------|------|------------|
| 1 | Write contract schema specification (`docs/contract_schema.md` or section in this doc) | None |
| 2 | Write example contracts (`contract_feature.yaml`, `contract_bugfix.yaml`) | Step 1 |
| 3 | Implement `agent/verify_contract.py` core script (9 check functions) | Step 1 (schema) |
| 4 | Implement `hermes_cli/subcommands/verify_contract.py` CLI | Step 3 |
| 5 | Write verifier tests (21 tests listed in §8.1–8.3) | Step 3, 4 |
| 6 | Run verifier tests → all pass | Step 5 |
| 7 | Run verifier against example contracts in temp workspaces → PASS | Step 3, 4, 6 |
| 8 | Update `agent/agent_init.py` implementor prompt | Step 3 (script must exist before prompt refers to it) |
| 9 | Run full Hermes test suite → no regressions | Step 8 |
| 10 | Human review of: script, CLI, prompt change, examples, tests | Steps 3–9 |
| 11 | Merge/commit (if approved) | Step 10 |

**Critical path:** Steps 1→3→6. Steps 2, 4, 5, 7 are parallelizable once step 3 exists.

---

## 11. Definition of Done

Milestone 1 is DONE when ALL of the following are true:

- [ ] `agent/verify_contract.py` exists and implements all 9 check functions
- [ ] `hermes_cli/subcommands/verify_contract.py` exists and is callable as `hermes verify-contract <contract>`
- [ ] Verifier produces structured JSON report with `overall: PASS` or `overall: FAIL`
- [ ] Verifier exits 0 on PASS, 1 on FAIL
- [ ] All 21 verifier tests pass
- [ ] Example contracts load and verify successfully in temp workspaces
- [ ] `agent/agent_init.py` prompt updated with contract requirement + non-completion reporting
- [ ] Full Hermes test suite passes with no regressions
- [ ] Documentation: contract schema specified, usage documented
- [ ] Reviewed by human: script, CLI, prompt change, examples, tests
- [ ] No production code changes beyond `agent/agent_init.py` prompt
- [ ] No commits made (per "Nie commituj żadnych zmian")

**NOT required for Done:**
- Adversarial review agent
- Contract auto-generation
- Pipeline automation into conversation loop
- Coverage integration
- Multi-agent orchestration

---

## 12. Verification of This Specification

| Constraint | Evidence |
|-----------|----------|
| ≤500 lines | `wc -l` target: must be ≤500 when written |
| No production code modified | This doc creates new files + modifies only `agent/agent_init.py` prompt (acknowledged behavior change). No changes to `conversation_loop.py`, `run_agent.py`, `verify/runner.py`, `verify/recipes.py`, `verification_evidence.py`, `verification_stop.py`. |
| No implementation | This is a specification. No code is implemented by this document. |
| No commits | Document is not committed. `git status` will show `??` for this file. |
| No multi-agent | Explicitly excluded. Single deterministic script only. |
| No assumed agent spawning | Explicitly excluded. No Stage 4 adversarial review in M1. |
| Deterministic preferred | All 9 checks are deterministic. No LLM judgment. |
| Builds on existing infra | Uses `verification_evidence.py` for recording. No modifications to it. |
| No speculative abstractions | Every component has a clear purpose tied to a failure mode from the Goal System incident. |
| Contract schema distinguishes all file types | `create`, `modify`, `immutable`, `forbidden` (with `type: exists|modified`), `required_symbols`, `forbidden_symbols`, `verification_commands`, `scope_constraints` — all present in §3. |
| Verifier checks all 9 items | 1. CREATE exist, 2. MODIFY changed, 3. Immutable unchanged, 4. Unexpected modified, 5. Unexpected untracked, 6. Required symbols, 7. Forbidden symbols, 8. git diff --check, 9. Commands pass — all listed in §4.1. |
| Untracked logic clarified | §4.2 explicitly states expected CREATE files may be untracked, unexpected untracked reported separately. |

---

*End of specification.*
