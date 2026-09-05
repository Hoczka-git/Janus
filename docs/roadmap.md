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

The following items are small, concrete implementation steps that can be
executed independently and are suitable for automatic task replenishment.

- [ ] Add `data/*` to `.gitignore` and verify the full test suite passes
- [ ] Verify automatic task replenishment
