# Janus Weekly Planner — V1 Design

> **Status:** Design complete. Implemented on master (rule-based + LLM backend).
> **Source:** Research of `src/janus/`, `tests/`, `docs/design/`, `docs/research-findings/`.
> **Companion research:** `docs/research-findings/goal_system_discovery_research.md`,
> `docs/research-findings/planning_calendar_findings.md`,
> `docs/research-findings/goal_health_progress_research_findings.md`.

---

## 1. Executive Summary

`janus plan week` generates a structured weekly plan from active goals, open tasks,
and calendar availability. V1 implements two planner backends:

- **`LLMWeeklyPlanner`** (primary) — LLM-driven planning with structured output,
  retry, and fallback.
- **`RuleBasedPlanner`** (fallback) — deterministic rules when no LLM is available.

Both satisfy the `WeeklyPlanner` Protocol and produce the same `WeeklyPlan` model.

**Key constraints (from research):**

- CLI uses manual arg parsing — no argparse/click/typer; dispatch-by-if-elif in
  `main()` (`src/janus/__init__.py:75-307`).
- All data is file-backed under `data/` with `atomic_io` + `data_integrity` write
  protection (`src/janus/integrations/atomic_io.py`, `src/janus/services/data_integrity.py`).
- Goal model: `Goal` dataclass with metric + task-based progress paths
  (`src/janus/models/goal.py:7-149`).
- Weekly review exists (`janus weekly`) but is retrospective — no forward planning.
- Domain planning engine already has rules-based next-action derivation
  (`src/janus/domain/planning.py:297-501`, P1-P7 / R1-R5 priority rules).
- `plan_cli.py` exists on master with `RuleBasedPlanner`, `PlanningContext`,
  `WeeklyPlan`, `handle_plan_week`, `print_plan_help` (`src/janus/plan_cli.py`).

---

## 2. Command Syntax and Flags

### 2.1 Primary command

```bash
uv run janus plan week
```

### 2.2 Flags

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `-h`, `--help` | — | — | Print usage and exit |

### 2.3 Current behavior (V1 on master)

`janus plan week` accepts no arguments. It builds context from current data,
runs `RuleBasedPlanner`, and prints the formatted plan to stdout.

```bash
uv run janus plan week          # current week, all goals, table output
uv run janus plan week --help   # print usage
```

### 2.4 Dispatch convention

The `plan` command is dispatched in `main()` (`src/janus/__init__.py`):

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

`handle_plan_week()` rejects any arguments (exit 1) and delegates to the
planner. `print_plan_help()` prints usage for the `plan` command group.

---

## 3. Weekly Planner Data Model

All models live in `src/janus/planner/models.py`, following the dataclass
convention used across `src/janus/models/`.

### 3.1 Enums

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

### 3.2 Domain models

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


@dataclass
class PlanningContext:
    """Input to the weekly planner."""
    goals: list[Goal]
    tasks: list[Task]
    calendar: list[Event]
    signals: PlanningSignals = field(default_factory=PlanningSignals)


@dataclass
class PriorityEntry:
    """A goal's priority ranking within the weekly plan."""
    goal_id: str            # Goal title (persistence identity)
    reason: str             # Human-readable justification
    priority: Priority      # HIGH / MEDIUM / LOW


@dataclass
class PlannedTask:
    """A task scheduled for a specific day in the weekly plan."""
    task_id: str            # Task title (persistence identity)
    goal_id: str            # Goal this task supports
    priority: Priority      # HIGH / MEDIUM / LOW
    reason: str             # Human-readable justification
    suggested_day: date     # Date this task is suggested for


@dataclass
class PlanningRisk:
    """A risk or conflict identified in the weekly plan."""
    description: str
    severity: RiskSeverity  # LOW / MEDIUM / HIGH


@dataclass
class WeeklyPlan:
    """The output of the weekly planner."""
    week_summary: str
    priorities: list[PriorityEntry] = field(default_factory=list)
    planned_tasks: list[PlannedTask] = field(default_factory=list)
    risks: list[PlanningRisk] = field(default_factory=list)
```

### 3.3 Planning context builder

`_build_context()` in `plan_cli.py` loads active goals, open tasks, and calendar
events for the current week, then computes deterministic signals:

- overdue tasks (due date < today)
- due soon tasks (due within 7 days)
- stalled goals (no recent activity)
- calendar conflicts (task due date on a busy day)
- competing tasks (multiple tasks due same day)

All loaders are wrapped in try/except — missing data yields empty collections,
never exceptions.

### 3.4 Relationship to existing models

| Model | Source | Used by planner |
|-------|--------|-----------------|
| `Goal` | `src/janus/models/goal.py:7-149` | Active goals provide priorities |
| `Task` | `src/janus/models/task.py:7-27` | Open tasks are plan candidates |
| `Event` | `src/janus/models/event.py` | Calendar availability |
| `NextAction` | `src/janus/domain/planning.py:36-119` | Reuse priority derivation rules |

---

## 4. Storage / Integration with Existing Janus State

### 4.1 Read path — existing data

The planner reads from the same sources as the weekly review:

| Data | Loader | File |
|------|--------|------|
| Goals | `markdown_goals.load_goals()` | `data/goals.md` |
| Tasks | `markdown_tasks.load_tasks()` | `data/tasks.md` |
| Calendar | `google_calendar.list_upcoming_events()` | Google Calendar API |

### 4.2 Write path

V1 on master does **not** persist plans to disk. The plan is generated and
displayed to stdout only. Persistence (`data/weekly_plans.md` via `atomic_io`)
is an open design question (see §8).

### 4.3 No side effects in V1

The planner **does not** modify goals, tasks, or calendar entries. It only
generates a plan proposal and prints it. All mutations require explicit user
approval (deferred to V2).

---

## 5. CLI Output Format

### 5.1 Table format (default)

Match the `weekly.py` renderer style (`src/janus/weekly.py:6-79`):

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

### 5.2 JSON format

Not implemented in V1 on master. Deferred to a future `--format json` flag.

### 5.3 Text format

Not implemented in V1 on master. Deferred to a future `--format text` flag.

---

## 6. Error Conditions

| Condition | Behavior | Exit Code |
|-----------|----------|-----------|
| Unknown subcommand | Print error to stderr | 1 |
| Unexpected arguments | Print error to stderr, `sys.exit(1)` | 1 |
| `-h` / `--help` | Print usage, return | 0 |
| Calendar API unavailable | Proceed without calendar data; note in risks | 0 |
| `data/goals.md` missing | Treat as no goals (match `load_goals` empty-list behavior) | 0 |
| `data/tasks.md` missing | Treat as no tasks (match `load_tasks` behavior) | 0 |
| LLM provider error (LLM backend) | Retry up to `max_retries`, then use fallback or raise `RuntimeError` | 1 |
| Invalid LLM structured output | Reject with `ValueError`, retry up to 3 times | 1 |
| Duplicate task scheduling | Reject with `ValueError` during validation | 1 |

### 6.1 Error handling conventions

Follow the existing pattern from `tasks_cli.py` and `goals_cli.py`:

- User-facing errors: `print(f"Error: ...", file=sys.stderr)` + `sys.exit(1)`
- Warnings: `print(f"Warning: ...", file=sys.stderr)` + continue
- Help: `-h` / `--help` flag on every subcommand

---

## 7. Planner Implementations

### 7.1 `LLMWeeklyPlanner` (primary, `src/janus/planner/llm_planner.py`)

- Builds a prompt from `PlanningContext` (goals, tasks, calendar, signals).
- Calls the LLM via the `LLMClient` Protocol (provider-agnostic).
- Parses JSON response into `WeeklyPlan`.
- Validates: goal/task IDs exist in context, no duplicate scheduling.
- Retry on LLM errors (transient); no retry on parse/validation errors.
- Fallback to `RuleBasedPlanner` if all retries exhausted and fallback set.
- Raises `RuntimeError` if no fallback and all retries exhausted.

### 7.2 `RuleBasedPlanner` (fallback, `src/janus/plan_cli.py`)

- Prioritizes goals: overdue tasks → HIGH, stalled → HIGH, deadline soon → HIGH.
- Schedules tasks by due date; HIGH priority if due < today or due within 3 days.
- Identifies risks from signals (overdue, stalled, calendar conflicts, competing).
- Builds summary from signal counts.

### 7.3 `WeeklyPlanner` Protocol (`src/janus/planner/protocol.py`)

```python
class WeeklyPlanner(Protocol):
    def plan(self, context: PlanningContext) -> WeeklyPlan: ...
```

All implementations satisfy this protocol. The CLI handler types the planner
as `WeeklyPlanner` for dependency inversion.

---

## 8. Tests

Tests live in `tests/test_plan_cli.py` and cover:

- `print_plan_help` — usage output
- `handle_plan_week` — basic invocation, help flag, rejects arguments, empty context
- `_build_context` — loads goals/tasks, filters inactive goals, handles missing
  data, computes overdue/due soon/stalled signals
- `RuleBasedPlanner` — returns `WeeklyPlan`, prioritizes goals with overdue
  tasks, schedules by due date, identifies risks, empty context
- `_format_plan` — complete plan, empty plan, groups tasks by day

---

## 9. Open Design Questions

| # | Question | Status | Notes |
|---|----------|--------|-------|
| Q1 | **Plan persistence** | Open | V1 does not persist plans. `data/weekly_plans.md` via `atomic_io` is proposed but not implemented. |
| Q2 | **`--format json/text` flags** | Open | Not implemented in V1. CLI accepts no arguments currently. |
| Q3 | **`--from`/`--to` date range** | Open | Not implemented; V1 always plans the current week (Mon–Sun). |
| Q4 | **`--goal` filter** | Open | Not implemented; V1 uses all active goals. |
| Q5 | **`--priority` filter** | Open | Not implemented; V1 uses all tasks. |
| Q6 | **`--dry-run` flag** | Open | Not implemented; V1 never persists, so this is a no-op today. |
| Q7 | **LLM provider configuration** | Open | `LLMClient` Protocol is provider-agnostic; no config TOML structure for API keys/providers yet. |
| Q8 | **Calendar write access** | Open | V1 is read-only for calendar. Auto-creating focus blocks requires OAuth scope upgrade. |
| Q9 | **Interactive / Telegram mode** | Open | Should `janus plan week` support Telegram interaction for clarifications? |
| Q10 | **Plan evaluation criteria** | Open | What makes a "good" plan? Overdue coverage? Priority alignment? Calendar fit? Needs explicit metric before V2. |

---

## 10. Repository Patterns Referenced

| Pattern | Source |
|---------|--------|
| Manual arg parsing, `sys.exit(1)` on error | `src/janus/tasks_cli.py:86-418`, `src/janus/goals_cli.py:253-501` |
| CLI dispatch: `if/elif` chain in `main()` | `src/janus/__init__.py:75-307` |
| Data loading from `data/*.md` | `src/janus/integrations/markdown_tasks.py`, `markdown_goals.py` |
| Atomic writes via `atomic_io` | `src/janus/integrations/atomic_io.py:1-457` |
| Data integrity / backup rotation | `src/janus/services/data_integrity.py` |
| `Goal` dataclass with validation | `src/janus/models/goal.py:7-149` |
| `Task` dataclass | `src/janus/models/task.py:7-27` |
| `Event` dataclass | `src/janus/models/event.py` |
| Rules-based priority derivation (P1-P7) | `src/janus/domain/planning.py:297-501` |
| Weekly review renderer | `src/janus/weekly.py:6-79` |
| Weekly review service (deterministic) | `src/janus/services/weekly_review.py:193-334` |
| Config TOML structure | `config/config.example.toml:1-79` |
| Design doc conventions (status banner, kebab-case, numbered sections, code citations) | `docs/design/goal_system_design.md` |

---

## 11. Definition of Done

- [x] `janus plan week` runs end-to-end (rule-based + LLM backend)
- [x] Reads Goals, Tasks, Calendar (read-only)
- [x] Produces `WeeklyPlan` with priorities, planned tasks, risks
- [x] `RuleBasedPlanner` and `LLMWeeklyPlanner` implement `WeeklyPlanner` Protocol
- [x] Error conditions handled with correct exit codes
- [x] Tests: unit tests for models, service, CLI handler (`tests/test_plan_cli.py`)
- [x] Matches tone/structure of existing `docs/design/` docs
- [x] No side effects on goals/tasks/calendar

---

## 12. Out of Scope for V1

- Plan persistence to disk
- `--format json/text` flags
- `--from`/`--to` date range
- `--goal` / `--priority` filters
- `--dry-run` flag
- Interactive / Telegram planning
- Multi-week plans
- Historical plan analysis / feedback loop
- Automatic plan revision mid-week