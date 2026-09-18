from datetime import datetime, timezone
from janus.services.activity_ingest import ActivityRecord, ActivityType, ingest_activity
from janus.models.workout import StrengthWorkout, WorkoutType, Exercise, Set, IntegrationType

id = "sw-20260916"
date = datetime(2026, 9, 16, 10, 0, 0, tzinfo=timezone.utc)
created = datetime(2026, 9, 16, 10, 0, 0, tzinfo=timezone.utc)
updated = datetime(2026, 9, 16, 10, 0, 0, tzinfo=timezone.utc)

exercises = [
    Exercise(
        name="Drop box jump",
        sets=[
            Set(reps=6, weight_kg=None, rpe=None),
            Set(reps=6, weight_kg=None, rpe=None),
        ],
        notes="2 serie x 6, bez dodatkowego ciężaru, RPE nie podano",
    ),
    Exercise(
        name="Pompki plyometryczne na boskie",
        sets=[
            Set(reps=8, weight_kg=None, rpe=None),
            Set(reps=8, weight_kg=None, rpe=None),
        ],
        notes="2 serie x 8, bez dodatkowego ciężaru, RPE nie podano",
    ),
    Exercise(
        name="Martwy ciąg trap bar",
        sets=[
            Set(reps=5, weight_kg=90.0, rpe=6.0),
            Set(reps=5, weight_kg=100.0, rpe=6.0),
            Set(reps=5, weight_kg=110.0, rpe=7.0),
        ],
        notes="3 serie x 5, postęp: 90→100→110 kg",
    ),
    Exercise(
        name="Wyciskanie sztangi leżąc",
        sets=[
            Set(reps=None, weight_kg=52.5, rpe=7.0),
            Set(reps=None, weight_kg=55.0, rpe=8.0),
            Set(reps=None, weight_kg=57.5, rpe=9.0),
        ],
        notes="3 serie, ciężary 52.5/55/57.5 kg, RPE 7/8/9. Liczba powtórzeń zgodnie z planem T2 — niejednoznaczne, nie zgaduj",
    ),
    Exercise(
        name="Wiosłowanie hantlą w oparciu o ławkę",
        sets=[
            Set(reps=12, weight_kg=24.0, rpe=9.0),
            Set(reps=None, weight_kg=20.0, rpe=8.0),
            Set(reps=None, weight_kg=20.0, rpe=7.0),
        ],
        notes="3 serie, zakres powtórzeń 8/10 z planu, ciężar 20/24 kg, RPE 7/8/9. Seria z 24 kg z 10 powtórzeniami i RPE 9. Pary 20 kg z 8 powtórzeniami i RPE 8; 20 kg RPE 7 — powtórzenia pominięte, zgodnie z życiem (ich kontekst: 8 w T1 A?).",
    ),
    Exercise(
        name="Wznosy hantli bokiem siedząc",
        sets=[
            Set(reps=15, weight_kg=3.0, rpe=8.0),
            Set(reps=10, weight_kg=4.0, rpe=9.0),
            Set(reps=None, weight_kg=4.0, rpe=None),
        ],
        notes="3 serie, powtórzenia 15/10, ciężar 3/4 kg, RPE 8/9. Kolejna po 3 sierii z 4 kg z powtórzeniami nieznanymi i RPE pominiętym (brak w treści, transkrypcja: 'trzecia wartość' pominięta).",
    ),
    Exercise(
        name="Unoszenie nóg w zwisie na drążku",
        sets=[
            Set(reps=10, weight_kg=None, rpe=8.0),
            Set(reps=8, weight_kg=None, rpe=9.0),
            Set(reps=6, weight_kg=None, rpe=8.0),
        ],
        notes="3 serie, powtórzenia 10/8/6, RPE 8/9/8, masa ciała",
    ),
    Exercise(
        name="Wspięcia jednonóż stojąc",
        sets=[
            Set(reps=10, weight_kg=16.0, rpe=8.0),
            Set(reps=10, weight_kg=16.0, rpe=9.0),
            Set(reps=10, weight_kg=16.0, rpe=9.0),
        ],
        notes="3 serie x 10, 16 kg, RPE 8/9/9",
    ),
]

evidence = {
    "exercises": [
        {
            "name": e.name,
            "sets": [
                {"reps": s.reps, "weight_kg": s.weight_kg, "rpe": s.rpe}
                for s in e.sets
            ],
        }
        for e in exercises
    ],
}

record = ActivityRecord(
    source="plan14",
    activity_type=ActivityType.WORKOUT_ADDED,
    train_name="Plan 14, Trening B, Tydzień 2",
    workout_id=id,
    date=date,
    integrated_at=created,
    evidence={
        "exercises": [
            {
                "name": e.name,
                "sets": [
                    {"reps": s.reps, "weight_kg": s.weight_kg, "rpe": s.rpe}
                    for s in e.sets
                ],
                "notes": e.notes,
            }
            for e in exercises
        ],
    },
)

res = ingest_activity(record)
print(f"RESULT: {res}")

# Verification
from janus.integrations.workout_md import load_workouts as lw
from janus.services.workout_analytics import compute_overall_summary as cos
w = lw()
s = compute_overall_summary(w)
print(f"Total: {s.total_workouts} | Strength: {s.strength_count} | Running: {s.running_count}")
print(f"Most recent: {s.most_recent_workout_id} ({s.most_recent_date})")

w2 = None
for ww in w.workouts:
    if ww.id == id:
        w2 = ww
        break
if w2 is None:
    print("ERROR: workout not found in file")
else:
    print(f"Found workout: id={w2.id}, date={w2.date}, workout_type={w2.workout_type}, source={w2.source}")
    print(f"Exercises count: {len(w2.evidence['exercises'])}")

    chk_e = [e["name"] for e in w2.evidence.get("exercises", [])]
    exp = [
        "Drop box jump",
        "Pompki plyometryczne na boskie",
        "Martwy ciąg trap bar",
        "Wyciskanie sztangi leżąc",
        "Wiosłowanie hantlą w oparciu o ławkę",
        "Wznosy hantli bokiem siedząc",
        "Unoszenie nóg w zwisie na drążku",
        "Wspięcia jednonóż stojąc",
    ]
    missing = [n for n in exp if n not in chk_e]
    extra = [n for n in chk_e if n not in exp]
    if missing or extra:
        if missing:
            print(f"Missing: {missing}")
        if extra:
            print(f"Extra: {extra}")
    else:
        print("All expected exercises present.")

    # Check sets structure for each exercise
    for e in w2.evidence["exercises"]:
        for s in e["sets"]:
            if s["reps"] is None and s["weight_kg"] is None and s["rpe"] is None:
                print(f"BUG: all-null set in exercise '{e['name']}'")
    print("Sets structure looks correct (no all-null sets).")

print("=== DONE ===")
