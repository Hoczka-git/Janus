# Janus Weekly Planner — V1 Design Document

> **Status:** Implemented on `master` (rule-based + LLM backend)
> **Last updated:** 2026-10-02
> **Source:** Research of `src/janus/`, `tests/`, `docs/design/`, `docs/research-findings/`.
> **Companion research:** `docs/research-findings/goal_system_discovery_research.md`, `docs/research-findings/planning_calendar_findings.md`, `docs/research-findings/goal_health_progress_research_findings.md`.
> **Parent tasks:** `t_36165f52` (architecture), `t_473202bc` (LLM error-handling precedent)

## 1. Overview

The LLM Weekly Planner is the first production AI-thinking component in Janus. It generates a structured week plan from the user's real data — active goals, open tasks, and calendar events — using an LLM for prioritization, reasoning, and conflict detection.

V1 answers one question:

> Can Janus credibly plan a week based on active goals, tasks, and calendar?

**V1 is proposal-only.** It generates a `WeeklyPlan` and displays it. It does not create tasks, modify goals, write to the calendar, or trigger side effects. Telegram approval and autonomous execution are out of scope.

### Core architectural principle

The LLM never reads files or executes business logic directly. Janus prepares a structured context:

```
Domain data (goals, tasks, calendar)
    ↓
Context Builder (deterministic signals)
    ↓
PlanningContext
    ↓
LLM / RuleBasedPlanner
    ↓
structured WeeklyPlan
    ↓
validation
    ↓
CLI output
```

Deterministic logic stays in code. The LLM is responsible for prioritization, reasoning, planning, conflict detection, and justification of decisions.

## 2. Goals and Non-Goals

### Goals (V1)

| # | Goal | Done when |
|---|------|-----------|
| G1 | Generate a structured weekly plan from real user data | `janus plan week` produces a valid `WeeklyPlan` |
| G2 | Deterministic signal computation before LLM call | Overdue, stalled, and conflict signals are computed in code |
| G3 | LLM-agnostic domain model | Planning models have no provider dependency |
| G4 | Pluggable planner interface | `WeeklyPlanner` Protocol allows LLM, rule-based, and mock implementations |
| G5 | Robust error handling | Invalid LLM output never reaches downstream; transient failures are retried and fallback is available |
| G6 | Evaluation suite | Scenario tests cover edge cases and planner properties |
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
- UI beyond CLI
- Kubernetes / cloud infrastructure
- Plan persistence
- Multi-week planning
- Historical plan analysis / feedback loop
- Automatic plan revision mid-week

These may be considered after V1 value is validated.

## 3. Architecture

### 3.1 Component diagram

```
┌──────────────┐     ┌──────────────────┐     ┌────────────────┐
│ Data Loaders │────▶│ Context Builder  │────▶│ PlanningContext│
│ goals/tasks/ │     │ deterministic    │     │ domain model   │
│ calendar     │     │ signals          │     └───────┬────────┘
└──────────────┘     └──────────────────┘             │
                                                      ▼
                                               ┌──────────────────┐
                                               │ LLMWeeklyPlanner │
                                               │ LLM + structured │
                                               │ output           │
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
                                               │ janus plan week  │
                                               └──────────────────┘
```

`RuleBasedPlanner` implements the same planner interface and serves as the deterministic fallback.

### 3.2 Data loaders

Pure integration adapters return typed domain objects:

| Loader | Source | Returns |
|--------|--------|---------|
| `load_goals()` | `markdown_goals` | `list[Goal]` |
| `load_tasks()` | `markdown_tasks` | `list[Task]` |
| `load_calendar()` | `google_calendar` | `list[Event]` |

### 3.3 Context Builder (`janus/services/planning_context.py` / planner context logic)

The Context Builder computes deterministic signals before any LLM call.

Responsibilities:

- Filter active goals, open tasks, and upcoming calendar events
- Compute overdue and due-soon tasks
- Detect stalled and behind-target goals
- Detect calendar conflicts
- Detect competing tasks
- Assemble `PlanningContext`

No LLM calls and no side effects occur in this layer.

### 3.4 LLM prompt pipeline

Responsibilities:

- Render `PlanningContext` into an LLM prompt
- Call the LLM through a provider-agnostic client
- Request structured output matching `WeeklyPlan`
- Parse and validate the response
- Handle transient provider failures and use the rule-based fallback when configured

Representative interfaces:

```python
def build_prompt(context: PlanningContext) -> str: ...
def parse_llm_response(raw: str) -> WeeklyPlan: ...
```

### 3.5 State storage

V1 does **not** persist plans. Plans are generated on demand, displayed, and discarded. Future versions may store plans in `data/weekly_plans.md` or another lightweight persistence layer.

## 4. Data Model

All planner models are LLM-independent and follow the established `@dataclass` conventions used by Janus.

### 4.1 Enums

```python
class Priority(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"

class RiskSeverity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
```

### 4.2 PlanningSignals

```python
@dataclass
class PlanningSignals:
    """Deterministic signals computed before the LLM is invoked."""
    overdue_tasks: list[str] = field(default_factory=list)
    due_soon_tasks: list[str] = field(default_factory=list)
    stalled_goals: list[str] = field(default_factory=list)
    behind_target_goals: list[str] = field(default_factory=list)
    calendar_conflicts: list[str] = field(default_factory=list)
    competing_tasks: dict[str, int] = field(default_factory=dict)
```

### 4.3 PlanningContext

```python
@dataclass
class PlanningContext:
    """Input to the weekly planner."""
    goals: list[Goal]
    tasks: list[Task]
    calendar: list[Event]
    signals: PlanningSignals = field(default_factory=PlanningSignals)
```

### 4.4 WeeklyPlan and supporting models

```python
@dataclass
class PriorityEntry:
    """A goal's priority ranking within the weekly plan."""
    goal_id: str
    reason: str
    priority: Priority

@dataclass
class PlannedTask:
    """A task scheduled for a specific day in the weekly plan."""
    task_id: str
    goal_id: str
    priority: Priority
    reason: str
    suggested_day: date

@dataclass
class PlanningRisk:
    """A risk or conflict identified in the weekly plan."""
    description: str
    severity: RiskSeverity

@dataclass
class WeeklyPlan:
    """The output of the weekly planner."""
    week_summary: str
    priorities: list[PriorityEntry] = field(default_factory=list)
    planned_tasks: list[PlannedTask] = field(default_factory=list)
    risks: list[PlanningRisk] = field(default_factory=list)
```

## 5. Command and CLI

### 5.1 Primary command

```bash
uv run janus plan week
```

### 5.2 Flags

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `-h`, `--help` | — | — | Print usage and exit |

V1 accepts no planning filters or output-format arguments.

### 5.3 Dispatch convention

The `plan` command is dispatched in `main()` using the repository's manual `if/elif` convention:

```python
elif command == "plan":
    if len(filtered) < 2 or filtered[1] in ("-h", "--help", "help"):
        print_plan_help()
        return
    sub = filtered[1]
    if sub == "week":
        handle_plan_week(filtered[2:])
    else:
        print(f"Unknown plan subcommand: {sub}")
```

`handle_plan_week()` rejects unexpected arguments and delegates to the configured planner.

### 5.4 Current behavior

The command builds context from current goals, tasks, and calendar data, invokes the configured planner, validates the resulting `WeeklyPlan`, and prints the plan to stdout. The implementation supports both the LLM backend and the deterministic `RuleBasedPlanner` fallback.

### 5.5 CLI output

The renderer follows the style of `weekly.py`:

```text
JANUS WEEKLY PLAN

Week of 05 Oct – 11 Oct 2026 — 2 overdue task(s), 1 stalled goal(s)

TOP PRIORITIES

1. Career
   Has overdue tasks

2. Health
   Active goal

RISKS

⚠ Overdue tasks: Old task
• Stalled goals: Stalled goal

PLANNED TASKS

Monday
  ! Write plan

Tuesday
    Review PR #340
```

JSON output and alternative text formats are deferred.

## 6. LLM Interaction and Error Handling

### 6.1 Provider abstraction

The provider is isolated behind a protocol so that the planner domain remains provider-agnostic:

```python
class LLMClient(Protocol):
    def complete(self, prompt: str, schema: dict) -> str: ...
```

The implementation uses an OpenAI-compatible API configuration supplied outside the domain model.

### 6.2 Structured output

The LLM is instructed to return JSON conforming to the `WeeklyPlan` schema. The response is parsed into domain models and validated before it can reach downstream rendering.

### 6.3 Error handling

The implementation follows the retry/fallback precedent from `t_473202bc` / `kanban_decompose.py`:

1. Transient provider/LLM failures may be retried.
2. Structured output is parsed and validated before downstream use.
3. Invalid structured output is rejected rather than silently accepted.
4. If configured, the `RuleBasedPlanner` is used after exhausted LLM retries.
5. If no fallback is configured, an unrecoverable planner failure raises `RuntimeError`.

User-facing CLI errors follow the existing Janus convention: errors go to stderr and return exit code `1`; warnings go to stderr and execution continues where the condition is recoverable.

### 6.4 Prompt structure

The prompt contains:

- system instructions defining role and constraints,
- the structured `PlanningContext`, including deterministic signals,
- the required `WeeklyPlan` output schema.

## 7. Planner Implementations

### 7.1 WeeklyPlanner Protocol

```python
class WeeklyPlanner(Protocol):
    def plan(self, context: PlanningContext) -> WeeklyPlan: ...
```

### 7.2 `LLMWeeklyPlanner`

Primary planner (`src/janus/planner/llm_planner.py`):

- Builds a prompt from `PlanningContext`.
- Calls the LLM through the provider-agnostic client.
- Parses JSON into `WeeklyPlan`.
- Validates that referenced goal/task IDs exist in context.
- Rejects duplicate task scheduling.
- Retries transient provider failures.
- Falls back to `RuleBasedPlanner` when configured and LLM retries are exhausted.
- Raises `RuntimeError` when no fallback exists and planning cannot complete.

### 7.3 `RuleBasedPlanner`

Fallback planner (`src/janus/plan_cli.py`):

- Prioritizes overdue tasks, stalled goals, and near deadlines.
- Schedules tasks by due date.
- Assigns HIGH priority to tasks overdue or due within three days.
- Identifies risks from overdue, stalled, calendar-conflict, and competing-task signals.
- Builds the plan summary from deterministic signal counts.

### 7.4 `MockPlanner`

A fixed-response implementation is used for deterministic tests and evaluation scenarios.

### 7.5 Planning lifecycle

The broader Janus architecture can evolve toward:

```text
Observe → Plan → Approve/policy → Execute → Observe result → Review
```

V1 stops after **Plan**. Human approval, execution, and feedback loops are deferred to later versions.

## 8. Storage and Integration with Existing Janus State

### 8.1 Read path

The planner reads the same underlying state used by the weekly review:

| Data | Loader | Source |
|------|--------|--------|
| Goals | `markdown_goals.load_goals()` | `data/goals.md` |
| Tasks | `markdown_tasks.load_tasks()` | `data/tasks.md` |
| Calendar | `google_calendar.list_upcoming_events()` | Google Calendar API |

### 8.2 Existing services and patterns

The design leverages:

- `janus/services/goals.py`
- `janus/services/tasks.py`
- `janus/services/weekly_review.py`
- `janus/services/goal_health.py`
- `janus/services/goal_progress.py`
- `janus/integrations/atomic_io.py`
- `janus/services/data_integrity.py`
- `janus/domain/planning.py`

Existing patterns reused include `@dataclass` validation, manual CLI dispatch, connector abstractions, retry/fallback handling, and structured logging through `janus._log.emit`.

### 8.3 No side effects in V1

The planner does not modify goals, tasks, or calendar entries. It only generates and displays a proposal.

## 9. Security and Permissions

- No API keys are stored in source code.
- Credentials are supplied through configuration/environment mechanisms.
- Prompts contain only the data needed for planning, such as goal/task titles and dates.
- Planner output is treated as untrusted until validated.
- Invalid structured output never reaches downstream components.
- V1 has read-only access to goals, tasks, and calendar.

## 10. Evaluation

### 10.1 Approach

Evaluation checks plan **properties**, not exact text. LLM output is not expected to be identical across runs.

### 10.2 Minimum scenario set

| # | Scenario | Property tested |
|---|----------|-----------------|
| 1 | One urgent task | Urgent task prioritized |
| 2 | Many overdue tasks | Overdue tasks addressed or explicitly rejected with reason |
| 3 | Stalled goal | Stalled goal flagged in risks |
| 4 | No calendar availability | Availability constraint reflected in plan |
| 5 | Deadline conflict | Conflict detected and flagged |
| 6 | Too many tasks for one week | Realistic capacity planning |
| 7 | Empty task list | Graceful handling, no crash |
| 8 | Goal with no linked tasks | Risk identified |
| 9 | Already completed goal | Excluded from plan |
| 10 | Multiple goals with similar priority | Sensible tie-breaking |

### 10.3 Quality metrics

Minimum metrics:

- task coverage,
- overdue-task handling,
- deadline awareness,
- calendar conflict rate,
- plan validity,
- unsupported recommendations.

## 11. Error Conditions

| Condition | Behavior | Exit code |
|-----------|----------|-----------|
| Unknown subcommand | Print error to stderr | 1 |
| Unexpected arguments | Print error to stderr | 1 |
| `-h` / `--help` | Print usage | 0 |
| Calendar API unavailable | Proceed without calendar data; note limitation in risks | 0 |
| `data/goals.md` missing | Treat as no goals | 0 |
| `data/tasks.md` missing | Treat as no tasks | 0 |
| LLM provider error | Retry according to planner policy, then fallback or raise | 1 if unrecoverable |
| Invalid LLM structured output | Reject; do not pass downstream | 1 if unrecoverable |
| Duplicate task scheduling | Reject during validation | 1 |

## 12. Definition of Done

V1 is complete when:

- [x] `janus plan week` runs end-to-end
- [x] Reads Goals, Tasks, Calendar (read-only)
- [x] Produces `WeeklyPlan` with priorities, planned tasks, and risks
- [x] `RuleBasedPlanner` and `LLMWeeklyPlanner` implement `WeeklyPlanner`
- [x] Error conditions are handled with defined exit behavior
- [x] Unit tests exist for models, service, and CLI handler
- [x] Evaluation scenarios exist
- [x] Planner has no side effects
- [x] Architecture/documentation exists
- [x] Example output exists
- [x] Entire flow runs with one command

## 13. Rollout and Roadmap

### Phase 1 — Domain and context

- WP-001 — Design Weekly Planner domain model
- WP-002 — Build PlanningContext builder

### Phase 2 — Planner core

- WP-003 — Define WeeklyPlanner interface
- WP-004 — Implement LLM weekly planner

### Phase 3 — CLI

- WP-005 — Add `janus plan week`

### Phase 4 — Evaluation

- WP-006 — Build weekly planner evaluation suite
- WP-007 — Define planner quality metrics

### Phase 5 — Architecture and documentation

- WP-008 — Write Weekly Planner ADR
- WP-009 — Document Weekly Planner

### Phase 6 — V1 completion

- WP-010 — Harden Weekly Planner V1

The repository currently marks the core V1 implementation as complete; WP-010 represents the final hardening/review pass where applicable.

### V2 backlog

- WP-011 — Design action proposal model
- WP-012 — Add human approval workflow
- WP-013 — Add task mutation tools
- WP-014 — Add calendar mutation tools
- WP-015 — Add execution policy
- WP-016 — Add execution result tracking
- WP-017 — Add weekly review loop
- WP-018 — Add planner feedback/evaluation loop

## 14. Open Design Questions

| # | Question | Status |
|---|----------|--------|
| 1 | LLM provider selection | Open — confirm endpoint/model configuration |
| 2 | Structured output validation location | Open — `__post_init__` vs separate validator |
| 3 | Context Builder granularity | Open — reuse existing services vs direct computation |
| 4 | Plan persistence | Resolved — no persistence in V1 |
| 5 | Calendar integration capabilities | Open — free/busy vs event listing |
| 6 | Output formats | Open — JSON/text flags deferred |
| 7 | Date/goal/task filtering | Open — deferred from V1 |
| 8 | Interactive / Telegram mode | Open — deferred beyond V1 |

## 15. Decisions Log

| Decision | Rationale |
|----------|-----------|
| No persistence in V1 | Keeps scope minimal; validates value before adding complexity |
| Deterministic signals before LLM | Reduces token usage and improves planning quality |
| Protocol-based abstraction | Enables mock and rule-based implementations for testing/fallback |
| CLI-only output in V1 | No Telegram approval required; planner remains proposal-only |
| `@dataclass` models | Matches existing Janus model conventions |
| Retry + fallback for LLM errors | Reuses established error-handling precedent |
| Evaluation tests properties, not exact text | LLM output is non-deterministic |

## 16. Future Versions

### V2 — Human-in-the-loop

```text
WeeklyPlan
    ↓
Proposed actions
    ↓
User approval
    ↓
Execution
```

Future planners may propose task creation, priority/deadline changes, or calendar events. Destructive or external actions require explicit approval.

### V3 — Autonomous execution

A future version may add policy-controlled execution after approval/policy evaluation.

### V4 — Feedback loop

A future version may analyze planned actions, completed actions, postponed/ignored actions, goal progress, prediction accuracy, LLM cost, and approval requirements, then feed the results into subsequent planning.