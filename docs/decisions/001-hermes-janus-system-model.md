# ADR-001: Hermes and Janus System Model

## Status

Accepted

---

# Context

The project contains both an autonomous agent layer and application/domain functionality.

Without a clear distinction, domain logic risks becoming embedded directly in agent prompts and workflows.

This would make the system harder to:

- test,
- maintain,
- reuse,
- reason about.

---

# Decision

The system uses two primary conceptual layers.

## Hermes

Hermes is responsible for:

- agent interaction,
- orchestration,
- planning,
- tool usage,
- autonomous execution,
- reporting.

## Janus

Janus is responsible for:

- domain models,
- business logic,
- persistence,
- integrations,
- deterministic processing.

Conceptually:

```text
User
 │
 ▼
Hermes
 │
 ▼
Janus
 │
 ▼
Data / Integrations
