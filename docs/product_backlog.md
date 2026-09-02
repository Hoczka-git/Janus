# Janus Product Backlog

This document contains concrete product capabilities that are candidates for future implementation.

It complements:

- `docs/vision.md` — long-term product direction
- `docs/roadmap.md` — strategic sequencing

This file is the primary source for roadmap-driven task replenishment.

Status definitions:

- `planned` — identified but not ready for implementation
- `ready` — sufficiently defined and eligible for TRIAGE
- `in_progress` — currently being implemented
- `done` — implemented and verified
- `blocked` — requires external input or dependency

---

# Next

# Product Capabilities

## [ready] Configure roadmap-driven replenishment for Janus

Configure and validate the Hermes replenishment plugin for the Janus project.

Planning sources:

- `docs/roadmap.md`
- `docs/product_backlog.md`
- `docs/vision.md`

Requirements:

- enable replenishment,
- register planning sources,
- configure `max_generated_tasks = 1`,
- target generated tasks to TRIAGE,
- perform an end-to-end validation,
- verify idempotency and audit trail.

---

## [ready] Goal execution planning

Extend the Goal System from tracking toward execution planning.

Capabilities:

- break goals into actionable milestones,
- derive next actions,
- detect stalled goals,
- connect goal actions with tasks,
- surface relevant calendar context,
- preserve backward compatibility with existing goals.

Deferred:

- task dependency graph,
- historical progress tracking,
- calendar write-back.

---

## [planned] Calendar-aware planning

Improve Janus daily and weekly planning using calendar availability.

Potential capabilities:

- identify available focus blocks,
- detect overloaded days,
- account for upcoming events when suggesting tasks,
- recommend realistic task placement.

Dependencies:

- Google Calendar read-side integration,
- Goal execution planning.

---

## [planned] Research knowledge pipeline

Formalize how Janus turns research into durable knowledge.

Potential capabilities:

- structured research artifacts,
- source provenance,
- research summaries,
- promotion of durable insights into Obsidian,
- explicit distinction between transient research and curated knowledge.

---

## [planned] Weekly review automation

Extend the existing weekly reporting capabilities.

Potential capabilities:

- summarize completed work,
- review goal progress,
- identify stalled commitments,
- surface unresolved attention items,
- suggest next week's priorities.

---

# Later

## [later] Personal finance domain

Potential capabilities:

- portfolio overview,
- investment research integration,
- thesis tracking,
- watchlists.

---

## [later] Home automation integration

Deferred due to limited current smart-home infrastructure.

Potential capabilities:

- Home Assistant integration,
- contextual device control,
- routines,
- environment-aware automation.

---

# Parking Lot

Ideas worth preserving but not currently prioritized:

- additional messaging interfaces,
- proactive notification intelligence,
- richer personal knowledge graph,
- external data integrations,
- advanced autonomous planning.
