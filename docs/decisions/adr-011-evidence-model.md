# ADR-011: Evidence Model for Goal Tracking

Status: Proposed

Context: No formal `Evidence` concept exists in Janus. Goal completion is state-based (`set_goal_state()`), not evidence-based. The Agency-First development phase (docs/janus-agency-first-development-phase.md) identifies evidence and audit as the next strategic gap after the Goal → Task → Execution → Completion → Review loop is closed.

Decision: Introduce `Evidence` as a first-class domain concept linking demonstrated work to goal/metric progress. Evidence records are deterministic given inputs (manual input, measured data, derived from task results, or system event). Non-deterministic agent assessments are explicitly labeled and not used as sole basis for completion.

Rationale: Agency-First — goal completion should be provable, not assertable. Evidence provides the proof trail without over-engineering full event sourcing.

Consequences:
- New `services/evidence.py` (or domain model) with `Evidence` record.
- Evidence storage: `data/evidence/` with content-integrity hash.
- Metric derivation can reference evidence records.
- Goal completion gates (ADR-004 extended to goals, P0-2) can require at least one evidence record.
- Keeps current loop intact; does not replace review or verification.

Tests / invariants:
- Evidence creation is deterministic (same inputs → same hash).
- Evidence links to exactly one goal/task/metric target.
- Evidence records are immutable after creation.
- Goal completion can be gated on evidence presence.

Alternatives considered: Full event sourcing (rejected — over-engineered); implicit execution results only (rejected — not provable); skip evidence until PersonalState (rejected — evidence is prerequisite).

Related: ADR-012 (proposed), ADR-003 (review), ADR-004 (gates), docs/triage_architectural_roadmap_next_phase.md §3.2 (Evidence/Verification gap).
