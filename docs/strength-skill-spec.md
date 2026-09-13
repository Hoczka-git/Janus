# Strength Training Skill Specification

> Concrete specification for the **strength** domain skill
> (`skills/autonomous-ai-agents/strength/SKILL.md`). This document is the
> blueprint implementers follow to build the strength slice. The finished
> skill SKILL.md will mirror the running skill's structure but specialize
> every section for the `StrengthWorkout → Exercise → Set` hierarchy.

**Status:** Specification — ready for implementation
**Parent task:** t_00b27784 (Define skill specification for strength training domain)
**Related:** running skill `skills/autonomous-ai-agents/running/SKILL.md`,
activity-ingestion `skills/autonomous-ai-agents/activity-ingestion/SKILL.md`

---

## 1. Dependency: Activity Ingestion

This skill MUST use the shared **Activity Data Ingestion** skill for ALL
persistence of activity data. This dependency is non-optional — every
model-driven write must route through it.

Shared skill (absolute path):
`/home/dan11hermes/workspaces/janus/skills/autonomous-ai-agents/activity-ingestion/SKILL.md`

```text
Domain Skill (this skill)
  → ActivityRecord(WORKOUT_ADDED, ...)
  → Activity Ingestion: ingest_activities()
  → Janus service / gateway
  → data/
```

The skill MUST NOT:

- **Directly modify files under `data/`.** Never call `Path.write_text()`,
  `open(..., "w")`, or any I/O targeting `data/workouts.md` (or any other
  `data/` file) from model-driven code.
- **Generate or rewrite `data/workouts.md`.** The model emits structured
  `ActivityRecord` values; the gateway owns serialization via the existing
  `_workout_to_markdown_lines()`. The model never hand-writes `## Workout:`
  blocks or any markdown into `data/`.
- **Implement its own persistence or deduplication logic.** No custom
  `save_workouts()` or dedup logic in the strength skill. Use the gateway's
  `_dispatch_workout()` / `read_modify_write_with_retry()`.
- **Bypass `ActivityRecord` / `ingest_activities()`.** Never call
  `workout_md.save_workout()` from model-driven code. The CLI path
  (`handle_workout_add`) is the exception — it is a human-operated path that
  calls `save_workout()` directly.

Use the Activity Ingestion skill for:

- validation,
- normalization,
- deduplication,
- idempotency,
- controlled persistence,
- protection of existing data.

---

## 2. Data Model — Workout → Exercise → Set Hierarchy

### 2.1 The hierarchy (existing code)

The strength workout hierarchy is already modeled in
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

### 2.2 Dataclass definitions (verbatim from source)

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

### 2.3 Validation rules (from `__post_init__`)

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

### 2.4 On-disk markdown representation

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

### 2.5 Serialization / parsing functions

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

## 3. How the Model Registers New Workouts / Exercises / Sets

The model MUST NOT edit `data/` files directly. There are **two
registration paths**, both converging on the Activity Ingestion gateway.

### 3.1 Path A — Human CLI (direct persistence, human-operated)

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

### 3.2 Path B — Model-driven ingestion (Hermes → Janus, via Activity Ingestion)

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

### What the model emits vs. what it never touches

| | What the model emits | What the model NEVER touches |
|---|---|---|
| **Type** | `ActivityRecord(type=WORKOUT_ADDED, ...)` dataclass instances | `data/workouts.md` file path, file handle, or file content |
| **Structure** | `evidence["exercises"]` as a list of dicts, `evidence["notes"]` as a string, `workout_type="strength"`, `date` / `evidence["date"]` as ISO string, optional `workout_id` | The `## Workout:` markdown block format, the `# Fitness Workouts` header, the `---` separator |
| **Persistence call** | `ingest_activities(records)` — the single gateway entry point | `workout_md.save_workout()`, `workout_md._write_workouts()`, `atomic_io.atomic_write()`, or any direct file I/O to `data/` |
| **Dedup** | A `workout_id` or a date + `workout_type` so `compute_dedup_key()` can form a key | Dedup policy selection, tolerance windows, duplicate detection logic |
| **Normalization** | ISO 8601 timestamps (UTC), `weight_kg` in kg, RPE in 1–10 range, `notes` as free text | Unit conversion rules, text sanitization, timestamp timezone conversion |
| **Response** | Receives `list[IngestResult]` with `accepted`, `wrote`, `action`, `error` | The internal dispatch table, the `read_modify_write_with_retry` implementation, the `.bak` backup mechanism |

The model hands structured `ActivityRecord` objects to the Activity Ingestion
skill and receives `IngestResult` objects back. It never touches `data/`
files, never serializes markdown, and never invokes persistence or dedup
primitives directly.

### 3.3 Data entry surface — field table

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

### 3.4 Multiple exercises per workout

A single `StrengthWorkout` may contain multiple exercises. The model
emits them all in `evidence["exercises"]` as a list. The gateway
constructs them in order. No separate registration flow is needed per
exercise — they are all part of one workout record.

### 3.5 ID generation

- **CLI path:** `_generate_id(WorkoutType.STRENGTH)` → scans existing
  workouts, finds the max numeric prefix for `sw-NNN`, increments by 1.
  Format: `sw-001`, `sw-002`, etc.
- **Model-driven path:** If `record.workout_id` is absent,
  `_gen_uuid("w")` generates `w-<8-hex>`. The model SHOULD provide
  explicit `workout_id` values when it knows them (e.g. `sw-005` from
  a scanned counter), to enable dedup.

---

## 4. Data Normalization Rules

Normalization runs **inside** `ingest_activities()` (via
`_normalize_record()`), before validation and persistence. This skill
does NOT implement its own normalization — it relies on the Activity
Ingestion skill.

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

## 5. Analysis Capabilities

### 5.1 Exercise summary — `compute_exercise_summary(workouts, exercise_name)`

Located in `src/janus/services/workout_analytics.py:161-234`.

**Analysis read path:** Analysis functions are **read-only** pure functions.
They receive already-loaded `list[Workout]` objects (loaded from
`data/workouts.md` via `load_workouts()` in `workout_md.py`). Analysis does
NOT write back to `data/` — it does NOT call `ingest_activities()` or any
persistence path. The data is read from `data/workouts.md` through the Janus
service/gateway layer (`workout_md.load_workouts()`), analyzed in memory, and
results are surfaced only to the caller (CLI output, model context). No
analysis function modifies `data/` files.

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
  `latest_sets_description` (weight is simply omitted — see code below)
  but contribute `0.0` to volume and are excluded from `highest_weight_kg`.
- Latest sets description format: `<reps>x<weight>kg@<rpe>` joined by
  `, `. E.g. `"5x80.0kg@8.0, 5x80.0kg@8.5"`. For bodyweight sets
  (`weight_kg is None`), the weight portion is omitted entirely:
  `<reps>x@<rpe>` or `<reps>x` if RPE is also `None`. (Format defined
  in `workout_analytics.py:192-200`. Note: this differs from the CLI
  display in `workout_cli.py:329-342` which uses `_format_set_weight`
  to render bodyweight as the string `"bodyweight"`.)

### 5.2 Overall summary — `compute_overall_summary(workouts)`

| Field | Computation |
|-------|-------------|
| `total_workouts` | All loaded workouts |
| `strength_count` | Count of `StrengthWorkout` |
| `running_count` | Count of `RunningWorkout` |
| `most_recent_workout_id` | Sort by date desc, take first |
| `most_recent_date` | Most recent workout date |

### 5.3 Strength-specific queries (not yet implemented — planned extension)

The following query functions are **planned** for the strength skill but
do NOT currently exist in `workout_md.py`. The implementer should add
them to mirror the running equivalents:

| Function | Proposed location | Purpose |
|----------|-------------------|---------|
| `find_strength_workouts()` | `workout_md.py` | All `StrengthWorkout` instances (mirrors `find_running_workouts()`) |
| `find_exercises()` | `workout_md.py` | Deduplicated list of all exercise names across all strength workouts |

### 5.4 CLI access

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

No changes to `workout_cli.py` are needed for the strength skill spec —
the existing CLI already handles `--exercise` for strength workouts.

---

## 6. Location and Supporting Files

### 6.1 Skill file

```
skills/autonomous-ai-agents/strength/SKILL.md
```

The directory `skills/autonomous-ai-agents/strength/` **already exists** (created
in commit `022b61e` — "docs: strength training skill SKILL.md"). It contains
`SKILL.md`. This document (`docs/strength-skill-spec.md`) is the detailed
blueprint that the SKILL.md mirrors and is derived from.

### 6.2 Existing implementation surface (no new files required)

| File | Role |
|------|------|
| `src/janus/models/workout.py` | `StrengthWorkout`, `Exercise`, `Set` dataclasses + validation (lines 1–263) |
| `src/janus/integrations/workout_md.py` | Persistence: `load_workouts`, `save_workout`, `_workout_to_markdown_lines`, `_finalize_workout`, `find_history_by_exercise`, `find_workout_by_id` (lines 1–195) |
| `src/janus/services/workout_analytics.py` | Analytics: `compute_exercise_summary`, `compute_overall_summary` (lines 1–234) |
| `src/janus/workout_cli.py` | CLI: `handle_workout_add`, `handle_workout_show`, `handle_workout_summary` (lines 1–603) |
| `src/janus/services/activity_ingest.py` | Gateway: `_dispatch_workout`, `compute_dedup_key`, `ActivityRecord`, `ActivityType.WORKOUT_ADDED` (lines 1–1042) |
| `src/janus/integrations/atomic_io.py` | Atomic write primitives: `atomic_write`, `read_modify_write`, `read_modify_write_with_retry` (lines 1–~200) |
| `src/janus/integrations/data_protection.py` | Regeneration gate, backup rotation, `protected_write` |
| `config/config.example.toml` | `[data_ingestion]` + `[data_ingestion.files]` config |
| `data/workouts.md` | The persisted fitness workout data (shared by running + strength) |

### 6.3 Reference specs

| File | Purpose |
||------|---------|
|| `docs/strength-skill-spec.md` | This specification |
|| `docs/decisions/005-activity-data-ingestion-layer.md` | ADR-005: the ingestion gateway design |
|| `docs/activity_data_guide.md` | Operational guide for the ingestion layer |
|| `findings/skills_layout_and_activity_ingestion.md` | Inspection findings: skills layout + Activity Ingestion interface contract |
|| `docs/goal_milestone_project_task_hierarchy.md:1563` | Aspirational cross-domain workout → goal progress aggregation |

### Parent skill (mandatory dependency)

```
/home/dan11hermes/workspaces/janus/skills/autonomous-ai-agents/activity-ingestion/SKILL.md
```

The Activity Ingestion skill is the single controlled-write gateway for all
model-driven persistence. It provides:

- **Validation** — `_validate_record` enforces `ActivityType`-specific field
  requirements; domain model `__post_init__` validators enforce type/range
  constraints.
- **Normalization** — timestamps → UTC, free text stripped of control chars,
  units converted via `[data_ingestion.normalization.units.<metric>]`.
- **Deduplication** — `compute_dedup_key()` + configurable `dedup_policy`
  (`reject` / `merge` / `replace`) + `dedup_tolerance_seconds` window.
- **Idempotency** — safe to re-ingest; duplicates are detected and handled
  per policy.
- **Controlled persistence** — all writes through
  `atomic_io.read_modify_write` / `read_modify_write_with_retry`
  (`write-to-temp + os.replace`, retry with backoff, `.bak` backup).
- **Protection of existing data** — the `data_protection` regeneration gate
  (`allowed_regenerators`, `regeneration_threshold`), concurrent-write
  detection via `_FileSnapshot` (mtime + size + inode), and atomic
  `os.replace` ensure no torn writes or data loss.

---

## 7. Dedup Key Rules (for WORKOUT_ADDED, strength)

From ADR-005 §3 and `compute_dedup_key()` in `activity_ingest.py:169`:

| Condition | Dedup key |
|-----------|-----------|
| `record.workout_id` is set | `record.workout_id` |
| `evidence["date"]` is set | `<evidence["date"]>::strength` |
| `record.date` is set | `<record.date>::strength` |
| Neither date nor workout_id | `"::strength"` — **degenerate, causes spurious duplicates** |

**Action for the model:** Always populate `evidence["date"]` (an ISO
date string like `"2026-09-12"`) or `record.date`, and always set
`workout_id` when the workout has a known ID. A second
`WORKOUT_ADDED` with the same date + type and no `workout_id` is
rejected under the default `policy="reject"`.

**Caveat for multi-exercise workouts:** Two strength workouts on the
same date with different exercises will share the dedup key
`<date>::strength`. The model should provide an explicit `workout_id`
when logging multiple strength sessions on the same day, or accept that
only the first will be persisted under the default reject policy.

---

## 8. Safety Constraints

### 8.1 data/ protection rules (MUST follow)

The strength skill MUST NOT:

- **Directly modify files under `data/`.** Never call `Path.write_text()`,
  `open(..., "w")`, or any I/O targeting `data/workouts.md` from
  model-driven code.
- **Generate or rewrite `data/workouts.md`.** The model emits structured
  `ActivityRecord` values; the gateway owns serialization via the existing
  `_workout_to_markdown_lines()`.
- **Implement its own persistence or deduplication logic.** No custom
  `save_workouts()` or dedup logic in the strength skill. Use the gateway.
- **Bypass `ActivityRecord` / `ingest_activities()`.** Never call
  `workout_md.save_workout()` from model-driven code. The CLI path
  (`handle_workout_add`) is the exception — it is a human-operated path
  that calls `save_workout()` directly.

### 8.2 Atomic-write guarantees

All writes to `data/workouts.md` go through `atomic_io.read_modify_write`
or `read_modify_write_with_retry`:

1. **Write-to-temp + `os.replace`** — atomic on POSIX; never a torn file.
2. **Concurrent-write detection** — `_FileSnapshot` (mtime + size + inode)
   compared after the read; `ConcurrentWriteError` raised on mismatch.
3. **Retry with exponential backoff** — up to `cfg.write_retry_count`
   (default 3) times.
4. **Backup** — a `.bak` snapshot is created before overwrite
   (`backup_previous()` in `data_protection.py`).

### 8.3 Regeneration gate

`workout_md._write_workouts` is in the `allowed_regenerators` set
(`data_protection.py:132`), so the full-file rewrite path (used by the
CLI `save_workout` → `_write_workouts` → `all_workouts` round-trip) is
permitted to replace the entire file when it exceeds the 50% change
threshold. **Model-driven code does not go through this path** — it
appends via `read_modify_write_with_retry`.

### 8.4 Validation enforcement

- **Domain model validation:** `StrengthWorkout.__post_init__` rejects
  invalid data at construction (non-Exercise items, non-Set items in
  sets, empty exercise names, invalid reps/weight/RPE). The gateway's
  `_dispatch_workout` constructs the `StrengthWorkout` from the
  `ActivityRecord`; if the domain model raises `ValueError`, the
  gateway catches it and returns `IngestResult(accepted=True,
  wrote=False, error="dispatch: ...")`.
- **Gateway validation:** `_validate_record` checks that `workout_type`
  is present for `WORKOUT_ADDED` records.

---

## 9. Integration Points

### 9.1 Janus system layers

| Layer | Module | Role for strength |
|-------|--------|-------------------|
| **Model** | `src/janus/models/workout.py` | `StrengthWorkout`, `Exercise`, `Set` dataclasses + validation |
| **Persistence** | `src/janus/integrations/workout_md.py` | `load_workouts`, `save_workout`, `find_history_by_exercise`, `_workout_to_markdown_lines` |
| **Service** | `src/janus/services/workout_analytics.py` | `compute_exercise_summary`, `compute_overall_summary` |
| **CLI** | `src/janus/workout_cli.py` | `handle_workout_add`, `handle_workout_show`, `handle_workout_summary` |
| **Gateway** | `src/janus/services/activity_ingest.py` | `_dispatch_workout` — model-driven ingestion path |

### 9.2 Data file

| File | Format | Access |
|------|--------|--------|
| `data/workouts.md` | `# Fitness Workouts` header; `## Workout:` blocks with `key = value` fields; `exercises` as JSON for strength; `---` separator | Load via `load_workouts()`; append via gateway's `_dispatch_workout` |

### 9.3 Config

| Section | File | Strength-relevant keys |
|---------|------|------------------------|
| `[data_ingestion]` | `config/config.toml` (from `config.example.toml`) | `dedup_policy`, `dedup_tolerance_seconds`, `write_retry_count`, `write_retry_backoff_base` |
| `[data_ingestion.files]` | `config/config.example.toml` | `"workout_added" = "data/workouts.md"` (default, currently commented) |
| `[data_protection]` | `config/config.toml` | `regeneration_threshold`, `allowed_regenerators`, backup settings |

### 9.4 Observability

All ingestion emits structured events via `janus._log.emit` under the
`service.activity_ingest.*` namespace:

- `service.activity_ingest.record_accepted` — successful workout append
- `service.activity_ingest.record_rejected` — validation or dedup reject
- `service.activity_ingest.write_failed` — persistence failure
- `service.activity_ingest.dedup_replace` — duplicate replaced (policy=replace)

---

## 10. Limitations

1. **No cross-domain goal aggregation.** The strength skill does not
   update `data/goals.md` when a workout is added. This is tracked as
   aspirational in `docs/goal_milestone_project_task_hierarchy.md:1563`.
2. **No wearable sync.** Strava / Garmin / FIT / GPX import is a
   separate integration that must produce `ActivityRecord` values.
3. **No real-time telemetry.** The skill deals with summary workout
   records, not raw telemetry.
4. **Dedup key degenerates without dates.** A `WORKOUT_ADDED` without
   `workout_id` and without `date` / `evidence["date"]` produces the key
   `"::strength"`, which matches every undated strength workout.
5. **Multi-exercise same-day dedup.** Two strength workouts on the same
   date share the dedup key `<date>::strength`; the model should supply
   explicit `workout_id` for same-day multi-session logging.
6. **No strength-specific CLI `show` filter.** There is no
   `janus workout show --strength` filter; strength workouts appear in
   the default `show` (last N) and can be queried individually by ID or
   via `--exercise NAME`. (Planned extension: add `find_strength_workouts()`
   and a `--strength` flag.)

---

## 11. SKILL.md Section Outline

The finished `skills/autonomous-ai-agents/strength/SKILL.md` should
follow this structure (mirroring the running skill):

1. **Frontmatter** — `name`, `description`, `version`, `author`,
   `license`, `platforms`, `metadata.hermes.tags`,
   `metadata.hermes.related_skills`.
2. **When to Use** — the two ingestion paths (CLI + model-driven).
3. **Dependency: Activity Data Ingestion** — the mandatory routing rule.
4. **Purpose and Scope** — model, serialization, parsing, analytics, CLI,
   ingestion; what is and is not in scope.
5. **Data Model** — the `StrengthWorkout → Exercise → Set` hierarchy
   with dataclass definitions and validation rules.
6. **Data Ingestion Methods** — Path A (CLI) and Path B (model-driven),
   with code examples and field table.
7. **Data Normalization Rules** — timestamp/UTC, text stripping, unit
   conventions.
8. **Analysis Capabilities** — exercise summary, overall summary, CLI
   access, query functions.
9. **Strength vs. Running Fields** — field-level comparison + model
   validation table.
10. **Safety Constraints** — data/ protection rules, atomic-write
    guarantees, regeneration gate, validation enforcement.
11. **Integration Points** — Janus layers table, data file, config,
    observability, CLI integration.
12. **Dedup Key Rules** — the `compute_dedup_key` logic for
    `WORKOUT_ADDED` (strength).
13. **Limitations** — what this skill does NOT do.
14. **References** — source files, data files, tests, ADR-005, config.
15. **Verification Checklist** — import check, model construction,
    round-trip serialization, analytics correctness, CLI smoke tests,
    ingestion gateway.

---

## 12. Verification Checklist

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
