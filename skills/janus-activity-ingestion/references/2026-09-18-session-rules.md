# Activity Ingestion — Session Reference (2026-09-18)

Source: session with Hoczka (Polish/English, concise responses, mechanical verification required before declaring ingestion complete).

## Key rules confirmed this session

- **Always populate `evidence["date"]` (ISO date) or `record.date`** when emitting `WORKOUT_ADDED`. Without it, dedup key collapses to `"::strength"` / `"::running"`, causing spurious duplicates.
- **Always supply `workout_id`** if the workout has a known ID (e.g., `sw-20260918`, `rw-20260917`). If absent, gateway generates `w-<8-hex>` UUID.
- **One `StrengthWorkout` = one `ActivityRecord(type=WORKOUT_ADDED, workout_type="strength")`** with `evidence["exercises"]` as a list of dicts. Do NOT emit one `ActivityRecord` per exercise.
- **Each set is a separate `sets[]` element.** Never encode series count as `reps`.
- **Reguła serii 3 = seria 2, gdy brak opisu.** Potwierdzona dla PLAN 14. Jeśli seria 3 ma własne dane (np. 6 powt., 15 kg, RPE 9) — użyć ich; w przeciwnym razie skopiować serię 2.
- **BW (bodyweight) = `weight_kg` jako `None`, nie sztuczne 0 kg.** 16+16 kg = 16 kg w każdej ręce (32 kg łącznie, zapisane jako `weight_kg: 16.0` z notatką o łącznie 32 kg w `Exercise.notes`).
- **Nie zgadywać brakujących RPE / VO2max / stref tętna.** Jeśli brak — `rpe: None`.
- **Verification after ingestion:** 1) exactly one `sw-...` / `rw-...` record with target date; 2) exactly 9 exercises (for PLAN 14 C); 3) each `sets[]` has correct `reps`, `weight_kg`, `rpe`; 4) prior records (`sw-...`, `rw-...`) unchanged.
- **Idempotency before ingestion:** compute `compute_dedup_key(record)`; if the key exists in `data/workouts.md`, skip.
- **`data/workouts.md` is NOT tracked by git.** Verification must read file content (`load_workouts()` or `cat -n`), not `git diff`.
- **Always go through `ingest_activities()`; never direct `Path.write_text()` on `data/`.**
- **Style correction embedded:** do not invent non-existent Polish idioms. If no Polish equivalent, use full sentence or English (e.g. do not force "bitwa z mięsem" — write clearly instead).
