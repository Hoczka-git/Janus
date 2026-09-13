# Strength Skill Specification

<!-- This file is the detailed blueprint for the strength workout domain skill.
     It is referenced by skills/autonomous-ai-agents/strength/SKILL.md and governs
     the implementation of skills/strength/. -->

**Status**: Specification
**Owner**: implementer
**Parent skill**: `skills/autonomous-ai-agents/activity-ingestion/SKILL.md` (mandatory)
**ADR reference**: `docs/decisions/005-activity-data-ingestion-layer.md` (ADR-005)
**Companion domain skill**: `skills/autonomous-ai-agents/running/SKILL.md` (shared model, persistence, analytics)

---

## Purpose and Scope

The **strength** skill provides the Janus domain slice for tracking, ingesting,
and analyzing strength-training workouts. Its scope is *domain logic only*:
the data model, serialization, analytics, and CLI handlers for strength lifts.

It owns **neither** persistence nor deduplication. All writes flow through the
shared Activity Data Ingestion gateway (see §1, §2, §7).

**This spec is implementable.** It references concrete source files, exact
function signatures, dataclass fields, and the ActivityRecord shape the model
emits. An implementer building `skills/strength/` should never need to leave
this document to know what to build or how to route data.

---

## 1. Workout → Exercise → Set Hierarchy and SKILL.md Representation

### 1.1 The three-level hierarchy

```text
StrengthWorkout  (1..*) ──has exercises──►  Exercise  (1..*) ──has sets──►  Set
```

| Level | Dataclass | Location | Cardinality |
|-------|-----------|----------|-------------|
| Workout | `StrengthWorkout(Workout)` | `src/janus/models/workout.py:95` | One per lifting session |
| Exercise | `Exercise` | `src/janus/models/workout.py:51` | Many per workout |
| Set | `Set` | `src/janus/models/workout.py:32` | Many per exercise |

### 1.2 Domain model — verbatim dataclass definitions

**Base class** (`src/janus/models/workout.py:71`):

```python
@dataclass
class Workout:
    id: str
    date: datetime
    workout_type: WorkoutType
    source: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    # __post_init__ validates: id non-empty str, date is datetime, workout_type is WorkoutType,
    # source is non-empty str or None.
```

**`WorkoutType`** (`src/janus/models/workout.py:27`):

```python
class WorkoutType(str, Enum):
    STRENGTH = "strength"
    RUNNING  = "running"
```

**`Set`** (`src/janus/models/workout.py:32`):

```python
@dataclass
class Set:
    reps: int = 0                    # int, >= 0
    weight_kg: float | None = None   # None = bodyweight, 0.0 = zero added weight, else >= 0
    rpe: float | None = None         # float in [1, 10] or None
```

**`Exercise`** (`src/janus/models/workout.py:51`):

```python
@dataclass
class Exercise:
    name: str                        # non-empty str
    sets: list[Set] = field(default_factory=list)
    notes: str | None = None         # non-empty str or None
```

**`StrengthWorkout`** (`src/janus/models/workout.py:95`):

```python
@dataclass
class StrengthWorkout(Workout):
    workout_type: WorkoutType = field(default=WorkoutType.STRENGTH)
    exercises: list[Exercise] = field(default_factory=list)
    notes: str | None = None
```

### 1.3 Field validation rules (enforced in `__post_init__`)

| Field | Type | Constraint |
|-------|------|-----------|
| `Workout.id` | `str` | Non-empty |
| `Workout.date` | `datetime` | Must be a `datetime` |
| `Workout.workout_type` | `WorkoutType` | Must be `WorkoutType.STRENGTH` |
| `Workout.source` | `str \| None` | Non-empty if present |
| `Set.reps` | `int` | `>= 0` |
| `Set.weight_kg` | `float \| None` | `>= 0` or `None` (bodyweight) |
| `Set.rpe` | `float \| None` | `1–10` or `None` |
| `Exercise.name` | `str` | Non-empty |
| `Exercise.sets` | `list[Set]` | List of `Set` instances |
| `Exercise.notes` | `str \| None` | Non-empty if present |
| `StrengthWorkout.exercises` | `list[Exercise]` | List of `Exercise` instances |
| `StrengthWorkout.notes` | `str \| None` | Non-empty if present |

### 1.4 How SKILL.md documents the hierarchy

The `skills/autonomous-ai-agents/strength/SKILL.md` follows the standard
skill template (see §6 Conventions). Within it, the hierarchy is documented
in the **Data Model** section (`## Data Model — Workout → Exercise → Set Hierarchy`)
using:

- **Tree diagram** (ASCII) showing the class inheritance and containment.
- **Verbatim dataclass definitions** in code blocks.
- A **field/constraint table** (the `__post_init__` rules above).
- The **on-disk markdown representation** showing `exercises = [...]` as a
  JSON-encoded array (see §1.5).

### 1.5 On-disk representation in SKILL.md

The SKILL.md documents how `StrengthWorkout` is serialized to the shared
`data/workouts.md` file via `_workout_to_markdown_lines()`
(`src/janus/integrations/workout_md.py:101`). Each workout is a
`## Workout:` block:

```text
## Workout:
id = w-1a2b3c4d
date = 2026-09-12T14:30:00+00:00
workout_type = strength
source = chat
notes = Back day — felt strong
exercises = [{"name": "Pull-ups", "sets": [{"reps": 8, "weight_kg": null, "rpe": null}, {"reps": 6, "weight_kg": 12.5, "rpe": 8.0}], "notes": null}, {"name": "Barbell Row", "sets": [{"reps": 5, "weight_kg": 60.0, "rpe": 8.5}], "notes": null}]

---
```

Key serialization facts (documented in SKILL.md):

- `exercises` is a **JSON-encoded array** on a single line, produced by
  `json.dumps()` (via `workout_to_dict()` at `workout.py:149`).
- Each exercise: `{name: str, sets: [{reps: int, weight_kg: float|null, rpe: float|null}], notes: str|null}`.
- `weight_kg: null` indicates bodyweight.
- The block ends with `---` on its own line.
- Parsing round-trips via `_finalize_workout()` (`workout_md.py:128`) which
  JSON-decodes the `exercises` line back into `Exercise`/`Set` instances.

---

## 2. Model Registration Without Direct data/ Editing

### 2.1 Two ingestion paths — both converge on the Activity Ingestion gateway

There are two ways a strength workout enters the system. Both ultimately
persist to `data/workouts.md` through `ingest_activities()`, but they
differ in *who* drives the flow:

| Path | Driven by | Persists via | Permitted to call `save_workout()` directly? |
|------|-----------|--------------|------------------------------------------|
| **Path A** | Human (CLI) | `handle_workout_add()` → `save_workout()` → `protected_write()` → `atomic_write()` | **Yes** — human-operated exception |
| **Path B** | Model (Hermes) | `ActivityRecord` → `ingest_activities()` → `_dispatch_workout()` → `read_modify_write_with_retry()` → `atomic_write()` | **No** — must use the gateway |

### 2.2 Path A — Human CLI (direct persistence)

**Command syntax** (documented in SKILL.md as the reference example):

```sh
janus workout add --type strength \
    --exercise "Back Squat" --sets "5x80kg@8,5x80kg@8.5,5x80kg@8" \
    --date 2026-09-12 --source manual --notes "Heavy day"
```

**Implementation flow** — `handle_workout_add()` in
`src/janus/workout_cli.py:113`:

1. Parse args manually (no argparse — matches `workout_cli.py` convention).
2. Parse `--sets` string via `_parse_sets()`:
   - Format: `<reps>x<weight>kg@<rpe>`, `<reps>x<weight>kg`, `<reps>x` (bodyweight).
   - Comma-separated list → `list[Set]`.
3. Generate ID via `_generate_id(WorkoutType.STRENGTH)`
   (`workout_cli.py:25`):
   - Prefix `sw`, scans existing workouts via `load_workouts()`,
     finds max numeric suffix `sw-NNN`, increments.
   - Format: `sw-001`, `sw-002`, etc.
4. Construct `StrengthWorkout` dataclass (validated by `__post_init__`).
5. Call `save_workout(workout)` (`workout_md.py:68`):
   - `load_workouts()` → append new → `_write_workouts()` →
     `protected_write()` → `atomic_write()`.
6. Print confirmation: `Added workout: sw-005`.

### 2.3 Path B — Model-driven ingestion (the governed path)

When Hermes captures a strength workout from chat, a wearable sync, or a
completed Kanban task, the model **MUST** emit an `ActivityRecord` and pass it
to `ingest_activities()`. It never touches `data/` directly.

**Concrete model output** (verbatim from the existing strength SKILL.md, §Path B):

```python
import sys
from datetime import datetime, timezone
sys.path.insert(0, "src")

from janus.services.activity_ingest import (
    ActivityRecord,
    ActivityType,
    ingest_activities,
)

now = datetime(2026, 9, 12, 14, 30, tzinfo=timezone.utc)

records = [
    ActivityRecord(
        type=ActivityType.WORKOUT_ADDED,
        source="chat",
        timestamp=now,
        workout_type="strength",
        date="2026-09-12",
        evidence={
            "notes": "Back day — felt strong",
            "date": "2026-09-12",          # critical for dedup key fallback
            "exercises": [
                {
                    "name": "Pull-ups",
                    "sets": [
                        {"reps": 8, "weight_kg": None, "rpe": None},
                        {"reps": 6, "weight_kg": 12.5, "rpe": 8.0},
                    ],
                    "notes": None,
                },
                {
                    "name": "Barbell Row",
                    "sets": [
                        {"reps": 5, "weight_kg": 60.0, "rpe": 8.5},
                    ],
                    "notes": None,
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

### 2.4 What the model emits — the ActivityRecord field table for strength

| Concept | ActivityRecord field | Path | Notes |
|---------|---------------------|------|-------|
| Workout type | `workout_type="strength"` | top-level | Must be the string `"strength"` — gateway calls `WorkoutType(record.workout_type)` (`activity_ingest.py:887`). |
| Source label | `source` | top-level | e.g. `"chat"`, `"hermes_kanban"`, `"manual"`, `"strava"`. |
| Timestamp | `timestamp` | top-level | `datetime`, naive → UTC. Used as `date`/`created_at`/`updated_at` in the workout. |
| Exercises | `evidence["exercises"]` | evidence dict | **Required.** List of dicts: `{name: str, sets: [{reps, weight_kg, rpe}], notes: str\|null}`. |
| Set reps | `evidence["exercises"][i]["sets"][j]["reps"]` | nested | Integer `>= 0`. |
| Set weight | `evidence["exercises"][i]["sets"][j]["weight_kg"]` | nested | Float `>= 0`, or `None` for bodyweight. |
| Set RPE | `evidence["exercises"][i]["sets"][j]["rpe"]` | nested | Float `1–10`, or `None`. |
| Workout notes | `evidence["notes"]` | evidence dict | Workout-level free text. Optional. |
| Workout date | `evidence["date"]` or `date` | top-level / evidence | **Critical for dedup** — ISO date string `YYYY-MM-DD`. |
| Workout ID | `workout_id` | top-level | If absent, gateway generates `w-<8-hex>` via `_gen_uuid("w")` (`activity_ingest.py:186`). Model should provide explicit IDs for same-day multi-session logging. |

### 2.5 Gateway dispatch — `_dispatch_workout()` (activity_ingest.py:938)

The model never calls persistence directly. The gateway's
`_dispatch_workout()` handles strength records as follows:

```python
def _dispatch_workout(
    record: ActivityRecord,
    file_path: Path,
    retry_count: int,
    backoff: float,
) -> str:
    """Route a WORKOUT_ADDED record through the atomic write gateway."""
    from janus.models.workout import Workout, WorkoutType, StrengthWorkout, RunningWorkout
    from janus.integrations.workout_md import _workout_to_markdown_lines, _HEADER

    workout_type = WorkoutType(record.workout_type)
    now = record.timestamp
    if workout_type == WorkoutType.RUNNING:
        workout = RunningWorkout(...)    # running path — NOT this skill's concern
    else:
        workout = StrengthWorkout(
            id=record.workout_id or _gen_uuid("w"),
            date=now,
            workout_type=WorkoutType.STRENGTH,
            source=record.source,
            created_at=now,
            updated_at=now,
            exercises=record.evidence.get("exercises", [])
                if isinstance(record.evidence.get("exercises"), list) else [],
            notes=record.evidence.get("notes")
                if isinstance(record.evidence.get("notes"), str) else None,
        )

    # Serialize and append atomically
    lines = _workout_to_markdown_lines(workout)
    new_line = "\n".join(lines) + "\n\n"

    def _append_workout(current: str) -> str:
        if not current.strip():
            return _HEADER + new_line
        if not current.endswith("\n"):
            current += "\n"
        return current + new_line

    read_modify_write_with_retry(
        file_path, _append_workout,
        max_retries=retry_count, backoff_base=backoff,
    )
    return "appended"
```

### 2.6 The prohibition — what the model NEVER touches

The strength skill's SKILL.md MUST state these prohibitions explicitly
(copying the convention from the existing strength SKILL.md §Safety Constraints):

1. **Direct `data/` writes** — The skill MUST NOT call `Path.write_text()`,
   `open(..., "w")`, or any I/O targeting `data/workouts.md` from model-driven
   code. All persistence flows through the Activity Ingestion gateway
   (`ActivityRecord` → `ingest_activities()` → `read_modify_write_with_retry`
   → `atomic_write`).

2. **Generate or rewrite `data/workouts.md`** — The model emits structured
   `ActivityRecord` values; the gateway owns serialization via the existing
   `_workout_to_markdown_lines()`. The model never hand-writes `## Workout:`
   blocks.

3. **Own persistence or deduplication logic** — No custom `save_workouts()`
   or dedup logic in the strength skill. Use the gateway's
   `_dispatch_workout()` / `read_modify_write_with_retry()`.

4. **Bypass `ActivityRecord` / `ingest_activities()`** — Never call
   `workout_md.save_workout()` from model-driven code. The CLI path
   (`handle_workout_add`) is the **only** exception — it is a human-operated
   path that calls `save_workout()` directly.

These prohibitions are enforced structurally: `data/` path construction is
centralized in `activity_ingest.py` (`PROJECT_ROOT / "data"` at line 49);
all other modules receive paths via parameters. A CI grep gate
(`docs/examples/contract_phase1.yaml`) rejects any new `data/` file write
outside `atomic_io.py` or the integration modules' `read_modify_write` usage.

---

## 3. Workout Analysis

### 3.1 Analysis reads from data/ — it does NOT write back

Analysis is a **read-only** surface. It loads workouts from `data/workouts.md`
via `load_workouts()` (`workout_md.py:40`) — which the model invokes through
the Janus service/gateway — and computes summaries. Analysis functions are
**pure**: they take `list[Workout]` as input and return a dataclass. They
never write to `data/`.

The data flow for analysis:

```text
Analysis request
  → load_workouts()        [reads data/workouts.md]
  → compute_*_summary()     [pure function, no side effects]
  → result dataclass        [surfaced to caller / CLI / model]
```

### 3.2 The analysis interface — functions and signatures

| Function | Module | Line | Signature | Returns |
|----------|--------|------|-----------|---------|
| `compute_overall_summary` | `src/janus/services/workout_analytics.py:78` | | `compute_overall_summary(workouts: List[Workout]) -> OverallSummary` | `OverallSummary` |
| `compute_running_summary` | `src/janus/services/workout_analytics.py:105` | | `compute_running_summary(workouts: List[Workout]) -> RunningSummary` | `RunningSummary` |
| `compute_exercise_summary` | `src/janus/services/workout_analytics.py:161` | | `compute_exercise_summary(workouts: List[Workout], exercise_name: str) -> ExerciseSummary` | `ExerciseSummary` |

### 3.3 Query functions — reading workouts from data/

Analysis reads workouts through query functions in `src/janus/integrations/workout_md.py`:

| Function | Line | Signature | Returns |
|----------|------|-----------|---------|
| `load_workouts()` | `workout_md.py:40` | `() -> list[Workout]` | All workouts (strength + running) |
| `find_history_by_exercise(name)` | `workout_md.py:160` | `(name: str) -> list[StrengthWorkout]` | Strength workouts containing the named exercise (case-insensitive) |
| `find_workout_by_id(workout_id)` | `workout_md.py:189` | `(workout_id: str) -> Optional[Workout]` | Single workout by ID or `None` |
| `find_last_n(n)` | `workout_md.py:180` | `(n: int) -> list[Workout]` | Most recent `n` (most-recent first) |
| `find_workouts_by_date_range(start, end)` | `workout_md.py:142` | `(start: datetime \| None, end: datetime \| None) -> list[Workout]` | Workouts in `[start, end]` inclusive |
| `find_running_workouts()` | `workout_md.py:174` | `() -> list[RunningWorkout]` | All running workouts (sibling-skill support) |

**Analysis reads from `data/` via the Janus service/gateway (`load_workouts()`).**
The model invokes these through the Janus service layer, not by opening
`data/workouts.md` directly.

### 3.4 Supported analyses

#### 3.4.1 Exercise summary — `compute_exercise_summary(workouts, exercise_name)`

**Input**: `list[Workout]` (loaded via `load_workouts()`), an exercise name
string.

**Matching**: Case-insensitive on `Exercise.name`. Only `StrengthWorkout`
instances are scanned; running workouts are skipped.

**Output** — `ExerciseSummary` dataclass (`workout_analytics.py:60`):

| Field | Type | Computation |
|-------|------|-------------|
| `workout_count` | `int` | Count of strength workouts containing the named exercise |
| `latest_sets_description` | `str \| None` | From the most recent matching workout. Format: `<reps>x<weight>kg@<rpe>` joined by `, `. Bodyweight sets (`weight_kg=None`) omit the weight: `<reps>x@<rpe>` or `<reps>x`. |
| `highest_weight_kg` | `float \| None` | Max `weight_kg` across all sets of the exercise. Bodyweight sets (`None`) **excluded**. |
| `highest_workout_volume_kg` | `float` | Max `(sum of weight_kg × reps)` per workout containing the exercise. All-bodyweight workouts → `0.0`. |
| `chronological_progression` | `list[ExerciseProgressionPoint]` | One point per matching workout, ascending by date. |

`ExerciseProgressionPoint` (`workout_analytics.py:53`):

| Field | Type | Computation |
|-------|------|-------------|
| `date` | `datetime` | Workout date |
| `max_weight_kg` | `float \| None` | Heaviest loaded set in that workout (`None` if all bodyweight) |
| `total_volume_kg` | `float` | `sum(weight_kg × reps)` across all sets (`0.0` if all bodyweight) |

**Key behaviors** (documented in SKILL.md):
- Bodyweight sets (`weight_kg is None`) contribute to set count and
  `latest_sets_description` but add `0.0` to volume and are excluded from
  `highest_weight_kg`.
- Volume is per-workout (sets summed), then the max across workouts is taken.

#### 3.4.2 Running summary — `compute_running_summary(workouts)`

Relevant here because `OverallSummary` counts strength vs. running. Located at
`workout_analytics.py:105`. Returns `RunningSummary` (`workout_analytics.py:40`):

| Field | Type | Computation |
|-------|------|-------------|
| `run_count` | `int` | Count of `RunningWorkout` |
| `total_distance_km` | `float` | `sum(w.distance_km)` |
| `total_duration_min` | `float` | `sum(w.duration_minutes)` |
| `avg_pace_min_per_km` | `float \| None` | `total_duration_min / total_distance_km` — **distance-weighted**, not arithmetic mean |
| `best_pace_min_per_km` | `float \| None` | `min(individual_pace)` across runs with `distance_km > 0` |
| `avg_hr_bpm_when_available` | `float \| None` | Mean of `avg_hr_bpm` from runs that have HR data |
| `highest_run_km` | `float` | `max(w.distance_km)` |
| `total_elevation_m` | `float` | `sum(w.elevation_m)` across runs with elevation data |
| `runs_with_elevation` | `int` | Count of runs with `elevation_m is not None` |
| `runs_with_hr` | `int` | Count of runs with `avg_hr_bpm is not None` |

#### 3.4.3 Overall summary — `compute_overall_summary(workouts)`

Located at `workout_analytics.py:78`. Returns `OverallSummary`
(`workout_analytics.py:31`):

| Field | Type | Computation |
|-------|------|-------------|
| `total_workouts` | `int` | All loaded workouts |
| `strength_count` | `int` | Count of `StrengthWorkout` |
| `running_count` | `int` | Count of `RunningWorkout` |
| `most_recent_workout_id` | `str \| None` | Sort by date desc; take first |
| `most_recent_date` | `datetime \| None` | Most recent workout date |

### 3.5 How analysis results are surfaced

Analysis results are surfaced through the CLI handlers (human-facing) and are
available to the model via direct function calls within the Janus process:

**CLI access** (`src/janus/workout_cli.py:113`):

```sh
janus workout summary --exercise "Back Squat"   # → compute_exercise_summary()
janus workout show --exercise "Back Squat"      # → find_history_by_exercise()
janus workout show sw-001                       # → find_workout_by_id()
janus workout show                              # → find_last_n(5)
janus workout summary                           # → compute_overall_summary()
```

The `handle_workout_summary()` handler (`workout_cli.py:512`) dispatches:
- `--exercise NAME` → `compute_exercise_summary(workouts, NAME)`
- `--running` → `compute_running_summary(workouts)`
- default → `compute_overall_summary(workouts)`

**Model access:** The model calls the same analysis functions directly:
`load_workouts()` → `compute_exercise_summary(...)` / `compute_overall_summary(...)`.
Analysis is read-only; the model uses results to inform decisions (e.g.
progress tracking, set/rep progression) but does **not** write back through
analysis. Writes always go through §2 (Activity Ingestion gateway).

---

## 4. Exact File Locations

### 4.1 The strength skill directory

```text
skills/autonomous-ai-agents/strength/
└── SKILL.md
```

**Primary spec artifact**: `skills/autonomous-ai-agents/strength/SKILL.md`

The strength skill, when implemented, lives at:
`/home/dan11hermes/workspaces/janus/skills/autonomous-ai-agents/strength/SKILL.md`

This is the **skill declaration** — a single SKILL.md file following the
standard template (see §6 Conventions). It must reference this document
(`docs/strength-skill-spec.md`) in its References section, as the existing
strength SKILL.md already does at `skills/autonomous-ai-agents/strength/SKILL.md:662`.

### 4.2 The specification document

**Spec document**: `docs/strength-skill-spec.md`
Absolute path: `/home/dan11hermes/workspaces/janus/docs/strength-skill-spec.md`
(This file.)

### 4.3 Supporting files the skill would own or reference

The strength domain logic currently lives in **shared** modules (not in the
skill directory itself). The skill's SKILL.md documents these as the
implementation surface:

| File | Role for strength |
|------|-------------------|
| `src/janus/models/workout.py` | `StrengthWorkout`, `Exercise`, `Set`, `workout_to_dict`, `dict_to_workout` — domain model + validation. |
| `src/janus/integrations/workout_md.py` | `load_workouts`, `save_workout`, `find_history_by_exercise`, `_workout_to_markdown_lines`, `_finalize_workout`, `find_last_n`, `find_workout_by_id`, `find_workouts_by_date_range`, `find_running_workouts` — persistence + query. |
| `src/janus/services/workout_analytics.py` | `compute_exercise_summary`, `compute_running_summary`, `compute_overall_summary`, plus `ExerciseSummary`, `RunningSummary`, `OverallSummary`, `ExerciseProgressionPoint` dataclasses. |
| `src/janus/workout_cli.py` | `handle_workout_add`, `handle_workout_show`, `handle_workout_summary`, `_parse_sets`, `_generate_id`. |
| `src/janus/services/activity_ingest.py` | `_dispatch_workout`, `compute_dedup_key`, `_validate_record`, `ActivityRecord`, `ActivityType`, `ingest_activities`, `IngestResult`, `IngestDryRun`, `IngestConfig`, `_gen_uuid`. |
| `src/janus/integrations/atomic_io.py` | `atomic_write`, `atomic_read`, `read_modify_write`, `read_modify_write_with_retry`, `ConcurrentWriteError`, `AtomicWriteError`. |
| `src/janus/integrations/data_protection.py` | `protected_write`, `compute_content_hash`, `backup_previous`, regeneration gate, `allowed_regenerators` set. |
| `config/config.example.toml` | `[data_ingestion]`, `[data_ingestion.files]`, `[data_ingestion.normalization]` sections. |
| `data/workouts.md` | Canonical fitness data file (gitignored — `data/*` in `.gitignore`). Shared by running + strength. |
| `tests/test_fitness.py` | Model validation + persistence round-trip tests. |
| `tests/test_workout_cli.py` | CLI handler tests. |
| `tests/test_workout_analytics.py` | Analytics correctness tests. |
| `docs/decisions/005-activity-data-ingestion-layer.md` | ADR-005 design doc. |
| `docs/activity_data_guide.md` | Operational guide for the ingestion layer. |
| `docs/goal_milestone_project_task_hierarchy.md` | Aspirational cross-domain workout→goal aggregation (line 1563). |
| `scripts/repair_workouts.py` | Data repair utility (context for why atomic writes matter). |

### 4.4 File the skill references as its mandatory dependency

**Parent skill (mandatory dependency)**:
`/home/dan11hermes/workspaces/janus/skills/autonomous-ai-agents/activity-ingestion/SKILL.md`

This is the shared Activity Data Ingestion skill. The strength skill MUST
declare this as a dependency (via `metadata.hermes.related_skills` in
frontmatter and a `## Dependency: Activity Data Ingestion` section in the
body) and MUST route all persistence through its interface.

**Sibling skill** (shared model, not a dependency):
`/home/dan11hermes/workspaces/janus/skills/autonomous-ai-agents/running/SKILL.md`

---

## 5. Activity Ingestion Dependency Contract

The strength skill depends on the shared Activity Data Ingestion skill. This
section is the contract an implementer must satisfy.

### 5.1 Dependency location and declaration

**Shared skill path**:
`/home/dan11hermes/workspaces/janus/skills/autonomous-ai-agents/activity-ingestion/SKILL.md`

The strength skill declares this dependency via:
- `metadata.hermes.related_skills: [activity-ingestion, running]` in the
  SKILL.md YAML frontmatter.
- A `## Dependency: Activity Data Ingestion` section in the body, with the
  explicit file path above and the routing diagram (§7).

### 5.2 Required data flow

```text
Domain Skill (strength)
  → ActivityRecord(WORKOUT_ADDED, workout_type="strength", ...)
  → Activity Ingestion: ingest_activities()
  → Janus service / gateway (_dispatch_workout)
  → data/
```

The model NEVER:
```text
Model → Generic file edit → data/
```

### 5.3 What Activity Ingestion provides

The Activity Ingestion gateway provides these guarantees to the strength
skill, so the strength skill does not reimplement them:

| Guarantee | Where implemented |
|-----------|-------------------|
| **Validation** — `_validate_record()` checks `type`, `workout_type` presence, etc. (`activity_ingest.py`) |
| **Normalization** — `_normalize_record()`: timestamps → UTC, free-text stripping, unit conversion (lb→kg, mi→km) for `MEASUREMENT`/`GOAL_UPDATED` (`activity_ingest.py`) |
| **Deduplication** — `compute_dedup_key()` + configurable policy (`reject`/`merge`/`replace`) + tolerance window (`activity_ingest.py:169`) |
| **Idempotency** — same dedup key = single persisted record under `reject` policy |
| **Controlled persistence** — `_dispatch_workout()` → `_workout_to_markdown_lines()` → `read_modify_write_with_retry()` → `atomic_write()` (`activity_ingest.py:938`) |
| **Protection of existing data** — `atomic_io` (write-to-temp + `os.replace`), `data_protection` (`.bak` backups, regeneration gate, conflict detection) |

### 5.4 Prohibition — restated as a hard contract

The strength skill's SKILL.md MUST state, verbatim in spirit:

> The skill MUST NOT:
> - directly modify files under `data/`,
> - generate or rewrite `data/workouts.md`,
> - implement its own persistence or deduplication logic,
> - bypass `ActivityRecord` / `ingest_activities()`.

The CLI path (`handle_workout_add`) is the **explicit exception**: it is a
human-operated path that may call `save_workout()` directly. Model-driven
code must never do so.

### 5.5 Dedup key rules for strength WORKOUT_ADDED records

From `compute_dedup_key()` (`activity_ingest.py:169`); the WORKOUT_ADDED
rule:

| Condition | Dedup key |
|-----------|-----------|
| `record.workout_id` is set | `record.workout_id` |
| `evidence["date"]` is set | `<evidence["date"]>::strength` |
| `record.date` is set | `<record.date>::strength` |
| Neither date nor workout_id | `"::strength"` — **degenerate, causes spurious duplicates** |

**Action for the model**: Always populate `evidence["date"]` (ISO date string
`YYYY-MM-DD`) or `record.date`, and always set `workout_id` when the workout
has a known ID. ID generation:
- CLI: `_generate_id(WorkoutType.STRENGTH)` → `sw-NNN` (scans existing,
  increments max).
- Model-driven: if `record.workout_id` absent, `_gen_uuid("w")` →
  `w-<8-hex>`.

**Caveat — multi-exercise same-day dedup**: Two strength workouts on the
same date share the key `<date>::strength`. The model MUST supply an explicit
`workout_id` when logging multiple strength sessions on the same day, or
accept that only the first will be persisted under the default `reject`
policy.

### 5.6 IngestResult — interpreting gateway output

The model calls `ingest_activities(records)` and receives `list[IngestResult]`:

| Field | Meaning |
|-------|---------|
| `record_id` | The dedup key that was used |
| `accepted` | `False` if rejected by validation or dedup policy |
| `wrote` | `False` if no file write occurred (rejected, or write failed) |
| `file_path` | The `data/` file written (or `None`) — for strength: `data/workouts.md` |
| `action` | `"created"` / `"updated"` / `"appended"` / `"rejected"` |
| `error` | Human-readable error string |

**Best-effort invariant**: `ingest_activities` never raises on an individual
record failure. A malformed record produces `accepted=False` and the batch
continues.

### 5.7 Config — `[data_ingestion]` table

From `config/config.example.toml` (defaults applied when absent):

```toml
[data_ingestion]
dedup_policy = "reject"         # reject | merge | replace
dedup_tolerance_seconds = 0     # 0 = exact match
write_retry_count = 3
write_retry_backoff_base = 0.1
```

These apply to all `ingest_activities()` calls, including `WORKOUT_ADDED`.

---

## 6. Conventions (Observed During Inspection)

### 6.1 SKILL.md structure

Every domain skill (activity-ingestion, running, strength) follows the same
template. The strength skill's SKILL.md MUST follow this structure:

1. **Frontmatter** — `name`, `description`, `version`, `author`, `license`,
   `platforms`, `metadata.hermes.tags`, `metadata.hermes.related_skills`.
2. **When to Use** — trigger scenarios (chat capture, wearable sync,
   completed Kanban task, CLI).
3. **Dependency: Activity Data Ingestion** — mandatory routing rule
   (ActivityRecord → Activity Ingestion → Janus service → data/), explicit
   file path, and the prohibition list.
4. **Purpose and Scope** — model, serialization, parsing, analytics, CLI,
   ingestion; what is and is not in scope.
5. **Data Model** — dataclass definitions (§1 of this spec), validation rules.
6. **Ingestion Methods** — Path A (CLI) and Path B (model-driven), with
   code examples and the field table (§2 of this spec).
7. **Data Normalization Rules** — timestamp/UTC, text stripping, unit
   conventions. Strength metrics (weight_kg, RPE) are NOT subject to unit
   normalization — they are domain-specific scalars in native units.
8. **Analysis Capabilities** — exercise summary, overall summary, running
   summary, CLI access, query functions (§3 of this spec).
9. **Safety Constraints** — data/ protection rules, atomic-write guarantees,
   regeneration gate, validation enforcement (§2.6 of this spec).
10. **Integration Points** — Janus layers table (§4.3), data file, config,
    observability, CLI integration.
11. **Dedup Key Rules** — the `compute_dedup_key` logic for `WORKOUT_ADDED`
    and the imperative to always populate dates/IDs (§5.5 of this spec).
12. **Limitations** — what this skill does NOT do (cross-domain goal
    aggregation, wearable sync, real-time telemetry).
13. **References** — source files, data files, tests, ADR-005, config,
    parent skill, sibling skill.
14. **Verification Checklist** — concrete implementation checks.

### 6.2 Dependency declaration pattern

Domain skills declare dependencies via:
- `metadata.hermes.related_skills` in frontmatter (e.g.,
  `[activity-ingestion, running]`).
- A dedicated `## Dependency: Activity Data Ingestion` section with the
  explicit file path:
  `/home/dan11hermes/workspaces/janus/skills/autonomous-ai-agents/activity-ingestion/SKILL.md`
- The routing diagram:
  ```text
  Domain Skill → ActivityRecord → ingest_activities() → Janus service → data/
  ```

### 6.3 File layout

```text
skills/
└── autonomous-ai-agents/
    ├── activity-ingestion/   ← parent (mandatory dependency)
    │   └── SKILL.md
    ├── running/              ← sibling (shared model)
    │   └── SKILL.md
    └── strength/             ← this skill
        └── SKILL.md
```

Each skill = one directory with a single `SKILL.md`. No supplementary
files (`references/`, `scripts/`, `templates/` subdirectories) exist in the
current convention.

### 6.4 Data directory

`data/` is gitignored (`.gitignore` line 33: `data/*`). It is runtime state
created lazily. `data/workouts.md` is the shared fitness file. The strength
skill reads it via `load_workouts()` and appends to it only through the
Activity Ingestion gateway.

---

## 7. Required Data Flow Summary

This is the single invariant the strength skill must enforce:

```text
┌─────────────────┐      ┌──────────────────────┐      ┌─────────────────────┐      ┌────────┐
│  Model (Hermes) │      │ Strength Skill       │      │ Activity Ingestion  │      │  data/ │
│                 │      │ (domain logic only)  │      │  (gateway)          │      │        │
│  emits          │      │  builds ActivityRecord│      │  ingest_activities()│      │        │
│  ActivityRecord │ ───► │  → ActivityRecord    │ ───► │  → validate         │ ───► │workouts│
│  (WORKOUT_ADDED)│      │                       │      │  → normalize         │      │ .md    │
│  with           │      │  (NO direct data/    │      │  → dedup             │      │        │
│  evidence:      │      │   writes)            │      │  → _dispatch_workout │      │        │
│  {exercises,    │      │                       │      │  → atomic_write      │      │        │
│   date, notes}  │      │                       │      │                       │      │        │
└─────────────────┘      └──────────────────────┘      └─────────────────────┘      └────────┘
```

The reverse direction (reads):

```text
Analysis / model query
  → load_workouts()                    [reads data/workouts.md]
  → find_history_by_exercise()        [read-only query]
  → compute_exercise_summary()        [pure function]
  → result dataclass                  [no writes to data/]
```

**Analysis reads from `data/` (via the Janus service/gateway) but does NOT
write back through the skill.** The write path is unidirectional through
§7's top diagram. Analysis functions are pure and side-effect-free.

---

## 8. Acceptance Criteria — For the Spec

- [x] File `docs/strength-skill-spec.md` exists.
- [x] Area 1 (Workout → Exercise → Set hierarchy) addressed with verbatim
  dataclass definitions, field validation table, and on-disk representation.
- [x] Area 2 (registration without direct `data/` editing) addressed with
  the two-path model, the concrete `ActivityRecord` emission, and the
  `_dispatch_workout()` flow.
- [x] Area 3 (analysis) addressed with the read interface, function
  signatures, supported analyses, and the explicit read-only boundary.
- [x] Area 4 (exact file locations) addressed with precise paths for the
  skill SKILL.md, this spec, and all supporting implementation files.
- [x] The Activity Ingestion dependency is declared with its exact path:
  `/home/dan11hermes/workspaces/janus/skills/autonomous-ai-agents/activity-ingestion/SKILL.md`.
- [x] The prohibition on direct `data/` writes is stated as a hard contract.
- [x] The required data flow (Domain Skill → Activity Ingestion → Janus
  service/gateway → data/) is documented.
- [x] What Activity Ingestion provides (validation, normalization,
  deduplication, idempotency, controlled persistence, protection of
  existing data) is listed.
- [x] The spec is concrete and implementable: includes dataclass fields,
  function signatures, line-number references, and code examples.

---

## 9. References

- `docs/strength-skill-spec.md` — this specification (the detailed blueprint).
- `skills/autonomous-ai-agents/strength/SKILL.md` — the skill declaration
  that will reference this spec.
- `skills/autonomous-ai-agents/activity-ingestion/SKILL.md` — **mandatory
  parent dependency**.
- `skills/autonomous-ai-agents/running/SKILL.md` — sibling skill (shared
  model, persistence, analytics).
- `docs/decisions/005-activity-data-ingestion-layer.md` — ADR-005 (design
  decisions, controlled-write gateway, alternatives considered).
- `docs/activity_data_guide.md` — operational guide for the ingestion layer.
- `src/janus/models/workout.py` — `StrengthWorkout`, `Exercise`, `Set`,
  `workout_to_dict`, `dict_to_workout` + validation.
- `src/janus/integrations/workout_md.py` — persistence + query functions.
- `src/janus/services/workout_analytics.py` — analytics functions + output
  dataclasses.
- `src/janus/workout_cli.py` — CLI handlers.
- `src/janus/services/activity_ingest.py` — the ingestion gateway
  (`_dispatch_workout`, `compute_dedup_key`, `_validate_record`,
  `ActivityRecord`, `ActivityType`, `ingest_activities`, `IngestResult`,
  `IngestDryRun`, `IngestConfig`).
- `src/janus/integrations/atomic_io.py` — atomic write primitives.
- `src/janus/integrations/data_protection.py` — regeneration gate, backups.
- `config/config.example.toml` — `[data_ingestion]` configuration.
- `data/workouts.md` — persisted fitness data (gitignored runtime file).
- `tests/test_fitness.py` — model validation + persistence round-trip.
- `tests/test_workout_cli.py` — CLI handler tests.
- `tests/test_workout_analytics.py` — analytics correctness tests.
- `scripts/repair_workouts.py` — data repair context.
- `docs/goal_milestone_project_task_hierarchy.md:1563` — aspirational
  cross-domain workout→goal aggregation.
