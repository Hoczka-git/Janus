import json, sys, os
sys.path.insert(0, "/home/dan11hermes/workspaces/janus/src")
os.environ["PYTHONPATH"] = "src"

from datetime import datetime, timezone
from janus.services.activity_ingest import ActivityRecord, ActivityType, ingest_activities

W = "strength"
dt = datetime(2026, 9, 16, 10, 0, 0, tzinfo=timezone.utc)

exercises = [
    {
        "name": "Drop box jump",
        "sets": [
            {"reps": 6, "weight_kg": None, "rpe": None},
            {"reps": 6, "weight_kg": None, "rpe": None},
        ],
        "notes": "Bez dodatkowego ciężaru",
    },
    {
        "name": "Pompki plyometryczne na boskie",
        "sets": [
            {"reps": 8, "weight_kg": None, "rpe": None},
            {"reps": 8, "weight_kg": None, "rpe": None},
        ],
        "notes": "Bez dodatkowego ciężaru",
    },
    {
        "name": "Martwy ciąg trap bar",
        "sets": [
            {"reps": 5, "weight_kg": 90.0, "rpe": 6.0},
            {"reps": 5, "weight_kg": 100.0, "rpe": 6.0},
            {"reps": 5, "weight_kg": 110.0, "rpe": 7.0},
        ],
    },
    {
        "name": "Wyciskanie sztangi leżąc",
        "sets": [
            {"reps": 0, "weight_kg": 52.5, "rpe": 7.0},
            {"reps": 0, "weight_kg": 55.0, "rpe": 8.0},
            {"reps": 0, "weight_kg": 57.5, "rpe": 9.0},
        ],
        "notes": "Liczba powtórzeń niejednoznaczna w planie T2 — niezgadnięte, pozostawione 0",
    },
    {
        "name": "Wiosłowanie hantlą w oparciu o ławkę",
        "sets": [
            {"reps": 8, "weight_kg": 20.0, "rpe": 7.0},
            {"reps": 10, "weight_kg": 24.0, "rpe": 8.0},
            {"reps": 0, "weight_kg": None, "rpe": 9.0},
        ],
        "notes": "Zakres powtórzeń 8/10 i ciężar 20/24 dla 3 serii — trzecia seria niejednoznaczna; reps/weight pozostawione 0/null",
    },
    {
        "name": "Wznosy hantli bokiem siedząc",
        "sets": [
            {"reps": 15, "weight_kg": 3.0, "rpe": 8.0},
            {"reps": 10, "weight_kg": 4.0, "rpe": 9.0},
            {"reps": 0, "weight_kg": None, "rpe": None},
        ],
        "notes": "Powtórzenia 15/10, ciężar 3/4 kg, RPE 8/9 dla 3 serii; trzecia seria null zgodnie z planem",
    },
    {
        "name": "Unoszenie nóg w zwisie na drążku",
        "sets": [
            {"reps": 10, "weight_kg": None, "rpe": 8.0},
            {"reps": 8, "weight_kg": None, "rpe": 9.0},
            {"reps": 6, "weight_kg": None, "rpe": 8.0},
        ],
        "notes": "Masa ciała",
    },
    {
        "name": "Wspięcia jednonóż stojąc",
        "sets": [
            {"reps": 10, "weight_kg": 16.0, "rpe": 8.0},
            {"reps": 10, "weight_kg": 16.0, "rpe": 9.0},
            {"reps": 10, "weight_kg": 16.0, "rpe": 9.0},
        ],
    },
]

record = ActivityRecord(
    type=ActivityType.WORKOUT_ADDED,
    workout_type=W,
    workout_id="sw-20260916",
    source="plan14",
    timestamp=dt,
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
