# Review-Loop Observability and Limits — Position Statement

**Status:** Final — resolves open question in `docs/decisions/003-canonical-review-topology.md:155`
**Date:** 2026-08-31
**Source:** Synthesis of `docs/research/review-loop-handling-findings.md`, `docs/research/review-loop-risk-analysis.md`, `docs/research/review-loop-policy-spec.md`

---

## Verdict

Hermes should impose **observability** (metrics + warnings) on repeated review cycles, but should **not** impose automated hard limits unless evidence of pathological loops emerges.

The current unlimited behavior is preserved as the default. Review cycling remains a healthy, expected part of the workflow — this is a deliberate design property, not a gap to be patched away prematurely.

---

## What exists today

| Signal | Where | Tracks |
|--------|-------|--------|
| `changes_requested` events | `kanban_db.py` | Each rejection persisted |
| `review_round_warning` | (proposed) | Warning at N rounds |
| `review_stuck_candidate` diagnostic | (proposed) | Board-level flag for >3 rounds |

What does **not** exist:
- No `review_rounds` counter (derivable from events)
- No circuit breaker for review cycles
- No diagnostic rule flagging cycling tasks

Both existing loop-detection systems (`block_recurrences`, `consecutive_failures`) explicitly exclude review transitions **by design**. This is intentional: review cycles are a quality signal, not a worker-health signal, and conflating the two would break semantic clarity.

---

## Proposed posture

### 1. Metrics (always on)
- `review_rounds` — derived dynamically from `changes_requested` event count, surfaced in `kanban_show` output.
- `review_elapsed_seconds` — time since first `review_requested` event, computed on read.
- Both are informational only. No schema migration required; computed from existing `task_events`.

### 2. Warning at N=3 (configurable, opt-out)
- Config key: `kanban.review_round_warning_threshold` (default: 3, set to 0 to disable).
- Fires once per threshold crossing via `review_round_warning` event in task history.
- Informational only — does not block, triage, or change task status.
- Aligned with `sdlc-review` skill's lens variation (Round 3+ = "Contract" lens).

### 3. Hard limit via `kanban.review_round_limit` (opt-in, default NULL = off)
- When set to a positive integer and the task's `review_rounds` reaches that value, the task is auto-blocked with `block_kind = "review_loop_detected"`.
- Does NOT increment `block_recurrences` (review is not a block-loop pattern).
- Not enabled by default. Operators enable it only after metrics show tasks cycling beyond N rounds without progress.
- Rationale: false-positive risk for legitimately complex tasks (4+ rounds), and adding a hard limit without evidence violates the principle of minimal intervention.

### 4. Diagnostic rule
- `kanban_diagnostics.py`: flag tasks with >3 `changes_requested` events as `review_stuck_candidate` (severity: warning).
- Separate from runtime warning event — this is a board-level diagnostic for operators, not a per-task signal.

---

## What is explicitly rejected

- **Soft throttle / cooldown** — complexity not justified at current risk level; revisit if metrics show frequent high-round-count tasks.
- **Per-board configuration** — v1 is global only; per-board scoping can be added later without breaking the global default.
- **Automatic threshold tuning** — N is operator-chosen, not ML-driven.

---

## Implementation priority

1. `review_rounds` + `review_elapsed_seconds` in `kanban_show` (lowest cost, highest value — foundation for everything else).
2. `review_round_warning` event in `reopen_review_task()` when threshold crossed.
3. `_rule_review_stuck_candidate` diagnostic in `kanban_diagnostics.py`.
4. `kanban.review_round_limit` hard limit (defer until evidence of pathological loops emerges — but the config key and the auto-block path should be wired so it can be enabled without code changes when needed).

---

## Acceptance criteria scope

Full 18-criteria acceptance test suite is defined in the policy spec (`docs/research/review-loop-policy-spec.md`, AC-1 through AC-18). Key invariants:
- AC-1 through AC-4: default behavior preserved (2 cycles = no warning, no block; `kanban_show` shows counts).
- AC-5 through AC-8: warning fires at exactly round 3, configurable, fires once per crossing.
- AC-9 through AC-11: hard limit works when enabled, never fires when NULL.
- AC-12 through AC-15: no interference with `consecutive_failures`, `block_recurrences`, existing tests, or `sdlc-review` skill.
- AC-16 through AC-18: config keys exist with correct defaults, env var override works, invalid values rejected.

---

## Revisit triggers

- Operators report tasks stuck in review for >5 cycles with default config.
- Metrics show high-round-count tasks consuming disproportionate resources.
- `sdlc-review` lens variation proves insufficient for decorrelation.
- Need for per-board scoping emerges.

---

## Open question closed

`docs/decisions/003-canonical-review-topology.md:155` noted: *"Whether a dedicated review-loop guard is needed is an open question."*

**Resolution:** A dedicated review-loop guard is NOT needed by default. Observability (metrics + warnings) is needed immediately. A hard limit mechanism should exist as an opt-in escape hatch but should remain disabled until evidence of actual pathological loops justifies enabling it. This preserves the design philosophy that "review is not a block" while giving operators visibility and an escalation path.
