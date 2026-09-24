# Hermes / Janus Roadmap

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
- [~] Verify the complete Goal → Task → Execution → Completion → Review loop
  - Status transitions and execution evidence verified.
  - Remaining: production verification of Completion → Goal Update and Review.
- [x] Add evidence-based skill tracking linking completed work and project outcomes to career-development goals
- [x] Add strategic state summaries that surface meaningful changes, neglected goals, stalled work, and recommended next actions
- [x] Define the `GoalIntegrityReport` and `GoalIntegrityIssue` domain models. specification in [`docs/design/goal_integrity_audit.md`
- [x] Implement deterministic goal/task integrity checks. specification in [`docs/design/goal_integrity_audit.md`
- [x] Add `janus goal audit` CLI command. specification in [`docs/design/goal_integrity_audit.md`
- [x] Add `janus goal audit --json` output and exit-code semantics
- [x] Add unit and CLI test coverage. specification in [`docs/design/goal_integrity_audit.md`](../docs/design/goal_integrity_audit.md)
- [x] Document the audit specification in [`docs/design/goal_integrity_audit.md`](../docs/design/goal_integrity_audit.md)
- [x] Consolidate the goal execution planning extension into the Janus domain layer and add automated tests for boundary cases.
- [x] Verify the complete Goal → Task → Execution → Completion → Review loop, including production verification of Completion → Goal Update and Review.
- [x] Complete the knowledge curation gate for artifact promotion into the Obsidian vault.
- [x] Expose deterministic goal next-action derivation through `janus goal next <title>` and integrate it into user-facing reviews.

## Agency-First Janus

See [Agency-First Development Phase](janus-agency-first-development-phase.md).

Janus should optimize for increasing user capability and agency,
not maximizing autonomous agent execution.

Key phases:
- [ ] Complete Goal → Task → Execution → Completion → Review
- [ ] Evidence & Audit
- [ ] Personal State Model
- [ ] Agency-Aware Planning
- [ ] Policy & Approval
- [ ] Connector Protocol
- [ ] Self-Extending Skills
- [ ] Multi-Agent Orchestration
