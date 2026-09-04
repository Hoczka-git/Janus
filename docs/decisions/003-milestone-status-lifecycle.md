# ADR-003: Milestone Status Lifecycle and State Transitions

## Status

Accepted

---

# Context

The original design left several questions open around milestone lifecycle,
ordering, shared tasks, deadline precedence, and next-action output. This ADR
resolves those questions and documents the intended state-transition and
planning model for Janus.

---

# Decision

## 1. Milestone Status Values

**Decision:** Keep all four states:

`open | in_progress | completed | skipped`

**Rationale:**

* `in_progress` is useful for sequencing and user-facing context. It marks the milestone currently being worked on.
* `skipped` is needed to model milestones that were intentionally abandoned and should no longer participate in active planning.
* `completed` and `skipped` are terminal states for planning purposes.
* Validation prevents invalid status values from entering the domain model.

The four states therefore represent:

* `open` — available for execution but not currently active.
* `in_progress` — currently active.
* `completed` — successfully finished.
* `skipped` — intentionally abandoned and excluded from active planning.

---

## 2. Valid State Transitions

The lifecycle is a finite state machine. Not all state changes are valid.

### Transition Table

| From          | To            | Allowed? | Trigger                   | Notes                          |
| ------------- | ------------- | -------- | ------------------------- | ------------------------------ |
| `open`        | `in_progress` | Yes      | `start_milestone(...)`    | Start working on the milestone |
| `open`        | `completed`   | Yes      | `complete_milestone(...)` | Manual completion              |
| `open`        | `skipped`     | Yes      | `skip_milestone(...)`     | Milestone no longer applies    |
| `in_progress` | `completed`   | Yes      | `complete_milestone(...)` | Normal completion              |
| `in_progress` | `skipped`     | Yes      | `skip_milestone(...)`     | Abandoning an active milestone |
| `in_progress` | `open`        | Yes      | `reopen_milestone(...)`   | Return to open state           |
| `completed`   | `open`        | Yes      | `reopen_milestone(...)`   | Correct a mistaken completion  |
| `skipped`     | `open`        | Yes      | `reopen_milestone(...)`   | Re-enable a skipped milestone  |
| `completed`   | `skipped`     | No       | —                         | Must reopen first              |
| `skipped`     | `completed`   | No       | —                         | Must reopen first              |
| `skipped`     | `in_progress` | No       | —                         | Must reopen first              |
| `completed`   | `in_progress` | No       | —                         | Must reopen first              |

### Transition Rules

1. The only way to leave `completed` or `skipped` is through `open`.
2. `in_progress` can only be reached from `open`.
3. Direct transitions between `completed` and `skipped` are not allowed.
4. Once a milestone reaches `completed` or `skipped`, it is excluded from next-action derivation and active planning.
5. Reopening a terminal milestone returns it to `open`; it must then be explicitly started before becoming `in_progress`.

### Triggers

| Transition                  | Method               | Source        |
| --------------------------- | -------------------- | ------------- |
| `open` → `in_progress`      | `start_milestone`    | CLI / service |
| `open` → `completed`        | `complete_milestone` | CLI / service |
| `open` → `skipped`          | `skip_milestone`     | CLI / service |
| `in_progress` → `completed` | `complete_milestone` | CLI / service |
| `in_progress` → `skipped`   | `skip_milestone`     | CLI / service |
| `in_progress` → `open`      | `reopen_milestone`   | CLI / service |
| `completed` → `open`        | `reopen_milestone`   | CLI / service |
| `skipped` → `open`          | `reopen_milestone`   | CLI / service |

---

## 3. How Status Affects Goal Execution Planning

### Next-Action Derivation

Milestone status determines which milestones participate in next-action derivation.

The current milestone is the **first milestone by `order` whose status is `open` or `in_progress`**.

Milestones with status `completed` or `skipped` are excluded.

Therefore:

* `open` milestones are eligible for planning.
* `in_progress` milestones remain the active planning target.
* `completed` milestones are ignored.
* `skipped` milestones are ignored.

The engine advances through milestone order until it finds the first non-terminal milestone.

### Shared Tasks

A task may be associated with more than one milestone.

Task-to-milestone membership is derived **dynamically at execution time**, rather than stored as a permanent assignment.

When a task belongs to multiple milestones, it is associated with the earliest milestone by `order` that is still non-terminal (`open` or `in_progress`).

As earlier milestones become `completed` or `skipped`, the same task may become eligible through the next non-terminal milestone that references it.

This makes shared-task planning stateless and avoids permanently assigning a task to one milestone when its planning context can change.

### Skipped Milestones

A skipped milestone is treated as terminal for planning purposes.

The next-action engine:

* does not return the skipped milestone itself;
* does not return tasks exclusively belonging to the skipped milestone;
* advances to the next non-terminal milestone.

### In-Progress Milestones

An `in_progress` milestone remains the current planning target.

Its status provides explicit user-facing context about the active milestone, while next-action derivation continues to select actionable open tasks within it.

---

## 4. Milestone Ordering

Milestones have an `order` field defining their position within a goal.

Order values are assigned when milestones are created.

When a milestone is skipped or removed, existing milestone order values are **not renumbered**.

This preserves stable milestone identity and avoids rewriting the ordering of historical milestones.

The next-action engine uses the existing order values to determine which non-terminal milestone is currently eligible.

---

## 5. Stall Detection

Milestone status also affects stall detection.

### `milestone_slipped`

A `milestone_slipped` signal is generated when:

* the milestone has a deadline;
* the deadline is before today;
* the milestone is not `completed`;
* the milestone is not `skipped`.

Therefore:

* `open` + past deadline → `milestone_slipped`
* `in_progress` + past deadline → `milestone_slipped`
* `completed` + past deadline → no milestone slip
* `skipped` + past deadline → no milestone slip

A skipped milestone does not represent an active obligation and therefore should not generate a deadline-slip signal.

### `milestone_deadline_soon`

A `milestone_deadline_soon` signal is generated when:

* the milestone has a future deadline;
* the deadline is within seven days;
* the milestone is neither `completed` nor `skipped`.

The signal provides an early-warning attention item before a milestone becomes overdue.

---

## 6. Goal Deadline vs. Milestone Deadline Precedence

**Decision:** Goal-level deadline signals take precedence over milestone deadline signals.

Goal-level deadline signals include:

* `goal_overdue`
* `goal_deadline_today`
* `goal_deadline_soon`

Milestone-level deadline signals include:

* `milestone_slipped`
* `milestone_deadline_soon`

When a goal-level deadline signal fires, milestone deadline signals are **suppressed for that goal**.

This establishes a clear hierarchy:

```text
Goal deadline
     ↓
authoritative deadline context
     ↓
Milestone deadline
     ↓
subordinate planning signal
```

The purpose is to avoid competing deadline signals for the same goal.

If no goal-level deadline signal fires, an applicable milestone deadline signal may be emitted.

This means the attention engine treats the goal deadline as the primary deadline context while still using milestone deadlines when no stronger goal-level deadline signal is active.

---

## 7. Status-Related Fields on the Milestone Model

The milestone model contains the following relevant fields:

| Field         | Type          | Behavior                                      |
| ------------- | ------------- | --------------------------------------------- |
| `title`       | `str`         | Milestone identity; must be non-empty         |
| `goal_title`  | `str`         | Parent goal reference                         |
| `description` | `str`         | Human-readable milestone description          |
| `deadline`    | `str \| None` | Optional ISO date used by deadline signals    |
| `status`      | `str`         | `open \| in_progress \| completed \| skipped` |
| `order`       | `int`         | Stable milestone ordering                     |

### Task Relationships

Task-to-milestone relationships are not treated as a permanent assignment for planning.

Where milestone/task relationship data is present for compatibility with persisted or legacy data, the execution engine derives the effective milestone membership dynamically from the current goal, milestone, and task state.

The derived relationship is therefore the authoritative input for next-action planning.

---

## 8. Persistence

Milestone status is persisted with the milestone.

The persistence layer serializes the milestone status and restores it when loading the goal.

When older persisted milestone data does not contain an explicit status, the default status is `open`.

This provides backward compatibility with milestones created before the status lifecycle was introduced.

---

## 9. Resolving the Original Open Questions

### Q1: Milestone status values — keep `in_progress`?

**Resolved: Yes.**

Keep:

`open | in_progress | completed | skipped`

`in_progress` provides explicit active-state information without requiring the planning engine to infer the current milestone solely from task or deadline state.

---

### Q2: Milestone `order` gaps?

**Resolved: No renumbering.**

Orders are assigned when milestones are created and remain stable.

Skipping or removing a milestone does not cause later milestones to be renumbered.

---

### Q3: What happens when a task belongs to multiple milestones?

**Resolved: Dynamic derivation.**

The task is associated with the earliest non-terminal milestone at derivation time.

If that milestone becomes `completed` or `skipped`, the task can become eligible through the next non-terminal milestone that references it.

No permanent task-to-milestone assignment is required.

---

### Q4: Goal deadline vs. milestone deadline precedence?

**Resolved: Goal deadline takes precedence.**

When a goal-level deadline signal fires, milestone deadline signals for that goal are suppressed.

If no goal-level deadline signal fires, milestone deadline signals may be considered.

This prevents competing deadline attention signals and makes the goal deadline the authoritative deadline context.

---

### Q5: `goal next` output format?

**Resolved: Human-readable plain text with a reason.**

The `goal next` command returns a concise human-readable next-action recommendation together with the reason for that recommendation.

Machine-readable output such as JSON can be added as a future CLI extension if required by integrations.

---

# Consequences

* Milestone lifecycle has an explicit and validated four-state model.
* Terminal milestones (`completed` and `skipped`) are excluded from active planning.
* Milestone ordering remains stable over time.
* Shared task relationships can be resolved dynamically as milestone state changes.
* Milestone deadline signals do not compete with an already-fired goal deadline signal.
* The attention engine has a clear deadline hierarchy.
* Persisted milestone state remains backward-compatible with older data.
* The next-action engine can respond to milestone state changes without maintaining permanent task-to-milestone assignments.
* Future changes to milestone status semantics must update both the domain model and the next-action/stall-detection logic.

---

# References

* `DESIGN_EXECUTION_PLANNING.md` — Goal Execution Planning design specification.
* `docs/goal_milestone_research_findings.md` — research into the existing Goal/Milestone/Task model.
* `docs/decisions/001-hermes-janus-system-model.md` — Hermes/Janus layer separation.
* Dynamic milestone task derivation implementation and tests.
* Goal deadline precedence implementation and tests.
