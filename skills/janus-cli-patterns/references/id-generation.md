# ID generation helper

## Pattern

When the domain model uses sequential IDs (`sw-001`, `rw-001`, ...), write a standalone helper that reads existing entities and returns the next available ID:

```python
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
```

## How it works

- Determines the prefix from the entity type (`sw` for strength, `rw` for running).
- Reads all existing entities from persistence (`load_workouts()`).
- Finds the maximum numeric suffix among entities of the same type.
- Returns `prefix-N` where N = max + 1, zero-padded to 3 digits.

## Why this approach

- Sequential, deterministic IDs that are human-readable (no UUIDs).
- Respects existing IDs in the data file — does not reset on each run.
- Coexists with the rest of the persistence layer (no separate ID file).

## Pitfall — real I/O in tests

`_generate_id` calls `load_workouts()` which reads the real `data/workouts.md`. In CLI handler TESTS that mock `save_workout` but do NOT mock `load_workouts`, the ID helper still reads the actual repo file and returns IDs based on the real state.

Example failure (from first CLI implementation):

- Test asserted `"Added workout: sw-001"` but got `"Added workout: sw-002"` because the repo already had `sw-001` in `data/workouts.md`.
- Same for running: expected `rw-001`, got `rw-003`.

Fix — monkeypatch `load_workouts` to return `[]` in each test that asserts a specific ID:

```python
def test_add_strength_minimal(self, capsys, monkeypatch):
    monkeypatch.setattr("janus.workout_cli.load_workouts", lambda: [])
    with patch("janus.workout_cli.save_workout") as mock_save:
        mock_save.return_value = None
        handle_workout_add([...])
    out = capsys.readouterr().out
    assert "Added workout: sw-001" in out
```

## Independent functions vs handler integration

The ID helper is a pure function with a side channel (calling `load_workouts`). This is intentional — it keeps the ID logic in one place and makes it testable via monkeypatch. If the ID generation were moved into the handler, it would be harder to test in isolation and would duplicate the logic across handlers.

## Alternative approaches considered and rejected

- **UUIDs:** rejected — not human-readable, harder to reference in conversation.
- **Timestamp-based IDs:** rejected — not sequential, collisions possible.
- **Separate counter file:** rejected — adds another file to maintain, no benefit over reading existing entities.
- **Passing max_id as parameter:** rejected — would require the caller to know the current max, duplicating the lookup logic.

The chosen approach (read existing, compute max) is the simplest that meets the requirements.