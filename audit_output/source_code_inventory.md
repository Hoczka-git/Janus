# Janus Source Code Inventory

Generated: 2026-10-03 by researcher (task t_af31540c)
Scope: `src/` Python source only (excludes tests, docs, config templates)

---

## 1. Implemented Features

### CLI Subcommands (entry: `src/janus/__init__.py` → `main()`)
- `today` — daily briefing (schedule, attention, suggested focus)
- `telegram` — send today briefing to Telegram
- `telegram-weekly` — send weekly Telegram digest
- `task add/complete/list/state/progress/sync` — task CRUD + sync
- `workout add/show/summary` — workout logging
- `goal list/show/add/update/complete/milestone/project/next/health/audit/repair` — goal management
- `weekly` — weekly review
- `status` — strategic summary
- `inbox list/pending/triage` — inbox management
- `followup list/add/show/update/complete/convert-to-task` — follow-ups
- `research add/show/list/link/promote-finding/propose/approve/reject/defer/promote/show-proposal/list-proposals` — research pipeline
- `knowledge` — knowledge vault operations
- `decision propose/link-finding/link-goal/list/show` — decision records
- `plan week` — weekly plan
- `proposal list/show/approve/reject/execute` — proposal engine CLI
- `execution list/show` — execution results

### Core Services (`src/janus/services/`)
- Task service: full CRUD, state machine, progress, completion gates, sync
- Goal service: CRUD, milestones, projects, health, audit, repair, skills
- Goal integrity audit (`goal_integrity.py`) — deterministic read-only health check
- Goal integrity repair (`goal_integrity_repair.py`) — configurable, reversible repairs
- Knowledge pipeline (`knowledge_pipeline.py`) — validation + summary generation
- Obsidian promoter (`obsidian_promoter.py`) — vault promotion
- Curation gate (`curation_gate.py`) — human approval gate for knowledge
- Execution feedback (`execution_feedback.py`) — Hermes→Janus write-back
- Policy engine (`policy_engine.py`) — approval gates with audit log
- Pipeline (`pipeline.py`) — Planner→Agency→Policy orchestration
- Strategic summary (`strategic_summary.py`) — portfolio health, stalled/neglected goals
- Weekly review (`weekly_review.py`) — weekly review generation
- Daily briefing (`daily_briefing.py`) — daily briefing generation
- Attention engine (`attention.py`) — deterministic prioritization
- Skill pipeline (`skill_pipeline.py`) — self-extending capabilities G1-G9
- Evidence collection (`evidence_collection.py`) — evidence pipeline
- Remediation (`remediation.py`) — remediation planning
- Recommendations / recommended actions
- Projects, milestones, follow-ups, inbox, workout analytics
- Measurement collection / log

### Models (`src/janus/models/`)
Goal, Task, Milestone, Project, Event, DailyBriefing, WeeklyReview, Decision, ResearchArtifact,
KnowledgeSummary, CurationProposal, VerificationResult, Policy, TrustModel, AgentRole,
AgentLifecycle, AttentionItem, FollowUp, OutcomeRecord, MetricSnapshot, Constraint,
Resource, Routine, Preference, PersonalState, RecommendedAction, StrategicSummary,
GoalHealthAssessment, GoalIntegrityReport, AgentAssignment, TaskAgency, ExecutionMode,
SupportMode, SkillProposal, Remedy/Remediation, CurationProposal, etc.

### Integrations (`src/janus/integrations/`)
- Google Calendar (read + ad-hoc connector)
- Telegram (send briefing, message formatting)
- Markdown-based storage: tasks, goals, inbox, followups, routines, preferences, constraints, curation, research, resources
- GitHub, AWS, Email, Fitness connectors — all **stubs** (read-only, return empty list)
- Atomic IO, data integrity, metric history, workout markdown
- `connector.py` — Connector ABC protocol (7 methods: source, capabilities, permissions, read, propose, execute, evidence)
- `registry.py` — ConnectorRegistry lifecycle management

### Execution Engine (`src/janus/execution/`)
- `TaskExecutor` — V1 executor (CREATE_TASK, UPDATE_TASK, RESCHEDULE_TASK)
- `PolicyGate` — pre-execution policy evaluation
- `ExecutionService` — persistence + idempotency (data/executions.jsonl)
- Protocol (`ActionExecutor`) — runtime_checkable protocol

### Verification (`src/janus/verification.py`)
12 check functions: files_create, files_immutable, data_write_path, data_file_write_gates,
commands, files_modify, unexpected_modified, untracked, symbols_required, symbols_forbidden,
os_replace, git_diff_check
+ 3 default-on pre-completion checks: working_tree_clean, git_diff_check, tests_pass_after_rebase
YAML contract loading, AST-based symbol detection, conflict marker detection

### Proposal System (`src/janus/proposal/`)
ActionProposal model, ApprovalGate, ApprovalWorkflow, Guard, PolicyCheck
ActionType: CREATE_TASK, UPDATE_TASK, RESCHEDULE_TASK, CHANGE_PRIORITY, CREATE_CALENDAR_EVENT

### Domain / Planning (`src/janus/domain/planning.py`)
`derive_next_action()` — derives next action from goals/tasks

---

## 2. TODOs / FIXMEs / HACKs / XXXs

| File | Line | Text |
|------|------|------|
| `src/janus/services/goal_gates.py` | 92 | `# TODO: Integrate with task service to check task completion status.` |
| `src/janus/services/skill_pipeline.py` | 938 | `# TODO: Implement {proposal.capability_name} logic` (generated stub comment) |
| `src/data/skills/fetch-weather.py` | 15 | `# TODO: Implement fetch-weather logic` + raises NotImplementedError |

Only 3 TODOs found in source. No FIXME, HACK, or XXX comments.

---

## 3. Lifecycle Behavior

### Start / Run / Shutdown
- **No explicit lifecycle manager**. `src/janus/__init__.py::main()` is a CLI dispatcher — runs a command and exits. No daemon, no background loop.
- Logging configured via `setup_logging()` (verbose flag).
- `emit()` structured logging throughout (trace_id, span_id, correlation_id).
- No init/teardown hooks, no state machine for the application itself.
- Agent lifecycle (`AgentLifecycle` enum) is **managed by Hermes**, not Janus — Janus only tracks dispatch decision + task assignment.

### Plugin lifecycle
- `plugins/janus_sync/__init__.py` registers two hooks: `kanban_task_claimed` (pre-implementation sync), `kanban_task_completed` (Hermes→Janus write-back).
- `plugins/replenishment` referenced but not present in this tree.

---

## 4. Verification Capabilities

### What exists
- **Verification pipeline** (`src/janus/verification.py`): 12 check types + 3 default-on pre-completion checks, YAML contract-driven, AST-based symbol detection, git diff conflict marker detection, data write path enforcement.
- **Goal integrity audit** (`src/janus/services/goal_integrity.py`): deterministic read-only health check of goal↔task↔metric relationships.
- **Data integrity** (`src/janus/integrations/data_integrity.py`): post-write verification, file repair, backup.
- **Atomic IO** (`src/janus/integrations/atomic_io.py`): read-modify-write with SHA-256 conflict detection, post-write verify.
- **Completion gates** (tasks.py: `run_completion_gates`, `run_unified_completion_gates`; goal_gates.py: `run_goal_completion_gates`).
- **Policy engine** (`policy_engine.py`): approval gate with audit log (`get_audit_log`).
- **Skill pipeline verify_capability** (skill_pipeline.py:515).
- **Outcome verification** (`outcome_verification.py:366`).
- **CLI verification**: `janus goal audit`, `janus goal repair`, `janus task sync`.

### Stubs vs real
- Verification pipeline: **real**, fully implemented.
- Goal integrity audit + repair: **real**, fully implemented.
- Data integrity: **real**, fully implemented.
- Atomic IO: **real**, fully implemented.
- Completion gates: **real**, fully implemented.

---

## 5. Integration Behavior

### External connectors
- **Google Calendar**: real (wraps `google-api-python-client`), read-only.
- **Telegram**: real (send briefing + message formatting).
- **Markdown storage**: real (13 markdown integration modules for tasks/goals/inbox/followups/routines/preferences/constraints/curation/research/resources).
- **GitHub, AWS, Email, Fitness**: **stubs** — define Connector subclass, return empty list from `read()`, raise NotImplementedError for propose/execute/evidence.
- **Atomic IO + data integrity**: real, used by markdown modules for safe writes.

### Hermes integration
- **Direction**: Hermes → Janus only (Janus never calls Hermes).
- **Bridge**: `janus_domain` frontmatter in task bodies (parsed by `execution_feedback.parse_janus_domain_metadata`).
- **Plugin**: `plugins/janus_sync` — hooks `kanban_task_claimed` (Phase 1 sync) and `kanban_task_completed` (write-back).
- **Wire protocol**: `send_execution_result` / `receive_execution_result` round-trip through `ExecutionResultMessage`.
- **Execution feedback dispatch**: `dispatch_completion` routes to goals.update_goal_progress, tasks.complete_janus_task, milestones.update_milestone_status, research ingestion, ADR persistence.

### Integration gate
- `src/janus/integration.py`: Safe Integration phase primitive (fast-forward attempt → controlled merge → post-merge tests → push → remote containment check). Reason codes for each failure mode.

---

## 6. Goal Audit / Repair

### Audit
- `src/janus/services/goal_integrity.py:audit_goal_integrity()` — deterministic read-only health check.
- Checks: GOAL_WITHOUT_TASKS, UNKNOWN_GOAL_REFERENCE, INVALID_METRIC, STALE_ACTIVITY, ORPHANED_TASK, INVALID_RELATED_TASK, RELATIONSHIP_COUNT_MISMATCH, CIRCULAR_REFERENCE.
- CLI: `janus goal audit [--json]` (`goals_cli.py:1488`).

### Repair
- `src/janus/services/goal_integrity_repair.py:repair_goal_integrity()` — configurable, reversible, dry-run by default.
- Repairable: UNKNOWN_GOAL_REFERENCE, INVALID_RELATED_TASK, CIRCULAR_REFERENCE, ORPHANED_TASK, RELATIONSHIP_COUNT_MISMATCH.
- Non-repairable (report only): GOAL_WITHOUT_TASKS, INVALID_METRIC, STALE_ACTIVITY.
- CLI: `janus goal repair` (`goals_cli.py:1572`).

### Health
- `src/janus/services/goal_health.py` — goal health assessment.
- `src/janus/models/goal_integrity_report.py` — GoalIntegrityReport with healthy_checks + issue tracking.

---

## 7. Execution Feedback

### How the system reports progress/results
- **Structured logging**: `emit()` with trace_id/span_id/correlation_id throughout (`_log.py`).
- **CLI output**: formatted terminal tables (today, weekly, status, goals, tasks).
- **Telegram**: `send_briefing()` (daily) + `send_weekly_telegram()` (weekly).
- **Execution results**: `ExecutionResult` model persisted to `data/executions.jsonl`.
- **Hermes→Janus write-back**: `execution_feedback.py` — `EvidencePackage`, `JanusDomainMetadata`, `propagate_state_updates`.
- **Audit comments**: `janus_sync` writes structured audit comments on completed tasks.
- **Strategic summary**: `strategic_summary.py` — portfolio health, stalled/neglected goals, recommended next actions.
- **Weekly review**: `weekly_review.py` — structured review with remediation.
- **Daily briefing**: `daily_briefing.py` — attention items, suggested focus, calendar integration.

---

## 8. Obsidian / Knowledge Pipeline

### What exists
- **Research Knowledge Pipeline** (4 steps):
  - Step 1: `knowledge_pipeline.py::validate_artifact()` — intake validation.
  - Step 2: `knowledge_pipeline.py` — summary generation (KnowledgeSummary IR).
  - Step 3: `curation_gate.py` — human curation approval gate.
  - Step 4: `obsidian_promoter.py::promote_to_obsidian()` — write to vault + audit record.
- **Models**: KnowledgeSummary, CurationProposal (states: pending_approval → approved → vaulted).
- **CLI**: `janus knowledge` subcommand (promote, render).
- **Research CLI**: `janus research promote-finding`, `janus research promote`, `janus research list-proposals`.
- Config: `JANUS_OBSIDIAN_VAULT` env var or `--vault` CLI flag.

### Stubs vs real
- Full pipeline from research artifact → validation → curation → Obsidian promotion: **real**.
- No knowledge graph code found (no graph data structure or graph operations in source).

---

## 9. Hermes Integration

### What exists
- **`plugins/janus_sync/__init__.py`**: full Hermes→Janus sync listener.
  - `kanban_task_claimed` hook: auto-sync branch (ADR-004 Phase 1).
  - `kanban_task_completed` hook: parse `janus_domain` frontmatter, assemble EvidencePackage, dispatch to Janus service functions, record audit comment.
  - Best-effort, idempotent, fail-safe.
- **`src/janus/services/execution_feedback.py`**: Hermes→Janus write-back protocol.
  - `EvidencePackage`, `JanusDomainMetadata`, `ExecutionResultMessage`.
  - `send_execution_result` / `receive_execution_result` round-trip.
  - `propagate_state_updates` — dispatches to goal/task/milestone/research/ADR services.
- **`src/janus/integration.py`**: integration primitive for task branches (safe sync-and-integrate workflow).
- **Agent registry** (`src/janus/services/agent_registry.py`): role→capability mapping for Planner/Researcher/Executor/Reviewer/Coach.
- **Agent lifecycle model** (`src/janus/models/agent_lifecycle.py`): SPAWNING/ACTIVE/IDLE/SHUTDOWN states (managed by Hermes, Janus tracks dispatch only).
- **Directionality**: Hermes → Janus only. Janus never calls Hermes back.

### Stubs vs real
- Janus↔Hermes integration: **real and functional** — hooks, wire protocol, dispatch, audit.
- Agent registry: **real** but populated with static defaults (backed by Phase G skill registry in design, not yet implemented).
- Agent lifecycle: **model only** — Janus tracks states but does not manage transitions (Hermes manages).

---

## Summary: Stubs vs Real

### Real (fully implemented)
- CLI command dispatching (all listed subcommands)
- Task/Goal/Milestone/Project/FollowUp/Inbox CRUD + state machines
- Knowledge pipeline (research → validation → curation → Obsidian)
- Goal integrity audit + repair
- Verification pipeline (12 checks + 3 default-on)
- Policy engine + approval gates
- Execution engine V1 (TaskExecutor + PolicyGate + ExecutionService)
- Action proposal system (propose → approve → execute)
- Hermes→Janus integration (janus_sync plugin + execution_feedback protocol)
- Atomic IO + data integrity
- Google Calendar + Telegram integrations
- Markdown-based storage (13 modules)
- Strategic summary + weekly review + daily briefing
- Agent registry + AgentLifecycle model
- Integration gate primitive

### Stubs / Partial
- GitHub, AWS, Email, Fitness connectors (stub read-only, return [])
- `fetch-weather.py` skill (NotImplementedError)
- Skill pipeline generation (G3-G9: generates code stubs but execution delegated to Hermes)
- Agent registry backed by Phase G skill registry (design exists, static defaults only)
- `replenishment` plugin (referenced but not in tree)
