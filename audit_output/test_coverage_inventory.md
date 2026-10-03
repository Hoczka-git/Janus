# Janus Test Suite — Inventory of Actual Coverage

Generated: 2026-10-03
Total test files: 125 (1113 test classes/functions; 1068 non-regression + 45 regression)
Source analyzed: `tests/` directory, all `*.py` files.

---

## 1. Feature Coverage

| Feature Area | Test Files | Approx. Test Classes/Functions | Status |
|---|---|---|---|
| Execution Engine (status, policy, executor, service, proposals) | test_execution_engine.py | ~25 classes, ~60+ functions | Well-covered |
| Execution Feedback / Dispatch Completion | test_execution_feedback.py | ~15 classes, ~30+ functions | Well-covered |
| Evidence Collection, Propagation, Verification Chain | test_evidence_collection.py, test_evidence_propagation.py, test_evidence_propagation_edge_cases.py, test_evidence_verification_chain.py | ~10 classes each | Well-covered |
| Evidence Types | test_evidence_type.py | 1 class | Basic |
| Goal Health (assessment, signals, transitions) | test_goal_health.py, test_goal_health_cli.py, test_goal_health_transitions.py | ~20 classes, ~30+ functions | Well-covered |
| Goal Integrity Audit + Repair | test_goal_integrity_audit.py, test_goal_integrity_repair.py | ~15 classes, ~25+ functions | Well-covered |
| Goal Progress | test_goal_progress.py | ~25 functions | Well-covered |
| Goal Lifecycle (states, skill tracking) | test_goal_skill_tracking.py | ~10 classes | Moderate |
| Personal State (construction, serialization, lifecycle, queries) | test_personal_state.py, test_personal_state_builder.py, test_personal_state_integration.py | ~20 classes, ~40+ functions | Well-covered |
| Agent Lifecycle / Registry / Role | test_agent_lifecycle.py, test_agent_registry.py, test_agent_role.py | 3 classes | Basic |
| Agent Assignment + Serialization | test_agent_assignment.py, test_agent_assignment_serialization.py, test_task_agency_serialization.py | 3 classes | Basic |
| Project Model / Persistence / Service | test_project_model.py, test_project_persistence.py, test_projects_service.py | ~10 classes | Moderate |
| Milestone Model / Persistence / Service | test_milestone_model.py, test_milestone_persistence.py, test_milestones_service.py | ~10 classes | Moderate |
| Recommendation / Recommended Actions | test_recommendations.py, test_recommended_actions.py | ~10 classes | Moderate |
| Decision Record / Decision CLI / Finding-to-Decision | test_decision_record.py, test_decision_cli.py, test_finding_to_decision.py | ~10 classes | Moderate |
| Outcome Verification | test_outcome_verification.py | 7 classes | Moderate |
| Metric Progression / History / Provenance | test_metric_progression.py, test_metric_history.py, test_metric_provenance.py | ~15 classes | Moderate |
| Remediation / No-Progress Detector | test_remediation.py, test_remediation_engine.py, test_no_progress_detector.py | ~12 classes | Moderate |
| Attention (deadline, stagnation, sorting) | test_attention.py, test_attention_extended.py | ~12 classes | Moderate |
| Curation Gate / Knowledge Pipeline (vault resolution, promotion, E2E) | test_curation_gate.py, test_knowledge_pipeline.py | ~20 classes each | Well-covered |
| Knowledge Summary / Research Artifact Models | test_research_models.py, test_research_artifact_models.py | ~10 classes | Moderate |
| Actionability | test_actionability.py | 4 classes | Moderate |
| Activity Ingest (routing, normalization, dedup) | test_activity_ingest.py | ~20 classes, ~40+ functions | Well-covered |
| Planning (boundary, next-action, derive milestones) | test_planning_boundary.py, test_next_action.py, test_next_action_projects.py, test_derive_milestone_tasks.py | ~15 classes | Moderate |
| Agency Planning (mode selection, agency classification, confidence) | test_agency_planning.py, test_phase_d_mode_selection_integration.py | ~15 classes | Moderate |
| Policy Engine / Policy Check / Policy Models | test_policy_engine.py, test_policy_check.py, test_policy_model.py, test_policy_models.py, test_policy_integration.py | ~12 classes | Moderate |
| Approval Workflow / Gate / Contract | test_approval_workflow.py, test_approval_gate.py, test_approval_contract.py, test_approval_integration.py, test_approval_request_handling.py | ~12 classes | Well-covered |
| Proposal Engine (rules, guardrails, targeted, interface) | test_proposal_engine.py, test_proposal_engine_targeted.py, test_proposal_guardrails.py, test_proposal_engine_interface.py | ~15 classes | Well-covered |
| Skill Pipeline (proposal, generation, tests, sandbox, verification, approval, install, trust, stage transitions) | test_skill_pipeline.py | ~12 classes | Well-covered |
| Execution Mode / Support Mode | test_execution_mode.py, test_support_mode.py | 2 classes each | Basic |
| Constraint / Commitment / Preference / Resource | test_constraint.py, test_commitment.py, test_preference.py, test_resource.py | 1-2 classes each | Minimal |
| Telegram / Calendar / Google Calendar | test_telegram.py, test_telegram_weekly.py, test_google_calendar.py, test_calendar_planning.py | ~10 classes | Moderate |
| Git Sync / Integration | test_git_sync.py, test_integration.py | ~10 classes | Moderate |
| Data Integrity (atomic IO, writer guard, conflict detection, regeneration gate, backups) | test_data_integrity.py, test_atomic_io.py | ~10 classes | Moderate |
| Logging / Structured Envelope | test_logging.py | 6 classes | Moderate |
| Daily / Weekly Briefing | test_daily_briefing.py, test_weekly_review.py | 3 classes, ~15 functions | Moderate |
| Weekly Planner Interface | test_weekly_planner_interface.py | 6 classes | Basic |
| Planner Evaluation (scenarios S01-S15, B01-B03, R01-R08) | test_planner_evaluation.py, test_planner_evaluation_harness.py, test_planner_scenarios_1_5.py | ~25 classes | Well-covered (scenario matrix) |
| Rule-Based Planner (CLI, context, format) | test_plan_cli.py | 5 classes | Moderate |
| Markdown Goals / Tasks | test_markdown_goals.py, test_markdown_tasks.py | ~10 classes each | Moderate |
| Goals CLI | test_goals_cli.py | ~16 classes | Well-covered |
| Tasks CLI | test_tasks_cli.py | 3 classes | Basic |
| Workout CLI / Analytics / Strength Skill / Running Skill | test_workout_cli.py, test_workout_analytics.py, test_strength_skill.py, test_running_skill.py | ~10 classes | Moderate |
| Fitness Connector / Workout Model | test_fitness.py, test_connector_protocol.py | ~6 classes | Moderate |
| Kanban Review Topology | test_kanban_review_topology.py | ~10 functions | Moderate |
| Unified Completion Gate / Task Complete / Janus Gates | test_unified_completion_gate.py, test_task_complete.py, test_task_complete_gates.py, test_task_complete_janus_gates.py | ~10 classes | Moderate |
| Structured Remediation Integration | test_structured_remediation_integration.py | 3 classes | Basic |
| Handoff Parsing | test_handoff.py | 1 class | Minimal |
| Inbox Triage Title | test_inbox_triage_title.py | 1 class | Minimal |
| Goal Next / Goal Gates | test_goal_next.py, test_goal_gates.py | 2-3 classes each | Basic |
| Overload | test_overload.py | 7 classes | Moderate |
| Narrative Engine | test_narrative_engine.py | 2 classes | Minimal |
| E2E Loop Flow / Task Loop | test_e2e_loop_flow.py, test_e2e_task_loop.py | ~10 functions/classes | Moderate |
| Swarm Root Lifecycle / Swarm Integration Opt-Out / Swarm Coordination | test_swarm_root_lifecycle.py, test_swarm_integration_opt_out.py, test_regression_swarm_coordination.py | ~12 classes | Moderate |
| Artifact Linking | test_artifact_linking.py | 3 classes | Basic |
| Decision-to-Action | test_decision_to_action.py | 1 function | Minimal |
| Congestion / Meaninful Change Detection | test_meaningful_change_detection.py | 8 classes | Moderate |
| Measurement Collection / Log | test_measurement_collection.py, test_measurement_log.py | ~4 classes | Basic |
| Research CLI / Models | test_research_models.py, test_research_artifact_models.py | Covered above | — |

### Features Lacking Tests
- **Obsidian vault operations** (direct file I/O, vault sync, note linking) — no dedicated test file; only `test_curation_gate.py` and `test_knowledge_pipeline.py` touch vault resolution/promotion indirectly.
- **Knowledge CLI** — tested only indirectly via `TestKnowledgeCliSurface` in curation/knowledge pipeline tests.
- **Plugin system (Janus sync plugin, replenishment plugin)** — tested in `tests/plugins/` but plugin registration/lifecycle is minimal.
- **Config loading / settings schema** — no dedicated test file; some coverage via `TestLoadIngestConfig` in activity_ingest.
- **Hermes agent integration** — only tested via `pytest.importorskip("hermes_cli")` guards; no actual integration tests exist.
- **Task state machine (full lifecycle)** — partially covered by `test_task_state_progress.py` but no comprehensive end-to-end lifecycle test.
- **Inbox processing (full pipeline)** — tested via `test_activity_ingest.py` but not full end-to-end from Telegram receipt to task creation.

---

## 2. Lifecycle Tests

| Category | Files | Coverage |
|---|---|---|
| Startup/initialization | test_execution_engine.py (TestExecutionStatus), test_coordination.py (TestAgentCoordinatorInit) | Minimal — basic status/model construction |
| Shutdown/cleanup | test_atomic_io.py (atomic write safety), test_data_integrity.py (backups) | Indirect — no explicit shutdown test |
| State transitions | test_goal_health_transitions.py, test_personal_state.py, test_curation_gate.py, test_skill_pipeline.py | Moderate — state transition tables and edge cases |
| Task lifecycle (todo → in_progress → done) | test_task_state_progress.py, test_task_complete.py, test_task_complete_gates.py, test_task_complete_janus_gates.py | Good — includes gate enforcement |
| Goal lifecycle | test_goal_health.py, test_goal_health_transitions.py, test_goal_integrity_audit.py | Good — health state transitions, audit |
| Agent lifecycle | test_agent_lifecycle.py | Basic — construction and status |
| Swarm root lifecycle | test_swarm_root_lifecycle.py, test_regression_root_initiation.py | Moderate — swarm root detection, children done, integration skip |
| Review phases | test_regression/test_regression_review_phases.py | Comprehensive — 15 test cases covering review request → approval → rejection → re-request → timeout → multiple rounds |
| Completion gates | test_task_complete_gates.py, test_unified_completion_gate.py, test_regression/test_regression_completion_gates.py | Comprehensive — phase 1/3/4 gates, integration gate, evidence artifacts |
| Failure modes | test_regression/test_regression_failure_modes.py (F1-F10) | Comprehensive — working tree dirty, tests fail, sync conflict, contract verification failure, integration failure, hook error, non-git path, swarm root children not done, multiple gate failures, gate exception |
| Retry policies | test_regression/test_regression_retry_policies.py (T1-T13) | Comprehensive — exponential backoff, max retries, RMW conflicts, timeouts, fallbacks |
| Integration gates | test_regression/test_regression_integration_gates.py | Moderate — 8 gate scenarios |
| Child spawning | test_regression/test_regression_child_spawning.py, test_regression/test_regression_swarm_coordination.py | Moderate |

### Regression Suite (test_regression/)
- 8 test files, ~45 test classes/functions
- Focused on lifecycle: root initiation, child spawning, completion gates, failure modes, integration gates, retry policies, review phases, swarm coordination
- Uses `TestHarness` class with git repo setup, lifecycle state fixtures, gate mock fixtures, failure injection fixtures

---

## 3. Verification Tests

| Subcategory | Files | Coverage |
|---|---|---|
| Verification Phase 1 (symbol checks, git diff) | test_verification_phase1.py | Comprehensive — F01-F03: malformed symbols, forbidden symbols, git diff check |
| Verification Phase 3.5 (file state checks) | test_verification_phase3_5.py | Comprehensive — pass/missing-create-file/unmodified-modify/immutable-modified/unexpected-tracked/untracked/required-symbol-missing/wrong-type/forbidden-present/whitespace/verification-command-failure/multiple-failures |
| Verification Default Checks | test_verification_default_checks.py | Good — working tree clean, git diff conflict markers, tests pass after rebase, run default checks, contract checks |
| Verification OS Replace Gate | test_verification_os_replace_gate.py | Basic — find os.replace calls, check no os.replace on real repo |
| Verification Result Model | test_verification_result.py | Minimal — model construction |
| Evidence Verification Chain | test_evidence_verification_chain.py | Moderate — dispatch completion verification, propagate state updates, Janus sync reporting, end-to-end chain |
| Contract Verification | test_contract_exports.py, test_approval_contract.py | Moderate — protocol conformance, interface boundary, contract evaluation |

---

## 4. Integration Tests (External Systems)

| Integration | Test Files | Coverage |
|---|---|---|
| Google Calendar | test_google_calendar.py | Moderate — event parsing, source assignment, multi-calendar |
| Telegram | test_telegram.py, test_telegram_weekly.py | Moderate — message formatting, config loading, sending, retry, API error |
| GitHub Connector | test_connector_protocol.py | Basic — connector capability, permission, proposal, result, registry, full registry |
| Email Connector | test_connector_protocol.py | Basic — same pattern as GitHub |
| Fitness Connector | test_connector_protocol.py | Basic — same pattern |
| AWS Connector | test_connector_protocol.py | Basic — same pattern |
| Git Sync | test_git_sync.py | Good — target branch detection, staleness, sync success/failure, conflict detection, rebase verification |
| Integration Module | test_integration.py | Moderate — fast-forward merge, controlled merge, conflict, post-merge failure, target not integrated, setup failures, report generation, remote containment, edge cases, push failure |
| Agent Coordination (swarm) | test_coordination.py, test_swarm_root_lifecycle.py, test_swarm_integration_opt_out.py | Moderate — delegate, aggregate, retry, backoff, timeout, failure, swarm root lifecycle |
| Hermes CLI Integration | test_evidence_propagation.py, test_evidence_verification_chain.py, test_kanban_review_topology.py, test_swarm_integration_opt_out.py | Indirect — uses `pytest.importorskip("hermes_cli")`, skips if not available |
| Plugin E2E | tests/plugins/test_e2e_execution_feedback.py | Moderate — end-to-end goal/task/milestone/research/decision flows |
| Plugin Janus Sync | tests/plugins/test_janus_sync_plugin.py | Moderate — goal/task/milestone dispatch, gate block routing, evidence lifecycle, auto-invoke |
| Plugin Replenishment | tests/plugins/test_replenishment_plugin.py | Moderate — title prefix guard, file/json sources, idempotency, error isolation, webhook/swarm sources |

### External Integrations WITHOUT Tests
- **Obsidian vault direct I/O** — only tested indirectly through curation/knowledge pipeline
- **Telegram bot incoming messages** — only outbound formatting/sending tested
- **Google Calendar write operations** — only read/parse tested
- **GitHub API operations** — connector protocol tested, not real API
- **Email IMAP/SMTP** — connector protocol tested, not real integration
- **Fitness device sync** — connector protocol tested

---

## 5. Goal Audit/Repair Tests

| Test File | Coverage |
|---|---|
| test_goal_integrity_audit.py | Comprehensive — healthy goals, goals without tasks, unknown goal refs, invalid metrics, stale activity, multiple issues, determinism, report model, CLI, orphan tasks, invalid related tasks, relationship count mismatch, circular references |
| test_goal_integrity_repair.py | Comprehensive — config, dry-run by default, repair unknown goal ref, invalid related task, orphan, relationship mismatch, circular reference, unsupported codes, idempotency, reversibility, model, CLI |
| test_remediation.py | Moderate — stalled/overdue signals, deadline soon, milestone slipped, goal inactive, no recent activity, watch signals, healthy returns none |
| test_remediation_engine.py | Moderate — remediation action model, output shape, healthy goal, excluded goals, stalled/watch primary actions, structural precedence, secondary actions, dedup, determinism, no history, edge cases, config, strategic summary integration |
| test_structured_remediation_integration.py | Basic — structured remediation field, weekly review, Telegram weekly, CLI weekly |
| test_recommended_actions.py | Moderate — identify neglected goals, create recommended actions, render |

---

## 6. Execution Feedback Tests

| Test File | Coverage |
|---|---|
| test_execution_feedback.py | Comprehensive — evidence package, Janus domain metadata parsing, goal progress update, task completion, milestone status, dispatch completion, research decision dispatch, research-to-finding connection, result message serialization, send/receive protocol, attach evidence, propagate state updates |
| test_execution_engine.py | Comprehensive — execution status, results, policy decisions, gates, task executor, execution service, proposal service, end-to-end |
| test_e2e_loop_flow.py | Moderate — full loop close, unlink removes connection, dispatch research ingests and links, emit gaps with goal scoping |
| test_e2e_task_loop.py | Moderate — add/list/complete/state progress/integration/help routing |
| tests/plugins/test_e2e_execution_feedback.py | Moderate — end-to-end goal/task/milestone/research/decision/no-linkage/failsafe/goal-skill-evidence flows |
| test_coordination.py | Moderate — agent result, coordination result, init, delegate, aggregate, timeout, failure, execute with fallback, retry with backoff, coordination integration |
| test_dispatch_task.py | Basic — extract required capabilities, match agent role, dispatch task |

---

## 7. Obsidian/Knowledge Pipeline Tests

| Test File | Coverage |
|---|---|
| test_knowledge_pipeline.py | Comprehensive — curation gate state transitions, curate proposal dispatcher, expire stale proposals, promote to Obsidian vault resolution, promote transitions to vaulted, vaulted transition, propose note content, from summary finding indices, validation to curation bridge, generate summary to promoter bridge, persist promotion record, vault resolution, promotion report serializable, knowledge CLI surface, promotion records data directory, full pipeline E2E |
| test_curation_gate.py | Comprehensive — curation gate state transitions, curate proposal dispatcher, expire stale proposals, promote to Obsidian vault resolution, propose note content, from summary finding indices, validation to curation bridge, generate summary to promoter bridge, persist promotion record, vault resolution, promotion report serializable, knowledge CLI surface, promotion records data directory, full pipeline E2E |
| test_skill_pipeline.py | Moderate — gap detection, proposal, generation, tests, sandbox, verification, approval, install, trust model, stage transitions, skill proposal, trust level, full pipeline |
| test_research_models.py | Moderate — research artifact, composite confidence, topic block, entity extraction, knowledge summary, topic ordering, linked goal titles |
| test_research_artifact_models.py | Moderate — source, finding, research artifact, YAML parsing, section extraction, findings extraction, round trip, slugify, research artifact service, cross-linking |
| test_structured_remediation_integration.py | Basic — structured remediation field, weekly review, Telegram weekly, CLI weekly |

### Notable Gap
- No direct Obsidian vault file I/O tests (creating, updating, deleting vault notes).
- Knowledge pipeline tested through curation gate layer, not direct vault operations.

---

## 8. Hermes Integration Tests

| Test File | Coverage |
|---|---|
| test_evidence_propagation.py | Uses `pytest.importorskip("hermes_cli")` — skips entirely if hermes_cli not installed |
| test_evidence_verification_chain.py | Same importorskip guard |
| test_evidence_propagation_edge_cases.py | Same importorskip guard |
| test_kanban_review_topology.py | Same importorskip guard |
| test_swarm_integration_opt_out.py | Same importorskip guard |
| tests/plugins/conftest.py | Same importorskip guard |

### Key Finding
- **No actual Hermes integration tests exist.** All hermes_cli references use `importorskip`, meaning these tests are silently skipped when hermes_cli is absent. The test suite has zero tests that exercise the real Hermes CLI or agent integration.

---

## 9. TODOs, FIXMEs, Skip, XIT, XDescribe in Tests

### importorskip (hermes_cli not available)
| File | Line | Reason |
|---|---|---|
| tests/test_evidence_propagation_edge_cases.py | 59 | `pytest.importorskip("hermes_cli", reason="hermes_cli not available (install hermes-agent)")` |
| tests/test_evidence_verification_chain.py | 42 | Same |
| tests/test_evidence_propagation.py | 49 | Same |
| tests/test_kanban_review_topology.py | 60 | Same |
| tests/test_swarm_integration_opt_out.py | 50 | Same |
| tests/plugins/conftest.py | 37 | Same |

### Skipped/Pending Test Logic (not pytest.skip, but conditional skip behavior)
| File | Test | Reason |
|---|---|---|
| tests/test_weekly_review.py:859 | `test_skips_open_tasks` | Only `- [x]` lines considered; `- [ ]` lines skipped |
| tests/test_weekly_review.py:872 | `test_skips_lines_without_completion_date` | Completed lines without parseable date silently skipped |
| tests/test_evidence_propagation_edge_cases.py:189 | `test_dispatch_skips_research_without_body` | Research/finding with no body is skipped, not crashed |
| tests/test_personal_state_builder.py:548 | `test_build_skips_integrity_audit_when_disabled` | build() skips integrity audit when include_integrity_audit=False |
| tests/test_execution_engine.py:127-141 | Multiple | ExecutionStatus.SKIPPED assertions (testing status enum, not skipping tests) |
| tests/test_state_update.py:92 | docstring | "apply_verification_result dispatches evidence on PASS, skips on FAIL" |
| tests/test_metric_progression.py:11 | docstring | metric_updates lists, metric-name matching/skipping |
| tests/test_next_action_projects.py:78 | `test_p1_skips_completed_task` | P1 skips completed task |
| tests/test_next_action_projects.py:205 | `test_p4_skips_terminal_projects_in_next_milestone` | P4 skips terminal projects |
| tests/test_execution_feedback.py:802 | `test_dispatch_decision_skips_if_exists` | Dispatch decision skips if already exists |
| tests/test_execution_feedback.py:1284 | `test_receive_skips_unknown_object` | Dispatch skips unknown objects |
| tests/test_metric_history.py:173 | `test_skips_malformed_lines` | Skips malformed lines |
| tests/test_task_list.py:147 | `test_list_skips_default_priority_and_state` | List skips default priority/state |
| tests/test_evidence_propagation.py:199 | docstring | Already-completed tasks skip gates |
| tests/test_activity_ingest.py:966 | docstring | dedup_policy='merge' = skip duplicate |

### No FIXME/TODO/XFAIL/XDESCRIBE Found
- Zero `FIXME`, `TODO`, `xfail`, or `xdescribe` markers found in the test suite.
- The only skip-related patterns are `importorskip` guards and application-level conditional skip logic.

---

## Summary Statistics

| Metric | Count |
|---|---|
| Total test files | 125 |
| Total test classes/functions (non-regression) | 1,068 |
| Total regression test classes/functions | 45 |
| Total combined | 1,113 |
| Test files with importorskip (hermes_cli) | 6 |
| Test files with TODO/FIXME/xfail/xdescribe | 0 |
| Regression test files | 8 |
| Plugin test files | 3 |

### Category Coverage Summary

| Category | Coverage Level |
|---|---|
| Feature coverage | Broad but shallow — many features have tests but often only model-level, not integration-level |
| Lifecycle tests | Strong — comprehensive regression suite for startup/shutdown/state transitions/completion gates |
| Verification tests | Strong — Phase 1, Phase 3.5, default checks, OS replace gate, verification result |
| Integration tests | Moderate for git/calendar/telegram; Weak for external APIs (no real API calls) |
| Goal audit/repair | Strong — comprehensive audit + repair test matrices |
| Execution feedback | Strong — full dispatch completion, evidence propagation, E2E loop flows |
| Obsidian/knowledge pipeline | Moderate — curation gate and knowledge pipeline well-tested; direct vault I/O not tested |
| Hermes integration | **None** — all hermes references use importorskip, tests skipped when hermes_cli absent |
| TODOs/skip markers | Minimal — no TODO/FIXME/xfail; skip logic is application-level only |

### Critical Gaps
1. **Hermes integration is untested** — 6 files use importorskip, zero real integration tests
2. **Obsidian vault direct I/O** — no file-level vault operations tested
3. **Telegram incoming messages** — only outbound formatting tested
4. **Real external API calls** — all external integrations use protocol/mock testing
5. **Full task lifecycle E2E** — no single test covers todo → in_progress → done with all gates end-to-end
6. **Config/settings loading** — minimal coverage; no dedicated test file