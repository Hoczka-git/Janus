# Review Findings: Canonical Review Topology Implementation

**Task:** t_0ab53c2f — Review canonical review topology implementation
**Date:** 2026-08-31
**Reviewer:** reviewer (this run, run_id=104)

## Decision Doc
`/home/dan11hermes/workspaces/janus/.worktrees/t_0ccf3c75/docs/decisions/003-canonical-review-topology.md`
Model A (Native Review Lane / Task Lifecycle Ownership Transfer) adopted.

## Independent Verification

All subsystems inspected directly against the decision doc's §Subsystem Implications.

### What matches (no defects found)

| Subsystem | Location | Verdict |
|---|---|---|
| prompt_builder.py — KANBAN_GUIDANCE | agent/prompt_builder.py:322-328 | Model B language removed. Worker instructed to use kanban_request_review() |
| kanban_decompose.py — review child rejection | hermes_cli/kanban_decompose.py:318-527 | _looks_like_review_child() flags dedicated review children. Re-prompt once (limit=2), then hard-reject. Permits review-mentioning children that reference kanban_request_review |
| Dispatcher — review lane | hermes_cli/kanban_db.py:10054-10410 | review_rows enumerated before ready loop, one-slot reservation, respawn guard per lane, sdlc-review skill force-loaded |
| DB — review transitions | hermes_cli/kanban_db.py:6601 (request_review), 6663 (request_changes), 4750 (claim_review_task), 6962 (reopen_review_task) | All present. changes_requested persists {reason, implementer, reviewer, status}. _landing_status_after_parents() re-gates |
| Watchers — review events | gateway/kanban_watchers.py:636-670 | review_requested wakes origin with handoff summary. changes_requested wakes with reason + reviewer/implementer provenance |
| CLI | hermes_cli/kanban.py:696 (request-review), 730 (reopen-review) | Both subcommands exist. Goal-mode judge gate applied to request-review (2378-2393) |
| sdlc-review skill | skills/devops/sdlc-review/SKILL.md:29 | Explicitly rejects Model B. Verdict table: approve→complete, request changes→request_changes, escalate→block. Round tracking from changes_requested count |

### Test results (independent run, not trusting parent summaries)

- review lifecycle + decompose + surface tests: 57 passed
- full hermes_cli suite: 308 passed, 1 pre-existing failure (test_approval_transport.py::test_cli_selected_transport_replaces_builtin_prompt — unrelated, not a regression)

## Findings (documented)

### Finding 1: CLI help table naming inconsistency (minor)
File: `hermes_cli/kanban.py:3453`
The `complete` subcommand's help table uses `request-review <id>` in its prose entry, but the actual argparse subparser at line 730 is named `reopen-review`. Both subcommands exist and work, but the help table entry doesn't match the canonical CLI naming. A reader scanning the help text sees `request-review` where the actual command is `reopen-review`.

**Severity:** cosmetic — both commands exist, no functional impact.

### Finding 2: Decision doc §7.7 CLI docs polish item incomplete
The decision doc §7.7 says: "The CLI docs/examples should explicitly state that this is the canonical review workflow, not a secondary option."
Current help text at line 3453 says `request-review <id>` "Enter first-class review" — it says "first-class" but does NOT say "canonical" or "primary workflow". The functional implementation is complete and correct; this is a documentation polish item from the decision doc that was not fully addressed.

**Severity:** low — the workflow works, wording could be stronger.

### Finding 3: Re-review loop limits — open design question (not a defect)
Decision doc §Remaining Uncertainty #3: no dedicated review-loop counter. consecutive_failures is preserved across review cycles and only reset on complete_task. The dispatcher's spawn-failure counter does not catch a task bouncing implementer↔reviewer N times. This is by design and carries forward as an open question, not a defect.

**Severity:** n/a — documented open question, not a regression.

## Conclusion

Implementation matches decision doc 003. Model A (Native Review Lane) is fully implemented and consistent across DB, tools, dispatcher, watchers, CLI, prompt guidance, auto-decomposer, and skill system. No blockers. Two minor documentation items outstanding (CLI help wording, reopen-review naming in help table). One open design question (re-review loop limits) tracked in decision doc §Remaining Uncertainty.
