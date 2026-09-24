# Janus Lifecycle Synthesis: Discovery → Coherence

**Task:** t_80157ed1 — Consolidated discovery and synthesis
**Date:** 2026-09-24
**Last verified:** 2026-09-24
**Scope:** Synthesis of 5 research-findings worktrees + t_80157ed1 discovery reads (roadmap, backlog, vision, design docs)
**Method:** Cross-worktree thematic aggregation. No implementation changes.

---

## 1. Purpose and Scope

This document synthesizes findings from five prior research-findings worktrees and the discovery reads performed against the t_80157ed1 worktree itself. It is the integration artifact for the "roadmap review → ADR audit → repository inventory → execution-review model → synthesis" pipeline.

**Source worktrees (research findings):**

| Worktree | Finding file | Focus |
|----------|-------------|-------|
| t_0abb90ab | `documentation_roadmap_review_findings.md` | Docs/roadmap staleness, contradictions, recommendations |
| t_92d7c729 | `adr_audit_report.md` | All 11 ADRs/decision records: status, constraints, staleness |
| t_eacb6a05 | `repository_inventory_findings.md` | Repo structure, 94 source files, 84 test files, gaps |
| t_f339fe3e | `goal_task_execution_completion_review_model.md` | Lifecycle flow, enforcement, authoritative state, gaps |
| t_80157ed1 | 12 research-findings files + 4 discovery docs | E2E verification, goal discovery, review lifecycle, ADR-004 reconciliation, implementation notes, goal health, planning calendar, knowledge capture, observability, measurement, hierarchy, integrity audit, execution planning, verification contract |

**Discovery docs read from t_80157ed1:**

- `docs/roadmap.md` — 12-item implementation roadmap
- `docs/product_backlog.md` — done/planned/later/parking lot
- `docs/vision.md` — long-term Chief of Staff evolution
- `docs/design/goal_system_design.md` — 1221-line goal architecture (metric fields, progress computation)
- `docs/design/goal_milestone_project_task_hierarchy.md` — 2003-line 4-level hierarchy draft
- `docs/design/measurement_collection_design.md` — 729-line MeasurementLog design
- `docs/design/execution_planning.md` — milestone/next-action/stall detection extension
- `docs/design/goal_integrity_audit.md` — goal integrity audit design
- `docs/verification.md` — repository verification contract (pytest)
- `docs/specs/goal_system_implementation_plan.md` — 948-line implementation-ready spec (referenced)

---

## 2. Architecture: What Exists and Holds

### 2.1 Two-Layer System Model (ADR-001) — Foundation

The Hermes/Janus boundary is the architectural backbone and is fully active:

- **Hermes:** agent interaction, orchestration, planning, tool usage, autonomous execution, Telegram UI
- **Janus:** domain models, business logic, persistence, integrations, deterministic processing

Every subsequent ADR and every design document assumes this boundary. No revisiting needed. The boundary is respected in code: domain logic lives under `src/janus/`, orchestration lives in Hermes plugins (`plugins/janus_sync/`, `plugins/replenishment/`).

### 2.2 ADR-002 — Obsidian as Curated Knowledge Layer

Obsidian is a curated long-term knowledge layer, not default storage. Flow: Raw → Operational Storage → Analysis → Curation → Obsidian. Active and governing. The vault versioning decision is a downstream consequence.

### 2.3 ADR-003 — Canonical Review Topology (Model A) — Fully Implemented

Model A (Native Review Lane) is adopted; Model B (reviewer-child workflow) is rejected. Review is a phase of the same task; task identity and run history persist across review rounds. All subsystems (DB schema, tool surface, dispatcher, watchers, CLI, skill system) are consistent with Model A.

**Architectural constraint:** All code review MUST use `kanban_request_review`. The auto-decomposer must NOT generate review children.

ADR-003-S1 (Milestone Status Lifecycle) and ADR-003-S2 (Review Probes + Human-in-the-Loop) are accepted supplements. S1 governs milestone FSM (open/in_progress/completed/skipped). S2 establishes delegate_task probes as read-only parallel investigators and human reviewers as first-class participants via `claim_review_task`.

### 2.4 ADR-004 — Safe Sync-and-Integrate Workflow — Code-Complete, Runtime-Dormant

The 5-phase gated workflow is implemented in full:

| Phase | Status | Location |
|-------|--------|----------|
| 1 (pre-implementation sync) | IMPLEMENTED | `git_sync.py:sync_branch()` + `on_task_claimed` hook (PR #178) |
| 2 (implementation) | UNCHANGED | worktree isolation |
| 3 (pre-completion gate) | IMPLEMENTED | `_phase3_pre_completion_gate()` (PR #176) |
| 4 (safe integration) | IMPLEMENTED | `integrate_task()` in `integration.py` (PR #176) |
| 5 (gated completion) | IMPLEMENTED | `run_completion_gates()` (PR #176/#189) |

**Critical runtime caveat:** The `janus_sync` plugin is code-complete but NOT LOADED in the current Hermes install. It is absent from all `plugins.enabled` lists, and `janus.pth` points at a deleted worktree. This means Phase 1 auto-invoke and execution-feedback gate-block routing are dormant at runtime. ADR-004 compliance is achieved in code but not in production.

The integrator model chosen is Option B (automated step in completion path), not Option A (separate agent). The ADR text still references Option A framing in places.

### 2.5 ADR-005 + ADR-005-A1 — Activity Data Ingestion — Resolved

ADR-005 established the controlled-write-gateway design. ADR-005-A1 resolved the `atomic_io` vs `data_protection` overlap via layered composition. All 7 legacy `protected_write` callers migrated to `atomic_io`/`data_integrity` (PR #204); `data_protection.py` deleted. Status: criteria met (2026-09-22).

**Deferred:** SHA-256 conflict detection, `flock`, post-write verification are not yet in `atomic_io`. Deferred to `t_1f9c2a7`. Current behavior relies on `data_integrity.py` wrapping `atomic_io`.

---

## 3. Domain Model: What's Built and What's Designed

### 3.1 Core Entities (Implemented)

**Goal** (`models/goal.py`): title-based identity, status (active/completed/inactive), `related_tasks: list[str]`, metric fields (metric_name, metric_unit, start_value, current_value, target_value, direction), milestones/projects as dicts, recent_activity. Validation in `__post_init__`.

**Task** (`models/task.py`): title identity, state (todo/in_progress/blocked), progress 0-100 (no auto-complete at 100), `extra_metadata: list[str]` for goal references and evidence fields.

**Milestone:** 4-state FSM (ADR-003-S1). Dynamic task-to-milestone assignment via `derive_milestone_tasks()`.

**Project:** Explicit task assignment entity. Auto-completes when all assigned tasks done.

### 3.2 Lifecycle Flow (Implemented, with gaps)

```
Goal (active)
  └── related_tasks: [task_title_1, ...]
        └── Task (todo) → Hermes Kanban task → Execution → Completion
              ├── Parse janus_domain frontmatter
              ├── Build EvidencePackage
              └── dispatch_completion() → update_goal_progress | complete_janus_task | update_milestone_status | complete_project_by_title | ingest research
              └── Janus task complete → Phase 1 sync → Phase 3 gates → Phase 4 integration
        └── Milestone (optional) → Project (optional) → auto-completion cascade
        └── Goal complete: manual (complete_goal) or auto when all tasks done
```

**Enforcement (ADR-004 Phase 5 gates):**
- Phase 1: Re-sync (blocks only on SYNC_CONFLICT)
- Phase 3: Working tree clean, git diff --check, tests pass after rebase (blocks on failure)
- Phase 3ext: Contract verification (opt-in, blocks on failure)
- Phase 4: Safe integration (blocks on failure)

**Two enforcement paths:** CLI (`janus task complete`) and Hermes execution-feedback (`dispatch_completion()`). The execution-feedback path runs gates ONLY if the Janus task is currently open AND lives in a git repo. Already-completed tasks are idempotent re-evidence updates (no re-gating).

### 3.3 Goal Integrity Audit (Implemented)

`janus goal audit` — read-only health checks:

| Issue code | Severity | Condition |
|------------|----------|-----------|
| UNKNOWN_GOAL_REFERENCE | error | Task references non-existent goal |
| INVALID_METRIC | error | Goal has metric_name but incomplete/invalid fields |
| STALE_ACTIVITY | warning | Active goal with no activity in inactivity window |
| GOAL_WITHOUT_TASKS | warning | Active goal with no related open/actionable tasks |

### 3.4 Designed but Not Implemented

These are design-complete but have no implementation commitment:

1. **Goal metric fields** (`goal_system_design.md`, 1221 lines) — 11-field dataclass extension with `compute_goal_progress()`. Spec exists (`specs/goal_system_implementation_plan.md`, 948 lines, "implementation-ready") but roadmap item is `[ ]` (not done).

2. **Goal → Milestone → Project → Task hierarchy** (`goal_milestone_project_task_task_hierarchy.md`, 2003 lines) — Draft for review v2. Introduces Project as execution unit between Milestone and Task. No implementation commitment.

3. **Measurement collection** (`measurement_collection_design.md`, 729 lines) — `measurement_requirements` on Goal + `MeasurementLog` (JSONL). Complementary to and potentially overlapping with metric fields.

4. **Strategic summary service** (`strategic_summary_spec.md`) — No implementation.

5. **Calendar-aware planning** — Product backlog, not started.

6. **Research knowledge pipeline** — Product backlog, not started.

7. **Weekly review automation** — Product backlog, not started.

---

## 4. Cross-Cutting Themes

### 4.1 Title-Based Identity Is the MVP Constraint

Goals and tasks use human-readable titles as identity. Renaming breaks `goal.related_tasks` references silently. No unique IDs. The goal_task_execution_completion_review_model.md explicitly flags this as a structural gap. The `related_tasks` list is a denormalized cache that must be kept in sync with actual task state. UUID migration requires data migration.

### 4.2 No Formal Review Phase in the Lifecycle

Goals: active/completed/inactive. Tasks: todo/in_progress/blocked. There is no `under_review` or `awaiting_review` state. The weekly review is a read-only snapshot report, not a state machine phase. This is the single most flagged gap across the execution-review model findings, the review lifecycle findings, and the ADR-003 supplementary documents.

The recommendation from the execution-review model: add `under_review` state to tasks (between `in_progress` and completed), implement goal-level completion gates (currently only task-level), strengthen metric advancement idempotency, tighten milestone auto-completion derivation.

### 4.3 Evidence-Based Verification Is the Cultural Backbone

`docs/principles.md` states three guiding principles:
1. Verify before assuming
2. Repo/data as truth
3. Evidence before inference

These are operationalized through: observability logging (41 dedicated tests, 579 total passing), verification pipeline (phases 1-3 + adversarial E2E), goal integrity audit, pre-completion gates, structured events with trace_id, and the ADR-004 gated completion workflow. The culture is "don't trust self-reported done — demand mechanical verification."

### 4.4 Documentation Volume Is a Burden

`docs/` contains 100+ markdown files. Many are output artifacts from prior Kanban tasks. The repository inventory flags this as a notable gap. Specific problems: stale roadmap items, overlapping consolidated ADR files, "implementation-ready" specs coexisting with "Not committed" architecture docs, a referenced file that doesn't exist (`janus-agency-first-development-phase.md`).

### 4.5 Test Coverage Is Healthy but Not Complete

84 test files, ~28.4k LOC vs ~36.5k source LOC (ratio ~0.78). 28 of 33 services have dedicated tests. Gaps: `obsidian_promoter.py` (293 LOC, no test), `followup.py` (230 LOC, no dedicated service test), `inbox.py` (142 LOC, no dedicated service test), `project_progress.py` (no dedicated test). No mypy/pyright, no ruff/flake8.

### 4.6 Two Dormant Plugins

Both Hermes plugins are code-complete but have runtime caveats:

- **janus_sync:** Not loaded in current Hermes install. ADR-004 Phase 1 auto-invoke and execution-feedback gate-block routing are dormant.
- **replenishment:** Code-complete, best-effort observer. No reported runtime issue.

---

## 5. Contradictions and Stale Signals

### 5.1 Roadmap Items 9-12 Are Stale

`docs/roadmap.md` marks items 9-12 as `[ ]` but they are implemented, tested, and merged. Verified by prior review (t_3d55f0c0). Items: Janus ↔ Hermes execution feedback, Strategic state summaries, Evidence-based skill tracking, and one more. The roadmap needs updating to `[x]` or `[~]`.

### 5.2 Consolidated ADR File — Resolved

- `docs/decisions/adr-003-004-005-consolidated-decisions.md` (211 lines, canonical) — the single authoritative consolidated ADR.
- `adr-consolidated-decisions.md` was the duplicate; it was removed in commits b7ef125 / 4c34204 / 3178c97.

ADR-004 status is now "Accepted" (post-PR-189). Only the runtime plugin-loading gap remains.

### 5.3 Goal Progress: Metric Fields vs Measurement Log

`goal_system_design.md` stores `current_value` directly on the Goal (11-field dataclass). `measurement_collection_design.md` stores measurements in a separate `data/measurements.jsonl` log. Two different persistence strategies for the same conceptual problem. The measurement approach is more sophisticated (time-series, due-date tracking) but the goal design approach is simpler. Both are "design complete — not implemented." Implementing both without reconciliation would be redundant.

### 5.4 Roadmap Items 11 and 15 Are Near-Duplicates

- Item 11: `[~]` Verify the complete Goal → Task → Execution → Completion → Review loop
- Item 15: `[ ]` Verify the complete Goal → Task → Execution → Completion → Review loop, including production verification of Completion → Goal Update and Review

Item 11 is partially done; item 15 is not started. These should be consolidated.

### 5.5 Execution Planning vs Project Hierarchy

`execution_planning.md` adds Milestones to Goal (Goal → Milestone → Task, 3-level). `goal_milestone_project_task_hierarchy.md` adds Project between Milestone and Task (Goal → Milestone → Project → Task, 4-level). The latter is more recent/detailed but has no implementation commitment. Both coexist.

### 5.6 Missing File: `janus-agency-first-development-phase.md`

Referenced in a task body but does not exist in the repository. Unknown what it was supposed to contain.

### 5.7 ADR Status Signals — Resolved

- ADR-004 status field: Updated from "Accepted with implementation caveats" to "Accepted" — all 5 phases implemented post-PR-189; only the runtime plugin-loading gap remains.
- ADR-005 status: Updated from "Accepted (on consolidation)" to "Accepted" — migration complete, `data_protection.py` deleted.
- Consolidated ADR files: Duplicate removed; `adr-003-004-005-consolidated-decisions.md` is the sole canonical file.

---

## 6. Execution Stage Assessment

### 6.1 What's Live (production, user-facing)

- Two-layer Hermes/Janus architecture
- Obsidian knowledge layer curation principle
- Model A native review lane (fully operational)
- Milestone status lifecycle FSM
- 5-phase gated completion (code-complete; Phase 1 dormant due to plugin not loaded)
- Atomic write gateway (ADR-005-A1 resolved, `data_protection.py` deleted)
- Execution planning with milestones, next-action derivation, stall detection
- Structured observability logging (41 tests, 579 total passing)
- Goal health signals and attention engine integration
- Unified inbox and follow-up model
- Research → finding → decision → action loop (connection model)
- Janus ↔ Hermes execution feedback
- Evidence-based skill tracking
- Strategic state summaries
- Goal integrity audit (`janus goal audit`)
- Verification pipeline phases 1-3 + adversarial E2E
- Repository verification contract (pytest-based)

### 6.2 What's Designed but Dormant

- Goal metric fields (11-field dataclass, `compute_goal_progress()`)
- Goal → Milestone → Project → Task hierarchy (2003-line draft)
- Measurement collection (MeasurementLog, JSONL)
- Strategic summary service
- Calendar-aware planning
- Research knowledge pipeline
- Weekly review automation

### 6.3 What's Dormant Due to Operational Gap

- ADR-004 Phase 1 auto-invoke (janus_sync plugin not loaded)
- ADR-005-A1 deferred features (SHA-256, flock, post-write verification — deferred to t_1f9c2a7)

### 6.4 What's Explicitly Out of Scope

- Phase 4 adversarial LLM review (ADR-004 verification pipeline)

---

## 7. Critical Gaps (Ranked by Impact)

### 7.1 Runtime ADR-004 Non-Compliance (High)

The `janus_sync` plugin is not loaded. This means: no auto-sync on task claim, no execution-feedback gate-block routing. A Hermes-completed task can bypass Phase 1 sync and the execution-feedback gate checks. This is the single most impactful operational gap. Two options: enable the plugin in config, or document gated completion as opt-in/dormant.

### 7.2 No Formal Review State in Lifecycle (High)

The lifecycle has no `under_review` state. Review is a Kanban phase (via `kanban_request_review`) but not a domain state. This means: no domain-level enforcement of "execution done → awaiting review → review complete → completion accepted." The weekly review is a report, not an enforcement point. Recommendation: add `under_review` state to tasks, implement goal-level completion gates.

### 7.3 Title-Based Identity Fragility (Medium)

Renaming a task breaks `goal.related_tasks` silently. No unique IDs. The `related_tasks` list is a denormalized cache. UUID migration would require data migration and is flagged as an MVP constraint — not imminent.

### 7.4 Metric Advancement Idempotency (Medium)

Re-completing a task via `update_goal_progress()` overwrites the metric value each time. The `recent_activity` entry is replaced (idempotent by task_id), but the metric `current_value` is overwritten with whatever the evidence carries — no guard against double-counting.

### 7.5 Stale Documentation Signals (Medium)

Roadmap items 9-12, ADR status fields, consolidated ADR files, and the near-duplicate items 11/15 all carry stale or ambiguous signals. A reader directed to these documents will get outdated information. Update cost is low; impact is moderate (misleads downstream workers).

### 7.6 Goal System Direction Unresolved (Medium)

Metric fields on Goal vs separate MeasurementLog solve the same problem differently. Implementing both without reconciliation would be redundant. No decision has been made.

### 7.7 Test Coverage Gaps (Low-Medium)

`obsidian_promoter.py` (293 LOC), `followup.py` (230 LOC), `inbox.py` (142 LOC), `project_progress.py` — no dedicated tests. Not blocking, but the gaps are known and unexamined.

### 7.8 No Type Checking / Linting (Low)

No mypy/pyright, no ruff/flake8. Only pytest configured. The project uses dataclasses extensively. Adding type checking would catch a class of errors but is not blocking.

---

## 8. Consolidated Recommendations

### 8.1 Immediate (Operational)

1. **Load janus_sync plugin in Hermes config** — realizes ADR-004 compliance in production. Alternatively, document gated completion as opt-in. This is the highest-impact action.

2. **Update roadmap items 9-12 from `[ ]` to `[x]`** — verified implemented. Low effort, removes stale signal.

3. **Update ADR status signals** — ADR-004 status field, ADR-005 status field, both consolidated ADR files. Reflect post-PR-189 code-complete state. The only remaining caveat is runtime plugin availability.

### 8.2 Near-Term (Decision Required)

4. **Decide goal system direction** — metric fields on Goal vs MeasurementLog. These overlap. Pick one, reconcile, or explicitly defer one. The 948-line implementation plan exists for metric fields; the 729-line measurement design exists for the log approach.

5. **Consolidate roadmap items 11 and 15** — near-duplicate. Merge into one item with clear scope.

6. ~~**Resolve consolidated ADR file duplication**~~ — RESOLVED. `adr-consolidated-decisions.md` (duplicate) was removed. `adr-003-004-005-consolidated-decisions.md` is now the sole canonical file.

7. **Create or remove `janus-agency-first-development-phase.md`** — referenced but missing. Either create it or remove the reference.

### 8.3 Medium-Term (Design/Implementation)

8. **Add `under_review` state to tasks** — between `in_progress` and completed. Implements the formal review phase that the lifecycle currently lacks.

9. **Implement goal-level completion gates** — currently only task-level. Goal completion (`complete_goal()`) has no gates.

10. **Strengthen metric advancement idempotency** — only update if task_id not already recorded with same value.

11. **Tighten milestone auto-completion derivation** — require explicit task linkage, not just dynamic derivation from potentially stale `related_tasks`.

### 8.4 Lower-Priority (Quality)

12. **Fill test coverage gaps** — obsidian_promoter, followup, inbox, project_progress.

13. **Add type checking (mypy/pyright) and linting (ruff)** — low effort, catches errors early.

14. **Add "Last verified" date to each ADR** — so readers can assess whether the status signal reflects current state.

---

## 9. What This Synthesis Does Not Decide

- Whether to implement the Goal → Milestone → Project → Task hierarchy (2003-line draft) — no implementation commitment exists, and the simpler milestone-only approach from execution_planning.md is already operational.
- Whether Phase 4 adversarial LLM review should be revisited — explicitly out of scope per ADR-004.
- Whether to enable the janus_sync plugin or document gated completion as opt-in — this is an operational decision for the user.
- UUID migration for title-based identity — flagged as MVP constraint, not imminent.

---

## 10. Source Mapping

| Theme | Primary sources |
|-------|----------------|
| Architecture (ADR-001 through ADR-005-A1) | adr_audit_report.md, adr004_reconciliation_findings.md, documentation_roadmap_review_findings.md |
| Lifecycle flow and enforcement | goal_task_execution_completion_review_model.md, execution_planning.md, review_lifecycle_findings.md |
| Goal domain model (implemented + designed) | goal_system_design.md, goal_system_discovery_research.md, goal_health_progress_research_findings.md, measurement_collection_design.md |
| Hierarchy (milestone + project) | goal_milestone_project_task_hierarchy.md, execution_planning.md, repository_inventory_findings.md |
| Verification and observability | verification.md, observability_verification_report.md, e2e_verification_synthesis_t_cbe72f8a.md |
| Documentation staleness and contradictions | documentation_roadmap_review_findings.md, adr_audit_report.md, implementation_notes.md |
| Test coverage and repo structure | repository_inventory_findings.md, implementation_notes.md |
| Runtime plugin status | adr_audit_report.md, repository_inventory_findings.md, adr004_reconciliation_findings.md |
| Product backlog and roadmap | roadmap.md, product_backlog.md, documentation_roadmap_review_findings.md |
| Vision and strategic direction | vision.md, strategic_summary_spec.md |

---

*End of synthesis.*
