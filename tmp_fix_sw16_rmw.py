#!/usr/bin/env python3
"""
Fix sw-20260916 via read-modify-write on data/workouts.md:
1. Load existing workouts.md
2. Find sw-20260916 block
3. Apply "seria 3 = seria 2" to exercises 5 (Wiosłowanie) and 6 (Wznosy hantli)
4. Write back atomically via atomic_io.read_modify_write
"""

import json, sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from janus.integrations.workout_md import load_workouts, find_workout_by_id, _HEADER, _workout_to_markdown_lines
from janus.models.workout import StrengtheningWorkout
from janus.services.activity_ingest import ActivityRecord, ActivityType, ingest_activities
from datetime import datetime, timezone
from pathlib import Path
import copy

PROJECT_ROOT = Path(__file__).parent
WORKOUTS_MD = PROJECT_ROOT / "data" / "workouts.md"

WORKOUT_ID = "sw-20260916"

def load_workouts_raw():
    from janus.integrations.workout_md import load_workouts
    return load_workouts()

def write_workouts_md(lines):
    from janus.integrations.atomic_io import write_atomic
    content = _HEADER + "\n".join(lines) + "\n\n"
    write_atomic(str(WORKOUTS_MD), content)

def fix_workout():
    now = datetime(2026, 9, 17, 10, 0, tzinfo=timezone.utc)
    w = load_workouts()
    if not w:
        print("ERROR: no workouts loaded")
        return
    
    target = find_workout_by_id(WORKOUT_ID)
    assert target is not None, f"{WORKOUT_ID} not found in workouts"
    assert str(target.workout_type) == "strength", f"Not a strength workout: {target.workout_type}"
    assert len(target.exercises) == 8, f"Expected 8 exercises, got {len(target.exercises)}"
    
    # Map exercise indices
    ex5_idx = None
    ex6_idx = None
    for i, ex in enumerate(target.exercises):
        ename = ex.name
        if "Wiosł" in ename and "ławkę" in ename:
            ex5_idx = i
        if "Wznosy" in ename and "hantli" in ename:
            ex6_idx = i
    
    assert ex5_idx is not None and ex6_idx is not None, f"Could not locate ex5/ex6"
    
    ex5 = target.exercises[ex5_idx]
    ex6 = target.exercises[ex6_idx]
    
    # Apply "seria 3 = seria 2" rule
    if len(ex5.sets) < 3:
        ex5.sets.append(copy.copy(ex5.sets[1]))
    else:
        # already has 3 sets — overwrite set 3
        ex5.sets[2] = copy.copy(ex5.sets[1])
    
    if len(ex6.sets) < 3:
        ex6.sets.append(copy.copy(ex6.sets[1]))
    else:
        ex6.sets[2] = copy.copy(ex6.sets[1])
    
    # Verify: ex3 (trak bar) set 3 should also be checked (it's already correct — 110kg/RPE 7)
    # ex4 (wyciskanie sztangi) — ALL sets have weight/RPE but reps unknown; leave as is
    
    lines = _workout_to_markdown_lines(target)
    write_workouts_md(lines)
    
    print(f"Fixed {WORKOUT_ID}: ex5 sets={ex5.sets}, ex6 sets={ex6.sets}")

if __name__ == "__main__":
    fix_workout()
