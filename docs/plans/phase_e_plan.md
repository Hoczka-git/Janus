# Phase E — Policy & Approval: Synthesized Plan and Handoff Package

**Status:** Plan complete — ready for implementer phase
**Date:** 2026-09-30
**Scope:** Phase E (Policy & Approval, P1/P2)
**Parent tasks:**
- t_4a3bc8f3 — P1 design doc (merged, PR #293)
- t_f0a8da14 — P2 design doc (merged, PR #294)
- t_58f3186c — P1 requirements spec
- t_23d33a79 — P2 requirements spec
- t_bb8e173d — Infrastructure discovery findings
**Dependent task:** t_16d8884f (root plan task, todo)
**Roadmap context:** `docs/roadmap.md` line 156 — Phase E — Policy & Approval (P1/P2)
**Source docs:**
- `docs/design/policy_approval_p1_design.md` (P1, 612 lines)
- `docs/design/p2-policy-enforcement-design.md` (P2, 913 lines)
- `docs/specs/p1-policy-approval-requirements.md` (P1, 305 lines)
- `docs/specs/p2-policy-approval-requirements.md` (P2, 269 lines)
- `docs/research/t_bb8e173d-policy-approval-infrastructure-findings.md` (discovery, 325 lines)

---

## 1. Purpose

This document synthesizes the P1 and P2 designs, discovery findings, and requirements into a single Phase E plan. It is the handoff package for the implementer phase (t_16d8884f). It does not implement features — it organizes what has already been designed into an implementable sequence with dependencies, open questions, and a clear handoff.

Phase E's goal (from roadmap): **increase automation without reducing user control**. The Phase E layer turns Phase D's agency-aware classification into enforceable policy: which actions are allowed automatically, which require explicit user approval, and which are denied.

---

## 2. What Exists (Input Documents Summary)

### 2.1 P1 — Enforcement tier (PR #293, merged)

P1 is the **blocking, human-approval layer**. It defines 16 policy rules (R1-R16) mapping actions to ALLOW/ASK/DENY verdicts, 7 approval gates (G-1 to G-7), and the approval workflow. P1 rules are encoded as code (a `PolicyRule` registry), not YAML — that extraction is P2's job.

**Key P1 components:**
- `PolicyVerdict` enum (ALLOW/ASK/DENY)
- `RiskLevel` enum (LOW/MEDIUM/HIGH)
- `PolicyRule` dataclass (16 rules, first-match with most-restrictive-precedence)
- `PolicyDecision` dataclass (evaluation result)
- `ApprovalRequest` dataclass (what to present to user)
- `ApprovalResponse` enum (APPROVE/DENY/DEFER)

**P1 gates (G-1 to G-7):**
- G-1: Task completion (git repo) — mechanical + human (ADR-004 Phase 3+5)
- G-2: Goal completion — mechanical (structural) + human (high-stakes) — ADR-011
- G-3: Knowledge artifact promotion — human (curation gate, existing)
- G-4: External system state-changing write — human (CLI prompt)
- G-5: Goal deletion — human (CLI confirm)
- G-6: Bulk state change — human (CLI lists entities)
- G-7: Policy-relevant configuration change — human (CLI confirm)

**P1 implementation phases (from design doc §10):**
1. Data models + policy engine (no integration)
2. Goal completion gates (ADR-011)
3. External write + bulk + config gates
4. CLI approval prompt
5. Edge cases + failure modes

P1 addresses 17 acceptance criteria (AC-PR-1..5, AC-AG-1..5, AC-AW-1..4, AC-SB-1..3).

### 2.2 P2 — Substrate tier (PR #294, merged)

P2 is the **classification, configuration, recording, and deferral layer**. It does NOT add new blocking gates — it makes P1's gates configurable, auditable, and deferrable. P2 is data-driven: policy rules, action taxonomy, and thresholds are YAML files.

**Key P2 components:**
- `ActionType` enum (8 types: state_change, data_write, external_call, external_write, bulk_operation, deletion, configuration_change, knowledge_promotion)
- `action_taxonomy.yaml` — default risk mapping (data, not hardcoded)
- PolicyEngine — loader + evaluator reading `policy_rules.yaml`
- `ApprovalRequest` model with status lifecycle (pending/approved/rejected/deferred/escalated/timed_out)
- `ApprovalHandler` — deferred + escalated approval logic
- `PolicyDecisionLog` — JSONL recording in `data/policy_decisions/`
- `BulkClassifier` — bulk operation detection with configurable thresholds
- Policy version lifecycle — versioned rule sets, no retroactive re-evaluation

**P2 file layout (from design doc §5):**
```
config/policy/
  action_taxonomy.yaml
  policy_rules.yaml
  bulk_thresholds.yaml

src/janus/models/
  action_type.py
  approval_request.py

src/janus/services/
  policy_engine.py
  approval_handler.py
  policy_decision_log.py
  bulk_classifier.py

data/
  approval_requests/
    approval_requests.jsonl
  policy_decisions/
    YYYY-MM-DD.jsonl

tests/
  test_policy_engine.py
  test_approval_request.py
  test_approval_handler.py
  test_policy_decision_log.py
  test_bulk_classifier.py
  test_action_type.py
```

**P2 implementation phases (from design doc §6):**
1. Data models + taxonomy (no dependencies) — ActionType, action_taxonomy.yaml, ApprovalRequest model
2. Loaders + evaluators (depends on Phase 1) — PolicyEngine, policy_rules.yaml, BulkClassifier
3. Handlers + recording (depends on Phase 2) — ApprovalHandler, PolicyDecisionLog
4. Versioning (depends on Phase 2) — version field in YAML, version recording in log
5. Integration tests — P1 gate → PolicyEngine → ApprovalRequest flow, bulk → classifier flow, timeout → deferred, escalation → re-routed

P2 maps all 30 acceptance criteria (AC2.1.1 through AC2.7.4).

### 2.3 Discovery findings (t_bb8e173d)

10 existing policy/approval/governance components identified:
1. ADR-004 5-phase gated completion (fully implemented) — `tasks.py:run_completion_gates`, `integration.py:integrate_task`
2. Curation gate (knowledge pipeline approval) — 5 states, 6 transitions, `CurationGateError`
3. Regeneration gate (write-policy enforcement) — `data_integrity.py:426-518`, threshold + whitelist
4. Verification pipeline — `verification.py:2690`, 3 default checks + 14 contract check types
5. Goal integrity audit — `goal_integrity.py:665`, 8 issue codes, 3 severity levels
6. Remediation engine — `remediation.py:882`, `ESCALATION_POLICY` dict (advisory)
7. State transition rules — `personal_state.py:62-105`, 3 transition tables
8. Execution feedback dispatch — `execution_feedback.py:1019`, Phase 5 gate for tasks
9. Plugin hook infrastructure — `janus_sync` (dormant, not loaded), `replenishment`
10. ADR-003 review topology (Hermes-core Model A native review lane)

10 gaps identified:
1. No goal-level completion gates (ADR-011 proposed, P0)
2. Dormant janus_sync plugin (code-complete, not loaded)
3. No contracts/ directory usage (capability implemented, unused)
4. No reusable generic approval workflow service
5. No configurable policy engine (hardcoded)
6. No multi-step workflow state machine for approvals
7. No structured policy decision recording entity
8. No escalation enforcement (ESCALATION_POLICY advisory only)
9. Contract completion_gates field not wired
10. No governance dashboard / aggregated audit trail

Reusability: `CompletionGateResult` + `CompletionGateError` pattern, `CurationProposal` state machine, `gate_regeneration()` pattern, `DefaultCheckConfig` + `run_default_checks()`, `ImplementationContract` + `run_verification()`, `ESCALATION_POLICY` dict pattern, state transition tables, `EvidencePackage` + `ExecutionResultMessage`, `atomic_io` + `data_integrity`, `janus_sync` plugin hook pattern.

### 2.4 Phase D integration (already implemented)

P1 policy rules consume Phase D outputs:
- `ExecutionMode` (USER|JANUS|COLLABORATIVE) — from `models/execution_mode.py`
- `SupportMode` (EXPLAIN|COACH|SCAFFOLD|REVIEW|EXECUTE) — from `models/support_mode.py`
- `TaskAgency` (mode, support, reason, confidence) — from `models/task_agency.py`, computed by `services/agency_planning.py:classify_task()`
- `AgencyContext` (skill_evidence_count, goal_health, goal_stalled, task_completion_history) — from `services/agency_planning.py`

---

## 3. Combined Dependency Graph

```
                    t_bb8e173d (discovery findings)
                            │
        ┌───────────────────┼───────────────────┐
        ▼                   ▼                   ▼
   t_58f3186c          t_23d33a79          t_eb3af3e3
   (P1 req spec)       (P2 req spec)       (Phase D done)
        │                   │                   │
        ▼                   ▼                   │
   t_4a3bc8f3          t_f0a8da14             │
   (P1 design)         (P2 design)            │
        │                   │                   │
        └───────┬───────────┘                   │
                ▼                               │
          t_8660a159  ◄── THIS TASK            │
          (synthesize plan)                     │
                │                               │
                ▼                               │
          t_16d8884f (root, todo)              │
          (implementer phase) ◄────────────────┘
```

**Dependency direction:** P1 → P2 (one-way). P1 gates consult P2's classification and rule set to determine whether to block, ask, or allow. P2 does not call P1's gates. P2's deferred/escalated approvals are the "lighter controls" — P1 requires explicit confirmation for high-risk; P2 says "if the user doesn't respond, defer and escalate rather than block forever or auto-approve."

---

## 4. Combined Implementation Order

The two designs each define a 5-phase implementation order. The combined order respects the P1→P2 dependency: P2's substrate must be partially available before P1's gates can consume it, but P1's enforcement gates are the higher-priority blocking layer.

### Combined Phase 1: Data models (both tiers, parallelization possible)

**P1 track (from P1 design §10 Phase 1):**
1. Create `src/janus/models/policy.py` with all P1 data models (PolicyVerdict, RiskLevel, PolicyRule, PolicyDecision, ApprovalRequest, ApprovalResponse)
2. Create `src/janus/services/policy.py` with `POLICY_RULES` and `evaluate_policy()`
3. Write unit tests for policy evaluation (all 16 rules, precedence, edge cases)
4. **No integration with existing services yet**

**P2 track (from P2 design §6 Phase 1):**
1. Create `ActionType` enum in `src/janus/models/action_type.py`
2. Create `config/policy/action_taxonomy.yaml` — default risk mapping
3. Create `ApprovalRequest` model in `src/janus/models/approval_request.py`
4. Create `data/approval_requests/` directory
5. Tests: `test_action_type.py`, `test_approval_request.py`

**Note:** P1's `ApprovalRequest` dataclass (in `policy.py`) and P2's `ApprovalRequest` model (in `approval_request.py`) must be reconciled. P2's model is more complete (status lifecycle, channel, policy_version, expires_at). P1's design predates P2's model. The combined implementer should use P2's richer model as the single source of truth and update P1's references accordingly. See Open Question OQ-COMBO-1.

**Parallelization:** P1 track step 1-3 and P2 track step 1-4 are independent and can be done in parallel by different workers.

### Combined Phase 2: Loaders, evaluators, and P1 goal gates

**P2 track (from P2 design §6 Phase 2):**
1. Create `PolicyEngine` in `src/janus/services/policy_engine.py`
2. Create `config/policy/policy_rules.yaml` — default rule set
3. Create `BulkClassifier` in `src/janus/services/bulk_classifier.py`
4. Create `config/policy/bulk_thresholds.yaml`
5. Tests: `test_policy_engine.py`, `test_bulk_classifier.py`

**P1 track (from P1 design §10 Phase 2):**
1. Create `src/janus/services/goal_gates.py` with `run_goal_completion_gates()`
2. Integrate into `goals.py:complete_goal()`
3. Write unit tests for goal completion gates
4. Wire G-2 into the approval workflow

**Dependency:** P1's G-2 (goal completion gates) consults P2's PolicyEngine to evaluate the action. P2 Phase 2 must land before P1 Phase 2 integration. P2 Phase 2 steps 1-2 (PolicyEngine + rules YAML) are the dependency; BulkClassifier (step 3-4) can come later.

### Combined Phase 3: Handlers, recording, and remaining P1 gates

**P2 track (from P2 design §6 Phase 3):**
1. Create `ApprovalHandler` in `src/janus/services/approval_handler.py` (deferred + escalated)
2. Create `PolicyDecisionLog` in `src/janus/services/policy_decision_log.py`
3. Create `data/policy_decisions/` directory
4. Tests: `test_approval_handler.py`, `test_policy_decision_log.py`

**P1 track (from P1 design §10 Phase 3):**
1. Add G-4 (external write) integration to relevant service functions
2. Add G-6 (bulk operation) integration
3. Add G-7 (config change) integration
4. Write unit tests for each gate

**Dependency:** P1's G-4, G-6, G-7 all produce approval requests that P2's ApprovalHandler manages (deferred/escalated) and PolicyDecisionLog records. P2 Phase 3 must land before P1 Phase 3 integration is complete. P1's G-3 (curation gate) is already implemented — no new work.

### Combined Phase 4: CLI approval prompt + P2 versioning

**P1 track (from P1 design §10 Phase 4):**
1. Create the approval prompt formatter (`format_approval_prompt()`)
2. Integrate into CLI commands (`janus goal complete`, `janus goal delete`, external write commands, bulk operation commands, config change commands)
3. Write integration tests for the full approval flow

**P2 track (from P2 design §6 Phase 4):**
1. Add version field to YAML files (already in schema)
2. Add version recording to PolicyDecisionLog (already in schema)
3. Tests: version increment, version recording, no re-evaluation

**Parallelization:** P1 Phase 4 (CLI prompt) and P2 Phase 4 (versioning) are independent and can be parallelized.

### Combined Phase 5: Integration tests + edge cases + failure modes

**P2 track (from P2 design §6 Phase 5):**
1. Integration tests — P1 gate → PolicyEngine → ApprovalRequest flow
2. Bulk operation → BulkClassifier → ApprovalRequest flow
3. Timeout → deferred flow
4. Escalation → re-routed flow

**P1 track (from P1 design §10 Phase 5):**
1. Add error handling for all failure modes (§9 of P1 design)
2. Add logging for policy decisions
3. Write tests for edge cases (§8 of P1 design)

---

## 5. Consolidated File/Directory Layout (combined)

```
config/policy/
  action_taxonomy.yaml          # P2 — action types + default risk mapping
  policy_rules.yaml             # P2 — policy rules (verdicts, approval, channels)
  bulk_thresholds.yaml          # P2 — bulk operation thresholds

src/janus/models/
  policy.py                     # P1 — PolicyVerdict, RiskLevel, PolicyRule, PolicyDecision (P1 versions)
  action_type.py                # P2 — ActionType enum
  approval_request.py           # P2 — ApprovalRequest model + status lifecycle (RICHER — use this)
  policy_decision.py            # P1 — PolicyDecision (may merge into approval_request.py or keep separate)

src/janus/services/
  policy.py                     # P1 — POLICY_RULES + evaluate_policy() (P1 code-driven rules)
  policy_engine.py              # P2 — PolicyEngine (loader + evaluator, YAML-driven)
  goal_gates.py                 # P1 — run_goal_completion_gates() (ADR-011)
  approval_handler.py           # P2 — deferred/escalated approval logic
  policy_decision_log.py        # P2 — policy decision recording (JSONL)
  bulk_classifier.py            # P2 — bulk operation classifier
  agency_planning.py            # Phase D — classify_task() (existing, consumed by P1/P2)

src/janus/cli/
  approval.py                   # P1 — format_approval_prompt() + CLI approval flow (new module)

data/
  approval_requests/
    approval_requests.jsonl     # P2 — approval request records
  policy_decisions/
    YYYY-MM-DD.jsonl            # P2 — policy decision log (one file per day)

tests/
  test_policy.py                # P1 — policy evaluation unit tests
  test_policy_engine.py         # P2 — policy engine unit tests
  test_approval_request.py      # P2 — approval request model tests
  test_approval_handler.py      # P2 — deferred/escalated approval tests
  test_policy_decision_log.py   # P2 — policy decision recording tests
  test_bulk_classifier.py       # P2 — bulk classifier tests
  test_action_type.py           # P2 — action type taxonomy tests
  test_goal_gates.py            # P1 — goal completion gates tests
```

---

## 6. P1 ↔ P2 Interface Contract

This is the critical integration point. The two designs were done independently; the interface must be made concrete before implementation.

### 6.1 What P1 consumes from P2

| P1 gate | P2 component | What P1 gets |
|---|---|---|
| G-1 (task completion) | PolicyEngine | Verdict for action="state_change", context="task_completion" |
| G-2 (goal completion) | PolicyEngine + BulkClassifier | Verdict for action="state_change", context="goal_completion"; bulk classification if applicable |
| G-3 (knowledge promotion) | PolicyEngine | Verdict for action="knowledge_promotion" (existing curation gate — P2 just classifies) |
| G-4 (external write) | PolicyEngine + ApprovalRequest | Verdict for action="external_write"; creates ApprovalRequest via P2 model |
| G-5 (goal deletion) | PolicyEngine + BulkClassifier + ApprovalRequest | Verdict for action="deletion"; bulk classification; creates ApprovalRequest |
| G-6 (bulk state change) | BulkClassifier + ApprovalRequest | Bulk classification; creates ApprovalRequest |
| G-7 (config change) | PolicyEngine | Verdict for action="configuration_change" |

### 6.2 What P2 does NOT do (by design)

- P2 does not implement the CLI prompt, Telegram notification, or review lane adapter. P2 defines the ApprovalRequest model and the policy decision log. Channels are separate work (P1 Phase 4).
- P2 does not block. P2 classifies, configures, records, and defers. P1 blocks.
- P2 does not call P1's gates. The dependency flows P1 → P2.

### 6.3 P1's evaluate_policy() vs P2's PolicyEngine

This is the key reconciliation point:

- **P1 design** defines `evaluate_policy()` in `src/janus/services/policy.py` — a code-driven function with a hardcoded list of 16 `PolicyRule` instances. This is the "code for now" approach (P1 requirement O1).
- **P2 design** defines `PolicyEngine` in `src/janus/services/policy_engine.py` — a data-driven loader + evaluator that reads `policy_rules.yaml`.

**Recommended reconciliation:** P1's `evaluate_policy()` should be implemented as a thin wrapper that delegates to P2's `PolicyEngine` once P2 is available. During P1-only implementation (before P2 lands), P1 uses its hardcoded rules. After P2 lands, P1's `evaluate_policy()` reads from the PolicyEngine. This avoids duplicating the rule set and gives P2 the data-driven behavior it requires.

The P1 `PolicyRule` dataclass and P2's YAML rule schema must be mapped: P1's `rule_id`, `action`, `context`, `risk_level`, `verdict`, `rationale`, `enforcement_point`, `gate_id` map to P2's `id`, `action`, `context_filter`, `risk_level`, `approval_required` (derived from verdict), `channel`, `expires_hours`.

---

## 7. Consolidated Open Questions

### From P1 requirements (O1-O5)

| # | Question | P1 stance | Action for implementer |
|---|---|---|---|
| O1 | Rules as data or code? | Code for now; P2 extracts to config | P1 implements code-driven; P2 implements data-driven; reconcile via §6.3 |
| O2 | Threshold for "high-stakes goal" (R6/R10)? | Not defined at P1. All goal completions require structural gates. | Future: goal metadata (`high_stakes: true`) or heuristic. Not blocking. |
| O3 | Collaborative-mode: user claim required? | Yes. If unclaimed, route to ASK. | Implement claim check in G-2/G-3 path. |
| O4 | External write approval via Telegram? | P1: CLI only. Telegram is Phase E. | CLI prompt in P1 Phase 4; Telegram adapter is separate work. |
| O5 | G-2 require evidence at P1? | Structural checks only. Evidence requirement is ADR-012. | Implement structural gates now; evidence enforcement is ADR-012 (separate). |

### From P2 requirements (remaining uncertainty)

| # | Question | Status | Action for implementer |
|---|---|---|---|
| U1 | Bulk threshold N | Proposed N=5 as starting point | Use N=5 default; make configurable via `bulk_thresholds.yaml`; tune after real usage |
| U2 | Default expires_at / escalation thresholds | Not specified; choose when channel implemented | Use 24h default for CLI; shorter for interactive channels; configurable per rule |
| U3 | Storage format for policy-decision log | Proposed JSONL in `data/policy_decisions/` | Use JSONL; rotation policy is implementation detail |
| U4 | Per-goal/per-project frontmatter key name | Proposed `janus_policy` | Use `janus_policy`; finalize when frontmatter convention extended |
| U5 | Action taxonomy: model or just documentation? | Requirement says "data, not hardcoded" | Implement as `ActionType` enum + YAML data file (per P2 design §3.1.4) |

### Consolidated open questions (new, from synthesis)

| # | Question | Status | Action |
|---|---|---|---|
| OQ-COMBO-1 | P1 `ApprovalRequest` (dataclass in policy.py) vs P2 `ApprovalRequest` (model in approval_request.py) — which is authoritative? | **Unresolved** | **Decision needed before implementation.** Recommendation: P2's model is richer (status lifecycle, channel, policy_version, expires_at) and should be the single source of truth. P1's `policy.py` should import from P2's `approval_request.py`, not define its own. This affects P1 Phase 1 step 1. |
| OQ-COMBO-2 | P1's `evaluate_policy()` (code-driven, 16 hardcoded rules) vs P2's `PolicyEngine` (YAML-driven) — do we maintain both, or does P1 delegate to P2? | **Unresolved** | **Decision needed.** Recommendation per §6.3: P1's `evaluate_policy()` delegates to P2's `PolicyEngine` once P2 lands. Until then, P1 uses hardcoded rules. The 16 P1 rules must be expressible in P2's YAML schema — verify this during P2 Phase 2. |
| OQ-COMBO-3 | P1's `PolicyDecision` dataclass vs P2's policy-decision-log record schema — do these need to be the same structure? | **Unresolved** | P2's log record (§3.5.1 of P2 design) includes `policy_version`, `approval_request_id`, `approval_outcome` — fields P1's `PolicyDecision` doesn't have. Recommendation: P1's `PolicyDecision` is the in-memory evaluation result; P2's log record is the persisted event. They are related but not identical. The log record should be created from the `PolicyDecision` + approval outcome when available. |
| OQ-COMBO-4 | ADR-011 (goal completion gates) is "proposed, not implemented" — P1 Phase 2 depends on it. What is the implementation status? | **P0 gap per discovery** | P1 Phase 2 step 1 creates `run_goal_completion_gates()`. This is the implementation of ADR-011. The implementer should treat P1 Phase 2 as the ADR-011 implementation task. |
| OQ-COMBO-5 | janus_sync plugin is dormant (not loaded in Hermes install). P1 gates G-1 (task completion) rely on ADR-004 which is implemented but the plugin hook `kanban_task_completed` is not active at runtime. | **Operational gap** | The gate logic is implemented in `tasks.py:run_completion_gates()`. The plugin dormancy affects auto-invoke on task claim, not the gate itself. P1 implementation does not require the plugin to be loaded — the gates run when `complete_task()` is called. Document this distinction. |
| OQ-COMBO-6 | P2's deferral/escalation behavior — "timeout → deferred, not auto-approved" — requires a background process or poll to detect expired requests. Does Janus have such a process? | **Unresolved** | P2 design §3.4 specifies the behavior but not the mechanism. The `replenishment` plugin has a periodic sweep pattern. Recommendation: defer enforcement of timeout/escalation to a later phase; P2 Phase 3 implements the `ApprovalHandler` logic but the actual timeout detection may require a separate scheduler. The model and handler are implementable without the scheduler. |
| OQ-COMBO-7 | P2's per-goal/per-project frontmatter override (`janus_policy` block) — does Janus already parse frontmatter from goal/project files? | **Check required** | Verify that `src/janus/models/` already has frontmatter parsing for goals/projects. If yes, the override path is straightforward. If no, add it as part of P2 Phase 1. |

---

## 8. What P1 and P2 Explicitly Exclude (combined)

- **No new blocking gates beyond P1's G-1 to G-7.** P2 adds no blocking gates.
- **No full rules engine.** No condition expressions, chaining, or negation beyond pattern matching.
- **No full audit log / event sourcing.** P2-5 is a policy-decision log, not an event store.
- **No approval channel implementation in P2.** CLI/Telegram/review adapters are separate work.
- **No auto-approval on timeout or escalation.** Both defer or re-route.
- **No retroactive re-evaluation of past decisions.**
- **No queryable database for policy decisions.**
- **No mode-specific permissions or UI paths (P3).**
- **No evidence model (ADR-012 — separate concern, Phase B).**
- **Not the existing triage-doc P2 items** (CI grep gate P2-1, documentation updates P2-2 — orthogonal to policy/approval domain).
- **Not Phase F (Connector Protocol) or Phase G (self-extending skills).**

---

## 9. Existing Infrastructure to Reuse (consolidated)

| Component | Used for | File reference |
|---|---|---|
| `CompletionGateResult` + `CompletionGateError` | Any gated transition (P1 G-1, G-2) | `src/janus/services/tasks.py:48-88` |
| `CurationProposal` state machine | Approval workflow reference (P1 G-3) | `src/janus/models/curation_proposal.py` |
| `gate_regeneration()` | Write-policy enforcement pattern | `src/janus/integrations/data_integrity.py:426-518` |
| `DefaultCheckConfig` + `run_default_checks()` | Configurable deterministic checks | `src/janus/verification.py` |
| `ImplementationContract` + `run_verification()` | Contract-based enforcement (14 check types) | `src/janus/verification.py` |
| `ESCALATION_POLICY` dict | Policy-driven channel routing pattern | `src/janus/services/remediation.py:67` |
| State transition tables | Model-level validation | `src/janus/models/personal_state.py:62-105` |
| `EvidencePackage` + `ExecutionResultMessage` | Structured handoff evidence | `src/janus/services/execution_feedback.py:29,191` |
| `atomic_io` + `data_integrity` | Safe writes for policy decision log | `src/janus/integrations/data_integrity.py` |
| `janus_sync` plugin hook pattern | Lifecycle-gated enforcement | `plugins/janus_sync/__init__.py:197,198` |
| `TaskAgency`, `ExecutionMode`, `SupportMode` | Phase D classification inputs | `src/janus/models/task_agency.py`, `execution_mode.py`, `support_mode.py` |
| CLI prompt pattern | Approval channel (P1 Phase 4) | Existing CLI commands in `src/janus/cli/` |

---

## 10. Acceptance Criteria Coverage (consolidated)

### P1 criteria (17 total, all addressed in P1 design)
- AC-PR-1..5 (policy rules): §4 of P1 design
- AC-AG-1..5 (approval gates): §5 of P1 design
- AC-AW-1..4 (approval workflow): §5 of P1 design
- AC-SB-1..3 (scope boundaries): §2.3 of P1 design + §8 of this document

### P2 criteria (30 total, all addressed in P2 design)
- AC2.1.1..4 (action-type taxonomy): §3.1 of P2 design
- AC2.2.1..5 (configurable policy rules): §3.2 of P2 design
- AC2.3.1..4 (approval-request model): §3.3 of P2 design
- AC2.4.1..4 (deferred/escalated): §3.4 of P2 design
- AC2.5.1..5 (policy decision recording): §3.5 of P2 design
- AC2.6.1..4 (policy versioning): §3.6 of P2 design
- AC2.7.1..4 (bulk classification): §3.7 of P2 design

### Combined criteria (new, from synthesis)
- AC-COMB-1: P1↔P2 interface contract (§6 of this document) is implemented and tested
- AC-COMB-2: P1's `evaluate_policy()` delegates to P2's `PolicyEngine` after P2 lands (OQ-COMBO-2)
- AC-COMB-3: P2's `ApprovalRequest` model is the single source of truth (OQ-COMBO-1)
- AC-COMB-4: Policy decision log records both P1 verdicts and P2 approval outcomes with policy_version (OQ-COMBO-3)

---

## 11. Handoff for Implementer Phase (t_16d8884f)

### 11.1 What the implementer gets

1. **P1 requirements spec** — 16 policy rules, 7 gates, approval workflow, 17 ACs
2. **P2 requirements spec** — 7 requirement areas, 30 ACs, action taxonomy, configurable rules, ApprovalRequest model, deferred/escalated approvals, policy decision recording, versioning, bulk classification
3. **P1 design doc** — data models, rule table, gate table, Phase D integration, CLI integration, 5 implementation phases, edge cases, failure modes, testing strategy
4. **P2 design doc** — architecture diagram, 7 component designs, P1 integration points, file/directory layout, 5 implementation phases, configuration reference, testing strategy, AC mapping
5. **Discovery findings** — 10 existing components, 10 gaps, 10 reusable components, recommendations
6. **This synthesized plan** — combined implementation order, dependency graph, interface contract, consolidated open questions

### 11.2 What the implementer must resolve before coding

1. **OQ-COMBO-1:** Which `ApprovalRequest` model is authoritative? (Recommendation: P2's)
2. **OQ-COMBO-2:** Does P1's `evaluate_policy()` delegate to P2's `PolicyEngine`? (Recommendation: yes, after P2 lands)
3. **OQ-COMBO-3:** Relationship between P1's `PolicyDecision` and P2's log record
4. **OQ-COMBO-6:** Mechanism for timeout/escalation detection (defer to later phase if no scheduler exists)
5. **OQ-COMBO-7:** Whether frontmatter parsing exists for goal/project files

### 11.3 Implementation sequence (implementer's checklist)

1. Resolve OQ-COMBO-1, OQ-COMBO-2, OQ-COMBO-3 (design decisions, document in ADR or design doc update)
2. Combined Phase 1: P1 data models + P2 data models + taxonomy (parallelizable)
3. Combined Phase 2: P2 PolicyEngine + rules YAML → P1 goal gates (G-2)
4. Combined Phase 3: P2 ApprovalHandler + PolicyDecisionLog → P1 G-4/G-6/G-7
5. Combined Phase 4: P1 CLI prompt + P2 versioning (parallelizable)
6. Combined Phase 5: Integration tests + edge cases + failure modes

### 11.4 What NOT to implement

- No new blocking gates beyond G-1 to G-7
- No full rules engine
- No approval channel implementation (CLI prompt is P1 Phase 4; Telegram/review adapters are separate)
- No auto-approval
- No retroactive re-evaluation
- No queryable database
- No governance dashboard
- No evidence model (ADR-012)
- No mode-specific permissions (P3)

### 11.5 Test strategy (consolidated)

- **P1:** Unit tests for all 16 rules, precedence, edge cases (§8), failure modes (§9). Integration tests for full approval flow (CLI prompt → approve/deny/defer → gate proceeds/blocks).
- **P2:** Unit tests per component (`test_policy_engine.py`, `test_approval_request.py`, `test_approval_handler.py`, `test_policy_decision_log.py`, `test_bulk_classifier.py`, `test_action_type.py`). Integration tests for P1 gate → PolicyEngine → ApprovalRequest flow, bulk → classifier flow, timeout → deferred, escalation → re-routed.
- **Existing infrastructure:** Reuse `CompletionGateResult` + `CompletionGateError` pattern for new gates. Reuse `atomic_io` for policy decision log writes.

---

## 12. Status of Input Artifacts

| Artifact | Task | Status | PR | CI |
|---|---|---|---|---|
| P1 requirements spec | t_58f3186c | Complete | — (design-only task, integration_required=false) | n/a |
| P2 requirements spec | t_23d33a79 | Complete | — (design-only task, integration_required=false) | n/a |
| Infrastructure findings | t_bb8e173d | Complete | — (design-only task, integration_required=false) | n/a |
| P1 design doc | t_4a3bc8f3 | Complete, merged | #293 | 2/2 verify pass |
| P2 design doc | t_f0a8da14 | Complete, merged | #294 | pass |
| Phase E plan (this doc) | t_8660a159 | **This task** | pending | pending |
| Implementer phase | t_16d8884f | todo (waiting on this task) | — | — |

---

## 13. Remaining Cross-Cutting Concerns

1. **ADR-011 implementation:** P1 Phase 2 is de facto the ADR-011 implementation. If ADR-011 has its own task or decision record, coordinate with that task owner.
2. **Dormant janus_sync plugin:** The plugin is code-complete but not loaded. P1 gates work without it (gates run in `complete_task()`), but the auto-invoke on task claim is inactive. This is an operational concern, not a P1 implementation blocker.
3. **Contracts/ directory:** The verification pipeline supports `contracts/<branch>.yaml` with `completion_gates` field, but it's unused and the `completion_gates` field is not wired. P1's new gates could use this mechanism, but wiring it is a separate concern.
4. **Telegram approval channel:** P1 Phase 4 implements CLI prompt. Telegram notification of pending approvals is a Phase E integration concern (uses existing `dispatch_completion()` Telegram path). Not blocking for P1/P2 core.
5. **Policy decision log rotation:** P2 specifies JSONL in `data/policy_decisions/YYYY-MM-DD.jsonl`. Rotation policy (file size limits, retention) is an implementation detail not specified in requirements. Implementer should choose a simple default (e.g., one file per day, no automatic rotation) and document it.

---

*End of Phase E plan.*

*Next step: implementer phase (t_16d8884f) picks up this plan, resolves open questions OQ-COMBO-1 through OQ-COMBO-7, and begins Combined Phase 1 implementation.*
