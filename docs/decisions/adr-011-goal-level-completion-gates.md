# ADR-011: Goal-Level Completion Gates (Proposed)

**Status:** Proposed  
**Date:** 2026-09-25  
**Relates to:** ADR-004 (Safe Sync-and-Integrate), Agency-First phase

## Context

ADR-004 defines gated completion for tasks (Phase 3 verification, Phase 5 completion). Goal completion (`services/goals.py:set_goal_state()`) has no equivalent gates — a higher-level entity has weaker protection than its child tasks. The triage (t_ea99cee2 / docs/triage_architectural_roadmap_next_phase.md) identifies this as P0 gap.

5 parent tasks of root `t_0c6028b4` are complete: goal health diagnostics (#230 merged), strategic summary integration (#255 merged), review topology (#251 merged), research findings (`weekly_review_integration_points.md`), and integrity audit (t_a5bccc99). The stalled-goals diagnostic + remediation pipeline is now fully wired into weekly review and Telegram delivery.

## Decision

Extend ADR-004 Phase 3/5 gate pattern to goal lifecycle. `complete_goal()` must run `run_goal_completion_gates()` before state change. Failed gates return structured reason codes and block the transition.

## Rationale (Agency-First)

Goals represent user intent. Agency requires that intent-fulfillment be verifiable, not just assertable. Gated goal completion protects the user from premature or unverified state changes.

## Consequences

- New `tests/test_goal_completion_gates.py` needed.
- `services/goals.py` gains gate functions.
- Evidence model (ADR-012) inserts naturally at the gate layer.

## Alternatives considered

- Skip gates and rely on user CLI judgment only — rejected; contradicts ADR-004 principle.
- Full event sourcing — rejected as over-engineered (P3 deferred).
