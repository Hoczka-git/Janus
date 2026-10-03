---
name: janus-cli-patterns
description: >
  Janus CLI subcommand patterns: handler tests, ID pitfalls.
---

# Janus CLI Patterns

Use when adding or modifying a `janus <command>` subcommand, or when
writing handler-level tests for CLI commands in the Janus project.

## Trigger

- Adding a new subcommand (e.g. `janus workout add`, `janus workout show`).
- Extending an existing subcommand with new arguments or flag combinations.
- Writing handler tests that verify CLI output via `capsys` + mocked service calls.
- Debugging CLI tests that fail because of real ID generation or state leakage.

## What this skill is NOT

- It is not a full CLI framework guide. The project uses plain `sys.argv` dispatch.
- It is not a testing general guide. It only covers the CLI handler test pattern.

## Dispatcher structure (`src/janus/__init__.py`)

The `main()` function dispatches on `sys.argv[1]` → subcommand → handler.

When adding a new top-level command:

1. Import the handler function(s) from the new `*_cli.py` module.
2. Add a branch: `elif command == "workout":`
3. Inside, dispatch on `sys.argv[2]` (subcommand).
4. For each subcommand, slice `sys.argv[3:]` into the handler.
5. For unknown subcommand, print usage and return (NOT sys.exit — the entry point should not exit on unknown subcommand; handlers may sys.exit on invalid args).

Existing pattern (from `tasks_cli.py` → `__init__.py`):

```python
from janus.tasks_cli import handle_task_add, handle_task_complete

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
```

## Arg parsing — inline, args-first

Handlers take `args: list[str]` (the slice after the subcommand). Parse loops:

```python
i = 0
while i < len(args):
    arg = args[i]
    if arg == "--type":
        i += 1
        if i >= len(args):
            print("Error: --type requires a value", file=sys.stderr)
            sys.exit(1)
        value = args[i]
        # validate / store
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
```

Rules:

- Unknown flags → error + `sys.exit(1)`.
- Flags that require a value → check `i+1 < len(args)`, else error.
- Positional title (like `task add`) collects into a list and joins with space.
- After the loop, validate required fields are present (e.g. `--type` was given).

## Parsing helpers for domain-specific DSL

When a flag accepts a compact DSL (e.g. `--sets "5x80kg@8,5x80kg@8.5"`), write a separate pure helper (no `sys.exit`, return parsed value or raise `ValueError`) and call it from the handler. The handler catches `ValueError` and sys.exits.

Pattern for `--sets` (from `workout_cli.py`):

```python
def _parse_sets(sets_str: str) -> list[Set]:
    """Parse '5x80kg@8.0,5x80kg@8.5,5x80kg' → list[Set]."""
    sets = []
    for part in sets_str.split(","):
        part = part.strip()
        if not part:
            continue
        if "x" not in part:
            raise ValueError(f"invalid set format: {part}")
        reps_str, rest = part.split("x", 1)
        reps = int(reps_str)
        weight_kg = None
        rpe = None
        if rest:
            if "@" in rest:
                weight_str, rpe_str = rest.split("@", 1)
                weight_str = weight_str.strip()
                if weight_str:
                    if weight_str.endswith("kg"):
                        weight_str = weight_str[:-2]
                    weight_kg = float(weight_str)
                rpe = float(rpe_str)
            else:
                weight_str = rest.strip()
                if weight_str:
                    if weight_str.endswith("kg"):
                        weight_str = weight_str[:-2]
                    weight_kg = float(weight_str)
        sets.append(Set(reps=reps, weight_kg=weight_kg, rpe=rpe))
    return sets
```

Key lessons:

- When `@` is present, BOTH the weight part and the RPE part must be parsed — not just the RPE. Missing this caused a real bug (weight parsed as None).
- Bodyweight sets (`"10x"`) have `rest` empty → weight stays None.
- Each parse failure should raise `ValueError` with a clear message; the handler translates to stderr + sys.exit(1).

## ID generation

When the domain model uses sequential IDs (`sw-001`, `rw-001`, ...), write a helper that reads existing workouts and picks the next number:

```python
def _generate_id(workout_type: WorkoutType) -> str:
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
```

Pitfall — this calls `load_workouts()` which reads the real `data/workouts.md`. In CLI handler TESTS that mock `save_workout`, the ID helper still calls the real loader and returns IDs based on the actual repo state (e.g. `sw-002` instead of `sw-001`). The fix is to monkeypatch `load_workouts` to return `[]` in each CLI test that asserts a specific ID.

## Cross-cutting field propagation

When a new field is added to a domain model (e.g. `state` and `progress` on `Task`),
the change must propagate through every layer that touches the model. Missing one layer
produces a half-implemented feature that works in some code paths and silently drops the
field in others.

Propagation checklist (worked example: `Task.state` + `Task.progress`):

1. **Domain model** (`src/janus/models/task.py`) — add the field to the dataclass,
   including validation in `__post_init__`. Export any constants (e.g. `ALLOWED_STATES`)
   that consumers need.

2. **Persistence parse** (`src/janus/integrations/markdown_tasks.py`) — extend the
   line parser to extract the new field from markdown metadata. Unknown fields should be
   preserved (e.g. `_extract_unknown_metadata`) so that hand-edited files don't lose data.

3. **Persistence format** (`src/janus/integrations/markdown_tasks.py`) — extend the
   formatter (`_format_task_line`) to write the new field back. Known fields are normalized;
   unknown fields are appended after them.

4. **Service layer** (`src/janus/services/tasks.py`) — add service functions that read
   the existing file, mutate the field on the matched task, and rewrite. The function must
   preserve all other metadata (notes, due date, priority, extra_metadata).

5. **CLI handler** (`src/janus/tasks_cli.py`) — add a handler that parses CLI args into
   the new field, calls the service function, and prints a confirmation. The handler should
   validate the value against the same constants the model uses.

6. **Dispatcher** (`src/janus/__init__.py`) — wire the new handler into the dispatch tree
   under the appropriate top-level command and subcommand.

7. **Attention/engine scoring** (if applicable) — if the new field affects prioritization
   (e.g. `state == "blocked"` → +30 attention), update the scoring function. Add tests that
   create tasks with the new field and verify the scoring change.

Pitfall — forgetting layer 7. The attention engine already referenced `task.state` before
any tests existed for it. Without tests, a future refactor could remove the scoring without
any test failing. Always add at least one attention-scoring test per new field that affects
prioritization.

Pitfall — partial implementation. A feature is not done when the CLI handler works in
isolation. It is done when the full propagation chain is implemented AND tested at each layer
that carries the field. The task state/progress feature was already implemented across all
layers in the working tree before any tests existed for it — the gap was tests, not code.

## CLI handler test pattern

Style: match `tests/test_tasks_cli.py` — capsys for output/err, mock the service call, assert on printed strings.

### Add handler tests

```python
def test_add_strength_minimal(self, capsys, monkeypatch):
    monkeypatch.setattr("janus.workout_cli.load_workouts", lambda: [])
    with patch("janus.workout_cli.save_workout") as mock_save:
        mock_save.return_value = None
        handle_workout_add([
            "--type", "strength",
            "--exercise", "Back Squat",
            "--sets", "5x80kg@8,5x80kg@8.5",
        ])
    out = capsys.readouterr().out
    assert "Added workout: sw-001" in out
    assert "Type: strength" in out
```

Rules:

- Always monkeypatch `load_workouts` → `[]` when testing ID-dependent output.
- Mock the persistence call (`save_workout`), not the whole module — the handler should still run the real parsing and validation.
- Assert on exact printed strings (e.g. `"Added workout: sw-001"`, `"Type: strength"`).
- For error cases, assert `pytest.raises(SystemExit)` and check `capsys.readouterr().err` for the error substring.

### Show handler tests

Tests for `handle_workout_show` mock the query functions (`find_last_n`, `find_running_workouts`, `find_history_by_exercise`, `find_workouts_by_date_range`) and assert on the printed table.

```python
def test_show_running(self, capsys):
    with patch("janus.workout_cli.find_running_workouts") as mock_find:
        mock_find.return_value = [
            RunningWorkout(
                id="rw-001",
                date=_dt_full(2026, 9, 1, 18, 0),
                workout_type=WorkoutType.RUNNING,
                distance_km=5.0,
                duration_minutes=30.0,
                avg_hr_bpm=145.0,
                elevation_m=80.0,
            ),
        ]
        handle_workout_show(["--running"])
    out = capsys.readouterr().out
    assert "rw-001" in out
    assert "HR: 145.0bpm" in out  # note: float preserves .0
    assert "Elevation: 80.0m" in out
```

Watch out: float values print with `.0` (e.g. `145.0bpm`, not `145bpm`). Assert the actual output, not what you assumed.

## Command-line interface surface

Keep the usage messages consistent across subcommands. Print them on unknown subcommand, not on first run.

Example (from `workout_cli.py`):

```
Usage: janus workout add --type strength|running [options]
       janus workout show [--last N] [--from YYYY-MM-DD] [--to YYYY-MM-DD] [--running] [--exercise NAME]
```

## Pitfalls

- **Real IDs in tests.** `_generate_id` calls `load_workouts()` which reads the real repo file. Tests that assert on specific IDs (e.g. `sw-001`) must monkeypatch `load_workouts` to return `[]`, otherwise they see IDs from the actual `data/workouts.md`.
- **Weight parsing when `@` is present.** When the set DSL contains `@`, the parser must parse BOTH the weight string before `@` and the RPE string after `@`. Parsing only the RPE caused `weight_kg=None` for sets like `5x80kg@8.0`.
- **Float formatting in output.** Float values (`avg_hr_bpm=145.0`) print as `145.0bpm`, not `145bpm`. Assert the actual string, don't assume integer formatting.
- **`sys.exit(1)` in handlers.** Handlers call `sys.exit(1)` on invalid args. Tests catch `pytest.raises(SystemExit)`. The dispatcher (`__init__.py`) should NOT call sys.exit for unknown subcommand — just print usage and return.
- **Unknown flags.** Unknown flags → immediate error + sys.exit(1). Do not silently ignore.
- **Flags requiring values.** Always check `i+1 < len(args)` before reading the value; else print an error naming the flag.
- **Import consistency.** When adding a new handler, both `__init__.py` and the handler module must be updated together — the import and dispatch branch in `__init__.py`, and the handler function in the module. Patching `__init__.py` first without the handler produces `ImportError: cannot import name 'X'`. Add the handler function first, or patch both files together. Prefer `patch` (targeted edits) over `write_file` (full rewrite) for `*_cli.py` modules to avoid dropping existing handlers.
- **LSP diagnostics vs test reality.** LSP can flag "unknown import symbol" errors that do not correspond to actual import failures — LSP may lag behind file writes or miss recently-added symbols. When LSP flags an import as unknown, verify against the actual test run (`uv run pytest tests/`) before assuming the import is genuinely broken. Tests are the source of truth; LSP diagnostics are advisory.
- **Test expectations vs implementation.** When a test fails on a computed value (pace, volume, weight, etc.), compute the expected value BY HAND from the test inputs before assuming the implementation is wrong. Common Janus cases: `best_pace_min_per_km = min(paces)` where pace = duration/distance; `total_volume_kg = sum(weight_kg * reps)`; floats print with `.0` (e.g. `145.0bpm`). If the implementation is correct and the test expectation is wrong, report it — do NOT silently change the implementation to match a mistaken test.

## Verification

After adding or modifying a CLI subcommand:

1. `uv run pytest tests/` — full suite must pass (including new handler tests).
2. Run the command manually against production data for read-only subcommands
   (e.g. `janus workout summary`) to confirm end-to-end wiring.
3. For write subcommands, run against a temporary data directory — do NOT touch
   `data/workouts.md`.
4. `git status --short` — confirm only intended files changed.
5. `git diff --stat` and `git diff <files>` — confirm changes are as intended.

Do NOT commit automatically. Present the diff and the manual smoke test results
to the user for review.

## LSP diagnostics vs test reality

LSP diagnostics (Pyright, Pylance, etc.) can flag "unknown import symbol" errors
that do NOT correspond to actual import failures. LSP may lag behind file writes or
miss recently-added symbols.

Rule: when LSP flags an import as "unknown", verify against the actual test run
(`uv run pytest tests/`) before assuming the import is genuinely broken. Tests are
the source of truth; LSP diagnostics are advisory.

If an import genuinely fails, the stack trace shows the missing symbol name and the
module it was imported from — use that to find the mismatch.

## Import consistency between __init__.py and handler modules

When adding a new subcommand, both sides must be updated together:

1. `src/janus/__init__.py` — import the handler AND add the dispatch branch.
2. `src/janus/<module>_cli.py` — define the handler function.

Pitfall: patching `__init__.py` to import and dispatch a handler that does not yet
exist in the `*_cli.py` module produces `ImportError: cannot import name 'X' from 'janus.<module>'`.
The fix is to add the handler function to the module BEFORE (or simultaneously with)
wiring the dispatch.

When modifying both files, prefer `patch` (targeted edits) over `write_file` (full
rewrite) for the `*_cli.py` module, so you don't accidentally drop existing handlers.
If you must rewrite the whole file, read it first in full and re-include all existing
functions.

## Test expectations vs implementation — verify before assuming failure

When a test fails, compute the expected value BY HAND from the inputs before assuming
the implementation is wrong. Common cases in Janus:

- `best_pace_min_per_km` is `min(paces)` where pace = duration/distance per run.
  If two runs have the same pace, best equals that pace (not a different value).
- `total_volume_kg` is `sum(weight_kg * reps)` — multiply first, then sum. Not
  `(sum of weights) * (sum of reps)`.
- Float formatting: `145.0bpm` prints as `145.0bpm`, not `145bpm`. Assert the
  actual string from `capsys.readouterr().out`, not what you assumed.

If the implementation produces the correct value but the test expects a different
one, the test expectation is wrong — report it, do NOT silently "fix" the
implementation to match a mistaken test.

## Safe manual smoke test on production data

You can run CLI commands against the canonical `data/workouts.md` as a manual smoke
test, provided:

- The command is READ-ONLY (e.g. `janus workout show`, `janus workout summary`).
- You explicitly do NOT run commands that write (e.g. `janus workout add`).

If a command writes (adds/updates/deletes), isolate it using a temporary data
directory (patch `PROJECT_ROOT` / `_workouts_path()` in the smoke test script) rather
than touching production data.

## References

- `references/args-dispatch.md`
- `references/test-pattern.md`
- `references/id-generation.md`
- `references/parsing-helpers.md`
- `references/cross-cutting-fields.md`
- `references/failures.md`
