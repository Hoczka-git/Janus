# P1 Policy Enforcement & Approval Workflow — Design

**Status:** Design (ready for implementation handoff)
**Date:** 2026-09-30
**Scope:** P1-tier policy rules and approval gates only
**Requirements spec:** `docs/specs/p1-policy-approval-requirements.md`
**Task:** t_4a3bc8f3
**Decomposition parent:** t_16d8884f (Phase E plan)
**Requirements spec:** t_58f3186c (docs/specs/p1-policy-approval-requirements.md)

---

## 1. Purpose

This document converts the P1 requirements spec into an implementable design: data models, workflow states, integration points, new components, edge cases, and failure modes. It is the bridge between the requirements (the "what") and implementation (the "how").

**Non-goals:** P2 items (configurable policy engine, audit trail, policy decision entity, multi-step workflow state machine beyond curation gate) are explicitly out of scope. See requirements spec §2.3.

---

## 2. Design Principles

1. **Reuse over reinvent.** P1 policy rules reference existing enforcement points (ADR-004 gates, curation gate, state transition rules). The policy layer orchestrates; it does not replace.
2. **Service-function boundary.** Policy evaluation happens at the service function entry point, before any state-changing operation. This matches the triage doc §7.6 boundary.
3. **Most restrictive verdict wins.** When multiple rules match, DENY > ASK > ALLOW.
4. **Advisory escalation at P1.** Escalation paths follow the existing `ESCALATION_POLICY` pattern but are not enforced by a downstream gate.
5. **No new persistence at P1.** Approval decisions are recorded where existing infrastructure supports it (CurationProposal, task completion metadata, execution log). The structured "policy decision" entity is P2.

---

## 3. Data Models

### 3.1 PolicyVerdict (enum)

```python
class PolicyVerdict(StrEnum):
    ALLOW = "allow"   # proceed without additional approval
    ASK = "ask"       # requires explicit user approval
    DENY = "deny"     # blocked; cannot proceed even with approval
```

**Location:** `src/janus/models/policy.py` (new module)

### 3.2 RiskLevel (enum)

```python
class RiskLevel(StrEnum):
    LOW = "low"       # metric update, task status change, log entry
    MEDIUM = "medium" # goal status change, milestone completion
    HIGH = "high"     # goal deletion, bulk state changes, external writes
```

**Location:** `src/janus/models/policy.py`

### 3.3 PolicyRule (dataclass)

A single policy rule mapping an action + context to a verdict.

```python
@dataclass(frozen=True)
class PolicyRule:
    rule_id: str                          # "R1", "R2", ...
    action: str                           # action class (e.g., "task_execution")
    context: str                          # context filter (e.g., "execution_mode=USER")
    risk_level: RiskLevel                 # risk if this rule matches
    verdict: PolicyVerdict                # ALLOW, ASK, or DENY
    rationale: str                        # human-readable why
    enforcement_point: str                # file:line or service:function reference
    gate_id: str | None = None            # associated gate (G-1..G-7) if ASK/DENY
```

**Location:** `src/janus/models/policy.py`

### 3.4 PolicyDecision (dataclass)

The result of evaluating a policy rule against an action.

```python
@dataclass
class PolicyDecision:
    rule_id: str                          # which rule produced this verdict
    verdict: PolicyVerdict                # ALLOW, ASK, or DENY
    risk_level: RiskLevel                 # risk level of the matched rule
    rationale: str                        # why this verdict was reached
    gate_id: str | None = None            # gate to invoke if ASK
    enforcement_point: str = ""           # where to enforce
```

**Location:** `src/janus/models/policy.py`

### 3.5 ApprovalRequest (dataclass)

The structured approval request presented to the user when a gate returns ASK.

```python
@dataclass
class ApprovalRequest:
    action: str                           # what is being attempted
    context: str                          # what entities are affected
    risk_level: RiskLevel                 # low / medium / high
    policy_rule: str                      # which rule produced this (e.g., "R6")
    rationale: str                        # why approval is needed
    what_approval_entails: str            # what the user is approving
    alternative: str                      # what happens if denied
    gate_id: str | None = None            # associated gate
```

**Location:** `src/janus/models/policy.py`

### 3.6 ApprovalResponse (enum)

```python
class ApprovalResponse(StrEnum):
    APPROVE = "approve"
    DENY = "deny"
    DEFER = "defer"    # P1: defer = cancel for now
```

**Location:** `src/janus/models/policy.py`

### 3.7 ApprovalRecord (dataclass)

Recorded after a user responds to an approval request. At P1, this is ephemeral (returned to caller, logged). Persistent recording is P2.

```python
@dataclass
class ApprovalRecord:
    request: ApprovalRequest              # the original request
    response: ApprovalResponse            # user's decision
    decided_at: datetime                  # when the decision was made
    decided_by: str = "user"              # who decided (always "user" at P1)
```

**Location:** `src/janus/models/policy.py`

---

## 4. Policy Rule Table (P1)

The 16 rules from the requirements spec §3.2, expressed as data. Rules are evaluated in order; first match wins. On overlap, most restrictive verdict wins (DENY > ASK > ALLOW).

| Rule | Action | Context | Risk | Verdict | Enforcement Point | Gate |
|------|--------|---------|------|---------|-------------------|------|
| R1 | Task execution (user-mode) | execution_mode=USER, support_mode!=EXECUTE | low | ALLOW | Normal task lifecycle | — |
| R2 | Task execution (Janus-mode) | execution_mode=JANUS, support_mode=EXECUTE | low | ALLOW | ADR-004 gates if git repo | — |
| R3 | Task execution (collaborative) | execution_mode=COLLABORATIVE | medium | ASK | User must have claimed task | — |
| R4 | Janus assistive (explain/coach/scaffold) | support_mode in {EXPLAIN,COACH,SCAFFOLD} | low | ALLOW | No state change | — |
| R5 | Janus review of user work | support_mode=REVIEW | medium | ASK | Task must be in reviewable state | — |
| R6 | Goal completion | any goal | medium | ASK | ADR-011 structural gates | G-2 |
| R7 | Knowledge artifact promotion | curation_proposal.approval_state != approved | medium | ASK | `curation_gate.promote_to_vault()` | G-3 |
| R8 | External system read | any external read | low | ALLOW | No state change | — |
| R9 | External system write (state-changing) | calendar write, file write outside data/, API mutation | high | ASK | Service returns prompt → CLI | G-4 |
| R10 | Goal deletion | any goal | high | DENY (via ASK + confirmation) | CLI confirms before `set_goal_state` | G-5 |
| R11 | Bulk state changes | multiple goals/tasks in one operation | high | ASK | CLI lists affected entities | G-6 |
| R12 | Policy-relevant config change | policy keywords, risk levels, mode thresholds | high | ASK | CLI confirms before config write | G-7 |
| R13 | Task status change (routine) | todo→in_progress, in_progress→blocked | low | ALLOW | `personal_state.py` transition rules | — |
| R14 | Task completion (git repo) | task in git repo, via `complete_task()` | medium | ASK | ADR-004 Phase 3+5 gates | G-1 |
| R15 | Task completion (non-git) | task not in git repo | low | ALLOW | Normal markdown flip | — |
| R16 | Evidence-less goal completion | goal completed with no evidence records | high | DENY | ADR-011 structural gates (enforced when ADR-012 in place) | G-2 |

### 4.1 Rule precedence

```
DENY > ASK > ALLOW
```

When multiple rules match an action, the most restrictive verdict wins. Example: a collaborative-mode task execution (R3, ASK) that is also a high-risk external write (R9, ASK) — both are ASK, so the action requires approval. A collaborative task that also involves goal deletion (R10, DENY) — DENY wins.

### 4.2 Rule encoding

At P1, rules are encoded as code (a list of `PolicyRule` instances in a registry), not as YAML/config. This matches the existing pattern of hardcoded reason codes, transition tables, and whitelists. Phase E (P2) extracts to a configurable layer.

**Location:** `src/janus/services/policy.py` — `POLICY_RULES: list[PolicyRule]`

---

## 5. Approval Gates

### 5.1 Gate types

| Gate type | Meaning | Example |
|-----------|---------|---------|
| Mechanical | Deterministic check that passes/fails with reason code | ADR-004 Phase 3 checks |
| Human | Requires explicit user approval via CLI prompt | External write confirmation |

### 5.2 P1 gates

| Gate | Action gated | Type | Enforcement point | Approver | Channel |
|------|-------------|------|-------------------|----------|---------|
| G-1 | Task completion (git repo) | Mechanical + Human (if Phase 5 review) | `services/tasks.py:run_completion_gates()` → `complete_task()` | User (Kanban review or CLI) | Kanban review / CLI |
| G-2 | Goal completion | Mechanical (structural) + Human (high-stakes) | `services/goals.py:run_goal_completion_gates()` (ADR-011) | User | CLI `janus goal complete` |
| G-3 | Knowledge artifact promotion | Human | `curation_gate.promote_to_vault()` → `CurationGateError` | User (curator) | CLI `janus research approve` |
| G-4 | External system state-changing write | Human | Service function returns prompt → CLI | User | CLI prompt |
| G-5 | Goal deletion | Human | CLI confirms before `set_goal_state(goal, "deleted")` | User | CLI `janus goal delete` |
| G-6 | Bulk state change | Human | CLI lists affected entities, user confirms | User | CLI prompt |
| G-7 | Policy-relevant config change | Human | CLI confirms before config write | User | CLI prompt |

### 5.3 Gate state machine (human-approval gates)

For human-approval gates (G-2 through G-7), the workflow follows this state machine:

```
                    ┌──────────────────────────────────────┐
                    │                                      │
                    ▼                                      │
    ┌──────────┐  detect   ┌──────────┐  evaluate   ┌──────────┐
    │  IDLE    │ ────────► │ PENDING  │ ──────────► │ PRESENTED│
    └──────────┘           └──────────┘             └──────────┘
                                                        │
                                         ┌──────────────┼──────────────┐
                                         │              │              │
                                         ▼              ▼              ▼
                                   ┌──────────┐  ┌──────────┐  ┌──────────┐
                                   │ APPROVED │  │  DENIED  │  │ DEFERRED │
                                   └──────────┘  └──────────┘  └──────────┘
                                         │              │              │
                                         ▼              ▼              ▼
                                   ┌──────────┐  ┌──────────┐  ┌──────────┐
                                   │ EXECUTED │  │ BLOCKED  │  │CANCELLED │
                                   └──────────┘  └──────────┘  └──────────┘
```

**States:**

| State | Meaning | Transitions |
|-------|---------|-------------|
| IDLE | No gate active | → PENDING (on detect) |
| PENDING | Gate triggered, evaluating policy | → PRESENTED (on ASK verdict) |
| PRESENTED | Approval request shown to user | → APPROVED / DENIED / DEFERRED |
| APPROVED | User approved | → EXECUTED (action proceeds) |
| DENIED | User denied | → BLOCKED (action blocked, reason recorded) |
| DEFERRED | User deferred | → CANCELLED (P1: defer = cancel for now) |
| EXECUTED | Action completed after approval | terminal |
| BLOCKED | Action blocked after denial | terminal |
| CANCELLED | Action cancelled after deferral | terminal |

### 5.4 Gate state machine (mechanical gates)

For mechanical gates (G-1, G-2 structural checks), the workflow is simpler:

```
    ┌──────────┐  run checks  ┌──────────┐
    │  IDLE    │ ───────────► │ CHECKING │
    └──────────┘              └──────────┘
                                    │
                         ┌──────────┼──────────┐
                         │                     │
                         ▼                     ▼
                   ┌──────────┐         ┌──────────┐
                   │  PASSED  │         │  FAILED  │
                   └──────────┘         └──────────┘
                         │                     │
                         ▼                     ▼
                   ┌──────────┐         ┌──────────┐
                   │ EXECUTED │         │ BLOCKED  │
                   └──────────┘         └──────────┘
                                              │
                                              ▼
                                       (route to human
                                        via kanban_block)
```

---

## 6. Integration Points

### 6.1 Service-function entry points

The policy layer hooks into existing service functions at their entry points. The pattern is:

```python
def some_service_function(...):
    # 1. Evaluate policy
    decision = evaluate_policy(action, context, risk_level)
    
    # 2. Handle verdict
    if decision.verdict == PolicyVerdict.DENY:
        raise PolicyDenialError(decision.rationale)
    elif decision.verdict == PolicyVerdict.ASK:
        request = build_approval_request(decision, ...)
        response = present_approval_request(request)  # CLI prompt
        if response != ApprovalResponse.APPROVE:
            return  # blocked or deferred
    
    # 3. Proceed with original operation
    ...
```

### 6.2 Integration map

| Service function | Policy rule(s) | Gate | Integration type |
|-----------------|---------------|------|-----------------|
| `tasks.py:complete_task()` | R14, R15 | G-1 | Already integrated (ADR-004). Policy layer adds verdict evaluation before gate run. |
| `goals.py:complete_goal()` | R6, R16 | G-2 | New: add `run_goal_completion_gates()` call before state change (ADR-011). |
| `goals.py:set_goal_state(goal, "deleted")` | R10 | G-5 | New: add CLI confirmation before deletion. |
| `curation_gate.py:promote_to_vault()` | R7 | G-3 | Already integrated. Policy layer references existing `CurationGateError`. |
| External write services (calendar, file write) | R9 | G-4 | New: service returns approval prompt, CLI presents. |
| Bulk operation services | R11 | G-6 | New: CLI lists affected entities, user confirms. |
| Config change services | R12 | G-7 | New: CLI confirms before config write. |
| `personal_state.py` transitions | R13 | — | Already integrated. Policy layer references existing transition rules. |

### 6.3 Phase D integration

P1 policy rules consume Phase D outputs:

| Phase D output | Type | Used by |
|---------------|------|---------|
| `ExecutionMode` | `USER \| JANUS \| COLLABORATIVE` | R1, R2, R3 |
| `SupportMode` | `EXPLAIN \| COACH \| SCAFFOLD \| REVIEW \| EXECUTE` | R4, R5 |
| `TaskAgency` | dataclass (mode, support, reason, confidence) | All task-execution rules |
| `AgencyContext` | dataclass (skill_evidence_count, goal_health, ...) | Context for policy evaluation |

The policy layer calls `classify_task()` to get the `TaskAgency` for a task, then uses `execution_mode` and `support_mode` to match against policy rules.

### 6.4 CLI integration

The CLI is the primary approval channel at P1. The pattern:

1. Service function detects gate trigger and returns an `ApprovalRequest`.
2. CLI receives the request and presents it to the user (formatted prompt).
3. User responds: approve, deny, or defer.
4. CLI passes the response back to the service function.
5. Service function proceeds or blocks based on the response.

**CLI commands affected:**
- `janus task complete` — already has ADR-004 gate integration
- `janus goal complete` — new: add G-2 gate
- `janus goal delete` — new: add G-5 gate
- `janus research approve` — already has curation gate integration
- External write commands — new: add G-4 gate
- Bulk operation commands — new: add G-6 gate
- Config change commands — new: add G-7 gate

---

## 7. New Components

### 7.1 `src/janus/models/policy.py` (new module)

Contains all policy data models:
- `PolicyVerdict` (enum)
- `RiskLevel` (enum)
- `PolicyRule` (dataclass)
- `PolicyDecision` (dataclass)
- `ApprovalRequest` (dataclass)
- `ApprovalResponse` (enum)
- `ApprovalRecord` (dataclass)

### 7.2 `src/janus/services/policy.py` (new module)

Contains the policy evaluation engine:
- `POLICY_RULES: list[PolicyRule]` — the 16 P1 rules as data
- `evaluate_policy(action, context, risk_level, task_agency=None) -> PolicyDecision` — evaluates rules against an action, returns the most restrictive verdict
- `build_approval_request(decision, action, context) -> ApprovalRequest` — constructs the approval request from a policy decision
- `present_approval_request(request) -> ApprovalResponse` — presents the request to the user via CLI and returns their response
- `record_approval(approval_record) -> None` — logs the approval decision (P1: execution log only)

### 7.3 `src/janus/services/goal_gates.py` (new module)

Contains goal-level completion gates (ADR-011):
- `run_goal_completion_gates(goal) -> GoalCompletionGateResult` — runs structural gates (completed child tasks, metrics at target)
- `GoalCompletionGateResult` — dataclass with `ok`, `blocked_reason`, `blocked_message`
- `GoalCompletionGateError` — raised when gates block completion

### 7.4 `src/janus/exceptions.py` (extend)

Add policy-specific exceptions:
- `PolicyDenialError` — raised when a DENY verdict is returned
- `PolicyApprovalRequired` — raised when an ASK verdict requires approval (service function returns this to trigger CLI prompt)

### 7.5 CLI approval prompt formatter (new)

A utility function that formats an `ApprovalRequest` into a human-readable CLI prompt:

```python
def format_approval_prompt(request: ApprovalRequest) -> str:
    """Format an approval request as a CLI prompt."""
    ...
```

**Location:** `src/janus/cli/approval.py` (new module) or inline in existing CLI modules.

---

## 8. Edge Cases

### 8.1 Rule overlap

When multiple rules match an action, the most restrictive verdict wins (DENY > ASK > ALLOW). The `evaluate_policy()` function must collect all matching rules and return the most restrictive.

**Example:** A collaborative-mode task execution (R3, ASK) that is also a high-risk external write (R9, ASK) — both are ASK, so the action requires approval. A collaborative task that also involves goal deletion (R10, DENY) — DENY wins.

### 8.2 Missing Phase D classification

If `classify_task()` cannot produce a `TaskAgency` (e.g., task has no goal context), the policy layer falls back to a conservative default: treat as MEDIUM risk, ASK verdict. This ensures that unknown actions are not automatically allowed.

### 8.3 Concurrent approval requests

If two approval requests are triggered simultaneously (e.g., two CLI commands in parallel), each is independent. At P1, there is no global approval queue. The CLI processes one at a time.

### 8.4 Gate failure after approval

If a user approves an action but the mechanical gate then fails (e.g., tests fail after user approves task completion), the action is blocked. The approval is consumed. The user must address the gate failure and re-trigger the approval.

### 8.5 Policy rule change while approval pending

If a policy rule changes while an approval request is pending (e.g., user modifies config that affects rule evaluation), the pending request is evaluated against the new rules. At P1, this is an edge case — the user would need to re-trigger the action.

### 8.6 Circular dependency: policy rule change requires policy approval

If a user attempts to change a policy rule (R12, G-7), the change itself requires approval. This is not circular — the approval is for the config change, not for the policy evaluation. The policy evaluation of the config change request uses the current (pre-change) rules.

### 8.7 Empty rule set

If no rules match an action (should not happen with the P1 rule table covering all in-scope actions), the default is DENY. This is a safety fallback.

### 8.8 Task in git repo but no ADR-004 gates applicable

If a task is in a git repo but ADR-004 gates are not applicable (e.g., no tests, no diff), the gate passes trivially. The policy layer still evaluates the rule (R14, ASK) but the gate run is a no-op.

---

## 9. Failure Modes

### 9.1 Policy evaluation failure

**What:** `evaluate_policy()` raises an unexpected exception (e.g., malformed rule data).
**Handling:** Catch the exception, log it, and return a DENY verdict with rationale "Policy evaluation error: {error}". This fails safe — the action is blocked.

### 9.2 Approval prompt failure

**What:** The CLI cannot present the approval prompt (e.g., terminal error, invalid input).
**Handling:** The service function catches the presentation error and returns a DENY verdict. The user can retry.

### 9.3 Gate timeout

**What:** A mechanical gate takes too long to run (e.g., test suite hangs).
**Handling:** At P1, there is no timeout mechanism. The gate runs to completion. Future: add a timeout parameter to gate functions.

### 9.4 Approval response invalid

**What:** The user provides an invalid response (not approve/deny/defer).
**Handling:** The CLI re-prompts until a valid response is received or the user cancels (Ctrl+C). Cancel = defer.

### 9.5 State change after approval but before execution

**What:** Between approval and execution, the state changes (e.g., another process modifies the goal).
**Handling:** At P1, there is no locking mechanism. The service function re-evaluates the gate at execution time. If the gate now fails, the action is blocked. Future: add optimistic locking.

### 9.6 Curation gate already approved

**What:** A curation proposal is already in `approved` state when `promote_to_vault()` is called.
**Handling:** The existing `CurationGateError` is raised. The policy layer does not re-evaluate — the existing enforcement is sufficient.

### 9.7 Goal deletion with active child tasks

**What:** User attempts to delete a goal that has active child tasks.
**Handling:** The gate blocks with reason "Goal has active child tasks. Resolve tasks first." The user must complete or reassign tasks before deletion.

---

## 10. Implementation Phases

### Phase 1: Data models + policy engine (no integration)

1. Create `src/janus/models/policy.py` with all data models.
2. Create `src/janus/services/policy.py` with `POLICY_RULES` and `evaluate_policy()`.
3. Write unit tests for policy evaluation (all 16 rules, precedence, edge cases).
4. **No integration with existing services yet.**

### Phase 2: Goal completion gates (ADR-011)

1. Create `src/janus/services/goal_gates.py` with `run_goal_completion_gates()`.
2. Integrate into `goals.py:complete_goal()`.
3. Write unit tests for goal completion gates.
4. Wire G-2 into the approval workflow.

### Phase 3: External write + bulk + config gates

1. Add G-4 (external write) integration to relevant service functions.
2. Add G-6 (bulk operation) integration.
3. Add G-7 (config change) integration.
4. Write unit tests for each gate.

### Phase 4: CLI approval prompt

1. Create the approval prompt formatter.
2. Integrate into CLI commands.
3. Write integration tests for the full approval flow.

### Phase 5: Edge cases + failure modes

1. Add error handling for all failure modes (§9).
2. Add logging for policy decisions.
3. Write tests for edge cases (§8).

---

## 11. Testing Strategy

### 11.1 Unit tests

- `tests/test_policy_models.py` — data model construction and validation
- `tests/test_policy_engine.py` — `evaluate_policy()` for all 16 rules, precedence, edge cases
- `tests/test_goal_gates.py` — `run_goal_completion_gates()` structural checks
- `tests/test_approval_workflow.py` — approval request/response flow

### 11.2 Integration tests

- `tests/test_policy_integration.py` — policy evaluation integrated with service functions
- `tests/test_approval_cli.py` — full approval flow via CLI

### 11.3 Test coverage targets

- All 16 policy rules: at least one test per rule
- Rule precedence: at least 3 overlap scenarios
- Edge cases (§8): all 8 scenarios
- Failure modes (§9): all 7 scenarios

---

## 12. File Inventory

### New files

| File | Purpose |
|------|---------|
| `src/janus/models/policy.py` | Policy data models |
| `src/janus/services/policy.py` | Policy evaluation engine |
| `src/janus/services/goal_gates.py` | Goal completion gates (ADR-011) |
| `src/janus/cli/approval.py` | CLI approval prompt formatter |
| `tests/test_policy_models.py` | Policy model unit tests |
| `tests/test_policy_engine.py` | Policy engine unit tests |
| `tests/test_goal_gates.py` | Goal gates unit tests |
| `tests/test_approval_workflow.py` | Approval workflow tests |
| `tests/test_policy_integration.py` | Policy integration tests |

### Modified files

| File | Change |
|------|--------|
| `src/janus/services/goals.py` | Add `run_goal_completion_gates()` call in `complete_goal()` |
| `src/janus/services/tasks.py` | Add policy verdict evaluation before ADR-004 gates |
| `src/janus/exceptions.py` | Add `PolicyDenialError`, `PolicyApprovalRequired` |
| `src/janus/cli/goal_cli.py` | Add G-5 (goal deletion) approval prompt |
| `src/janus/cli/task_cli.py` | Add G-4 (external write) approval prompt |

---

## 13. Dependencies

### 13.1 Existing components reused

| Component | Used for | File reference |
|-----------|---------|----------------|
| ADR-004 completion gates | Task completion gating (G-1) | `src/janus/services/tasks.py:run_completion_gates()` |
| Curation gate | Curation approval (G-3) | `src/janus/services/curation_gate.py:promote_to_vault()` |
| State transition rules | Routine task status changes (R13) | `src/janus/models/personal_state.py` |
| Kanban review lane (ADR-003) | Task review approval channel | Hermes kanban plugin |
| `ESCALATION_POLICY` | Advisory escalation routing | `src/janus/services/remediation.py:67` |
| `CompletionGateResult` + `CompletionGateError` | Gate failure reason codes | `src/janus/services/tasks.py:48-88` |
| `TaskAgency`, `ExecutionMode`, `SupportMode` | Phase D classification inputs | `src/janus/models/task_agency.py`, `execution_mode.py`, `support_mode.py` |
| `AgencyContext` | Policy evaluation context | `src/janus/services/agency_planning.py:36` |

### 13.2 Downstream consumers

| Consumer | Relationship |
|----------|-------------|
| Phase E (P2) configurable policy engine | P1 rules define the semantic content; P2 extracts to YAML |
| ADR-011 (goal completion gates) | P1 gate G-2 references ADR-011 as enforcement mechanism |
| ADR-012 (evidence model) | P1 rule R16 records policy intent; enforced when ADR-012 in place |
| Phase G (self-extending skills) | Generated skills subject to P1 policy rules |

---

## 14. Open Questions (from requirements spec)

| # | Question | P1 stance |
|---|----------|-----------|
| O1 | Rules as data or code? | Code for now (matches existing pattern). P2 extracts to config. |
| O2 | Threshold for "high-stakes goal"? | Not defined at P1. All goal completions require structural gates. |
| O3 | Collaborative-mode: user claim required? | Yes. If unclaimed, route to ASK. |
| O4 | External write approval via Telegram? | P1: CLI only. Telegram is Phase E. |
| O5 | G-2 require evidence at P1? | Structural checks only. Evidence requirement is ADR-012. |

---

## 15. Acceptance Criteria Mapping

| AC ID | Criterion | Design coverage |
|-------|-----------|-----------------|
| AC-PR-1 | Rule table covers all in-scope action categories | §4 rule table (16 rules) |
| AC-PR-2 | Rules reference existing infrastructure | §4 enforcement_point column |
| AC-PR-3 | Risk levels consistent with minimal model | §3.2 RiskLevel enum |
| AC-PR-4 | Most restrictive verdict wins | §4.1 precedence rule |
| AC-PR-5 | Consistent with Agency-First principles | §2 design principles |
| AC-AG-1 | All ASK/DENY rules have a gate | §5.2 gate table |
| AC-AG-2 | Gate types correctly classified | §5.1 gate types |
| AC-AG-3 | Approver and channel defined | §5.2 approver column |
| AC-AG-4 | Existing workflows reused | §6.2 integration map |
| AC-AG-5 | Escalation paths defined | Requirements spec §4.4 (advisory) |
| AC-AW-1 | Approval request format defined | §3.5 ApprovalRequest |
| AC-AW-2 | Approval flow defined | §5.3 state machine |
| AC-AW-3 | Approval recording defined | §3.7 ApprovalRecord (P1: ephemeral) |
| AC-AW-4 | Denial and deferral paths defined | §5.3 DENIED/DEFERRED states |
| AC-SB-1 | Narrowly scoped to P1 | §1 non-goals |
| AC-SB-2 | Does not redefine existing infrastructure | §13.1 reuse table |
| AC-SB-3 | Consistent with Phase D output | §6.3 Phase D integration |

---

*End of design document.*
