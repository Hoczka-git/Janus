import sys, os, json
sys.path.insert(0, "/home/dan11hermes/workspaces/janus/src")

from datetime import datetime, timezone
from janus.models.workout import WorkoutType, Exercise, Set
from janus.services.activity_ingest import (
    ActivityRecord, ActivityType, ingest_activities,
)

now = datetime(2026, 9, 16, 10, 0, 0, tzinfo=timezone.utc)

exercises = [
    Exercise("Drop box jump", sets=[
        Set(reps=6, weight_kg=None, rpe=None),
        Set(reps=6, weight_kg=None, rpe=None),
    ], notes=None),
    Exercise("Pompki plyometryczne na boskie", sets=[
        Set(reps=8, weight_kg=None, rpe=None),
        Set(reps=8, weight_kg=None, rpe=None),
    ], notes=None),
    Exercise("Martwy ciąg trap bar", sets=[
        Set(reps=5, weight_kg=90.0, rpe=6.0),
        Set(reps=5, weight_kg=100.0, rpe=6.0),
        Set(reps=5, weight_kg=110.0, rpe=7.0),
    ], notes="Warn: chest-level exercise planned in Plan B Week 2"),
    Exercise("Wyciskanie sztangi leżąc", sets=[
        Set(reps=0, weight_kg=52.5, rpe=7.0),
        Set(reps=0, weight_kg=55.0, rpe=8.0),
        Set(reps=0, weight_kg=57.5, rpe=9.0),
    ], notes="Liczba powtórzeń: niejednoznaczna w planie T2 — niezgadnięte, reps=0"),
    Exercise("Wiosłowanie hantlą w oparciu o ławkę", sets=[
        Set(reps=8, weight_kg=20.0, rpe=7.0),
        Set(reps=10, weight_kg=24.0, rpe=8.0),
        Set(reps=0, weight_kg=None, rpe=9.0),
    ], notes="Zakres powtórzeń 8/10 i ciężar 20/24; trzecia seria niejednoznaczna (reps/weight=None)"),
    Exercise("Wznosy hantli bokiem siedząc", sets=[
        Set(reps=15, weight_kg=3.0, rpe=8.0),
        Set(reps=10, weight_kg=4.0, rpe=9.0),
        Set(reps=0, weight_kg=None, rpe=None),
    ], notes="Powtórzenia 15/10, ciężar 3/4 kg, RPE 8/9; trzecia seria: brak danych → None"),
    Exercise("Unoszenie nóg w zwisie na drążku", sets=[
        Set(reps=10, weight_kg=None, rpe=8.0),
        Set(reps=8, weight_kg=None, rpe=9.0),
        Set(reps=6, weight_kg=None, rpe=8.0),
    ], notes="Masa ciała"),
    Exercise("Wspięcia jednonóż stojąc", sets=[
        Set(reps=10, weight_kg=16.0, rpe=8.0),
        Set(reps=10, weight_kg=16.0, rpe=9.0),
        Set(reps=10, weight_kg=16.0, rpe=9.0),
    ], notes=None),
]

record = ActivityRecord(
    type=ActivityType.WORKOUT_ADDED,
    source="plan14",
    timestamp=now,
    workout_id="sw-20260916",
    workout_type="strength",
    evidence={
        "notes": "PLAN 14, Trening B, Tydzień 2 — drugi tydzień planu, po tygodniu kalibracyjnym",
        "exercises": exercises,
    },
)

results = ingest_activities([record])
for r in results:
    print(json.dumps({
        "record_id": r.record_id,
        "accepted": r.accepted,
        "wrote": r.wrote,
        "action": r.action,
        "error": r.error,
        "file_path": r.file_path,
    }, indent=2, ensure_ascii=False))
