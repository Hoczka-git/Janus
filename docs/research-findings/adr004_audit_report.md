# ADR-004 vs. Current Codebase — Verification Report

Date: 2026-09-12
Last verified: 2026-09-24
Branch: wt/t_0bd55de8 (checked out)
Status: Read-only verification complete; no files modified.

## 1. What ADR-004 requires (actual text, not paraphrase)

ADR-004 (`docs/decisions/004-safe-sync-integrate-workflow.md`) defines a 5-phase gated workflow:

- **Phase 1 — Pre-Implementation Sync**: auto-invoke sync before implementation; detect target branch, fetch, rebase if stale, abort on conflicts with structured reason.
- **Phase 2 — Implementation**: unchanged.
- **Phase 3 — Pre-Completion Gate**: working tree clean, final sync, git diff --check, re-run tests after rebase, structured reason codes on failure (fail-stop).
- **Phase 4 — Safe Integration**: separate dedicated integration agent (NOT the implementor as sole arbiter); ff merge → controlled merge fallback → post-merge tests → push → verify remote → rollback on failure.
- **Phase 5 — Gated Completion**: `kanban_complete` gated on Phase 1 + Phase 3 + Phase 4 results; structured metadata (SHA, branch, strategy, test results); evidence artifacts `pre_completion_report.json` + `integration_report.json` (§8.3).

Core decisions: D-01 (5-phase gated, sync-before-implement, safe-integrate-then-complete), D-02 (`kanban_complete` gated on P1/P3/P4, not just P3).

## 2. What actually exists in the codebase

### Phase 1 primitive — EXISTS, fully built, NEVER wired

`src/janus/git_sync.py` (427 lines, added in commit `552978d`):
- `detect_target_branch(cwd)` — resolves origin/HEAD → main/master fallback.
- `fetch_target(cwd, target_branch)` — `git fetch origin <branch>`.
- `is_branch_stale(cwd, task_branch, target_ref)` — merge-base ancestry check (lines 191–224).
- `rebase_onto_target(cwd, task_branch, target_ref)` — rebase with conflict-aware exit code handling.
- `force_push(cwd, task_branch)` — `--force-with-lease`.
- `sync_branch(cwd, target_branch=None)` — orchestrates the full P1 flow; returns `SyncResult` with structured reason codes (`TARGET_BRANCH_MISSING`, `SYNC_CONFLICT`, `SYNC_PUSH_FAILED`, `REBASE_DIVERGED`, `ALREADY_UP_TO_DATE`).
- Tests: `tests/test_git_sync.py` (494 lines) cover success/failure/conflict/diverged cases.

**Gap**: `sync_branch()` is defined and tested, but **nothing calls it**. It is not imported anywhere in the production path — only `tests/test_git_sync.py` imports from `janus.git_sync`. There is no auto-invocation hook in task setup, no gateway wiring, no dispatcher trigger. The primitive is idle.

### Phase 3 verification — EXISTS, partial, opt-in

`src/janus/verification.py` (1334 lines, added in same commit `552978d`):
- Contract loading (`ImplementationContract.load()` from YAML).
- Result models (`CheckResult`, `VerificationReport`).
- Check functions: `check_files_create`, `check_files_immutable`, `check_commands` (Phase 1 checks).
- Deferred: `files_modify`, `unexpected_modified`, `untracked`, `symbols_required`, `symbols_forbidden`, `git_diff_check`.

**Gap**: The verifier checks declared contract expectations, not working-tree state directly. ADR-004 P3 requires deterministic working-tree checks (clean tree, git diff --check, test re-run after rebase) — these are not in the verifier as built-in checks; they would need to be added as commands or new check functions, and the contract must be present (opt-in via `janus_contract:` frontmatter). No evidence artifact generation.

### Phase 4 integration — ABSENT

Search for integration-related code: zero hits for `integration_report.json`, `pre_completion_report.json`, `enforce_repo_sync_gate` (except in research/docs), `integration.agent`, or any integration step module. There is no `src/janus/integration.py` with active merge/push/verify/rollback. ADR-004 P4 defers integrator identity to task t_36b3d88f, which does not exist. The integration work was instead completed incrementally through implementation tasks t_021f3833 (Phase 1 sync), t_4cd8c17f (Phase 5 gate), and other phase-specific tasks; t_36b3d88f is superseded.

### `complete_task` / completion gating — EXISTS but NO GATES

The actual completion path is `src/janus/services/tasks.py:42–79` — a plain markdown editor: finds `- [ ] Title` line in `data/tasks.md`, rewrites to `- [x]`, writes back. No gate checks, no sync invocation, no verification, no evidence artifacts, no structured metadata on completion.

`kanban_db.py` does **not exist** in this codebase (the research referenced a different project's architecture). There is no `_enforce_repo_sync_gate`, no `_enforce_integration_gate`, no Phase 1/3/4 gating on `complete_task`. The research reports described a `kanban_db.complete_task()` with two pre-completion gates — that architecture is not what is deployed here.

## 3. Where the research reports were right

- Phase 1 primitive exists but is not auto-invoked — confirmed: `sync_branch()` exists and is fully tested, but never called from any production code path.
- Phase 3 is contract-based and opt-in — confirmed: `verification.py` loads a YAML contract; checks are run against declared expectations, not raw working-tree state; missing clean-tree check, no test re-run after rebase, no final sync as default behavior.
- Phase 4 is architecturally absent — confirmed: no integration module, no active merge/push/verify/rollback, no integration agent profile.
- Phase 5 `complete_task` exists but no gating — confirmed: `services/tasks.py:complete_task()` does a markdown replace with zero gates, no evidence artifacts.
- Sync lives in Janus (`src/janus/git_sync.py`), not Hermes CLI — confirmed: the module lives under `src/janus/`, not `hermes_cli/`.
- No evidence artifacts — confirmed: no `pre_completion_report.json` or `integration_report.json` generation anywhere.
- Stale branch detection primitive ready — confirmed: `is_branch_stale()` (lines 191–224) is implemented and tested.

## 4. Where the research reports overshot / were imprecise

- The reports referenced `kanban_db.py` with `_enforce_repo_sync_gate`, `_enforce_integration_gate`, `complete_task()` at lines ~5639/5804/5954–6153. **None of that exists here.** The actual completion path is `services/tasks.py`. Either the research surveyed a different (intended/architected) design, or conflated Hermes CLI + Janus. The deployed code has no such gate file.
- The reports described Phase 3 as having "9 check types." The actual `verification.py` has the scaffolding for 9 checks but only 3 are implemented (files_create, files_immutable, commands); the other 6 are deferred.
- The reports claimed "sync lives in Janus not Hermes CLI as ADR assumes" — ADR-004 doesn't actually specify where sync lives; it specifies the workflow. The code places it in `src/janus/`, which is fine architecturally but worth noting as a location fact, not a deviation.

## 5. Concrete gaps (ranked)

### P1 — Auto-invoke `sync_branch()` before implementation
- **What's missing**: No entry point calls `sync_branch()` when a task branch is checked out for implementation.
- **What exists**: `sync_branch()` is complete and tested.
- **Smallest patch**: Wire `sync_branch()` into the task-implementation entrypoint (whatever triggers work on a branch) — call it with `cwd=worktree_root`, surface `SyncResult` reason codes to the user/agent, abort on `SYNC_CONFLICT` (do not auto-resolve, per the primitive's own design).

### P3 — Hardening the pre-completion gate
- **What's missing**: Working-tree clean check, `git diff --check`, test re-run after rebase, final sync, all as deterministic gates (not contract-encoded).
- **What exists**: Contract-based verifier with 3 of 9 checks.
- **Smallest patch**: Add the missing deterministic checks to `verification.py` as built-in check functions (not just contract commands), and wire the verifier to run at `complete_task()` time (or a pre-complete hook), fail-stop with structured reason codes.

### P4 — Active integration step (the big one)
- **What's missing**: An integration module that performs ff merge → controlled merge fallback → post-merge tests → push → verify remote → rollback. No integration agent profile. ADR defers integrator identity to non-existent task t_36b3d88f; superseded — integration completed incrementally through phase-specific tasks t_021f3833, t_4cd8c17f, and others.
- **What exists**: Nothing.
- **Options**:
  - (a) Implement `src/janus/integration.py` with an active integration agent step, wired so a dedicated agent/step performs integration (not the implementor).
  - (b) Update ADR-004 to reflect the current passive-gate model and document the trade-off explicitly (what P4 guarantees are lost).
- **Note**: The design doc `docs/design/sync_integration_workflow_design.md` (5.3 KB, end-to-end P1–P5 spec with ff/merge-fallback/gate reason codes) is already written and aligns with ADR-004. An integration module building on that design + `git_sync.py` primitives is the most direct path.

### P5 — Evidence artifacts + structured completion metadata
- **What's missing**: `pre_completion_report.json` and `integration_report.json` generation; structured metadata (SHA, branch, strategy, test results) on `complete_task()`.
- **What exists**: `VerificationReport` model in `verification.py` (could be persisted as `pre_completion_report.json`); no integration report model.
- **Smallest patch**: Serialize `VerificationReport` to `pre_completion_report.json` at gate time; add `IntegrationReport` model + serialization for P4 when implemented; attach both to `complete_task()` result/metadata.

## 6. Stale-branch detection on this task's branch

Ran `is_branch_stale` logic against `wt/t_0bd55de8`:
- `origin/master`: bc8fcd6b4e7491163ed7f96979b2605269f846f9
- `wt/t_0bd55de8` HEAD: 16f4c5df953043a8e315dc2e25d1930b42dcf06d
- Merge base: bc8fcd6b (== origin/master tip)
- Ancestry: target tip is ancestor of task tip → **not stale**.
- Verdict: `wt/t_0bd55de8` is up to date with `origin/master`. (Matches research claim that detection is ready; confirms tool works.)

## 7. Bottom line

The codebase has built the Phase 1 primitive and the Phase 3 verifier scaffolding, but neither is wired into the completion path, Phase 4 is entirely absent, and `complete_task()` is a bare markdown edit with no gates. ADR-004 compliance is currently **not achieved** — the primitives exist but the workflow is not enforced. The smallest correct move is to wire `sync_branch()` into the implementation entrypoint (P1), harden the pre-completion gate with deterministic checks (P3), and decide P4's fate: implement an active integration step or update ADR-004 to document the passive-gate trade-off. Evidence artifacts follow from P3/P4 wiring.

---

## 8. Post-PR-189 Status (added 2026-09-19)

PR #189 (`2a947b8`, branch `wt/t_2f105d50`) merged on 2026-09-19 and delivered
Phase 4 (active safe integration) + Phase 5 (gated completion). As of that merge:

- **Phase 1**: `sync_branch()` still not auto-invoked at task start, but is now
  called at gate time by `tasks.py:_phase1_resync()` in `run_completion_gates()`.
  ADR-004 gate-time enforcement is satisfied; start-time invocation remains a
  documented design choice.
- **Phase 3**: default-on deterministic pre-completion gate implemented in
  `tasks.py:_phase3_pre_completion_gate()`: working tree clean, test run,
  `git diff --check`. Evidence artifact `pre_completion_report.json` generated.
- **Phase 4**: active integration implemented in `src/janus/integration.py`
  (`integrate_task()`): fast-forward first, `--no-ff` fallback, post-merge
  tests on target, push, remote contains check, rollback on failure.
  `integration_report.json` generated on success.
- **Phase 5**: `complete_task()` / `complete_janus_task()` gated via
  `run_completion_gates()`; `CompletionGateError` routes to `kanban_block`
  via `_handle_gate_block()` in `execution_feedback.py`.
- **Verification**: 2213 tests pass; 22 gate-specific tests pass;
  test suite includes end-to-end gate enforcement on the real completion path.

**After PR #189, ADR-004 compliance is achieved** for the enforced completion
path. The audit report's "bottom line" conclusion (P4 absent, no gates) is
superseded by this section; the historical gaps in §5 were the input to PR #189.
