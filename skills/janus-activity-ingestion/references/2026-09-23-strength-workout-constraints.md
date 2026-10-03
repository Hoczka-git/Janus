# Activity Ingestion — Session Reference (2026-09-23)

Source: session with Hoczka — PLAN 14 Trening A Tydzień 3 (strength, 2026-09-21) ingestion.

## Object construction for strength workouts

### Enum vs string

`WorkoutType` is an `enum.StrEnum` member — pass `WorkoutType.STRENGTH`, not the literal string `"strength"`. The gateway validates the enum; a raw string may be rejected at validation time.

```python
from janus.models.workout import WorkoutType

# correct
workout_type=WorkoutType.STRENGTH

# wrong — may fail validation
workout_type="strength"
```

### Exercise / Set objects, not dicts

`evidence["exercises"]` must be a `list[Exercise]`. Each `Exercise.sets` is a `list[Set]`. Plain dicts are rejected — the gateway expects typed model objects.

```python
from janus.models.workout import Exercise, Set

exercises = [
    Exercise(
        name="Ciąć ćwiczenie",
        sets=[
            Set(reps=10, weight_kg=12.0, rpe=7.0),
            Set(reps=10, weight_kg=12.0, rpe=8.0),
            Set(reps=10, weight_kg=12.0, rpe=9.0),
        ],
        notes=None,
    ),
]
```

Constructing dicts instead of `Exercise`/`Set` instances produces a `TypeError` at ingest time:

```
TypeError: Set.__init__() got an unexpected keyword argument 'order_index'
```

### Set constructor signature

`Set` accepts only these keyword arguments: `reps`, `weight_kg`, `rpe`, `notes`. There is **no** `order_index` parameter — do not pass it.

```python
Set(reps=8, weight_kg=6.0, rpe=7.0)          # valid
Set(reps=8, weight_kg=6.0, rpe=7.0, order_index=0)  # TypeError
```

### BW (bodyweight)

Use `weight_kg=None` for bodyweight sets, not `0` or any synthetic value.

```python
Set(reps=10, weight_kg=None, rpe=7.0)   # bodyweight
```

### Per-side loads

When `Target` specifies per-side loading, keep `weight_kg` per-side and note the total in `Exercise.notes` (e.g. "16 kg w każdej ręce, łącznie 32 kg").

## CLI limitation — one exercise per call

`uv run janus workout add` accepts only **one `--exercise` per invocation**. Calling it 10 times for a 10-exercise workout creates 10 separate workouts, not one workout with 10 exercises.

For multi-exercise workouts, use `activity_ingest.py` directly: one `ActivityRecord(type=ActivityType.WORKOUT_ADDED)` with `evidence["exercises"]` populated as a list of `Exercise` objects.

## Verification after ingestion

### `find_workouts_by_date_range` may not see newly written workouts

After `ingest_activities()` returns success, `find_workouts_by_date_range(date, date)` can still return 0 workoutów for that date. This is a cache/stale-load behavior, not necessarily a write failure.

**Preferred verification path:**

1. `load_workouts()` — reads the file directly, more reliable for confirming persistence.
2. Inspect `data/workouts.md` directly if in doubt.
3. Check that the `ActivityRecord` used typed `Exercise`/`Set` objects (not dicts).

### Ingest can succeed without persisting

`ingest_activities` returning `accepted=True` / `wrote=True` does **not** guarantee the workout is visible through `find_workouts_by_date_range()`. Diagnose by checking file contents and `load_workouts()`.

### Idempotency check

Always call `compute_dedup_key(record)` before ingesting to avoid unintended duplicates:

```python
from janus.services.activity_ingest import compute_dedup_key
key = compute_dedup_key(record)
# if key exists → skip (policy=reject)
```

## Test artifacts

When prototyping, a small test workout (e.g. 2 exercises) may be created first with a different `workout_id`. If the final workout uses a different ID, both persist — the test artifact is not a duplicate of the real workout.

There is no `janus workout delete` CLI command. Removal of a test artifact requires either direct file editing (outside the data-protection boundary) or a future Janus mutation path. Decide with the user whether to keep or clean up.

## Verification checklist for this session's workout

For PLAN 14 — Trening A, Tydzień 3 (2026-09-21, strength):

1. Exactly one workout with date 2026-09-21.
2. Exactly one `ActivityRecord` with `type=ActivityType.WORKOUT_ADDED` and `workout_id="sw-20260921"`.
3. `evidence["exercises"]` is a list of exactly 10 `Exercise` objects.
4. Each `Exercise.sets` is a list with the correct number of `Set` elements (2 for ćwiczenie 1, 2 for ćwiczenie 2, 3 for ćwiczenia 3/4/5/6/7/8/9/10).
5. Each `Set` has correct `reps`, `weight_kg`, `rpe` — no `order_index` passed.
6. Ćwiczenie 8 (`Rozpiętki na maszynie butterfly`) has `notes="Trzymaj wypchniętą klatkę piersiową"`.
7. No duplicate of an existing training (check `compute_dedup_key` before ingest).
8. Prior trainings (e.g. `sw-20260918`) unchanged.

## Common errors and debugging

| Symptom | Likely cause | Fix |
|---|---|---|
| `TypeError: Set.__init__() got an unexpected keyword argument 'order_index'` | Passed `order_index` to `Set()` | Remove it; `Set` doesn't accept it |
| `compute_dedup_key` returns `"::strength"` | `evidence["date"]` or `record.date` missing for `WORKOUT_ADDED` | Populate `evidence["date"]` as ISO date string |
| `ingest` succeeds but `find_workouts_by_date_range` returns 0 | Cache/stale load, or dict-vs-object mismatch | Use `load_workouts()` + check file contents |
| `ingest` fails with `accepted=False`, `action="rejected"`, `error="duplicate"` | Dedup key already exists | Skip or use `dedup_policy="replace"` |
| `WorkoutType` validation error | Passed string `"strength"` instead of enum | Use `WorkoutType.STRENGTH` |
