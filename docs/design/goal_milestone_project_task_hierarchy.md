# Goal → Milestone → Project → Task Hierarchy — Design Spec

**Task:** t_4b368d4d
**Status:** Draft for review — v2
**Base state:** docs/design/execution_planning.md + ADR-003 fully implemented and tested (1210 tests pass)
**This is a design document only — no implementation changes.**

---

## 1. Executive Summary

The current Janus execution-planning model is a two-level hierarchy:

```text
Goal ──► Milestone ──► Task
```

Goals own milestones; tasks are flat entities in `data/tasks.md` linked to goals by title strings in `goal.related_tasks`.

Task membership in milestones is currently **derived dynamically** rather than stored explicitly. Per ADR-003, all related tasks belong to the earliest non-terminal milestone.

The roadmap calls for extending this to a four-level hierarchy:

```text
Goal ──► Milestone ──► Project ──► Task
```

This specification introduces **Project** as an intermediate execution unit between Milestone and Task.

The design deliberately separates three concepts:

1. **Task inventory** — which tasks belong to a Goal.
2. **Task assignment** — which Project explicitly owns a task.
3. **Execution ordering** — which Milestone and Project should currently be worked on.

Projects provide explicit task assignment while preserving the existing dynamic derivation as a backward-compatible fallback.

### What changes vs. today

| Aspect             | Current state                | Proposed design                                      |
| ------------------ | ---------------------------- | ---------------------------------------------------- |
| Hierarchy          | Goal → Milestone → Task      | Goal → Milestone → Project → Task                    |
| Task inventory     | `Goal.related_tasks`         | `Goal.related_tasks` — unchanged                     |
| Task assignment    | Dynamic milestone derivation | Explicit Project assignment + legacy fallback        |
| New entity         | —                            | `Project` dataclass                                  |
| Persistence        | `goals.md` with Milestones   | `goals.md` with Milestones + Projects                |
| Next-action engine | R1–R5                        | Project-aware traversal                              |
| Project ownership  | —                            | Explicit, at most one Project per Task within a Goal |
| Project state      | —                            | open / active / blocked / completed / skipped        |

### What does NOT change

* `Task` model: unchanged.
* Existing `Goal.related_tasks`: remains the canonical task inventory for a goal.
* Existing Goal → Milestone dynamic task derivation: preserved as a fallback.
* ADR-003 milestone lifecycle: unchanged:

  * `open`
  * `in_progress`
  * `completed`
  * `skipped`
* Milestone ordering and deadline semantics remain unchanged.
* Goal health signals, attention engine scoring, metric history, and goal progress remain unaffected.
* Project does not become a measurement layer.

---

# 2. Domain Model

## 2.1 Hierarchy

The conceptual domain hierarchy becomes:

```text
Goal
│
├── Milestone
│   │
│   ├── Project
│   │   ├── Task references
│   │   └── ...
│   │
│   └── ...
│
└── related_tasks
```

The important distinction is:

```text
Goal.related_tasks
    = canonical task inventory

Project.related_tasks
    = explicit task assignment

unassigned Goal.related_tasks
    = legacy dynamic derivation
```

A task can therefore be:

```text
Goal
 └── Task
```

without a Project during gradual adoption.

Once explicitly assigned to a Project:

```text
Goal
 └── Milestone
      └── Project
           └── Task
```

the Project assignment becomes authoritative.

---

## 2.2 Domain Invariants

The following invariants are normative and must be enforced by the service layer.

### I1 — Project belongs to exactly one Milestone

A Project must always reference an existing Milestone.

```text
Project → Milestone → Goal
```

The Project does not independently store the Goal as a second foreign key.

### I2 — Project title is unique within its Milestone

Two Projects under the same Milestone cannot have the same title.

The same Project title may exist under different Milestones.

Example:

```text
Milestone A
 └── Project: Research

Milestone B
 └── Project: Research
```

is valid.

### I3 — A Task can belong to at most one Project within a Goal

This is a critical invariant.

Invalid:

```text
Project A → Task X
Project B → Task X
```

Valid:

```text
Project A → Task X
Project B → Task Y
```

This guarantees deterministic task ownership.

### I4 — Project tasks must belong to the same Goal

A Project cannot explicitly assign a Task belonging to another Goal.

The service layer must reject cross-goal task references.

### I5 — Goal.related_tasks is the canonical Goal task inventory

A Project assignment does not remove the task from `Goal.related_tasks`.

Instead:

```text
Goal.related_tasks
    ↓
canonical inventory

Project.related_tasks
    ↓
explicit execution assignment
```

### I6 — Project assignment overrides dynamic derivation

If a task appears in a Project, that assignment is authoritative.

The task must not subsequently be treated as an unassigned dynamic task.

### I7 — Unassigned tasks retain legacy behavior

A task in `Goal.related_tasks` that is not assigned to any Project continues to participate in the existing dynamic milestone derivation.

### I8 — Project order is stable

Project `order` is assigned when the Project is created.

It is not automatically renumbered when Projects are skipped or deleted.

### I9 — Project status `blocked` is non-terminal

A blocked Project may later become `open` or `active`.

Terminal Project states are:

```text
completed
skipped
```

### I10 — Project parent references are immutable in MVP

Project reassignment between Milestones is out of scope.

`goal_title` and `milestone_title` are therefore not editable through `project update`.

If Project reassignment is required later, it should be implemented as an explicit move operation with invariant validation.

---

# 3. The Project Entity

## 3.1 Data Model

**New file:**

```text
src/janus/models/project.py
```

```python
@dataclass
class Project:
    """A project groups related tasks under a milestone."""

    title: str
    milestone_title: str
    description: str = ""
    deadline: str | None = None
    status: str = "open"
    order: int = 0
    related_tasks: list[str] = None

    def __post_init__(self):
        if self.related_tasks is None:
            self.related_tasks = []

        self.related_tasks = self._dedup(self.related_tasks)

        if self.status not in (
            "open",
            "active",
            "blocked",
            "completed",
            "skipped",
        ):
            raise ValueError(...)

        if not self.title or not self.title.strip():
            raise ValueError("Project title must not be empty")
```

The domain model intentionally does **not** contain `goal_title`.

The Goal is obtained from the parent context:

```text
Project
  └── milestone_title
        └── Goal
```

This prevents inconsistent duplicate parent references.

---

## 3.2 Why These Fields

### `title`

Human-readable Project identity.

Unique within its parent Milestone.

### `milestone_title`

Parent Milestone reference.

The current MVP continues using title-based references to remain compatible with the existing Janus model.

### `description`

Optional human-readable description of the execution scope.

### `deadline`

Optional ISO date:

```text
YYYY-MM-DD
```

### `status`

One of:

```text
open
active
blocked
completed
skipped
```

### `order`

Stable sequential position within the parent Milestone.

Assigned once at creation.

### `related_tasks`

Explicitly assigned Task titles.

Tasks remain title-based because the existing `Task` model is intentionally unchanged.

---

# 4. Goal Model Changes

## 4.1 Goal.projects

`Goal` gains:

```python
projects: list[Project] = field(default_factory=list)
```

The domain model should expose actual `Project` objects rather than raw dictionaries.

The persistence layer may use dictionaries internally if required by the Markdown serializer, but that representation must not leak into the domain model.

This keeps:

```text
Domain model
    Goal.projects → list[Project]

Persistence
    Markdown ↔ dictionaries / serialized fields
```

separate.

---

## 4.2 Goal Model

Conceptually:

```python
@dataclass
class Goal:
    title: str
    ...
    milestones: list[dict]
    related_tasks: list[str]
    projects: list[Project] = field(default_factory=list)
```

The existing milestone representation is retained for compatibility with the current implementation.

Projects are the first hierarchy level that should use a proper domain object.

---

# 5. Persistence Format

## 5.1 goals.md — Projects Section

Projects are stored at the Goal level but reference their parent Milestone.

Recommended format:

```markdown
## Goal: Build a personal website
Status: active
Deadline: 2026-11-30
Related tasks:
- Design homepage mockup
- Buy domain name

## Milestone: MVP launch
Description: Minimum viable website.
Deadline: 2026-10-31
Status: in_progress
Order: 0

## Milestone: Polish
Description: Refine design and add content.
Deadline: 2026-11-30
Status: open
Order: 1

## Projects

### Homepage
Milestone: MVP launch
Order: 0
Deadline: 2026-10-15
Status: active
Description: First-version homepage with about and contact.
Related tasks:
- Design homepage mockup
- Buy domain name

### Blog
Milestone: MVP launch
Order: 1
Deadline: 2026-10-25
Status: open
Related tasks:
- Write first three posts
```

This is preferred over encoding parent metadata in the heading:

```text
### Project: Homepage (milestone: MVP launch, order: 0)
```

because individual fields are easier to parse, validate, and extend.

---

## 5.2 Parsing Rules

`markdown_goals.py` must:

1. Detect the `## Projects` section.
2. Detect each `### <project title>` block.
3. Parse:

   * `Milestone`
   * `Order`
   * `Deadline`
   * `Status`
   * `Description`
   * `Related tasks`
4. Ignore unknown fields.
5. Validate that `Milestone` is present.
6. Validate that the referenced Milestone exists.
7. Validate Project status.
8. Construct `Project` domain objects.
9. Store them in `Goal.projects`.

A Project without a parent Milestone must be rejected with a clear error.

---

## 5.3 Backward Compatibility

Goals without a `## Projects` section parse as:

```python
projects=[]
```

Existing goals therefore retain exactly their current behavior.

The presence of Projects opts the Goal into Project-aware task assignment.

---

# 6. Project Task Assignment

## 6.1 Canonical Assignment Rules

There are two layers:

### Layer 1 — Goal inventory

```text
Goal.related_tasks
```

contains the tasks associated with the Goal.

### Layer 2 — Project assignment

```text
Project.related_tasks
```

explicitly assigns tasks to Projects.

The assignment relationship is therefore:

```text
Goal.related_tasks
        │
        ├── assigned to Project A
        │
        ├── assigned to Project B
        │
        └── unassigned
                 │
                 └── legacy dynamic derivation
```

---

## 6.2 Assignment Precedence

Given:

```text
Goal.related_tasks:
- A
- B
- C

Project X:
- A

Project Y:
- B
```

then:

```text
A → Project X
B → Project Y
C → dynamic derivation
```

Project assignment always wins.

---

## 6.3 Duplicate Project Assignment

The following is invalid:

```text
Project X:
- Task A

Project Y:
- Task A
```

The service layer must reject this with a clear error.

This guarantees deterministic next-action derivation.

---

## 6.4 Missing Goal Task Reference

If:

```text
Project X:
- Task A
```

but:

```text
Task A
```

is not currently in `Goal.related_tasks`, the service should issue a warning rather than fail.

Rationale:

* the Task may be added to the Goal shortly afterward;
* strict rejection would make gradual adoption unnecessarily difficult.

However, the task cannot belong to another Goal.

---

# 7. Project Status Lifecycle

## 7.1 Statuses

Projects use:

| Status      | Meaning                   |
| ----------- | ------------------------- |
| `open`      | Not yet started           |
| `active`    | Currently being worked on |
| `blocked`   | Cannot currently proceed  |
| `completed` | Successfully completed    |
| `skipped`   | Intentionally abandoned   |

---

## 7.2 Lifecycle

```text
                 ┌─────────────┐
                 │             ▼
open ─────────► active ─────► completed
 │                 │
 │                 ▼
 │              blocked
 │                 │
 │                 └──────► open
 │
 └──────────────► skipped
```

Valid transitions:

```text
open → active
open → skipped
open → blocked

active → completed
active → skipped
active → blocked

blocked → open
blocked → active

completed → open
skipped → open
```

Reopening a terminal Project should be explicit.

---

## 7.3 No Implicit Auto-Activation in MVP

When a Milestone becomes `in_progress`, Projects are **not automatically mutated**.

For example:

```text
Milestone → in_progress
Project → open
```

is a valid state.

`next_action` may select the first eligible Project without mutating its status.

This keeps state changes explicit and avoids hidden side effects.

Automatic Project activation can be introduced later as an explicit policy.

---

# 8. Milestone Lifecycle

Before implementing Project auto-advance, the existing milestone lifecycle services should be completed.

The following functions from ADR-003 should be implemented:

```python
start_milestone(...)
skip_milestone(...)
reopen_milestone(...)
```

These should be treated as a prerequisite for any future automatic Project lifecycle behavior.

Project implementation must not introduce implicit Milestone mutations.

---

# 9. Next-Action Derivation

## 9.1 Design Goal

The next-action engine should remain deterministic and understandable.

Rather than introducing a large set of independent policy rules, it should perform hierarchical traversal:

```text
Goal
 ↓
Current Milestone
 ↓
Current Project
 ↓
Open Task
```

The legacy dynamic task derivation remains an assignment mechanism, not a separate competing policy engine.

---

## 9.2 Existing Interface

The public signature remains:

```python
def derive_next_action(
    goal,
    tasks,
    completed_task_titles,
    today,
    projects=None,
) -> NextAction | None
```

When `projects` is absent or empty, the existing R1–R5 behavior remains unchanged.

---

## 9.3 Project-Aware Algorithm

### Step 1 — Determine Current Milestone

Use the existing milestone selection logic.

The current Milestone is:

```text
first milestone whose status is:
open | in_progress
```

according to existing ordering rules.

---

### Step 2 — Determine Current Project

For the current Milestone:

1. Find Projects belonging to the Milestone.
2. Exclude:

   * `completed`
   * `skipped`
3. Order remaining Projects by `order`.
4. Select the first eligible Project.

`blocked` Projects are not actionable as task containers but remain visible as Project state.

---

### Step 3 — Find an Open Task

For the selected Project:

```text
Project.related_tasks
```

is traversed in stored order.

The first task that is not completed is returned:

```text
NextAction(
    kind="task",
    title=task.title,
    reason="Open task in project X within milestone Y"
)
```

---

### Step 4 — Project Without Open Tasks

If the selected Project has no open tasks:

```text
NextAction(
    kind="project",
    title=project.title,
    reason="Project has no open tasks"
)
```

This makes the Project itself the next actionable unit.

---

### Step 5 — Current Milestone Without Eligible Project

If the current Milestone has no active/open Project:

use legacy dynamic derivation to find unassigned Goal tasks associated with that Milestone.

If an open task exists:

```text
NextAction(
    kind="task",
    ...
)
```

---

### Step 6 — Next Milestone

If the current Milestone has no actionable Project or dynamic task:

1. Find the next non-terminal Milestone.
2. If it has an eligible Project, return the first Project.
3. Otherwise return the Milestone itself.

---

### Step 7 — No Next Action

If:

```text
all milestones = completed/skipped
and
all related tasks = completed
```

return:

```python
None
```

---

# 10. Project-Aware Rules

The resulting policy can be summarized as:

| Priority | Condition                                                | Result    |
| -------- | -------------------------------------------------------- | --------- |
| P1       | Current Project has an open Task                         | Task      |
| P2       | Current Milestone has unassigned open Task               | Task      |
| P3       | Current Project has no open Tasks                        | Project   |
| P4       | Next Milestone has an eligible Project                   | Project   |
| P5       | Next Milestone has an unassigned open Task               | Task      |
| P6       | Next Milestone exists but has no actionable Project/Task | Milestone |
| P7       | Nothing actionable remains                               | None      |

The exact ordering should be implemented as a deterministic traversal rather than seven unrelated branches.

---

# 11. Dynamic Derivation

Existing functions:

```python
derive_milestone_tasks(...)
derive_milestone_task_set(...)
```

are extended to understand Project assignment.

Conceptually:

```python
assigned_project_tasks = {
    task
    for project in goal.projects
    for task in project.related_tasks
}
```

Then:

```text
if task in assigned_project_tasks:
    explicit Project assignment wins

else:
    legacy dynamic milestone derivation applies
```

This preserves backward compatibility while allowing gradual migration.

---

# 12. Project CRUD Service

**New file:**

```text
src/janus/services/projects.py
```

Proposed API:

```python
def add_project_for_milestone(
    goal_title: str,
    milestone_title: str,
    title: str,
    description: str = "",
    deadline: str | None = None,
    status: str = "open",
    related_tasks: list[str] | None = None,
) -> Project: ...


def get_projects_for_milestone(
    goal_title: str,
    milestone_title: str,
) -> list[Project]: ...


def get_projects_for_goal(
    goal_title: str,
) -> list[Project]: ...


def get_project(
    goal_title: str,
    milestone_title: str,
    project_title: str,
) -> Project: ...


def update_project(
    goal_title: str,
    milestone_title: str,
    project_title: str,
    **kwargs,
) -> Project: ...


def complete_project(
    goal_title: str,
    milestone_title: str,
    project_title: str,
) -> Project: ...


def skip_project(
    goal_title: str,
    milestone_title: str,
    project_title: str,
) -> Project: ...


def block_project(
    goal_title: str,
    milestone_title: str,
    project_title: str,
) -> Project: ...


def reopen_project(
    goal_title: str,
    milestone_title: str,
    project_title: str,
) -> Project: ...
```

---

## 12.1 Service Responsibilities

The service layer must:

* validate Goal existence;
* validate Milestone existence;
* validate Project uniqueness within Milestone;
* validate Project status;
* validate Project task assignment;
* reject duplicate Task assignment;
* warn about missing Goal task references;
* reject cross-goal task references;
* auto-assign Project order;
* preserve Project order during updates;
* persist through the existing Goal persistence path.

---

## 12.2 Project Order

When adding a Project:

```text
order = max(existing orders in milestone) + 1
```

If no Projects exist:

```text
order = 0
```

Order is not renumbered when a Project is skipped or deleted.

---

# 13. CLI Exposure

The CLI should follow the existing Milestone command structure.

```text
janus goal project add <goal> <milestone> <title>
    [--description D]
    [--deadline D]
    [--status S]
    [--add-related-task T]
```

```text
janus goal project list <goal>
    [<milestone>]
    [--status S]
```

```text
janus goal project show <goal> <milestone> <project>
```

```text
janus goal project update <goal> <milestone> <project>
    [--description D]
    [--deadline D]
    [--status S]
    [--add-related-task T]
    [--remove-related-task T]
```

```text
janus goal project start <goal> <milestone> <project>
```

```text
janus goal project complete <goal> <milestone> <project>
```

```text
janus goal project skip <goal> <milestone> <project>
```

```text
janus goal project block <goal> <milestone> <project>
```

```text
janus goal project reopen <goal> <milestone> <project>
```

`janus goal next <title>` remains unchanged at the interface level.

---

# 14. Milestone CLI Lifecycle

As part of stabilizing the dependency for future Project lifecycle automation:

```text
janus goal milestone start <goal> <milestone>
janus goal milestone skip <goal> <milestone>
janus goal milestone reopen <goal> <milestone>
```

should map to the corresponding service functions.

This is not Project functionality, but is considered prerequisite lifecycle infrastructure.

---

# 15. Weekly Review

## 15.1 ProjectProgress

Add:

```python
@dataclass
class ProjectProgress:
    project_title: str
    milestone_title: str
    status: str
    completed_tasks: int
    total_tasks: int
```

`completed_tasks` and `total_tasks` are derived from:

```text
Project.related_tasks
```

and the existing Task completion model.

---

## 15.2 GoalReview

Extend:

```python
@dataclass
class GoalReview:
    ...
    projects: list[ProjectProgress] = field(default_factory=list)
```

---

## 15.3 Separation of Responsibilities

Weekly review must not independently implement Project traversal logic.

Project progress should be computed by a dedicated helper/service, for example:

```python
compute_project_progress(project, tasks)
```

The weekly review consumes the resulting `ProjectProgress`.

This avoids duplicating task/project semantics in multiple services.

---

# 16. Attention Engine

No new attention signal types are required for the initial implementation.

Existing signals remain authoritative:

```text
goal_overdue
goal_deadline_today
milestone_slipped
goal_stalled
goal_inactive
no_recent_activity
```

Project information may contribute indirectly through existing goal/milestone state.

---

## 16.1 Deferred Project Signal

A future:

```text
project_slipped
```

signal may be introduced.

Suggested score:

```text
45
```

This would sit between existing milestone/goal attention levels.

It is explicitly out of scope for this implementation.

---

# 17. Goal Progress

`compute_goal_progress` remains unchanged.

Projects are an **organizational and sequencing layer**, not a measurement layer.

Therefore:

```text
Goal progress
    ↓
existing metric/task logic

Project progress
    ↓
completed Project tasks / total Project tasks
```

These concepts remain separate.

---

# 18. Daily Briefing

No direct changes are required.

The daily briefing continues consuming:

```text
AttentionItem
suggested_focus
```

from existing services.

Project deadlines may eventually influence attention through milestone/goal signals, but no new briefing-specific Project logic is required.

---

# 19. Data Model Changes Summary

## 19.1 New Entity

| Entity    | File                          | Fields                                                                      |
| --------- | ----------------------------- | --------------------------------------------------------------------------- |
| `Project` | `src/janus/models/project.py` | title, milestone_title, description, deadline, status, order, related_tasks |

---

## 19.2 Modified Entities

| Entity       | File                                | Change                                |
| ------------ | ----------------------------------- | ------------------------------------- |
| `Goal`       | `src/janus/models/goal.py`          | Add `projects: list[Project]`         |
| `GoalReview` | `src/janus/models/weekly_review.py` | Add `projects: list[ProjectProgress]` |
| `NextAction` | `src/janus/services/next_action.py` | No structural change                  |

---

## 19.3 New Service Layer

| Module           | File                                     | Purpose                              |
| ---------------- | ---------------------------------------- | ------------------------------------ |
| Project CRUD     | `src/janus/services/projects.py`         | Project lifecycle and assignment     |
| Project progress | `src/janus/services/project_progress.py` | Project task completion calculations |

---

## 19.4 Persistence

| Function             | File                                       | Change             |
| -------------------- | ------------------------------------------ | ------------------ |
| `_format_goal_block` | `src/janus/integrations/markdown_goals.py` | Serialize Projects |
| `load_goals`         | `src/janus/integrations/markdown_goals.py` | Parse Projects     |

---

## 19.5 CLI

| Handler               | File                     |
| --------------------- | ------------------------ |
| `handle_goal_project` | `src/janus/goals_cli.py` |

---

# 20. Migration & Compatibility

## 20.1 Schema Migration

No migration is required.

Existing goals:

```text
projects=[]
```

and continue using the existing R1–R5 logic.

---

## 20.2 Data Migration

Existing:

```text
data/goals.md
```

files remain valid.

No automatic conversion of existing milestone task assignments is performed.

---

## 20.3 Gradual Adoption

Projects can be introduced one at a time.

Example:

```text
Goal
├── Milestone A
│   └── Project A
│       ├── Task 1
│       └── Task 2
│
└── Milestone B
    └── legacy dynamic tasks
```

This is valid.

There is no requirement to migrate all existing tasks to Projects at once.

---

# 21. Gaps & Risks

## 21.1 Task Completion Timestamps

Task completion timestamps are not currently recorded.

This limits:

```text
progress_slow
days_since_last_activity
```

for task-based goals.

This is a pre-existing limitation and is not introduced by Projects.

---

## 21.2 Milestone Lifecycle Infrastructure

ADR-003 specifies:

```text
start_milestone
skip_milestone
reopen_milestone
```

but these were not implemented in the current base state.

This should be addressed before implementing Project auto-advance.

---

## 21.3 Persistence Rewrite

`update_goal()` rewrites the complete Goal block.

If Projects are not included in `_format_goal_block`, they will be lost.

This is a high-impact persistence risk.

Mandatory mitigation:

```text
save → load → update → save → load
```

round-trip tests.

---

## 21.4 Parent Immutability

Project parent references are title-based.

Therefore Project/Milestone parent titles must remain immutable in the MVP.

Rename/move support should be a separate feature.

---

## 21.5 Mixed Assignment Semantics

The combination of:

```text
Goal.related_tasks
Project.related_tasks
dynamic milestone derivation
```

could produce confusing behavior if precedence is not enforced.

The normative rule is:

```text
explicit Project assignment
        >
dynamic derivation
```

and a Task can belong to only one Project within a Goal.

---

## 21.6 Blocked State

`blocked` is Project-specific and must not be interpreted as a Milestone state.

A blocked Project does not imply:

```text
Milestone = blocked
```

A Milestone may remain:

```text
in_progress
```

while one of its Projects is blocked.

---

# 22. Risks

| Risk                                     | Likelihood | Impact | Mitigation                                                    |
| ---------------------------------------- | ---------: | -----: | ------------------------------------------------------------- |
| `update_goal` loses Projects             |     Medium |   High | Round-trip persistence tests                                  |
| Project parent inconsistency             |        Low |   High | Immutable parent references + service validation              |
| Duplicate Task assignment                |     Medium |   High | Domain invariant + service validation                         |
| Dynamic/project precedence confusion     |     Medium | Medium | Explicit precedence rules + tests                             |
| Blocked Project becomes stuck            |     Medium | Medium | `blocked → open/active` transitions                           |
| Next-action logic becomes overly complex |     Medium |   High | Hierarchical traversal instead of independent policy branches |
| Weekly review duplicates Project logic   |     Medium | Medium | Dedicated project progress service                            |
| Too many CLI commands                    |        Low | Medium | Mirror existing Milestone patterns                            |
| Hidden state mutations                   |     Medium | Medium | No automatic Project activation in MVP                        |

---

# 23. Acceptance Criteria

## 23.1 Project Model

* [ ] `Project` dataclass exists.
* [ ] Fields:

  * [ ] `title`
  * [ ] `milestone_title`
  * [ ] `description`
  * [ ] `deadline`
  * [ ] `status`
  * [ ] `order`
  * [ ] `related_tasks`
* [ ] Project validates status.
* [ ] Project validates non-empty title.
* [ ] Project does not duplicate `goal_title`.
* [ ] Project status `blocked` is non-terminal.
* [ ] Project task list is deduplicated.

---

## 23.2 Domain Invariants

* [ ] Project must belong to an existing Milestone.
* [ ] Project title is unique within Milestone.
* [ ] A Task cannot belong to two Projects within one Goal.
* [ ] Project cannot reference a Task from another Goal.
* [ ] Project assignment overrides dynamic derivation.
* [ ] Unassigned Goal tasks retain dynamic derivation.
* [ ] Project order is stable.

---

## 23.3 Persistence

* [ ] `goals.md` parses `## Projects`.
* [ ] Project blocks are parsed into `Project` objects.
* [ ] Missing Projects section produces `projects=[]`.
* [ ] Projects are serialized by `_format_goal_block`.
* [ ] `update_goal()` preserves Projects.
* [ ] Unknown Project fields are ignored.
* [ ] Missing Milestone reference is rejected.
* [ ] Invalid Project status is rejected.
* [ ] Project persistence round-trip is tested.

---

## 23.4 Project CRUD

* [ ] `add_project_for_milestone()` works.
* [ ] Project order is auto-assigned.
* [ ] `get_projects_for_milestone()` works.
* [ ] `get_projects_for_goal()` works.
* [ ] `get_project()` works.
* [ ] `update_project()` works.
* [ ] `--add-related-task` works.
* [ ] `--remove-related-task` works.
* [ ] `complete_project()` works.
* [ ] `skip_project()` works.
* [ ] `block_project()` works.
* [ ] `reopen_project()` works.
* [ ] Duplicate Project title is rejected.
* [ ] Duplicate Task assignment is rejected.
* [ ] Invalid parent references are rejected.

---

## 23.5 Next Action

* [ ] Existing goals without Projects use R1–R5 unchanged.
* [ ] Current Project open Task is returned first.
* [ ] Project task ordering is respected.
* [ ] Project assignment overrides dynamic assignment.
* [ ] Unassigned Goal tasks retain legacy behavior.
* [ ] Project with no open Tasks can be returned as a Project action.
* [ ] Next Milestone Project can be returned.
* [ ] Next Milestone can be returned when it has no actionable Project/Task.
* [ ] `None` is returned when no action remains.
* [ ] `reason` contains Project context when applicable.
* [ ] Existing `goal next` behavior does not regress for non-Project goals.

---

## 23.6 Weekly Review

* [ ] `ProjectProgress` exists.
* [ ] Project progress reports completed/total Tasks.
* [ ] `GoalReview.projects` exists.
* [ ] Project progress is computed outside `weekly_review.py`.
* [ ] Weekly review renders Project progress.
* [ ] Existing weekly review output remains valid for goals without Projects.

---

## 23.7 CLI

* [ ] `goal project add`
* [ ] `goal project list`
* [ ] `goal project show`
* [ ] `goal project update`
* [ ] `goal project start`
* [ ] `goal project complete`
* [ ] `goal project skip`
* [ ] `goal project block`
* [ ] `goal project reopen`
* [ ] `goal project list --status`
* [ ] `goal next <title>` exposes Project-aware context.
* [ ] Existing `goal milestone *` behavior remains compatible.

---

# 24. Deferred

The following are explicitly outside the MVP implementation:

* [ ] Automatic Project activation when a Milestone starts.
* [ ] Automatic Project skipping when a Milestone completes/skips.
* [ ] Automatic lifecycle propagation between Milestone and Project.
* [ ] `project_slipped` attention signal.
* [ ] Calendar write-back for Project deadlines.
* [ ] Cross-domain progress such as workouts → Project progress.
* [ ] Project back-reference stored on Task.
* [ ] Stable Project IDs replacing title references.
* [ ] Project movement between Milestones.
* [ ] Milestone/Goal rename propagation.
* [ ] Automatic migration of legacy task assignments into Projects.

---

# 25. Recommended Implementation Sequence

The implementation should proceed in the following order.

## Phase 1 — Stabilize Milestone Lifecycle

Implement:

```text
start_milestone
skip_milestone
reopen_milestone
```

and corresponding CLI commands.

Do not introduce Project behavior yet.

---

## Phase 2 — Project Domain Model

Implement:

```text
Project
Goal.projects
```

plus domain validation and invariants.

---

## Phase 3 — Project Persistence

Implement Markdown parsing and serialization.

Add round-trip tests before continuing.

---

## Phase 4 — Project CRUD

Implement:

```text
add
get
list
update
complete
skip
block
reopen
```

and enforce all domain invariants.

---

## Phase 5 — Project Task Assignment

Implement:

```text
Project.related_tasks
```

and precedence over dynamic derivation.

Add tests for:

```text
explicit assignment
duplicate assignment
unassigned task
mixed legacy/project goals
cross-goal references
```

---

## Phase 6 — Next Action

Extend `derive_next_action()`.

Keep the implementation hierarchical:

```text
Goal
 ↓
Milestone
 ↓
Project
 ↓
Task
```

Avoid creating an independent branch for every policy rule.

---

## Phase 7 — Project Progress

Implement:

```text
compute_project_progress(...)
```

and integrate it with Weekly Review.

---

## Phase 8 — CLI Integration

Implement:

```text
goal project *
```

and ensure existing CLI commands continue working.

---

## Phase 9 — Regression Suite

Run:

```text
all existing tests
+
new Project tests
```

No regressions are acceptable for goals without Projects.

---

# 26. Key Design Decisions

## D1 — Project is a domain entity

`Project` is represented as a proper domain object.

Persistence may use dictionaries internally, but `Goal.projects` exposes:

```python
list[Project]
```

This keeps persistence representation separate from domain representation.

---

## D2 — Project belongs to a Milestone, not directly to a Goal

The Project stores:

```text
milestone_title
```

but not:

```text
goal_title
```

The Goal is obtained through the parent Milestone context.

This eliminates redundant parent references.

---

## D3 — Goal.related_tasks remains canonical

`Goal.related_tasks` remains the master inventory of Goal-associated Tasks.

Project assignment adds execution structure without replacing the inventory.

---

## D4 — Explicit Project assignment overrides dynamic derivation

The precedence is:

```text
Project assignment
        >
legacy dynamic milestone derivation
```

This enables gradual adoption without breaking existing goals.

---

## D5 — A Task belongs to at most one Project per Goal

This is required for deterministic execution planning.

If a Task needs to support multiple Projects in the future, that should be introduced as an explicit dependency/relationship model rather than allowing ambiguous ownership.

---

## D6 — `blocked` is non-terminal

A Project can transition:

```text
active → blocked → active
```

without being considered completed or skipped.

---

## D7 — No automatic Project mutation in MVP

Starting a Milestone does not automatically mutate Project state.

This avoids hidden side effects and keeps lifecycle state explicit.

Automatic Project lifecycle propagation may be introduced later.

---

## D8 — `next_action` is hierarchical traversal

The engine should conceptually traverse:

```text
Goal
 ↓
Current Milestone
 ↓
Current Project
 ↓
Open Task
```

rather than implementing a large collection of independent P-rules.

---

## D9 — Existing R1–R5 remain the compatibility path

A Goal with no Projects must behave exactly as before.

Project-aware behavior is opt-in through the existence of Project assignments.

---

## D10 — Project order is stable

Project order is assigned at creation and is not renumbered automatically.

---

## D11 — Parent references are immutable in MVP

Project movement and parent renaming are separate future features.

---

## D12 — Progress and execution remain separate concerns

Projects organize and sequence work.

They do not replace the existing Goal progress/metric system.

---

# 27. Open Questions

## Q1 — Should stable Project IDs be introduced?

**Recommendation:** not required for MVP.

Title-based references remain consistent with the existing Janus architecture.

However, Project IDs should be considered before Project relationships become more complex.

---

## Q2 — Should Goal.related_tasks eventually be deprecated?

**Recommendation:** no.

It remains the canonical Goal task inventory and supports legacy/dynamic execution for tasks that have not yet been assigned to Projects.

---

## Q3 — Should Project tasks be required to exist in Goal.related_tasks?

**Recommendation:** no hard requirement.

Warn if a Project references a task not currently present in the Goal inventory, but do not block the operation.

Cross-goal references remain hard errors.

---

## Q4 — Should `goal project list` support status filtering?

**Recommendation:** yes.

```text
janus goal project list <goal> --status blocked
```

is useful for operational workflows.

---

## Q5 — Should Project deadlines write to Calendar?

**Recommendation:** no.

Projects follow the same principle as Goals/Milestones:

```text
deadline
    ↓
attention/context
```

rather than automatic calendar mutation.

---

## Q6 — Should Project auto-advance be implemented later?

**Recommendation:** yes, but only after Milestone lifecycle transitions are stable.

Potential future behavior:

```text
Milestone → in_progress
    ↓
first eligible Project → active
```

and:

```text
Milestone → completed/skipped
    ↓
remaining Projects → skipped
```

This should be a separate, explicit lifecycle policy.

---

## Q7 — Should blocked Projects affect Milestone state?

**Recommendation:** not automatically.

A Milestone can contain:

```text
Project A → completed
Project B → blocked
Project C → open
```

without changing Milestone status automatically.

Future attention logic may surface the blocked Project.

---

# 28. Final Architecture

The resulting architecture is:

```text
                        Goal
                         │
             ┌───────────┴───────────┐
             │                       │
        Milestones             related_tasks
             │                       │
             │                canonical inventory
             │
          Projects
             │
       explicit assignment
             │
           Tasks
```

Execution planning becomes:

```text
Goal
 │
 ▼
Current Milestone
 │
 ├── Current Project
 │      │
 │      └── Open Task
 │
 └── Unassigned Goal Tasks
        │
        └── Legacy dynamic derivation
```

The core invariant is:

```text
explicit Project assignment
        >
legacy dynamic derivation
```

while:

```text
Goal.related_tasks
```

remains the canonical task inventory.

This gives Janus a four-level execution hierarchy without requiring a breaking migration of existing goals.

---

*End of design spec.*
