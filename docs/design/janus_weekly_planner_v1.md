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
  (`src/janus/__init__.py:75-307`).
- All data is file-backed under `data/` with `atomic_io` + `data_integrity` write protection
  (`src/janus/integrations/atomic_io.py`, `src/janus/services/data_integrity.py`).
- Goal model: `Goal` dataclass with metric + task-based progress paths
  (`src/janus/models/goal.py:7-149`).
- Weekly review exists (`janus weekly`) but is retrospective — no forward planning.
- Domain planning engine already has rules-based next-action derivation
  (`src/janus/domain/planning.py:297-501`, P1-P7 / R1-R5 priority rules).
- No `plan` command exists; no `plan week` subcommand; no weekly planner module.

---

## 2. Command Syntax and Flags

### 2.1 Primary command

```bash
uv run janus plan week [options]
```

### 2.2 Flags

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `--from` | `YYYY-MM-DD` | Monday of current week | Week start (inclusive) |
| `--to` | `YYYY-MM-DD` | Sunday of current week | Week end (inclusive) |
| `--goal` | `str` | All active goals | Filter to goal matching title substring |
| `--priority` | `int >= 1` | 1 | Minimum priority level to include |
| `--format` | `table \| json \| text` | `table` | Output format |
| `--dry-run` | flag | `false` | Validate inputs, print plan, do not persist |
| `--help` | `-h` | — | Print usage and exit |

### 2.3 Examples

```bash
uv run janus plan week                        # current week, all goals, table
uv run janus plan week --from 2026-10-05      # week containing Oct 5
uv run janus plan week --goal "Career"        # only goals matching "Career"
uv run janus plan week --priority 2           # only priority >= 2
uv run janus plan week --format json          # machine-readable output
uv run janus plan week --dry-run              # validate + print, no persist
```

### 2.4 Dispatch convention

Follow the existing `main()` dispatch pattern (`src/janus/__init__.py:75-307`):

```python
elif command == "plan":
    if len(filtered) < 2 or filtered[1] in ("-h", "--help"):
        print_plan_help()
        return
    sub = filtered[1]
    if sub == "week":
        handle_plan_week(filtered[2:])
    else:
        print(f"Unknown plan subcommand: {sub}")
```

Add `print_plan_help()` and `handle_plan_week()` following the `handle_task_*` /
`handle_goal_*` patterns (`src/janus/tasks_cli.py`, `src/janus/goals_cli.py`).

---

## 3. Weekly Planner Data Model

### 3.1 Domain models

All models live in `src/janus/models/weekly_planner.py` (new file), following the
dataclass convention in `src/janus/models/`.

```python
@dataclass
class PlannedTask:
    """A task proposed for a specific day in the weekly plan."""
    title: str
    goal_title: str | None = None
    priority: int = 1              # 1 = lowest, higher = more important
    suggested_day: str | None = None  # ISO date YYYY-MM-DD, or None = flexible
    reason: str = ""               # Why this task was scheduled this way
    estimated_minutes: int | None = None


@dataclass
class Priority:
    """A ranked priority for the week."""
    level: int                     # 1 = top priority
    goal_title: str
    reason: str


@dataclass
class PlanningRisk:
    """A risk or conflict identified during planning."""
    description: str
    severity: str                  # "low" | "medium" | "high"
    affected_tasks: list[str] = field(default_factory=list)


@dataclass
class WeeklyPlan:
    """The output of the weekly planner."""
    week_start: str                # ISO date YYYY-MM-DD
    week_end: str                  # ISO date YYYY-MM-DD
    generated_at: str              # ISO datetime
    priorities: list[Priority]
    planned_tasks: list[PlannedTask]
    risks: list[PlanningRisk]
    summary: str                   # Human-readable week summary
```

### 3.2 Planning context

```python
@dataclass
class PlanningContext:
    """Input data assembled for the planner."""
    goals: list[Goal]
    tasks: list[Task]
    calendar_events: list[Event]
    today: str                     # ISO date
```

### 3.3 Relationship to existing models

| Model | Source | Used by planner |
|-------|--------|-----------------|
| `Goal` | `src/janus/models/goal.py:7-149` | Active goals provide priorities |
| `Task` | `src/janus/models/task.py:8-27` | Open tasks are plan candidates |
| `Event` | `src/janus/models/event.py:3-13` | Calendar availability |
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

All loaders return empty lists (not errors) when data is missing — consistent
with `load_tasks()` / `load_goals()` behavior.

### 4.2 Write path — persisting plans

New file: `data/weekly_plans.md` — one block per plan, markdown format:

```markdown
# Weekly Plans

## Plan: 2026-10-05 to 2026-10-11
Generated: 2026-10-05T09:00:00Z

### Priority 1: Career
Reason: ...

### Planned Tasks

| Day | Task | Priority | Reason |
|-----|------|----------|--------|
| Mon | Prepare AI/Agent plan | 1 | ... |
| Tue | ... | ... | ... |

### Risks
- High: Multiple tasks compete for same time slot
```

**Persistence mechanism:** Follow the `atomic_io` pattern used by all other
data writers (`src/janus/integrations/atomic_io.py`):
- `atomic_write(path, content)` — write-to-temp + `os.replace`
- Backup rotation via `data_integrity.protected_write()` (configurable,
  `config/config.example.toml` lines 38-60)

### 4.3 No side effects in V1

The planner **does not** modify goals, tasks, or calendar entries. It only
writes the plan to `data/weekly_plans.md`. All mutations require explicit
user approval (deferred to V2).

---

## 5. CLI Output Format

### 5.1 Table format (default)

Match the `weekly.py` renderer style (`src/janus/weekly.py:6-79`):

```text
JANUS — WEEKLY PLAN
5–11 Oct 2026

TOP PRIORITIES
  1. Career — Complete AI/Agent Engineering development plan
  2. Janus  — Finish weekly planner V1 design
  3. Health — 2 strength sessions

PLANNED TASKS
  Monday
    [P1] Prepare AI/Agent plan (Career)
    [P2] Review PR #340 (Janus)
  Tuesday
    [P1] Write planner tests (Janus)
    [P2] Run 5 km (Health)

RISKS
  ⚠ Career goal has no completed actions this sprint
  ⚠ Multiple tasks compete for the same time slot
```

### 5.2 JSON format (`--format json`)

```json
{
  "week_start": "2026-10-05",
  "week_end": "2026-10-11",
  "generated_at": "2026-10-05T09:00:00Z",
  "priorities": [
    {"level": 1, "goal_title": "Career", "reason": "..."}
  ],
  "planned_tasks": [
    {
      "title": "Prepare AI/Agent plan",
      "goal_title": "Career",
      "priority": 1,
      "suggested_day": "2026-10-05",
      "reason": "...",
      "estimated_minutes": null
    }
  ],
  "risks": [
    {"description": "...", "severity": "high", "affected_tasks": []}
  ],
  "summary": "..."
}
```

### 5.3 Text format (`--format text`)

Plain text, one line per planned task:

```text
2026-10-05 [P1] Prepare AI/Agent plan (Career) — ...
2026-10-05 [P2] Review PR #340 (Janus) — ...
```

---

## 6. Error Conditions

| Condition | Behavior | Exit Code |
|-----------|----------|-----------|
| No active goals | Print "No active goals — nothing to plan" | 0 |
| No open tasks | Print "No open tasks" + priorities from goals only | 0 |
| Invalid `--from` / `--to` date | Print error to stderr, `sys.exit(1)` | 1 |
| `--from` after `--to` | Print error to stderr, `sys.exit(1)` | 1 |
| `--goal` not matching any active goal | Print warning, proceed with all goals | 0 |
| `--priority` not an integer | Print error to stderr, `sys.exit(1)` | 1 |
| `--format` not in {table, json, text} | Print error to stderr, `sys.exit(1)` | 1 |
| Calendar API unavailable | Proceed without calendar data; note in risks | 0 |
| `data/goals.md` missing | Treat as no goals (match `load_goals` empty-list behavior) | 0 |
| `data/tasks.md` missing | Treat as no tasks (match `load_tasks` behavior) | 0 |
| LLM provider error (V2) | Print error, show partial plan if available | 1 |
| LLM timeout (V2) | Retry once, then fail with partial plan | 1 |
| Invalid LLM structured output (V2) | Reject, retry up to 3 times, then fail | 1 |
| Write failure (persist plan) | Print error, plan was generated but not saved | 1 |
| Concurrent write conflict | Retry per `atomic_io` backoff, then fail | 1 |

### 6.1 Error handling conventions

Follow the existing pattern from `tasks_cli.py` and `goals_cli.py`:
- User-facing errors: `print(f"Error: ...", file=sys.stderr)` + `sys.exit(1)`
- Warnings: `print(f"Warning: ...", file=sys.stderr)` + continue
- Help: `-h` / `--help` flag on every subcommand

---

## 7. Open Design Questions

| # | Question | Status | Notes |
|---|----------|--------|-------|
| Q1 | **LLM provider integration** | Open | V1 could use rule-based planning (reuse `domain/planning.py` P1-P7). LLM path deferred to V2 or made optional via config flag. |
| Q2 | **Plan persistence format** | Open | Markdown (`data/weekly_plans.md`) vs. JSON vs. structured Goal blocks. Markdown matches existing convention but is harder to query. |
| Q3 | **Task duration estimation** | Open | Tasks have no duration field. `estimated_minutes` on `PlannedTask` is new — needs a source (manual? ML? historical?). |
| Q4 | **Calendar write access** | Open | V1 is read-only for calendar. Auto-creating focus blocks requires OAuth scope upgrade (per `planning_calendar_findings.md`). |
| Q5 | **Plan evaluation criteria** | Open | What makes a "good" plan? Overdue coverage? Priority alignment? Calendar fit? Needs explicit metric before V2. |
| Q6 | **Multi-week planning** | Open | V1 plans one week. Multi-week requires cross-week dependency tracking. |
| Q7 | **Goal deadline awareness** | Open | `Goal.deadline` exists but is not used in planning logic. Should near-deadline goals get automatic priority boost? |
| Q8 | **Side effects policy** | Open | V1 is read-only (no mutations). V2 needs approval workflow for task creation/modification. |
| Q9 | **Interactive mode** | Open | Should `janus plan week` support Telegram interaction for clarifications? |
| Q10 | **Plan revision** | Open | If a task is completed mid-week, should `janus plan week` support `--update` to re-plan remaining days? |

---

## 8. Definition of Done

- [ ] `janus plan week` runs end-to-end (rule-based, no LLM)
- [ ] Reads Goals, Tasks, Calendar (read-only)
- [ ] Produces `WeeklyPlan` with priorities, planned tasks, risks
- [ ] `--format table|json|text` works
- [ ] `--dry-run` validates without persisting
- [ ] All error conditions handled with correct exit codes
- [ ] Persists plan to `data/weekly_plans.md` via `atomic_io`
- [ ] Tests: unit tests for models, service, CLI handler
- [ ] Matches tone/structure of existing `docs/design/` docs
- [ ] No side effects on goals/tasks/calendar

---

## 9. Out of Scope for V1

- LLM-powered planning (rule-based only)
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
| Existing weekly planner architecture spec | `docs/design/janus_weekly_planner_v1.md` (high-level, pre-existing) |