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

---

## Legend

| Disposition | Meaning |
|-------------|---------|
| **OPEN** | Verified at HEAD — work remains to be done |
| **CLOSED** | Resolved by `2dc1b72` or prior work — no action needed |
| **ARCHIVE** | Claim is stale/no longer relevant — keep for history but mark archived |
| **REMOVE** | Claim is factually wrong at HEAD — should be deleted |

---

## 1. ADR Status Fields — Stale (All Three ADRs)

| ADR | File | Field | Current | Should Be | Evidence (HEAD) |
|-----|------|-------|---------|-----------|-----------------|
| ADR-003 | `docs/decisions/003-canonical-review-topology.md:3` | Status | Proposed | Accepted | Commit `76fd1cd` (2026-09-16) set to "Accepted" on master/remote; HEAD still shows "Proposed" |
| ADR-004 | `docs/decisions/004-safe-sync-integrate-workflow.md` (line 5 under `## Status`) | Status | Proposed | Accepted | Same — `76fd1cd` not on HEAD |
| ADR-005 | `docs/decisions/005-activity-data-ingestion-layer.md` (line 5 under `## Status`) | Status | Proposed | Accepted | Same — `76fd1cd` not on HEAD |

**Recommended next step:** Update all three status fields from "Proposed" to
"Accepted" on the current HEAD branch. This is a trivial documentation fix.

---

## 2. ADR-003: Canonical Review Topology

### GAP-003: Prompt still contains Model B language (OPEN)

- **ADR Reference:** `docs/decisions/003-canonical-review-topology.md` §1 Required Change #1
- **Description:** `prompt_builder.py` `KANBAN_GUIDANCE` still contains "pre-created review,
  QA, or release child" language, introducing Model B ambiguity.
- **Current status:** OPEN — confirmed at the Hermes agent repo.
- **Evidence linking to HEAD:**
  - `agent/prompt_builder.py:322` (Hermes agent repo) contains: `"pre-created review, QA, or release child depends on your task, call "`
  - This is in the `KANBAN_GUIDANCE` constant (Hermes agent repo)
  - The ADR's §1 lists the required change at line 95: "Patch `prompt_builder.py` to
    remove the Model B language from `KANBAN_GUIDANCE`."
  - The ADR itself (at `docs/decisions/003-canonical-review-topology.md:95`) is
    unchanged at HEAD — it still describes the patch as required.
- **Recommended next step:** Edit `agent/prompt_builder.py` to remove the "pre-created review, QA, or release child" paragraph and replace with the Model A-only guidance per ADR §2.

### ADR-003 implementation itself (CLOSED)

- **Evidence:** Model A is fully implemented across DB schema (`VALID_STATUSES`
  includes `review`), tool surface (`kanban_request_review`, `kanban_request_changes`),
  dispatcher (spawns reviewer with `sdlc-review` skill), watchers, CLI subcommand,
  and `sdlc-review` skill. No gap remains in the Janus repo.

---

## 3. ADR-004: Safe Sync-and-Integrate Workflow

### GAP-004: Phases 3-5 not implemented (OPEN — P0)

- **ADR Reference:** `docs/decisions/004-safe-sync-integrate-workflow.md`
- **Description:** Only Phase 1 (Pre-Implementation Sync) is implemented. Phases 3
  (Pre-Completion Gate), 4 (Safe Integration), and 5 (Completion gating) are missing.
- **Current status:** OPEN — `sync_branch()` exists but is not invoked in the completion flow.
- **Evidence linking to HEAD:**
  - `src/janus/git_sync.py:267` — `sync_branch()` fully implemented (Phase 1)
  - `grep -rn "sync_branch" hermes-agent/` → **0 matches** (not called anywhere in Hermes agent repo)
  - `grep -rn "def integrate|def pre_completion|def safe_complete" src/` → **0 matches**
  - `git_sync.py` docstring (lines 10–11): "This module is narrowly scoped to the *sync* primitive
    only. It does not orchestrate the full workflow (verification, integration, completion gating)."
  - `kanban_complete` is not blocked on sync/integration — a task can be marked done with
    an unintegrated branch.
- **Recommended next step:** Implement Phase 3 (`pre_completion_gate`), Phase 4
  (`integrate_branch` / FF merge + push + verify), and wire both into the `kanban_complete`
  flow in the Hermes agent repo.

### GAP-006: ADR-004 Phase 4 "separate agent" claim is inaccurate (OPEN — P1)

- **ADR Reference:** `docs/decisions/004-safe-sync-integrate-workflow.md` §10 (Neutral)
- **Description:** The ADR states "Phase 4 requires a separate agent/profile" but also
  notes the task is "superseded." The body text at line 109 still frames t_36b3d88f as
  "the implementation task" with the superseded status only in a parenthetical.
  Furthermore, Phase 4 was never implemented — the "incremental" tasks only delivered
  Phase 1.
- **Current status:** OPEN — documentation accuracy issue.
- **Evidence linking to HEAD:**
  - `docs/decisions/004-safe-sync-integrate-workflow.md:109` — still contains
    "Phase 4 requires a separate agent/profile" language
  - `docs/decisions/004-safe-sync-integrate-workflow.md:111` — references t_36b3d88f
    as "superseded" but the body doesn't front-load this
  - `docs/decisions/004-safe-sync-integrate-workflow.md:173` — references t_36b3d88f
    as "superseded" in footnotes but main text still frames it as "the implementation task"
  - No `integrate_branch` or equivalent function exists in `src/`
- **Recommended next step:** Either (a) remove the "separate agent" requirement from
  ADR-004 §10 and document that Phase 4 remains open, or (b) implement Phase 4 and
  update the ADR accordingly.

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

| Priority | Gap | ADR | Effort | Block |
|----------|-----|-----|--------|--------|
| **P0** | GAP-004: ADR-004 Phases 3-5 not implemented | ADR-004 | High | Core correctness — tasks can be marked done with unintegrated branch |
| **P1** | GAP-005: Services still use data_protection instead of atomic_io | ADR-005 | High | Two write surfaces (data_protection + atomic_io) contradict "sole gateway" |
| **P1** | GAP-001: ADR-002 curation gate not implemented | ADR-002 | Medium | Blocks end-to-end knowledge pipeline |
| **P1** | GAP-006: ADR-004 Phase 4 "separate agent" claim inaccurate | ADR-004 | Low | Documentation accuracy |
| **P1** | GAP-007: ADR-005 "sole gateway" claim contradicted by code | ADR-005 | Medium | Documentation accuracy |
| **P2** | GAP-003: Prompt still contains Model B language | ADR-003 | Low | Model B ambiguity in worker prompt |
| **P2** | GAP-008: ADR-005 CI grep gate not implemented | ADR-005 | Low | Regression protection |

### 6.1 ADR-002: Curation Gate Not Implemented (OPEN — P1)

- **ADR Reference:** `docs/decisions/002-obsidian-knowledge-layer.md`
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

### 6.2 tmp_*.py scratch files committed to repository (OPEN — Cleanup)

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
| ADR-003 status says "Proposed" | `docs/decisions/003-canonical-review-topology.md:3` — `**Status:** Proposed` |
| ADR-004 status says "Proposed" | `docs/decisions/004-safe-sync-integrate-workflow.md:3-5` — `## Status` / `Proposed` |
| ADR-005 status says "Proposed" | `docs/decisions/005-activity-data-ingestion-layer.md:3-5` — `## Status` / `Proposed` |
| Commit 76fd1cd set statuses to "Accepted" on master | `git show 76fd1cd` — 4 files changed, status lines modified |
| 76fd1cd is NOT an ancestor of HEAD | `git merge-base 0f6caec 76fd1cd` returns `345090f` (not 76fd1cd) |
| Model B prompt language exists in Hermes agent repo | `agent/prompt_builder.py:322` — "pre-created review, QA, or release child" |
| sync_branch implemented but not called | `src/janus/git_sync.py:267`; `grep -rn "sync_branch" hermes-agent/` → 0 matches |
| Phases 3-5 functions do not exist | `grep -rn "def integrate\|def pre_completion\|def safe_complete" src/` → 0 matches |
| activity_ingest.py fully implemented | `src/janus/services/activity_ingest.py` — 1109 lines |
| atomic_io.py fully implemented | `src/janus/integrations/atomic_io.py` — 224 lines |
| data_protection.py has separate atomic_write | `src/janus/integrations/data_protection.py:258` |
| Services import and call protected_write | `src/janus/services/tasks.py:17,74,184,284,349`; `src/janus/services/decisions.py:19,132,172,223,274` |
| Integration modules use protected_write | `markdown_inbox.py:158,178`, `markdown_followups.py:194,214`, `workout_md.py:14,94`, `markdown_research.py:16`, `markdown_goals.py:46,787` |
| measurement_log uses f.write | `src/janus/services/measurement_log.py:103` (append-only JSONL) |
| google_calendar uses TOKEN_PATH.write_text | `src/janus/integrations/google_calendar.py:42` (credentials, not data/) |
| CI grep gate not in verification.py | `src/janus/verification.py:1144` — `check_files_immutable` is immutable-files check, not write-path gate |
| Vault IS versioned (decision executed) | `/mnt/c/Users/dan11/Documents/HermesVault` — `.git` exists with commits `fcf155d`, `a534147` |
| data/ directory removed from git | `git log --oneline 80b1e8e` — "removed data files from git"; `ls data/` → not found at HEAD |
| Vault versioning audit is stale | `docs/research/obsidian_vault_audit.md:111` says "No version control" but vault now has `.git` |
| 11 tmp_*.py files committed in 2dc1b72 | `git ls-files tmp_*.py` — 11 files; `git show 2dc1b72 --stat` lists all 11 |
| ADR-004 Phase 4 "separate agent" language remains | `docs/decisions/004-safe-sync-integrate-workflow.md:109-111` |
| Consolidated ADR docs not on HEAD | `76fd1cd` and `c74d1ac` create `adr-003-004-005-consolidated-decisions.md` and `adr-consolidated-decisions.md`; both on `origin/master` but not on HEAD |

---

## 8. Recommendations Summary

### Immediate (next 24 hours)
1. **Fix ADR status fields** — change "Proposed" to "Accepted" in ADR-003, ADR-004, ADR-005
2. **Remove `tmp_*.py` files** — 11 scratch files committed by 2dc1b72 should be deleted

### This week
3. **Patch prompt_builder.py** — remove Model B language (ADR-003 GAP-003)
4. **Update ADR-004 §10** — fix the inaccurate Phase 4 "separate agent" claim (GAP-006)
5. **Update ADR-005 §2/§6** — acknowledge migration is in progress (GAP-007)
6. **Back-port consolidated ADR docs** — `adr-003-004-005-consolidated-decisions.md`
   and `adr-consolidated-decisions.md` exist on master (`76fd1cd`, `c74d1ac`) but not
   on HEAD. Back-port to HEAD or document as master-only.

### Implementation backlog (requires dedicated tasks)
7. **ADR-004 Phases 3-5** — implement pre-completion gate, safe integration, completion gating
8. **ADR-005 migration** — route service functions through `atomic_io` instead of
   `data_protection`
9. **ADR-005 CI grep gate** — add write-path verification to `verification.py`
10. **ADR-002 curation gate** — implement human-approval step for Obsidian promotion

---

*End of authoritative open work list.*
