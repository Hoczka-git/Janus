# Design: Generic Measurement Collection for Goals

**Task:** t_e1dc741c
**Date:** 2026-09-06
**Status:** Design complete — awaiting implementation
**Depends on:** Research findings (t_adc16d5c) — `reports/goal_measurement_research_findings.md`

---

## 1. Problem Statement

Goals can declare **what** to measure (metric name, unit, target value, direction) but not **when** or **how often** to collect. There is no mechanism to:

- Declare a measurement requirement with a collection frequency and preferred time window
- Determine which measurements are currently due
- Record a time-series history of measurement values
- Surface pending measurements in the daily briefing or weekly review
- Abstract where a measurement value comes from (manual entry, device, API)

The design must be **domain-agnostic** — it must work for fitness, finance, health, learning, and any other measurable goal.

---

## 2. Architecture Overview

```
                    ┌─────────────────────────────┐
                    │   data/goals.md             │
                    │   (Goal + measurement_       │
                    │    requirements)            │
                    └─────────────┬───────────────┘
                                  │ load_goals()
                                  ▼
                    ┌─────────────────────────────┐
                    │   Goal (domain model)        │
                    │   + measurement_requirements │
                    └─────────────┬───────────────┘
                                  │
                    ┌─────────────▼───────────────┐
                    │  measurement_collection.py   │
                    │  get_due_measurements()      │
                    └─────────────┬───────────────┘
                                  │
                    ┌─────────────▼───────────────┐
                    │  MeasurementLog (read-only)  │
                    │  data/measurements.jsonl     │
                    └─────────────────────────────┘
                                  │
                    ┌─────────────▼───────────────┐
                    │  Output: MeasurementRequest  │
                    │  (structured, for Hermes/    │
                    │   CLI/briefing)              │
                    └─────────────────────────────┘
```

**Core principle:** The measurement collection service is a pure function from (goals, log, today, now) → due measurements. It has no side effects, no scheduling thread, and no awareness of how the result will be used. Consumers (daily briefing, weekly review, CLI, Hermes) decide what to do with the output.

---

## 3. Data Model Changes

### 3.1 Goal.measurement_requirements (NEW FIELD)

**File:** `src/janus/models/goal.py`

```python
@dataclass
class Goal:
    # ... existing fields ...
    measurement_requirements: list[dict] | None = None
    # Each dict:
    # {
    #   "metric": str,           # e.g. "weight", "savings_balance", "study_hours"
    #   "unit": str,             # e.g. "kg", "PLN", "hours"
    #   "frequency": str,        # "daily" | "twice_weekly" | "weekly" | "weekends" | "custom"
    #   "preferred_time": str,   # "morning" | "afternoon" | "evening" | "anytime"
    #   "interval_days": int     # optional, only for frequency="custom"
    # }
```

**Default:** `None` (no requirements — backward compatible with existing goals).

**Validation:** Not validated in the Goal constructor (MVP). Validation happens at the service layer when requirements are added or updated. This keeps the model simple and allows partial/invalid requirements to exist in the markdown file without breaking loading (unknown keys are ignored on parse, matching the existing pattern for other fields).

**Rationale for list[dict] over a dedicated model class:**

1. Consistent with how `milestones` are already stored (list[dict] on Goal, model objects constructed on demand).
2. Avoids an import cycle if a MeasurementRequirement model would need to import Goal or vice versa.
3. Keeps markdown serialization simple — dict keys map directly to lines in `goals.md`.
4. Allows sparse definition (e.g., only `metric` + `frequency`, omitting `preferred_time`).

**Alternative considered — dedicated MeasurementRequirement dataclass + separate persistence file:**

Rejected for MVP. A separate model and file would require: new parser, new CRUD service, new CLI commands, and a foreign-key relationship (goal_title → requirements). This is appropriate for a future iteration if requirements become complex (e.g., per-requirement deadlines, conditions, or dependencies), but is overkill for the current need.

### 3.2 MeasurementLogEntry (NEW — JSONL record)

**File:** `data/measurements.jsonl` (new file, created on first measurement)

Each line is a JSON object:

```json
{"date": "2026-09-06", "metric": "weight", "value": 82.5, "unit": "kg", "goal_title": "Reduce body fat", "collected_at": "2026-09-06T07:15:00+02:00"}
```

**Fields:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `date` | ISO date string | Yes | The day this measurement applies to |
| `metric` | string | Yes | Metric name (must match a requirement's `metric`) |
| `value` | float | Yes | Measured value |
| `unit` | string | Yes | Unit (must match requirement's `unit`) |
| `goal_title` | string | Yes | Goal this measurement belongs to |
| `collected_at` | ISO datetime string | No | When the measurement was actually recorded (timezone-aware). Defaults to midnight of `date` if omitted. |

**Format choice — JSONL:**

- Append-only (no read-modify-write on the file — safe for concurrent appends from different processes).
- Human-readable and grep-able.
- No database dependency.
- Each entry is self-contained (no multi-line records to parse).

**Alternative considered — SQLite:**

Rejected. Adds a runtime dependency and a binary file that is not human-readable or version-controllable. JSONL is sufficient for the expected data volume (dozens to low hundreds of entries per goal).

**Alternative considered — append to goals.md:**

Rejected. Mixing time-series data with goal definitions would make both harder to parse and would bloat the goals file. A separate file keeps concerns separated.

### 3.3 MeasurementLog (service-layer abstraction)

**File:** `src/janus/services/measurement_log.py` (new)

A read-only interface over `measurements.jsonl`:

```python
@dataclass
class MeasurementEntry:
    date: date
    metric: str
    value: float
    unit: str
    goal_title: str
    collected_at: datetime | None = None

def load_entries(path: Path | None = None) -> list[MeasurementEntry]:
    """Load all entries from the JSONL file. Returns [] if file missing."""

def find_last_entry(entries: list[MeasurementEntry], goal_title: str, metric: str) -> MeasurementEntry | None:
    """Return the most recent entry for a given goal + metric, or None."""

def find_entries_since(entries: list[MeasurementEntry], goal_title: str, metric: str, since: date) -> list[MeasurementEntry]:
    """Return all entries on or after `since` for a given goal + metric."""

def append_entry(path: Path, entry: MeasurementEntry) -> None:
    """Append a single entry to the JSONL file. Creates file if missing."""
```

**Rationale:** A small service layer isolates file format details from the collection logic. If the storage format changes (e.g., to SQLite or an API), only this module needs to change.

---

## 4. Measurement Collection Service

**File:** `src/janus/services/measurement_collection.py` (new)

### 4.1 Core function

```python
def get_due_measurements(
    goals: list[Goal],
    entries: list[MeasurementEntry],
    today: date,
    now: time | None = None,
) -> list[MeasurementRequest]:
    """Return measurements that are currently due for collection.

    A measurement is due when:
    1. Its goal is active AND has measurement_requirements.
    2. The frequency schedule says a new collection is due.
    3. If preferred_time is set, the current time is within the preferred window.
    """
```

**Parameters:**

| Parameter | Type | Purpose |
|-----------|------|---------|
| `goals` | list[Goal] | Active goals with potential requirements |
| `entries` | list[MeasurementEntry] | Historical measurement log |
| `today` | date | The date being evaluated (for "is it time today?" logic) |
| `now` | time | Current time (for preferred_time window checks). If None, preferred_time is ignored and all due measurements are returned regardless of time. |

### 4.2 Frequency schedule logic

```python
FREQUENCY_RULES: dict[str, Callable[[date, date | None], bool]] = {
    "daily": lambda today, last_date: last_date is None or last_date < today,
    "twice_weekly": lambda today, last_date: (
        last_date is None
        or (today - last_date).days >= 3
    ),
    "weekly": lambda today, last_date: (
        last_date is None
        or (today - last_date).days >= 7
    ),
    "weekends": lambda today, last_date: (
        today.weekday() in (5, 6)  # Saturday or Sunday
        and (last_date is None or last_date < today)
    ),
    "custom": lambda today, last_date, interval_days: (
        last_date is None
        or (today - last_date).days >= interval_days
    ),
}
```

**Behavior details:**

- **daily:** Due if no entry exists for `today`. One measurement per calendar day, regardless of when it was last recorded. If you record at 23:00, the next is due tomorrow.
- **twice_weekly:** Due if the last entry is 3 or more days ago. This gives a flexible "every 3-4 days" cadence without requiring fixed days of the week.
- **weekly:** Due if the last entry is 7 or more days ago. Simple 7-day cadence from the last recording, not a fixed weekday.
- **weekends:** Due on Saturday or Sunday if no entry has been recorded yet this weekend (since the most recent Friday). This is a special case — it checks that today is a weekend day and no entry exists for either Saturday or Sunday of the current weekend.
- **custom:** Uses `interval_days` from the requirement dict. Due if `today - last_date >= interval_days`.

**Last-entry determination:** The "last date" for frequency checking is the date of the most recent `MeasurementEntry` for the same `goal_title` + `metric` pair, regardless of value. This means recording a value "resets" the schedule for that metric.

### 4.3 Preferred time window logic

```python
PREFERRED_TIME_WINDOWS: dict[str, tuple[int, int]] = {
    "morning": (6, 10),      # 06:00–10:00 (hour 10 is exclusive)
    "afternoon": (12, 14),   # 12:00–14:00
    "evening": (18, 22),     # 18:00–22:00
    "anytime": None,          # No window restriction
}
```

**Behavior:**

- If `now` is `None`, preferred_time is **ignored** and the measurement is returned as due (the caller may not have access to the current time, e.g., a background batch job that runs once per day).
- If `now` is provided and the current hour falls outside the preferred window, the measurement is **not** returned as due. It will become due when the window opens or when `now` is None.
- If `preferred_time` is `"anytime"` or missing from the requirement, no time restriction applies.

**Timezone handling (deferred):** The MVP uses the system local time via `datetime.now().astimezone()`. Travel across timezones is noted as a remaining uncertainty (see §8). A future iteration could store a user timezone preference and use it consistently.

### 4.4 Return type

```python
@dataclass
class MeasurementRequest:
    goal_title: str
    metric: str
    unit: str
    frequency: str
    preferred_time: str | None
    last_recorded: date | None          # date of last measurement, if any
    last_value: float | None            # value of last measurement, if any
    target_value: float | None          # copied from Goal for context
    direction: str | None               # copied from Goal for context
    interval_days: int | None           # only for custom frequency
```

The `target_value` and `direction` fields are included so consumers (e.g., Hermes) can present the measurement in the context of the goal's target — "weigh yourself (last: 82.5 kg, target: 75.0 kg)".

---

## 5. Markdown Persistence Changes

**File:** `src/janus/integrations/markdown_goals.py`

### 5.1 Parse: new fields in `## Goal:` blocks

New lines recognized inside a goal block (before `## Milestones`):

```
Measurement requirements:
  - metric: weight
    unit: kg
    frequency: daily
    preferred_time: morning
  - metric: waist
    unit: cm
    frequency: twice_weekly
    preferred_time: evening
```

**Format rationale:**

- YAML-like indented list (not full YAML — just consistent indentation for readability).
- Each requirement is a `- metric: ...` bullet followed by indented key-value lines.
- `metric` is the only required key in each requirement; others default to sensible values (`frequency: daily`, `preferred_time: anytime`).
- Unknown keys in a requirement block are ignored (matching the existing "unknown field ignored" behavior).

**Parsing state machine changes:**

The existing parser tracks `in_milestones` and `in_milestone`. A new flag `in_measurement_requirements` and `current_requirement: dict | None` track the parsing of a single requirement block.

When `Measurement requirements:` is encountered:
- Set `in_measurement_requirements = True`
- Initialize `current["measurement_requirements"] = []`

When a line starting with `  - metric:` is encountered inside the requirements section:
- Finalize any pending `current_requirement`
- Start a new requirement dict with `metric` set

When an indented key-value line is encountered inside a requirement:
- Parse `key: value` and store in `current_requirement`

When a non-indented line is encountered inside the requirements section:
- Finalize pending requirement
- Exit requirements section (the line is processed as a goal-level field or milestone header)

### 5.2 Serialize: writing requirements back to markdown

In `_format_goal_block()`:

```python
if goal.measurement_requirements:
    lines.append("Measurement requirements:")
    for req in goal.measurement_requirements:
        lines.append(f"  - metric: {req['metric']}")
        if req.get("unit"):
            lines.append(f"    unit: {req['unit']}")
        if req.get("frequency") and req["frequency"] != "daily":
            lines.append(f"    frequency: {req['frequency']}")
        if req.get("preferred_time") and req["preferred_time"] != "anytime":
            lines.append(f"    preferred_time: {req['preferred_time']}")
        if req.get("interval_days"):
            lines.append(f"    interval_days: {req['interval_days']}")
```

Only non-default values are written (frequency defaults to "daily", preferred_time defaults to "anytime"). This keeps the markdown clean.

### 5.3 Unknown field behavior

Unknown keys inside a requirement block are ignored on parse (consistent with how unknown goal-level fields are handled). This means:

- Old files with partial requirements (e.g., only `metric` specified) parse correctly.
- Future extensions (e.g., `conditions`, `deadline`) can be added without breaking old parsers.

---

## 6. Goal CRUD Changes

**File:** `src/janus/services/goals.py`

### 6.1 `add_goal()` — new parameters

```python
def add_goal(
    title: str,
    ...
    measurement_requirements: list[dict] | None = None,
) -> Goal:
```

### 6.2 `update_goal_fields()` — new operations

```python
def update_goal_fields(title: str, **kwargs) -> Goal:
    # New valid kwargs:
    #   add_measurement_requirement: dict   — append a requirement dict
    #   remove_measurement_requirement: str  — remove by metric name
    #   set_measurement_requirements: list[dict] — replace all
    #   (existing kwargs continue to work)
```

**Validation in the service layer:**

When adding or updating a measurement requirement, the service validates:

- `metric` is a non-empty string
- `frequency` is one of the recognized values (or "custom" with `interval_days`)
- `unit` is a non-empty string if provided
- `preferred_time` is one of the recognized values if provided
- `interval_days` is a positive integer if provided (only valid with `frequency: "custom"`)

Validation errors raise `ValueError` with a descriptive message.

**Note:** The Goal model constructor does NOT validate measurement_requirements (they are stored as opaque dicts). Validation happens at the service layer, matching how `related_tasks` is handled (the Goal constructor deduplicates but does not validate task titles).

---

## 7. Integration Points

### 7.1 Daily Briefing — attention items

**File:** `src/janus/services/daily_briefing.py` (consumer, not modified in MVP)

The `get_due_measurements()` function returns a list of `MeasurementRequest`. The Attention Engine or Daily Briefing can convert these into `AttentionItem`s:

```python
# Pseudocode — to be implemented in a follow-up
for req in due_measurements:
    items.append(AttentionItem(
        title=f"{req.metric} — {req.goal_title}",
        reason=f"{req.frequency} measurement due"
                + (f" (preferred: {req.preferred_time})" if req.preferred_time and req.preferred_time != "anytime" else ""),
        score=35,  # Between goal_stalled (40) and goal_inactive (30)
        category="measurement_due",
    ))
```

**Score rationale:** 35 places measurement_due items below goal_stalled (40) and above goal_inactive (30). This means a pending measurement surfaces as a prompt but does not dominate the briefing when a goal is actually stalled. The exact score can be tuned after real-world use.

**Frequency cap in briefing:** To avoid flooding the briefing with many daily measurements, the MVP limits the number of `measurement_due` attention items to a reasonable cap (e.g., 5) in the daily briefing. This is a display concern, not a collection concern — all due measurements are still returned by `get_due_measurements()`.

### 7.2 Weekly Review — compliance reporting

**File:** `src/janus/services/weekly_review.py` (consumer, not modified in MVP)

The weekly review can report measurement compliance per goal:

```python
# Pseudocode — to be implemented in a follow-up
for goal in active_goals:
    if goal.measurement_requirements:
        compliance = compute_measurement_compliance(goal, entries, week_start, week_end)
        # compliance = {"weight": {"daily": 5/7}, "waist": {"twice_weekly": 1/2}}
```

This is a **follow-up** enhancement. The MVP delivers the collection mechanism; compliance reporting is a natural next step that reuses the same data.

### 7.3 CLI — `janus goal measurements`

**File:** `src/janus/goals_cli.py` (consumer, not modified in MVP)

A new subcommand:

```
janus goal measurements          # List all due measurements
janus goal measurements record   # Record a new measurement (interactive or --json)
```

The `record` subcommand appends a new entry to `data/measurements.jsonl` and is the primary way external tools (e.g., Hermes) submit measurement values.

### 7.4 Hermes integration output format

The `get_due_measurements()` function returns `list[MeasurementRequest]`, which is already a structured Python dataclass. For Hermes consumption, it can be serialized as JSON:

```json
[
  {
    "goal_title": "Reduce body fat",
    "metric": "weight",
    "unit": "kg",
    "frequency": "daily",
    "preferred_time": "morning",
    "last_recorded": "2026-09-05",
    "last_value": 82.5,
    "target_value": 75.0,
    "direction": "decrease"
  }
]
```

This is the same format recommended in the research findings (§10.7). No new serialization code is needed — the dataclass fields map directly to JSON keys.

---

## 8. Measurement Source Abstraction

### 8.1 MVP: no source abstraction

For the MVP, there is **no** `MeasurementSource` abstraction. Measurements are recorded as flat entries with a value, unit, and goal reference. Where the value came from (manual entry, scale API, bank export) is not tracked.

**Rationale:** Adding a source abstraction (e.g., `source: "manual" | "withings" | "bank_api"`) would require:

- A source registry
- Per-source parsing/normalization logic
- Auth/credential handling for API sources
- Error handling for source failures

This is scope creep for the MVP. The collection mechanism (frequency, scheduling, due determination) is independent of the source. Sources can be added later as a separate concern.

### 8.2 Future: source field on MeasurementEntry

When source abstraction is needed, the minimal extension is a `source: str` field on `MeasurementEntry` and a `source` key in the requirement dict. The collection logic does not need to change — it only cares about whether a measurement was recorded, not how.

---

## 9. Scheduling Approach

### 9.1 Pull, not push

The MVP uses a **pull model**: consumers call `get_due_measurements()` when they need to know what is due. There is no background scheduler, no cron job inside Janus, and no notification system.

**Consumers that trigger collection:**

| Consumer | Trigger | Action |
|----------|---------|--------|
| Daily Briefing | Each briefing generation | Surfaces due measurements as attention items |
| CLI `janus goal measurements` | Manual invocation | Lists due measurements |
| Hermes (external) | On demand or scheduled externally | Calls the CLI or a future API endpoint |

**Why pull, not push:**

1. Janus has no runtime process — it is a library + CLI. There is nothing to schedule.
2. Hermes (the external agent) manages its own scheduling. It can call Janus on whatever cadence it chooses.
3. A push model would require a scheduler inside Janus, which would add a runtime dependency and a process lifecycle to manage.

### 9.2 When to call get_due_measurements()

The caller decides. Typical patterns:

- **Daily, at the preferred time:** Hermes calls Janus once per morning and once per evening, filters by `preferred_time`, and prompts the user for measurements that are due in that window.
- **On briefing generation:** The daily briefing includes due measurements as attention items.
- **On demand:** The user asks "what measurements do I need to record?" and the CLI or Hermes responds.

### 9.3 Missed collections

If a measurement is not recorded on its due day, the next call to `get_due_measurements()` will still return it as due (the frequency logic checks `last_date < today`, not "was it recorded on the exact due date"). There is no backfill or catch-up mechanism in the MVP — the measurement is simply due again. This is intentional: it avoids complex "make up missed measurements" logic that would be domain-specific.

**Example:** If `weight` (daily) is not recorded on Monday, it will be due on Tuesday (and every day after until recorded). The user records on Tuesday, and the schedule resets from Tuesday.

---

## 10. Frequency & Time Window Reference

### 10.1 Frequency values

| Value | Meaning | Due condition |
|-------|---------|---------------|
| `daily` | Once per calendar day | No entry for `today` |
| `twice_weekly` | Every 3-4 days | Last entry >= 3 days ago |
| `weekly` | Every 7 days | Last entry >= 7 days ago |
| `weekends` | Saturday or Sunday only | Today is Sat/Sun, no entry this weekend |
| `custom` | User-defined interval | Last entry >= `interval_days` ago |

### 10.2 Preferred time values

| Value | Window (local time) | Notes |
|-------|---------------------|-------|
| `morning` | 06:00–10:00 | Exclusive end — 10:00 is not in the window |
| `afternoon` | 12:00–14:00 |  |
| `evening` | 18:00–22:00 |  |
| `anytime` | No restriction | Default if not specified |

### 10.3 Default values

When a requirement is parsed from markdown and a field is missing:

| Field | Default |
|-------|---------|
| `frequency` | `"daily"` |
| `preferred_time` | `"anytime"` |
| `interval_days` | `None` (only used when frequency is `"custom"`) |

---

## 11. Files Changed (MVP)

| File | Change |
|------|--------|
| `src/janus/models/goal.py` | Add `measurement_requirements: list[dict] | None = None` field |
| `src/janus/integrations/markdown_goals.py` | Parse and serialize `Measurement requirements:` section |
| `src/janus/services/goals.py` | Accept `measurement_requirements` in `add_goal()`; handle `add_measurement_requirement`, `remove_measurement_requirement`, `set_measurement_requirements` in `update_goal_fields()` |
| `src/janus/services/measurement_log.py` | **NEW** — MeasurementEntry dataclass + load/find/append functions |
| `src/janus/services/measurement_collection.py` | **NEW** — get_due_measurements() + MeasurementRequest dataclass + frequency/time logic |
| `data/measurements.jsonl` | **NEW** — created on first measurement recording (not shipped in repo) |

---

## 12. Files NOT Changed (MVP)

These are consumers that will use the new service in follow-up work:

| File | Reason for deferral |
|------|---------------------|
| `src/janus/services/attention.py` | Measurement_due attention items — follow-up |
| `src/janus/services/daily_briefing.py` | Surface measurements in briefing — follow-up |
| `src/janus/services/weekly_review.py` | Compliance reporting — follow-up |
| `src/janus/goals_cli.py` | `goal measurements` subcommand — follow-up |
| `src/janus/models/attention.py` | No change needed — AttentionItem already supports arbitrary categories |

---

## 13. Alternatives Considered

### 13.1 Dedicated MeasurementRequirement model + separate persistence file

**What it would look like:** A new `MeasurementRequirement` dataclass, a new `data/measurement_requirements.md` (or JSON) file, a new CRUD service, new CLI commands.

**Why rejected for MVP:** Adds 3-4 new files, a new persistence format, and a foreign-key relationship to manage. The list[dict] approach on Goal achieves the same functional outcome with 2 new service files and a field on an existing model. If requirements become complex (per-requirement deadlines, conditions, dependencies), revisit this.

### 13.2 SQLite for measurement log

**What it would look like:** A `measurements.db` SQLite file with a `measurements` table, queried via SQL for "find last entry" and "find entries in date range".

**Why rejected for MVP:** Binary format, not human-readable, not version-controllable, adds a runtime dependency. JSONL is sufficient for the expected data volume and is easier to inspect/debug.

**When to revisit:** If the measurement log grows beyond tens of thousands of entries and query performance becomes a concern. At that point, SQLite or a lightweight format like DuckDB would be appropriate.

### 13.3 YAML for measurement requirements in goals.md

**What it would look like:** Each requirement as a YAML block:

```
Measurement requirements:
  - metric: weight
    unit: kg
    frequency: daily
```

**Why rejected:** The existing parser already handles a simplified key-value format. Full YAML parsing (with `pyyaml` as a dependency) is heavier than needed. The indented key-value format is sufficient and matches the existing parser style. If the format becomes unwieldy (e.g., nested structures, arrays within requirements), YAML can be adopted at that point.

### 13.4 Push model with internal scheduler

**What it would look like:** A background thread or asyncio task in Janus that periodically checks for due measurements and fires callbacks or writes to a queue.

**Why rejected:** Janus has no runtime process. It is a library + CLI invoked on demand. A scheduler would require a running process, a lifecycle manager, and a notification mechanism — all outside the current architecture. Hermes manages its own scheduling and can call Janus when needed.

### 13.5 Coupled measurement collection into the Attention Engine

**What it would look like:** Add measurement-due logic directly into `assess_goal_stall()` or `get_attention_items()`.

**Why rejected:** The Attention Engine's job is to score what deserves attention. Measurement collection (determining what is due) is a separate concern. Keeping them separate means:

- The collection logic can be tested independently of attention scoring.
- The collection logic can be used by CLI, Hermes, or other consumers without going through the attention pipeline.
- The attention integration is a thin adapter on top of the collection service.

---

## 14. Testing Strategy

### 14.1 Measurement log tests

- Load entries from JSONL (valid file, missing file, empty file)
- Append entry (creates file, appends to existing file)
- Find last entry for a goal+metric (found, not found)
- Find entries since a date

### 14.2 Frequency logic tests

For each frequency value, test:

- Due when no previous entry exists
- Not due when a recent entry exists
- Due when the interval has elapsed
- Edge cases (first day of tracking, interval boundaries)

### 14.3 Preferred time tests

- Due when current time is within the preferred window
- Not due when current time is outside the window
- Due regardless of time when `now=None`
- No restriction when `preferred_time="anytime"`

### 14.4 Parser tests

- Parse a goal with measurement requirements (all fields specified)
- Parse a goal with partial requirements (only metric)
- Parse a goal with multiple requirements
- Unknown keys in a requirement are ignored
- Requirement section ends correctly when a new section starts
- Round-trip: write a goal with requirements, read it back

### 14.5 Integration tests

- `add_goal()` with measurement_requirements
- `update_goal_fields()` with `add_measurement_requirement`
- `update_goal_fields()` with `remove_measurement_requirement`
- `get_due_measurements()` with a realistic goal + log setup

---

## 15. Open Questions (deferred)

1. **Measurement log retention:** How long to keep history? The MVP keeps everything (append-only, no cleanup). A retention policy (e.g., keep 1 year, aggregate older entries) can be added later.

2. **Missed collection handling:** The MVP has no backfill. If a user wants to record a missed daily measurement for a past date, the CLI can support an explicit `--date` flag on the record command. This is a CLI feature, not a collection-logic feature.

3. **Timezone handling:** The MVP uses system local time. A user traveling across timezones may see unexpected due/not-due transitions. A user-level timezone setting (stored in config) can be added later.

4. **Goal UUID migration:** The current `related_tasks: list[str]` and `goal_title` references are string-based and fragile. A UUID-based identity for goals would make measurement log entries more robust. This is a larger refactor and is out of scope for this MVP.

5. **Source abstraction:** Deferred to a future iteration (see §8).

6. **Calibration/normalization:** Some measurements need calibration (e.g., a scale that reports in lbs but the goal is in kg). The MVP does not handle unit conversion. If needed, a conversion layer can be added at the record-ingestion point.

---

## 16. Sequence Diagram (MVP data flow)

```
User/Hermes                  Janus CLI / Library             data/
     │                              │                      │
     │  1. Define goal with         │                      │
     │     measurement_requirements │                      │
     │──────────────────────────────>│                      │
     │                              │  add_goal()          │
     │                              │──────────────────────>│ goals.md
     │                              │                      │ (appended)
     │                              │                      │
     │  2. Daily: "what's due?"     │                      │
     │──────────────────────────────>│                      │
     │                              │  load_goals()        │
     │                              │<──────────────────────│ goals.md
     │                              │                      │
     │                              │  load_entries()      │
     │                              │<──────────────────────│ measurements.jsonl
     │                              │                      │
     │                              │  get_due_measurements()
     │                              │<──────────────────────│
     │  3. Due measurements         │                      │
     │<──────────────────────────────│                      │
     │                              │                      │
     │  4. Record value              │                      │
     │──────────────────────────────>│                      │
     │                              │  append_entry()      │
     │                              │──────────────────────>│ measurements.jsonl
     │                              │                      │ (appended)
     │                              │                      │
     │  5. Next day: "what's due?"  │                      │
     │──────────────────────────────>│                      │
     │                              │  get_due_measurements()
     │                              │ (weight not due,     │
     │                              │  waist is due)       │
     │  6. Due measurements         │                      │
     │<──────────────────────────────│                      │
```

---

**End of design document.**
