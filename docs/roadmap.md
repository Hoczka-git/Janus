# Hermes / Janus Roadmap

This document describes strategic direction and intended sequencing.

Implementation status must always be verified against the current repository, Hermes installation and integrations. The roadmap describes direction, not guaranteed implementation state.

---

# Product Direction

Hermes is evolving toward a persistent personal Chief of Staff capable of working across multiple domains.

The system should combine:

- persistent user context,
- autonomous but controlled execution,
- deterministic domain logic,
- structured operational data,
- curated long-term knowledge,
- multiple input and interaction interfaces.

The development strategy is to build useful capabilities incrementally while maintaining:

- clear ownership boundaries,
- deterministic foundations,
- observable system state,
- evidence-based verification,
- reusable infrastructure,
- minimal duplication of existing Hermes capabilities.

A key architectural principle is:

> Build domain capabilities in Janus. Reuse Hermes for agent orchestration whenever possible.

---

# Current Architecture Direction

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
└── Autonomous Runs
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
     Obsidian
```

---

# Planned Work

The items below are the active planning backlog consumed by the Hermes
replenishment plugin (see `~/.hermes/hermes-agent/plugins/replenishment`).
When a `[plan]`-prefixed task completes on the JANUS board, the plugin pulls
the first unchecked item here as a new `[plan]` task into the `triage` column,
checks the item off, and parents the new task on the completed one.

- [x] Instrument JANUS daily briefing with structured observability logs
- [x] Add canonical review topology test coverage for reviewer-child rejection
- [ ] Document the Phase 3 adversarial verification workflow
