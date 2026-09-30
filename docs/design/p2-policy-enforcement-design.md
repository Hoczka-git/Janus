# P2 Policy Enforcement and Approval Workflow — Design

**Status:** Design document — ready for implementation handoff
**Date:** 2026-09-30
**Task:** t_f0a8da14
**Parent requirements:** `docs/specs/p2-policy-approval-requirements.md` (t_23d33a79)
**P1 requirements:** `docs/specs/p1-policy-approval-requirements.md` (t_58f3186c)
**Infrastructure findings:** `docs/research/t_bb8e173d-policy-approval-infrastructure-findings.md` (t_bb8e173d)

---

## 1. Purpose

This document translates the P2 requirements spec into a concrete design ready for implementation. P2 is the **substrate tier** of Phase E policy and approval — it provides the classification, configuration, deferral, recording, and lifecycle infrastructure that P1's enforcement gates consume. P2 does not add new blocking gates; it makes P1's gates configurable, auditable, and deferrable.

### Design goals

1. **Data-driven, not code-driven.** Policy rules, action taxonomy, and thresholds are data files. Changing policy does not require a code deploy.
2. **Channel-agnostic.** The approval model holds state; channels (CLI, Telegram, review lane) are adapters that write transitions.
3. **Defer, don't block forever.** Timeout → deferred (not auto-approved). Escalation re-routes to a different channel. Neither auto-approves.
4. **Auditable.** Every policy decision is recorded with policy version, verdict, and context.
5. **Minimal surface.** No full rules engine, no event sourcing, no query API. A log, a loader, a model.

### Non-goals (explicit)

- No new blocking gates (P1 owns enforcement)
- No full rules engine (no condition expressions, chaining, negation)
- No approval channel implementation (CLI/Telegram/review adapters are separate work)
- No auto-approval on timeout or escalation
- No retroactive re-evaluation of past decisions
- No queryable database for policy decisions

---

## 2. Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│  P1 Enforcement Layer (gates, blocking, human approval)      │
│  - ADR-004 completion gates (task completion)                │
│  - ADR-011 goal completion gates (proposed)                  │
│  - Curation gate (knowledge promotion)                      │
│  - Review lane (Kanban Model A)                             │
│  - G-1 through G-7 (P1 spec §4.2)                           │
└──────────────────────────┬──────────────────────────────────┘
                           │ consults
                           ▼
┌─────────────────────────────────────────────────────────────┐
│  P2 Substrate Layer (this design)                           │
│                                                             │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐  │
│  │ Action       │  │ Policy       │  │ ApprovalRequest  │  │
│  │ Taxonomy     │  │ Rule Set     │  │ Model            │  │
│  │ (YAML)       │  │ (YAML)       │  │ (Python + JSONL) │  │
│  └──────┬───────┘  └──────┬───────┘  └────────┬─────────┘  │
│         │                 │                    │            │
│         └────────┬────────┘                    │            │
│                  ▼                             │            │
│         ┌────────────────┐                     │            │
│         │ Policy Engine  │────────────────────►│            │
│         │ (loader +      │  produces requests  │            │
│         │  evaluator)    │                     │            │
│         └────────┬───────┘                     │            │
│                  │                             │            │
│         ┌────────┴───────┐          ┌──────────┴─────────┐  │
│         │ Bulk           │          │ Deferred/Escalated │  │
│         │ Classifier     │          │ Approval Handler   │  │
│         └────────────────┘          └────────────────────┘  │
│                                                             │
│  ┌──────────────────────────────────────────────────────┐   │
│  │ Policy Decision Log (JSONL)                          │   │
│  │ data/policy_decisions/YYYY-MM-DD.jsonl               │   │
│  └──────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

### Dependency direction

P1 → P2 (one-way). P1 gates consult P2's classification and rule set to determine whether to block, ask, or allow. P2 does not call P1's gates. P2's deferred/escalated approvals are the "lighter controls" — P1 requires explicit confirmation for high-risk; P2 says "if the user doesn't respond, defer and escalate rather than block forever or auto-approve."

---

## 3. Component Designs

### 3.1 Action-Type Taxonomy (P2-1)

**File:** `src/janus/models/action_type.py` — Python enum (single source of truth for the taxonomy itself)

**Data file:** `config/policy/action_taxonomy.yaml` — default risk mapping, overridable per goal/project

#### 3.1.1 ActionType enum

```python
class ActionType(StrEnum):
    STATE_CHANGE = "state_change"
    DATA_WRITE = "data_write"
    EXTERNAL_CALL = "external_call"
    EXTERNAL_WRITE = "external_write"
    BULK_OPERATION = "bulk_operation"
    DELETION = "deletion"
    CONFIGURATION_CHANGE = "configuration_change"
    KNOWLEDGE_PROMOTION = "knowledge_promotion"
```

#### 3.1.2 Default risk mapping (YAML)

```yaml
# config/policy/action_taxonomy.yaml
version: "1.0.0"
action_types:
  state_change:
    description: "Goal/task/followup/milestone/project status change"
    default_risk: medium
    overrides:
      task_status: low        # task status changes are low-risk
      goal_status: medium     # goal status changes are medium-risk
      milestone_completion: medium

  data_write:
    description: "Write to a Janus data file (goal, task, decision, followup, inbox, workout, measurement)"
    default_risk: low

  external_call:
    description: "Call to an external system (read or write)"
    default_risk: medium
    overrides:
      read_only: low          # read-only external calls are low-risk

  external_write:
    description: "Write to an external system (calendar, GitHub, email, etc.)"
    default_risk: high

  bulk_operation:
    description: "Operation touching N+ items or crossing goal boundaries"
    default_risk: high

  deletion:
    description: "Goal/task/followup/decision deletion"
    default_risk: high

  configuration_change:
    description: "Change to Janus config, policy rules, or plugin state"
    default_risk: high
    overrides:
      non_policy: low         # non-policy config changes are low-risk

  knowledge_promotion:
    description: "Promotion of a knowledge artifact to the Obsidian vault"
    default_risk: medium
```

#### 3.1.3 Per-goal/per-project override

Override via frontmatter in goal/project markdown files:

```yaml
---
janus_policy:
  overrides:
    state_change:
      default_risk: low       # this goal treats all state changes as low-risk
    external_write:
      default_risk: medium    # this goal treats external writes as medium-risk
---
```

The policy loader reads frontmatter overrides and merges them with the default taxonomy. Override scope is the goal/project the frontmatter belongs to.

#### 3.1.4 Design decisions

| Decision | Choice | Rationale |
|---|---|---|
| Taxonomy representation | Python enum + YAML data file | Enum gives type safety and IDE support; YAML gives data-driven risk mapping. The enum is the catalog; the YAML is the risk assignment. |
| Override mechanism | Frontmatter `janus_policy` block | Consistent with existing Janus frontmatter conventions (goal metadata, task metadata). No new file format. |
| Override scope | Per goal/project | Matches the requirement that a low-stakes goal can treat goal-status-change as low. |
| Risk level values | `low`, `medium`, `high` | Matches P1 spec §3.1 and triage doc §7.2. |

---

### 3.2 Lightweight Configurable Policy Rules (P2-2)

**File:** `src/janus/services/policy_engine.py` — loader + evaluator

**Data file:** `config/policy/policy_rules.yaml` — default rule set

#### 3.2.1 Rule schema

```yaml
# config/policy/policy_rules.yaml
version: "1.0.0"
rules:
  - id: "R-STATE-CHANGE-LOW"
    action: "state_change"
    context_filter: null           # null = applies to all contexts
    risk_level: low
    approval_required: false
    channel: cli
    expires_hours: null

  - id: "R-STATE-CHANGE-MED"
    action: "state_change"
    context_filter: "goal_status"
    risk_level: medium
    approval_required: true
    channel: cli
    expires_hours: 24

  - id: "R-DATA-WRITE"
    action: "data_write"
    context_filter: null
    risk_level: low
    approval_required: false
    channel: cli
    expires_hours: null

  - id: "R-EXTERNAL-CALL-READ"
    action: "external_call"
    context_filter: "read_only"
    risk_level: low
    approval_required: false
    channel: cli
    expires_hours: null

  - id: "R-EXTERNAL-WRITE"
    action: "external_write"
    context_filter: null
    risk_level: high
    approval_required: true
    channel: cli
    expires_hours: 24

  - id: "R-BULK-OPERATION"
    action: "bulk_operation"
    context_filter: null
    risk_level: high
    approval_required: true
    channel: cli
    expires_hours: 24

  - id: "R-DELETION"
    action: "deletion"
    context_filter: null
    risk_level: high
    approval_required: true
    channel: cli
    expires_hours: 24

  - id: "R-CONFIG-CHANGE"
    action: "configuration_change"
    context_filter: "policy"
    risk_level: high
    approval_required: true
    channel: cli
    expires_hours: 24

  - id: "R-CONFIG-NON-POLICY"
    action: "configuration_change"
    context_filter: "non_policy"
    risk_level: low
    approval_required: false
    channel: cli
    expires_hours: null

  - id: "R-KNOWLEDGE-PROMOTION"
    action: "knowledge_promotion"
    context_filter: null
    risk_level: medium
    approval_required: true
    channel: cli
    expires_hours: 48
```

#### 3.2.2 Policy engine interface

```python
# src/janus/services/policy_engine.py

@dataclass(frozen=True)
class PolicyVerdict:
    """Result of evaluating an action against the policy rule set."""
    rule_id: str
    action: str
    risk_level: str           # "low" | "medium" | "high"
    approval_required: bool
    channel: str              # "cli" | "telegram" | "review" | "any"
    expires_hours: int | None
    policy_version: str

class PolicyEngine:
    """Loads policy rules from YAML and evaluates actions against them."""

    def __init__(self, rules_path: Path | None = None):
        ...

    def evaluate(
        self,
        action: str,
        context: str | None = None,
        goal_id: str | None = None,
    ) -> PolicyVerdict:
        """Evaluate an action against the rule set.

        Returns the most restrictive matching verdict.
        If no rule matches, returns ALLOW with low risk (fail-open for
        unclassified actions — P1 gates provide the blocking layer).
        """
        ...

    def reload(self) -> None:
        """Reload rules from disk. Called when rules file changes."""
        ...
```

#### 3.2.3 Evaluation algorithm

1. Load all rules from `config/policy/policy_rules.yaml`.
2. If `goal_id` is provided, load that goal's frontmatter overrides and merge.
3. Filter rules where `action` matches the input action.
4. If `context` is provided, further filter rules where `context_filter` matches.
5. If multiple rules match, return the most restrictive verdict (DENY > ASK > ALLOW, i.e., `approval_required=True` wins).
6. If no rule matches, return a default ALLOW verdict with `risk_level=low` and `approval_required=False` (fail-open — P1 gates are the blocking layer, not P2).

#### 3.2.4 Design decisions

| Decision | Choice | Rationale |
|---|---|---|
| Rule format | YAML list of rule objects | Human-readable, diff-friendly, no code change to add rules. |
| Evaluation | First-match + most-restrictive | Simple, deterministic, no chaining. Matches the "not a full rules engine" requirement. |
| Default verdict | ALLOW (fail-open) | P2 does not block. P1 gates block. If P2 fails to classify, P1's existing gates still protect. |
| Override mechanism | Frontmatter `janus_policy` block | Consistent with R2.1.3. Same override path for both taxonomy and rules. |
| Reload | Explicit `reload()` call | No file watching. Reload on startup and on explicit signal. |

---

### 3.3 ApprovalRequest Data Model (P2-3)

**File:** `src/janus/models/approval_request.py` — Python model

**Storage:** `data/approval_requests/approval_requests.jsonl` — JSONL log, one record per line

#### 3.3.1 Model

```python
# src/janus/models/approval_request.py

class ApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    DEFERRED = "deferred"
    ESCALATED = "escalated"
    TIMED_OUT = "timed_out"

class ApprovalDecision(StrEnum):
    APPROVE = "approve"
    REJECT = "reject"
    DEFER = "defer"

@dataclass
class ApprovalRequest:
    id: str                          # unique identifier (UUID)
    action: str                      # action type (from ActionType enum)
    action_description: str          # human-readable description
    risk_level: str                  # "low" | "medium" | "high"
    context: str                     # goal/task/project/metric being affected
    policy_version: str              # which policy version produced this request
    requested_at: str                # ISO 8601 timestamp
    requested_by: str                # who/what triggered it (e.g., service function name)
    expires_at: str | None           # ISO 8601 timestamp; null = no expiry
    status: ApprovalStatus           # current status
    approver: str | None             # who approved/rejected (if decided)
    decision: ApprovalDecision | None  # approve/reject/defer
    rationale: str | None            # free text from the approver
    channel: str                     # how the request was presented (cli/telegram/review)
    escalation_count: int = 0        # number of times this request has been escalated
```

#### 3.3.2 Status lifecycle

```
                  ┌──────────┐
                  │ PENDING  │
                  └────┬─────┘
           ┌───────────┼───────────┬───────────┐
           │           │           │           │
           ▼           ▼           ▼           ▼
     ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐
     │ APPROVED │ │ REJECTED │ │ DEFERRED │ │TIMED_OUT │
     │(terminal)│ │(terminal)│ │(terminal)│ │(terminal)│
     └──────────┘ └──────────┘ └──────────┘ └──────────┘
           │
           │ (escalation threshold reached)
           ▼
     ┌──────────┐
     │ESCALATED │  (terminal — re-routed to different channel)
     │(terminal)│
     └──────────┘
```

**Valid transitions:**
- `pending` → `approved` (terminal)
- `pending` → `rejected` (terminal)
- `pending` → `deferred` (terminal)
- `pending` → `timed_out` (terminal)
- `pending` → `escalated` (terminal)

**Invalid transitions (rejected by validator):**
- Any terminal state → any state (terminal states are terminal)
- `approved` → `pending` (no re-approval)
- `rejected` → `pending` (no re-approval after rejection)

#### 3.3.3 Storage format

Each approval request is one JSON object per line in `data/approval_requests/approval_requests.jsonl`:

```json
{"id": "ar-001", "action": "external_write", "action_description": "Write to Google Calendar", "risk_level": "high", "context": "goal:learn-agent-engineering", "policy_version": "1.0.0", "requested_at": "2026-09-30T18:00:00Z", "requested_by": "services.calendar.create_event", "expires_at": "2026-10-01T18:00:00Z", "status": "pending", "approver": null, "decision": null, "rationale": null, "channel": "cli", "escalation_count": 0}
```

Writes use `atomic_io` (consistent with ADR-005 write gateway). The file is append-only; status transitions are recorded as new lines (the latest line for a given `id` is the current state).

#### 3.3.4 Design decisions

| Decision | Choice | Rationale |
|---|---|---|
| Storage | JSONL file | Simple, append-only, human-readable, no database. Consistent with existing Janus data files. |
| Identity | UUID (`ar-` prefix) | Unique, sortable, no collision risk. |
| Channel | Stored as field, not baked into model | Channel-agnostic model. Channels are adapters. |
| Expiry | Optional `expires_at` | Not all requests need a timeout. When set, timeout → deferred. |
| Escalation count | Tracked on the request | Prevents infinite escalation loops. Max 2 escalations (configurable). |

---

### 3.4 Deferred and Escalated Approval (P2-4)

**File:** `src/janus/services/approval_handler.py` — timeout + escalation logic

#### 3.4.1 Deferred approval (timeout → defer)

When an approval request reaches `expires_at` with no decision:

1. A background check (or lazy evaluation on read) detects the timeout.
2. The request status transitions: `pending` → `timed_out`.
3. A policy decision record is written (R2.5): `approval_outcome = timed_out`.
4. The action is **not** auto-approved. It is deferred — the action is not taken, but it is not blocked forever. It can be re-requested later (new ApprovalRequest, possibly with a different channel or longer timeout).

**Default behavior:** `timed_out` is terminal. The action is not taken. The user can re-trigger the action, which creates a new ApprovalRequest.

#### 3.4.2 Escalation

Each approval request may carry an `escalation_threshold` (e.g., 24h pending → escalate). When the threshold is reached with no decision:

1. The request status transitions: `pending` → `escalated`.
2. A new ApprovalRequest is created with a different channel (e.g., CLI → Telegram, or Telegram → weekly review).
3. The escalation channel sequence is configured per policy rule or per request.

**Escalation channel sequence (default):**

```
cli → telegram → weekly_review
```

This is configurable in the policy rule set:

```yaml
# In policy_rules.yaml, per rule:
escalation_sequence:
  - cli
  - telegram
  - weekly_review
max_escalations: 2
```

#### 3.4.3 Escalation does not auto-approve

Escalation re-routes the pending request to a different channel. The decision still requires a human. If all channels are exhausted, the request becomes `deferred`.

#### 3.4.4 Design decisions

| Decision | Choice | Rationale |
|---|---|---|
| Timeout detection | Lazy evaluation on read + optional background check | No background process needed for P2. Lazy evaluation is sufficient — the next time the approval list is read, expired requests are detected and transitioned. |
| Escalation max | 2 (configurable) | Prevents infinite escalation loops. After 2 escalations, defer. |
| Escalation channel sequence | Configurable per rule | Different rules may need different escalation paths. |
| Auto-approval | Explicitly not supported | Core P2 principle. Timeout and escalation never auto-approve. |

---

### 3.5 Policy Decision Recording (P2-5)

**File:** `src/janus/services/policy_decision_log.py` — writer

**Storage:** `data/policy_decisions/YYYY-MM-DD.jsonl` — JSONL log, one file per day

#### 3.5.1 Recorded fields

```json
{"timestamp": "2026-09-30T18:00:00Z", "policy_version": "1.0.0", "action": "external_write", "action_description": "Write to Google Calendar", "context": "goal:learn-agent-engineering", "risk_level": "high", "verdict": "ASK", "approval_request_id": "ar-001", "approval_outcome": "approved", "approver": "hoczka", "rationale": "confirmed during weekly review", "channel": "cli"}
```

#### 3.5.2 When decisions are recorded

| Event | Recorded? | Fields |
|---|---|---|
| Policy verdict = ALLOW | Yes | `verdict=ALLOW`, `approval_request_id=null`, `approval_outcome=null` |
| Policy verdict = ASK, approval requested | Yes | `verdict=ASK`, `approval_request_id=<id>`, `approval_outcome=<outcome>` |
| Policy verdict = DENY | Yes | `verdict=DENY`, `approval_request_id=null`, `approval_outcome=null` |
| Approval request created | Yes | `verdict=ASK`, `approval_request_id=<id>`, `approval_outcome=pending` |
| Approval request decided | Yes (update) | `approval_outcome=approved/rejected/deferred` |
| Approval request timed out | Yes (update) | `approval_outcome=timed_out` |
| Approval request escalated | Yes (update) | `approval_outcome=escalated` |

#### 3.5.3 Design decisions

| Decision | Choice | Rationale |
|---|---|---|
| Storage | JSONL, one file per day | Simple rotation, no database, easy to grep. |
| Write path | `atomic_io` | Consistent with ADR-005 write gateway. No new write path. |
| Query API | None | P2 is a log, not a queryable database. If querying is needed later, that's separate work. |
| Retention | All files kept (no rotation/deletion) | Audit trail. Disk space is not a concern at current scale. |

---

### 3.6 Policy Version Lifecycle (P2-6)

**File:** Version is stored in the YAML data files (`version` field)

#### 3.6.1 Versioning scheme

- The rule set carries a `version` identifier (semver: `major.minor.patch`).
- The action taxonomy YAML also carries a `version` identifier.
- When rules change, the version increments.
- The version is recorded with every policy decision (R2.5).
- No retroactive re-evaluation — old decisions are not re-decided under new rules.

#### 3.6.2 Version increment rules

| Change type | Version increment | Example |
|---|---|---|
| Add new rule | patch | `1.0.0` → `1.0.1` |
| Remove rule | minor | `1.0.1` → `1.1.0` |
| Change risk level | minor | `1.1.0` → `1.2.0` |
| Change approval requirement | minor | `1.2.0` → `1.3.0` |
| Structural schema change | major | `1.3.0` → `2.0.0` |

#### 3.6.3 Design decisions

| Decision | Choice | Rationale |
|---|---|---|
| Version format | Semver | Standard, well-understood, sortable. |
| Version location | Top-level `version` field in YAML | Easy to read, easy to bump. |
| Re-evaluation | Not supported | Core P2 principle. Old decisions remain under the policy version active when made. |

---

### 3.7 Bulk-Operation Classification (P2-7)

**File:** `src/janus/services/bulk_classifier.py` — classifier

**Config:** `config/policy/bulk_thresholds.yaml` — thresholds

#### 3.7.1 Thresholds

```yaml
# config/policy/bulk_thresholds.yaml
version: "1.0.0"
thresholds:
  bulk_item_count: 5           # operation touching >= 5 items = bulk
  bulk_goal_crossing: true     # operation crossing goal boundaries = bulk
  bulk_deletion_count: 1       # deleting >= 1 goal = bulk (deletion is already high-risk)
  bulk_task_deletion_count: 3  # deleting >= 3 tasks in one call = bulk
```

#### 3.7.2 Classification logic

```python
# src/janus/services/bulk_classifier.py

@dataclass(frozen=True)
class BulkClassification:
    is_bulk: bool
    reason: str | None          # why this was classified as bulk (or None if not bulk)
    affected_item_count: int
    affected_goal_count: int

class BulkClassifier:
    """Classifies operations as bulk or not based on configurable thresholds."""

    def __init__(self, config_path: Path | None = None):
        ...

    def classify(
        self,
        affected_items: list[str],     # list of item IDs being affected
        affected_goals: list[str],     # list of goal IDs being affected
        is_deletion: bool = False,
    ) -> BulkClassification:
        """Classify an operation as bulk or not.

        Returns BulkClassification with is_bulk=True if any threshold is exceeded.
        """
        ...
```

#### 3.7.3 Classification rules

An operation is classified as `bulk_operation` if ANY of:

1. `len(affected_items) >= bulk_item_count` (default: 5)
2. `len(affected_goals) > 1` (crosses goal boundaries)
3. `is_deletion and len(affected_goals) >= bulk_deletion_count` (default: 1)
4. `is_deletion and len(affected_items) >= bulk_task_deletion_count` (default: 3)

#### 3.7.4 Design decisions

| Decision | Choice | Rationale |
|---|---|---|
| Default threshold N | 5 items | Starting point from requirements spec. Configurable. |
| Goal crossing | Always bulk | Cross-goal operations are inherently higher-risk. |
| Deletion threshold | 1 goal = bulk | Deleting even one goal is already high-risk; bulk deletion is a stronger signal. |
| Classification only | Does not block | The classifier classifies. The approval request (R2.3) and P1's high-risk explicit-confirmation rule handle the blocking. |

---

## 4. Integration with P1 Infrastructure

### 4.1 How P1 gates consume P2

P1 gates (G-1 through G-7) consult P2 in the following way:

```
P1 gate triggered (e.g., G-4: external system write)
  │
  ▼
PolicyEngine.evaluate(action="external_write", context="calendar_write")
  │
  ▼
PolicyVerdict(risk_level="high", approval_required=True, channel="cli", expires_hours=24)
  │
  ▼
P1 gate creates ApprovalRequest (R2.3)
  │
  ▼
P1 gate presents to user via channel (CLI at P1)
  │
  ▼
User decides → ApprovalRequest status transitions
  │
  ▼
P1 gate proceeds (approved) or blocks (rejected/deferred)
```

### 4.2 Integration points

| P1 gate | P2 component used | How |
|---|---|---|
| G-1 (task completion) | PolicyEngine | Evaluates action="state_change", context="task_completion" |
| G-2 (goal completion) | PolicyEngine + BulkClassifier | Evaluates action="state_change", context="goal_completion" |
| G-3 (knowledge promotion) | PolicyEngine | Evaluates action="knowledge_promotion" |
| G-4 (external write) | PolicyEngine + ApprovalRequest | Evaluates action="external_write", creates approval request |
| G-5 (goal deletion) | PolicyEngine + BulkClassifier + ApprovalRequest | Evaluates action="deletion", classifies bulk, creates approval request |
| G-6 (bulk state change) | BulkClassifier + ApprovalRequest | Classifies bulk, creates approval request |
| G-7 (config change) | PolicyEngine | Evaluates action="configuration_change" |

### 4.3 What P2 does NOT do

- P2 does not implement the CLI prompt, Telegram notification, or review lane adapter. P2 defines the ApprovalRequest model and the policy decision log. Channels are separate work.
- P2 does not block. P2 classifies, configures, records, and defers. P1 blocks.
- P2 does not call P1's gates. The dependency flows P1 → P2.

---

## 5. File and Directory Layout

```
config/policy/
  action_taxonomy.yaml          # R2.1 — action types + default risk mapping
  policy_rules.yaml             # R2.2 — policy rules (verdicts, approval, channels)
  bulk_thresholds.yaml          # R2.7 — bulk operation thresholds

src/janus/models/
  action_type.py                # R2.1 — ActionType enum
  approval_request.py           # R2.3 — ApprovalRequest model + status lifecycle

src/janus/services/
  policy_engine.py              # R2.2 — PolicyEngine (loader + evaluator)
  approval_handler.py           # R2.4 — deferred/escalated approval logic
  policy_decision_log.py        # R2.5 — policy decision recording
  bulk_classifier.py            # R2.7 — bulk operation classifier

data/
  approval_requests/
    approval_requests.jsonl     # R2.3 — approval request records
  policy_decisions/
    YYYY-MM-DD.jsonl            # R2.5 — policy decision log (one file per day)

tests/
  test_policy_engine.py         # R2.2 — policy engine unit tests
  test_approval_request.py     # R2.3 — approval request model tests
  test_approval_handler.py     # R2.4 — deferred/escalated approval tests
  test_policy_decision_log.py   # R2.5 — policy decision recording tests
  test_bulk_classifier.py       # R2.7 — bulk classifier tests
  test_action_type.py           # R2.1 — action type taxonomy tests
```

---

## 6. Implementation Order

The implementation order is designed so that each component can be tested independently before integration.

### Phase 1: Data models + taxonomy (no dependencies)

1. **R2.1 — ActionType enum + action_taxonomy.yaml**
   - Create `ActionType` enum in `src/janus/models/action_type.py`
   - Create `config/policy/action_taxonomy.yaml`
   - Tests: `test_action_type.py`

2. **R2.3 — ApprovalRequest model**
   - Create `ApprovalRequest` model in `src/janus/models/approval_request.py`
   - Create `data/approval_requests/` directory
   - Tests: `test_approval_request.py`

### Phase 2: Loaders + evaluators (depends on Phase 1)

3. **R2.2 — PolicyEngine + policy_rules.yaml**
   - Create `PolicyEngine` in `src/janus/services/policy_engine.py`
   - Create `config/policy/policy_rules.yaml`
   - Tests: `test_policy_engine.py`

4. **R2.7 — BulkClassifier + bulk_thresholds.yaml**
   - Create `BulkClassifier` in `src/janus/services/bulk_classifier.py`
   - Create `config/policy/bulk_thresholds.yaml`
   - Tests: `test_bulk_classifier.py`

### Phase 3: Handlers + recording (depends on Phase 2)

5. **R2.4 — ApprovalHandler (deferred + escalated)**
   - Create `ApprovalHandler` in `src/janus/services/approval_handler.py`
   - Tests: `test_approval_handler.py`

6. **R2.5 — PolicyDecisionLog**
   - Create `PolicyDecisionLog` in `src/janus/services/policy_decision_log.py`
   - Create `data/policy_decisions/` directory
   - Tests: `test_policy_decision_log.py`

### Phase 4: Versioning (depends on Phase 2)

7. **R2.6 — Policy version lifecycle**
   - Add version field to YAML files (already in schema)
   - Add version recording to PolicyDecisionLog (already in schema)
   - Tests: version increment, version recording, no re-evaluation

### Phase 5: Integration tests

8. **Integration tests**
   - P1 gate → PolicyEngine → ApprovalRequest flow
   - Bulk operation → BulkClassifier → ApprovalRequest flow
   - Timeout → deferred flow
   - Escalation → re-routed flow

---

## 7. Configuration Reference

### 7.1 Default configuration values

| Setting | Default | Location | Description |
|---|---|---|---|
| `bulk_item_count` | 5 | `bulk_thresholds.yaml` | Items threshold for bulk classification |
| `bulk_goal_crossing` | true | `bulk_thresholds.yaml` | Cross-goal = bulk |
| `bulk_deletion_count` | 1 | `bulk_thresholds.yaml` | Goal deletion = bulk |
| `bulk_task_deletion_count` | 3 | `bulk_thresholds.yaml` | Task deletion threshold |
| `expires_hours` (CLI) | 24 | `policy_rules.yaml` | Default approval expiry for CLI channel |
| `expires_hours` (knowledge) | 48 | `policy_rules.yaml` | Knowledge promotion approval expiry |
| `max_escalations` | 2 | `policy_rules.yaml` | Max escalation attempts before defer |
| `escalation_sequence` | cli → telegram → weekly_review | `policy_rules.yaml` | Default escalation channel sequence |

### 7.2 Per-goal override example

```yaml
# In a goal's markdown file frontmatter
---
janus_policy:
  overrides:
    state_change:
      default_risk: low
    external_write:
      default_risk: medium
  rules:
    - id: "R-GOAL-SPECIFIC"
      action: "data_write"
      context_filter: null
      risk_level: low
      approval_required: false
      channel: cli
      expires_hours: null
---
```

---

## 8. Error Handling

| Error | Behavior |
|---|---|
| Policy rules file missing | Log warning, use built-in defaults (fail-open: ALLOW all) |
| Policy rules file malformed YAML | Log error, use built-in defaults (fail-open: ALLOW all) |
| Action type not in taxonomy | Log warning, classify as `state_change` with `medium` risk (conservative default) |
| Approval request ID not found | Log error, return 404-equivalent |
| Invalid status transition | Log error, reject transition, raise `ApprovalTransitionError` |
| Policy decision log write failure | Log error, do not retry (log is best-effort; the approval request is the source of truth) |

**Fail-open principle:** If P2 cannot classify an action (missing rule, missing taxonomy entry, malformed config), the default verdict is ALLOW with low risk. P1's gates are the blocking layer — P2 failing to classify does not create a security hole; it just means P1's existing gates apply.

---

## 9. Testing Strategy

### 9.1 Unit tests

Each component has dedicated unit tests:

- `test_action_type.py` — enum values, taxonomy YAML loading, override merging
- `test_policy_engine.py` — rule evaluation, most-restrictive verdict, fail-open default, per-goal override
- `test_approval_request.py` — model creation, status transitions, invalid transition rejection
- `test_approval_handler.py` — timeout → deferred, escalation → re-routed, max escalations
- `test_policy_decision_log.py` — decision recording, JSONL format, atomic write
- `test_bulk_classifier.py` — threshold classification, goal crossing, deletion classification

### 9.2 Integration tests

- P1 gate → PolicyEngine → ApprovalRequest → approval flow
- Bulk operation → BulkClassifier → ApprovalRequest → approval flow
- Timeout → deferred → re-request flow
- Escalation → re-routed → approved flow
- Policy version change → new decisions use new version, old decisions unchanged

### 9.3 Test data

- Mock goal/task/project data in `tests/fixtures/`
- Mock policy rules in `tests/fixtures/policy_rules_test.yaml`
- Mock approval requests in `tests/fixtures/approval_requests_test.jsonl`

---

## 10. Open Questions

| # | Question | Status | Resolution path |
|---|---|---|---|
| 1 | Should the policy engine be a singleton or instantiated per request? | Open | Recommend: singleton with explicit `reload()`. Policy is read-only at runtime. |
| 2 | Should the approval handler run as a background process or lazy evaluation? | Open | Recommend: lazy evaluation for P2. Background process is future work. |
| 3 | Should the policy decision log have a rotation/retention policy? | Open | Recommend: no rotation for P2. All files kept. Revisit if disk space becomes a concern. |
| 4 | Should the bulk classifier be integrated into the policy engine or standalone? | Open | Recommend: standalone. The policy engine calls the classifier when needed. |
| 5 | Should the ApprovalRequest model be persisted in a single JSONL file or one file per request? | Open | Recommend: single JSONL file. Simpler, consistent with existing Janus data files. |

---

## 11. Acceptance Criteria Mapping

| AC | Criterion | Design component |
|---|---|---|
| AC2.1.1 | Action-type taxonomy documented with type, description, default risk level | §3.1.2 `action_taxonomy.yaml` |
| AC2.1.2 | Default risk mapping is data, not hardcoded reason codes | §3.1.2 YAML data file |
| AC2.1.3 | Per-goal/per-project override path exists via frontmatter | §3.1.3 frontmatter override |
| AC2.1.4 | Taxonomy does not introduce new blocking gates | §2 non-goals, §3.1.4 fail-open |
| AC2.2.1 | Default rule set ships with Janus, covering R2.1 action types | §3.2.1 `policy_rules.yaml` |
| AC2.2.2 | Per-goal/per-project override via `janus_policy` frontmatter | §3.2.3 evaluation algorithm step 2 |
| AC2.2.3 | Policy loader is deterministic | §3.2.3 evaluation algorithm |
| AC2.2.4 | Rule set is a data file, not a code change | §3.2.1 YAML format |
| AC2.2.5 | No full rules engine | §3.2.3 simple first-match + most-restrictive |
| AC2.3.1 | ApprovalRequest data model defined with required fields | §3.3.1 model |
| AC2.3.2 | Status transitions validated; terminal states are terminal | §3.3.2 lifecycle |
| AC2.3.3 | expires_at → deferred by default; auto-approval not default | §3.4.1 deferred approval |
| AC2.3.4 | Model is channel-agnostic | §3.3.1 channel field |
| AC2.4.1 | Timeout → deferred; auto-approval not supported | §3.4.1 |
| AC2.4.2 | Escalation threshold + channel sequence configurable | §3.4.2 escalation config |
| AC2.4.3 | Escalation re-routes; does not auto-approve | §3.4.3 |
| AC2.4.4 | Deferred and escalated requests are recorded | §3.5.2 decision recording |
| AC2.5.1 | Every ASK → approval request produces a recorded decision | §3.5.2 |
| AC2.5.2 | Every ALLOW/DENY verdict produces a recorded decision | §3.5.2 |
| AC2.5.3 | Records include policy_version | §3.5.1 recorded fields |
| AC2.5.4 | Records written via atomic_io | §3.5.3 design decisions |
| AC2.5.5 | Policy-decision log, not a queryable database | §3.5.3 |
| AC2.6.1 | Rule set carries a version identifier | §3.6.1 |
| AC2.6.2 | Version recorded with every policy decision | §3.5.1 |
| AC2.6.3 | Rule set change increments version | §3.6.2 |
| AC2.6.4 | No retroactive re-evaluation | §3.6.3 |
| AC2.7.1 | Bulk thresholds documented and data-driven | §3.7.1 |
| AC2.7.2 | Bulk operation classified high-risk | §3.7.3 |
| AC2.7.3 | Bulk classifier is deterministic | §3.7.2 |
| AC2.7.4 | Bulk classifier does not block; it classifies | §3.7.4 |

---

## 12. References

- `docs/specs/p2-policy-approval-requirements.md` — P2 requirements spec (t_23d33a79)
- `docs/specs/p1-policy-approval-requirements.md` — P1 requirements spec (t_58f3186c)
- `docs/research/t_bb8e173d-policy-approval-infrastructure-findings.md` — existing infrastructure findings (t_bb8e173d)
- `docs/triage_architectural_roadmap_next_phase.md` §7 — Policy/Approval minimal model
- `docs/janus-agency-first-development-phase.md` §10, §Phase E — Policy and Approval layer
- `docs/roadmap.md` line 156 — Phase E — Policy & Approval (P1/P2)
- `docs/decisions/004-safe-sync-integrate-workflow.md` — ADR-004 (5-phase gated completion)
- `docs/decisions/adr-011-goal-level-completion-gates.md` — ADR-011 (proposed goal gates)
- `src/janus/services/curation_gate.py` — existing 5-state approval workflow (reference for R2.3)
- `src/janus/services/remediation.py` — existing ESCALATION_POLICY dict (reference for R2.4)
- `src/janus/verification.py` — existing DefaultCheckConfig pattern (reference for R2.2)
- `src/janus/integrations/data_integrity.py` — existing atomic_io write gateway (reference for R2.5)

---

*End of design document.*
