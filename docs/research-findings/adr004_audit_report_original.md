# ADR-004 Audit Report

**Task:** t_7a55554d — Synthesize ADR-004 audit report  
**Date:** 2026-09-12  
**Last verified:** 2026-09-24
**Scope:** Compare ADR-004 (`docs/decisions/004-safe-sync-integrate-workflow.md`) against current Janus/Hermes implementation.  
**Method:** Synthesize findings from three parent research tasks: t_73ff09a7 (completion/integration flow survey), t_b352e609 (sync/integrate implementation survey), t_ce633bb3 (ADR-004 claim extraction).

---

## 1. Executive Summary

The current Janus/Hermes system is a **passive gate architecture** layered on top of
`src/janus/services/tasks.py:complete_task()`. ADR-004 specifies an **active 5-phase
workflow** with dedicated agents for integration. The gap is structural: the system
verifies integration happened (or the agent claims it did) but never performs it.

> **Note:** Earlier research reports referenced `hermes_cli/kanban_db.py` with
> line numbers for `_enforce_repo_sync_gate`, `_enforce_integration_gate`, and
> `complete_task()`. **Those references are stale** — `hermes_cli/` does not
> exist in the Janus codebase. The actual completion path is
> `src/janus/services/tasks.py:complete_task()` — a plain markdown checkbox edit
> with no gates. See §6 for the full mapping table.

| ADR-004 Phase | ADR-004 Intent | Current Implementation | Verdict |
|---|---|---|---|
| Phase 1 — Pre-Implementation Sync | Auto-sync before implementation | Primitive exists (`src/janus/git_sync.py`), not auto-invoked | **PARTIAL** |
| Phase 2 — Implementation | Unchanged — work in worktree | Worktree isolation via `_ensure_git_worktree` | **MATCH** |
| Phase 3 — Pre-Completion Gate | Clean tree, final sync, re-run tests, `git diff --check` | Contract-based verifier (`src/janus/verification.py`); missing clean-tree check, no test re-run after rebase | **PARTIAL** |
| Phase 4 — Safe Integration | Active merge, push, post-merge verify, rollback, separate agent | Passive gate (`_enforce_integration_gate`); no active merge, no integrator profile | **DIVERGES** |
| Phase 5 — Completion | `kanban_complete` gated on Phases 1+3+4, structured metadata + evidence artifacts | `complete_task()` exists, no gating on sync/integration results, no evidence artifacts | **PARTIAL** |

**Overall verdict: PARTIAL MATCH — Phase 4 (Safe Integration) is architecturally absent.** The current model cannot enforce "no partially-integrated state" (ADR POS-02) because it has no mechanism to perform or roll back integration. The implementor remains the sole arbiter of "is this done" (ADR POS-03).

---

## 2. Claim-by-Claim Audit

### 2.1 Context Claims

| ADR ID | Claim | Verdict | Evidence |
|---|---|---|---|
| C-01 | Agent claims `kanban_complete` after implementation | MATCH | `complete_task()` in `src/janus/services/tasks.py:43-79` allows transition to `done` after gates pass |
| C-02 | No mechanical gate for sync/clean/integrate | PARTIAL | Gate exists for verification (contract-based) and integration (passive check), but not for sync/clean-tree/test-rerun |
| C-03 | Risk: stale branch marked done | UNRESOLVED | Phase 1 sync not auto-invoked; no gate prevents stale branch completion |
| C-04 | Risk: unpushed/uncommitted changes | PARTIAL | Integration gate checks pushed state (`web_git.py:683-694`); no clean-tree check |
| C-05 | Risk: failing tests after rebase | UNRESOLVED | No test re-run after rebase in gate; contract-based verifier may or may not include `pytest` in `verification_commands` |
| C-06 | Risk: branch never integrated | UNRESOLVED | Integration gate only verifies; if agent never merges, task sits in `running` indefinitely |

### 2.2 Decision Claims (Phase 1 — Pre-Implementation Sync)

| ADR ID | Claim | Verdict | Evidence |
|---|---|---|---|
| D-01 | Three-phase gated workflow adopted | PARTIAL | Gates exist but are passive (verify-only), not active (perform + verify) |
| D-02 | `kanban_complete` gated on all three phases | PARTIAL | Only Phase 3 (verification) and Phase 4 (integration) gates exist; Phase 1 has no enforcement |
| P1-01 | Phase 1 runs before implementation | DIVERGES | `sync_branch()` exists but is not auto-invoked by dispatcher; agent must call manually |
| P1-02 | Fetch remote target branch | MATCH | `fetch_target()` at `git_sync.py:171-182` |
| P1-03 | Detect staleness via `merge-base` | MATCH | `is_branch_stale()` at `git_sync.py:191-224` |
| P1-04 | Rebase + force-push with lease | MATCH | `rebase_onto_target()` + `force_push()` at `git_sync.py:240-264` |
| P1-05 | Conflict → block → merge-reconciler | PARTIAL | `SYNC_CONFLICT` returned; `merge-reconciler` skill exists; routing not automated |
| P1-06 | Sync conflicts NOT resolved in worktree | MATCH | `git_sync.py:360-374` aborts on conflict, returns code |

### 2.3 Decision Claims (Phase 2 — Implementation)

| ADR ID | Claim | Verdict | Evidence |
|---|---|---|---|
| P2-01 | Unchanged — work in worktree | MATCH | Task branch + worktree per task (dispatcher-managed); no direct `kanban_db._ensure_git_worktree` equivalent in this codebase |

### 2.4 Decision Claims (Phase 3 — Pre-Completion Gate)

| ADR ID | Claim | Verdict | Evidence |
|---|---|---|---|
| P3-01 | Phase 3 runs when implementor believes done | MATCH | `_enforce_janus_verification_gate()` called from `complete_task()` |
| P3-02 | Working tree clean | DIVERGES | No automatic check; only if contract declares `check_files_untracked` |
| P3-03 | Final fetch + re-sync | DIVERGES | No automatic loop back to Phase 1 |
| P3-04 | Re-run full test suite after rebase | DIVERGES | Contract verifier does not run `pytest` unless declared in contract |
| P3-05 | `git diff --check` | PARTIAL | `check_git_diff_check()` exists but only runs if contract declares it |
| P3-06 | Failure → `kanban_block` with structured code | MATCH | `VerificationGateError` raised on failure; reason codes in `git_sync.py:25-34` |

### 2.5 Decision Claims (Phase 4 — Safe Integration)

| ADR ID | Claim | Verdict | Evidence |
|---|---|---|---|
| P4-01 | Dedicated integration agent | DIVERGES | No integrator profile exists; implementor does merge |
| P4-02 | Verify task has latest target | DIVERGES | No code exists |
| P4-03 | Attempt `--ff-only` merge | DIVERGES | No code exists |
| P4-04 | `--no-ff` fallback, abort on conflict | DIVERGES | No code exists |
| P4-05 | Post-merge tests, rollback on failure | DIVERGES | No code exists |
| P4-06 | Push target branch | DIVERGES | No code exists |
| P4-07 | Verify remote contains commit | DIVERGES | No code exists |

### 2.6 Decision Claims (Phase 5 — Completion)

| ADR ID | Claim | Verdict | Evidence |
|---|---|---|---|
| P5-01 | Only after Phases 1, 3, 4 pass | DIVERGES | No gating on Phase 1 or Phase 4 results |
| P5-02 | Structured metadata (SHA, branch, strategy, tests) | DIVERGES | `complete_task()` accepts `metadata` dict but no sync/integration data is injected |
| P5-03 | Evidence artifacts (pre-completion + integration reports) | DIVERGES | No `pre_completion_report.json` or `integration_report.json` generated |
| P5-04 | `kanban_task_completed` fires → cleanup + replenishment | MATCH | Hook fires; consumers: `janus_sync`, `replenishment`, gateway notifiers |

### 2.7 Consequence Claims

| ADR ID | Claim | Verdict | Evidence |
|---|---|---|---|
| POS-01 | Catches stale-branch + post-rebase failures | DIVERGES | No test re-run after rebase; sync not enforced |
| POS-02 | No partially-integrated state | DIVERGES | No atomic merge + rollback; passive gate only |
| POS-03 | Separation of implementor/integrator | DIVERGES | No separate actor; implementor is sole arbiter |
| POS-04 | Auditable failures with structured codes | PARTIAL | Phase 1 reason codes exist; Phase 4 codes documented but unimplemented |
| POS-05 | Preserves existing infrastructure | MATCH | Worktrees, Kanban state machine, CI, merge-reconciler all reused |
| POS-06 | Per-task isolation preserved | MATCH | Worktree-per-task; no shared dev branch |
| NEU-01 | Adds latency (tests run twice) | DIVERGES | Tests do not run twice; Phase 4 absent |
| NEU-02 | Separate agent for Phase 4 | DIVERGES | Deferred to t_36b3d88f; no agent exists |

### 2.8 Constraint Compliance

| Constraint | Required | Current | Verdict |
|---|---|---|---|
| CON-1 | No shared dev branch | No shared dev branch exists | COMPLIANT |
| CON-2 | Task branches single-writer | Worktree isolation enforces single-writer | COMPLIANT |
| CON-3 | No new state model | Reuses Kanban + worktree | COMPLIANT |
| CON-4 | No locking — git ref atomicity | No locking code exists | COMPLIANT |
| CON-5 | No prose-only claims | Reason codes used in Phase 1 | COMPLIANT |
| CON-6 | Sync conflicts → merge-reconciler | `SYNC_CONFLICT` returned; routing not automated | PARTIAL |
| CON-7 | Phase 4 by separate agent | No integrator exists | NON-COMPLIANT |

---

## 3. Gap Analysis

### 3.1 Critical Gaps (Block ADR-004 Compliance)

| Gap | Impact | ADR Reference |
|---|---|---|
| **Phase 4 (Safe Integration) not implemented** | The system cannot enforce atomic integration. The implementor can still be the sole arbiter of "done." | P4-01 through P4-07 |
| **No integrator profile/agent** | No separation of concerns. Phase 4 requires a dedicated actor per ADR. | P4-01, NEU-02 |
| **No active merge/push/rollback** | Risk of partially-integrated state. No atomic rollback on test failure. | P4-03, P4-04, P4-05 |
| **No evidence artifacts** | No `pre_completion_report.json` or `integration_report.json`. Failures are not auditable in structured form. | P5-03 |
| **Phase 3 missing deterministic checks** | Working tree clean, final sync, test re-run after rebase are not enforced unless contract declares them. | P3-02, P3-03, P3-04 |

### 3.2 Medium Gaps

| Gap | Impact | ADR Reference |
|---|---|---|
| **Phase 1 not auto-invoked** | Agent must remember to call `sync_branch()` at task start; no enforcement. | P1-01 |
| **Phase 4 reason codes documented but not implemented** | `integration_conflict`, `post_integration_test_failure`, `target_push_failed` have no code paths. | ADR §7 |
| **No test re-run after rebase in Phase 3** | Tests may pass before rebase but fail after; this is the most common failure mode ADR targets. | P3-04, POS-01 |

### 3.3 Low Gaps

| Gap | Impact | ADR Reference |
|---|---|---|
| **Duplicated target-branch detection** | `git_sync.py` duplicates logic in `web_git.py:_default_branch_name()`. Risk of drift. | ADR §3 |
| **Contract coverage unknown** | Percentage of tasks with `janus_contract:` frontmatter unknown. | Phase 3 opt-in |

---

## 4. Architectural Divergence

**ADR-004 Model:**
```
Agent → Phase 1 (auto-sync) → Phase 2 (implement) → Phase 3 (gate) → Phase 4 (integrator merges) → Phase 5 (done)
```

**Current Model:**
```
Agent → [optional: manual sync] → Phase 2 (implement) → [optional: contract verify] → Agent/Human merges → Integration gate (verify-only) → Phase 5 (done)
```

The current model is **reactive**: the agent performs integration and the gate verifies (or the human does it manually). ADR-004 requires a **proactive** model: integration is performed by a dedicated actor with atomic rollback, independent of the implementor's claim.

---

## 5. Recommended Actions

### 5.1 Immediate (Close Critical Gaps)

1. **Implement Phase 4 (Safe Integration)** — Create `src/janus/integration.py` with:
   - Fast-forward merge attempt (`--ff-only`)
   - Controlled merge fallback (`--no-ff`)
   - Merge conflict → abort → `kanban_block(integration_conflict)`
   - Post-merge test run on target; failure → `git reset --hard <pre-merge-sha>` → `kanban_block(post_integration_test_failure)`
   - Push target; failure → `kanban_block(target_push_failed)`
   - Remote verification (`git branch -r --contains`)
   - Evidence artifact: `integration_report.json`

2. **Create integrator profile/agent** — Separate from implementor. Either a long-running process or cron-polled workflow. Must NOT be the same agent that performed implementation.

3. **Generate evidence artifacts** — `pre_completion_report.json` (Phase 3 results) and `integration_report.json` (Phase 4 results) as specified in ADR §8.3.

### 5.2 Near-Term (Close Medium Gaps)

4. **Auto-invoke Phase 1 sync** — Wire `sync_branch()` into the dispatcher or worker prompt so it runs automatically at task start.

5. **Harden Phase 3 gate** — Add default checks:
   - Working tree clean (`git status --porcelain` empty)
   - Final fetch + re-sync loop
   - Re-run `uv run pytest` after rebase (not contract-encoded)

### 5.3 Long-Term (Reduce Drift)

6. **Deduplicate target-branch detection** — Have `git_sync.py` delegate to `web_git.py:_default_branch_name()` or vice versa to prevent logic drift.

7. **Decide on active vs passive Phase 4** — If the passive-gate model is preferred, update ADR-004 to reflect this and document the trade-off explicitly.

---

## 6. References

| Source | Location |
|---|---|
| ADR-004 specification | `docs/decisions/004-safe-sync-integrate-workflow.md` |
| Completion/integration flow survey | `findings/completion_integration_flow_survey_t_73ff09a7.md` (parent t_73ff09a7) |
| Sync/integrate implementation survey | `reports/survey_sync_integrate_findings.md` (parent t_b352e609) |
| ADR-004 claim extraction | `adr004_claims_extraction.md` (parent t_ce633bb3) |
| Phase 1 sync primitive | `src/janus/git_sync.py` — `sync_branch()`, `detect_target_branch()`, `is_branch_stale()`, etc. |
| Phase 3 contract verifier | `src/janus/verification.py` — `run_verification()`, `ImplementationContract`, `CheckResult`, `VerificationReport` |
| Completion function | `src/janus/services/tasks.py:complete_task()` (line 43) |
| Remote PR/CI check | Via `web_git.py` integration — `review_integration_state` |
| Integration design doc | `docs/specs/integration_contract.md` |
| Research: git worktree/branch sync | `docs/research/git_worktree_branch_sync_findings.md` |
| Research: PR automation gap analysis | `docs/research/pr_automation_gap_analysis.md` |

### Note on `kanban_db.py` references

Earlier research reports and this audit referenced `hermes_cli/kanban_db.py`
with specific line numbers (e.g., `_enforce_integration_gate` at ~5804,
`_enforce_janus_verification_gate` at ~5639, `complete_task()` at ~5954).
**These references are stale — `hermes_cli/` does not exist in the Janus
codebase.** The actual implementation lives in the Janus domain layer:

| Stale reference (`kanban_db.py`) | Actual codebase location |
|---|---|
| `kanban_db.py:5465` — `_enforce_repo_sync_gate` | No equivalent in Janus. Sync primitive is `src/janus/git_sync.py:sync_branch()` (line 267) |
| `kanban_db.py:5639` — `_enforce_janus_verification_gate` | `src/janus/verification.py:run_verification()` (line 1231) |
| `kanban_db.py:5804` — `_enforce_integration_gate` | No equivalent exists. ADR Phase 4 (Safe Integration) is architecturally absent. |
| `kanban_db.py:5954` — `complete_task()` | `src/janus/services/tasks.py:complete_task()` (line 43) |
| `kanban_db.py:5899` — `complete_task()` | `src/janus/services/tasks.py:complete_task()` (line 43) |

The `kanban_db.complete_task()` architecture described in the original research
was a passive-gate model from an intended (architected) design. The deployed
code has no such gate file — completion is a bare markdown edit in
`src/janus/services/tasks.py`.

---

## 7. Remaining Uncertainty

1. **Auto-invocation of Phase 1 sync:** It is unclear whether the dispatcher or worker prompt currently instructs agents to call `sync_branch()` at task start. The primitive exists but enforcement is unknown. The worker context in this session does not mention sync.

2. **Contract coverage:** The Janus verification gate is opt-in via `janus_contract:` frontmatter. The percentage of tasks that declare a contract is unknown. If low, Phase 3 gate coverage is effectively zero for most tasks.

3. **Integration agent design:** ADR-004 defers the identity of the integration agent to implementation task t_36b3d88f. No such agent/profile exists. The `docs/research/pr_automation_gap_analysis.md` and `docs/design/pr_automation_workflow_design.md` explore long-running vs. cron-polled models but neither is implemented.

4. **Current state of Phase 3 contract verification:** The 9 check types in `verification.py` are comprehensive for contract-based verification. The question is whether they are sufficient to replace the deterministic gate described in ADR-004 Phase 3. They are not — the deterministic gate checks working tree state directly, while the contract verifier checks declared expectations.

---

*Audit completed from repository state on branch `wt/t_7a55554d` at commit `baada21`. No modifications made to source code.*
