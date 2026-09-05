# Calendar-Aware Planning — Feature Specification

**Status:** Accepted
**Parent task:** t_4810582f (Design calendar-aware planning feature specification)
**Child tasks:** t_f819923c (Implement), t_ad206032 (Verify)
**ADR reference:** ADR-001 (Janus owns domain logic, deterministic processing)

---

## 1. Overview and Goals

Calendar-aware planning extends the Janus daily/weekly briefing pipeline so
that calendar availability data informs task prioritization, overload
detection, and realistic placement suggestions. All logic lives in Janus
(per ADR-001) and is deterministic, testable, and non-blocking on external
services at computation time.

**Four design questions addressed:**

1. How are available focus blocks identified from calendar data?
2. How are overloaded days detected (task estimates vs available time)?
3. How do upcoming events influence task suggestions?
4. How is realistic task placement computed and presented?

---

## 2. Current State (as-built)

### What exists

- **Calendar read integration** (`src/janus/integrations/google_calendar.py`):
  - OAuth with `calendar.readonly` scope, multi-calendar via `config.toml`.
  - `list_upcoming_events()` returns all upcoming `Event` objects across
    configured calendars, merged and sorted by start time.
  - `list_events(calendar_id)` hardcodes `maxResults=10`, `singleEvents=True`,
    `orderBy="startTime"`.
  - `parse_event()` converts Google API dicts into the `Event` dataclass.

- **Daily briefing** (`src/janus/services/daily_briefing.py`):
  - `create_daily_briefing(events, tasks, goals, today)` assembles a
    `DailyBriefing` by delegating to the Attention Engine.
  - `DailyBriefing` model fields: `events`, `attention_items`,
    `suggested_focus`.

- **Attention Engine** (`src/janus/services/attention.py`):
  - `get_attention_items(events, tasks, goals, today, now=None)` → ranked
    list of `AttentionItem`.
  - Scoring: overdue (100), due_today (80), high_priority (50), blocked
    (30), in_progress (30), upcoming_event (10), goal_stalled (40).
  - Deterministic sort: score desc → category asc → title asc.

- **Today renderer** (`src/janus/today.py`):
  - `show_today()` prints SCHEDULE, REQUIRES ATTENTION (top 3), SUGGESTED
    FOCUS (top 1).
  - `_build_today_briefing()` fetches events filtered to today's date.

- **Telegram** (`src/janus/integrations/telegram.py`):
  - `format_telegram_message(briefing)` mirrors the CLI layout.

### What is missing (verified)

| Capability | Status |
|---|---|
| Free/busy slot computation | Missing |
| Overload detection (tasks vs available time) | Missing |
| Focus block scheduling / time-block model | Missing |
| Task duration estimation | Missing |
| Conflict detection (overlapping events) | Missing |
| Calendar write access (create events) | Missing |
| Busy-hours aggregation | Missing |

### Key constraints

1. Calendar API is **read-only** (`calendar.readonly` scope). No event
   creation/modification in this spec.
2. `maxResults=10` is hardcoded — only ~10 upcoming events per calendar are
   fetched. Focus-block computation uses only today's events (the `today`
   slice already filtered by `_build_today_briefing`), so this is sufficient
   for the daily view but limits multi-day lookahead.
3. **Task model has no duration/estimate field** — tasks have `due_date`,
   `priority`, `state`, `progress`, `extra_metadata` but no `estimate` or
   `duration_hours`.
4. All-day events have `end = None` (no duration).
5. Timezone handling is inconsistent: `list_upcoming_events()` uses
   `datetime.now().astimezone().isoformat()` for `timeMin`; event parsing
   converts ISO strings to timezone-aware datetimes; the today filter in
   `_build_today_briefing` compares `e.start.date() == today` (naive date
   vs aware datetime `.date()`).
6. `extra_metadata: list[str]` on `Task` provides an extension point for
   future fields without changing the markdown parser.

---

## 3. Data Flow

```
Google Calendar API  ──►  list_upcoming_events()       ──► Event[]
data/tasks.md         ──►  load_tasks()                 ──► Task[]
data/goals.md         ──►  load_goals()                 ──► Goal[]
                                          │
                                          ▼
               create_daily_briefing()  (today filter)
                    │
                    ├──► freebusy.compute_free_slots(events, today) → TimeBlock[]
                    ├──► overload.evaluate_load(events, tasks, today) → OverloadRating | None
                    ├──► attention.get_attention_items(events, tasks, goals, today) → AttentionItem[]
                    │        (extended: upcoming-event + free-slot context)
                    │
                    ▼
               DailyBriefing (extended model)
                    │
                    ├──► today.show_today()  /  telegram.format_telegram_message()
                    ▼
              User: CLI / Telegram
```

**New modules introduced:**

- `src/janus/services/freebusy.py` — free/busy slot computation
- `src/janus/services/overload.py` — overload detection
- `src/janus/models/time_block.py` — `TimeBlock` dataclass

**Extended modules:**

- `src/janus/models/daily_briefing.py` — add `free_slots` and
  `overload_warning` fields
- `src/janus/services/daily_briefing.py` — orchestrate new services
- `src/janus/services/attention.py` — extend upcoming-event context with
  free-slot awareness
- `src/janus/today.py` — render new sections
- `src/janus/integrations/telegram.py` — render new sections
- `config/config.example.toml` — add `[planning]` section (optional)

No changes to the `Task` model are required in this spec (estimation is
deferred to a future spec; see §9.5).

---

## 4. Data Models

### 4.1 TimeBlock (new)

File: `src/janus/models/time_block.py`

```python
from dataclasses import dataclass
from datetime import datetime

@dataclass
class TimeBlock:
    start: datetime
    end: datetime
    title: str = ""
    type: str = "free"   # "free" | "busy"

    @property
    def duration_minutes(self) -> int:
        delta = self.end - self.start
        return int(delta.total_seconds() // 60)

    @property
    def is_free(self) -> bool:
        return self.type == "free"
```

Design notes:
- `TimeBlock` is a **pure value object** — no persistence, no identity.
  It is computed from `Event` data each briefing cycle.
- `type` discriminates free (available) vs busy (calendar event) blocks.
  This dual-purpose design lets a single merge routine produce both the
  free-slot list (for placement) and the busy-segment list (for overload
  computation), avoiding duplicate interval-merging code.
- `title` is populated from the event title for busy blocks; empty for
  free blocks.

### 4.2 DailyBriefing (extended)

File: `src/janus/models/daily_briefing.py`

```python
@dataclass
class DailyBriefing:
    events: list[Event]
    attention_items: list[AttentionItem] = field(default_factory=list)
    suggested_focus: AttentionItem | None = None
    free_slots: list[TimeBlock] = field(default_factory=list)      # NEW
    overload_warning: str | None = None                           # NEW
```

Backward compatibility: Both new fields default to empty/None, so all
existing callers and tests that construct `DailyBriefing` without these
fields continue to work unchanged.

### 4.3 AttentionItem (extended)

The existing `AttentionItem` gains no new fields. The upcoming-event
scoring enhancement (§7) operates on the existing schema — event items
already appear in `attention_items` with category `upcoming_event`. The
free-slot context is surfaced as additional attention items (see §7).

---

## 5. Focus Block Identification (Question 1)

### 5.1 Algorithm: `compute_free_slots`

File: `src/janus/services/freebusy.py`

**Input:**
- `events: list[Event]` — all events for the day (timed + all-day)
- `day: date` — the day to analyze
- `work_hours: tuple[int, int]` — default `(9, 17)` (9 AM start, 5 PM end)
- `min_slot_minutes: int` — default `30` (minimum viable free block)
- `tz: timezone` — default to local timezone (for boundary alignment)

**Output:** `list[TimeBlock]` — free slots sorted by start time

**Algorithm:**

1. **Filter to-day timed events.** Keep only events where `event.start`
   is not None and `event.start.date() == day`. All-day events are
   excluded from slot computation (they have no timed boundary; treating
   them as blocking would distort availability and the existing today
   filter already handles their display separately). This is a known
   limitation — see §9.3.

2. **Build busy intervals.** For each timed event:
   - If `event.end` is not None, use `[start, end]` as the busy interval.
   - If `event.end` is None (edge case for timed events missing end), fall
     back to `[start, start + 1 hour]` — a conservative 60-minute busy
     assumption. This is flagged in the overload warning's confidence
     note if any event lacked an end time.
   - Convert all datetimes to the target `tz`.

3. **Clamp to work-hours window.** Only consider the window
   `[work_hours_start, work_hours_end]` on `day`. Events outside this
   window are excluded from blocking computation (evening/personal events
   do not reduce working-day availability in this model).

4. **Merge overlapping intervals.** Sort busy intervals by start; merge
   any that overlap or touch. This handles back-to-back meetings and
   overlapping events (implicit conflict detection — see §9.2).

5. **Compute gaps.** Walk the sorted, merged busy intervals within the
   work-hours window. The free slots are the gaps between:
   - window_start → first_busy.start
   - each busy.end → next_busy.start
   - last_busy.end → window_end

6. **Filter by minimum size.** Drop any free slot shorter than
   `min_slot_minutes`.

7. **Return** the list of free `TimeBlock` objects, sorted by start.

**Concrete example:**

Calendar (work hours 9-17, local tz):
- 09:00–10:30 Standup + planning
- 10:30–11:00 Buffer (free)
- 11:00–12:00 Deep work (busy)
- 12:00–13:00 Lunch break
- 13:00–14:00 Meeting
- 14:00–15:30 Free (focus block candidate)
- 15:30–17:00 Busy

Busy intervals (merged): [09:00–12:00, 13:00–14:00, 15:30–17:00]
Free slots: [12:00–13:00, 14:00–15:30]

### 5.2 Configuration

File: `config/config.example.toml`

```toml
[planning]
# Work hours window for free/busy computation (24-hour format).
# Only time within this window on the current day counts as "working availability".
work_hours_start = 9    # 9:00
work_hours_end = 17     # 17:00
# Minimum consecutive free minutes to qualify as a usable focus block.
min_focus_slot_minutes = 30
# Tasks with this many total estimated+due-today points trigger a soft warning.
# (Without estimates, uses a simpler task-count heuristic — see §6.)
overload_task_count_threshold = 4
# Fraction of work-hours that must be free for a day to be "under capacity".
# Below this → overload. Default 0.5 (i.e., >50% of work hours consumed → overloaded)
overload_busy_fraction_threshold = 0.5
```

All fields optional. Defaults are applied when `[planning]` is absent, so
existing configs continue to work without modification.

### 5.3 Edge cases

- **No events:** entire work-hours window is one free slot.
- **Events spanning work hours:** clamped to work-hours window.
- **Events starting before work hours:** the busy interval is clamped to
  `work_hours_start`.
- **No config / no calendars:** `free_slots` is empty (no events means no
  data to compute from — returns empty, not a full window). The renderer
  displays "No calendar configured or no events today." Rationale: without
  a calendar config, we cannot assume the user is entirely free; the
  absence of data is surfaced as a missing-config note rather than a
  false full-availability signal.
- **maxResults=10 limit:** if today's events exceed 10 per calendar, free
  slots may be incomplete. The overload computation notes this as a
  confidence caveat. This is tracked as a known limitation (§9.1).

---

## 6. Overload Detection (Question 2)

### 6.1 Algorithm: `evaluate_load`

File: `src/janus/services/overload.py`

**Inputs:**
- `events: list[Event]` — today's events
- `tasks: list[Task]` — open tasks
- `day: date`
- `free_slots: list[TimeBlock]` — from §5 (computed first)
- `config: PlanningConfig` — thresholds

**Output:** `tuple[str | None, str | None]`
- `(warning_level, message)` where `warning_level` is `"warning"` or
  `"critical"`, or `(None, None)` if no overload.

**Overload criteria (checked in order, first match wins):**

1. **Busy-fraction overload (primary, data-based).**
   - Compute total busy minutes within work-hours from the merged busy
     intervals (i.e., `work_hours_total - sum(free_slot.durations)`).
   - If `busy_minutes / work_hours_total > overload_busy_fraction_threshold`
     (default 0.5), the day is overloaded by time.
   - Severity escalates to `"critical"` when busy fraction exceeds 0.8
     (i.e., the user has <20% of work hours free).

2. **Task-count overload (fallback, estimate-free).**
   - Without task duration estimates (see §9.5), fall back to a
     count-based heuristic: count tasks that are overdue + due today +
     high priority (priority >= 3). If this count ≥
     `overload_task_count_threshold` (default 4), flag as `"warning"`.
   - Rationale: we cannot sum task hours without estimates, but a high
     count of urgent tasks alongside heavy meeting load is a reliable
     overload signal. This criterion is only applied when the busy-fraction
     criterion did NOT already trigger (avoids double-flagging).

3. **Free-slot exhaustion (granular).**
   - If free slots exist but none ≥ `min_focus_slot_minutes * 2` (i.e.,
     no slot can accommodate even a medium task), and there is ≥ 1 overdue
     or due-today task, flag as `"warning"`: "No focus block large enough
     for deep work."

**Confidence level:** The overload message includes a confidence tag
(`[estimated]` when using task-count fallback, `[measured]` when using
busy-fraction). This is surfaced in the message text, not as a separate
field, to keep the renderer simple.

**Examples:**

- Work hours 9-17 = 480 minutes. 6 hours of meetings = 360 busy minutes.
  360/480 = 0.75 > 0.5 → `"warning".
- Same day, 432 busy minutes (9-17 fully booked except 48 min gap).
  432/480 = 0.9 > 0.8 → `"critical"`.
- 2 hours of meetings, 0 urgent tasks → no warning.

### 6.2 Integration with Attention Engine

The overload state is computed at briefing-assembly time (§8) and attached
to `DailyBriefing`. The Attention Engine itself is **not modified** for
overload detection — it remains a pure scoring engine over events + tasks
+ goals. Overload is a separate concern (planning capacity), surfaced in
the briefing model and renderer, not in attention items. This keeps the
attention engine testable in isolation and avoids coupling scoring to
calendar arithmetic.

---

## 7. Upcoming Events Influencing Task Suggestions (Question 3)

### 7.1 Existing behavior

The Attention Engine already emits `upcoming_event` items (score 10,
category `"upcoming_event"`) for events starting later today after `now`.
These appear in the attention list and may influence `suggested_focus`
if they score higher than tasks (they don't — max score 10 vs 50+ for
priority tasks).

### 7.2 Enhancement: Free-slot-aware task suggestions

When free slots are computed, the briefing surface tasks that can
realistically fit in available blocks. This uses the existing
`AttentionItem` schema — no new model.

**Rule:** For each free slot ≥ `min_focus_slot_minutes`, emit an
`AttentionItem` with:
- `category = "focus_available"`
- `title = "<N> min free: <slot start>–<slot end>"`
- `reason = f"Free focus block from {start} to {end}"`
- `score = 5` (lower than upcoming events at 10, so tasks still take
  precedence; but higher than nothing — surfaces availability)
- `focus = False` (these are informational, not suggested-work items)

Wait — this would clutter the attention list with slot announcements.
**Refined approach:** Instead of injecting free-slot items into the main
attention list (which is capped at 3 in the renderer), the free slots are
rendered as a dedicated `FREE BLOCKS` section in the briefing. Task
placement recommendations that reference specific slots are generated in
§8 and presented in a `TASK PLACEMENT` section.

**Upcoming-event influence on suggestions (actual enhancement):**
The `upcoming_event` scoring is augmented by slot context. When a free
slot exists after an upcoming event, tasks due today or overdue are
prioritized as "should start in this block." This produces
`AttentionItem` entries with `category = "placement_candidate"`:

```
If free_slot after upcoming_event E and (task due today or overdue):
    AttentionItem(
        title = task.title,
        reason = f"Suggested for {slot.start:%H:%M}–{slot.end:%H:%M} (after '{E.title}')",
        score = task's existing attention score,  # preserves priority ordering
        category = "placement_candidate",
        focus = True
    )
```

**But** — without task duration estimates (§9.5), we cannot verify the
task fits in the slot. Therefore this enhancement operates as a
**soft suggestion** only: candidates are presented with a confidence
marker `(fit not verified — no duration estimate)`. The renderer labels
these as "SUGGESTED FOR" rather than "SCHEDULED FOR."

This is the realistic scope for the current spec: upcoming events
influence *which* slot is suggested as the target window, but actual
duration-aware fitting is deferred.

### 7.3 Non-goals

- No reordering of `suggested_focus` based on slot availability. The
  top-scored attention item remains the suggested focus regardless of
  calendar availability — it is the "what," not the "when."
- No automatic task-to-slot binding in the model. Placement suggestions
  are computed at render time (§8.2), not stored as persistent state.

---

## 8. Realistic Task Placement Computation & Presentation (Question 4)

### 8.1 Computation: `suggest_placement`

File: `src/janus/services/placement.py` (new)

**Inputs:**
- `free_slots: list[TimeBlock]`
- `tasks: list[Task]` (open tasks only)
- `attention_items: list[AttentionItem]` (already scored)
- `min_slot_minutes: int`

**Algorithm:**

1. Take the top-N attention items that are task-derived (categories:
   `overdue_task`, `due_today`, `high_priority_task`, `blocked_task`,
   `in_progress_task`). Exclude `upcoming_event` and `goal_stalled`
   (events cannot be placed in calendar blocks; stalled goals need
   milestone work, not a single slot).
2. For each candidate task (in attention-score order), find the first
   free slot ≥ `min_slot_minutes`. Assign the task to that slot's start
   time. Mark the slot as "consumed" (removed from the pool) so a second
   task isn't placed in the same block.
3. Stop when no free slots remain.
4. Return `list[Placement]` where:

```python
@dataclass
class Placement:
    task_title: str
    slot: TimeBlock
    reason: str   # e.g. "Due today; fits in available 90-min block"
```

**Confidence:** Since no duration estimates exist, the reason always
includes "Estimated fit — no task duration on record." If a task has
`extra_metadata` entries containing `estimate:` or `duration:`, the
placement service can parse them (optional, best-effort) and only assign
if the slot is large enough. This uses the existing `extra_metadata`
extension point without changing the `Task` model.

### 8.2 Presentation

#### 8.2.1 CLI renderer (`today.py`)

New sections appended after `SUGGESTED FOCUS`:

```
FREE BLOCKS
- 12:00–13:00 — 60 min available
- 14:00–15:30 — 90 min available

TASK PLACEMENT
- Buy groceries → 12:00–13:00
  Due today; fits in available 60-min block (estimated fit — no task duration on record)
- Write report → 14:00–15:30
  High priority; fits in available 90-min block (estimated fit — no task duration on record)
```

If no free slots: `FREE BLOCKS: No calendar data available. Configure
calendars in config.toml.`

If overload: rendered in the `REQUIRES ATTENTION` section as the first
item (score override to 200 so it always surfaces at top):
```
⚠ HIGH MEETING LOAD TODAY — 6/8 hours scheduled. 2 tasks due today.
```

#### 8.2.2 Telegram (`telegram.py`)

Same sections, using emoji headers for scannability:
- `💤 FREE BLOCKS`
- `📋 TASK PLACEMENT`
- Overload warning rendered as an attention item with `⚠` prefix.

### 8.3 Suggested Focus extension (optional display-only)

The existing top-1 `suggested_focus` continues to be the highest-scored
attention item. When placement suggestions exist, the renderer may
additionally show the placement target beneath the suggested focus:

```
SUGGESTED FOCUS
1. Buy groceries
   Due today
   → Suggested for 12:00–13:00 free block
```

This is a display annotation only — the `AttentionItem` and
`DailyBriefing.suggested_focus` are not structurally changed.

---

## 9. Limitations and Future Extensions

### 9.1 maxResults=10 constraint

`list_events()` hardcodes `maxResults=10`. If a user has >10 events on a
single day (busy day), free-slot computation will be incomplete. **Mitigation
in this spec:** the overload warning appends a confidence note when the
event count per calendar reaches the cap. **Future fix:** parameterize
`maxResults` and add pagination (tracked as follow-up, not in scope here).

### 9.2 All-day event handling

All-day events have `end = None` and no timed boundary. This spec excludes
them from free-slot computation entirely. **Future extension:** treat all-day
events as full-day busy blocks if the user configures them to represent
busy days (vacation, travel, etc.).

### 9.3 Overlapping events (implicit conflict detection)

The interval-merge in §5.2 merges overlapping intervals silently. If two
events overlap, the union is treated as one continuous busy block.
**No explicit conflict warning** is emitted in this spec (it would require
a separate detection pass). **Future extension:** add a conflict-warning
attention item when overlaps are detected during merge.

### 9.4 Timezone handling

The existing timezone handling is inconsistent (see §2, constraint 5).
This spec's freebusy service accepts an explicit `tz` parameter (default
local) and converts all event datetimes to it before comparison. The
today-filter in `_build_today_briefing` continues to use the existing
`e.start.date() == today` logic. **Future cleanup:** normalize all
datetime comparisons to aware datetimes in the user's local timezone.

### 9.5 Task duration estimation

**Not in scope for this spec.** Without a task `estimate` or
`duration_hours` field, placement suggestions are confidence-qualified
"fits in available slot (estimated fit — no duration on record)." The
`placement.suggest_placement` service supports best-effort parsing of
`estimate: Nh` or `duration: Nmin` from `extra_metadata` so that users
who manually annotate estimates get duration-aware fitting, while others
get soft suggestions. A future spec will introduce an `estimate_minutes`
field on `Task` and a CLI `janus task estimate <title> --mins N`.

### 9.6 Calendar write access

**Out of scope.** The spec is read-only. Creating focus blocks as actual
calendar events would require upgrading the OAuth scope from
`calendar.readonly` to `calendar.events` and re-running the OAuth flow.
This is intentionally deferred — the spec treats free slots as
suggestions, not committed calendar blocks. A future spec may add
`janus plan block <title> --from HH:MM --to HH:MM` to create events
(requires scope upgrade).

### 9.7 Multi-day lookahead

The daily briefing filters to today's events. This spec's free-slot and
overload computation is for today only. **Future extension:** a
`janus plan week` command that computes free slots and overload across
the next 7 days (requires increasing `maxResults` or adding date-range
queries — see §9.1).

---

## 10. API and Interface Changes

### 10.1 New service functions

| Function | Module | Signature |
|---|---|---|
| `compute_free_slots` | `services/freebusy.py` | `(events, day, work_hours=(9,17), min_slot_minutes=30, tz=None) -> list[TimeBlock]` |
| `evaluate_load` | `services/overload.py` | `(events, tasks, day, free_slots, config=None) -> tuple[str\|None, str\|None]` |
| `suggest_placement` | `services/placement.py` | `(free_slots, tasks, attention_items, min_slot_minutes=30) -> list[Placement]` |

### 10.2 Extended model fields

| Model | Field | Type | Default |
|---|---|---|---|
| `DailyBriefing` | `free_slots` | `list[TimeBlock]` | `[]` |
| `DailyBriefing` | `overload_warning` | `str \| None` | `None` |

### 10.3 Extended `create_daily_briefing`

```python
def create_daily_briefing(
    events: list[Event],
    tasks: list[Task],
    goals: list[Goal],
    today: date,
) -> DailyBriefing:
```

The signature is unchanged (no new parameters). Internally, it calls the
new `compute_free_slots` and `evaluate_load` services and populates the
new `DailyBriefing` fields. This keeps the public API stable for
existing callers and tests.

### 10.4 Config additions

```toml
[planning]
work_hours_start = 9
work_hours_end = 17
min_focus_slot_minutes = 30
overload_task_count_threshold = 4
overload_busy_fraction_threshold = 0.5
```

### 10.5 No CLI changes in this spec

The `janus today` and `janus telegram` commands are unchanged in their
command-line interface. The enhanced output (free blocks, placement,
overload warnings) is automatically included in the existing `show_today()`
and `format_telegram_message()` output. No new subcommands.

---

## 11. Acceptance Criteria

### 11.1 Focus block identification

- [ ] `compute_free_slots` returns empty list when no events exist for the
  day (with a configured calendar service returning empty).
- [ ] `compute_free_slots` returns the full work-hours window as a single
  free slot when no events conflict.
- [ ] `compute_free_slots` correctly computes gaps between non-overlapping
  events (e.g., 9-10:30 busy, 10:30-11 free, 11-12 busy → one 30-min slot).
- [ ] `compute_free_slots` merges overlapping events into a single busy
  interval (no false free slots in the overlap).
- [ ] `compute_free_slots` removes free slots shorter than `min_slot_minutes`.
- [ ] `compute_free_slots` clamps events to the configured work-hours
  window (event 8-18 with work hours 9-17 → busy 9-17, free slots computed
  within 9-17 only).
- [ ] All-day events do not appear as timed busy blocks (excluded from
  slot computation).
- [ ] Events with no `end` time fall back to a 60-minute busy interval.

### 11.2 Overload detection

- [ ] `evaluate_load` returns `(None, None)` when ≤50% of work hours are
  busy and ≤3 urgent tasks.
- [ ] `evaluate_load` returns `"warning"` when >50% of work hours are
  busy.
- [ ] `evaluate_load` returns `"critical"` when >80% of work hours are
  busy.
- [ ] `evaluate_load` returns `"warning"` (task-count fallback) when busy
  fraction is low but ≥4 overdue/due-today/high-priority tasks exist,
  with `[estimated]` confidence marker.
- [ ] `evaluate_load` returns `"warning"` when free slots exist but none
  ≥ `2 * min_slot_minutes` and ≥1 urgent task exists.
- [ ] Overload message includes the confidence tag (`[measured]` or
  `[estimated]`).

### 11.3 Upcoming events influencing suggestions

- [ ] `upcoming_event` attention items continue to be emitted by the
  existing Attention Engine (unchanged behavior).
- [ ] `DailyBriefing` with a free slot after an upcoming event produces a
  placement suggestion for the top urgent task targeting that slot.
- [ ] Placement suggestions include the confidence qualifier when no task
  duration estimate is available.
- [ ] `goal_stalled` and `upcoming_event` items are excluded from
  `suggest_placement` candidate selection.

### 11.4 Task placement

- [ ] `suggest_placement` assigns the highest-scored task to the first
  eligible free slot.
- [ ] `suggest_placement` does not assign two tasks to the same slot
  (slot consumed after assignment).
- [ ] `suggest_placement` stops when no free slots remain.
- [ ] `suggest_placement` returns an empty list when no free slots
  exist.
- [ ] `suggest_placement` parses best-effort `estimate:` metadata from
  `extra_metadata` and skips slots too small when an estimate is present.

### 11.5 Rendering (CLI + Telegram)

- [ ] `show_today()` displays a `FREE BLOCKS` section with slot
  durations.
- [ ] `show_today()` displays a `TASK PLACEMENT` section matching tasks
  to slots.
- [ ] `show_today()` surfaces the overload warning at the top of
  `REQUIRES ATTENTION` when present.
- [ ] `format_telegram_message()` displays the same information with
  emoji headers (`💤 FREE BLOCKS`, `📋 TASK PLACEMENT`).
- [ ] Existing sections (SCHEDULE, REQUIRES ATTENTION, SUGGESTED FOCUS)
  remain unchanged in format when no calendar data or overload exists.

### 11.6 Backward compatibility

- [ ] `DailyBriefing` constructed without `free_slots` / `overload_warning`
  defaults to empty list / None.
- [ ] Existing tests in `tests/test_daily_briefing.py` and
  `tests/test_attention.py` pass unchanged.
- [ ] `config/config.example.toml` additions are optional; existing configs
  without `[planning]` work with defaults.
- [ ] `create_daily_briefing` signature is unchanged.

### 11.7 Testing

- [ ] `tests/test_freebusy.py` — unit tests for `compute_free_slots`
  covering all acceptance criteria in §11.1.
- [ ] `tests/test_overload.py` — unit tests for `evaluate_load` covering
  all acceptance criteria in §11.2.
- [ ] `tests/test_placement.py` — unit tests for `suggest_placement`
  covering all acceptance criteria in §11.4.
- [ ] Existing test files (`test_daily_briefing.py`, `test_attention.py`,
  `test_google_calendar.py`) continue to pass.
- [ ] New tests follow existing patterns: `monkeypatch` for config
  dependencies, `FakeCalendarService` pattern for calendar mocking,
  `FIXED_TODAY = date(2026, 8, 28)` convention.

---

## 12. Non-Goals

The following are explicitly **not** in scope for this specification and
are deferred to future specs:

1. Calendar write access (creating/modifying calendar events).
2. Persistent time-block storage (`data/time_blocks.md` or similar).
3. A dedicated `janus plan` command.
4. Multi-day free-slot computation (today-only).
5. Formal task duration estimation field on `Task`.
6. Explicit conflict detection as a user-facing warning (overlaps are
   silently merged).
7. All-day event as blocking time windows.
8. Pagination or `maxResults` increase for the Google Calendar API.

---

## 13. Implementation Order (for child task t_f819923c)

1. Add `TimeBlock` model (`models/time_block.py`).
2. Add `compute_free_slots` service (`services/freebusy.py`) with tests.
3. Add `evaluate_load` service (`services/overload.py`) with config loader
   helper, with tests.
4. Add `Placement` model + `suggest_placement` service
   (`services/placement.py`) with tests.
5. Extend `DailyBriefing` model with `free_slots` and `overload_warning`.
6. Update `create_daily_briefing` to call the new services and populate
   the new fields.
7. Extend `today.py` renderer with `FREE BLOCKS` and `TASK PLACEMENT`
   sections; surface overload warning in `REQUIRES ATTENTION`.
8. Extend `telegram.py` with the same sections.
9. Add `[planning]` section to `config/config.example.toml`.
10. Run full test suite; ensure all existing tests pass unchanged.
