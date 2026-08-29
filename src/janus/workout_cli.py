"""CLI command handler for 'janus workout add' and 'janus workout show'."""


import sys
from datetime import date, datetime, timezone
from typing import Optional

from janus.models.workout import Exercise, RunningWorkout, Set, StrengthWorkout, WorkoutType
from janus.integrations.workout_md import (
    find_history_by_exercise,
    find_last_n,
    find_running_workouts,
    find_workouts_by_date_range,
    load_workouts,
    save_workout,
)


def _generate_id(workout_type: WorkoutType) -> str:
    """Generate next available ID: sw-001, rw-001, etc."""
    prefix = "sw" if workout_type == WorkoutType.STRENGTH else "rw"
    existing = load_workouts()
    max_num = 0
    for w in existing:
        if w.workout_type == workout_type:
            try:
                num = int(w.id.split("-")[1])
                max_num = max(max_num, num)
            except (ValueError, IndexError):
                pass
    return f"{prefix}-{max_num + 1:03d}"



def _parse_date(s: Optional[str]) -> date:
    """Parse YYYY-MM-DD or return today."""
    if s is None:
        return date.today()
    try:
        return date.fromisoformat(s)
    except ValueError:
        print(f"Error: invalid date: {s}", file=sys.stderr)
        sys.exit(1)


def _parse_datetime(date_val: date) -> datetime:
    """Convert date to datetime at midnight UTC."""
    return datetime(date_val.year, date_val.month, date_val.day, tzinfo=timezone.utc)


def _parse_sets(sets_str: str) -> list[Set]:
    """Prase sets string like '5x80kg@8.0,5x80kg@8.5,5x80kg'."""
    sets = []
    for part in sets_str.split(","):
        part = part.strip()
        if not part:
            continue
        if "x" not in part:
            print(f"Error: invalid set format: {part}", file=sys.stderr)
            sys.exit(1)
        reps_str, rest = part.split("x", 1)
        try:
            reps = int(reps_str)
        except ValueError:
            print(f"Error: invalid reps: {reps_str}", file=sys.stderr)
            sys.exit(1)

        weight_kg = None
        rpe = None

        if rest:
            if "@" in rest:
                weight_str, rpe_str = rest.split("@", 1)
                # Parse weight from weight_str (e.g. "80kg")
                weight_str = weight_str.strip()
                if weight_str:
                    if weight_str.endswith("kg"):
                        weight_str = weight_str[:-2]
                    try:
                        weight_kg = float(weight_str)
                    except ValueError:
                        print(f"Error: invalid weight: {weight_str}", file=sys.stderr)
                        sys.exit(1)
                # Parse RPE from rpe_str (e.g. "8.0")
                try:
                    rpe = float(rpe_str)
                except ValueError:
                    print(f"Error: invalid RPE: {rpe_str}", file=sys.stderr)
                    sys.exit(1)
            else:
                weight_str = rest

                weight_str = weight_str.strip()
                if weight_str:
                    if weight_str.endswith("kg"):
                        weight_str = weight_str[:-2]
                    try:
                        weight_kg = float(weight_str)
                    except ValueError:
                        print(f"Error: invalid weight: {weight_str}", file=sys.stderr)
                        sys.exit(1)

        sets.append(Set(reps=reps, weight_kg=weight_kg, rpe=rpe))

    return sets


def handle_workout_add(args: list[str]) -> None:
    """Parse 'janus workout add' arguments and save workout.

    Usage:
        janus workout add --type strength --exercise "Back Squat" --sets "5x80kg@8,5x80kg@8.5"
        janus workout add --type running --distance 5.0 --duration 30
        janus workout add --type strength --exercise "Bench Press" --sets "8x60kg@7" --date 2026-09-01
    """
    workout_type = None
    exercise_name = None
    sets_str = None
    distance_km = None
    duration_minutes = None
    avg_hr_bpm = None
    elevation_m = None
    notes = None
    source = "manual"
    date_str = None

    i = 0
    while i < len(args):
        arg = args[i]

        if arg == "--type":
            i += 1
            if i >= len(args):
                print("Error: --type requires a value (strength|running)", file=sys.stderr)
                sys.exit(1)
            if args[i] == "strength":
                workout_type = WorkoutType.STRENGTH
            elif args[i] == "running":
                workout_type = WorkoutType.RUNNING
            else:
                print(f"Error: invalid workout type: {args[i]}", file=sys.stderr)
                sys.exit(1)
        elif arg == "--exercise":
            i += 1
            if i >= len(args):
                print("Error: --exercise requires a value", file=sys.stderr)
                sys.exit(1)
            exercise_name = args[i]
        elif arg == "--sets":
            i += 1
            if i >= len(args):
                print("Error: --sets requires a value", file=sys.stderr)
                sys.exit(1)
            sets_str = args[i]
        elif arg == "--distance":
            i += 1
            if i >= len(args):
                print("Error: --distance requires a value", file=sys.stderr)
                sys.exit(1)
            try:
                distance_km = float(args[i])
            except ValueError:
                print(f"Error: invalid distance: {args[i]}", file=sys.stderr)
                sys.exit(1)
        elif arg == "--duration":
            i += 1
            if i >= len(args):
                print("Error: --duration requires a value", file=sys.stderr)
                sys.exit(1)
            try:
                duration_minutes = float(args[i])
            except ValueError:
                print(f"Error: invalid duration: {args[i]}", file=sys.stderr)
                sys.exit(1)
        elif arg == "--hr":
            i += 1
            if i >= len(args):
                print("Error: --hr requires a value", file=sys.stderr)
                sys.exit(1)
            try:
                avg_hr_bpm = float(args[i])
            except ValueError:
                print(f"Error: invalid heart rate: {args[i]}", file=sys.stderr)
                sys.exit(1)
        elif arg == "--elevation":
            i += 1
            if i >= len(args):
                print("Error: --elevation requires a value", file=sys.stderr)
                sys.exit(1)
            try:
                elevation_m = float(args[i])
            except ValueError:
                print(f"Error: invalid elevation: {args[i]}", file=sys.stderr)
                sys.exit(1)
        elif arg == "--notes":
            i += 1
            if i >= len(args):
                print("Error: --notes requires a value", file=sys.stderr)
                sys.exit(1)
            notes = args[i]
        elif arg == "--source":
            i += 1
            if i >= len(args):
                print("Error: --source requires a value", file=sys.stderr)
                sys.exit(1)
            source = args[i]
        elif arg == "--date":
            i += 1
            if i >= len(args):
                print("Error: --date requires a value (YYYY-MM-DD)", file=sys.stderr)
                sys.exit(1)
            date_str = args[i]
        else:
            print(f"Error: unknown argument: {arg}", file=sys.stderr)
            sys.exit(1)
        i += 1

    if workout_type is None:
        print("Error: --type is required (strength|running)", file=sys.stderr)
        sys.exit(1)

    workout_date = _parse_date(date_str)

    if workout_type == WorkoutType.STRENGTH:
        if not exercise_name:
            print("Error: --exercise is required for strength workouts", file=sys.stderr)
            sys.exit(1)
        if not sets_str:
            print("Error: --sets is required for strength workouts", file=sys.stderr)
            sys.exit(1)

        sets = _parse_sets(sets_str)
        exercise = Exercise(name=exercise_name, sets=sets)
        workout = StrengthWorkout(
            id=_generate_id(workout_type),
            date=_parse_datetime(workout_date),
            workout_type=WorkoutType.STRENGTH,
            source=source,
            exercises=[exercise],
            notes=notes,
        )
    else:  # RUNNING
        if distance_km is None:
            print("Error: --distance is required for running workouts", file=sys.stderr)
            sys.exit(1)
        if duration_minutes is None:
            print("Error: --duration is required for running workouts", file=sys.stderr)
            sys.exit(1)

        workout = RunningWorkout(
            id=_generate_id(workout_type),
            date=_parse_datetime(workout_date),
            workout_type=WorkoutType.RUNNING,
            source=source,
            distance_km=distance_km,
            duration_minutes=duration_minutes,
            avg_hr_bpm=avg_hr_bpm,
            elevation_m=elevation_m,
            notes=notes,
        )

    save_workout(workout)

    print(f"Added workout: {workout.id}")
    print(f"  Type: {workout.workout_type.value}")
    print(f"  Date: {workout_date.isoformat()}")
    if workout.notes:
        print(f"  Notes: {workout.notes}")


def handle_workout_show(args: list[str]) -> None:
    """Parse 'janus workout show' arguments and display workouts.

    Usage:
        janus workout show                   # last 5 workouts
        janus workout show --last 10        # last 10 workouts
        janus workout show --from 2026-09-01 --to 2026-09-30
        janus workout show --running         # only running workouts
        janus workout show --exercise "Back Squat"  # strength history
    """
    last_n = 5
    from_date = None
    to_date = None
    show_running = False
    exercise_name = None

    i = 0
    while i < len(args):
        arg = args[i]

        if arg == "--last":
            i += 1
            if i >= len(args):
                print("Error: --last requires a value", file=sys.stderr)
                sys.exit(1)
            try:
                last_n = int(args[i])
                if last_n < 1:
                    raise ValueError
            except ValueError:
                print(f"Error: invalid --last value: {args[i]}", file=sys.stderr)
                sys.exit(1)
        elif arg == "--from":
            i += 1
            if i >= len(args):
                print("Error: --from requires a value (YYYY-MM-DD)", file=sys.stderr)
                sys.exit(1)
            try:
                from_date = date.fromisoformat(args[i])
            except ValueError:
                print(f"Error: invalid from date: {args[i]}", file=sys.stderr)
                sys.exit(1)
        elif arg == "--to":
            i += 1
            if i >= len(args):
                print("Error: --to requires a value (YYYY-MM-DD)", file=sys.stderr)
                sys.exit(1)
            try:
                to_date = date.fromisoformat(args[i])
            except ValueError:
                print(f"Error: invalid to date: {args[i]}", file=sys.stderr)
                sys.exit(1)
        elif arg == "--running":
            show_running = True
        elif arg == "--exercise":
            i += 1
            if i >= len(args):
                print("Error: --exercise requires a value", file=sys.stderr)
                sys.exit(1)
            exercise_name = args[i]
        else:
            print(f"Error: unknown argument: {arg}", file=sys.stderr)
            sys.exit(1)
        i += 1

    if show_running and exercise_name:
        print("Error: --running and --exercise are mutually exclusive", file=sys.stderr)
        sys.exit(1)

    workouts = []

    if exercise_name:
        workouts = find_history_by_exercise(exercise_name)
        if not workouts:
            print(f"No workouts found for exercise: {exercise_name}")
            return
        print(f"History for exercise: {exercise_name}")
        print("-" * 40)
        for w in workouts:
            print(f"  {w.id} | {w.date.date().isoformat()} | "
                  f"{w.exercises[0].name} x {w.exercises[0].sets[0].reps} reps x {w.exercises[0].sets[0].weight_kg}kg")
    elif show_running:
        workouts = find_running_workouts()
        if not workouts:
            print("No running workouts found")
            return
        print("Running workouts:")
        print("-" * 40)
        for w in workouts:
            hr_str = f" | HR: {w.avg_hr_bpm}bpm" if w.avg_hr_bpm else ""
            elev_str = f" | Elevation: {w.elevation_m}m" if w.elevation_m else ""
            print(f"  {w.id} | {w.date.date().isoformat()} | "
                  f"{w.distance_km}km in {w.duration_minutes}min{hr_str}{elev_str}")
    elif from_date or to_date:
        start_dt = _parse_datetime(from_date) if from_date else None
        end_dt = _parse_datetime(to_date) if to_date else None
        workouts = find_workouts_by_date_range(start_dt, end_dt)
        if not workouts:
            print("No workouts found in date range")
            return
        print(f"Workouts from {from_date.isoformat() if from_date else '...'} to "
              f"{to_date.isoformat() if to_date else '...'}")
        print("-" * 40)
        for w in workouts:
            if isinstance(w, StrengthWorkout):
                ex_names = ", ".join(e.name for e in w.exercises)
                print(f"  {w.id} | {w.date.date().isoformat()} | "
                      f"Strength: {ex_names}")
            elif isinstance(w, RunningWorkout):
                print(f"  {w.id} | {w.date.date().isoformat()} | "
                      f"Running: {w.distance_km}km in {w.duration_minutes}min")
            else:
                print(f"  {w.id} | {w.date.date().isoformat()} | "
                      f"Unknown type ({w.workout_type.value})")
    else:
        workouts = find_last_n(last_n)
        if not workouts:
            print("No workouts found")
            return
        print(f"Last {len(workouts)} workout(s):")
        print("-" * 40)
        for w in workouts:
            if isinstance(w, StrengthWorkout):
                ex_names = ", ".join(e.name for e in w.exercises)
                print(f"  {w.id} | {w.date.date().isoformat()} | "
                      f"Strength: {ex_names}")
            elif isinstance(w, RunningWorkout):
                print(f"  {w.id} | {w.date.date().isoformat()} | "
                      f"Running: {w.distance_km}km in {w.duration_minutes}min")
            else:
                print(f"  {w.id} | {w.date.date().isoformat()} | "
                      f"Unknown type ({w.workout_type.value})")