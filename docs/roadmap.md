# Hermes / Janus Roadmap

**Last verified:** 2026-10-01

This document describes the strategic direction and intended sequencing for the
Hermes / Janus system.

Implementation status must always be verified against the current repository,
Hermes installation, Kanban state, and integrations.

The roadmap describes direction and sequencing, not guaranteed implementation
state.

---

# Product Direction

Hermes is evolving toward a persistent personal Chief of Staff capable of
working across multiple domains.

The system should combine:

- persistent user context,
- autonomous but controlled execution,
- deterministic domain logic,
- structured operational data,
- curated long-term knowledge,
- multiple input and interaction interfaces.

The development strategy is to build useful capabilities incrementally while
maintaining:

- clear ownership boundaries,
- deterministic foundations,
- observable system state,
- evidence-based verification,
- reusable infrastructure,
- minimal duplication of existing Hermes capabilities.

A key architectural principle is:

> Build domain capabilities in Janus. Reuse Hermes for agent orchestration whenever possible.

---

# Architecture Direction

```text
Multiple User Interfaces
│
├── ChatGPT
├── Telegram
├── CLI
└── Future Interfaces
│
▼
Hermes
Agent Runtime / Orchestration / Kanban / Scheduling
│
├── Profiles
├── Workers
├── Task Dispatch
├── Workspaces
├── Review Workflow
├── Execution History
├── Autonomous Runs
├── Verification Gates
└── Repository Integration
│
▼
Janus
Domain Logic / Models / Deterministic Analysis
│
├── Goals
├── Tasks
├── Fitness
├── Research
├── Reviews
└── Future Domains
│
▼
Persistent Data
│
├── Operational Data
├── Structured Domain Data
└── Curated Knowledge
│
▼

---

# Near-Term Implementation

The following items represent planned implementation work derived from
existing design and planning artifacts in this repository.

- [x] Implement the execution planning extension described in
  [`docs/design/execution_planning.md`](../docs/design/execution_planning.md)
- [x] Implement the structured observability log schema and instrumentation
  described in [`docs/design/observability_plan.md`](../docs/design/observability_plan.md)
- [x] Verify roadmap-driven task replenishment end-to-end (triage targeting,
  idempotency, audit trail) — see `docs/guides/replenishment_sources.md`
- [x] Extend goal management with goal health, progress signals, and
  stalled-goal detection
- [x] Extend execution planning with goal → milestone → project → task
  hierarchy and goal-aware task recommendations
- [x] Janus CLI's complete_task finds all matching [ ] lines and errors on >1 match.
  Add safeguard, and return to user warning when trying to add duplicate entry to tasks
  (safeguard in place: complete_task refuses on duplicates with actionable CLI warning;
  handle_task_add rejects duplicate open entries with clear message)
- [x] Implement a unified inbox and follow-up model for capturing and
  tracking actionable items that do not yet belong to an active task
- [x] Close the research → finding → decision → action loop by connecting research artifacts with decisions, goals, projects, and follow-up tasks
- [x] Implement Janus ↔ Hermes execution feedback, including task handoff, execution results, evidence, and resulting state updates
- [x] Complete and verify the Goal → Task → Execution → Completion → Review loop
  - Status transitions and execution evidence verified.
  - Production verification of Completion → Goal Update and Review complete (ADR-002 curation gate with VAULTED state).
  - Verified end-to-end (E2E checks pass; see `.verifications/goal_task_execution_loop_report.md`).
- [x] Add evidence-based skill tracking linking completed work and project outcomes to career-development goals
- [x] Add strategic state summaries that surface meaningful changes, neglected goals, stalled work, and recommended next actions
- [x] Define the `GoalIntegrityReport` and `GoalIntegrityIssue` domain models. specification in [`docs/design/goal_integrity_audit.md`
- [x] Implement deterministic goal/task integrity checks. specification in [`docs/design/goal_integrity_audit.md`
- [x] Add `janus goal audit` CLI command. specification in [`docs/design/goal_integrity_audit.md`
- [x] Add `janus goal audit --json` output and exit-code semantics
- [x] Add unit and CLI test coverage. specification in [`docs/design/goal_integrity_audit.md`](../docs/design/goal_integrity_audit.md)
- [x] Document the audit specification in [`docs/design/goal_integrity_audit.md`](../docs/design/goal_integrity_audit.md)
- [x] Consolidate the goal execution planning extension into the Janus domain layer and add automated tests for boundary cases.
- [~] Complete the knowledge curation gate for artifact promotion into the Obsidian vault.
  - `curation_gate.py` + `CurationProposal` state machine implemented; `create_curation_proposal` in `knowledge_pipeline.py`. `promote_to_vault` wired in `research_cli.py`. Full `human_approval()` → `promote_to_vault()` flow not yet end-to-end verified in production.
- [x] Expose deterministic goal next-action derivation through `janus goal next <title>` and integrate it into user-facing reviews.

## Agency-First Janus

See [Agency-First Development Phase](janus-agency-first-development-phase.md).

Janus should optimize for increasing user capability and agency,
not maximizing autonomous agent execution.

Key phases:
- [~] Phase A — Complete the Core Loop (P0)
  - Goal → Planning → Task → Execution → Completion → Review. Foundational; must not be bypassed by adding autonomous features.
  - Status: ADR-005 migration, ADR-011 gates planned. See `docs/triage/architectural_roadmap_next_phase.md` §8/§9.
- [~] Phase B — Evidence & Audit (P1)
  - First-class evidence, verification results, outcome records, decision records, audit trail. Goal: make Janus able to explain how it knows that progress occurred.
  - Status: ADR-011 (goal-level gates) proposed; ADR-012 (evidence model) proposed. See `docs/decisions/adr-011-goal-level-completion-gates.md`.
  - Progress: Goal remediation engine implemented (structured action suggestions); integrated with weekly review (PR #267).
  - Depends on: Phase A.
- [x] Phase C — Personal State Model (P1)
  - Structured model of goals, metrics, tasks, projects, commitments, routines, constraints, preferences, activities, evidence, decisions. Goal: give Janus a coherent model of the user's current situation.
  - Status: Implemented. PersonalState dataclass (read-model aggregate root), PersonalStateBuilder service (constructs aggregate from data files with fingerprint caching, integrity checks), persistence layer, and comprehensive tests. See PRs #268, #269, #270.
  - Depends on: Phase A.
- [x] Phase D — Agency-Aware Planning (P1)
  - execution_mode (USER/JANUS/COLLABORATIVE) + support_mode (EXPLAIN/COACH/SCAFFOLD/REVIEW/EXECUTE). Planner chooses least substitutive mode that enables progress.
  - Status: Implemented (ExecutionMode/SupportMode enums, TaskAgency dataclass, AgencyContext, classify_task/dispatch_task in agency_planning service; wired into derive_next_action(); 126 agency tests pass). See PR #337, #335.
  - Depends on: Phases A, C.
- [x] Phase E — Policy & Approval (P1/P2)
  - Action classification, configurable policies, approval requests, explicit user confirmation, auditability. Goal: increase automation without reducing user control.
  - Depends on: Phases A, B.
- [ ] Phase F — Connector Protocol (P2)
  - Common interface for external data and actions (source, capabilities, permissions, read, propose, execute, evidence). Optimize for clean capability model, not number of integrations.
  - Depends on: Phases A, B.
- [x] Phase G — Self-Extending Skills (P2)
  - Identify missing capabilities, propose new skills. Lifecycle: proposal → generate → tests → sandbox → verification → approval → install. Generated capabilities must not silently become trusted.
  - Depends on: Phases A, E.
- [x] Phase H — Multi-Agent Orchestration (P3)
  - Specialized agents (Planner, Researcher, Executor, Reviewer, Coach) only when real workload benefits. Orchestration subordinate to Janus domain model.
  - Status: Implemented. AgentCoordinator (delegate/aggregate/handle_timeout/execute_with_fallback/retry_with_backoff), AgentRegistry (role-to-capability mapping), AgentRole/AgentLifecycle enums, AgentAssignment dataclass, dispatch_task() in agency_planning service. 37 coordination tests pass.
  - Depends on: Phases A–G.
- [x] Finalize "integration_required" policy and implement deterministic type-based auto-detection with explicit metadata precedence, safe ambiguous fallback, non-worktree handling, and independent parent/child semantics.
- [x] Close the Janus completion-gates lifecycle gap and make completion-gate execution deterministic, idempotent, auditable, and correctly integrated with task completion.
- [x] Harden root/child lifecycle semantics so coordination roots wait through dependency gating without duplicating child work or incorrectly requiring integration.
- [x] Complete and verify the end-to-end Goal → Task → Execution → Completion → Review lifecycle across real Janus/Hermes execution.
- [x] Operationalize Agency-Aware Planning by integrating "execution_mode", "support_mode", and least-substitutive-mode selection into planner decisions.
- [x] Build autonomous task-completion verification based on objective evidence from execution, children, integration, and review.
- [x] Establish unified lifecycle observability for task creation, decomposition, execution, integration, blocking, completion, retry, and review.
- [x] Build an end-to-end autonomous lifecycle regression suite covering roots, children, swarms, integration gates, completion gates, failures, retries, and reviews.
- [x] Establish unified lifecycle observability for task creation, decomposition, execution, integration, blocking, completion, retry, and review. (Plan finalized t_d61f4ce7; spec: docs/design/unified_lifecycle_observability_spec.md; 15 lifecycle.* events; 4-phase rollout. See child tasks t_7adc5a80 audit, t_eb2d2ec9 gap analysis, t_775f6038 design spec, t_4276ffa2 synthesis.)
- [x] Build an end-to-end autonomous lifecycle regression suite covering roots, children, swarms, integration gates, completion gates, failures, retries, and reviews.
- [x] Domknąć Agency-Aware Next Action Planner: zintegrować PersonalState, agency context, execution_mode i support_mode z rankingiem next action.
- [x] Dodać explainability dla Agency-Aware Planning: reason, confidence i źródła decyzji dla rekomendowanego next action.
- [x] Domknąć Policy & Approval Engine: klasyfikować akcje jako auto-allowed, approval-required lub user-only i egzekwować te reguły przed wykonaniem.
- [x] Zintegrować Policy & Approval z Hermes execution: przekazywać tylko akcje dozwolone przez politykę i obsługiwać wymagane approval requests.
- [x] Zbudować pełną closed-loop execution: Planner → Agency → Policy → Hermes → Evidence → Verification → State Update → Planner.
- [x] Przeprowadzić audit granicy Janus/Hermes lifecycle: usunąć duplikację completion/integration logic i jednoznacznie zdefiniować ownership każdego etapu.
- [x] Uaktualnić roadmapę i dokumentację do faktycznego stanu implementacji, oznaczając zaimplementowane elementy Agency/PersonalState jako completed. (Completed by t_34c8818c — Phase C/D/H updated; personal_state_model_spec.md status updated; roadmap item 182 marked complete.)
- [ ] WP-001 — Design Weekly Planner domain model — P0 — Design: `docs/design/janus_weekly_planner_v1.md`
- [ ] WP-002 — Build PlanningContext builder — P0 — Design: `docs/design/janus_weekly_planner_v1.md`
- [ ] WP-003 — Define WeeklyPlanner interface — P0 — Design: `docs/design/janus_weekly_planner_v1.md`
- [ ] WP-004 — Implement LLM weekly planner — P0 — Design: `docs/design/janus_weekly_planner_v1.md`
- [ ] WP-005 — Add `janus plan week` — P1 — Design: `docs/design/janus_weekly_planner_v1.md`
- [ ] WP-006 — Build weekly planner evaluation suite — P0 — Design: `docs/design/janus_weekly_planner_v1.md`
- [ ] WP-007 — Define planner quality metrics — P1 — Design: `docs/design/janus_weekly_planner_v1.md`
- [ ] WP-008 — Write Weekly Planner ADR — P1 — Design: `docs/design/janus_weekly_planner_v1.md`
- [ ] WP-009 — Document Weekly Planner — P1 — Design: `docs/design/janus_weekly_planner_v1.md`
- [ ] WP-010 — Harden Weekly Planner V1 — P1 — Design: `docs/design/janus_weekly_planner_v1.md`