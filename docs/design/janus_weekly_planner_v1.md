# Janus Weekly Planner — V1 Design Document

**Status:** Draft for review
**Parent task:** t_36165f52 (architecture), t_473202bc (LLM error-handling precedent)
**Last updated:** 2026-10-02

---

## 1. Overview

The LLM Weekly Planner is the first production AI-thinking component in Janus.
It generates a structured week plan from the user's real data — active goals,
open tasks, and calendar events — using an LLM for prioritization, reasoning,
and conflict detection.

V1 answers one question:

> Can Janus credibly plan a week based on active goals, tasks, and calendar?

**V1 is proposal-only.** It generates a `WeeklyPlan` and displays it. It does
not create tasks, modify goals, write to the calendar, or trigger any side
effects. No Telegram approval, no autonomous execution.

### Core architectural principle

The LLM never reads files or executes business logic directly. Janus prepares
a structured context:

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

Deterministic logic stays in code. The LLM is responsible for:
- prioritization,
- reasoning,
- planning,
- conflict detection,
- justification of decisions.

---

## 2. Goals & Non-Goals

### Goals (V1)

| # | Goal | Done when |
|---|------|-----------|
| G1 | Generate a structured weekly plan from real user data | `janus plan week` produces a valid `WeeklyPlan` |
| G2 | Deterministic signal computation before LLM call | Overdue, stalled, conflict signals computed in code |
| G3 | LLM-agnostic domain model | `PlanningContext`, `WeeklyPlan`, etc. have no LLM dependency |
| G4 | Pluggable planner interface | `WeeklyPlanner` Protocol allows LLM/RuleBased/Mock implementations |
| G5 | Robust error handling | Invalid LLM output never reaches downstream; retry + fallback |
| G6 | Evaluation suite | 10+ scenario tests covering edge cases |
| G7 | No side effects | Planner never mutates tasks, goals, or calendar |

### Non-Goals (V1)

- Multi-agent system
- LangGraph or any agent framework
- MCP
- Vector database / RAG
- Autonomous execution
- Telegram approval workflow
- Long-term memory
- Web search
- UI (CLI only)
- Kubernetes / cloud infrastructure
- Plan persistence (ephemeral only)

These may be considered after V1 value is validated.

---

## 3. Architecture Description

### 3.1 Component diagram

```
┌──────────────┐     ┌──────────────────┐     ┌───────────────┐
│  Data Loaders │────▶│ Context Builder  │────▶│ PlanningContext│
│ (goals,tasks, │     │  (deterministic  │     │  (domain model)│
│  calendar)    │     │   signals)       │     └───────┬───────┘
└──────────────┘     └──────────────────┘             │
                                                       ▼
                                              ┌──────────────────┐
                                              │  LLMWeeklyPlanner│
                                              │  (LLM call +     │
                                              │   structured out)│
                                              └────────┬─────────┘
                                                       │
                                                       ▼
                                              ┌──────────────────┐
                                              │ WeeklyPlan       │
                                              │ validation       │
                                              └────────┬─────────┘
                                                       │
                                                       ▼
                                              ┌──────────────────┐
                                              │ CLI / output     │
                                              │ (janus plan week)│
                                              └──────────────────┘
```

### 3.2 Data Loaders

Pure integration adapters. Each returns typed domain objects.

| Loader | Source | Returns |
|--------|--------|---------|
| `load_goals()` | `markdown_goals` | `list[Goal]` |
| `load_tasks()` | `markdown_tasks` | `list[Task]` |
| `load_calendar()` | `google_calendar` | `list[Event]` |

### 3.3 Context Builder (`janus/services/planning_context.py`)

Deterministic signal computation before any LLM call. Produces
`PlanningContext`.

**Responsibilities:**
- Filter active goals, open tasks, upcoming calendar events
- Compute deterministic signals:
  - task overdue / due soon
  - goal stalled / behind target
  - calendar availability / conflicts
  - task-to-goal mapping density
- Assemble `PlanningContext` dataclass

**No LLM calls. No side effects. Pure function.**

### 3.4 LLM Prompt Pipeline (`janus/services/planning_prompt.py`)

**Responsibilities:**
- Render `PlanningContext` into an LLM prompt
- Call LLM with structured output schema
- Parse and validate LLM response
- Retry with fallback on malformed output (pattern from t_473202bc)

**Interface:**
```python
def build_prompt(context: PlanningContext) -> str: ...
def parse_llm_response(raw: str) -> WeeklyPlan: ...
```

### 3.5 State Storage

V1 does **not** persist plans. Plans are ephemeral — generated on demand,
displayed, discarded. This keeps V1 simple and avoids a persistence layer
before the value proposition is validated.

Future versions may store plans in `data/plans.md` or a lightweight DB.

---

## 4. Domain Model (WP-001)

**WP-001** — Design Weekly Planner domain model
**Priority:** P0
**Parent task:** t_5d30bf1f
**Research spec:** `docs/research-findings/planner_domain_research.md` (t_d2a5732e)

### 4.1 Overview

The weekly planner domain model defines the input (`PlanningContext`) and
output (`WeeklyPlan`) of the planning process, along with deterministic
signals computed before the LLM is invoked. All models are LLM-independent
and live in `src/janus/planner/models.py`.

The model follows the existing Janus `@dataclass` pattern. Identity is
title-based (`Goal.title`, `Task.title`) — no UUIDs in V1. The planning
week is implicit (current week, Monday–Sunday); no `week_start`/`week_end`
fields on `PlanningContext`.

### 4.2 Domain Entities

#### PlanningContext (input)

```python
@dataclass
class PlanningContext:
    goals: list[Goal]           # active goals
    tasks: list[Task]           # open (not completed) tasks
    calendar: list[Event]       # calendar events for the planning period
    signals: PlanningSignals    # pre-computed deterministic signals
```

#### PlanningSignals (deterministic pre-computation)

```python
@dataclass
class PlanningSignals:
    overdue_tasks: list[str]           # task titles past due date
    due_soon_tasks: list[str]          # task titles due within 7 days
    stalled_goals: list[str]           # goal titles with no recent activity
    behind_target_goals: list[str]    # goal titles behind target progress
    calendar_conflicts: list[str]      # human-readable conflict descriptions
    competing_tasks: dict[str, int]    # task title → count of competing tasks
```

Computed by `plan_cli.py::_build_context()`. No LLM calls, no side effects.

#### WeeklyPlan (output)

```python
@dataclass
class WeeklyPlan:
    week_summary: str
    priorities: list[PriorityEntry]    # goal priorities, ordered by importance
    planned_tasks: list[PlannedTask]   # tasks scheduled for specific days
    risks: list[PlanningRisk]          # risks and conflicts
```

#### PriorityEntry

```python
@dataclass
class PriorityEntry:
    goal_id: str        # Goal.title (persistence identity)
    reason: str         # human-readable justification
    priority: Priority  # HIGH | MEDIUM | LOW
```

#### PlannedTask

```python
@dataclass
class PlannedTask:
    task_id: str        # Task.title (persistence identity)
    goal_id: str        # Goal.title
    priority: Priority  # HIGH | MEDIUM | LOW
    reason: str         # human-readable justification
    suggested_day: date # ISO date YYYY-MM-DD
```

#### Priority (StrEnum)

```python
class Priority(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
```

#### PlanningRisk

```python
@dataclass
class PlanningRisk:
    description: str
    severity: RiskSeverity  # LOW | MEDIUM | HIGH
```

#### RiskSeverity (StrEnum)

```python
class RiskSeverity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
```

### 4.3 Relationship Diagram

```
┌──────────────────────────────────────────────────────────────┐
│                       PlanningContext                        │
│  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌────────────────┐  │
│  │  Goal   │  │  Task   │  │  Event  │  │PlanningSignals │  │
│  │ (title) │  │ (title) │  │(ephem.) │  │                │  │
│  └────┬────┘  └────┬────┘  └─────────┘  └────────────────┘  │
│       │            │                                         │
└───────┼────────────┼─────────────────────────────────────────┘
        │            │
        │     ┌──────┴──────┐
        │     │  WeeklyPlan │
        │     │ ┌─────────┐ │
        │     │ │Priority │ │
        │     │ │Entry    │ │
        │     │ │goal_id ─┼─┘ (many-to-one → Goal.title)
        │     │ │priority │ │
        │     │ └─────────┘ │
        │     │ ┌─────────┐ │
        │     │ │Planned  │ │
        │     │ │Task     │ │
        │     │ │task_id ──┼── (many-to-one → Task.title)
        └─────┼─┤goal_id ──┼── (many-to-one → Goal.title)
              │ │priority │ │
              │ │suggested│ │
              │ │_day     │ │
              │ └─────────┘ │
              │ ┌─────────┐ │
              │ │Planning │ │
              │ │Risk     │ │
              │ │severity │ │
              │ └─────────┘ │
              └─────────────┘
```

### 4.4 Invariants

Enforced by `LLMWeeklyPlanner._validate_plan()`:

1. Every `PriorityEntry.goal_id` must exist in `context.goals` (by title).
2. Every `PlannedTask.task_id` must exist in `context.tasks` (by title).
3. Every `PlannedTask.goal_id` must exist in `context.goals`.
4. No `task_id` may appear in `planned_tasks` more than once (duplicate
   scheduling rejected).

Not enforced (open):
- `suggested_day` must be within the planning week — validation absent.
- `PriorityEntry` ordering is not validated (list order = priority ranking).

### 4.5 Interface Sketch

```python
class WeeklyPlanner(Protocol):
    def plan(self, context: PlanningContext) -> WeeklyPlan: ...
```

Implementations:

| Implementation | Status | Notes |
|----------------|--------|-------|
| `LLMWeeklyPlanner` | Primary (P0) | Calls LLM with structured output |
| `RuleBasedPlanner` | Fallback | Deterministic, in `plan_cli.py` |
| `MockPlanner` | Tests (P0) | Fixed responses for evaluation |

### 4.6 Open Questions

| # | Question | Status |
|---|----------|--------|
| 1 | `models/` vs `planner/` location for domain models | Open — implementation uses `planner/` |
| 2 | `PriorityEntry` vs inline `Priority` in design | Open — implementation separates them |
| 3 | Task/goal identity: title vs UUID | Open — title-based in V1 |
| 4 | `Block`/time-block model: include or defer? | Open — missing from codebase |
| 5 | `availability_hours` signal: add or drop? | Open — in original design, not in impl |
| 6 | Week as explicit model vs implicit | Open — implicit current-week convention |
| 7 | `behind_target_goals` signal computed? | Open — in model, not computed in `plan_cli.py` |

### 4.7 References

- Parent task: t_5d30bf1f (WP-005 design)
- Research spec: `docs/research-findings/planner_domain_research.md` (t_d2a5732e)
- Roadmap: `docs/roadmap.md` §WP-001
- Implementation: `src/janus/planner/models.py`

---

## 5. LLM Interaction Flow

### 5.1 Provider Abstraction

V1 has no LLM provider yet. The abstraction layer:

```python
class LLMProvider(Protocol):
    def complete(self, prompt: str, schema: dict) -> str: ...
```

First implementation: OpenAI-compatible API via environment variables
`JANUS_LLM_API_KEY` and `JANUS_LLM_BASE_URL`.

### 5.2 Structured Output

LLM is prompted to return JSON conforming to the `WeeklyPlan` schema.
Validation via `WeeklyPlan.__post_init__` after parsing.

### 5.3 Error Handling (pattern from t_473202bc)

The retry + fallback pattern from `kanban_decompose.py` (t_473202bc) is reused:

1. Try parse JSON → on failure, retry once with corrective nudge
2. Retry fails → raise `PlanningError` with original response attached
3. Invalid structured output → never pass to downstream; log + raise
4. Provider error → retry once, then raise
5. Timeout → retry once, then raise

### 5.4 Prompt structure

The prompt includes:
- System prompt: role, constraints, output schema
- User prompt: rendered `PlanningContext` with all deterministic signals
- Output format: JSON matching `WeeklyPlan` schema

---

## 6. Interface Specifications

### 6.1 WeeklyPlanner Protocol

```python
class WeeklyPlanner(Protocol):
    def plan(self, context: PlanningContext) -> WeeklyPlan: ...
```

### 6.2 Implementations

| Implementation | Status | Notes |
|---------------|--------|-------|
| `LLMWeeklyPlanner` | Primary (P0) | Calls LLM with structured output |
| `RuleBasedPlanner` | Future | Deterministic fallback |
| `MockPlanner` | Tests (P0) | Fixed responses for evaluation |

### 6.3 CLI Interface

```bash
uv run janus plan week
```

Example output:

```
JANUS WEEKLY PLAN
5–11 Oct 2026

TOP PRIORITIES

1. Career
   Prepare AI/Agent Engineering development plan

2. Janus
   Complete autonomous planning V1

3. Health
   2 strength sessions

RISKS

⚠ Career goal has no completed actions...
⚠ Multiple tasks compete for the same time...

PLANNED TASKS

Monday
  ...

Tuesday
  ...
```

CLI dispatch in `janus/__init__.py`:
```python
elif command == "plan":
    handle_plan_week(filtered[2:])
```

---

## 7. Integration Points with the Repository

### 7.1 Existing integrations used

| Integration | Purpose | Read/Write |
|-------------|---------|------------|
| `markdown_goals` | Read active goals | Read |
| `markdown_tasks` | Read open tasks | Read |
| `google_calendar` | Read upcoming events | Read |
| `metric_history` | Goal progress signals | Read (via existing services) |

### 7.2 Existing services leveraged

- `janus/services/goals.py` — goal loading and status
- `janus/services/tasks.py` — task loading and status
- `janus/services/weekly_review.py` — weekly aggregation pattern
- `janus/services/goal_health.py` — health signal computation
- `janus/services/goal_progress.py` — progress tracking

### 7.3 Existing patterns reused

- `@dataclass` + `__post_init__` validation (from `janus/models/`)
- CLI dispatch pattern (from `janus/__init__.py`)
- Connector ABC (from `janus/integrations/connector.py`)
- Retry + fallback error handling (from t_473202bc `kanban_decompose.py`)
- `janus._log.emit` for structured logging

### 7.4 No integration with

- Telegram (V1 is CLI-only)
- Execution/action system (V1 proposes only)
- Memory/vector DB (out of scope)

---

## 8. Security & Permissions

- **No API keys in code** — all credentials via environment variables
  (`JANUS_LLM_API_KEY`, `JANUS_LLM_BASE_URL`)
- **No PII in prompts** — only goal/task titles and dates, no user identifiers
- **Plan proposals are read-only** — V1 never creates/modifies tasks,
  goals, or calendar events
- **Input validation** — all user data loaded through existing validated
  integrations (markdown_goals, markdown_tasks, google_calendar)
- **Error messages** — no stack traces or internal details in CLI output
- **LLM output is untrusted** — all structured output validated before use;
  invalid output never reaches downstream components

---

## 9. Evaluation

### 9.1 Approach

Evaluation checks plan **properties**, not exact text. The LLM is not required
to produce identical output across runs.

### 9.2 Minimum scenario set

| # | Scenario | Property tested |
|---|----------|-----------------|
| 1 | One urgent task | Urgent task prioritized |
| 2 | Many overdue tasks | All overdue tasks addressed or explicitly rejected with reason |
| 3 | Stalled goal | Stalled goal flagged in risks |
| 4 | No calendar availability | Availability constraint reflected in plan |
| 5 | Deadline conflict | Conflict detected and flagged |
| 6 | Too many tasks for one week | Realistic capacity planning |
| 7 | Empty task list | Graceful handling, no crash |
| 8 | Goal with no linked tasks | Flagged as risk |
| 9 | Already completed goal | Excluded from plan |
| 10 | Multiple goals with similar priority | Sensible tie-breaking |

### 9.3 Quality metrics (P1, WP-007)

- task coverage
- overdue-task handling
- deadline awareness
- calendar conflict rate
- plan validity
- number of unsupported recommendations

---

## 10. Rollout Plan

### Phase 1 (P0) — Domain & Context

- Domain models (`PlanningContext`, `WeeklyPlan`, `PlannedTask`, `Priority`,
  `PlanningRisk`, `PlanningSignals`) + tests
- Context Builder + tests

### Phase 2 (P0) — Planner Core

- `WeeklyPlanner` Protocol
- `LLMWeeklyPlanner` + prompt pipeline
- Error handling (retry + fallback)

### Phase 3 (P1) — CLI

- `janus plan week` command
- Output formatting

### Phase 4 (P0) — Evaluation

- 10+ scenario test suite
- Quality metrics definition

### Post-V1 (not in scope)

- Human-in-the-loop approval
- Autonomous execution
- Telegram integration
- Multi-agent system
- RAG / vector DB

---

## 11. Definition of Done

V1 is complete when:

- [ ] `janus plan week` works end-to-end
- [ ] Planner reads Goals
- [ ] Planner reads Tasks
- [ ] Planner reads Calendar
- [ ] `PlanningContext` exists
- [ ] `WeeklyPlanner` interface exists
- [ ] `LLMWeeklyPlanner` exists
- [ ] LLM generates structured output
- [ ] `WeeklyPlan` is validated
- [ ] Invalid output is handled
- [ ] Unit tests exist
- [ ] Evaluation scenarios exist
- [ ] Planner has no side effects
- [ ] ADR documenting architecture exists
- [ ] Documentation exists
- [ ] Example output exists
- [ ] Entire flow runs with one command

---

## 12. Future Versions

### V2 — Human-in-the-loop

```
WeeklyPlan
    ↓
Proposed actions
    ↓
User approval
    ↓
Execution
```

Planner may propose: create task, change priority, change deadline, create
calendar event. Destructive or external actions require approval.

### V3 — Autonomous execution

```
Observe → Plan → Approve/policy → Execute → Observe result → Review
```

### V4 — Feedback loop

After each week, Janus analyzes: planned actions, completed actions,
postponed actions, ignored actions, goal progress, prediction accuracy,
LLM cost, number of approvals required. Results feed into next week's
planning.

---

## 13. Roadmap Tasks

### Phase 1 — Domain & context

#### WP-001 — Design Weekly Planner domain model
**Priority:** P0

Design `PlanningContext`, `WeeklyPlan`, `PlannedTask`, `Priority`,
`PlanningRisk`.

**Done when:**
- models are LLM-independent,
- have validation,
- have tests,
- contain no provider logic.

#### WP-002 — Build PlanningContext builder
**Priority:** P0
**Depends on:** WP-001

Build component aggregating Goals, Tasks, and Calendar into `PlanningContext`.

**Done when:**
- one component generates complete context,
- empty data handled,
- edge cases handled,
- tests exist.

---

### Phase 2 — Planner

#### WP-003 — Define WeeklyPlanner interface
**Priority:** P0
**Depends on:** WP-001

Introduce `WeeklyPlanner` abstraction enabling implementation swap.

**Done when:**
- protocol/interface exists,
- `LLMWeeklyPlanner` can be a drop-in implementation,
- mock/rule-based implementations work in tests.

#### WP-004 — Implement LLM weekly planner
**Priority:** P0
**Depends on:** WP-002, WP-003

Implement flow: `PlanningContext → prompt → LLM → structured WeeklyPlan`.

**Done when:**
- structured output is validated,
- invalid output does not pass through,
- retry/error handling exists,
- provider is separated from domain.

---

### Phase 3 — CLI

#### WP-005 — Add `janus plan week`
**Priority:** P1
**Depends on:** WP-004

Add CLI generating weekly plan.

**Done when:**
- command works end-to-end,
- shows priorities,
- shows planned tasks,
- shows risks,
- no side effects.

---

### Phase 4 — Evaluation

#### WP-006 — Build weekly planner evaluation suite
**Priority:** P0
**Depends on:** WP-004

Build 10+ test scenarios covering overdue tasks, stalled goals, conflicts,
and unavailable calendar.

**Done when:**
- scenarios are reproducible,
- test response properties,
- can compare planner/prompt versions.

#### WP-007 — Define planner quality metrics
**Priority:** P1
**Depends on:** WP-006

Define planning quality metrics.

Minimum: task coverage, overdue-task handling, deadline awareness,
calendar conflict rate, plan validity, unsupported recommendations.

---

### Phase 5 — Architecture & documentation

#### WP-008 — Write Weekly Planner ADR
**Priority:** P1
**Depends on:** WP-004

Document: deterministic vs LLM boundary, domain model, context building,
structured output, error handling, no side effects in V1.

#### WP-009 — Document Weekly Planner
**Priority:** P1
**Depends on:** WP-005, WP-006, WP-008

Add runbook, architecture docs, example output, and limitations.

---

### Phase 6 — V1 completion

#### WP-010 — Harden Weekly Planner V1
**Priority:** P1
**Depends on:** WP-007, WP-009

Full review and fix pass before V1 is considered done.

**Done when:**
- all DoD met,
- tests pass,
- evaluation suite runs,
- documentation current,
- flow runs with one command.

---

### V2 backlog

After V1 completion:

- WP-011 — Design action proposal model
- WP-012 — Add human approval workflow
- WP-013 — Add task mutation tools
- WP-014 — Add calendar mutation tools
- WP-015 — Add execution policy
- WP-016 — Add execution result tracking
- WP-017 — Add weekly review loop
- WP-018 — Add planner feedback/evaluation loop

---

## 14. Open Questions

| # | Question | Status |
|---|----------|--------|
| 1 | LLM provider selection — which provider for V1? | Open — OpenAI-compatible default, confirm endpoint and model with user |
| 2 | Structured output validation location — `__post_init__` or separate validator? | Open |
| 3 | Context Builder granularity — use existing services or compute directly? | Open |
| 4 | Plan persistence — confirmed V1: no persistence, ephemeral only | Resolved |
| 5 | Calendar integration — does `google_calendar` provide free/busy or just event listing? | Open |

---

## 15. Decisions Log

| Decision | Rationale |
|----------|-----------|
| No persistence in V1 | Keeps scope minimal; validates value before adding complexity |
| Deterministic signals before LLM | Reduces token usage, improves plan quality |
| Protocol-based abstraction | Enables mock/rule-based implementations for testing |
| CLI-only output in V1 | No Telegram approval needed; proposals only |
| `@dataclass` + `__post_init__` | Matches existing model pattern in Janus |
| Retry + fallback for LLM errors | Reuses proven pattern from t_473202bc |
| Evaluation tests properties, not text | LLM output is non-deterministic; properties are stable |
