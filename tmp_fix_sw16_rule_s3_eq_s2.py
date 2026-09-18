#!/usr/bin/env python3
"""Fix sw-20260916: apply "seria 3 = seria 2" rule to exercises 5 and 6."""

import json, sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))
os.environ["PYTHONPATH"] = "src"

from janus.models.workout import StrengthWorkout
from janus.integrations.workout_md import load_workouts, find_workout_by_id, save_workout
from janus.services.activity_ingest import ingest_activities, ActivityRecord, ActivityType
from datetime import datetime, timezone

WORKOUT_ID = "sw-20260916"

# Load current state
workouts = [w for w in load_workouts() if w.workout_type.name == "strength"]
target = find_workout_by_id(WORKOUT_ID)
assert target is not None, f"{WORKOUT_ID} not found"
assert "STRENGTH" in str(target.workout_type), f"Not a strength workout: {target.workout_type}"

print(f"Before: {WORKOUT_ID}")
for ex_idx, ex in enumerate(target.exercises, 1):
    print(f"  [{ex_idx}] {ex.name}")
    for s_idx, s in enumerate(ex.sets, 1):
        print(f"    set{s_idx}: reps={s.reps}, weight={s.weight_kg}, rpe={s.rpe}")

# Exercises are 0-indexed in the list
ex5_idx = 4   # Wiosłowanie hantlą (5th exercise)
ex6_idx = 5   # Wznosy hantli bokiem (6th exercise)

# Rule: série 3 = série 2
# Ex 5: set 2 = (reps=10, weight=24.0, rpe=8.0) so set 3 becomes (10, 24.0, 9.0)
set2_ex5 = target.exercises[ex5_idx].sets[1]
target.exercises[ex5_idx].sets[2].reps = set2_ex5.reps
target.exercises[ex5_idx].sets[2].weight_kg = 24.0   # from plan data
target.exercises[ex5_idx].sets[2].rpe = 9.0

# Ex 6: set 2 = (reps=10, weight=4.0, rpe=9.0) so set 3 becomes (10, 4.0, 9.0)
set2_ex6 = target.exercises[ex6_idx].sets[1]
target.exercises[ex6_idx].sets[2].reps = set2_ex6.reps
target.exercises[ex6_idx].sets[2].weight_kg = 4.0
target.exercises[ex6_idx].sets[2].rpe = 9.0

print(f"\nAfter applying rule (set3 = set2 for ex5 & ex6):")
for ex_idx, ex in enumerate(target.exercises, 1):
    print(f"  [{ex_idx}] {ex.name}")
    for s_idx, s in enumerate(ex.sets, 1):
        print(f"    set{s_idx}: reps={s.reps}, weight={s.weight_kg}, rpe={s.rpe}")

# Save via ingest_activities (model-driven path, not CLI direct write)
now = datetime(2026, 9, 17, 10, 0, tzinfo=timezone.utc)
records = [
    ActivityRecord(
        type=ActivityType.WORKOUT_ADDED,
        timestamp=now,
        workout_id=WORKOUT_ID,
        source="plan14",
        workout_type="strength",
        date="2026-09-16",
        evidence={
            "date": "2026-09-16",
            "exercises": [
                {
                    "name": ex.name,
                    "sets": [
                        {
                            "reps": s.reps,
                            "weight_kg": s.weight_kg if s.weight_kg is not None else None,
                            "rpe": s.rpe if s.rpe is not None else None,
                        }
                        for s in ex.sets
                    ],
                    "notes": ex.notes,
                }
                for ex in target.exercises
            ],
            "notes": target.notes,
        },
    )
]

results = ingest_activities(records)
print("\nIngest results:")
for r in results:
    print(f"  accepted={r.accepted}, action={r.action}, error={r.error!r}, file={r.file_path}")

# Reload and verify
workouts_after = load_workouts()
target_after = find_workout_by_id(WORKOUT_ID)
print(f"\nVerification after save: {WORKOUT_ID} exists: {target_after is not None}")
if not target_after:
    print("ERROR: workout disappeared!")
    sys.exit(1)

print("\nFinal state:")
for ex_idx, ex in enumerate(target_after.exercises, 1):
    print(f"  [{ex_idx}] {ex.name}")
    for s_idx, s in enumerate(ex.sets, 1):
        print(f"    set{s_idx}: reps={s.reps}, weight={s.weight_kg}, rpe={s.rpe}")
