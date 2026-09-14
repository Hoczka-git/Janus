---
name: strength
description: "Track, analyze, and ingest strength workouts via the Janus activity ingestion layer."
version: 0.1.0
author: Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [Janus, Strength, Workouts, Analytics, ADR-005, Activity-Data]
    related_skills: [activity-ingestion, running]
---

# Strength Training Workout Tracking & Analysis

Track strength workouts (Workout → Exercise → Set hierarchy), surface
analytics (volume, progression, load), and ingest model-generated activities
through the Janus activity data ingestion layer — **never** by writing to
`data/` directly.

## When to Use

Use this skill whenever a strength workout was:

- **Captured from chat** — the user told Hermes about a lifting session
  (exercises, sets, reps, weight, RPE) and Hermes should record it as a
  structured activity.
- **Received from an external integration** — a Strava / Garmin / Fitbit
  export, a `.csv` or `.json` of workout history is being imported.
- **Derived from a completed Kanban task** — e.g. the task "Do strength
  session" completes and reports its exercises/sets as evidence.
- **Reviewed via CLI** — `janus workout add --type strength ...`,
  `janus workout show --exercise "Back Squat"`,
  `janus workout summary --exercise "Back Squat"`.

Use this skill for the **domain logic** (what fields a strength workout has,
how volume is computed, how a workout is serialized to markdown, how strength
analytics are computed). Do **not** use it for:

- Generic non-strength workouts (use `running` or the appropriate domain skill).
- Goal or task mutation (route those through `goal_progress` /
  `task_completed` ActivityTypes in the activity-ingestion skill).
- Goal-metric aggregation from workouts (this is **not yet wired** — see
  §12 Limitations).

## Dependency: Activity Data Ingestion

This skill MUST use the shared **Activity Data Ingestion** skill for ALL
persistence of activity data.

Shared skill:
`/home/dan11hermes/workspaces/janus/skills/autonomous-ai-agents/activity-ingestion/SKILL.md`

All model-generated strength activity data MUST follow:

```text
Strength Skill (this skill)
  → ActivityRecord(WORKOUT_ADDED, ...)
  → Activity Ingestion: ingest_activities()
  → Janus service / gateway
  → data/
```

The skill MUST NOT:

- directly modify files under `data/`,
- generate or rewrite `data/workouts.md`,
- implement its own persistence or deduplication logic,
- bypass `ActivityRecord` / `ingest_activities()`.

Use the Activity Ingestion skill for:

- validation,
- normalization,
- deduplication,
- idempotency,
- controlled persistence,
- protection of existing data.

---

## Purpose and Scope

### What it does

Provides the Janus **domain slice** for strength workouts:

1. **Domain model** — `StrengthWorkout` dataclass (inherits `Workout`) with
   a nested hierarchy: `StrengthWorkout.exercises: list[Exercise]`, each
   `Exercise` has `sets: list[Set]`. Fields: `Set.reps` (int ≥ 0),
   `Set.weight_kg` (float ≥ 0 or `None` for bodyweight), `Set.rpe`
   (float 1–10 or `None`). All validated at construction.
2. **Serialization** — `_workout_to_markdown_lines()` renders a
   `StrengthWorkout` as `## Workout:` key=value blocks in
   `data/workouts.md` using the existing markdown format (header
   `# Fitness Workouts`, fields `id`, `date`, `workout_type`, `source`,
   `notes`, and `exercises` as a JSON-encoded array).
3. **Parsing** — `load_workouts()` / `dict_to_workout()` read existing
   `data/workouts.md` back into typed objects (round-trip safe).
4. **Analytics** — `compute_exercise_summary()` produces per-exercise
   progression (workout count, latest sets, highest weight, highest
   volume, chronological progression).
   `compute_overall_summary()` handles aggregate counts across all
   workout types.
5. **CLI** — `handle_workout_add`, `handle_workout_show`,
   `handle_workout_summary` in `src/janus/workout_cli.py` with manual arg
   parsing (no argparse).
6. **Model-driven ingestion** — the activity-ingestion gateway's
   `_dispatch_workout()` constructs a `StrengthWorkout` from an
   `ActivityRecord(type=WORKOUT_ADDED, workout_type="strength", ...)`
   and appends it atomically via `read_modify_write_with_retry`.

### What it covers

- Strength workouts only (`workout_type = "strength"`;
  `WorkoutType.STRENGTH`).
- Running workouts are handled by the **sibling** `running` skill; both share
  the `Workout` base model, the `data/workouts.md` file, and the
  `workout_md` / `workout_cli` / `workout_analytics` modules.
- Persistence goes through the activity-ingestion gateway
  (`ActivityType.WORKOUT_ADDED` → `data/workouts.md`, append mode via
  `read_modify_write_with_retry`).

### What is NOT in scope

- Changing the on-disk markdown format of `data/workouts.md`.
- Cross-domain aggregation (workouts → goal progress). This is aspirational
  (see `docs/design/goal_milestone_project_task_hierarchy.md:1563`); the strength
  skill does **not** update goal `Current:` / `Target:` values.
- Wearable sync protocols (Strava API, FIT file parsing) — these are
  separate integrations that produce `ActivityRecord` values which then flow
  through this skill's ingestion path.
- Real-time heart-rate streaming or GPS trace processing — the skill deals
  with summary records, not raw telemetry.

---

## Data Model — Workout → Exercise → Set Hierarchy

### The hierarchy (existing code)

The strength workout hierarchy is modeled in
`src/janus/models/workout.py`:

```text
WorkoutType (enum: strength | running)
│
└── Workout (base dataclass)
    ├── id: str
    ├── date: datetime
    ├── workout_type: WorkoutType
    ├── source: str | None
    ├── created_at: datetime | None
    ├── updated_at: datetime | None
    │
    └── StrengthWorkout(Workout)
        ├── exercises: list[Exercise]
        │   └── Exercise(name: str, sets: list[Set], notes: str | None)
        │       └── Set(reps: int, weight_kg: float | None, rpe: float | None)
        └── notes: str | None
```

### Dataclass definitions (verbatim from source)

```python
@dataclass
class Set:
    reps: int = 0
    weight_kg: float | None = None  # None = bodyweight, 0.0 = zero added weight
    rpe: float | None = None  # 1-10 optional

    def __post_init__(self):
        # reps must be int >= 0
        # weight_kg must be >= 0 or None (bodyweight)
        # rpe must be 1-10 or None

@dataclass
class Exercise:
    name: str
    sets: list[Set] = field(default_factory=list)
    notes: str | None = None

    def __post_init__(self):
        # name must be non-empty string
        # sets must be a list of Set instances
        # notes must be non-empty string or None

@dataclass
class StrengthWorkout(Workout):
    workout_type: WorkoutType = field(default=WorkoutType.STRENGTH)
    exercises: list[Exercise] = field(default_factory=list)
    notes: str | None = None

    def __post_init__(self):
        # exercises must be a list of Exercise instances
        # notes must be non-empty string or None
```

### Validation rules (from `__post_init__`)

| Field | Type | Constraint |
|-------|------|-----------|
| `id` | `str` | Non-empty |
| `date` | `datetime` | Must be a `datetime` |
| `workout_type` | `WorkoutType` | Must be `WorkoutType.STRENGTH` |
| `source` | `str \| None` | Non-empty string if present |
| `exercises` | `list[Exercise]` | List of `Exercise` instances |
| `notes` | `str \| None` | Non-empty string if present |
| `Exercise.name` | `str` | Non-empty |
| `Exercise.sets` | `list[Set]` | List of `Set` instances |
| `Exercise.notes` | `str \| None` | Non-empty string if present |
| `Set.reps` | `int` | `>= 0` |
| `Set.weight_kg` | `float \| None` | `>= 0` or `None` (bodyweight) |
| `Set.rpe` | `float \| None` | `1–10` or `None` |

### On-disk markdown representation

Strength workouts share `data/workouts.md` with running workouts. Each
workout is a `## Workout:` block. Strength-specific fields:

```text
## Workout:
id = sw-001
date = 2026-09-01T10:00:00+00:00
workout_type = strength
source = manual
notes = Back day
exercises = [{"name": "Pull-ups", "sets": [{"reps": 8, "weight_kg": null, "rpe": null}, {"reps": 6, "weight_kg": 12.5, "rpe": 8.0}], "notes": null}, {"name": "Barbell Row", "sets": [{"reps": 5, "weight_kg": 60.0, "rpe": 8.5}], "notes": null}]

---
```

- `exercises` is a **JSON-encoded array** on a single line.
- Each exercise: `{name, sets: [{reps, weight_kg, rpe}], notes}`.
- `weight_kg: null` indicates bodyweight.
- The block ends with `---` on its own line.
- A workout may contain multiple exercises (multi-exercise session).

### Serialization / parsing functions

| Function | Module | Role |
|----------|--------|------|
| `workout_to_dict(workout)` | `workout.py:149` | Serialize any `Workout` to a plain dict |
| `dict_to_workout(data)` | `workout.py:195` | Deserialize a dict back to a `Workout` instance |
| `_workout_to_markdown_lines(workout)` | `workout_md.py:101` | Render a `StrengthWorkout` as `key = value` lines |
| `_finalize_workout(data)` | `workout_md.py:128` | Parse a dict from markdown into a `Workout` (JSON-decodes `exercises`) |

The `exercises` array is JSON-encoded via `json.dumps()` when writing
and JSON-decoded via `json.loads()` when reading. `weight_kg` is
serialized as `null` for bodyweight sets.

---

## How the Model Registers New Workouts / Exercises / Sets

The model MUST NOT edit `data/` files directly. There are **two
registration paths**, both converging on the Activity Ingestion gateway.

### Path A — Human CLI (direct persistence, human-operated)

```sh
janus workout add --type strength \
    --exercise "Back Squat" --sets "5x80kg@8,5x80kg@8.5,5x80kg" \
    --date 2026-09-01 --source manual --notes "Heavy day"
```

`handle_workout_add()` in `src/janus/workout_cli.py`:

1. Parses args manually (no argparse).
2. Parses the `--sets` string via `_parse_sets()` into `list[Set]`.
   Format: `<reps>x<weight>kg@<rpe>`, `<reps>x<weight>kg`, `<reps>x`
   (bodyweight), comma-separated.
3. Generates an ID via `_generate_id(WorkoutType.STRENGTH)` → scans
   existing workouts for max `sw-NNN` prefix, increments.
4. Constructs a `StrengthWorkout` dataclass.
5. Calls `save_workout(workout)` → `_write_workouts(existing + [new])`
   → `protected_write()` → `atomic_write()` via `data_protection`.
6. Prints confirmation: `Added workout: sw-005`.

**This is the human-driven path.** It is permitted to call the
persistence layer directly. Model-driven code must use Path B.

### Path B — Model-driven ingestion (Hermes → Janus, via Activity Ingestion)

When Hermes captures a strength workout from chat, a wearable sync, or
a completed Kanban task, it emits an `ActivityRecord`:

```python
from janus.services.activity_ingest import (
    ActivityRecord, ActivityType, ingest_activities,
)
from datetime import datetime, timezone

now = datetime(2026, 9, 12, 14, 30, tzinfo=timezone.utc)

records = [
    ActivityRecord(
        type=ActivityType.WORKOUT_ADDED,
        source="chat",
        timestamp=now,
        workout_type="strength",
        date="2026-09-12",
        evidence={
            "notes": "Leg day — felt strong",
            "date": "2026-09-12",          # critical for dedup key fallback
            "exercises": [
                {
                    "name": "Back Squat",
                    "sets": [
                        {"reps": 5, "weight_kg": 80.0, "rpe": 8.0},
                        {"reps": 5, "weight_kg": 80.0, "rpe": 8.5},
                        {"reps": 5, "weight_kg": 80.0, "rpe": 9.0},
                    ],
                    "notes": None,
                },
                {
                    "name": "Walking Lunges",
                    "sets": [
                        {"reps": 16, "weight_kg": None, "rpe": 8.0},
                        {"reps": 16, "weight_kg": None, "rpe": 8.0},
                    ],
                    "notes": "Bodyweight",
                },
            ],
        },
    )
]

results = ingest_activities(records)
for r in results:
    if r.accepted:
        print(f"OK  {r.action:>8}  {r.file_path}  {r.record_id}")
    else:
        print(f"ERR {r.action:>8}  {r.file_path}  {r.record_id}  {r.error!r}")
```

The gateway's `_dispatch_workout()` (in `activity_ingest.py:877`):

1. Reads `workout_type` → `WorkoutType.STRENGTH`.
2. Constructs a `StrengthWorkout`:
   - `id = record.workout_id or _gen_uuid("w")` → `w-<8-hex>`
   - `exercises = record.evidence.get("exercises", [])` if it is a list
   - `notes = record.evidence.get("notes")` if it is a string
3. Serializes via `_workout_to_markdown_lines(workout)`.
4. Appends the new `## Workout:` block to `data/workouts.md` through
   `read_modify_write_with_retry()` (atomic, with retry-on-concurrency).
5. Emits `service.activity_ingest.record_accepted` event.

### Data entry surface — field table

| Field | ActivityRecord field | Notes |
|-------|---------------------|-------|
| Workout type | `workout_type="strength"` | Must be `"strength"` — gateway calls `WorkoutType("strength")` |
| Exercises | `evidence["exercises"]` | **Required.** List of dicts with `name`, `sets`, `notes`. |
| Set reps | `evidence["exercises"][i]["sets"][j]["reps"]` | Integer `>= 0`. |
| Set weight | `evidence["exercises"][i]["sets"][j]["weight_kg"]` | Float `>= 0`, or `None` for bodyweight. |
| Set RPE | `evidence["exercises"][i]["sets"][j]["rpe"]` | Float `1–10`, or `None`. |
| Notes | `evidence["notes"]` | Workout-level free text (optional). |
| Date | `evidence["date"]` or `record.date` | **Critical for dedup** — ISO date string `YYYY-MM-DD`. |
| Workout ID | `workout_id` | If absent, generated as `w-<8-hex>`. |
| Source | `source` (top-level) | `"hermes_kanban"`, `"chat"`, `"manual"`, etc. |

**Important:** The model emits `exercises` as plain dicts in `evidence`.
The gateway constructs `Set` / `Exercise` / `StrengthWorkout` instances
from these dicts. The dataclass `__post_init__` validators enforce
type/range constraints (reps `>= 0`, weight `>= 0` or `None`, RPE in
`1–10` or `None`). If the domain model raises `ValueError`, the gateway
catches it and returns `IngestResult(accepted=True, wrote=False,
error="dispatch: ...")`.

### Multiple exercises per workout

A single `StrengthWorkout` may contain multiple exercises. The model
emits them all in `evidence["exercises"]` as a list. The gateway
constructs them in order. No separate registration flow is needed per
exercise — they are all part of one workout record.

### ID generation

- **CLI path:** `_generate_id(WorkoutType.STRENGTH)` → scans existing
  workouts, finds the max numeric prefix for `sw-NNN`, increments by 1.
  Format: `sw-001`, `sw-002`, etc.
- **Model-driven path:** If `record.workout_id` is absent,
  `_gen_uuid("w")` generates `w-<8-hex>`. The model SHOULD provide
  explicit `workout_id` values when it knows them (e.g. `sw-005` from
  a scanned counter), to enable dedup.

---

## Data Normalization Rules

Normalization runs **inside** `ingest_activities()` (via
`_normalize_record()`), before validation and persistence. This skill does
NOT implement its own normalization — it relies on the Activity Ingestion
skill.

Rules that apply to strength workout records:

1. **Timestamps** → naive datetimes are assumed local and converted to
   UTC; stored as ISO 8601. `record.timestamp` is used as the workout
   `date` (and `created_at` / `updated_at`).
2. **Free text** (`notes`, `source`) → control characters stripped,
   whitespace trimmed (`_normalize_text`).
3. **Units** → strength metrics (`weight_kg`, RPE) are NOT subject to
   unit normalization. They are domain-specific scalars stored in their
   native units (kg for weight, 1–10 for RPE). The Activity Ingestion
   skill's unit normalization only applies to `MEASUREMENT` /
   `GOAL_UPDATED` records via `normalization_units`.
4. **Exercise sets** → `weight_kg` is `None` for bodyweight; `0.0` for
   zero added weight. These are distinct. `reps` is an integer `>= 0`.
   `rpe` is a float in `[1, 10]` or `None`.

---

## Analysis Capabilities

### Exercise summary — `compute_exercise_summary(workouts, exercise_name)`

Located in `src/janus/services/workout_analytics.py:161-234`.
Pure function; no side effects; input is `list[Workout]` (already
loaded from `data/workouts.md`).

Returns an `ExerciseSummary` dataclass:

| Field | Type | Computation |
|-------|------|-------------|
| `workout_count` | `int` | Count of strength workouts containing the named exercise |
| `latest_sets_description` | `str \| None` | E.g. `"5x80.0kg@8.0, 5x80.0kg@8.5, 5x80.0kg@9.0"` from the most recent workout |
| `highest_weight_kg` | `float \| None` | Max `weight_kg` across all sets of the exercise (bodyweight sets excluded — `None` weight) |
| `highest_workout_volume_kg` | `float` | Max `(sum of weight_kg × reps)` per workout containing the exercise |
| `chronological_progression` | `list[ExerciseProgressionPoint]` | One point per workout, ascending by date |

`ExerciseProgressionPoint`:

| Field | Type | Computation |
|-------|------|-------------|
| `date` | `datetime` | Workout date |
| `max_weight_kg` | `float \| None` | Heaviest loaded set weight in that workout (`None` if all bodyweight) |
| `total_volume_kg` | `float` | `sum(weight_kg × reps)` across all sets in that workout (0.0 if all bodyweight) |

**Key behaviors:**

- Matching is **case-insensitive** on exercise name.
- Only `StrengthWorkout` instances are scanned; running workouts are
  skipped.
- Bodyweight sets (`weight_kg is None`) contribute to set count and
  `latest_sets_description` (weight is simply omitted) but contribute
  `0.0` to volume and are excluded from `highest_weight_kg`.
- Latest sets description format: `<reps>x<weight>kg@<rpe>` joined by
  `, `. E.g. `"5x80.0kg@8.0, 5x80.0kg@8.5"`. For bodyweight sets
  (`weight_kg is None`), the weight portion is omitted entirely:
  `<reps>x@<rpe>` or `<reps>x` if RPE is also `None`.

### Overall summary — `compute_overall_summary(workouts)`

| Field | Computation |
|-------|-------------|
| `total_workouts` | All loaded workouts |
| `strength_count` | Count of `StrengthWorkout` |
| `running_count` | Count of `RunningWorkout` |
| `most_recent_workout_id` | Sort by date desc, take first |
| `most_recent_date` | Most recent workout date |

### CLI access

```sh
janus workout summary --exercise "Back Squat"  # per-exercise progression
janus workout show --exercise "Back Squat"     # all workouts with that exercise
janus workout show sw-001                       # single workout by ID
janus workout show                             # last 5 workouts (overall)
janus workout summary                          # overall summary
```

The `handle_workout_summary()` handler (line 512) dispatches:

- `--exercise NAME` → `compute_exercise_summary(workouts, NAME)`
- `--running` → `compute_running_summary(workouts)`
- default → `compute_overall_summary(workouts)`

### Query functions

| Function | Source | Purpose |
|----------|--------|---------|
| `find_history_by_exercise(name)` | `workout_md.py:160` | All `StrengthWorkout` containing the named exercise (case-insensitive) |
| `find_workout_by_id(workout_id)` | `workout_md.py:189` | Single by ID or `None` |
| `find_last_n(n)` | `workout_md.py:180` | Most recent first (all types) |
| `find_running_workouts()` | `workout_md.py:174` | All `RunningWorkout` (sibling skill) |
| `load_workouts()` | `workout_md.py:40` | All workouts (strength + running) |

### Strength vs. Running Fields

Both workout types share the same `data/workouts.md` file and the same
`## Workout:` block format. They diverge in which fields are serialized:

| Aspect | Strength | Running |
|--------|----------|---------|
| ID prefix | `sw-NNN` (CLI) or `w-<hex>` (model) | `rw-NNN` (CLI) or `w-<hex>` (model) |
| Scalar metrics | None | `distance_km`, `duration_minutes`, `avg_hr_bpm`, `elevation_m` |
| Nested structure | `exercises = [{name, sets: [{reps, weight_kg, rpe}], notes}]` | None |
| Notes | Workout-level `notes` | Workout-level `notes` |

---

## Safety Constraints

### data/ protection rules (MUST follow)

The strength skill MUST NOT:

- **Directly modify files under `data/`.** Never call `Path.write_text()`,
  `open(..., "w")`, or any I/O targeting `data/workouts.md` from
  model-driven code. All persistence flows through the Activity Ingestion
  gateway (`ActivityRecord` → `ingest_activities()` →
  `read_modify_write_with_retry` → `atomic_write`).
- **Generate or rewrite `data/workouts.md`.** The model emits structured
  `ActivityRecord` values; the gateway owns serialization via the existing
  `_workout_to_markdown_lines()`.
- **Implement its own persistence or deduplication logic.** No custom
  `save_workouts()` or dedup logic in the strength skill. Use the gateway's
  `_dispatch_workout()` / `read_modify_write_with_retry()`.
- **Bypass `ActivityRecord` / `ingest_activities()`.** Never call
  `workout_md.save_workout()` from model-driven code. The CLI path
  (`handle_workout_add`) is the exception — it is a human-operated path that
  calls `save_workout()` directly.

### Atomic-write guarantees

All writes to `data/workouts.md` go through `atomic_io.read_modify_write`
or `read_modify_write_with_retry`:

1. **Write-to-temp + `os.replace`** — atomic on POSIX; never a torn file.
2. **Concurrent-write detection** — `_FileSnapshot` (mtime + size + inode)
   compared after the read; `ConcurrentWriteError` raised on mismatch.
3. **Retry with exponential backoff** — up to `cfg.write_retry_count`
   (default 3) times.
4. **Backup** — a `.bak` snapshot is created before overwrite
   (`backup_previous()` in `data_protection.py`).

### Regeneration gate

`workout_md._write_workouts` is in the `allowed_regenerators` set
(`data_protection.py:132`), so the full-file rewrite path (used by the CLI
`save_workout` → `_write_workouts` → `all_workouts` round-trip) is
permitted to replace the entire file when it exceeds the 50% change
threshold. **Model-driven code does not go through this path** — it
appends via `read_modify_write_with_retry`.

### Validation enforcement

- **Domain model validation:** `StrengthWorkout.__post_init__` rejects
  invalid data at construction (non-Exercise items in `exercises`,
  non-Set items in `sets`, empty exercise names, invalid reps/weight/RPE).
  The gateway's `_dispatch_workout` constructs the `StrengthWorkout` from
  the `ActivityRecord`; if the domain model raises `ValueError`, the
  gateway catches it and returns `IngestResult(accepted=True,
  wrote=False, error="dispatch: ...")`.
- **Gateway validation:** `_validate_record` checks that `workout_type`
  is present for `WORKOUT_ADDED` records.

---

## Integration Points

### Janus system layers

| Layer | Module | Role for strength |
|-------|--------|-------------------|
| **Model** | `src/janus/models/workout.py` | `StrengthWorkout`, `Exercise`, `Set` dataclasses + validation |
| **Persistence** | `src/janus/integrations/workout_md.py` | `load_workouts`, `save_workout`, `find_history_by_exercise`, `_workout_to_markdown_lines` |
| **Service** | `src/janus/services/workout_analytics.py` | `compute_exercise_summary`, `compute_overall_summary` |
| **CLI** | `src/janus/workout_cli.py` | `handle_workout_add`, `handle_workout_show`, `handle_workout_summary` |
| **Gateway** | `src/janus/services/activity_ingest.py` | `_dispatch_workout` — model-driven ingestion path |

### Data file

| File | Format | Access |
|------|--------|--------|
| `data/workouts.md` | `# Fitness Workouts` header; `## Workout:` blocks with `key = value` fields; `exercises` as JSON for strength; `---` separator | Load via `load_workouts()`; append via gateway's `_dispatch_workout` |

### Config

| Section | File | Strength-relevant keys |
|---------|------|------------------------|
| `[data_ingestion]` | `config/config.toml` (from `config.example.toml`) | `dedup_policy`, `dedup_tolerance_seconds`, `write_retry_count`, `write_retry_backoff_base` |
| `[data_ingestion.files]` | `config/config.example.toml` | `"workout_added" = "data/workouts.md"` (default, currently commented) |
| `[data_protection]` | `config/config.toml` | `regeneration_threshold`, `allowed_regenerators`, backup settings |

### Observability

All ingestion emits structured events via `janus._log.emit` under the
`service.activity_ingest.*` namespace:

- `service.activity_ingest.record_accepted` — successful workout append
- `service.activity_ingest.record_rejected` — validation or dedup reject
- `service.activity_ingest.write_failed` — persistence failure
- `service.activity_ingest.dedup_replace` — duplicate replaced (policy=replace)

### CLI integration

The main Janus CLI (`src/janus/cli.py`) dispatches `workout` subcommands
to `workout_cli.handle_workout_add` / `handle_workout_show` /
`handle_workout_summary`. (This is an existing pattern, not a new
integration — see `src/janus/workout_cli.py:113`.)

---

## Dedup Key Rules (for WORKOUT_ADDED, strength)

From ADR-005 §3 and `compute_dedup_key()` in `activity_ingest.py:169`:

| Condition | Dedup key |
|-----------|-----------|
| `record.workout_id` is set | `record.workout_id` |
| `evidence["date"]` is set | `<evidence["date"]>::strength` |
| `record.date` is set | `<record.date>::strength` |
| Neither date nor workout_id | `"::strength"` — **degenerate, causes spurious duplicates** |

**Action for the model:** Always populate `evidence["date"]` (an ISO
date string like `"2026-09-12"`) or `record.date`, and always set
`workout_id` when the workout has a known ID. The CLI path generates IDs
as `sw-NNN` (auto-incremented); the model-driven path generates
`w-<8-hex>` UUIDs if none is provided.

**Caveat for multi-exercise workouts:** Two strength workouts on the
same date with different exercises will share the dedup key
`<date>::strength`. The model should provide an explicit `workout_id`
when logging multiple strength sessions on the same day, or accept that
only the first will be persisted under the default reject policy.

---

## Limitations

1. **No cross-domain goal aggregation.** The strength skill does not
   update `data/goals.md` when a workout is added. This is tracked as
   aspirational in `docs/design/goal_milestone_project_task_hierarchy.md:1563`.
2. **No wearable sync.** Strava / Garmin / FIT / GPX import is a
   separate integration that must produce `ActivityRecord` values before
   routing through this skill's ingestion path.
3. **No real-time telemetry.** The skill deals with summary workout
   records, not raw GPS traces or HR time series.
4. **Dedup key degenerates without dates.** A `WORKOUT_ADDED` without
   `workout_id` and without `date` / `evidence["date"]` produces the key
   `"::strength"`, which matches every undated strength workout of the
   same type. The model must always supply a date.
5. **Multi-exercise same-day dedup.** Two strength workouts on the same
   date share the dedup key `<date>::strength`; the model should supply
   explicit `workout_id` for same-day multi-session logging.
6. **No strength-specific CLI `show` filter.** There is no
   `janus workout show --strength` filter; strength workouts appear in
   the default `show` (last N) and can be queried individually by ID or
   via `--exercise NAME`. (Planned extension: add `find_strength_workouts()`
   and a `--strength` flag.)

---

## References

- `docs/decisions/005-activity-data-ingestion-layer.md` — ADR-005 (the
  ingestion gateway design)
- `docs/guides/activity_data_guide.md` — operational guide for the ingestion layer
- `docs/strength-skill-spec.md` — this specification (detailed blueprint)
- `src/janus/models/workout.py` — `StrengthWorkout`, `Exercise`, `Set` dataclasses + validation
- `src/janus/integrations/workout_md.py` — persistence layer
- `src/janus/services/workout_analytics.py` — analytics functions
- `src/janus/workout_cli.py` — CLI handlers
- `src/janus/services/activity_ingest.py` — the ingestion gateway
  (`_dispatch_workout`, `compute_dedup_key`, `_validate_record`)
- `src/janus/integrations/atomic_io.py` — atomic write primitives
- `src/janus/integrations/data_protection.py` — regeneration gate, backups
- `config/config.example.toml` — `[data_ingestion]` configuration
- `data/workouts.md` — the persisted fitness workout data (shared by running + strength)
- `tests/test_fitness.py` — model validation + persistence round-trip tests
- `tests/test_workout_cli.py` — CLI handler tests
- `tests/test_workout_analytics.py` — analytics correctness tests
- `scripts/repair_workouts.py` — data repair utility (context for why atomic writes matter)
- Parent skill: `skills/autonomous-ai-agents/activity-ingestion/SKILL.md`
  — the mandatory ingestion gateway this skill depends on
- Sibling skill: `skills/autonomous-ai-agents/running/SKILL.md`
  — the running workout skill (shared model, persistence, analytics)

---

## Verification Checklist

Before declaring the strength skill implemented, confirm:

1. **Import works:** constructing a `StrengthWorkout` with valid fields
   succeeds; invalid fields raise `ValueError` (see `test_fitness.py`).
2. **Round-trip:** `save_workout(workout)` → `load_workouts()` returns an
   equivalent `StrengthWorkout` with all fields preserved (exercises,
   sets, weights, RPE, notes).
3. **Exercise serialization:** `_workout_to_markdown_lines()` produces
   the `exercises = [{...}]` JSON field that `_finalize_workout()` can
   parse back into `Exercise`/`Set` objects (round-trip safe).
4. **Bodyweight handling:** `Set(weight_kg=None)` serializes as
   `"weight_kg": null` in the JSON and round-trips correctly.
5. **Analytics — volume:** `compute_exercise_summary()` returns
   `highest_workout_volume_kg = sum(weight_kg × reps)` per workout.
6. **Analytics — bodyweight excluded:** `highest_weight_kg` excludes
   `None` weight sets; `total_volume_kg` is `0.0` for all-bodyweight
   workouts.
7. **Analytics — case-insensitive:** `compute_exercise_summary()`
   matches exercise names case-insensitively.
8. **Analytics — progression:** `chronological_progression` is sorted
   ascending by date, one point per workout.
9. **CLI:** `janus workout add --type strength --exercise "Back Squat"
   --sets "5x80kg@8"` produces `sw-001` and persists to
   `data/workouts.md`; `janus workout show --exercise "Back Squat"` lists
   it; `janus workout summary --exercise "Back Squat"` prints correct
   volume and latest sets.
10. **Ingestion gateway:** an
    `ActivityRecord(type=WORKOUT_ADDED, workout_type="strength",
    evidence={"exercises": [...], "date": "2026-09-12"})` passed to
    `ingest_activities()` results in an `IngestResult` with
    `accepted=True`, `action="appended"`, and `file_path` pointing to
    `data/workouts.md`.
11. **Dedup:** a second identical `WORKOUT_ADDED` record (same date +
    type, no `workout_id`) is rejected under the default `policy="reject"`.
12. **No direct data/ writes:** no model-driven code path calls
    `workout_md.save_workout()` or `atomic_write` on `data/workouts.md`
    directly — all go through `ingest_activities()`.
