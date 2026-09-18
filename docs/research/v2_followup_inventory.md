# V2 Followup Inventory — t_1354daa3

**Date:** 2026-09-18
**Scope:** Reconciled inventory of followup items for the v2 feature branch, based on three parent research reports:
- `docs/research/reconciliation_report.md` (t_c5c6c0e1)
- `docs/research/e2e_followup_inventory.md` (t_3f17f2f4)
- `docs/research/vault_versioning_state_report.md` (t_a3635b0a)

**Method:** Each item mechanically verified against current repository state at `/home/dan11hermes/workspaces/janus/.worktrees/t_1354daa3` — file existence checks, `grep -rn` code searches, `git diff`/`git log` inspection, roadmap/backlog status checks, and local test execution (`pytest -q --tb=no`, 1873/1873 passed locally).

**Commit context:** HEAD is `60bed06` (docs: apply reconciliation report changes to ADR-004 and design spec, t_36b3d88f superseded). This commit is itself a reconciliation commit (PR #180 merge parent `e1a2fb5`, which merged `83c6460` — an earlier reconciliation commit). Both commits applied reconciliation items; the current worktree's working tree is clean with all three report conclusions applied.

---

## 1. Summary

| Source | Total items | Closed | Open | Deferred | Resolved (not Janus gap) |
|--------|-------------|--------|------|---------|--------------------------|
| Reconciliation report (t_c5c6c0e1) | 27 | 25 | 1 | 0 | 1 |
| E2E followup inventory (t_3f17f2f4) | 22 | 19 | 1 | 2 | 0 |
| Vault versioning report (t_a3635b0a) | 6 gaps | 3 | 0 | 3 | 0 |
| **Combined (deduplicated)** | **34** | **31** | **1** | **3** | **1** |

**One genuinely open item remains:** measurement consumers wiring (P2). All other items are either completed, correctly deferred, or resolved as non-gaps.

---

## 2. Closed Items (mechanically verified)

### 2.1 Reconciliation report items

| # | Item | Verification | Status |
|---|------|-------------|--------|
| 1-4 | Roadmap: execution feedback, E2E loop verification, skill tracking, strategic summaries | `docs/roadmap.md` lines 113-116: all `- [x]` confirmed. Implementation: `execution_feedback.py`, `skill_tracking.py`, `strategic_summary.py`. 9 E2E integration tests in `tests/plugins/test_e2e_execution_feedback.py`. Loop closure verified (t_1c8ada17). | **CLOSE** |
| 5 | Backlog: observability log schema | `docs/product_backlog.md` line 24-25: `[done]` confirmed (was `[ ]`). | **UPDATE → DONE** |
| 6 | Backlog: goal execution planning | `docs/product_backlog.md` line 48: `[done]` confirmed (was `[ready]`). | **UPDATE → DONE** |
| 15 | Attention→next_action wiring | `docs/design/connection_model_and_loop_workflow.md:363` explicitly says "not directly implemented; the daily briefing surfaces both." Not a gap. | **CLOSE** |
| 16-18 | ADR-004 C-03, C-05, C-06 | ADR-004 accepted with implementation caveats. Phase 1 sync (t_021f3833) + Phase 5 gate (t_4cd8c17f) merged. `is_branch_stale` exists in `git_sync.py`. `src/janus/integration.py` now implements Phase 4 (15 tests in `tests/test_integration.py`). See reconciliation §4.3. | **CLOSE** |
| 20 | t_36b3d88f orphaned reference | All 3 docs updated: `004-safe-sync-integrate-workflow.md:111`, `sync_integration_workflow_design.md:7,546`, `adr004_audit_report.md:46,83`. All note "superseded — never created; integration completed incrementally through phase-specific tasks t_021f3833, t_4cd8c17f." | **UPDATE → DONE** |
| 22 | Artifact version not auto-bumped | `docs/design/research_artifact_provenance_design.md` §4.1 updated to "caller-managed, not auto-incremented" (option B, lower risk). `markdown_research.py:update_artifact()` preserves version from frontmatter, never increments — behavior now documented. | **UPDATE → DONE** |
| 26 | No schema version for data/ files | `execution_planning.md:342` explicitly says "File-backed system, no schema versioning needed." | **CLOSE** |

### 2.2 E2E followup inventory items

| R# | Item | Verification | Status |
|----|------|-------------|--------|
| R2.1-R2.4 | Roadmap unchecked items (4) | All checked off in `roadmap.md` lines 113-116. | **CLOSE** |
| R3.1-R3.2 | Stale backlog items (2) | `product_backlog.md` already updated to `[done]`. | **CLOSE** |
| R4.1-R4.4 | Design deferred items (task deps, progress history, calendar write, measurement compliance) | Correctly deferred in spec/docs. No implementation task exists. | **DEFER (correct)** |
| R4.6 | validate-continuation CLI | Optional follow-up in spec. No task exists. Low priority. | **DEFER (correct)** |
| R5.1-R5.3 | ADR-004 risks (C-03, C-05, C-06) | ADR-004 accepted with caveats. Phase 4 now implemented in `src/janus/integration.py`. | **CLOSE** |
| R8.1 | t_36b3d88f orphaned reference | See reconciliation item 20. All 3 references updated. | **CLOSE** |

### 2.3 Vault versioning report items

| § | Item | Verification | Status |
|---|------|-------------|--------|
| §4.1 | Artifact version not auto-bumped | See reconciliation item 22. Design doc updated. | **CLOSE** |
| §4.2 | continuation_contract version mismatch | Spec only — production code path doesn't use `continuation_contract`. Design artifact, not runtime gap. | **CLOSE** |
| §? (data/* gitignored) | No opt-in path documented | By design — `.gitignore` excludes `data/*`. No opt-in needed. | **CLOSE** |

---

## 3. Open Items (genuinely pending)

### 3.1 Measurement consumers wiring (reconciliation #13, E2E R4.5) — P2

**Status:** OPEN — UNRESOLVED

**What exists:**
- `src/janus/services/measurement_collection.py` (236 lines) — `get_due_measurements(goals, entries, today, now) → list[MeasurementRequest]`
- `src/janus/services/measurement_log.py` (103 lines) — JSONL persistence (`data/measurements.jsonl`)
- Design doc `docs/design/measurement_collection_design.md` — full design with §7.1-7.3 listing consumers as follow-up
- `src/janus/services/goal_health.py:13,181-232` — `measurement_due` goal health signal already implemented

**What's missing:**
- No consumers wired for the design-doc §7.1-7.3 consumption paths:
  - Daily briefing attention items: `docs/design/measurement_collection_design.md:396-405` pseudocode ("to be implemented in a follow-up") — `src/janus/services/daily_briefing.py` has no measurement integration
  - Weekly review compliance reporting: `docs/design/measurement_collection_design.md:417-423` pseudocode ("follow-up enhancement") — `src/janus/services/weekly_review.py` has no measurement compliance reporting
  - CLI `janus goal measurements` subcommand: `docs/design/measurement_collection_design.md:427-435` — `src/janus/goals_cli.py` has no `goal measurements` subcommand
- The `measurement_due` goal health signal IS implemented (`goal_health.py`), but it surfaces as a goal health signal, not as the design-doc §7.1-7.3 consumer integrations
- No implementation task exists for the §7.1-7.3 consumer wiring
- No measurement collection tests (`pytest --collect-only` finds 0 tests in `test_measurement_collection.py` and `test_measurement_log.py`)

**Mechanical verification:**
```
$ grep -rn "measurement" src/janus/services/daily_briefing.py src/janus/services/weekly_review.py src/janus/goals_cli.py --include="*.py"
(no output — no consumer code in these files)
$ pytest --collect-only tests/test_measurement_collection.py tests/test_measurement_log.py 2>&1 | tail -1
(no tests collected)
```

**Recommendation:** Product decision needed (P2). Either:
- A) Implement minimum viable consumption: CLI subcommand (`janus goal measurements`) + daily briefing integration as the primary consumption path
- B) Formalize deferral with scope decision ("measurement consumers deferred to v3")

---

## 4. Deferred Items (correctly deferred, future work)

### 4.1 Backlog items (correctly `[planned]`)

| Item | Location | Why deferred |
|------|----------|-------------|
| Calendar-aware planning | `product_backlog.md:69` | Blocked on Google Calendar read-side integration (external dependency) |
| Research knowledge pipeline | `product_backlog.md:87` | Obsidian vault not yet versioned; design exists |
| Weekly review automation | `product_backlog.md:101` | Partially implemented but vague acceptance criteria |

### 4.2 Design spec deferred items (explicitly "deferred to follow-up task")

| Item | Location | Why deferred |
|------|----------|-------------|
| Task dependencies / `depends_on` field | `execution_planning.md:430` | Explicitly deferred in spec; no task created |
| Progress history / metric snapshots | `execution_planning.md:431` | Explicitly deferred in spec; no task created |
| Calendar write (goal/milestone → calendar event) | `execution_planning.md:432` | Requires scope decision on calendar write access |
| Measurement compliance reporting | `measurement_collection_design.md` pseudocode | Pseudocode only; not implemented |
| validate-continuation CLI | Spec optional follow-up | Optional convenience feature; low priority |

### 4.3 Vault versioning deferred items

| Item | Location | Why deferred |
|------|----------|-------------|
| Obsidian vault git repo initialization | `vault_versioning_decision.md` | Decision documented; no git init performed. Legitimate future work. |
| No `__version__` in janus package | `pyproject.toml:0.1.0` | Low impact; `pyproject.toml` carries version. Common pattern. |

---

## 5. Resolved as Non-Gap (mechanical verification)

### 5.1 Integration contract architecture mismatch (reconciliation #19, E2E R6.1)

**Claim:** Design doc `docs/specs/integration_contract.md` describes `hermes_cli/kanban_db.py` with `_enforce_integration_gate()` and `_body_declines_integration_required()`.

**Verification:**
```
$ ls hermes_cli/ 2>&1
ls: cannot access 'hermes_cli/': No such file or directory
$ ls kanban_db.py 2>&1
ls: cannot access 'kanban_db.py': No such file or directory
$ grep -rn "integration_required" --include="*.py" --include="*.md" --include="*.yaml" .
(found only in: src/janus/models/recent_activity.py:37, src/janus/services/execution_feedback.py:109,496,
 src/janus/integrations/markdown_research.py:33,281, docs/research-findings/implementation_notes.md:118,122,
 docs/decisions/adr-003-004-005-consolidated-decisions.md:99, docs/integration_marker_t_72569c5a.md:33,
 docs/implementation_notes/t_c643cef6.md:29, and plugins/replenishment/ — all documentation/comments except plugin)
```

**Disposition:** The integration contract design references Hermes CLI code (`hermes_cli/kanban_db.py`) which does NOT exist in the Janus repo. `hermes_cli/` is not present. The `integration_required` handling exists only in `plugins/replenishment/__init__.py` (which sets `integration_required=False` on generated tasks). This is a **Hermes-core design doc**, not a Janus implementation gap. No Janus code change needed. (Confirmed by reconciliation §4.2.)

---

## 6. V2 Completed (for context — not followup items)

The following were completed in the v2 feature branch and are NOT followup items:

- **ADR-004 Phases 1-5 design:** `docs/decisions/adr-003-004-005-consolidated-decisions.md`
- **ADR-004 decision document:** `docs/decisions/004-safe-sync-integrate-workflow.md` (with t_36b3d88f superseded note)
- **Sync integration workflow design:** `docs/design/sync_integration_workflow_design.md` (with t_36b3d88f superseded note)
- **Measurement collection service:** `src/janus/services/measurement_collection.py` + `measurement_log.py`
- **Measurement collection design:** `docs/design/measurement_collection_design.md`
- **Execution feedback loop:** `src/janus/services/execution_feedback.py`
- **E2E verification tests:** `tests/plugins/test_e2e_execution_feedback.py` (9 tests), `tests/plugins/test_janus_sync_plugin.py` (16 tests)
- **Integration primitive (Phase 4):** `src/janus/integration.py` + `tests/test_integration.py` (15 tests) — implements full Phase 4: ff merge → controlled merge fallback → post-merge test runner → rollback on failure → push → remote containment check → `integration_report.json`
- **ADR-to-Codebase Mapping Table:** `docs/decisions/004-safe-sync-integrate-workflow.md` (maps all ADR-004 phases to actual codebase locations)
- **Strategic summary + skill tracking services:** `src/janus/services/strategic_summary.py`, `skill_tracking.py`
- **Product backlog + roadmap updates:** `docs/product_backlog.md`, `docs/roadmap.md`
- **Artifact provenance design §4.1 update:** `docs/design/research_artifact_provenance_design.md`
- **Reconciliation commits:** `83c6460` (earlier reconciliation, merged via PR #180) + `60bed06` (current reconciliation, applied t_36b3d88f reference updates + Phase 4 rewrite)
- **Local test suite:** 1873/1873 passed (full pytest, no GitHub Actions)

---

## 7. Reconciliation Discrepancies Resolved

### 7.1 Phase 4 status — updated by current reconciliation

The earlier reconciliation commit `83c6460` classified Phase 4 as "design gap — not implemented" and still referenced `hermes_cli/kanban_db.py`. The current reconciliation commit `60bed06` reflects that `src/janus/integration.py` was created between `83c6460` and `60bed06` (merged via PR #180 from worktree t_2d81c24e). The ADR-to-Codebase Mapping Table in `004-safe-sync-integrate-workflow.md` now maps Phase 4 to `src/janus/integration.py` with status **"Implemented."**

### 7.2 ADR-004 `hermes_cli/kanban_db.py` references — resolved

Earlier research reports referenced `hermes_cli/kanban_db.py` with `_enforce_repo_sync_gate`, `_enforce_integration_gate`, and `complete_task()` at lines ~5639/5804/5954. These functions do NOT exist in the Janus repo — `hermes_cli/` is not present. The ADR-to-Codebase Mapping Table in the current ADR-004 decision document explicitly replaces these stale references with actual Janus codebase locations (`src/janus/git_sync.py`, `src/janus/verification.py`, `src/janus/services/tasks.py:complete_task()`, `src/janus/integration.py`).

---

## 8. Recommended Next Step

**P2 — Measurement consumers decision:** The only genuinely open item is wiring consumers for the measurement collection service per `measurement_collection_design.md` §7.1-7.3. Product decision needed: implement CLI + briefing consumers as minimum viable path, or formalize deferral to v3 with scope decision.

---

*End of inventory. All claims mechanically verified against current repository state at commit 60bed06.*
