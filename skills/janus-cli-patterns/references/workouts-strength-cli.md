# `--sets` DSL for strength workouts — encoding rules and failure modes

## Parser contract (what it accepts)

Per set, the parser splits on the FIRST `x` only and reads `<reps>x<rest>`.

`<rest>` is then parsed as:
- `<weight>kg[@<rpe>]` if it contains `@`
- `<weight>kg` if it contains no `@`
- empty → bodyweight set (no weight, no RPE)

So the *effective grammar per set* is:

```
<reps>x[<weight>kg][@<rpe>]
```

Multiple sets are comma-separated, whitespace-stripped:

```
"3x8x12kg@8,3x8x47.5kg@9,3x16x32kg@8"
```

## Correct encodings

| Scenario | Correct `--sets` value | Note |
|----------|-------------------------|------|
| 3 sets × 8 reps, 12 kg, RPE 8 | `3x8x12kg@8` | single weight per set |
| 3 sets × 8 reps, 47.5 kg, RPE 9 | `3x8x47.5kg@9` | decimal weight OK |
| 3 sets × 16 reps, combined 32 kg, RPE 8 | `3x16x32kg@8` | two 16 kg = 32 kg combined |
| Bodyweight, 10 reps, no RPE | `10x` | no weight, no RPE |
| 3 sets × 5 reps, 80 kg, RPE 8 and 8.5 | `3x5x80kg@8,3x5x80kg@8.5` | two RPE values → two items |
| Mixed: 5×80 kg@8, 5×80 kg@8.5, 5×80 kg (no RPE) | `5x80kg@8,5x80kg@8.5,5x80kg` | |

## Wrong encodings that cause parse errors

| Input | Error | Why |
|-------|-------|-----|
| `3x8x12kg@8` (when intent is "3 series of 8 reps at 12 kg") | `Error: invalid weight: 8x12kg` | second `x` is read as part of weight string |
| `3x8+8x12kg@8` | `Error: invalid weight: 8+8x12kg` | no `+` syntax |
| `3x(8x12kg)@8` | `Error: invalid set format` | parentheses not supported |
| `3x8x12+8x16kg@8` | `Error: invalid weight: ...` | no `+` weight syntax |

The parser treats the *first* `x` as the reps/weight separator. Everything after the first `x` is the weight component. There is no syntax for multiple weight values inside one set.

## Encoding strategies for real training logs

Real training logs often write sets with multiple weights or ranges. Choose one of these translations:

### 1. Sum into a single combined weight

- "16 + 16 kg" → one set at 32 kg → `3x16x32kg@RPE`
- "16 kg each hand" → 32 kg total → `3x16x32kg@RPE`

### 2. Split into separate CLI calls

If the log distinguishes two different exercises or two different set structures, emit two CLI calls:

- First call: exercise A, sets `3x8x12kg@8`
- Second call: exercise B, sets `3x8x16kg@9`

### 3. Drop the secondary weight

If the second weight is a warm-up set or a separate set that can be omitted without losing the main data, record only the primary working sets.

## What NOT to do

- **Do not** invent a syntax the parser does not recognize (parentheses, `+`, multiple `x` inside one set).
- **Do not** pass a string with two `x` separators expecting the parser to understand "sets × reps × weight".
- **Do not** assume the parser will sum weights or split on a secondary delimiter.

## Verification

After constructing the `--sets` string, run a single add with a temporary exercise name (or dry-run the parser if a test exists) to confirm the string parses before spending a real workout ID.

```bash
cd /home/dan11hermes/workspaces/janus && \
uv run janus workout add --type strength \
  --exercise "TEST_PARSE_ME" \
  --sets "3x8x12kg@8,3x8x47.5kg@9" \
  --date 2026-09-11 \
  --notes "DSL parse probe" 2>&1
```

If it exits 0 and prints `Added workout: ...`, the string is valid. Remove the probe workout afterward.
