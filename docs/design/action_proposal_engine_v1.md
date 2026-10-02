# Action Proposal Engine V1 — Design Document

**Status:** Implementation (interface + data model)
**Parent task:** t_6552d671 (Action Proposal Engine V1)
**Date:** 2026-10-02

---

## 1. Overview

The Action Proposal Engine V1 transforms a `WeeklyPlan` into structured,
validated `ActionProposal` objects. It is the bridge between the weekly
planner and a future approval/execution layer.

**V1 is proposal-only.** The engine generates proposals but never
executes them. No mutation methods are exposed for tasks, goals, or
calendar.

### Core principle

```
WeeklyPlan + PlanningContext → ActionProposalEngine → ActionProposal[]
```

The engine is a pure function: it takes planner output and context,
and returns a list of proposals. No side effects, no I/O, no state
mutation.

---

## 2. Goals & Non-Goals

### Goals (V1)

| # | Goal | Done when |
|---|------|-----------|
| G1 | Structured proposal data model | `ActionProposal` dataclass with all required fields |
| G2 | Proposal-only interface | `ActionProposalEngine` protocol with only `generate()` |
| G3 | Zero mutation endpoints | No mutation methods on model or protocol |
| G4 | Documented proposal schema | This document + docstrings |
| G5 | Serialization support | `to_dict()` / `from_dict()` round-trip |

### Non-Goals (V1)

- Proposal execution (future task)
- Approval workflow (future task)
- Policy check integration (future task)
- LLM-based proposal generation (future task)
- CLI presentation (future task, t_401568d8)
- Proposal persistence (future task)

---

## 3. Data Model

### 3.1 ActionProposal

```python
@dataclass
class ActionProposal:
    proposal_id: str = ""
    action_type: ActionType = ActionType.CREATE_TASK
    target_id: str | None = None
    parameters: dict[str, Any] = field(default_factory=dict)
    reason: str = ""
    source: str = ""
    risk: RiskLevel = RiskLevel.LOW
    status: ProposalStatus = ProposalStatus.PROPOSED
    created_at: datetime | None = None
    updated_at: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
```

**Location:** `src/janus/proposal/models.py`

### 3.2 ActionType (enum)

| Member | Value | Description |
|--------|-------|-------------|
| `CREATE_TASK` | `"CREATE_TASK"` | Propose creating a new task |
| `UPDATE_TASK` | `"UPDATE_TASK"` | Propose updating an existing task |
| `RESCHEDULE_TASK` | `"RESCHEDULE_TASK"` | Propose changing a task's due date |
| `CHANGE_PRIORITY` | `"CHANGE_PRIORITY"` | Propose changing a task's priority |
| `CREATE_CALENDAR_EVENT` | `"CREATE_CALENDAR_EVENT"` | Propose creating a calendar event |

**Explicitly excluded:** `DELETE_TASK`, `DELETE_GOAL`, `DELETE_CALENDAR_EVENT`,
`EXECUTE`, `MODIFY_GOAL`, `WRITE`. These are not valid proposal action types.

### 3.3 ProposalStatus (enum)

| Member | Value | Description |
|--------|-------|-------------|
| `PROPOSED` | `"PROPOSED"` | Awaiting human decision (initial state) |
| `APPROVED` | `"APPROVED"` | Human approved; ready for future execution |
| `REJECTED` | `"REJECTED"` | Human rejected; terminal |
| `EXECUTED` | `"EXECUTED"` | Action was executed; terminal |

V1 only produces `PROPOSED` proposals. Other statuses are for future
approval/execution workflow.

### 3.4 RiskLevel (reused from policy model)

Reuses `janus.models.policy.RiskLevel` (`LOW`, `MEDIUM`, `HIGH`).

---

## 4. Interface

### 4.1 ActionProposalEngine Protocol

```python
class ActionProposalEngine(Protocol):
    def generate(
        self,
        plan: WeeklyPlan,
        context: PlanningContext,
    ) -> list[ActionProposal]:
        ...
```

**Location:** `src/janus/proposal/protocol.py`

The protocol exposes only `generate()`. No mutation methods are part
of the interface.

### 4.2 V1 Implementation

The V1 implementation is `RuleBasedProposalEngine` (deterministic,
rule-based). It is implemented in `src/janus/proposal/engine.py`.

**Rules:**

| Rule | Trigger | ActionType | Source |
|------|---------|------------|--------|
| 1 | Overdue task in plan | `RESCHEDULE_TASK` | `rule:overdue` |
| 2 | Goal without tasks | `CREATE_TASK` | `rule:missing_task` |
| 3 | Priority mismatch | `CHANGE_PRIORITY` | `rule:priority_mismatch` |
| 4 | Planned task with suggested_day | `CREATE_CALENDAR_EVENT` | `rule:calendar_entry` |
| 5 | High-severity risk | `UPDATE_TASK` | `rule:risk` |

The engine is pure: no side effects, no I/O, no state mutation.

---

## 5. Module Structure

```
src/janus/proposal/
├── __init__.py          # Re-exports public symbols
├── models.py            # ActionProposal, ActionType, ProposalStatus
└── protocol.py          # ActionProposalEngine protocol
```

---

## 6. Integration Points

### 6.1 Upstream

- `WeeklyPlan` (from `janus.planner.models`) — the plan to transform
- `PlanningContext` (from `janus.planner.models`) — goals, tasks, calendar

### 6.2 Downstream (future)

- Approval workflow (t_401568d8)
- Policy check (future)
- Execution engine (future)
- CLI presentation (t_401568d8)

### 6.3 No integration with

- Task mutation services
- Goal mutation services
- Calendar mutation services
- Execution tools

---

## 7. Testing

**Test file:** `tests/test_proposal_engine_interface.py`

Coverage:
- ActionType enum values and membership
- ProposalStatus enum values and membership
- ActionProposal construction (minimal + full)
- Validation (empty reason, whitespace proposal_id)
- Timestamp auto-set
- `is_actionable` property
- Serialization round-trip (`to_dict` / `from_dict`)
- Protocol conformance (is_protocol, cannot instantiate, concrete impl)
- No mutation methods guarantee (model + protocol)
- Status field is data, not mutation

---

## 8. Definition of Done

- [x] `ActionProposal` dataclass exists with all required fields
- [x] `ActionType` enum with 5 action types
- [x] `ProposalStatus` enum with 4 statuses
- [x] `ActionProposalEngine` protocol with only `generate()`
- [x] Zero mutation methods on model and protocol
- [x] Serialization support (`to_dict` / `from_dict`)
- [x] Unit tests pass (21 tests)
- [x] Existing planner tests still pass
- [x] Design doc documents proposal schema
