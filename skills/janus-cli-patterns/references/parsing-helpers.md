# DSL parsing helpers — edge cases and patterns

## Purpose

When a CLI flag accepts a compact DSL (e.g. `--sets "5x80kg@8,5x80kg@8.5"`), extract the parsing into a pure helper function separate from the handler. The helper takes a string and returns parsed domain objects, or raises `ValueError` on invalid input. The handler catches `ValueError` and exits with `sys.exit(1)`.

## Pattern — `--sets` parser

```python
def _parse_sets(sets_str: str) -> list[Set]:
    """Parse '5x80kg@8.0,5x80kg@8.5,5x80kg' → list[Set].

    Format per set: <reps>x[<weight>kg][@<rpe>]
    - reps: integer, required
    - weight: float with optional 'kg' suffix (e.g. '80kg' or '80'), optional
    - rpe: float after '@' (e.g. '@8.0'), optional
    - Bodyweight set: '10x' (no weight, no RPE)
    """
    sets = []
    for part in sets_str.split(","):
        part = part.strip()
        if not part:
            continue
        if "x" not in part:
            raise ValueError(f"invalid set format: {part}")
        reps_str, rest = part.split("x", 1)
        try:
            reps = int(reps_str)
        except ValueError:
            raise ValueError(f"invalid reps: {reps_str}")
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
                        raise ValueError(f"invalid weight: {weight_str}")
                # Parse RPE from rpe_str (e.g. "8.0")
                try:
                    rpe = float(rpe_str)
                except ValueError:
                    raise ValueError(f"invalid RPE: {rpe_str}")
            else:
                weight_str = rest.strip()
                if weight_str:
                    if weight_str.endswith("kg"):
                        weight_str = weight_str[:-2]
                    try:
                        weight_kg = float(weight_str)
                    except ValueError:
                        raise ValueError(f"invalid weight: {weight_str}")
        sets.append(Set(reps=reps, weight_kg=weight_kg, rpe=rpe))
    return sets
```

## Edge cases

| Input | Expected | Notes |
|-------|----------|-------|
| `5x80kg@8.0` | `Set(reps=5, weight_kg=80.0, rpe=8.0)` | Full set with weight and RPE |
| `5x80kg@8.5` | `Set(reps=5, weight_kg=80.0, rpe=8.5)` | Multiple RPE values per exercise |
| `5x80kg` | `Set(reps=5, weight_kg=80.0, rpe=None)` | Weight without RPE |
| `10x` | `Set(reps=10, weight_kg=None, rpe=None)` | Bodyweight set (no weight) |
| `5x` | `Set(reps=5, weight_kg=None, rpe=None)` | Bodyweight with explicit 'x' |
| `5x0kg` | `Set(reps=5, weight_kg=0.0, rpe=None)` | Zero added weight |
| `5x80kg@notanumber` | `ValueError("invalid RPE: notanumber")` | RPE must be parseable float |
| `5xabc` | `ValueError("invalid weight: abc")` | Weight must be parseable float |
| `abcx80kg` | `ValueError("invalid reps: abc")` | Reps must be parseable int |
| `invalid` | `ValueError("invalid set format: invalid")` | No 'x' separator |
| `""` (empty string) | `[]` | Empty string returns empty list |
| `"5x80kg@8.0,5x80kg@8.5,5x80kg"` | 3 sets parsed | Comma-separated lists |

## Key lessons

### Parse BOTH sides of `@`

When `@` is present in the set string, the format is `<reps>x<weight>kg@<rpe>`. The parser must parse BOTH the weight part (before `@`) AND the RPE part (after `@`).

A common mistake is to split on `@` and parse only the RPE, ignoring the weight. This results in `weight_kg=None` for sets like `5x80kg@8.0` — the weight `80kg` is silently dropped.

**Correct:** split on `@`, parse `weight_str` for weight, parse `rpe_str` for RPE.

### Handle optional weight (bodyweight sets)

A set like `10x` has no weight and no RPE. The parser should handle this case:
- `rest` is empty after splitting on `x`.
- `weight_kg` stays `None`.
- `rpe` stays `None`.

This is different from `10x0kg` which explicitly has zero added weight (`weight_kg=0.0`).

### Strip whitespace

The input may contain spaces (e.g. `"5x80kg@8.0, 5x80kg@8.5"`). Strip each part after splitting on commas.

### Validate early, raise ValueError

The helper should raise `ValueError` with a clear message for invalid input. The handler catches `ValueError` and prints the message to stderr before calling `sys.exit(1)`.

Do not call `sys.exit` inside the parser — the parser is a pure function that should be testable independently of the CLI handler.

## Integration with handler

The handler calls the parser and catches `ValueError`:

```python
try:
    sets = _parse_sets(sets_str)
except ValueError as e:
    print(f"Error: {e}", file=sys.stderr)
    sys.exit(1)
```

This keeps the parser testable without mocking `sys.exit`. Tests for the parser assert on `ValueError` directly:

```python
def test_parse_invalid_format_raises(self):
    with pytest.raises(ValueError, match="invalid set format"):
        _parse_sets("invalid")
```

## Testing the parser

Parser tests are pure unit tests — no mocks, no capsys, no CLI handler. Test each edge case as a separate assert or separate test function.

```python
def test_parse_simple_sets(self):
    sets = _parse_sets("5x80kg@8.0,5x80kg@8.5,5x80kg")
    assert len(sets) == 3
    assert sets[0].reps == 5
    assert sets[0].weight_kg == 80.0
    assert sets[0].rpe == 8.0
    assert sets[2].weight_kg == 80.0
    assert sets[2].rpe is None

def test_parse_bodyweight_set(self):
    sets = _parse_sets("10x")
    assert len(sets) == 1
    assert sets[0].reps == 10
    assert sets[0].weight_kg is None

def test_parse_invalid_format_raises(self):
    with pytest.raises(ValueError, match="invalid set format"):
        _parse_sets("invalid")
```

## Errors to avoid

1. **Dropping the weight when `@` is present.** The parser must handle both sides of `@`.
2. **Calling `sys.exit` in the parser.** The parser should raise `ValueError`, not exit.
3. **Not handling bodyweight sets.** `10x` must parse as a valid bodyweight set, not as an error.
4. **Not stripping whitespace.** Input like `"5x80kg@8.0, 5x80kg"` has a space after the comma — strip each part.
5. **Not validating RPE as float.** `5x80kg@abc` should raise, not silently parse as None.
6. **Not validating weight as float.** `5xabc` should raise, not silently parse as None.