# Goal Execution Planning — Design Spec

**Task:** t_53583dbf
**Based on:** Discovery report (t_c07c049d) — 6 prioritized gaps
**Status:** Draft for review

---

## 1. Executive Summary

The current Goal System tracks goals with metric or task-based progress, surfaces stalled goals in the attention engine (binary: all tasks done → stalled), and derives a single `suggested_next_step` in the weekly review. It has no milestones, no deadline→attention path, no task dependencies, no progress history, and no execution sequencing.

This spec defines an **execution planning extension** that adds:

1. **Milestones** — first-class children of goals with title, deadline, status, and related tasks.
2. **Next-action derivation** — extended from "first open task" to a rules-based engine that considers task ordering, dependencies, and milestone state.
3. **Graduated stall detection** — adds deadline proximity and days-since-activity signals on top of the existing binary check.
4. **Goal/calendar/task integration** — goal deadlines and milestone deadlines feed the attention engine; task due dates remain the unit of calendar surfacing.

Two lower-priority gaps from the discovery report (task dependencies, progress history) are *deferred* to follow-up tasks — they are listed as "future considerations" with the rationale.

---

## 2. Data Model

### 2.1 Milestone (new)

```python
# src/janus/models/milestone.py

@dataclass
class Milestone:
    title: str                              # identity within parent goal
    goal_title: str                         # foreign key (denormalized for markdown)
    description: str = ""
    deadline: str | None = None             # ISO date YYYY-MM-DD
    status: str = "open"                    # open | in_progress | completed | skipped
    related_tasks: list[str] = None         # task titles supporting this milestone
    order: int = 0                          # sequential position within goal (0-based)

    def __post_init__(self):
        if self.related_tasks is None:
            self.related_tasks = []
        self.related_tasks = self._dedup(self.related_tasks)
        if self.status not in ("open", "in_progress", "completed", "skipped"):
            raise ValueError(...)
        if not self.title or not self.title.strip():
            raise ValueError("Milestone title must not be empty")
```

**Design notes:**

- `goal_title` is denormalized (stored in the milestone block, not looked up at runtime) because persistence is markdown-based and goals can be renamed only via a future feature. For MVP, goal_title is immutable (same constraint as Goal.title).
- `order` is explicit so milestones render in a defined sequence. It is assigned at creation time (auto-increment within the parent goal's existing milestones).
- `related_tasks` follows the same dedup-on-init pattern as Goal.

### 2.2 Goal (extended)

Add one field to `Goal`:

```python
# src/janus/models/goal.py (diff)

@dataclass
class Goal:
    # ... existing fields ...
    related_tasks: list[str] = None

    # NEW — execution planning
    milestones: list[dict] = None   # persisted as list of milestone dicts;
                                     # NOT a list[Milestone] to avoid import cycle
                                     # and keep markdown serialization simple
```

**Why a list[dict] and not list[Milestone]:**

- The Goal dataclass is imported by markdown_goals.py, which would then need to import Milestone, which would need Goal (for `goal_title` validation) — a circular dependency.
- Milestones are serialized as nested blocks in `goals.md` (see §3), so the raw storage format is already dict-like.
- The service layer (`services/milestones.py`) constructs real `Milestone` objects from the dicts when needed.

**Alternative considered:** Store milestones in a separate `data/milestones.md`. Rejected because: (a) it splits a goal's data across files, making `goal show` and backups less coherent; (b) the denormalized `goal_title` on each milestone creates a consistency risk if goals are ever renamed; (c) the existing `update_goal` rewrite pattern already rewrites the entire goal block — adding a sub-block is a smaller change than a new file with its own rewrite logic.

### 2.3 Task (unchanged)

No changes to `Task`. Task dependencies (discovery rec #5) are deferred — they would require a `depends_on` field and a dependency graph, which is a separate concern from execution planning. The next-action engine in §4 works with the existing flat `related_tasks` list.

---

## 3. Persistence Format

### 3.1 goals.md — milestone sub-blocks

Each goal block gains an optional `## Milestones` section:

```markdown
## Goal: Complete autumn endurance challenge

Description: Complete a meaningful endurance event during autumn.
Status: active
Deadline: 2026-11-15

Related tasks:
- Prepare training plan
- Buy running shoes

## Milestones

### Milestone: Register for event  (order: 0)
Description: Sign up for a specific autumn race.
Deadline: 2026-09-30
Status: open
Related tasks:
- Buy running shoes

### Milestone: Reach 10km base  (order: 1)
Description: Run 10km continuously.
Deadline: 2026-10-31
Status: open
Related tasks:
- Prepare training plan
```

**Parsing rules (markdown_goals.py):**

- After parsing a `## Goal:` block, if the next section header is `## Milestones`, parse subsequent `### Milestone:` blocks as belonging to that goal.
- Each milestone block ends at the next `### Milestone:` or `## Goal:` or EOF.
- Unknown fields inside a milestone block are ignored (same tolerant parse as goals).
- `order` is explicit in the file; if missing, defaults to 0.

**Serialization (markdown_goals.py):**

- `_format_goal_block` gains a milestones section when `goal.milestones` is non-empty.
- `save_goal` appends the goal block + milestones section together.
- `update_goal` rewrites the goal block + milestones section together (same rewrite logic as today, just extended).

### 3.2 Backward compatibility

- Existing `goals.md` without `## Milestones` sections parses fine — `milestones` defaults to `[]` (or `None` → `[]`).
- New goals without milestones are written without the section.
- The rewrite in `update_goal` preserves the milestones section if present (it rewrites the whole block, so milestones are re-serialized from the in-memory dict list).

**Risk:** If `milestones` is not re-serialized correctly, existing milestone data could be lost on the first `update_goal` call. This is the same class of risk as the existing "unknown fields are lost on rewrite" behavior — acceptable for MVP, documented in the persistence contract.

---

## 4. Next-Action Derivation

### 4.1 Current behavior (baseline)

`weekly_review.py` derives `suggested_next_step` as: *first open task in `goal.related_tasks` order*. This is purely positional — it ignores deadlines, dependencies, and milestones.

### 4.2 New behavior — `derive_next_action(goal, context)` → `NextAction | None`

```python
# src/janus/services/next_action.py

@dataclass
class NextAction:
    title: str                     # task title or milestone title
    kind: str                      # "task" | "milestone"
    reason: str                    # human-readable explanation
    goal_title: str
    score: int                     # for attention-engine ranking (0 if not applicable)
```

**Inputs:**

- `goal: Goal` (with milestones loaded)
- `tasks: list[Task]` (open tasks)
- `completed_task_titles: set[str]`
- `today: date`

**Rules (evaluated in priority order):**

| Rule | Condition | Output |
|------|-----------|--------|
| **R1 — Open task in current/next milestone** | Goal has milestones; the first non-completed milestone (by `order`) has an open related task | That task, kind="task", reason citing the milestone |
| **R2 — Open task outside any milestone** | No milestone match from R1, but goal has open related tasks not assigned to any milestone | First open task by `related_tasks` order, kind="task", reason: "No milestone assigned" |
| **R3 — Next open milestone** | No open tasks at all, but goal has an open or in_progress milestone | That milestone, kind="milestone", reason: "Milestone not yet reached" |
| **R4 — First uncompleted milestone** | All milestones are completed/skipped, but one has `order` beyond the last completed | That milestone, kind="milestone", reason: "Next milestone in sequence" |
| **R5 — No next action** | All milestones completed and no open related tasks | None |

**Design notes:**

- R1 gives priority to tasks that belong to the *current* milestone (the first non-completed one). This is the key improvement over the baseline: instead of blindly picking the first open task, it picks the first open task *that advances the current milestone*.
- A task is "in a milestone" if its title appears in that milestone's `related_tasks`. A task can appear in multiple milestones (shared task) — it is assigned to the earliest non-completed milestone that contains it.
- If R1 finds an open task but it's in a *future* milestone (not the current one), it is NOT selected by R1 — R1 only considers the current/next milestone. This prevents jumping ahead.
- If no tasks are in any milestone (R1 and R2 both yield nothing), R3/R4 surface the milestone itself as the action — the user needs to define tasks for it.
- The `score` field on `NextAction` is 0 by default. The attention engine (§5) assigns scores based on the action's kind and urgency — next actions are not self-scoring.

### 4.3 Integration points

- **Weekly review:** Replace the current `suggested_next_step` derivation with a call to `derive_next_action`. The `NextAction.title` becomes the `suggested_next_step` string (or None). The `NextAction.reason` becomes `progress_detail` for the "no progress but has next action" case.
- **Daily briefing / attention engine:** The attention engine does NOT pick next actions — it scores items that need attention. A next action becomes an attention item only if it meets the existing scoring thresholds (e.g., due today, overdue, high priority). The daily briefing's `suggested_focus` remains the top-scoring attention item, which may or may not be a next action. This is intentional: not every next action deserves immediate attention, and not every attention item is a next action.

### 4.4 CLI exposure

New command: `janus goal next <title>` — prints the derived next action for a goal, with its reason. This is a read-only query, useful for "what should I work on for this goal?"

---

## 5. Stall Detection (Extended)

### 5.1 Current behavior (baseline)

Binary: active goal with related_tasks where all existing tasks are completed → stalled (score=40).

### 5.2 New behavior — multi-signal stall assessment

The attention engine gains a `assess_goal_stall(goal, today, now, completed_task_titles, all_task_titles)` function that returns a list of `(signal, score, reason)` tuples. Multiple signals can fire for the same goal; the highest-scoring signal wins for the attention item.

**Signals (new, in addition to existing binary check):**

| Signal | Trigger | Score | Category |
|--------|---------|-------|----------|
| **Deadline approaching** | Goal has deadline, deadline ≤ 7 days away, goal not completed | 60 | `goal_deadline_soon` |
| **Deadline today** | Goal deadline == today, not completed | 90 | `goal_deadline_today` |
| **Deadline overdue** | Goal deadline < today, not completed, no open related tasks | 100 | `goal_overdue` |
| **Milestone slipped** | Current milestone has deadline < today, status != completed | 50 | `milestone_slipped` |
| **No recent activity** | All related tasks completed, no milestone progress in last 14 days (approximate: last completed task date unknown → use file mtime fallback or skip) | 30 | `goal_inactive` |
| **All tasks done (existing)** | All existing related tasks completed, goal active | 40 | `goal_stalled` |

**Design notes:**

- Deadline signals are the highest-priority new addition. A goal with a deadline tomorrow and no open tasks should outrank a generic blocked task (score 30) — deadline overdue at 100 does, deadline approaching at 60 does not (overdue task is 100, due today is 80). The scoring ladder is: overdue task (100) > deadline today (90) > due today (80) > high priority (50) > deadline approaching (60) → this means deadline approaching (60) sits between high priority (50) and due today (80). Review: is that right? A goal deadline 7 days away is less urgent than a task due today. Yes, 60 < 80 is correct. But it should outrank a plain high-priority task (50) — 60 > 50. Correct.
- "No recent activity" is approximate because the current system has no completion timestamps. The spec defines it as: if all related tasks are completed AND the goal has no milestones with a deadline in the future, signal inactivity. The 14-day window is aspirational — without timestamps, we can only check "are there any future-focused milestones?" If not, the goal looks inert. This signal is intentionally low (30) and does not fire if there is a future milestone or a future deadline.
- Milestone slipped: a milestone with a past deadline and status != completed. Score 50 — less than a task due today (80) because the milestone may not have tasks, and the user may have intentionally deprioritized it. Higher than the existing stalled signal (40) because a missed deadline is more concrete than "all tasks done."
- The existing binary stall signal (40) is retained but demoted: it only fires when no higher-scoring signal fires. In the current code, it fires unconditionally when all tasks are done. The new logic: if all tasks are done AND no deadline/milestone/inactivity signal fires, then stalled (40). This means a goal with all tasks done but a deadline in 30 days is NOT stalled — it's waiting for its next milestone or task. That's the intended behavior: "all tasks done" alone is not a stall if there's a future target.

### 5.3 Attention item construction

For each active goal, `assess_goal_stall` returns signals. The highest-scoring signal becomes the attention item:

```python
title = goal.title
reason = signal.reason
score = signal.score
category = signal.category
```

If no signal fires, the goal does not appear in attention items (same as today — goals without related tasks don't appear).

### 5.4 Data requirements and gaps

- **Deadline signals** require only `goal.deadline` (already stored). No new data.
- **Milestone slipped** requires milestones (new data, §2-3).
- **No recent activity** requires either completion timestamps (not available) or a heuristic. The spec uses the heuristic: "no future milestone and no future deadline → potentially inactive." This is weaker than a true inactivity detector but avoids adding a history log at this stage (discovery rec #6 deferred).

---

## 6. Goal/Calendar/Task Integration

### 6.1 Current state

- Goals have `deadline: str | None` (plain string, not synced to calendar).
- Tasks have `due_date: date | None` (not synced to calendar).
- Calendar is read-only; events feed into attention scoring (score=10 for today's events).
- No goal or milestone deadline creates or reads a calendar event.

### 6.2 Designed integration

**Principle:** The Goal System does NOT write to Google Calendar. Calendar write access is a separate decision (discovery report: "unclear if write access is desired"). The integration is read-side only, plus attention surfacing.

**What changes:**

1. **Goal deadline → attention (new):** The extended stall detection (§5.2) already surfaces approaching/overdue goal deadlines as attention items. This closes discovery rec #4.

2. **Milestone deadline → attention (new):** A milestone with a deadline ≤ 7 days away and status != completed generates a `milestone_slipped` or `milestone_deadline_soon` signal (depending on proximity). This is part of §5.2.

3. **Task due dates → attention (existing):** Already in the attention engine. No change.

4. **Calendar events → goal context (future, deferred):** If a calendar event's title or description matches a goal or milestone title, it could be linked. This is deferred — it requires fuzzy matching and is not essential for MVP execution planning.

### 6.3 What does NOT change

- No calendar writes from the Goal System.
- No two-way sync between goal deadlines and calendar events.
- Tasks remain the unit of calendar-representable work; goals and milestones are higher-level and their deadlines are surfaced via attention, not calendar events.

### 6.4 Rationale

Adding calendar write would require: OAuth scope expansion (currently `calendar.readonly`), a "which calendar?" config, conflict handling, and a decision about whether milestone deadlines and goal deadlines each become events. That's a separate feature. For execution planning MVP, surfacing deadlines via attention is sufficient — the user sees "goal X deadline in 3 days" in the daily briefing and can decide whether to act.

---

## 7. Interface / API Sketches

### 7.1 Service layer

```
services/milestones.py  — milestone CRUD (add, get, update, complete, list for goal)
services/next_action.py — derive_next_action(goal, tasks, completed_titles, today) → NextAction | None
services/attention.py   — extended: assess_goal_stall(...) returns signals; goal attention items use highest signal
services/goals.py       — extended: add_goal/get_goal/update_goal_fields gain milestone kwargs
services/weekly_review.py — uses derive_next_action instead of inline first-open-task logic
```

### 7.2 CLI

| Command | Handler | Notes |
|---------|---------|-------|
| `goal milestone add <goal> <title>` | `handle_goal_milestone_add` | `--description`, `--deadline`, `--status` |
| `goal milestone list <goal>` | `handle_goal_milestone_list` | Ordered by `order` |
| `goal milestone show <goal> <title>` | `handle_goal_milestone_show` | Full details + related tasks |
| `goal milestone complete <goal> <title>` | `handle_goal_milestone_complete` | Sets status=completed |
| `goal milestone update <goal> <title>` | `handle_goal_milestone_update` | `--description`, `--deadline`, `--status`, `--add-related-task`, `--remove-related-task` |
| `goal next <title>` | `handle_goal_next` | Derived next action for a goal |

### 7.3 Data flow (read path)

```
data/goals.md ──load_goals()──> Goal objects (with milestones dicts)
                                           │
data/tasks.md ──load_tasks()──> Task objects
                                           │
                                           ▼
                            derive_next_action(goal, tasks, completed_titles, today)
                                           │
                                           ▼
                            NextAction (title, kind, reason, score) | None
                                           │
                                           ▼
                            weekly_review.py ──> GoalReview.suggested_next_step
                            attention.py ──> assess_goal_stall(...) ──> AttentionItem
```

### 7.4 Data flow (write path)

```
CLI / Telegram ──> services/milestones.py ──> markdown_goals.py (rewrite goal block + milestones)
CLI / Telegram ──> services/goals.py ──> markdown_goals.py (rewrite goal block + milestones)
```

---

## 8. Migration Considerations

### 8.1 Schema changes

- **goals.md format:** Adds optional `## Milestones` section with `### Milestone:` sub-blocks. Backward compatible — existing files without the section parse correctly.
- **Goal dataclass:** Adds `milestones: list[dict] | None` field. Default `None` → `[]` in `__post_init__`. Existing goals loaded from markdown get `milestones=[]`.
- **No database migration:** File-backed system, no schema versioning needed. The parser ignores unknown sections, so old files work.

### 8.2 Code changes by file

| File | Change | Risk |
|------|--------|------|
| `models/goal.py` | Add `milestones` field + default | Low — field is optional, default None |
| `models/milestone.py` | New file | None — purely additive |
| `models/__init__.py` | Export Milestone | None |
| `integrations/markdown_goals.py` | Parse/serialize `## Milestones` section | Medium — rewrites the whole block; must preserve milestones on update |
| `services/goals.py` | Add milestone kwargs to add_goal/update_goal_fields | Low |
| `services/milestones.py` | New file — CRUD for milestones | None — additive |
| `services/next_action.py` | New file — next-action derivation | None — additive |
| `services/attention.py` | Replace binary stall with multi-signal assessment | Medium — changes scoring for existing goals |
| `services/weekly_review.py` | Use derive_next_action | Low — replaces inline logic |
| `goals_cli.py` | New milestone subcommands + `goal next` | None — additive |
| `goals_cli.py` (existing handlers) | May need to pass milestones through | Low |

### 8.3 Risk areas

1. **`update_goal` rewrite loses milestones:** The existing `update_goal` rewrites the entire goal block from `_format_goal_block`. If the new `_format_goal_block` doesn't include milestones, any goal with milestones loses them on the first update. **Mitigation:** `_format_goal_block` must serialize `goal.milestones` when non-empty. This is tested in the milestone persistence tests.

2. **Attention score changes affect daily briefing:** Extending stall detection changes which goals appear in the attention list and at what score. **Mitigation:** The existing binary stall (40) is retained as a fallback; new signals are additive. The daily briefing's "top 3 + suggested focus" selection is score-based and deterministic, so changes are measurable in tests.

3. **Circular import if Milestone imports Goal:** Addressed by storing milestones as dicts in Goal, not as `list[Milestone]`. The service layer constructs `Milestone` objects from dicts when needed.

4. **Milestone `order` assignment:** When adding a milestone to a goal that already has milestones, the new milestone's `order` must be max(existing orders) + 1. **Mitigation:** `add_milestone_for_goal` computes this automatically.

---

## 9. Acceptance Criteria

### 9.1 Milestone model and persistence

- [ ] `Milestone` dataclass with title, goal_title, description, deadline, status, related_tasks, order — validates status and title.
- [ ] `goals.md` parses `## Milestones` / `### Milestone:` blocks and produces Goal objects with `milestones` populated.
- [ ] `goals.md` without milestones section produces Goal objects with `milestones=[]`.
- [ ] `save_goal` with milestones writes the `## Milestones` section.
- [ ] `update_goal` with milestones rewrites the section correctly (milestones survive an update round-trip).
- [ ] Unknown fields inside a milestone block are ignored (same tolerant behavior as goal blocks).

### 9.2 Milestone CRUD service

- [ ] `add_milestone_for_goal(goal_title, title, ...)` creates a milestone with auto-assigned `order` (max existing + 1).
- [ ] `get_milestones_for_goal(goal_title)` returns list of Milestone objects.
- [ ] `update_milestone(goal_title, milestone_title, **kwargs)` updates fields.
- [ ] `complete_milestone(goal_title, milestone_title)` sets status=completed.
- [ ] Duplicate milestone title within a goal is rejected.
- [ ] Milestone with non-existent goal_title is rejected.

### 9.3 Next-action derivation

- [ ] `derive_next_action` returns a task in the current/next milestone if one exists (R1).
- [ ] `derive_next_action` returns a task outside any milestone if no milestone match (R2).
- [ ] `derive_next_action` returns the next open milestone if no open tasks (R3).
- [ ] `derive_next_action` returns the first uncompleted milestone in sequence if all milestones completed (R4).
- [ ] `derive_next_action` returns None when all milestones completed and no open tasks (R5).
- [ ] `derive_next_action` handles goals with no milestones (falls back to R2 — first open related task, or None).
- [ ] Weekly review uses `derive_next_action` for `suggested_next_step`.

### 9.4 Extended stall detection

- [ ] Goal with deadline ≤ 7 days away (not completed) generates `goal_deadline_soon` signal (score 60).
- [ ] Goal with deadline == today generates `goal_deadline_today` signal (score 90).
- [ ] Goal with deadline < today, no open tasks, not completed generates `goal_overdue` signal (score 100).
- [ ] Milestone with past deadline and status != completed generates `milestone_slipped` signal (score 50).
- [ ] Goal with all tasks done, no future deadline, no future milestone generates `goal_inactive` signal (score 30) — or falls through to existing stalled (40).
- [ ] Existing binary stall (all tasks done) fires at score 40 only when no higher signal fires.
- [ ] Goal with future deadline and all tasks done does NOT generate a stall signal (it's waiting for its next action).
- [ ] Attention items for goals use the highest-scoring signal.

### 9.5 CLI

- [ ] `goal milestone add` works end-to-end (creates milestone, persists in goals.md).
- [ ] `goal milestone list` shows ordered milestones for a goal.
- [ ] `goal milestone complete` marks a milestone completed.
- [ ] `goal next <title>` prints the derived next action or "No next action."
- [ ] Existing `goal list`, `goal show`, `goal add`, `goal update`, `goal complete` continue to work (no regression).

### 9.6 Integration

- [ ] Goal deadline approaching/overdue appears in attention items (via extended stall detection).
- [ ] Milestone slipped appears in attention items.
- [ ] Daily briefing's suggested focus can be a goal deadline or milestone signal (if it scores highest).
- [ ] No calendar writes — integration is read-side + attention only.

### 9.7 Deferred (not in this spec)

- [ ] Task dependencies (`depends_on` field) — deferred to follow-up task.
- [ ] Progress history / metric snapshots — deferred to follow-up task.
- [ ] Calendar write (goal/milestone deadline → calendar event) — deferred, requires scope decision.
- [ ] Goal rename — not in scope; goal_title remains immutable for MVP.
- [ ] `goal next` in the daily briefing as a default focus — not in scope; suggested_focus remains the top attention item.

---

## 10. File Inventory (new and modified)

### New files

- `src/janus/models/milestone.py` — Milestone dataclass
- `src/janus/services/milestones.py` — milestone CRUD service
- `src/janus/services/next_action.py` — next-action derivation

### Modified files

- `src/janus/models/goal.py` — add `milestones` field
- `src/janus/models/__init__.py` — export Milestone
- `src/janus/integrations/markdown_goals.py` — parse/serialize milestones section
- `src/janus/services/goals.py` — milestone kwargs on add/update
- `src/janus/services/attention.py` — multi-signal stall detection
- `src/janus/services/weekly_review.py` — use derive_next_action
- `src/janus/goals_cli.py` — milestone subcommands + `goal next`

### Test files (new and modified)

- `tests/test_milestone_model.py` — Milestone dataclass validation
- `tests/test_milestone_persistence.py` — goals.md parse/serialize round-trip
- `tests/test_milestones_service.py` — milestone CRUD
- `tests/test_next_action.py` — derive_next_action rules
- `tests/test_attention_extended.py` — extended stall signals (adds to existing test_attention.py)
- `tests/test_goals_cli_milestones.py` — CLI milestone commands
- `tests/test_goal_next.py` — `goal next` CLI
- Existing `tests/test_attention.py` — updated for new stall signals
- Existing `tests/test_weekly_review.py` — updated for derive_next_action
- Existing `tests/test_markdown_goals.py` — updated for milestones section

---

## 11. Open Questions

1. **Milestone status values:** Spec uses `open | in_progress | completed | skipped`. Is `in_progress` useful, or should milestones be binary (open/completed)? Binary is simpler; `in_progress` is more expressive. Recommend: start with `open | completed` for MVP, add `in_progress` later if needed. **Decision needed.**

2. **Milestone `order` gaps:** If milestone with order=1 is skipped/deleted, does order=2 become order=1? Spec says no — orders are assigned once and not renumbered. Gaps are acceptable. This matches the existing `related_tasks` behavior (no reordering on removal).

3. **Next action when a task belongs to multiple milestones:** R1 assigns the task to the earliest non-completed milestone that contains it. Is this correct, or should a shared task be "claimed" by the first milestone that references it, permanently? Spec: assign to earliest non-completed milestone at derivation time (not stored). This means a shared task can shift between milestones as earlier ones complete. **Decision needed.**

4. **Goal deadline vs. milestone deadline precedence:** If a goal has deadline 2026-10-01 and a milestone has deadline 2026-09-15, which signal fires? Spec: both can fire independently (goal_deadline_soon and milestone_slipped are separate signals). The highest score wins for the attention item. This means a slipped milestone (50) won't outrank a goal deadline today (90) — the goal deadline dominates. Is that right? A slipped milestone is more concrete than a goal deadline — maybe milestone should score higher? **Decision needed.**

5. **`goal next` output format:** Plain text? JSON? The spec says plain text with reason. If Telegram delivery needs structured data, a JSON flag could be added. **Decision needed.**

---

*End of spec.*
