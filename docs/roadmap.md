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
  [`DESIGN_EXECUTION_PLANNING.md`](../DESIGN_EXECUTION_PLANNING.md)
- [x] Implement the structured observability log schema and instrumentation
  described in [`OBSERVABILITY_PLAN.md`](../OBSERVABILITY_PLAN.md)
- [ ] Verify roadmap-driven task replenishment end-to-end (triage targeting,
  idempotency, audit trail) — see `docs/replenishment_sources.md`
- [ ] Extend goal management with goal health, progress signals, and
  stalled-goal detection
- [ ] Extend execution planning with goal → milestone → project → task
  hierarchy and goal-aware task recommendations
- [ ] Implement a unified inbox and follow-up model for capturing and
  tracking actionable items that do not yet belong to an active task
- [ ] Close the research → finding → decision → action loop by connecting
  research artifacts with decisions, goals, projects, and follow-up tasks
- [ ] Implement Janus ↔ Hermes execution feedback, including task handoff,
  execution results, evidence, and resulting state updates
- [ ] Add evidence-based skill tracking linking completed work and project
  outcomes to career-development goals
- [ ] Add strategic state summaries that surface meaningful changes,
  neglected goals, stalled work, and recommended next actions
