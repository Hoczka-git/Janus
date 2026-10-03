# Known failures and their fixes

Session-specific failure records for the Janus CLI patterns skill.
Each entry records what broke, why, and the fix — so a future session does not
rediscover the same pitfall by trial and error.

## ID generation reads real data in tests

- **Symptom:** CLI handler test asserts on `sw-001` but gets `sw-002` (or higher).
- **Root cause:** `_generate_id` calls `load_workouts()` which reads the real
  `data/workouts.md`. Tests that mock `save_workout` but not `load_workouts` still
  see real IDs from the repo.
- **Fix:** Monkeypatch `load_workouts` to return `[]` in each test that asserts a
  specific ID. See `references/id-generation.md`.

## Weight dropped when `@` is present in set DSL

- **Symptom:** `5x80kg@8.0` parses with `weight_kg=None`.
- **Root cause:** Parser split on `@`, parsed only the RPE, ignored the weight part.
- **Fix:** Parse both sides of `@` — weight before, RPE after. See `references/parsing-helpers.md`.

## Float values print with `.0` in CLI output

- **Symptom:** Test asserts `"145bpm"` but output is `"145.0bpm"`.
- **Root cause:** Python floats preserve the fractional part when printed; `145.0`
  renders as `145.0`, not `145`.
- **Fix:** Assert the actual output string, not the assumed integer formatting.
  See `test-pattern.md` show handler tests.

## Unknown subcommand should not sys.exit

- **Symptom:** Dispatcher calls `sys.exit(1)` on unknown subcommand, crashing the
  process instead of printing usage.
- **Root cause:** Confusion between handler responsibility (sys.exit on invalid args)
  and dispatcher responsibility (print usage and return).
- **Fix:** Dispatcher returns after printing usage; handlers may sys.exit.
  See `references/args-dispatch.md`.

## ImportError after patching __init__.py dispatch

- **Symptom:** After adding a new subcommand dispatch in `__init__.py`, tests fail
  with `ImportError: cannot import name 'X' from 'janus.<module>'`.
- **Root cause:** `__init__.py` imports and dispatches a handler that does not yet
  exist in the `*_cli.py` module. The handler function was not added to the module
  before (or at the same time as) wiring the dispatch.
- **Fix:** Add the handler function to the `*_cli.py` module first. If modifying both
  files, read the existing `*_cli.py` in full before rewriting, or use targeted
  `patch` edits to avoid dropping existing handlers.
- **See:** SKILL.md section "Import consistency between __init__.py and handler modules".

## Test expectations mismatch implementation

- **Symptom:** Tests fail with assertion errors on computed values (e.g. pace, volume,
  weight) despite the implementation being correct.
- **Root cause:** Test expectations were written with incorrect assumptions about the
  calculation (e.g. assuming `best_pace` picks a different value than `min(paces)`,
  or computing volume as `(sum weights) * (sum reps)` instead of `sum(weight * reps)`).
- **Fix:** Compute the expected value by hand from the test inputs before assuming the
  implementation is wrong. If the implementation is correct and the test expectation
  is wrong, report it — do NOT silently change the implementation to match a mistaken
  test.
- **See:** SKILL.md section "Test expectations vs implementation — verify before assuming failure".

## Compound `--sets` DSL rejected by parser

- **Symptom:** `janus workout add --sets "3x8x12kg@8"` exits with `Error: invalid weight: 8x12`.
- **Root cause:** The parser splits each comma-separated set on the FIRST `x` only, producing
  `(reps, rest)` = `(3, "8x12kg@8")`. It then treats `rest` as `weight_str + optional @rpe` — so
  `"8x12kg@8"` is parsed as weight `"8x12kg"` (which is not a valid float) → ValueError.
- **What the parser accepts (per set):** `<reps>x[<weight>kg][@<rpe>]` — single weight per set,
  optional `@rpe`. Multiple sets are comma-separated: `"3x8x12kg@8,3x8x47.5kg@9"`.
- **Correct encoding for each set:** `REPSxWEIGHTkg@RPE`. There is no syntax for "8 reps at two
  different weights in one set" — express the combined weight or split into separate sets.
  Example: `3x8x12kg@8` (3 sets of 8 reps at 12 kg, RPE 8); `3x16x32kg@8` (3 sets of 16 reps
  at a combined 32 kg, RPE 8).
- **Wrong encoding (causes error):** `3x8x12kg@8` where the intent was "3 series of 8 reps at
  12 kg each, RPE 8" — but the parser reads the second `x` as part of the weight string.
- **Fix:** Never pass a compound DSL string where a set contains more than one `x`. Use the
  canonical `REPSxWEIGHTkg@RPE` per comma-separated item. If you are transcribing a training
  log that lists multiple weights per exercise (e.g. "16 + 16 kg"), either sum them into one
  weight per set (`32kg`) or split into separate CLI calls.
- **See also:** `references/workouts-strength-cli.md`.
