# Dispatcher and handler structure

## Dispatcher (`src/janus/__init__.py`)

```python
import sys
from janus.today import show_today, show_telegram
from janus.weekly import show_weekly
from janus.tasks_cli import handle_task_add, handle_task_complete
from janus.workout_cli import handle_workout_add, handle_workout_show

def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: janus <command>")
        return

    command = sys.argv[1]

    if command == "today":
        show_today()
    elif command == "telegram":
        show_telegram()
    elif command == "task":
        if len(sys.argv) < 3:
            print("Usage: janus task <add|complete> ...")
            return
        subcommand = sys.argv[2]
        if subcommand == "add":
            handle_task_add(sys.argv[3:])
        elif subcommand == "complete":
            handle_task_complete(sys.argv[3:])
        else:
            print(f"Unknown task subcommand: {subcommand}")
            print("Usage: janus task add <title> [--due YYYY-MM-DD] [--priority N]")
            print("       janus task complete <title>")
    elif command == "workout":
        if len(sys.argv) < 3:
            print("Usage: janus workout <add|show> ...")
            return
        subcommand = sys.argv[2]
        if subcommand == "add":
            handle_workout_add(sys.argv[3:])
        elif subcommand == "show":
            handle_workout_show(sys.argv[3:])
        else:
            print(f"Unknown workout subcommand: {subcommand}")
            print("Usage: janus workout add --type strength|running [options]")
            print("       janus workout show [--last N] [--from YYYY-MM-DD] [--to YYYY-MM-DD] [--running] [--exercise NAME]")
    elif command == "weekly":
        show_weekly()
    else:
        print(f"Unknown command: {command}")
```

Rules:

- Unknown top-level command → `print(f"Unknown command: {command}")` (no usage list).
- Unknown subcommand → print the specific usage for that command.
- Entry point returns, does NOT sys.exit. Handlers may sys.exit on invalid args.

## Handler signature

Every handler takes `args: list[str]` — the slice after the subcommand.

```python
def handle_workout_add(args: list[str]) -> None:
    """Parse 'janus workout add' arguments and save workout.

    Usage:
        janus workout add --type strength --exercise "Back Squat" --sets "5x80kg@8,5x80kg@8.5"
        janus workout add --type running --distance 5.0 --duration 30
        janus workout add --type strength --exercise "Bench Press" --sets "8x60kg@7" --date 2026-09-01
    """
```

The docstring's `Usage:` block is the canonical usage text. Print it on unknown subcommand from the dispatcher.

## Arg parsing loop

```python
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
    # ... more flags ...
    else:
        print(f"Error: unknown argument: {arg}", file=sys.stderr)
        sys.exit(1)
    i += 1
```

Patterns:

- Classic `while` loop with `i` index.
- Each flag that consumes a value does `i += 1` to advance past the value, then `i += 1` at the end of the loop body.
- Unknown flag → error + sys.exit(1) immediately.
- Value flags → check bounds before reading `args[i]`.

## Post-loop validation

After the parsing loop, validate that all required fields were provided:

```python
if workout_type is None:
    print("Error: --type is required (strength|running)", file=sys.stderr)
    sys.exit(1)

if workout_type == WorkoutType.STRENGTH:
    if not exercise_name:
        print("Error: --exercise is required for strength workouts", file=sys.stderr)
        sys.exit(1)
    if not sets_str:
        print("Error: --sets is required for strength workouts", file=sys.stderr)
        sys.exit(1)
```

This is where you catch missing required args that were not caught during parsing (e.g. `--exercise` is optional in parsing, but required for strength type).