# Phase D Agency-Aware Planning — Status Marker

**Task:** t_f1e900e7  
**Date:** 2026-09-30  
**Status:** Implemented and merged on `master` via child PRs #274, #280, #283.

## Verification Summary

- `execution_mode` enum (USER/JANUS/COLLABORATIVE) — `src/janus/models/execution_mode.py`
- `support_mode` enum (EXPLAIN/COACH/SCAFFOLD/REVIEW/EXECUTE) — `src/janus/models/support_mode.py`
- `TaskAgency` dataclass — `src/janus/models/task_agency.py`
- `classify_next_action()` + `classify_task()` — `src/janus/services/agency_planning.py`
- `EXECUTION_MODE_ORDER` + `SUPPORT_MODE_ORDER` tuples used in selection functions
- `import re` at module scope
- `classify_task()` wired into `derive_next_action()` via `_agency_for_task()`
- 62 agency tests passing on master
- Spec conflict decision doc: `docs/triage/t_f1e900e7-spec-conflict-decision.md` (design doc takes precedence)

## Caveat

`docs/triage_architectural_roadmap_next_phase.md` §5.1/P3-2 flagged for update to reflect Phase D is implemented.
