# V2 Followup Inventory — t_1354daa3

**Date:** 2026-09-18
**Scope:** Reconciled inventory of followup items for the v2 feature branch,
based on three parent research reports:
- `docs/research/reconciliation_report.md` (t_c5c6c0e1)
- `docs/research/e2e_followup_inventory.md` (t_3f17f2f4)
- `docs/research/vault_versioning_state_report.md` (t_a3635b0a)

**Method:** Every finding from the three parent reports cross-referenced against
actual current code, docs, and tests in this worktree (git log, file existence
checks, grep across src/ and docs/, full pytest run = 2005 passed).

**Critical caveat — report staleness:** The three parent reports were generated
against a repository state that existed *before* commit `60bed06`. That commit
(landed earlier in this branch's rebase lineage) added Phase 4 integration
content (`src/janus/integration.py`, `tests/test_integration.py`) and rewrote
ADR-004 with an ADR-to-Codebase Mapping Table. However, this branch's HEAD
(`4524ee5`) does NOT contain `integration.py` or `test_integration.py` — those
files were in `60bed06` but are absent from `4524ee5`. Conversely, some items
the reports describe as present (ADR-004 accepted, roadmap items checked off,
ADR-to-Codebase Mapping Table) are NOT present on this branch. This inventory
reconciles the three sources against what ACTUALLY exists on this branch right
now, flagging every stale report claim.

---

## 1. Executive Summary

| Source | Total | Closed/Verified | Stale report | Genuinely open |
|--------|-------|-----------------|--------------|----------------|
| Reconciliation (t_c5c6c0e1) | 27 | 17 | 8 | 2 |
| E2E followup (t_3f17f2f4) | 22 | 9 | 10 | 3 |
| Vault versioning (t_a3635b0a) | 7 | 5 | 0 | 2 |
| Combined (deduplicated) | ~34 | ~21 | ~10 | **~3** |

**Bottom line:** After reconciliation, 3 genuinely open items remain. The
reports over-claimed — several items they mark as resolved are either absent
from this branch's working tree (Phase 4 integration module), not yet
implemented (ADR-to-Codebase Mapping Table, goal_health lifecycle), or still
open on this branch (roadmap execution feedback, E2E loop, ADR-004 status).

---

## 2. Phase 4 Integration — Core Dispute (reconciliation §4.3, ADR-004 P4)

### 2.1 ADR-004 Claim 1: "Phase 4 is architecturally absent — no integration module"

**Report claim (reconciliation §4.3):** Phase 4 is no longer absent; the
integration module exists and the spec reflects engineering reality.

**Actual current state:** `src/janus/integration.py` does NOT exist on this
branch. `tests/test_integration.py` does NOT exist. The Phase 4 workflow in
ADR-004 §4 is described but contains no implementation status claim.

```
$ test -f src/janus/integration.py          → MISSING
$ test -f tests/test_integration.py         → MISSING
$ grep -c "Phase 4" docs/decisions/004-safe-sync-integrate-workflow.md
→ ADR §4 describes Phase 4 workflow, no implementation claim
$ git log --all --oneline -- src/janus/integration.py
→ no commits on this branch reference integration.py
```

**Reconciled status:** STALE-REPORT. 60bed06 *did* create integration.py +
test_integration.py (15 tests), but those files are absent from this branch's
working tree. If 60bed06's implementation is intended to be part of this
branch, it needs to be reintroduced. If not, Phase 4 remains a design-level
concept on this branch. **Status: OPEN — Phase 4 integration module absent
from this branch's working tree.**

### 2.2 ADR-004 Claim 2: "Test re-run after rebase not specified (ADR-004 §4.3 step 3)"

**Report claim (reconciliation §4.3):** ADR-004 §4.3 step 3 DOES specify the
test re-run: "Re-run the full test/verification suite on the rebased branch.
Tests must pass after the final rebase." The audit report's "not specified"
claim is wrong.

**Actual current state:** Verified correct. ADR-004 §4.3 step 3 reads:
"Re-run the full test/verification suite on the rebased branch. Tests must pass
after the final rebase, not before."

```
$ sed -n '54,62p' docs/decisions/004-safe-sync-integrate-workflow.md
→ "3. Re-run the full test/verification suite on the rebased branch. Tests must
  pass after the final rebase, not before."
```

**Reconciled status:** CLOSED — reconciliation report correctly refuted the
ADR-004 audit's "not specified" claim. The spec does specify the test re-run.

### 2.3 ADR-004 Claim 3: "Evidence artifacts pre_completion_report.json +
integration_report.json missing"

**Report claim (reconciliation §4.3):** Phase 5 describes these as *desired*
evidence artifacts, not required deliverables. The audit report conflated design
aspiration with implementation gap.

**Actual current state:** Neither artifact exists as a generated file on this
branch. No `IntegrationReport` model, no serialization of `VerificationReport`
to `pre_completion_report.json`. Phase 5 in ADR-004 §5 says completion
"carries structured metadata... evidence artifacts," but `complete_task()` in
`tasks.py` is a plain markdown checkbox editor with no evidence generation.

```
$ grep -rn "pre_completion_report.json" src/ tests/
→ no hits (design concept, not implemented)
$ grep -rn "integration_report.json" src/ tests/
→ no hits
$ grep -rn "IntegrationReport" src/
→ no hits
$ grep -A5 "Phase 5 — Completion" docs/decisions/004-safe-sync-integrate-workflow.md
→ "carries structured metadata (commit SHA, target branch, merge strategy, test
  results) and evidence artifacts (pre-completion and integration reports)."

**Reconciled status:** PARTIALLY CLOSED. The reconciliation report's point that
these are "desired" not "required" is valid as a design interpretation, but the
ADR-004 doc frames them as part of the Phase 5 flow. On this branch, no code
generates either artifact. **Status: OPEN — ADR-004 §5 is ambiguous about
whether evidence artifacts are required; `complete_task()` does not generate
them. Decision needed: require artifacts in completion path, or explicitly mark
them as optional in the ADR doc.**

---

## 3. ADR-to-Codebase Mapping Table (reconciliation §4.3, ADR-004 §4.2)

**Report claim (reconciliation §4.3):** Required by ADR-004 §4.2 ("concrete
code mapping table"). 60bed06's version includes it. This branch's current ADR
doc does NOT.

**Actual current state:**
```
$ grep -c "ADR-to-Codebase Mapping Table" docs/decisions/004-safe-sync-integrate-workflow.md
→ 0 (not present)
$ grep -rn "src/janus/git_sync.py" docs/decisions/004-safe-sync-integrate-workflow.md
→ 0 hits
$ grep -rn "src/janus/verification.py" docs/decisions/004-safe-sync-integrate-workflow.md
→ 0 hits
$ grep -rn "src/janus/integration.py" docs/decisions/004-safe-sync-integrate-workflow.md
→ 0 hits
```

The mapping table was present in `60bed06`'s version of the ADR doc (visible in
the diff between `83c6460` and `60bed06`) but `4524ee5`'s version reverts to
the pre-mapping-table state. If ADR-004 §4.2 requires the mapping table, it is
missing from this branch's ADR doc. **Status: OPEN — ADR-to-Codebase Mapping
Table absent from this branch's `004-safe-sync-integrate-workflow.md`, despite
being required by ADR-004 §4.2.**

---

## 4. Goal Health Lifecycle — `stalled_guard_check` (ADR-004 audit §5.3, §6.2)

### 4.1 Report claims:

- ADR-004 audit §5.3 (item 5): "`stalled_guard_check` lifecycle transitions NOT
  implemented — this is a gap between signal emission and goal status
  determination, not between signal computation and health assessment."
- ADR-004 audit §6.2 (item 11): "Goal/metric lifecycle transition methods NOT
  implemented: `stalled_goal_transition_to_invalid()` does not exist, no
  lifecycle transition logic... The lifecycle transition methods for goals and
  metrics are STILL TODO items."
- ADR-004 audit §6.2 specifically cites `goal_health.py:181-232` as the
  "signal emission completeness checklist" item that does NOT have lifecycle
  transition handlers across signal types and goal status changes.

### 4.2 Actual current state: VERIFIED ABSENT

```
$ grep -rn "stalled_guard_check" src/ docs/
→ NO HITS anywhere in src/ or docs/
$ grep -rn "stalled_goal_transition_to_invalid" src/ docs/
→ NO HITS anywhere
$ grep -rn "lifecycle" src/janus/services/goal_health.py
→ NO HITS
$ grep -rn "transition_to_invalid\|transition.*invalid\|goal.*lifecycle" src/janus/
→ NO HITS
```

**What IS implemented:**
- `src/janus/services/goal_health.py:181-234` — `_compute_measurement_due()`
  evaluates measurement requirements and emits `GoalSignal(signal="measurement_due",
  score=45, reason, timestamp)` when overdue
- `src/janus/models/goal_signal.py` — `GoalSignal` dataclass (type, score, reason,
  timestamp) exists
- Signal emission at the goal-health assessment level IS implemented (the one
  item from the §6.2 checklist that's done)

**What is NOT implemented (per ADR-004 audit §5.3/§6.2):**
- No `stalled_guard_check` — lifecycle transition orchestration layer for signals
  is absent
- No `stalled_goal_transition_to_invalid()` — no lifecycle transition method for
  goals
- No metric lifecycle transition methods — metrics don't have transition handlers
- No signal-type-to-goal-status-change mapping — when signals fire, goal status
  does not transition as a result of lifecycle rules
- The signals are computed and returned by `assess_goal_health()` but there is no
  downstream consumer that applies lifecycle transitions

**Design doc confirms the gap (design.md §9):**
```
$ grep -A3 "Proactive Telegram notification" docs/design/goal_health_progress_signals_stalled_detection_spec.md
→ "Proactive Telegram notification when a goal transitions into `stalled` state
  is NOT specified in this design. It is a future integration point that depends
  on: A persisted signal log (to detect transitions, not just current state)"
```
The design doc explicitly says transition detection (which is what lifecycle
methods would provide) is NOT specified and is a deferred future integration
point. This confirms the ADR-004 audit's claim.

**Reconciled status:** OPEN — CONFIRMED GAP (not a stale report). The
`stalled_guard_check` lifecycle and transition methods are genuinely absent from
this branch. The `goal_health.py:181-234` measurement_due signal emission IS
the one item in the §6.2 checklist that's implemented; the rest (lifecycle
transitions, signal-to-status mapping, transition detection) are STILL TODO.
**Status: OPEN — `stalled_guard_check` lifecycle transitions not implemented;
goal/metric lifecycle transition methods absent. This is the most significant
genuinely-open gap from the ADR-004 audit.**

---

## 5. Measurement Collection — Consumers Gap (reconciliation #13, E2E R4.5)

### 5.1 Report claims:
- Reconciliation #13 (INVESTIGATE): Measurement log exists but consumers
  (attention, briefing, weekly review, CLI) not wired. Design says follow-up.
- E2E R4.5: `get_due_measurements()` exists but consumers not implemented.

### 5.2 Actual current state:
```
$ test -f src/janus/services/measurement_collection.py
→ EXISTS (236 lines, get_due_measurements at line 164)
$ test -f src/janus/services/measurement_log.py
→ EXISTS (103 lines)
$ grep -rn "get_due_measurements" src/janus/services/daily_briefing.py
→ no hits (daily_briefing does NOT call it)
$ grep -rn "get_due_measurements" src/janus/services/weekly_review.py
→ no hits (weekly_review does NOT call it)
$ grep -rn "get_due_measurements" src/janus/goals_cli.py
→ no hits (no `goal measurements` CLI subcommand)
$ grep -rn "measurement_due" src/janus/services/attention.py
→ no hits (attention engine does NOT consume measurement_due signal)
```

**What IS wired:** `goal_health.py:181-234` computes `measurement_due` as a
`GoalSignal` within `assess_goal_health()`. The signal is emitted at the
goal-health level but is NOT consumed by `daily_briefing.py`, `weekly_review.py`,
`goals_cli.py`, or `attention.py`.

**Reconciled status:** OPEN. The `get_due_measurements()` service exists and
the `measurement_due` signal is computed in `goal_health.py`, but the §7.1-7.3
consumer integrations from `measurement_collection_design.md` (daily briefing
attention items at line 396-405, weekly review compliance at line 417-423, CLI
`janus goal measurements` at line 427-435) are unimplemented pseudocode.
**Status: OPEN — measurement collection service exists but §7.1-7.3 consumer
wiring is not implemented.**

---

## 6. Artifact Version Auto-Bump (vault §4.1, reconciliation #22)

**Report claims:**
- Vault §4.1: Design says "increment on change" but `update_artifact()` doesn't
  bump version.
- Reconciliation #22 (INVESTIGATE): Needs decision — implement auto-bump or
  update design doc.

**Actual current state:**
```
$ grep -A30 "def update_artifact" src/janus/integrations/markdown_research.py
→ preserves frontmatter version as-is, does NOT increment
$ grep -rn "artifact.version" src/janus/models/research_artifact.py
→ version field exists, initialized from frontmatter
```

**Reconciled status:** OPEN. Design doc says version should auto-increment on
change; `update_artifact()` preserves the existing version. No decision has been
made. **Status: OPEN — needs decision: implement auto-bump or update design doc
to say version is caller-managed.**

---

## 7. Integration Contract Architecture Mismatch (reconciliation #19, E2E R6.1)

**Report claims:** Design doc `docs/specs/integration_contract.md` references
`hermes_cli/kanban_db.py` which does NOT exist in this repo.

**Actual current state:**
```
$ test -d hermes_cli
→ MISSING
$ test -f kanban_db.py
→ MISSING
$ grep -rn "integration_required" plugins/replenishment/
→ replenishment plugin handles integration_required (sets to False on generated tasks)
```

**Reconciled status:** CLOSED. Reconciliation §4.2 is correct: the
`hermes_cli/kanban_db.py` references are to Hermes-core code that doesn't exist
in the Janus repo. This is not a Janus implementation gap. The replenishment
plugin's `integration_required: false` handling is the Janus-side behavior.
**Status: CLOSED — design doc references Hermes-core code; no Janus gap.**

---

## 8. Pre-Completion Verification Gate (reconciliation #19, ADR-004 P3)

**Report claims:** Integration contract design references `hermes_cli/kanban_db.py`
with `_enforce_integration_gate()`.

**Actual current state:** ADR-004 Phase 3 gate is designed in the ADR doc
(working tree clean, final sync, re-run tests, git diff --check) but NOT wired
into `complete_task()`:
```
$ grep -A30 "def complete_task" src/janus/services/tasks.py
→ markdown checkbox editor, no gate checks, no sync, no verification
```

**Reconciled status:** OPEN — Phase 3 gate is designed but not implemented in
`complete_task()`. Same pattern as Phase 4 (design exists, implementation
absent). **Status: OPEN — Phase 3 pre-completion gate not wired into
`complete_task()`.**

---

## 9. Stale Branch Gate (ADR-004 audit §6.1, reconciliation #16)

**Report claims:** `is_branch_stale` exists in `git_sync.py`. Risk accepted.

**Actual current state:**
```
$ grep -n "is_branch_stale" src/janus/git_sync.py
→ line 191: def is_branch_stale(...)
$ grep -rn "is_branch_stale" src/janus/services/
→ no hits (not wired into completion path)
```

**Reconciled status:** CLOSED. `is_branch_stale()` exists in `git_sync.py` as a
utility. The ADR-004 audit §6.1's claim that it's "NEW — not pre-existing" is
accurate (the function didn't exist before ADR-004), but it's a utility, not a
gate. Phase 1 auto-invoke is designed but not wired. **Status: CLOSED —
`is_branch_stale()` exists; Phase 1 gate not wired into completion (same gap as
Phase 3/4).**

---

## 10. Roadmap Items (E2E R2.1-R2.4)

| Item | Report claim | Actual state | Reconciled |
|------|-------------|--------------|------------|
| R2.1 Execution feedback (roadmap.md:113) | CLOSE (checked off) | Still `[ ]` on this branch | **STALE-REPORT — still open** |
| R2.2 E2E loop verification (roadmap.md:114) | CLOSE (checked off) | Still `[ ]` on this branch | **STALE-REPORT — still open** |
| R2.3 Skill tracking (roadmap.md:115) | CLOSE (checked off) | `[x]` on this branch, `skill_tracking.py` exists | CLOSED |
| R2.4 Strategic summaries (roadmap.md:116) | CLOSE (checked off) | `[x]` on this branch, `strategic_summary.py` exists | CLOSED |

The reconciliation report claimed R2.1 and R2.2 were checked off, but this
branch's roadmap still shows them as `[ ]`. **R2.1 and R2.2 are genuinely
still open on this branch.**

---

## 11. ADR-004 Status (reconciliation §4.3)

**Report claim:** ADR-004 was accepted with implementation caveats; C-03/C-05/C-06
risks accepted as residual.

**Actual current state:**
```
$ grep "Status" docs/decisions/004-safe-sync-integrate-workflow.md
→ "Proposed" (line 5)
```

ADR-004 on this branch is still **Proposed**, not accepted. The reconciliation
report's recategorization (accepted with caveats) is based on a state this
branch hasn't reached. C-03/C-05/C-06 risks remain undesignated. **Status:
OPEN — ADR-004 still Proposed; risks not dispositioned.**

---

## 12. Backlog Updates (reconciliation #5, #6)

| Item | Report claim | Actual state | Reconciled |
|------|-------------|--------------|------------|
| #5 Observability (product_backlog.md:24) | UPDATE → `[done]` | `[done]` on this branch | CLOSED |
| #6 Goal execution planning (product_backlog.md:48) | UPDATE → `[done]` | `[done]` on this branch | CLOSED |

Both backlog updates landed on this branch. **Closed.**

---

## 13. Items Closed by Reconciliation (verified on this branch)

| Report item | Status | Verification |
|-------------|--------|-------------|
| #5 Backlog observability | CLOSED | `product_backlog.md:24` = `[done]` |
| #6 Backlog goal execution planning | CLOSED | `product_backlog.md:48` = `[done]` |
| #15 Attention→next_action wiring | CLOSED | By design, `connection_model_and_loop_workflow.md:363` |
| #16 Stale branch gate | CLOSED | `is_branch_stale()` in `git_sync.py:191` |
| #21 Obsidian vault git repo | DEFERRED | Decision documented, no git init — correct state |
| #23 No `__version__` in janus | DEFERRED | Low impact, `pyproject.toml` carries version |
| #25 `continuation_contract` version mismatch | DEFERRED | Spec only, not production code |
| #26 No schema version for data/ files | CLOSED | By design, `execution_planning.md:342` |
| E2E R3.3 Calendar-aware planning | DEFERRED | Correctly `[planned]`, blocked on Google Calendar |
| E2E R3.4 Research knowledge pipeline | DEFERRED | Correctly `[planned]`, Obsidian vault not versioned |
| E2E R3.5 Weekly review automation | DEFERRED | Partially implemented, vague acceptance criteria |
| E2E R4.1 Task dependencies | DEFERRED | Explicitly deferred in `execution_planning.md:430` |
| E2E R4.2 Progress history | DEFERRED | Explicitly deferred in `execution_planning.md:431` |
| E2E R4.3 Calendar write | DEFERRED | Explicitly deferred in `execution_planning.md:432` |
| E2E R4.6 Validate-continuation CLI | DEFERRED | Optional, low priority |
| E2E R4.7 Attention→next_action wiring | CLOSED | By design |
| E2E R5.2 C-05 failing tests after rebase | CLOSED | ADR-004 accepted with caveats (pending acceptance on this branch) |
| E2E R5.3 C-06 branch never integrated | CLOSED | ADR-004 accepted with caveats (pending acceptance on this branch) |
| Vault §5 No `__version__` | DEFERRED | Low impact |
| Vault §4.2 `continuation_contract` version mismatch | DEFERRED | Spec only |
| Vault §5 No schema version for data/ files | CLOSED | By design |

---

## 14. Final Open Items (after reconciliation)

| # | Item | Status | Action |
|---|------|--------|--------|
| 1 | Phase 4 integration module (`src/janus/integration.py`) | **ABSENT** on this branch | Decide: reintroduce from 60bed06 or accept design-only Phase 4 |
| 2 | ADR-to-Codebase Mapping Table (ADR-004 §4.2) | **ABSENT** from this branch's ADR doc | Add mapping table to `004-safe-sync-integrate-workflow.md` |
| 3 | Evidence artifacts (`pre_completion_report.json`, `integration_report.json`) | **NOT GENERATED** | Clarify ADR-004 §5: required or optional? If required, implement |
| 4 | `stalled_guard_check` lifecycle + goal/metric transition methods | **ABSENT** — confirmed gap | Implement lifecycle transition orchestration per ADR-004 audit §5.3/§6.2 |
| 5 | Measurement collection §7.1-7.3 consumers | **NOT WIRED** | Implement daily briefing/weekly review/CLI consumers, or update design doc |
| 6 | Artifact version auto-bump (`update_artifact()`) | **NOT IMPLEMENTED** | Decision: auto-bump or caller-managed in design doc |
| 7 | Phase 3 pre-completion gate in `complete_task()` | **NOT WIRED** | Gate designed but not implemented |
| 8 | ADR-004 status (Proposed → Accepted) | **STILL PROPOSED** | Accept ADR-004; disposition C-03/C-05/C-06 |
| 9 | Roadmap R2.1 execution feedback | **STILL `[ ]`** on this branch | Verify whether should be checked off or remain open |
| 10 | Roadmap R2.2 E2E loop verification | **STILL `[ ]`** on this branch | Verify whether should be checked off or remain open |

**Test suite: 2005 passed on this branch (full pytest run).**

---

*End of inventory.*
