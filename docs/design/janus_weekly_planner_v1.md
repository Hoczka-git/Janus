# ADR: Janus Weekly Planner V1

## Status

Accepted

**Date:** 2026-10-02
**Last verified:** 2026-10-02

---

## Context

Janus needs a weekly planning capability that helps the user prioritize tasks,
manage goals, and detect scheduling conflicts. The user's active goals, open
tasks, and calendar events are scattered across multiple data sources
(`data/goals.md`, `data/tasks.md`, Google Calendar). Without a planning layer,
the user must manually synthesize this information every week.

The core challenge is: **how to generate a credible weekly plan from real
user data without introducing unnecessary complexity or risk?**

Key constraints identified during research:

1. **V1 must be proposal-only.** No task creation, no goal mutation, no calendar
   writes, no Telegram approval workflow. The planner generates a `WeeklyPlan`
   and displays it. This keeps the blast radius zero while validating the value
   proposition.

2. **Deterministic logic stays in code.** Signal computation (overdue tasks,
   stalled goals, calendar conflicts, availability) must be deterministic and
   testable. The LLM is responsible only for prioritization, reasoning, and
   justification — not for computing facts that can be derived from data.

3. **LLM output is untrusted.** All structured output must be validated before
   reaching downstream components. Invalid output must never pass through.

4. **No persistence in V1.** Plans are ephemeral — generated on demand,
   displayed, discarded. This avoids building a persistence layer before the
   value is validated.

5. **Repository patterns must be reused.** The `@dataclass` + `__post_init__`
   validation pattern (from `janus/models/`), the CLI dispatch pattern (from
   `janus/__init__.py`), the connector ABC (from `janus/integrations/`), and
   the retry + fallback error handling pattern (from t_473202bc) are all
   established conventions that the planner must follow.

6. **Related ADRs:** ADR-001 (Hermes/Janus two-layer architecture), ADR-004
   (safe sync-and-integrate workflow), ADR-005 (activity data ingestion layer)
   define the architectural context in which the planner operates.

---

## Decision

Adopt an **LLM-based weekly planner with deterministic context building** as
the V1 planning approach. The architecture separates concerns into three
layers:

```
Domain data (goals, tasks, calendar)
    ↓
Context Builder (deterministic signals)
    ↓
PlanningContext
    ↓
LLM (prioritization, reasoning, planning)
    ↓
structured WeeklyPlan
    ↓
validation
    ↓
CLI output
```

### 1. Deterministic vs LLM boundary

The boundary is explicit and enforced:

| Deterministic (code) | LLM |
|------------------------|-----|
| Load goals, tasks, calendar | Prioritization |
| Compute overdue/stalled signals | Reasoning about trade-offs |
| Detect calendar conflicts | Justification of decisions |
| Calculate availability | Risk identification |
| Assemble `PlanningContext` | Plan generation |

The LLM never reads files or executes business logic directly. It receives a
fully-structured `PlanningContext` and returns a `WeeklyPlan`.

### 2. Domain model

All models live in `janus/models/planning.py` following the established
`@dataclass` + `__post_init__` pattern:

- **`PlanningContext`** — week boundaries, goals, tasks, calendar events,
  pre-computed signals
- **`PlanningSignals`** — overdue tasks, due-soon tasks, stalled goals,
  calendar conflicts, availability hours, competing tasks
- **`WeeklyPlan`** — week summary, priorities, planned tasks, risks
- **`PlannedTask`** — task ID, goal ID, priority, reason, suggested day
- **`Priority`** — goal ID, reason, priority level
- **`PlanningRisk`** — description, severity

The domain model is LLM-agnostic. No model imports or references any LLM
provider.

### 3. Context building

`janus/services/planning_context.py` is a pure function that:
- Filters active goals, open tasks, upcoming calendar events
- Computes deterministic signals (overdue, stalled, conflicts, availability)
- Assembles the `PlanningContext` dataclass

No LLM calls. No side effects. Fully testable.

### 4. Structured output

The LLM is prompted to return JSON conforming to the `WeeklyPlan` schema.
Validation occurs in `WeeklyPlan.__post_init__` after parsing. The prompt
pipeline (`janus/services/planning_prompt.py`) handles:
- Rendering `PlanningContext` into a prompt
- Calling the LLM with structured output schema
- Parsing and validating the response
- Retry with fallback on malformed output

### 5. Error handling

The retry + fallback pattern from t_473202bc is reused:

1. Try parse JSON → on failure, retry once with corrective nudge
2. Retry fails → raise `PlanningError` with original response attached
3. Invalid structured output → never pass to downstream; log + raise
4. Provider error → retry once, then raise
5. Timeout → retry once, then raise

### 6. No side effects in V1

The planner never mutates tasks, goals, or calendar events. It is read-only
with respect to all domain data. This is enforced by:
- The `WeeklyPlanner` Protocol signature: `plan(context) -> WeeklyPlan`
- No write methods on any planner implementation
- CLI output is display-only

### 7. Pluggable planner interface

```python
class WeeklyPlanner(Protocol):
    def plan(self, context: PlanningContext) -> WeeklyPlan: ...
```

Three implementations:
- `LLMWeeklyPlanner` — primary, calls LLM with structured output
- `RuleBasedPlanner` — future deterministic fallback
- `MockPlanner` — tests, fixed responses

### 8. CLI interface

```bash
uv run janus plan week
```

Output includes: week summary, top priorities, risks, planned tasks by day.
CLI dispatch in `janus/__init__.py`.

---

## Consequences

### Positive

- **Zero blast radius.** V1 is proposal-only. No data mutation, no external
  side effects. The user reviews the plan manually.
- **Testable deterministic core.** Signal computation is pure code, fully
  unit-testable without LLM mocking.
- **LLM-agnostic domain model.** The `PlanningContext` / `WeeklyPlan` models
  have no LLM dependency, enabling rule-based and mock implementations.
- **Reuses established patterns.** `@dataclass` validation, CLI dispatch,
  connector ABC, retry + fallback — all follow existing conventions.
- **Clear upgrade path.** V2 adds human-in-the-loop approval; V3 adds
  autonomous execution. The interface is stable across versions.

### Neutral

- **Adds LLM dependency.** The planner requires an LLM provider for V1. The
  provider is abstracted behind `LLMProvider` Protocol, but the dependency
  exists.
- **Ephemeral plans.** No persistence means plans cannot be reviewed historically
  or fed back into future planning. This is intentional for V1.
- **CLI-only output.** No Telegram integration in V1. The user must run the
  command manually.

### Negative / Risks

- **LLM output quality.** The plan is only as good as the LLM's reasoning.
  Mitigation: deterministic signals provide a factual foundation; the LLM
  only prioritizes and justifies.
- **LLM cost.** Each plan generation costs tokens. Mitigation: deterministic
  pre-computation reduces the context size; V1 is on-demand, not scheduled.
- **Provider dependency.** If the LLM provider is unavailable, planning fails.
  Mitigation: `RuleBasedPlanner` is planned as a deterministic fallback.
- **No feedback loop.** Without persistence, the system cannot learn from
  past plans. This is a known V1 limitation, addressed in V4 (feedback loop).

---

## References

- `docs/roadmap.md` — roadmap with WP-001 through WP-010 task definitions
- ADR-001 — Hermes and Janus System Model (two-layer architecture)
- ADR-004 — Safe Sync-and-Integrate Workflow (gated completion, integration)
- ADR-005 — Activity Data Ingestion Layer (controlled write gateway)
- `src/janus/models/planning.py` — domain model implementation
- `src/janus/services/planning_context.py` — context builder implementation
- `src/janus/services/planning_prompt.py` — LLM prompt pipeline
- t_473202bc — retry + fallback error handling pattern source
- t_42eaf016 — research summary for WP-008 ADR
