# Janus Weekly Planner — V1 Design

> **Status:** Design complete. Not implemented. Not committed.
> **Source:** Research of `src/janus/`, `tests/`, `docs/design/`, `docs/research-findings/`.
> **Companion research:** `docs/research-findings/goal_system_discovery_research.md`,
> `docs/research-findings/planning_calendar_findings.md`,
> `docs/research-findings/goal_health_progress_research_findings.md`.

---

## 1. Executive Summary

Add `janus plan week` — a deterministic + LLM-assisted weekly planner that produces a
structured `WeeklyPlan` from active goals, open tasks, and calendar availability.

V1 answers one question:

> Can Janus generate a credible week plan grounded in real goals, tasks, and calendar data?

**Key constraints (from research):**

- CLI uses manual arg parsing — no argparse/click/typer; dispatch-by-if-elif in `main()`
  (`src/janus/__init__.py:286-295`).
- All data is file-backed under `data/` with `atomic_io` + `data_integrity` write protection
  (`src/janus/integrations/atomic_io.py`).
- Goal model: `Goal` dataclass with metric + task-based progress paths
  (`src/janus/models/goal.py:7-149`).
- Weekly review exists (`janus weekly`) but is retrospective — no forward planning.
- Domain planning engine already has rules-based next-action derivation
  (`src/janus/domain/planning.py:297-501`, P1-P7 / R1-R5 priority rules).
- `plan_cli.py` already exists on master with `RuleBasedPlanner`, `PlanningContext`, `WeeklyPlan` models.
- `WeeklyPlanner` Protocol defined in `planner/protocol.py`.
- `LLMWeeklyPlanner` implemented in `planner/llm_planner.py`.

---

## 2. Command Syntax and Flags

### 2.1 Primary command

```bash
uv run janus plan week [options]
```

### 2.2 Flags (V1 scope)

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `-h`, `--help` | flag | — | Print usage and exit |

### 2.3 Current master implementation

The current `handle_plan_week` on master accepts no arguments — any extra args print an error
(`src/janus/plan_cli.py:405-431`). Flags like `--from`, `--to`, `--goal`, `--priority`,
`--format`, `--dry-run` are not yet implemented; they are reserved for a future flag-passing
refactor of the dispatch convention (see §10).

### 2.4 Examples

```bash
uv run janus plan week            # current week, all goals, table
uv run janus plan week --help     # print usage
```

### 2.5 Dispatch convention

Follow the existing `main()` dispatch pattern (`src/janus/__init__.py:286-295`):

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
        print_plan_help()
```

Imports already present on master (`src/janus/__init__.py:45`):

```python
from janus.plan_cli import handle_plan_week, print_plan_help
```

---

## 3. Weekly Planner Data Model

### 3.1 Domain models

All planner models live in `src/janus/planner/models.py` (new on master), following the
dataclass convention in `src/janus/models/`.

```python
@dataclass
class PlannedTask:
    task_id: str                       # persistence identity (task title)
    goal_id: str                       # goal this task supports
    priority: Priority                 # HIGH / MEDIUM / LOW
    reason: str                        # Why this task was scheduled this way
    suggested_day: date                # ISO date, the day this task is suggested for


@dataclass
class PriorityEntry:
    goal_id: str                       # persistence identity (goal title)
    reason: str                        # Human-readable justification
    priority: Priority                 # HIGH / MEDIUM / LOW


@dataclass
class PlanningRisk:
    description: str
    severity: RiskSeverity             # LOW / MEDIUM / HIGH


@dataclass
class PlanningSignals:
    overdue_tasks: list[str]
    due_soon_tasks: list[str]
    stalled_goals: list[str]
    behind_target_goals: list[str]
    calendar_conflicts: list[str]
    competing_tasks: dict[str, int]


@dataclass
class WeeklyPlan:
    week_summary: str                  # Human-readable week summary
    priorities: list[PriorityEntry]
    planned_tasks: list[PlannedTask]
    risks: list[PlanningRisk]
```

Enums (`Priority`, `RiskSeverity`) are `StrEnum` in `src/janus/planner/models.py`.

### 3.2 Planning context

```python
@dataclass
class PlanningContext:
    goals: list[Goal]
    tasks: list[Task]
    calendar: list[Event]
    signals: PlanningSignals = field(default_factory=PlanningSignals)
```

### 3.3 Relationship to existing models

| Model | Source | Used by planner |
|-------|--------|-----------------|
| `Goal` | `src/janus/models/goal.py:7-149` | Active goals provide priorities |
| `Task` | `src/janus/models/task.py:7-27` | Open tasks are plan candidates |
| `Event` | `src/janus/models/event.py` | Calendar availability |
| `NextAction` | `src/janus/domain/planning.py:36-119` | Reuse priority derivation rules |

### 3.4 Interface

`WeeklyPlanner` Protocol defined in `src/janus/planner/protocol.py`:

```python
class WeeklyPlanner(Protocol):
    def plan(self, context: PlanningContext) -> WeeklyPlan: ...
```

Two implementations on master:

| Implementation | Module | Role |
|---------------|--------|------|
| `RuleBasedPlanner` | `src/janus/plan_cli.py:145` | Deterministic fallback; no LLM |
| `LLMWeeklyPlanner` | `src/janus/planner/llm_planner.py:65` | Primary; LLM-driven planning |

---

## 4. Storage / Integration with Existing Janus State

### 4.1 Read path — existing data

The planner reads from the same sources as the weekly review:

| Data | Loader | File |
|------|--------|------|
| Goals | `markdown_goals.load_goals()` | `data/goals.md` |
| Tasks | `markdown_tasks.load_tasks()` | `data/tasks.md` |
| Calendar | `google_calendar.list_upcoming_events()` | Google Calendar API |

`load_goals()` returns `[]` (not errors) when the file is missing.

### 4.2 Write path — persisting plans

**Not implemented in V1.** The current master `plan week` produces ephemeral output only
(`_format_plan` prints to stdout; no file write). Persistence to `data/weekly_plans.md`
is reserved for a future update.

### 4.3 Side effects in V1

The planner **does not** modify goals, tasks, or calendar entries. It only displays the plan.
All mutations require explicit user approval (deferred to V2).

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

2. Janus
   Active goal

RISKS

⚠ Overdue tasks: Review PR #340
• Stalled goals: Health

PLANNED TASKS

Monday
  ! Prepare AI/Agent plan
  Review PR #340

Tuesday
  Write planner tests
```

Output formatting: `_format_plan()` in `src/janus/plan_cli.py:330`.

### 5.2 JSON format (`--format json`)

Reserved for future flag implementation (not yet on master).

### 5.3 Text format (`--format text`)

Reserved for future flag implementation (not yet on master).

---

## 6. Error Conditions

| Condition | Behavior | Exit Code |
|-----------|----------|-----------|
| Extra args passed | Print error to stderr, `sys.exit(1)` | 1 |
| `-h` / `--help` | Print help, return | 0 |
| Unknown subcommand | Print error + help, `sys.exit(1)` | 1 |
| No active goals | Planner produces empty priorities | 0 |
| No open tasks | Planner produces empty planned_tasks | 0 |
| Calendar API unavailable | Proceed without calendar data | 0 |
| `data/goals.md` missing | Treat as no goals (empty list) | 0 |
| `data/tasks.md` missing | Treat as no tasks (empty list) | 0 |
| LLM provider error (V2) | Print error, show partial plan if available | 1 |
| LLM timeout (V2) | Retry once, then fail with partial plan | 1 |
| Invalid LLM structured output (V2) | Reject, retry up to 3 times, then fail | 1 |

### 6.1 Error handling conventions

Follow the existing pattern from `tasks_cli.py` and `goals_cli.py`:

- User-facing errors: `print(f"Error: ...", file=sys.stderr)` + `sys.exit(1)`
- Warnings: `print(f"Warning: ...", file=sys.stderr)` + continue
- Help: `-h` / `--help` flag on every subcommand

---

## 7. Open Design Questions

| # | Question | Status | Notes |
|---|----------|--------|-------|
| Q1 | **Flag passing** | Open | Current master accepts no args; `--from`, `--to`, `--goal`, `--priority`, `--format`, `--dry-run` need dispatch integration |
| Q2 | **Plan persistence** | Open | V1 is ephemeral only. Markdown (`data/weekly_plans.md`) vs. JSON vs. structured Goal blocks. |
| Q3 | **Task duration estimation** | Open | Tasks have no duration field. Needs a source (manual? ML? historical?). |
| Q4 | **Calendar write access** | Open | V1 is read-only for calendar. Auto-creating focus blocks requires OAuth scope upgrade. |
| Q5 | **Plan evaluation criteria** | Open | What makes a "good" plan? Overdue coverage? Priority alignment? Calendar fit? |
| Q6 | **Multi-week planning** | Open | V1 plans one week. Multi-week requires cross-week dependency tracking. |
| Q7 | **Goal deadline awareness** | Open | `Goal.deadline` exists and is used in `RuleBasedPlanner._prioritize_goals` — but not in LLM path yet. |
| Q8 | **Side effects policy** | Open | V1 is read-only (no mutations). V2 needs approval workflow for task creation/modification. |
| Q9 | **Interactive mode** | Open | Should `janus plan week` support Telegram interaction for clarifications? |
| Q10 | **Plan revision** | Open | If a task is completed mid-week, should `janus plan week` support `--update` to re-plan remaining days? |

---

## 8. Definition of Done

- [ ] `janus plan week` runs end-to-end (rule-based via `RuleBasedPlanner`)
- [ ] Reads Goals, Tasks, Calendar (read-only)
- [ ] Produces `WeeklyPlan` with priorities, planned tasks, risks
- [ ] Help (`-h` / `--help`) works
- [ ] All error conditions handled with correct exit codes
- [ ] Tests: unit tests for models, service, CLI handler
- [ ] Matches tone/structure of existing `docs/design/` docs
- [ ] No side effects on goals/tasks/calendar

---

## 9. Out of Scope for V1

- Flag passing (`--from`, `--to`, `--goal`, `--priority`, `--format`, `--dry-run`)
- Plan persistence (ephemeral output only)
- LLM-powered planning (rule-based only in V1; LLM path exists but is secondary)
- Plan execution / task mutation
- Calendar write access
- Interactive / Telegram planning
- Multi-week plans
- Historical plan analysis / feedback loop
- Automatic plan revision mid-week

---

## 10. Repository Patterns Referenced

| Pattern | Source |
|---------|--------|
| Manual arg parsing, `sys.exit(1)` on error | `src/janus/tasks_cli.py:86-418`, `src/janus/goals_cli.py:253-501` |
| CLI dispatch: `if/elif` chain in `main()` | `src/janus/__init__.py:286-295` |
| Data loading from `data/*.md` | `src/janus/integrations/markdown_tasks.py`, `markdown_goals.py` |
| Atomic writes via `atomic_io` | `src/janus/integrations/atomic_io.py:248` |
| `Goal` dataclass with validation | `src/janus/models/goal.py:7-149` |
| `Task` dataclass | `src/janus/models/task.py:7-27` |
| `Event` dataclass | `src/janus/models/event.py` |
| Rules-based priority derivation (P1-P7) | `src/janus/domain/planning.py:297-501` |
| Weekly review renderer | `src/janus/weekly.py:6-79` |
| Weekly review service (deterministic) | `src/janus/services/weekly_review.py:193-334` |
| Config TOML structure | `config/config.example.toml:1-79` |
| Design doc conventions (status banner, kebab-case, numbered sections, code citations) | `docs/design/goal_system_design.md` |
| Existing plan CLI with RuleBasedPlanner | `src/janus/plan_cli.py:1-431` |
| WeeklyPlanner Protocol | `src/janus/planner/protocol.py` |
| LLMWeeklyPlanner implementation | `src/janus/planner/llm_planner.py:65-479` |