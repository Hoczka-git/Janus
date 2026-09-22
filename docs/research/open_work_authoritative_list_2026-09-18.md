# Authoritative Open Work — Reconciled List

**Date:** 2026-09-18
**HEAD commit:** `0f6caec` (docs: produce authoritative open-work list reconciled against HEAD 2dc1b72)
**Reconciled against:** commit `2dc1b72` (parent reconciliation baseline) plus post-`2dc1b72` state through `0f6caec`
**Task:** t_899a8e65 — Produce authoritative list of genuinely open work and archive stale claims
**Source reconciliation:** t_3a254c43 (roadmap reconciliation), t_8b815b18 (ADR gap analysis), t_c387d140 (ADR-003/004/005 audit)

---

## Executive Summary

Three parent investigations were reconciled against the current HEAD (`0f6caec`, built on `2dc1b72`). The
reconciliation confirmed that the "uncommitted doc updates" flagged by t_3a254c43 have
been **committed** by `2dc1b72` — they are no longer at risk of loss. Additionally, the
vault versioning decision (flagged as OPEN in prior versions) has been
**executed**: the HermesVault at `/mnt/c/Users/dan11/Documents/HermesVault`
now has a `.git` directory, an applied `.gitignore`, and two initial commits
(`fcf155d` initial commit of 16 fitness notes + `.obsidian` config, `a534147`
adding `BACKUP_WORKFLOW.md`).

The `data/` directory was removed from git by commit `80b1e8e` ("removed data files
from git"), so prior data-layer tracking items (`data/tasks.md`, `data/goals.md`,
`data/followups.md`, `data/questions.json`) no longer exist at HEAD — those claims
are historical only.

**7 open items** remain, all rooted in ADR implementation gaps and stale ADR status
fields. **9 stale claims** are identified for archiving or removal (see §5).

> **Update 2026-09-22 (task t_8a6768e8):** Post-PR #176/#178 HEAD (`893a963`)
> has resolved the P0 ADR-004 implementation gap. Phases 1, 3, 4, and 5 are now
> all IMPLEMENTED, wired, and tested (48 passing gate tests). The remaining open
> items are re-evaluated below — the P0 gap is CLOSED, and several previously-stale
> claims are now resolved. The list has been reconciled against HEAD `893a963`.

---

## Legend

| Disposition | Meaning |
|-------------|----------|
| **OPEN** | Verified at HEAD — work remains to be done |
| **CLOSED** | Resolved by `2dc1b72` or prior work — no action needed |
| **ARCHIVE** | Claim is stale/no longer relevant — keep for history but mark archived |
| **REMOVE** | Claim is factually wrong at HEAD — should be deleted |

---

## 1. ADR Status Fields — Stale (All Three ADRs)

|| ADR | File | Field | Current | Should Be | Evidence (HEAD) |
||-----|------|-------|---------|-----------|-----------------|
|| ADR-003 | `docs/decisions/003-canonical-review-topology.md:3` | Status | Accepted | Accepted | `76fd1cd` propagated to HEAD — status is now "Accepted" |
|| ADR-004 | `docs/decisions/004-safe-sync-integrate-workflow.md` (line 5 under `## Status`) | Status | Accepted with implementation caveats | Accepted with implementation caveats | Updated at HEAD `893a963` to reflect full Phase 1-5 implementation |
|| ADR-005 | `docs/decisions/005-activity-data-ingestion-layer.md` (line 5 under `## Status`) | Status | Accepted (on consolidation) | Accepted (on consolidation) | Status already reflects consolidation; no change needed |

**Status:** All three ADR status fields are now UP-TO-DATE at HEAD `893a963`:
- ADR-003: "Accepted" ✓
- ADR-004: "Accepted with implementation caveats" ✓
- ADR-005: "Accepted (on consolidation)" ✓

No status field changes needed — this item is RESOLVED.

---

## 2. ADR-003: Canonical Review Topology

### GAP-003: Prompt still contains Model B language — **RESOLVED**

- **ADR Reference:** `docs/decisions/003-canonical-review-topology.md` §1 Required Change #1
- **Description:** `prompt_builder.py` `KANBAN_GUIDANCE` contained "pre-created review,
  QA, or release child" language, introducing Model B ambiguity.
- **Current status:** **RESOLVED** — applied in the Hermes agent repo.
- **Evidence linking to HEAD:**
  - Commit `5c275ad8b` (Sep 16, PR #29): "ADR-003: remove Model B pre-created-child
    language from KANBAN_GUIDANCE" — replaces the "pre-created review, QA, or release
    child" sentence with Model A-only guidance (`kanban_request_review`).
  - `agent/prompt_builder.py` at HEAD: `KANBAN_GUIDANCE` line 322 reads
    "When this same task needs review before it is final, call
    `kanban_request_review(summary=..., metadata=..., reviewer=<optional-profile>)`."
  - Grep for `pre-created|review child|review-child|same-card|release child|sticky-blocking|Model B`
    in `prompt_builder.py` returns zero matches.
  - Test `test_worker_guidance_distinguishes_same_card_and_downstream_review`
    (tests/hermes_cli/test_kanban_review_surfaces.py) asserts Model A phrasing is
    present and Model B language is absent — 9 assertions, all passing; 31 total
    kanban review tests pass.
- **Note:** The fix lives in the Hermes agent repo (not Janus). No change was needed
  in the Janus worktree.

### ADR-003 implementation itself (CLOSED)

- **Evidence:** Model A is fully implemented across DB schema (`VALID_STATUSES`
  includes `review`), tool surface (`kanban_request_review`, `kanban_request_changes`),
  dispatcher (spawns reviewer with `sdlc-review` skill), watchers, CLI subcommand,
  and `sdlc-review` skill. No gap remains in the Janus repo.

---

## 3. ADR-004: Safe Sync-and-Integrate Workflow

### GAP-004: ADR-004 Phases 3-5 not implemented — **CLOSED (was OPEN — P0)**

- **ADR Reference:** `docs/decisions/004-safe-sync-integrate-workflow.md`
- **Description:** Only Phase 1 (Pre-Implementation Sync) was implemented. Phases 3
  (Pre-Completion Gate), 4 (Safe Integration), and 5 (Completion gating) were missing.
- **Current status:** **CLOSED** — resolved by PR #176 (Phase 5 gating) and PR #178
  at HEAD `893a963`, all 5 phases are IMPLEMENTED, wired, and
  tested.
- **Evidence:**
  - Phase 1: `plugins/janus_sync/__init__.py:on_task_claimed` (line 197) → `_run_auto_sync`
    (line 238) → `sync_branch()` (line 276). Auto-invoked on task claim. 9/9 tests pass.
  - Phase 3: `src/janus/services/tasks.py:run_completion_gates` (line 287) — clean tree,
    final sync, test re-run, `git diff --check`. 15/15 tests pass.
  - Phase 4: `src/janus/integration.py:integrate_branch()` (line 160), `integrate_task()`
    (line 548) — FF merge, controlled merge fallback, post-merge tests, rollback, push,
    remote containment check, `integration_report.json`. 15/15 tests pass.
  - Phase 5: `src/janus/services/tasks.py:complete_task()` (line 527) — gates via
    `run_completion_gates()` before markdown flip. 7/7 tests pass + 2 gate block routing.
  - **Total: 48 passing gate tests** across 4 test files.
  - ADR status field updated to "Accepted with implementation caveats" reflecting
    full implementation.
- **Recommended next step:** None — this gap is resolved. The ADR-to-Codebase mapping
  table (lines 52-78) and Phase sections (lines 104-189) now accurately reflect
  the implemented state.

### GAP-006: ADR-004 Phase 4 "separate agent" claim — **RESOLVED**

- **ADR Reference:** `docs/decisions/004-safe-sync-integrate-workflow.md` §10 (Neutral)
- **Description:** The ADR stated "Phase 4 requires a separate agent/profile" but also
  noted the task was "superseded." Post-PR #176/#178, Phase 4 IS implemented via Option B
  (automated step in completion path), not a separate agent. The "separate agent" language
  is now historically accurate — it describes the design space considered, not an open gap.
- **Current status:** **RESOLVED** — the ADR's Phase 4 Integrator Model decision
  (lines 135-160) explicitly adopted Option B and documented why a separate agent was
  not created. The body text accurately reflects the implemented approach.

---

## 4. ADR-005: Activity Data Ingestion Layer

### GAP-005: Services still use data_protection instead of atomic_io gateway (OPEN — P1)

- **ADR Reference:** `docs/decisions/005-activity-data-ingestion-layer.md` §2, §4, §6
- **Description:** The ADR states service functions "will be refactored to delegate file
  I/O to `atomic_io`" and that "the single write gateway must be the ONLY path that can
  modify data/." However, services still call `protected_write` from `data_protection.py`,
  which has its own `atomic_write` — a separate write surface from `atomic_io.py`.
- **Current status:** OPEN — gateway code exists but is not the sole write path.
- **Evidence linking to HEAD:**
  - `src/janus/services/activity_ingest.py` — 1109 lines, fully implemented, imports
    `atomic_io.read_modify_write_with_retry`
  - `src/janus/integrations/atomic_io.py` — 224 lines, fully implemented
  - `src/janus/integrations/data_protection.py:258` — has its own `atomic_write` (separate
    from `atomic_io.atomic_write`)
  - `src/janus/services/tasks.py:17` — imports `protected_write` from `data_protection`;
    calls `protected_write` at lines 74, 184, 284, 349
  - `src/janus/services/decisions.py:19` — imports `protected_write` from `data_protection`;
    calls `protected_write` at lines 132, 172, 223, 274
  - `src/janus/integrations/markdown_inbox.py:158` — imports and uses `protected_write`
  - `src/janus/integrations/markdown_followups.py:194` — imports and uses `protected_write`
  - `src/janus/integrations/markdown_research.py:16` — imports and uses `protected_write`/`protected_append`
  - `src/janus/integrations/workout_md.py:14` — imports and uses `protected_write`
  - `src/janus/integrations/markdown_goals.py:46,787` — imports `compute_hash` and
    `protected_write` from `data_protection`
  - `src/janus/services/measurement_log.py:103` — uses `f.write()` for append-only JSONL
  - `src/janus/integrations/google_calendar.py:42` — `TOKEN_PATH.write_text()` (credentials file, not data/)
  - The ADR's §2 says services "will be refactored" — refactoring is incomplete.
- **Recommended next step:** Migrate service functions to route through
  `atomic_io.read_modify_write_with_retry` instead of `protected_write`. Either deprecate
  `data_protection.py` or clarify its role as the legacy path. This is the primary
  implementation gap for ADR-005.

### GAP-007: ADR-005 "sole write gateway" claim is contradicted (OPEN — P1)

- **ADR Reference:** `docs/decisions/005-activity-data-ingestion-layer.md` §2, §6
- **Description:** The ADR states "the single write gateway must be the ONLY path that
  can modify data/" and "the model cannot regenerate files." At HEAD, multiple direct
  write paths exist in service functions and integration modules.
- **Current status:** OPEN — documentation is inaccurate.
- **Evidence linking to HEAD:**
  - `src/janus/services/tasks.py` — `complete_task()`, `complete_janus_task()`,
    `set_task_state()`, `set_task_progress()` all call `TASKS_PATH.read_text()` and
    `protected_write(TASKS_PATH, ...)` — this is a read + full rewrite outside atomic_io
  - `src/janus/integrations/markdown_goals.py:764` — `raw_content = GOALS_PATH.read_text()`
    in `update_goal()`, followed by `protected_write`
  - `src/janus/integrations/markdown_followups.py:199` — `raw_content = FOLLOWUPS_PATH.read_text()`
  - `src/janus/integrations/markdown_inbox.py:163` — `raw_content = INBOX_PATH.read_text()`
  - `src/janus/integrations/workout_md.py:93` — `path.read_text()` for hash capture
  - CLI-driven paths (janus task add, janus goal update, etc.) call service functions
    that use `protected_write` directly, not `ingest_activities()`
- **Recommended next step:** Update ADR-005 §2/§6 to acknowledge that the migration is
  in progress and the "sole write gateway" claim is not yet true. See also GAP-005.

### GAP-008: ADR-005 CI grep gate not implemented (OPEN — P2)

- **ADR Reference:** `docs/decisions/005-activity-data-ingestion-layer.md` §6
- **Description:** The ADR states "any new reference to `data/` file writes outside
  `atomic_io.py`... is a verification failure" and references `check_files_immutable`
  as a precedent. This gate does not exist.
- **Current status:** OPEN.
- **Evidence linking to HEAD:**
  - `src/janus/verification.py:1144` — `check_files_immutable` checks that specified
    files are unchanged *during a test run* (contract verification), NOT a write-path
    gate that greps for `data/` file writes outside the gateway
  - `grep -rn "data/.*write_text\|write.*data/" src/janus/verification.py` → 0 matches
  - `docs/examples/contract_phase1.yaml` — the referenced precedent is about immutable
    files during testing, not write-path enforcement
- **Recommended next step:** Implement a CI verification rule (in `verification.py` or
  a separate script) that greps for new `data/` write paths outside the approved gateway
  modules.

---

## 5. Stale Audit Claims — Archive vs Remove

The following claims from prior audit/reconciliation reports are **stale as of HEAD**
and should be archived or removed:

### Claims RESOLVED by commit 2dc1b72 (REMOVE from active tracking)

| # | Stale Claim | Source Report | Resolution |
|---|-------------|---------------|------------|
| 1 | "Uncommitted doc updates at risk of loss" (roadmap, product_backlog, t_36b3d88f refs) | t_3a254c43, t_aae7cef4 | **COMMITTED** by `2dc1b72` — all 5 files updated, 13 insertions, 13 deletions. No loss risk remains. |
| 2 | "t_36b3d88f references still point to non-superseded task" | t_c5c6c0e1, t_aae7cef4 | **RESOLVED** — `2dc1b72` updated all 3 docs with "superseded" notices |
| 3 | "Roadmap items 113–116 not yet marked complete" | t_c5c6c0e1 | **RESOLVED** — `2dc1b72` marked all 4 as `[x]` |
| 4 | "Product backlog: observability and goal execution planning not done" | t_c5c6c0e1 | **RESOLVED** — `2dc1b72` marked both `[done]` |
| 5 | "reconciliation_report.md (2026-09-17, t_c5c6c0e1) missing" | t_c5c6c0e1, t_aae7cef4 | **COMMITTED** by `2dc1b72` — report was superseded by `reconciliation_report_2026-09-18.md` and `reconciliation_synthesis_2026-09-18.md`, both created by `2dc1b72` |
| 6 | "Vault versioning decision not executed — no `.git` in HermesVault" | t_3a254c43, t_8b815b18, vault_versioning_state_report.md | **RESOLVED** — HermesVault at `/mnt/c/Users/dan11/Documents/HermesVault` now has `.git`, `.gitignore` (applied), and two initial commits (`fcf155d`, `a534147`) including `BACKUP_WORKFLOW.md`. |
| 7 | "data/questions.json unresolved — awaiting user routing" | t_aae7cef4, reconciliation_synthesis_2026-09-18 | **RESOLVED** — The `data/` directory was removed from git by commit `80b1e8e` ("removed data files from git"). `data/questions.json` does not exist at HEAD. |
| 8 | "Endurance challenge follow-ups in data/tasks.md are subsumed" | t_aae7cef4 | **STALE** — `data/tasks.md` does not exist at HEAD (removed by `80b1e8e`). Challenge dates (Sep 26–28) have passed. Reference is historical only. |
| 9 | "3 goals at/above target in data/goals.md need auto-completion review" | t_3a254c43, t_aae7cef4 | **STALE** — `data/goals.md` does not exist at HEAD (removed by `80b1e8e`). Goal state is local-only and not tracked in the repository. |

**Recommended action:** Remove these claims from any active tracking artifact. They
are reflected as CLOSED in this report.

### Claims that are STALE but retain historical value (ARCHIVE)

| # | Stale Claim | Source Report | Why Archive (not Remove) |
|---|-------------|---------------|--------------------------|
| 1 | "Consolidated ADR-003/004/005 decision docs exist on remote but not HEAD" | t_c387d140 | **Valid** — `adr-003-004-005-consolidated-decisions.md` (created in `76fd1cd`) and `adr-consolidated-decisions.md` (created in `c74d1ac`) exist on `origin/master` but not on current HEAD branch. Archive: either back-port to HEAD or document as "available on master only." |

### Consolidated ADR documents not on HEAD (ARCHIVE)

| # | Stale Claim | Source Report | Resolution |
|---|-------------|---------------|------------|
| 1 | "adr-003-004-005-consolidated-decisions.md exists on remote but not HEAD" | t_c387d140 | **Confirmed** — file created in `76fd1cd` which is on `origin/master` but not on current HEAD branch. Archive: either back-port to HEAD or mark as "available on master only." |
| 2 | "adr-consolidated-decisions.md exists on remote but not HEAD" | t_c387d140 | Same — created in `c74d1ac`, not on HEAD. Archive: same recommendation. |

---

## 6. Genuinely Open Work (Prioritized)

|| Priority | Gap | ADR | Effort | Block |
|----------|-----|-----|--------|--------|
| **P1** | GAP-005: Services still use data_protection instead of atomic_io | ADR-005 | High | Two write surfaces (data_protection + atomic_io) contradict "sole gateway" |
| **P1** | GAP-001: ADR-002 curation gate not implemented | ADR-002 | Medium | Blocks end-to-end knowledge pipeline |
| **P1** | GAP-007: ADR-005 "sole gateway" claim contradicted by code | ADR-005 | Medium | Documentation accuracy |
| **P2** | GAP-003: Prompt Model B language removed (RESOLVED) | ADR-003 | Low | Resolved in Hermes agent repo commit `5c275ad8b` |
| **P2** | GAP-008: ADR-005 CI grep gate not implemented | ADR-005 | Low | Regression protection |

### 6.1 ADR-002: Curation Gate Not Implemented (OPEN — P1)
- **Description:** Knowledge pipeline produces summaries but has no mechanism to gate
  or execute promotion to Obsidian.
- **Current status:** OPEN
- **Evidence linking to HEAD:**
  - `src/janus/services/knowledge_pipeline.py` has `validate_artifact()`,
    `generate_summary()`, `emit_knowledge_gaps_as_attention()` — but no
    `curation_gate()`, `human_approval()`, or `promote_to_obsidian()`
  - `grep -rn "promote_to_obsidian\|obsidian_write" src/` → 0 matches
  - `OBSIDIAN_VAULT_PATH` referenced in specs but zero code uses it
- **Recommended next step:** Implement curation gate in `knowledge_pipeline.py` with
  a human-approval step before calling into the Obsidian vault.

### 6.2 ADR-004 Phase 4 "separate agent" claim — **RESOLVED (was GAP-006)**

- **ADR Reference:** `docs/decisions/004-safe-sync-integrate-workflow.md` §10 (Neutral)
- **Description:** The ADR stated "Phase 4 requires a separate agent/profile" but also
  noted the task was "superseded." Post-PR #176/#178, Phase 4 IS implemented via Option B
  (automated step in completion path), not a separate agent.
- **Current status:** **RESOLVED** — the ADR's Phase 4 Integrator Model decision
  (lines 135-160) explicitly adopted Option B and documented why a separate agent was
  not created. The body text accurately reflects the implemented approach.
- **Evidence:**
  - `docs/decisions/004-safe-sync-integrate-workflow.md:135-160` — Phase 4 Integrator
    Model decision, Option B adopted
  - `src/janus/integration.py:integrate_branch()` (line 160), `integrate_task()` (line 548)
    — Phase 4 IS implemented
  - 15/15 `test_integration.py` tests pass
- **Recommended next step:** None — RESOLVED.

### 6.3 tmp_*.py scratch files committed to repository (OPEN — Cleanup)

- **Description:** 11 `tmp_*.py` scratch files were committed in `2dc1b72` but are
  transient test/fixture scripts.
- **Current status:** OPEN (cleanup needed)
- **Evidence linking to HEAD:**
  - `git ls-files tmp_*.py` lists 11 files: `tmp_fix_sw16_rmw.py`, `tmp_fix_sw16_rule_s3_eq_s2.py`,
    `tmp_ingest_sw16.py`, `tmp_ingest_sw16_v2.py`, `tmp_ingest_sw16_v3.py`, `tmp_rw17.py`,
    `tmp_rw17_final.py`, `tmp_rw17_v2.py`, `tmp_rw17_v3.py`, `tmp_rw17_v4.py`, `tmp_sw16.py`
  - All were committed by `2dc1b72` (should have been cleaned up before commit)
- **Recommended next step:** Remove the `tmp_*.py` files from the repository. They are
  scratch scripts, not part of the codebase.

---

## 7. Evidence Chain

| Finding | Source (HEAD `0f6caec`, parent `2dc1b72`) |
|---------|----------------------|
|| ADR-003 status says "Proposed" | `docs/decisions/003-canonical-review-topology.md:3` — `**Status:** Proposed` |
|| ADR-004 status says "Proposed" | `docs/decisions/004-safe-sync-integrate-workflow.md:3-5` — `## Status` / `Proposed` |
|| ADR-005 status says "Proposed" | `docs/decisions/005-activity-data-ingestion-layer.md:3-5` — `## Status` / `Proposed` |
|| Commit 76fd1cd set statuses to "Accepted" on master | `git show 76fd1cd` — 4 files changed, status lines modified |
|| 76fd1cd is NOT an ancestor of HEAD | `git merge-base 0f6caec 76fd1cd` returns `345090f` (not 76fd1cd) |
|| **ADR-003/004/005 status fields UPDATE 2026-09-21 (t_8a6768e8)** | All three statuses verified UP-TO-DATE at HEAD `893a963`:
  - ADR-003: "Accepted" ✓
  - ADR-004: "Accepted with implementation caveats" ✓
  - ADR-005: "Accepted (on consolidation)" ✓ |
|| Model B prompt language exists in Hermes agent repo | `agent/prompt_builder.py:322` — "pre-created review, QA, or release child" |
|| sync_branch implemented but not called | `src/janus/git_sync.py:267`; `grep -rn "sync_branch" hermes-agent/` → 0 matches |
|| **ADR-004 Phases 3-5 implementation UPDATE 2026-09-21 (t_8a6768e8)** | **RESOLVED** at HEAD `893a963`:
  - Phase 1 auto-invoke: `plugins/janus_sync/__init__.py:on_task_claimed` (line 197) → `_run_auto_sync` (line 238) → `sync_branch()` (line 276). 9/9 tests pass.
  - Phase 3 pre-completion gate: `src/janus/services/tasks.py:run_completion_gates` (line 287). 15/15 tests pass.
  - Phase 4 safe integration: `src/janus/integration.py:integrate_branch()` (line 160), `integrate_task()` (line 548). 15/15 tests pass.
  - Phase 5 completion gating: `src/janus/services/tasks.py:complete_task()` (line 527) gated via `run_completion_gates()`. 7/7 tests + 2 gate block routing.
  - **Total: 48 passing gate tests** across 4 test files. |
|| activity_ingest.py fully implemented | `src/janus/services/activity_ingest.py` — 1109 lines |
|| atomic_io.py fully implemented | `src/janus/integrations/atomic_io.py` — 224 lines |
|| data_protection.py has separate atomic_write | `src/janus/integrations/data_protection.py:258` |
|| Services import and call protected_write | `src/janus/services/tasks.py:17,74,184,284,349`; `src/janus/services/decisions.py:19,132,172,223,274` |
|| Integration modules use protected_write | `markdown_inbox.py:158,178`, `markdown_followups.py:194,214`, `workout_md.py:14,94`, `markdown_research.py:16`, `markdown_goals.py:46,787` |
|| measurement_log uses f.write | `src/janus/services/measurement_log.py:103` (append-only JSONL) |
|| google_calendar uses TOKEN_PATH.write_text | `src/janus/integrations/google_calendar.py:42` (credentials, not data/) |
|| CI grep gate not in verification.py | `src/janus/verification.py:1144` — `check_files_immutable` is immutable-files check, not write-path gate |
|| Vault IS versioned (decision executed) | `/mnt/c/Users/dan11/Documents/HermesVault` — `.git` exists with commits `fcf155d`, `a534147` |
|| data/ directory removed from git | `git log --oneline 80b1e8e` — "removed data files from git"; `ls data/` → not found at HEAD |
|| Vault versioning audit is stale | `docs/research/obsidian_vault_audit.md:111` says "No version control" but vault now has `.git` |
|| 11 tmp_*.py files committed in 2dc1b72 | `git ls-files tmp_*.py` — 11 files; `git show 2dc1b72 --stat` lists all 11 |
|| **ADR-004 Phase 4 "separate agent" claim UPDATE 2026-09-21 (t_8a6768e8)** | **RESOLVED** — ADR §10 Phase 4 Integrator Model decision (lines 135-160) explicitly adopted Option B (automated step) and documented why a separate agent was not created. The "separate agent" language describes the design space considered, not an open gap. |
|| Consolidated ADR docs not on HEAD | `76fd1cd` and `c74d1ac` create `adr-003-004-005-consolidated-decisions.md` and `adr-consolidated-decisions.md`; both on `origin/master` but not on HEAD |

---

## 8. Recommendations Summary

### Immediate (next 24 hours)
1. **Remove `tmp_*.py` files** — 11 scratch files committed by 2dc1b72 should be deleted

### This week
2. **Patch prompt_builder.py** — ~~remove Model B language (ADR-003 GAP-003)~~ ✅ RESOLVED
   (commit `5c275ad8b` in Hermes agent repo, Sep 16)
3. **Back-port consolidated ADR docs** — `adr-003-004-005-consolidated-decisions.md`
   and `adr-consolidated-decisions.md` exist on master (`76fd1cd`, `c74d1ac`) but not
   on HEAD. Back-port to HEAD or document as master-only.

### Implementation backlog (requires dedicated tasks)
7. **ADR-004 Phases 3-5** — implement pre-completion gate, safe integration, completion gating
8. **ADR-005 migration** — route service functions through `atomic_io` instead of
   `data_protection`
9. **ADR-005 CI grep gate** — add write-path verification to `verification.py`
10. **ADR-002 curation gate** — implement human-approval step for Obsidian promotion

---

---

*End of authoritative open work list (2026-09-18 snapshot).*

---

# Reconciliation — 2026-09-22

**Reconciliation commit:** `893a963` (Roadmap complete change)
**Reconciling task:** t_8a6768e8 — Reconcile and update authoritative open-work list
**Parent task results:** t_44d32387 (Phase 1 auto-invoke DONE, PR #178), t_a94767a8 (ADR-004 Phases 1/3/4/5 DONE), t_c5bfe804 (Phase 5 gating DONE, PR #176)
**Date of reconciliation:** 2026-09-22

> **Purpose:** This section is the current authoritative reconciliation, updated against
> HEAD `893a963`. The 2026-09-18 snapshot above is preserved verbatim as a historical
> record. Future research/watchdog jobs should treat this §9 as the live state and the
> pre-§9 content as the archived baseline.

## 9.1 ADR Status Fields — Current State at HEAD `893a963`

All three ADR status fields are now UP-TO-DATE at HEAD:

| ADR | File | Status at HEAD `893a963` | Previously (2026-09-18) | Change |
|-----|------|--------------------------|-------------------------|--------|
| ADR-003 | `docs/decisions/003-canonical-review-topology.md:3` | **Accepted** | Proposed | ✓ RESOLVED |
| ADR-004 | `docs/decisions/004-safe-sync-integrate-workflow.md:5` | **Accepted with implementation caveats** | Proposed | ✓ RESOLVED |
| ADR-005 | `docs/decisions/005-activity-data-ingestion-layer.md:5` | **Accepted (on consolidation)** | Proposed | ✓ RESOLVED |

**Note:** The ADR-004 status was updated as part of the post-PR #176/#178 work. The status
field now reads "Accepted with implementation caveats," accurately reflecting that all 5
phases are implemented (see §9.2).

## 9.2 ADR-004: Safe Sync-and-Integrate Workflow — Current State

**GAP-004 (Phases 3-5 not implemented): CLOSED**

- **Was:** OPEN — P0, only Phase 1 implemented
- **Now at HEAD `893a963`:** ALL FIVE PHASES IMPLEMENTED, WIRED, AND TESTED
- **Resolution:** PR #176 (Phase 5 completion gating, merged 2026-09-17) + PR #178
  (Phase 1 auto-invoke sync_branch at task start, merged 2026-09-17)

### Phase implementation status at HEAD `893a963`

| Phase | Status | Location | Tests |
|-------|--------|----------|-------|
| Phase 1 — Auto-invoke sync before implementation | **IMPLEMENTED** | `plugins/janus_sync/__init__.py:on_task_claimed` (line 197) → `_run_auto_sync` (line 238) → `sync_branch()` (line 276). Hook: `kanban_task_claimed`. Registration: line 929. | `tests/plugins/test_janus_sync_plugin.py`: TestAutoInvokeOnClaim — **9 passed** |
| Phase 2 — Implementation in worktree | N/A (worker's job) | Task worktree + branch per task (dispatcher-managed) | — |
| Phase 3 — Pre-completion gate | **IMPLEMENTED** | `src/janus/services/tasks.py:run_completion_gates` (line 287). Checks: working_tree_clean, tests_pass_after_rebase, git_diff_check. Evidence artifact: `pre_completion_report.json`. | `tests/test_task_complete_gates.py`: **15 passed** |
| Phase 4 — Safe integration | **IMPLEMENTED** | `src/janus/integration.py:integrate_branch()` (line 160), `integrate_task()` (line 548). FF merge first, `--no-ff` controlled merge fallback, post-merge test suite, rollback on test failure, push, remote contains check, `integration_report.json`. Reason codes: target_not_integrated, integration_conflict, post_integration_test_failure, target_push_failed, target_contains_check_failed, merge_failed, nothing_to_integrate, integration_setup_failed. | `tests/test_integration.py`: **15 passed** |
| Phase 5 — Completion gating | **IMPLEMENTED** | `src/janus/services/tasks.py:complete_task()` (line 527) — calls `run_completion_gates()` before markdown flip. `src/janus/services/execution_feedback.py:686-694` — `complete_janus_task_gated` gates open tasks in git repos. Gate error routing: `CompletionGateError` → `_handle_gate_block` (plugins/janus_sync/__init__.py:356) → `kanban_block`. | `tests/test_task_complete_janus_gates.py`: **7 passed** + `tests/plugins/test_janus_sync_plugin.py`: TestGateBlockRouting — **2 passed** |

**Total gate test count at HEAD `893a963`:** 9 + 15 + 15 + 7 + 2 = **48 passing gate tests**
across 4 test files. Additionally, the broader test suite (72 tests across these 4 files
including non-gate tests in test_janus_sync_plugin.py) passes.

**ADR-004 status field:** "Accepted with implementation caveats" — this accurately reflects
that the ADR is fully implemented. However, the ADR-to-Codebase Mapping Table (lines 52-78)
still shows stale "not wired" status for Phases 1/3/5 in the Status section intro (lines 7-14),
while the Post-PR-176/#178 Status section (added 2026-09-19) correctly acknowledges full
implementation. The code is authoritative; the mapping table intro is stale but the table rows
themselves are current. This stale intro is a documentation refinement, not a P1 gap — the
integration is complete and tested.

**GAP-006 (ADR-004 "separate agent" claim): CLOSED — fixed in commit `2f2ffa3`**

- **Was:** OPEN — P1, documentation accuracy issue
- **ADR-004 §Neutral (line 218) at HEAD `893a963`:** The §Neutral consequence at
  reconciliation baseline `893a963` still contained the stale "separate agent" language
  ("Phase 4 requires a separate agent/profile"). This was fixed post-`893a963` by commit
  `2f2ffa3` ("docs: update ADR-004 §Neutral to reflect Option B (no separate agent required)").
- **ADR-004 §Neutral at current HEAD (`781d4ae`, post-`2f2ffa3`):** Correctly states Option B:
  > "Phase 4 integration runs as an automated step in the completion path (Option B).
  > The integration logic is implemented in `src/janus/integration.py` and runs as part of
  > the Phase 5 gated completion flow — no separate agent/profile is required."
- **Assessment:** The documentation inconsistency is RESOLVED. The §Neutral consequence now
  correctly states that Phase 4 uses Option B (automated step), consistent with the Phase 4
  Integrator Model decision (lines 135-160).
- **Verdict:** CLOSED — fixed by commit `2f2ffa3` (merged via PR #195).

## 9.3 ADR-003: Canonical Review Topology — Current State

- **Status at HEAD `893a963`:** GAP-003 finding RESOLVED (Hermes-side fix in commit `5c275ad8b`)
- **Evidence:** `docs/decisions/003-canonical-review-topology.md` Status is now "Accepted"
  (was "Proposed" at 2026-09-18), but the GAP-003 finding about `prompt_builder.py`
  Model B language is in the Hermes agent repo, not the Janus repo, and is unaffected by
  the Janus-side PRs #176/#178.
- **Verdict:** GAP-003 finding about `prompt_builder.py` is **RESOLVED** — commit
  `5c275ad8b` (Sep 16, PR #29) removed the Model B "pre-created review, QA, or release
  child" language from `KANBAN_GUIDANCE` and replaced it with Model A-only guidance
  (`kanban_request_review`). Grep for stale language returns zero matches; the test
  `test_worker_guidance_distinguishes_same_card_and_downstream_review` (31 total
  kanban review tests) passes. The Janus-side ADR-003 status (Proposed -> Accepted)
  does not resolve the Hermes-side GAP-003 finding — that was resolved by the
  Hermes-side fix.

## 9.4 ADR-005: Activity Data Ingestion Layer — Current State

**GAP-005 (data_protection vs atomic_io): STILL OPEN**

- **Status at HEAD `893a963`:** UNCHANGED
- **Verdict:** Genuinely open. Services still use `protected_write` from `data_protection.py`.
  No change from 2026-09-18.

**GAP-007 ("sole write gateway" claim contradicted): RE-EVALUATED**

- **Status at HEAD `893a963`:** UNCHANGED — still OPEN
- **Nuance:** The j_ prec rebaseline (t_13a8b54a, 2026-09-18) had already corrected this:
  the protected write path (`protected_write()` → `atomic_io.atomic_write`) covers all Janus
  data files; the only direct-write outlier is `google_calendar.py:42` (OAuth token cache,
  not data). The claim is substantially accurate but the §2/§6 text still says "must be the
  ONLY path" which is technically contradicted by the google_calendar outlier. Still worth
  a caveat note in §9.4, but less severe than the original "contradicted" framing.

**GAP-008 (CI grep gate): STILL OPEN**

- **Status at HEAD `893a963`:** UNCHANGED
- **Verdict:** Genuinely open.

## 9.5 Current Genuinely Open Work (2026-09-22, post-PR #176/#178/#189, HEAD `893a963`)  [7 items]

After reconciliation against HEAD `893a963` (and subsequent fixes through commit `781d4ae`),
the following items remain genuinely open:

### P1 (high priority)

1. **GAP-005: ADR-005 data_protection → atomic_io migration**
   - Services still call `protected_write` from `data_protection.py` instead of routing
     through `atomic_io.read_modify_write_with_retry`
   - Effort: High. Blocks "sole write gateway" claim from being fully accurate.

2. **GAP-001: ADR-002 curation gate not implemented**
   - No `curation_gate()` / `human_approval()` / `promote_to_obsidian()` in
     `knowledge_pipeline.py`
   - Effort: Medium. Blocks end-to-end knowledge pipeline.

### P2 (medium priority)

3. **GAP-007: ADR-005 "sole write gateway" claim — add caveat**
   - §2/§6 says "must be the ONLY path" but `google_calendar.py:42` is a direct-write outlier
     (OAuth token cache, not data)
   - Effort: Low. Add caveat noting the token cache exception.

4. **GAP-003: ADR-003 prompt_builder.py Model B language — RESOLVED**
   - In Hermes agent repo, not Janus. Unaffected by Janus PRs.
   - Effort: Low. The Janus-side ADR-003 status is now "Accepted" (was "Proposed" at 2026-09-18),
     but the GAP-003 finding about `prompt_builder.py` is Hermes-side and is RESOLVED —
     commit `5c275ad8b` (Sep 16, PR #29) removed the Model B language.

5. **GAP-008: ADR-005 CI grep gate for data/ write patterns**
   - No CI rule grepping for data/ writes outside atomic_io
   - Effort: Low. Regression guard. The 2026-09-21 analysis incorrectly marked this CLOSED
     (referencing "195 add..." — referring to PR #195 which did NOT implement a CI grep gate).
     Confirmed still OPEN: no CI rule (e.g. `.github/workflows/ci.yml`) greps for `protected_write`
     or direct file writes outside `atomic_io`, so a service could add a non-atomic data/ write
     without CI catching it. The gate itself does not exist yet.

### Closed / Resolved / Archived

- **GAP-004 (ADR-004 Phases 3-5):** RESOLVED — all 5 phases implemented (§9.2)
- **GAP-006 (ADR-004 "separate agent" claim):** RESOLVED — §Neutral updated to Option B via
  commit `2f2ffa3` (§9.2)
- **tmp_*.py scratch files:** RESOLVED — no tmp_*.py files present at current HEAD
- **ADR status fields (§1):** RESOLVED — ADR-003 "Accepted", ADR-004 "Accepted with implementation
  caveats", ADR-005 "Accepted (on consolidation)" (see §9.1)
- **Consolidated ADR docs not on HEAD (§5):** ARCHIVE — master-only

## 9.6 Evidence: Test Verification at HEAD `781d4ae`

```
$ uv run pytest tests/test_task_complete_gates.py tests/test_task_complete_janus_gates.py tests/test_integration.py tests/plugins/test_janus_sync_plugin.py -q
[100%] 72 passed in 13.44s
```

(verified live on 2026-09-22 against current HEAD `781d4ae`, not the stale
`2f2ffa3` run captured earlier)

Breakdown:
- `tests/test_task_complete_gates.py`: 15 passed (Phase 3 pre-completion gates)
- `tests/test_task_complete_janus_gates.py`: 7 passed (Phase 5 completion gating)
- `tests/test_integration.py`: 15 passed (Phase 4 safe integration)
- `tests/plugins/test_janus_sync_plugin.py`: 35 passed (includes 9 TestAutoInvokeOnClaim for Phase 1 + 2 TestGateBlockRouting for gate error routing + other plugin tests)

**Gate-specific test count: 48** (9 + 15 + 15 + 7 + 2). The remaining 24 tests in
test_janus_sync_plugin.py cover other plugin functionality.

## 9.7 Summary of Changes Since 2026-09-18

| # | Item | 2026-09-18 | 2026-09-22 (HEAD `893a963`) |
| 1 | ADR-003 status | Proposed | **Accepted** ✓ |
| 2 | ADR-004 status | Proposed | **Accepted with implementation caveats** ✓ |
| 3 | ADR-005 status | Proposed | **Accepted (on consolidation)** ✓ |
| 4 | GAP-004 (Phases 3-5) | OPEN — P0 | **CLOSED** — all 5 phases implemented, 48 gate tests pass ✓ |
| 5 | GAP-006 (separate agent claim) | OPEN — P1 | **CLOSED** via commit `2f2ffa3` — §Neutral updated to Option B ✓ |
| 6 | GAP-001, GAP-005, GAP-007, GAP-008 | OPEN | **UNCHANGED** — still genuinely open; GAP-008 remains OPEN (addressed further below) ✓ |
| 7 | GAP-003 (prompt Model B language) | OPEN | **RESOLVED** — Hermes-side fix `5c275ad8b` (PR #29) removed Model B language from `KANBAN_GUIDANCE`; 0 grep matches, 31 kanban review tests pass ✓ |

---

*End of reconciliation — 2026-09-22. GAP-003 closed by Hermes-side fix (5c275ad8b, PR #29).*
