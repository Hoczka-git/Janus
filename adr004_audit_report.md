ADR-004 Audit Report — t_0bd55de8

Date: 2026-09-12
Task: Audit ADR-004 against current completion and integration flow
Status: Complete (research/analysis only)

## Executive Summary

ADR-004 (Safe Sync-and-Integrate Workflow for Coding Tasks) defines a 5-phase
gated workflow: Phase 1 (pre-implementation sync), Phase 2 (implementation),
Phase 3 (pre-completion gate), Phase 4 (safe integration by separate agent),
Phase 5 (gated completion). This audit evaluates whether the current Janus/Hermes
implementation matches ADR-004's normative architecture.

**Verdict: PARTIAL MATCH — Phase 4 is architecturally absent; Phase 1 primitive
exists but is not auto-invoked; Phase 3 is opt-in contract-based; Phase 5
completion has no gating on sync/integration results.**

Overall: ADR-004 describes an architecture that is only partially implemented.
The primitives for Phase 1 and Phase 3 exist but are not wired into the
completion flow. Phase 4 — the safe integration step — is entirely absent.

## Current Completion/Integration Architecture

The current architecture centers on two key files:

### src/janus/git_sync.py (427 lines, commit 552978d)

Phase 1 sync primitive. Functions:
- `detect_target_branch()` (lines 123-157): determines the target branch from
  workspace metadata
- `fetch_target()` (lines 171-182): fetches the target branch from remote
- `is_branch_stale()` (lines 191-224): compares merge-base to detect staleness
- `rebase_onto_target()` (lines 240-251): rebases task branch onto target
- `force_push()` (lines 254-264): force-pushes with --force-with-lease
- `sync_branch()` (lines 267-427): orchestrates the full sync — detect, fetch,
  check stale, rebase if needed, force-push, returns SyncResult with reason codes

Reason codes defined at lines 25-34:
- `TARGET_BRANCH_MISSING`: cannot determine target branch
- `SYNC_CONFLICT`: rebase produced conflicts (block, route to merge-reconciler)
- `SYNC_PUSH_FAILED`: force-push failed
- `REBASE_DIVERGED`: merge-base shows divergence
- `ALREADY_UP_TO_DATE`: no sync needed

Tests: `tests/test_git_sync.py` (494 lines, 20 tests passing)

### src/janus/verification.py (1334 lines, commit 552978d)

Phase 3 verification primitive. Contract-based verifier with:
- `ImplementationContract` model: loads YAML contract files with checks
- `CheckResult` / `VerificationReport` models: structured verification output
- 3 check types implemented: `check_files_create`, `check_files_immutable`,
  `check_commands`
- 6 check types deferred: `check_files_modify`, `check_files_unexpected_modified`,
  `check_files_untracked`, `check_symbols_required`, `check_symbols_forbidden`,
  `check_git_diff_check`

### hermes_cli/kanban_db.py (12803 lines, Hermes agent installation)

The Kanban board's completion gate. Two pre-completion gates exist:

1. `_enforce_janus_verification_gate()` (line 5639): runs Janus verification for
   worktree tasks with a discoverable contract. Opt-in — no contract, no gate.

2. `_enforce_integration_gate()` (line 5804): checks that the task branch is
   remotely integrated (pushed, branch exists, PR merged, CI green). Passive
   verification only — does NOT perform the merge.

Both gates run before `complete_task()`'s write transaction (lines 6037, 6042)
and fail-closed: raise an error before mutating task state.

**Missing**: no `_enforce_repo_sync_gate` — Phase 1 sync is NOT enforced at
completion time. No `sync_branch` or `git_sync` references exist in kanban_db.py
(0 matches confirmed via grep).

### src/janus/services/tasks.py (line 42)

Janus's own `complete_task()` — a bare markdown checkbox editor. Flips `[ ]` to
`[x]` in Janus domain markdown files. **No gates, no verification, no sync,
no integration check.** This is the Janus CLI's internal task completion, not the
Kanban board's `kanban_complete`.

### plugins/janus_sync/ (415 lines) + plugins/replenishment/ (915 lines)

Post-completion lifecycle hooks via `kanban_task_completed` event. These fire
AFTER the task is already `done` — they are observers, not gates. The janus_sync
plugin mirrors Hermes completion to Janus domain objects (goals, tasks, milestones);
the replenishment plugin pulls next items from roadmap. Neither enforces any
pre-completion check.

## ADR-004 Requirements That Changed/Don't Match

### Phase 1 — Pre-Implementation Sync: PARTIAL

**What exists**: Full sync primitive in `git_sync.py` (427 lines, tested, working).
`sync_branch()` implements the complete flow: detect target, fetch, check stale,
rebase, force-push, with structured reason codes.

**What's missing**: The primitive is NOT auto-invoked. Nothing calls
`sync_branch()` at task start or completion. ADR-004 §3.1 requires sync "before
implementation begins (or when a worktree is discovered to be stale)". The
primitive sits idle.

### Phase 2 — Implementation: MATCH

Unchanged per ADR-004. Implementor works in isolated worktree.

### Phase 3 — Pre-Completion Gate: PARTIAL

**What exists**: Contract-based verifier in `verification.py`. When a task carries
a `janus_contract:` frontmatter pointing to a contract YAML, the gate runs
verification checks.

**What's missing**:
- The gate is **opt-in** via contract frontmatter, NOT deterministic as ADR-004
  requires. ADR-004 §3.3 mandates: working tree clean, final sync, re-run tests
  after rebase, `git diff --check` — as mandatory checks, not contract-encoded.
- Only 3 of 9 planned checks are implemented; 6 are deferred.
- No working-tree clean check (ADR-004 §3.3.1)
- No final sync before gate (ADR-004 §3.3.2)
- No test re-run after rebase (ADR-004 §3.3.3)
- No `git diff --check` (ADR-004 §3.3.4) — though `check_git_diff_check` is
  listed as a deferred check type

### Phase 4 — Safe Integration: DIVERGES (Absent)

**What exists**: Passive integration verification gate in `kanban_db.py`
(`_enforce_integration_gate` at line 5804). Checks remote state: has unpushed
commits, remote branch exists, PR exists, PR merged, CI state. Fails if any
check fails.

**What's missing**:
- No active integration step — the gate VERIFIES but does NOT PERFORM the merge.
- No dedicated integration agent/step. ADR-004 §3.4 requires a separate agent
  that does ff-merge → controlled merge fallback → post-merge tests → push →
  verify remote → rollback on failure.
- The current gate is passive: it checks that integration happened, but doesn't
  ensure it happens. An implementor could theoretically call `kanban_complete`
  without ever having integrated (the gate would block, but the integration
  action itself is not automated).
- ADR-004 §3.4 step 1: "verify task branch contains latest target" — not
  automated; relies on Phase 1 sync which is not auto-invoked.
- No rollback mechanism (ADR-004 §3.4.4): `git reset --hard <pre-merge-sha>`
  on post-merge test failure.
- No post-merge test suite execution (ADR-004 §3.4.3).

**Stakeholder gap**: ADR-004 explicitly states Phase 4 must be performed by a
dedicated integration step/agent "not the sole arbiter of the implementor" (P4-01).
The current architecture has no such agent. The deferred task t_36b3d88f from the
original ADR-004 implementation was supposed to define this but does not exist.

### Phase 5 — Gated Completion: PARTIAL

**What exists**: `complete_task()` in kanban_db.py with two pre-completion gates
(Janus verification + integration check). Both fail-closed.

**What's missing**:
- No gating on Phase 1 sync results — `kanban_complete` does not check that
  sync was performed.
- No structured metadata on completion (ADR-004 §3.5 requires: commit SHA, target
  branch, merge strategy, test results).
- No evidence artifacts: `pre_completion_report.json` and `integration_report.json`
  per ADR-004 §8.3 are not generated.
- The Janus verification gate is opt-in (contract-based), not deterministic.

## ADR-004 Requirements That Still Hold

### Decision (ADR-004 §2)

The core decision — that `kanban_complete` should be gated on sync, verification,
and integration — still holds. The current architecture has two of the three gates
(Jupiter verification + integration check), but the sync gate is missing and the
verification gate is opt-in.

### Failure Semantics (ADR-004 §3.6)

The current gates follow fail-stop semantics: both `_enforce_janus_verification_gate`
and `_enforce_integration_gate` raise errors before the write transaction, preserving
workspace state. This matches ADR-004's intent.

### Replenishment Interaction (ADR-004 §6)

The current architecture has post-completion lifecycle hooks (janus_sync,
replenishment) that fire via `kanban_task_completed` event. These are observers
that run after completion — consistent with ADR-004's model where replenishment
is a post-completion concern.

## What Happened to the Original ADR-004 Implementation

The original ADR-004 implementation (task t_ad23793c and children) completed and
was archived. The implementation added:
- `git_sync.py` — Phase 1 sync primitive
- `verification.py` — Phase 3 verification scaffolding
- ADR-004 decision document

After completion, the codebase evolved:
- The Kanban board's `complete_task()` gained integration gate
- The janus_sync plugin was added for Hermes→Janus feedback
- The replenishment plugin was added for roadmap-driven task creation

The Phase 4 integration step (t_36b3d88f) was never implemented. The Phase 1
sync primitive was never wired into the completion flow. The Phase 3 verifier
remains contract-based and opt-in.

## Post-ADR-004 Changes (Commits)

- `552978d`: Added `src/janus/git_sync.py` and `src/janus/verification.py`
  (Phase 1 + Phase 3 primitives)
- `9163de4` (PR #102): Merge from t_69ab5211
- `baada21`: Fix missing Union import in workout_md.py
- `256acd1`: Fix missing Union import in workout_md.py

The ADR-004 decision document was written by the original implementation and has
not been updated since.

## ADR Status Recommendation

**ADR-004 should be updated, not superseded.**

The decision (gated workflow for coding tasks) remains valid. However, the
implementation status has diverged from the ADR's description:
- Phase 4 is absent — the ADR describes an active integration step that doesn't
  exist; the current architecture has only passive integration verification
- Phase 1 sync is not auto-invoked despite the primitive existing
- Phase 3 is opt-in rather than deterministic
- Phase 5 lacks evidence artifacts

**Minimum documentation change**: Update ADR-004 §3.4 (Phase 4) to reflect the
current passive-gate architecture, document the trade-off (passive verification
vs. active integration), and create a follow-up task for the missing integration
agent. Alternatively, update the status to "Accepted with amendments" and track
the gaps as open implementation issues.

**Do NOT create a new ADR that supersedes ADR-004** — the decision itself remains
valid. The gaps are implementation gaps, not decision changes.

**Do NOT reimplement Phase 4** as part of this audit — that's a separate
implementation task if the decision is to pursue it.

## Concrete Evidence

1. `git_sync.py` exists and is tested (20 tests passing) but not wired into any
   completion path — confirmed by grep for `sync_branch` in kanban_db.py: 0 matches

2. `verification.py` exists with 3/9 checks implemented — confirmed by reading
   the file and counting check types

3. `kanban_db.py` has `_enforce_janus_verification_gate` (line 5639) and
   `_enforce_integration_gate` (line 5804) but NO `_enforce_repo_sync_gate` —
   confirmed by grep

4. `complete_task()` in kanban_db.py calls both gates before write_txn (lines
   6037, 6042) — confirmed by reading lines 6030-6045

5. No evidence artifact generation exists — confirmed by grep for
   `pre_completion_report` and `integration_report` in the codebase: 0 matches

6. The janus_sync plugin (415 lines) and replenishment plugin (915 lines) are
   post-completion observers, not pre-completion gates — confirmed by reading
   their source

## Deliverables

- This report: `adr004_audit_report.md`
- Verification report: `verification_adr004.md` (preliminary, superseded by this)

## Tests Run

- `tests/test_git_sync.py`: 20 passed in 7.53s (Phase 1 primitives verified working)
- `tests/test_verification.py`: not run (Phase 3 contract verifier, opt-in)

## ADR-004 Requirements That Still Hold

The following ADR-004 requirements still match the current architecture:

1. **Gated completion** — `kanban_complete` is gated on verification + integration
   (two of three required gates; sync gate missing)

2. **Fail-stop semantics** — both gates raise errors before write_txn, preserving
   workspace state

3. **Post-completion replenishment** — lifecycle hooks fire after completion

4. **Worktree isolation** — Phase 2 implementation unchanged

5. **Opt-in for non-code tasks** — integration gate can be declined via
   `integration_required: false`

## ADR-004 Requirements That Changed

1. **Phase 1 sync is not auto-invoked** — primitive exists but not wired
2. **Phase 3 is opt-in, not deterministic** — contract-based, not mandatory checks
3. **Phase 4 is absent** — no active integration step, only passive verification
4. **Phase 5 lacks evidence artifacts** — no pre_completion_report.json or
   integration_report.json
5. **Phase 5 lacks structured metadata** — no SHA, branch, strategy, test results
   on completion

## ADR-004 Is Still Canonical (With Amendments Needed)

ADR-004 remains the architectural decision for safe sync-and-integrate workflow.
The decision is valid; the implementation is incomplete. The ADR should be updated
to reflect the current state (passive integration gate vs. active integration step)
and track the remaining gaps as implementation issues.

## Recommended Actions (Not Implemented Here)

1. **Update ADR-004 §3.4** to document the current passive integration gate and
   the trade-off vs. active integration
2. **Create follow-up task** for Phase 4 integration agent (or accept passive gate
   as the architectural decision and update ADR accordingly)
3. **Wire `sync_branch()` into task start** — Phase 1 auto-invocation (P1 gap)
4. **Harden Phase 3 gate** — add deterministic checks (clean tree, final sync,
   test re-run, git diff --check) as mandatory, not just contract-based
5. **Generate evidence artifacts** — pre_completion_report.json,
   integration_report.json per ADR-004 §8.3

## Conclusion

ADR-004 describes a 5-phase gated workflow. The current implementation has:
- Phase 1: primitive exists, not auto-invoked (PARTIAL)
- Phase 2: match (MATCH)
- Phase 3: contract-based opt-in, 3/9 checks, missing deterministic checks (PARTIAL)
- Phase 4: absent — only passive verification, no active integration step (DIVERGES)
- Phase 5: two gates exist but no sync gating, no evidence artifacts, no structured
  metadata (PARTIAL)

Overall: PARTIAL MATCH. ADR-004 should be updated to reflect the current
architecture (particularly the absent Phase 4) and track remaining gaps as
implementation issues. The decision itself remains valid and canonical.