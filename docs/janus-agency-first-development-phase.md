# Janus — Agency-First Development Phase

## Status

**Proposed next phase**

This document defines the next strategic development phase of Janus after the completion of the Goal → Task → Execution → Completion → Review loop.

---

# 1. Purpose

Janus should be designed around the **user's agency**, not around maximizing agent autonomy.

The primary purpose of Janus is not to replace the user in completing tasks. It is to help the user accomplish things that would otherwise be difficult by reducing cognitive friction, improving planning, providing knowledge and structure, supporting execution, and creating a feedback loop for continuous improvement.

### Core principle

> **Janus should increase the user's capability and agency, not replace them.**

The user remains the primary actor and decision maker.

Janus acts as a cognitive and organizational force multiplier.

---

# 2. Strategic Positioning

Janus should not compete directly with general-purpose autonomous personal agents on the dimension of:

- number of integrations,
- browser automation,
- autonomous task execution,
- maximum agent autonomy,
- number of tools,
- or amount of work performed without the user.

Instead, Janus should specialize in the problem of:

> **Turning user intentions and ambitions into achievable outcomes while increasing the user's capability to act.**

A useful product definition is:

> **Janus is a Personal Agency System: a system that helps a person Think → Plan → Learn → Act → Reflect → Improve.**

This distinguishes Janus from an agent whose primary objective is:

> Ask → Agent executes → Done.

---

# 3. Agency-First Model

The core interaction model should become:

```text
                USER
                  │
          intention / ambition
                  ↓
               JANUS
        ┌──────────────────┐
        │ Understand       │
        │ Clarify          │
        │ Plan             │
        │ Teach            │
        │ Prepare          │
        │ Coach            │
        │ Challenge        │
        │ Verify           │
        └────────┬─────────┘
                 ↓
                USER
             takes action
                 ↓
              EVIDENCE
                 ↓
               JANUS
          reviews / adapts
                 ↓
                USER
```

The user should remain in the loop whenever their participation is important to the desired outcome.

---

# 4. What Janus Optimizes For

Janus should optimize for:

1. **User outcomes**
2. **User capability**
3. **User agency**
4. **Learning and skill development**
5. **Reduced cognitive friction**
6. **Consistency of execution**
7. **Evidence-based progress**
8. **Better decisions over time**

Janus should not optimize primarily for:

- number of tasks executed autonomously,
- minimum user involvement,
- maximum automation,
- maximum number of tools,
- maximum agent complexity.

### Success metric

A useful conceptual metric is:

> **What can the user accomplish with Janus that they would struggle to accomplish without it?**

A second important metric is:

> **Does repeated use of Janus make the user more capable or merely more dependent?**

The desired trajectory is increased capability.

---

# 5. Human-in-the-Loop Principles

## 5.1 Assist before executing

When a task is meaningful for the user's development, Janus should prefer helping the user perform it over performing it entirely on their behalf.

Example:

### User goal

> Learn to build an agentic AI system.

Bad default:

```text
Janus builds the entire agent.
```

Preferred:

```text
Janus:
1. assesses current knowledge,
2. explains the relevant architecture,
3. proposes a small project,
4. prepares the environment,
5. provides scaffolding,
6. helps debug,
7. reviews the implementation,
8. identifies gaps,
9. proposes the next challenge.
```

The user writes and understands the important parts.

---

## 5.2 Automate low-value work

Automation is appropriate when the task does not materially contribute to the user's desired capability.

Examples:

- collecting data,
- aggregating calendar events,
- formatting reports,
- checking routine conditions,
- synchronizing information,
- preparing summaries,
- detecting anomalies.

Janus should remove administrative friction so the user can spend time on high-value actions.

---

## 5.3 Difficulty is information

When a user says:

> "I don't know how to do this."

Janus should first determine what is blocking progress.

Potential blockers:

- missing knowledge,
- unclear goal,
- poor decomposition,
- lack of confidence,
- excessive complexity,
- lack of time,
- missing tooling,
- decision uncertainty,
- insufficient feedback.

The response should address the actual blocker rather than automatically taking over the task.

---

## 5.4 Preserve meaningful decisions

Janus may provide:

- options,
- trade-offs,
- recommendations based on explicit criteria,
- simulations,
- research,
- decision frameworks.

The user should retain ownership of meaningful personal decisions.

---

# 6. Core Closed Loop

The existing Janus domain model should evolve into a human-centered closed loop:

```text
GOAL
  ↓
METRIC / SUCCESS CRITERIA
  ↓
PLANNING
  ↓
TASK
  ↓
USER ACTION
  ↓
EVIDENCE
  ↓
VERIFICATION
  ↓
COMPLETION
  ↓
REVIEW
  ↓
ADAPTATION
  ↓
NEXT ACTION
```

This is the core of Janus.

The key difference from a conventional task manager is that task completion is not the end of the loop.

The important question is:

> **Did the action produce evidence of progress toward the user's goal?**

---

# 7. Personal State

Janus should eventually maintain an explicit model of the user's current state.

Conceptually:

```text
PersonalState
├── Goals
├── Metrics
├── Tasks
├── Projects
├── Commitments
├── Routines
├── Preferences
├── Constraints
├── Resources
├── Activities
├── Evidence
└── Decisions
```

This state should be used for planning and review.

The purpose is not to create an enormous personal database. The purpose is to maintain enough structured state for Janus to reason consistently about:

- what the user wants,
- what the user is doing,
- what has changed,
- what is blocking progress,
- and what should happen next.

---

# 8. Evidence as a First-Class Concept

Janus should distinguish between:

- planned work,
- claimed completion,
- verified execution,
- and actual outcome.

Example:

```text
Goal:
Reduce waist circumference to 82 cm

Task:
Average 10,000 steps/day

Execution:
12,431 steps

Evidence:
Activity data

Verification:
PASS

Outcome:
Waist measurement decreased from 86 cm to 84 cm

Review:
Current trajectory remains consistent with goal
```

Evidence should become a first-class domain concept rather than merely a log entry.

This enables Janus to reason about progress instead of only activity.

---

# 9. Audit Trail and Decision Record

Important Janus decisions should be explainable.

A useful record is:

```text
WHY
  ↓
WHAT
  ↓
ACTION
  ↓
EVIDENCE
  ↓
RESULT
  ↓
DECISION
```

For example:

```text
Goal:
Improve AI engineering capability

Observation:
Current progress stalled

Evidence:
No completed learning task in 3 weeks

Decision:
Create a practical agent-engineering project

Reason:
Hands-on execution is more useful than additional passive reading

Action:
Create project milestone and first implementation task
```

This creates an inspectable reasoning history without requiring the user to reconstruct why a decision was made.

---

# 10. Policy and Approval Layer

Janus should eventually have an explicit policy layer governing actions.

Conceptually:

```text
              ACTION
                 ↓
          RISK / IMPACT
                 ↓
              POLICY
          ┌──────┼──────┐
          ↓      ↓      ↓
        ALLOW   ASK    DENY
```

Examples:

| Action | Default |
|---|---|
| Read calendar | ALLOW |
| Analyze training data | ALLOW |
| Create a task | ALLOW |
| Update derived progress | ALLOW |
| Perform research | ALLOW |
| Send an email | ASK |
| Make a purchase | ASK |
| Change an important goal | ASK |
| Delete user data | ASK / DENY |
| Destructive external action | ASK / DENY |

The exact policy should remain configurable.

The purpose is to preserve user control while allowing routine work to be automated.

---

# 11. Agent Runtime vs Janus Domain

Janus should not attempt to recreate every capability of a general-purpose agent runtime.

The architecture should separate:

```text
                 JANUS
        ┌────────────────────┐
        │ Domain / reasoning │
        │                    │
        │ Goals              │
        │ Metrics            │
        │ Planning           │
        │ Tasks              │
        │ Evidence           │
        │ Verification       │
        │ Review             │
        │ Decisions          │
        │ Policies           │
        └─────────┬──────────┘
                  ↓
                HERMES
        ┌────────────────────┐
        │ Execution runtime  │
        │                    │
        │ Skills             │
        │ Tools              │
        │ Cron               │
        │ Browser            │
        │ Subagents          │
        │ Shell              │
        └────────────────────┘
```

Hermes should remain an execution layer.

Janus should remain the domain system responsible for goals, planning, progress, verification, and user agency.

---

# 12. Inspiration From Modern Personal Agents

Modern personal agents demonstrate several capabilities that are relevant to Janus:

- persistent background execution,
- long-running tasks,
- tool and connector ecosystems,
- subagent orchestration,
- approval gates,
- audit trails,
- persistent personal context,
- agent-generated tools,
- proactive monitoring.

Janus should selectively adopt these capabilities when they reinforce its agency-first model.

The principle is:

> **Adopt execution capabilities as infrastructure, not as the product identity.**

---

# 13. Roadmap

## Phase A — Complete the Core Loop

**Priority: P0**

Finish and stabilize:

```text
Goal
→ Planning
→ Task
→ Execution
→ Completion
→ Review
```

Requirements:

- authoritative task state,
- consistent task lifecycle,
- goal/task relationships,
- completion enforcement,
- verification,
- review,
- end-to-end tests.

This phase is foundational and should not be bypassed by adding more autonomous capabilities.

---

## Phase B — Evidence & Audit

**Priority: P1**

Introduce first-class:

- evidence,
- verification results,
- outcome records,
- decision records,
- audit trail.

Goal:

> Make Janus able to explain how it knows that progress occurred.

---

## Phase C — Personal State Model

**Priority: P1**

Define and implement the minimal structured model of:

- goals,
- metrics,
- tasks,
- projects,
- commitments,
- routines,
- constraints,
- preferences,
- activities,
- evidence,
- decisions.

Goal:

> Give Janus a coherent model of the user's current situation.

---

## Phase D — Agency-Aware Planning

**Priority: P1**

Extend planning so Janus can distinguish between:

- tasks Janus should execute,
- tasks the user should execute,
- tasks that should be collaborative,
- tasks that should be delegated,
- tasks that require learning before execution.

Introduce a concept such as:

```text
execution_mode:
  USER
  JANUS
  COLLABORATIVE
```

Potentially extend this with:

```text
support_mode:
  EXPLAIN
  COACH
  SCAFFOLD
  REVIEW
  EXECUTE
```

The planner should choose the least substitutive mode that still enables progress.

---

## Phase E — Policy & Approval

**Priority: P1/P2**

Implement:

- action classification,
- configurable policies,
- approval requests,
- explicit user confirmation,
- auditability.

Goal:

> Increase automation without reducing user control.

---

## Phase F — Connector Protocol

**Priority: P2**

Define a common interface for external data and actions.

Conceptually:

```text
Connector
├── source
├── capabilities
├── permissions
├── read()
├── propose()
├── execute()
└── evidence()
```

Potential connectors:

- Google Calendar
- GitHub
- Telegram
- email
- fitness/wearable data
- AWS
- future external services

Do not optimize for the number of integrations. Optimize for a clean capability model.

---

## Phase G — Self-Extending Skills

**Priority: P2**

Allow Janus to identify missing capabilities and propose new skills.

Desired lifecycle:

```text
Need capability
      ↓
Proposal
      ↓
Generate skill
      ↓
Tests
      ↓
Sandbox
      ↓
Verification
      ↓
Approval
      ↓
Install
```

Generated capabilities should not silently become trusted capabilities.

---

## Phase H — Multi-Agent Orchestration

**Priority: P3**

Introduce specialized agents only when a real workload benefits from them.

Potential roles:

```text
Planner
Researcher
Executor
Reviewer
Coach
```

The orchestration layer should remain subordinate to the Janus domain model.

---

# 14. Product Principles

Every future Janus feature should be evaluated against these principles.

### Principle 1 — Agency First

Does this increase the user's ability to act?

### Principle 2 — Human Ownership

Does the user remain the owner of meaningful decisions?

### Principle 3 — Capability Over Dependency

Will repeated use make the user more capable, or merely more dependent?

### Principle 4 — Evidence Over Assumptions

Does Janus distinguish intentions and claims from verified outcomes?

### Principle 5 — Assist Before Replace

Can Janus help the user perform the important part instead of taking it over?

### Principle 6 — Automation Where It Matters

Automate low-value coordination and administrative work so the user can focus on meaningful actions.

### Principle 7 — Explainability

Can the user understand why Janus recommended or initiated something?

### Principle 8 — Progressive Autonomy

Autonomy should be earned through trust, verification, and explicit policy rather than assumed by default.

---

# 15. Feature Evaluation Framework

Before implementing a feature, ask:

### User value

- What user outcome does this improve?
- What becomes possible that was previously difficult?

### Agency

- Does the feature increase or decrease user agency?
- Does it teach, scaffold, or merely replace?

### Automation

- Is automation actually valuable here?
- Is the task meaningful for the user's own development?

### Evidence

- How will Janus know that the desired outcome occurred?

### Trust

- What permissions are required?
- What actions need approval?

### Long-term effect

- Will repeated use increase user capability?
- Could the feature create unnecessary dependency?

A feature should be reconsidered if its primary benefit is simply:

> "The agent can do more things without the user."

---

# 16. Example: Career Development

Goal:

> Become stronger at AI/agent engineering.

Instead of:

```text
Janus researches courses
Janus selects course
Janus completes exercises
Janus writes project
Janus reports completion
```

Preferred:

```text
Janus assesses current capability
        ↓
Janus proposes learning path
        ↓
User chooses direction
        ↓
Janus creates practical challenge
        ↓
User implements
        ↓
Janus assists when blocked
        ↓
Janus reviews implementation
        ↓
Evidence is recorded
        ↓
Janus identifies capability gaps
        ↓
Next challenge
```

The output is not only a completed project.

The output is **a more capable user**.

---

# 17. Example: Fitness

Goal:

> Complete an endurance challenge.

Janus should not simply optimize a calendar and issue commands.

It should:

1. understand the goal and constraints,
2. create a feasible training structure,
3. monitor evidence,
4. explain deviations,
5. adapt the plan,
6. help the user understand training decisions,
7. identify when recovery or additional preparation is needed,
8. review outcomes.

The user remains responsible for training.

Janus improves the user's ability to plan and execute it consistently.

---

# 18. Definition of Success

The long-term success criterion for Janus is not:

> **How autonomous is Janus?**

It is:

> **How much more capable is the user because Janus exists?**

A mature Janus should make the user:

- more capable,
- more consistent,
- better informed,
- better organized,
- more confident in difficult projects,
- better at learning,
- better at making decisions,
- and more capable of turning ambitions into outcomes.

The ideal endpoint is therefore not:

```text
USER → delegates everything → JANUS
```

but:

```text
USER
  ↕
JANUS
  ↕
CAPABILITY
  ↓
OUTCOME
```

Janus should become a **force multiplier for human agency**.

---

# 19. Immediate Next Step

Before implementing the next major feature, create a short architecture/roadmap review covering:

1. current Goal → Task → Execution → Completion → Review implementation,
2. existing ADRs and enforcement mechanisms,
3. current gaps against the Agency-First model,
4. proposed `Evidence` model,
5. proposed `PersonalState` model,
6. proposed execution/support modes,
7. policy and approval boundaries,
8. roadmap ordering,
9. tests required to protect the human-in-the-loop guarantees.

The next implementation work should begin only after this review has been converted into concrete, independently verifiable tasks.

---

# 20. Guiding Statement

> **Janus exists to help a person do difficult things—not to do the person's life for them.**

> **The best Janus is not the agent that does the most. It is the system that enables the user to accomplish the most.**
