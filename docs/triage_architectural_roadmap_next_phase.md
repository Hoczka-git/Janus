# Janus Architectural Triage — Next Development Phase

**Task:** t_ea99cee2
**Date:** 2026-09-24
**Status:** Complete — ready for review

---

## 1. Executive Summary

1. **Architecture is sound and mostly implemented.** ADR-003 (review topology) and ADR-004 (safe sync/integrate) are fully closed — verified by 57 + 48 passing tests respectively. The P0 gap that dominated earlier reports (ADR-004 phases 3-5) is CLOSED by PR #176/#178.

2. **Real open work is concentrated in two areas:** ADR-005 write-gateway consolidation (services still use `data_protection` instead of `atomic_io` — the "sole gateway" claim is contradicted) and ADR-002 curation gate (knowledge pipeline has no Obsidian promotion mechanism).

3. **Multiple stale claims have been cleared:** vault versioning executed, `data/` removed from git, uncommitted docs committed, Model B language removed from prompt. 9 prior-audit claims are now resolved and should not be tracked.

4. **Agency-First gap analysis** — the existing Goal→Task→Execution→Completion→Review loop already embodies much of Agency-First. The missing pieces are formal review gates at goal level, evidence/verification modeling, and curation gate for knowledge pipeline.

5. **No new code implemented in this task.** Analysis only. The triage document below consolidates findings from 6 ADRs, 5 child-task reports, roadmap/vision/principles, synthesis doc, and authoritative open-work list.

---

## 2. Current State

### 2.1 Architecture — Bounded Contexts

| Context | Location | Role |
|---------|----------|------|
| CLI | `src/janus/cli/` | User-facing commands (tasks, goals, workouts, measurements, decisions, activities) |
| Services | `src/janus/services/` | 33 service modules — business logic, persistence orchestration |
| Integrations | `src/janus/integrations/` | 14 modules — markdown I/O, Google Calendar, plugins |
| Models | `src/janus/models/` | 25 domain models — Goal, Task, Metric, Workout, Measurement, etc. |
| Plugins | `src/janus/plugins/` | `janus_sync` (Hermes Kanban sync), `replenishment` |
| Persistence | `data/` (gitignored) | Markdown files — tasks.md, goals.md, followups.md, inbox/, research/, workouts/ |
| Verification | `src/janus/verification.py` | Contract verification, immutable file checks |

**Hermes↔Janus boundary:** Hermes Kanban dispatches Janus tasks via `janus_sync` plugin. Hermes writes back via `dispatch_completion()` routing by `janus_domain.object`. The boundary is the Kanban task lifecycle (claim → execute → complete → review).

### 2.2 Goal → Task → Execution → Completion → Review Loop

Current state (from child task t_f339fe3e findings):

- **Goal:** Lifecycle in `services/goals.py`. Reads/writes `data/goals.md`. Status transitions: active → dormant → completed. No formal gates at goal level — completion is `set_goal_state()`.
- **Task:** Lifecycle in `services/tasks.py`. ADR-004 Phase 5 gated completion: `run_completion_gates()` (clean tree, final sync, test re-run, `git diff --check`) before markdown flip. Structured reason codes. CLI-only on direct path.
- **Execution:** Service functions called by CLI commands. Activity ingestion via ADR-005 gateway (`ingest_activities()`).
- **Completion:** ADR-004 Phase 3 (pre-completion gates) + Phase 5 (completion gating). Task completion writes to `data/tasks.md`. Goal completion not gated — no review step.
- **Review:** **Missing as formal phase.** Goal completion has no gates. Task gating is CLI-only. Milestone auto-completion depends on denormalized `related_tasks` cache. No `under_review` state in goal lifecycle.

### 2.3 ADR Landscape (6 decisions in `docs/decisions/`)

| ADR | Title | Status | Implementation | Agency-First Alignment |
|-----|-------|--------|----------------|------------------------|
| ADR-001 | Hermes-Janus System Model | Accepted | Fully implemented | Aligned — defines boundary |
| ADR-002 | Obsidian Knowledge Layer | Accepted | Pipeline scaffolding exists, **curation gate MISSING** | Partially aligned — knowledge pipeline needs promotion gate |
| ADR-003 | Canonical Review Topology | Accepted | **Fully implemented, verified** (57 tests) | Aligned — review is native phase |
| ADR-003a | Milestone Status Lifecycle | Accepted | Implemented | Aligned |
| ADR-003b | Review Probes and Human Review | Accepted | Implemented | Aligned — human review is first class |
| ADR-004 | Safe Sync-and-Integrate Workflow | Accepted with caveats | **All 5 phases, 48 gate tests** | Aligned — gates protect integrity |
| ADR-005 | Activity Data Ingestion Layer | Accepted (on consolidation) | **Primary gap** — dual write surfaces | Partially aligned — gateway exists but not sole path |
| ADR-006 | Kanban Task Protocol | Accepted | Implemented | Aligned |
| ADR-007 | Execution Feedback Sync | Accepted | Implemented | Aligned |
| ADR-008 | Verification Pipeline | Accepted | Implemented | Aligned |
| ADR-009 | Data Protection — Atomic IO | Accepted | `atomic_io` implemented, `data_protection` still used | Partially aligned — migration incomplete |
| ADR-010 | Observability Strategy | Accepted | Implemented | Aligned |

**Consolidated decision docs on `origin/master` but not HEAD:** `adr-003-004-005-consolidated-decisions.md`, `adr-consolidated-decisions.md`, `vault_versioning_decision.md` — historical artifacts, not blockers.

### 2.4 What Already Embodies Agency-First

- **Goal → Task derivation:** Goals produce tasks via planning. User intent flows through.
- **ADR-004 gates:** Completion is not automatic — gates verify before finalizing. This is agency-protective.
- **ADR-003 review topology:** Review is a native phase, not an afterthought. Human review is first class.
- **ADR-005 gateway:** Single entry point for model-driven writes — controls what modifies data.
- **Verification contracts:** Deterministic checks on domain invariants.
- **Manual override paths:** CLI commands allow direct user action outside agent automation.

---

## 3. Gap Analysis (vs `docs/janus-agency-first-development-phase.md`)

### 3.1 Already Exists

| Element | Where | Evidence |
|---------|-------|----------|
| Goal → Task planning | `services/planning.py`, `services/goals.py` | Goal execution planning extension (PRs #220, #221) |
| Task lifecycle with gates | `services/tasks.py`, ADR-004 | Phase 1-5 implemented, 48 tests pass |
| Review topology (task-level) | ADR-003, DB schema, tools, dispatcher | 57 review tests pass |
| Activity ingestion gateway | ADR-005, `services/activity_ingest.py`, `integrations/atomic_io.py` | Gateway implemented, used by activity_ingest |
| Verification contracts | `verification.py` | Contract verification, immutable file checks |
| Execution feedback sync | ADR-007, `services/execution_feedback.py` | Feedback loop implemented |
| Knowledge pipeline scaffolding | `services/knowledge_pipeline.py` | `validate_artifact()`, `generate_summary()`, `emit_knowledge_gaps_as_attention()` exist |
| Observability | ADR-010, `integrations/observability.py` | Log schema, structured logging |

### 3.2 Partially Exists (foundations, missing formal model/enforcement)

| Element | Gap | Where to look |
|---------|-----|---------------|
| **Goal-level review** | No `under_review` state, no gates before goal completion | `services/goals.py` — `set_goal_state()` has no gate |
| **Curation gate (ADR-002)** | Knowledge pipeline produces summaries but no promotion gate or Obsidian write | `knowledge_pipeline.py` — no `curation_gate()`, `human_approval()`, `promote_to_obsidian()`. `OBSIDIAN_VAULT_PATH` referenced but zero code uses it |
| **Write gateway consolidation (ADR-005)** | 8+ modules use `data_protection.protected_write` instead of `atomic_io` | `tasks.py`, `decisions.py`, `markdown_goals.py`, `markdown_inbox.py`, `markdown_followups.py`, `markdown_research.py`, `workout_md.py`, `measurement_log.py` |
| **Evidence/Verification model** | No formal `Evidence` concept — execution results are implicit in data files | No `evidence.py` or evidence model in domain |
| **Policy/Approval model** | No `ALLOW/ASK/DENY` abstraction — approval is implicit in review topology and CLI | No policy engine |
| **PersonalState** | No formal `PersonalState` concept — user context is implicit in goals/tasks/metrics | Not modeled |

### 3.3 Missing

| Element | Where it should be | Notes |
|---------|--------------------|-------|
| **Goal completion gates** | `services/goals.py` — `complete_goal()` or equivalent | Goal completion should have gates similar to task completion (ADR-004 Phase 5 pattern) |
| **Review phase for goals** | Goal lifecycle — `under_review` state | Extends ADR-003 from tasks to goals |
| **Curation gate implementation** | `services/knowledge_pipeline.py` | Implement `curation_gate()`, `human_approval()`, `promote_to_obsidian()` |
| **Obsidian promotion** | `integrations/obsidian_promoter.py` (exists but unused) | Vault versioning now available — unblocks this |
| **Evidence model** | New module — `services/evidence.py` or domain concept | What counts as evidence, how it flows to metrics |
| **Write gateway migration** | 8+ service/integration modules | Migrate from `protected_write` to `atomic_io.read_modify_write_with_retry` |

### 3.4 Should NOT Be Implemented (yet)

| Element | Reason |
|---------|--------|
| **Multi-agent system** | Premature — Agency-First is about user agency, not agent autonomy. Current Hermes→Janus boundary is sufficient. |
| **Event sourcing / full audit log** | Over-engineered for current needs. Verification contracts + review topology provide sufficient audit trail. |
| **Complex policy engine** | `ALLOW/ASK/DENY` as a formal engine is premature. Review topology + CLI override paths cover current needs. |
| **PersonalState as separate bounded context** | Personal state is implicit in goals, tasks, metrics, workouts. Extract only when there's a clear need that existing models can't express. |
| **Metrics engine rewrite** | Metric progression semantics (t_312decf2) are being defined. Don't build infrastructure before semantics are stable. |

---

## 4. Target Domain Model (proposed)

### 4.1 First-Class Domain Concepts

| Concept | First-class? | Truth source | Reasoning |
|---------|-------------|--------------|-----------|
| **Goal** | Yes | `data/goals.md` (via `goals.py`) | Core unit of user intent |
| **Metric** | Yes | `data/metrics/` or metric fields on Goal | Measures goal progress — semantics being defined (t_312decf2) |
| **Plan** | Yes (as part of Goal) | `data/goals.md` / planning service | Goal execution plan — already exists |
| **Task** | Yes | `data/tasks.md` (via `tasks.py`) | Unit of work — already first-class |
| **User Action** | Implicit | CLI commands, manual edits | User agency point — doesn't need to be a domain object yet |
| **Execution** | Implicit | Service function calls | Execution is what services do — not a separate domain concept |
| **Evidence** | **New — should be first-class** | To be defined | What counts as proof that work happened — needed for goal completion gates |
| **Verification** | Yes (partial) | `verification.py` + ADR-004 gates | Already exists at task level — needs to extend to goals |
| **Completion** | Yes | `tasks.py:complete_task()`, `goals.py:set_goal_state()` | Already exists — needs gates at goal level |
| **Review** | Yes (task-level) | ADR-003 | Exists for tasks — needs extension to goals |
| **Decision** | Yes | `data/decisions/` + ADR-006 | Already modeled — ADR-005 activity ingestion is a decision |
| **PersonalState** | **Not yet** | Implicit in goals/tasks/metrics | Extract when there's a clear need |

### 4.2 Key Relationships

```
Goal ──contains──> Plan
Goal ──measures──> Metric
Goal ──produces──> Task (via planning)
Task ──generates──> Evidence (proposed)
Evidence ──supports──> Verification
Verification ──enables──> Completion
Completion ──triggers──> Review (proposed for goals)
Review ──result───> Decision
```

### 4.3 Invariants (proposed)

1. **Goal completion requires evidence.** A goal cannot be marked completed without at least one evidence record supporting it.
2. **Metrics are derived, not guessed.** Metric values come from explicit user input, measured data, or deterministic derivation — never from agent speculation.
3. **Review is optional but available.** Not every completion needs review, but the path exists when it does.
4. **Write gateway is sole path for data/ writes.** (ADR-005 aspiration — currently violated, see gap analysis.)
5. **Completion gates run before state change.** (ADR-004 pattern — already implemented for tasks, proposed for goals.)

### 4.4 Responsibility Boundaries

| Boundary | What it owns |
|----------|-------------|
| **Goal service** | Goal lifecycle, status transitions, metric aggregation |
| **Task service** | Task lifecycle, gated completion (ADR-004) |
| **Planning service** | Goal → Task derivation, next-action selection |
| **Evidence service (proposed)** | Evidence records, evidence→metric linkage |
| **Knowledge pipeline (proposed curation gate)** | Artifact validation, human approval, Obsidian promotion |
| **Integration service** | External system sync (Google Calendar, Hermes Kanban) |
| **CLI** | User commands, manual overrides — agency point |

---

## 5. Agency-Aware Execution Model

### 5.1 Do we need `execution_mode: USER / JANUS / COLLABORATIVE`?

**Probably not as a formal enum.** The current model already captures this:

- **USER:** CLI commands, manual edits to markdown files. User acts directly.
- **JANUS:** Service functions called by CLI or by Hermes via `janus_sync` plugin. Janus executes on user's behalf within gates.
- **COLLABORATIVE:** The review topology (ADR-003) + planning + execution feedback (ADR-007) already create a collaborative loop. The user sets direction, Janus proposes/executes, user reviews.

**Recommendation:** Don't add `execution_mode` as a domain concept yet. The distinction is already implicit in *who invokes the service* (CLI vs Hermes dispatch) and *what gates apply*. Add it only if there's a concrete need (e.g., different permissions, different audit trails, different UI paths).

### 5.2 Do we need `support_mode: EXPLAIN / COACH / SCAFFOLD / REVIEW / EXECUTE`?

**Partially — REVIEW is already first-class (ADR-003).** The others map to existing patterns:

- **EXPLAIN:** `janus goal explain`, `janus task explain` — already exists as read-only commands.
- **COACH:** Planning suggestions, next-action derivation — exists in planning service.
- **SCAFFOLD:** Forms/templates for user input — exists in CLI structure.
- **REVIEW:** Native review lane (ADR-003) — implemented.
- **EXECUTE:** Service functions with gates — implemented.

**Recommendation:** Don't add `support_mode` as a domain concept. The existing CLI surface + planning + review topology cover these modes without a formal enum. If a future phase needs mode-specific behavior (different permissions, different UI, different audit), add it then.

### 5.3 Simpler alternative that achieves the same effect

The core Agency-First insight is: **Janus should increase user agency, not replace it.** This is achieved by:

1. **Gates before auto-completion** (ADR-004) — Janus doesn't finalize without verification.
2. **Review as native phase** (ADR-003) — human review is always available.
3. **Manual override paths** — CLI commands let users act directly, bypassing automation.
4. **Explicit evidence requirement** (proposed) — completion requires proof, not agent assertion.
5. **Planning as suggestion, not command** — goals produce tasks, user decides which to act on.

This is simpler than a formal `execution_mode`/`support_mode` taxonomy and covers the actual agency needs.

---

## 6. Evidence / Verification / Audit (minimal model)

### 6.1 Proposed Concepts

```
Evidence:
  - source: manual | measured | derived | system
  - target: goal | task | metric
  - timestamp
  - payload: {...}  # domain-specific proof
  - hash: content integrity

Verification:
  - target: goal | task
  - check: contract | gate | review
  - result: pass | fail | pending
  - timestamp

Decision:
  - type: completion | review_result | policy | goal_state
  - authority: user | agent | system
  - rationale: string
  - timestamp
```

### 6.2 Key Distinctions

- **Evidence ≠ Execution result.** Execution result is "the service ran and wrote data." Evidence is "here's proof the work accomplished what was intended." A workout was logged (execution) vs. the workout data shows progressive overload over 8 weeks (evidence).
- **Verification ≠ Completion.** Verification is the check. Completion is the state change. ADR-004 already separates these for tasks — Phase 3 (verify) before Phase 5 (complete).
- **Audit Event ≠ Decision.** An audit event is "something happened" (trace). A decision is "someone chose X for reason Y" (intent). Both are useful but different.

### 6.3 What Evidence Is Required

- **Goal completion:** At least one evidence record linking the goal to demonstrated progress.
- **Task completion:** The ADR-004 gates serve as structural evidence (tests pass, tree clean, sync done). Additional domain evidence may be needed for specific task types.
- **Metric update:** The update itself is evidence (explicit user input or measured data).

### 6.4 Determinism

Evidence records should be deterministic given their inputs — same source data + same derivation = same evidence. This allows re-verification. Non-deterministic evidence (agent-generated summaries, AI assessments) should be labeled as such and not used as sole basis for completion.

---

## 7. Policy / Approval (minimal model)

### 7.1 Current State

The current system already has implicit policy via:

- **ADR-004 gates:** Completion doesn't happen without verification. This is an implicit `ASK` for the system — "are you sure?" answered by test results.
- **ADR-003 review:** Human review is available as a phase. This is `ASK` for high-stakes changes.
- **CLI override:** Users can act directly via CLI, bypassing agent automation. This is `ALLOW` with user authority.

### 7.2 Proposed Minimal Model

```
Policy decision:
  - action: what is being attempted
  - context: goal/task/metric being affected
  - risk_level: low | medium | high  (determined by what's at stake)
  - verdict: ALLOW | ASK | DENY

Risk levels (proposed):
  - low:    metric update, task status change, log entry — ALLOW (gated by normal service logic)
  - medium: goal status change, milestone completion — ASK (verification gates, possibly review)
  - high:   goal deletion, bulk state changes, external system writes — ASK (explicit user approval via CLI)
```

### 7.3 What Should Be Deterministic

- **Gate outcomes:** ADR-004 gates are deterministic — same code state = same gate result.
- **Metric derivation:** Deterministic given inputs.
- **Task→Metric rules:** Being defined in t_312decf2 — should be deterministic.

### 7.4 What Can Be Agent Decision

- **Task prioritization** within a goal — agent suggests, user decides.
- **Next-action selection** — agent proposes, user acts.
- **Knowledge curation** — agent summarizes, curation gate decides promotion.

### 7.5 When User Approval Is Required

- **Goal completion** (proposed): At minimum, verification gates. For high-stakes goals, explicit user confirmation.
- **Goal deletion:** Always explicit.
- **Bulk operations:** Always explicit.
- **External system writes beyond read-only:** Explicit (Google Calendar write, not just read).

### 7.6 Policy Boundary

The policy boundary is at the **service function entry point**. Before any state-changing operation, the service checks: is this low/medium/high risk? Does it need gates? Does it need explicit user approval? The CLI is the user-approval channel — if a service function needs approval, it returns a prompt for CLI to present to the user.

---

## 8. ADR Plan

### 8.1 Existing ADRs That Need Extension

| ADR | Extension needed | Why |
|-----|-----------------|-----|
| **ADR-004** | Extend gated completion to goals | Currently only tasks have Phase 3-5 gates. Goal completion should have similar gates. |
| **ADR-003** | Extend review topology to goals | Review is defined for tasks. Goals need `under_review` state and review phase. |
| **ADR-005** | Complete write gateway migration + doc update | Services still use `data_protection`. Migration needed. §2/§6 need caveat. CI grep gate needed. |
| **ADR-002** | Implement curation gate | Pipeline exists but no promotion gate. Need `curation_gate()`, `human_approval()`, `promote_to_obsidian()`. |

### 8.2 New ADR Proposals

**ADR-011: Goal-Level Completion Gates**
- Status: Proposed
- Context: ADR-004 gates apply to tasks. Goal completion has no gates — `set_goal_state()` writes directly.
- Decision: Goal completion requires verification gates modeled on ADR-004 Phase 3/5 pattern.
- Rationale: Agency-First — goals are higher-level than tasks, completion should be more carefully guarded, not less.
- Consequences: `services/goals.py` gains gate functions. Goal completion becomes multi-step (verify → complete).

**ADR-012: Evidence Model for Goal Tracking**
- Status: Proposed
- Context: No formal evidence concept. Goal completion is state-based, not evidence-based.
- Decision: Introduce Evidence as a first-class concept linking work to goal progress.
- Rationale: Agency-First — completion should be provable, not assertable. Evidence provides the proof.
- Consequences: New `services/evidence.py` or domain concept. Evidence records in `data/evidence/`. Metric derivation can reference evidence.

**ADR-013: Curation Gate for Knowledge Pipeline**
- Status: Proposed (extends ADR-002)
- Context: ADR-002 defines Obsidian knowledge layer but curation gate is not implemented. Pipeline produces summaries with no promotion mechanism.
- Decision: Implement curation gate with human approval before Obsidian promotion.
- Rationale: Knowledge artifacts shouldn't auto-promote — human curation preserves quality and agency.
- Consequences: `curation_gate()`, `human_approval()`, `promote_to_obsidian()` in `knowledge_pipeline.py`. Vault versioning now available.

### 8.3 ADRs That Don't Need Changes

- **ADR-001** (system model) — still accurate.
- **ADR-006** (kanban task protocol) — still accurate.
- **ADR-007** (execution feedback sync) — still accurate.
- **ADR-008** (verification pipeline) — still accurate, may be referenced by new evidence model.
- **ADR-010** (observability) — still accurate.

---

## 9. Roadmap

### P0 — Necessary Foundations

**P0-1: ADR-005 write gateway migration**
- Problem: Two write surfaces contradict "sole gateway" claim. Data integrity risk.
- Scope: Migrate 8+ modules from `protected_write` to `atomic_io.read_modify_write_with_retry`.
- Dependencies: None — `atomic_io` is already implemented and used by `activity_ingest.py`.
- Acceptance criteria: Zero `protected_write` calls in service/integration modules (except `data_protection.py` itself if kept as legacy). ADR-005 §2/§6 updated.
- Tests: Existing tests should continue passing. Add regression test that greps for unauthorized write paths.
- Suggested ADR: Update ADR-005 (no new ADR needed — this is completing an existing one).
- Suggested PRs: One PR per module or grouped by domain (tasks+decisions, markdown integrations, goals+workout).

**P0-2: ADR-004 gates extended to goals**
- Problem: Goal completion has no gates. Higher-level entities have weaker guards than lower-level ones.
- Scope: Add `run_goal_completion_gates()` modeled on ADR-004 Phase 3/5. `complete_goal()` becomes gated.
- Dependencies: P0-1 (clean write gateway makes gate implementation cleaner).
- Acceptance criteria: Goal completion runs verification before state change. Failed gates block completion with reason code.
- Tests: New test file `tests/test_goal_completion_gates.py`. Mock goal state, verify gates run, verify blocked completions.
- Suggested ADR: ADR-011 (Goal-Level Completion Gates).
- Suggested PRs: One PR for gate implementation + tests.

### P1 — Directly Needed for Agency-First

**P1-1: Evidence model**
- Problem: No formal evidence concept. Goal completion is assertable but not provable.
- Scope: Introduce Evidence concept. Evidence records linked to goals/tasks/metrics. Metric derivation can reference evidence.
- Dependencies: P0-2 (goal gates provide natural insertion point for evidence requirement).
- Acceptance criteria: Evidence records exist. Goal completion can require evidence. Evidence is deterministic given inputs.
- Tests: Evidence creation, evidence→goal linkage, evidence immutability.
- Suggested ADR: ADR-012 (Evidence Model).
- Suggested PRs: Evidence model + storage + basic service functions.

**P1-2: Curation gate for knowledge pipeline**
- Problem: Pipeline produces summaries but no promotion mechanism. Obsidian vault versioning is now available.
- Scope: Implement `curation_gate()`, `human_approval()`, `promote_to_obsidian()` in `knowledge_pipeline.py`.
- Dependencies: Vault versioning executed. P0-1 (clean write gateway for Obsidian writes).
- Acceptance criteria: Artifacts go through curation gate before Obsidian promotion. Human approval is a gate step.
- Tests: Curation gate flow, approval rejection, promotion success/failure.
- Suggested ADR: ADR-013 (extends ADR-002).
- Suggested PRs: Curation gate implementation + tests.

**P1-3: Goal-level review phase**
- Problem: Review topology (ADR-003) is defined for tasks. Goals have no `under_review` state.
- Scope: Add `under_review` state to goal lifecycle. Goal completion can enter review before finalizing.
- Dependencies: P0-2 (goal gates) — review is a gate step.
- Acceptance criteria: Goals can enter `under_review`. Review transitions work like task review (ADR-003 pattern).
- Tests: Goal review lifecycle, review transitions, re-review.
- Suggested ADR: Extends ADR-003 (no new ADR — extend existing).
- Suggested PRs: Goal review state + transitions + tests.

### P2 — Valuable Extensions

**P2-1: CI grep gate for write paths (GAP-008)**
- Problem: No CI rule enforcing write gateway discipline. A service could add a non-atomic data/ write without CI catching it.
- Scope: Add verification rule in `verification.py` or separate script that greps for `data/` writes outside approved gateway modules.
- Dependencies: P0-1 (gateway migration completes — gate verifies the migration held).
- Acceptance criteria: CI fails if new `data/` write paths appear outside `atomic_io` (and `data_protection.py` if kept as legacy).
- Tests: The CI rule itself is the test — add a test that verifies the grep catches known violations.
- Suggested PR: One PR for the CI gate.

**P2-2: Documentation updates**
- GAP-007: ADR-005 §2/§6 caveat (migration in progress, "sole gateway" aspirational).
- ADR-003 §7.7: CLI help wording — "first-class" → "canonical/primary workflow".
- Consolidated ADR docs back-port to HEAD (or mark as "master only").

### P3 — Later / Experimental

**P3-1: PersonalState as explicit concept**
- Extract when there's a clear need that existing models (goals, tasks, metrics, workouts) can't express.

**P3-2: Execution mode / support mode taxonomy**
- Add only if there's a concrete need for mode-specific behavior (permissions, UI, audit).

**P3-3: Full audit log / event sourcing**
- Over-engineered for current needs. Review topology + verification contracts + evidence model provide sufficient audit trail.

---

## 10. Immediate Implementation Plan (next 2-4 weeks)

### Task 1: ADR-005 write gateway migration (P0-1)

**Title:** Migrate service/integration modules from `data_protection.protected_write` to `atomic_io.read_modify_write_with_retry`

**Objective:** Make `atomic_io` the sole write gateway for `data/` as required by ADR-005.

**Scope:**
- `services/tasks.py` — lines 74, 184, 284, 349
- `services/decisions.py` — lines 132, 172, 223, 274
- `integrations/markdown_goals.py` — lines 46, 764, 787
- `integrations/markdown_inbox.py` — lines 158, 163
- `integrations/markdown_followups.py` — lines 194, 199
- `integrations/markdown_research.py` — line 16
- `integrations/workout_md.py` — lines 14, 93
- `services/measurement_log.py` — line 103 (append-only JSONL — may need special handling)

**Out of scope:**
- `data_protection.py` deletion (defer — may be kept as legacy with deprecation notice)
- `google_calendar.py:42` (token cache, not data/ — exempt)
- New features

**Dependencies:** None — `atomic_io` is already implemented.

**Acceptance criteria:**
- Zero `protected_write` calls in migrated modules.
- All existing tests pass.
- ADR-005 §2/§6 updated with migration status.

**Tests:** Existing tests should continue passing. Add a verification script that greps for `protected_write` usage outside `data_protection.py`.

**Suggested PR boundary:** One PR per module group, or one large PR if modules are tightly coupled. Prefer smaller PRs.

---

### Task 2: Goal completion gates (P0-2, ADR-011)

**Title:** Add gated completion to goal lifecycle (ADR-011)

**Objective:** Extend ADR-004 Phase 3/5 gate pattern to goal completion.

**Scope:**
- `services/goals.py` — add `run_goal_completion_gates()` + gated `complete_goal()`
- New test file `tests/test_goal_completion_gates.py`
- Update goal lifecycle docs

**Out of scope:**
- Evidence model (P1-1) — gates can start with structural checks (goal has tasks completed, metrics at target) and later require evidence
- Review phase for goals (P1-3) — gates and review are separate concerns

**Dependencies:** P0-1 (clean write gateway preferred but not strictly required).

**Acceptance criteria:**
- Goal completion runs gates before state change.
- Failed gates block completion with structured reason code.
- Gates are deterministic.

**Tests:** Gate pass/fail scenarios, reason code propagation, idempotency.

**Suggested ADR:** ADR-011 (Goal-Level Completion Gates).

**Suggested PR boundary:** One PR for implementation + tests.

---

### Task 3: Curation gate for knowledge pipeline (P1-2, ADR-013)

**Title:** Implement curation gate for Obsidian knowledge pipeline (ADR-013)

**Objective:** Add human-approval gate before artifact promotion to Obsidian vault.

**Scope:**
- `services/knowledge_pipeline.py` — add `curation_gate()`, `human_approval()`, `promote_to_obsidian()`
- `integrations/obsidian_promoter.py` — wire up for actual promotion (currently unused)
- Use vault versioning now available at `/mnt/c/Users/dan11/Documents/HermesVault`

**Out of scope:**
- Knowledge pipeline restructuring — work within existing `validate_artifact()`, `generate_summary()`, `emit_knowledge_gaps_as_attention()`
- Obsidian vault content model — use existing vault structure

**Dependencies:** Vault versioning executed. P0-1 preferred (clean write gateway for Obsidian writes).

**Acceptance criteria:**
- Artifacts go through curation gate before promotion.
- Human approval is a required gate step.
- Promotion writes to Obsidian vault via `atomic_io` (not direct write).

**Tests:** Curation flow, approval rejection, promotion success, promotion failure recovery.

**Suggested ADR:** ADR-013 (extends ADR-002).

**Suggested PR boundary:** One PR for curation gate + promotion + tests.

---

### Task 4: CI grep gate for write paths (P2-1, GAP-008)

**Title:** Add CI verification rule enforcing write gateway discipline

**Objective:** Prevent regression — CI should catch new `data/` write paths outside approved gateway.

**Scope:**
- Add verification rule in `verification.py` or separate script
- Rule: grep for `data/` file writes outside `atomic_io.py` (and `data_protection.py` if kept as legacy)
- Integrate into CI workflow

**Out of scope:**
- Gateway migration itself (P0-1) — this is regression protection for it

**Dependencies:** P0-1 (gate validates the migration held).

**Acceptance criteria:**
- CI fails if new unauthorized write paths appear.
- Rule has no false positives on existing code.

**Tests:** Test that the grep catches known violation patterns.

**Suggested PR boundary:** One PR for the CI gate.

---

### Task 5: Documentation updates (P2-2)

**Title:** Update ADR documentation to reflect current state

**Objective:** Fix inaccurate claims and complete pending doc items.

**Scope:**
- ADR-005 §2/§6 — add caveat that migration is in progress, "sole gateway" is aspirational
- ADR-003 §7.7 — CLI help wording: "first-class" → "canonical/primary workflow"
- Consolidate or archive consolidated ADR docs on HEAD
- Remove 11 `tmp_*.py` scratch files

**Out of scope:**
- Anything beyond documentation and cleanup

**Dependencies:** None.

**Acceptance criteria:** Docs accurately reflect code state. No stale claims in active docs.

**Suggested PR boundary:** One PR for all doc updates + cleanup.

---

## 11. Proposed `docs/roadmap.md` Diff

This section proposes the minimal addition to `docs/roadmap.md` to reflect the Agency-First development phase. It does NOT duplicate `docs/janus-agency-first-development-phase.md` — it references it and adds concrete roadmap items.

```markdown
## Phase: Agency-First Development (next)

**Reference:** `docs/janus-agency-first-development-phase.md`
**Start:** 2026-09-24 (triage complete, t_ea99cee2)
**Principle:** Janus exists to help a person do difficult things—not to do the person's life for them. Every architectural decision is evaluated against whether it increases user agency, capability, and ability to achieve difficult outcomes.

### Already delivered (foundations)

- [x] ADR-003 Canonical Review Topology — Model A fully implemented, 57 tests pass
- [x] ADR-004 Safe Sync-and-Integrate Workflow — all 5 phases, 48 gate tests pass
- [x] ADR-001 Hermes-Janus System Model — boundary defined and implemented
- [x] Vault versioning executed — HermesVault has `.git`, `.gitignore`, initial commits
- [x] Goal → Task → Execution → Completion → Review loop verified end-to-end

### P0 — Necessary foundations

- [ ] **ADR-005 write gateway migration** — migrate 8+ modules from `data_protection` to `atomic_io`. Two write surfaces contradict "sole gateway" claim. (triage finding, GAP-005)
- [ ] **Goal completion gates (ADR-011)** — extend ADR-004 Phase 3/5 pattern to goal lifecycle. Goal completion currently has no gates. (triage finding)

### P1 — Directly needed for Agency-First

- [ ] **Evidence model (ADR-012)** — introduce Evidence as first-class concept. Goal completion should be provable, not assertable. (triage finding)
- [ ] **Curation gate for knowledge pipeline (ADR-013)** — implement human-approval gate before Obsidian promotion. Vault versioning now available. (triage finding, GAP-001)
- [ ] **Goal-level review phase** — extend ADR-003 review topology to goals. Add `under_review` state to goal lifecycle. (triage finding)

### P2 — Valuable extensions

- [ ] **CI grep gate for write paths (GAP-008)** — regression protection for ADR-005 migration.
- [ ] **ADR documentation updates** — ADR-005 §2/§6 caveat, ADR-003 CLI help wording, consolidated ADR docs, `tmp_*.py` cleanup.
- [ ] **Metric progression semantics** — finalize task→metric rules (t_312decf2, in progress).

### P3 — Later / experimental

- [ ] PersonalState as explicit concept (extract when need is clear)
- [ ] Execution mode / support mode taxonomy (add only if concrete need emerges)
- [ ] Full audit log / event sourcing (over-engineered for current needs)

### Not planned (yet)

- Multi-agent system — Agency-First is about user agency, not agent autonomy
- Event sourcing — review topology + verification + evidence provide sufficient audit
- Complex policy engine — review topology + CLI override paths cover current needs
```

---

## 12. Risks / Open Questions

1. **ADR-005 migration scope:** 8+ modules need migration. Some (`measurement_log.py` append-only JSONL) may need special handling. Risk: migration introduces subtle bugs in persistence. Mitigation: one module at a time, existing tests as safety net.

2. **Goal completion gates — what exactly should they check?** Structural checks (tasks completed, metrics at target) are straightforward. Evidence requirement (P1-1) is more complex. Risk: gates become too strict and block legitimate completions. Mitigation: start with structural gates, add evidence requirement later.

3. **Curation gate — what's the approval UX?** `human_approval()` needs a channel. CLI is the natural choice, but the details (how does the user see the artifact? how do they approve/reject?) need design. Risk: gate exists but approval flow is awkward, so users bypass it. Mitigation: design approval UX with user input before implementing.

4. **Evidence model — storage and querying:** Where do evidence records live? How are they queried for goal/metric derivation? Risk: over-engineered storage that's rarely queried. Mitigation: start simple (markdown files in `data/evidence/`), escalate only if querying needs demand it.

5. **Vault promotion — Obsidian API:** `obsidian_promoter.py` exists but is unused. Does it need modification to work with current vault structure? Risk: promotion fails on first attempt due to vault structure mismatch. Mitigation: test promotion against a real vault before merging.

6. **ADR-002 status:** Currently "Accepted" but curation gate is not implemented. Should status be "Proposed" until gate exists? Risk: status mismatch confuses future readers. Mitigation: update ADR-002 status as part of curation gate work.

---

## 13. Summary for Reviewer

This triage analyzed the Janus repository against the Agency-First development phase. Key findings:

- **Architecture is sound.** ADR-003 and ADR-004 are fully implemented and verified. The Goal→Task→Execution→Completion→Review loop is operational.
- **Two P0 gaps:** ADR-005 write gateway migration (dual write surfaces) and goal completion gates (no gates at goal level).
- **Three P1 items:** Evidence model, curation gate, goal-level review.
- **Agency-First is largely embodied** in existing architecture — gates, review topology, manual override paths, single write gateway (aspirationally). The missing pieces extend these patterns to goals and knowledge pipeline.
- **No new code implemented.** This is analysis and planning. The triage document + proposed roadmap diff are the deliverables.

**Proposed next step:** Reviewer approves direction, then Task 1 (ADR-005 migration) and Task 2 (goal completion gates) are created as kanban tasks and executed as independent PRs.
