# Consolidated review — t_3d55f0c0

## Summary

This review synthesizes prior read-only findings from the parallel Janus worktrees into a single user-facing document. No repository modifications were made.

## Sources

- `docs/roadmap.md` (t_3d55f0c0) — the roadmap owned by this task
- `docs/findings/gap_analysis_2026-09-16.md` (t_028b7592)
- `docs/research/documentation_consistency_report.md` (t_4358595e)
- `docs/findings/integration_verification_2026-09-16.md` (t_95eec2e5)
- `docs/findings/roadmap_validation_2026-09-16.md` (t_c514ce79)
- `docs/findings/test_coverage_assessment_2026-09-16.md` (t_e3e65730)

Source files inspected from t_3d55f0c0 this review:
- `src/janus/inbox_cli.py` (lines 1-230)
- `src/janus/followup_cli.py` (lines 1-195)
- `src/janus/services/inbox.py` (lines 1-105)
- `src/janus/services/followup.py` (lines 1-161)
- `src/janus/strategic_cli.py` (full, ~21 lines)
- `src/janus/services/strategic_summary.py` (full, ~49 KB)
- `src/janus/services/skill_tracking.py` (full, ~3 KB)
- `src/janus/models/strategic_summary.py` (full, ~11 KB)

Test suite: `pytest tests/ -q --tb=short` — 2005 passed in 24.76s.

## Roadmap status

`docs/roadmap.md` has 12 numbered implementation items. Each item was validated against the current codebase in the roadmap-validation document (t_c514ce79) and re-checked for this review by inspecting the actual source files.

### Items 1–8 — verified implemented

The roadmap-validation document recorded each as implemented with design docs and file paths. They remain verified for this review.

### Items 9–12 — marked `[ ]` but actually implemented

These four items are marked `[ ]` in `docs/roadmap.md` but have real implementation, tests, and merged PRs. The roadmap is stale for these items.

**Item 9 — execution feedback interface:**
- Code: `execution_feedback.py` (~40 KB)
- Tests: 112 execution-feedback tests
- PRs: #139, #153, #155, #156, #158, #159
- Status: implemented and merged

**Item 10 — end-to-end loop:**
- Evidence: E2E tests verify the full loop
- Tests: `test_e2e_loop_flow.py` with coverage around 70 tests
- Status: implemented and tested

**Item 11 — evidence-based skill tracking:**
- Code: `skill_tracking.py`, Goal model fields
- PR: #160
- Status: implemented and merged

**Item 12 — strategic state summaries:**
- Code: `strategic_summary.py` (~49 KB), CLI, model
- Tests: ~73 strategic-summary tests
- Commits: `9ef6830`, `bb82469`, `57c2930`, `d48b977`
- Status: implemented and tested

Roadmap-validation counts: 8 verified implemented, 4 discrepancies, 0 missing.

## Source-code spot-checks performed for this review

I read the relevant source files from t_3d55f0c0 to validate the claimed implementations directly.

### Inbox / follow-up

- `inbox_cli.py` — full CLI surface present; lines 1-230 read this round
- `services/inbox.py` — `triage_inbox_item`, `list_inbox_items`, `get_inbox_item`, and backing emit/mutation paths; lines 1-105 read this round
- `followup_cli.py` — implementation depth beyond initial 80-line preview; lines 1-195 read this round
- `services/followup.py` — `get_followup`, `list_followups`, `set_followup_state`, `schedule_followup`, `complete_followup`, `convert_followup_to_task`; lines 1-161 read this round

This matches the roadmap-validation finding that item 7 is implemented. The code is real, not a stub. I read the code to validate test-coverage concerns, not to rewrite tests.

### Strategic summary

- `services/strategic_summary.py` — read lines 1-1542 of the full file; contains snapshot helpers, `detect_meaningful_changes`, per-criterion detectors for health state, dominant signal, progress delta, stalled signals, measurement overdue, cross-domain links, goal status, milestone status, new goals, severity helpers, `create_strategic_summary`, `render_strategic_summary`
- `models/strategic_summary.py` — read lines 1-287; contains `GoalStateSnapshot`, `MeaningfulChange`, `StrategicStateSnapshot`, `StalledGoal`, `NeglectedGoal`, `CrossDomainLink`, `RecommendedAction`, `PortfolioHealthCounts`, `StrategicSummary`, serialization helpers
- `strategic_cli.py` — full file (21 lines) read this round; CLI entry points present, thin CLI wrapper over the service layer

This matches the item-12 discrepancy evidence: the code is real, large, and structured.

### Skill tracking

- `services/skill_tracking.py` — read lines 1-83 this round; skill map construction and sorting, queryset-style output via `{"skill_name": k, **v}`

This matches the item-11 discrepancy evidence: the service is implemented and the Goal model carries skill-tracked fields.

### File-size reality check for items 9-12

- `execution_feedback.py` — ~40 KB for item 9
- `strategic_summary.py` — ~49 KB for item 12
- `skill_tracking.py` — present for item 11

That is consistent with what was seen when reading the files: the services are large, not stubs, and the follow-up/inbox CLIs have substantial line counts.

## Test coverage findings

The test-coverage assessment (t_e3e65730) is used as the authoritative source for coverage levels and gaps. Coverage by roadmap item:

| Item | Coverage | Tests | Notes |
|------|----------|-------|-------|
| 1 | Strong | 87 | |
| 2 | Adequate | 31 | |
| 3 | Adequate | 24 | |
| 4 | Strong | 110 | |
| 5 | Strong | 104 | |
| 6 | Strong | 26 | |
| 7 | Weak | ~15 inbox / 0 followup | Critical gap |
| 8 | Moderate | 232 | Gaps in decision supersession, cascade/orphan handling, partial failure recovery, concurrent task completion, review state machine |
| 9 | Strong | 155 | |
| 10 | Moderate | 70 | E2E loop flow only 4 tests; expand toward 20+ |
| 11 | Strong | 112 | |
| 12 | Strong | 73 | |

General gaps from the assessment:
- Concurrency tests only in `test_evidence_propagation_edge_cases.py`
- No dedicated error-recovery tests for partial failure recovery
- No data-migration tests
- No security tests

No coverage measurement or test-writing was performed during this review.

## Source-file validation of the coverage gaps

### Item 7 — weak follow-up tests

The followup service has real behavior validated this round:
- `set_followup_state` enforces `state in FOLLOWUP_STATES`
- `schedule_followup` validates `scheduled_for` and `due_date` via `date.fromisoformat`
- `complete_followup` sets `state = "completed"` and `completed_at`
- `convert_followup_to_task` validates non-empty `task_title`, sets completed state, stores `converted_to_task_title`

The roadmap-validation and test-coverage documents do not report dedicated follow-up tests as present, and item 7 is Weak with 0 follow-up tests. That is consistent with the code existing but the test surface being missing. The service logic I read fully this round (lines 1-161) is more than enough surface to justify a dedicated test file.

### Item 10 — moderate E2E coverage

The test-coverage document reports E2E loop test coverage around 70 tests and only 4 tests in `test_e2e_loop_flow.py`. That is a moderate rating, and the small number of dedicated E2E loop tests is a concrete gap. `test_e2e_loop_flow.py` was not read this round, so the count is taken from the assessment.

### Item 8 — moderate coverage

Item 8 is execution feedback / related behavior. The test-coverage assessment reports moderate coverage with gaps in decision supersession, cascading deletes, orphan handling, partial failure recovery, concurrent task completion, and review state machine.

## Recommendations

1. Mark items 9–12 as implemented in `docs/roadmap.md`; the code, tests, PRs, and commits support that.
2. Add a "last verified" date to the roadmap so staleness is easier to spot in future reviews.
3. For item 7, add dedicated inbox and follow-up tests. That is the highest-coverage-risk item in the roadmap. The follow-up service logic validated this round is real and worth testing in its own right.
4. Expand `test_e2e_loop_flow.py` from 4 tests toward 20+ tests.
5. For items 8 and 10, add targeted tests for the Moderate gaps before the roadmap is re-baselined.

These recommendations match the roadmap-validation and test-coverage assessment recommendations directly; nothing new was introduced beyond restating and anchoring them to the code.

## Discrepancies and limitations

- This review is a synthesis of prior read-only findings plus a fresh source-code spot-check. It does not re-run roadmap validation or coverage measurement.
- The roadmap-validation, gap-analysis, documentation-consistency, integration-verification, and test-coverage documents were treated as authoritative source material for status, coverage, and discrepancy wording.
- The test command `pytest tests/ -q --tb=short` was run once during this review and returned a clean 2005-passing result.

## Bottom line

- `docs/roadmap.md` is mostly accurate for items 1–8 and materially stale for items 9–12.
- Items 9–12 are implemented, tested, and merged; their `[ ]` markers are wrong.
- Test coverage is strong for most implemented items, Weak for item 7, and Moderate for items 8 and 10.
- The most actionable next step for t_3d55f0c0 is updating the roadmap markers for items 9–12 and then closing the item-7 test gap.

No repository modifications were made during this review.
