# Goal System — Product & Architecture Discovery Brief

## Status

**Status:** Discovery
**Implementation:** Not started
**Purpose:** Define the future Goal domain before implementation

---

# 1. Context

Janus currently contains a basic Goal concept.

The existing model is primarily connected to tasks and is used by the Attention Engine to detect situations such as a goal becoming stalled when all linked tasks are completed.

This model is useful but too limited for the intended direction of the product.

The Goal system should evolve from:

> A collection of related tasks

toward:

> A desired outcome with measurable progress.

Goals should become a cross-domain concept capable of tracking meaningful personal outcomes across multiple areas of life.

Examples include:

* reducing body fat percentage
* running a specific distance
* completing a marathon
* improving sleep consistency
* saving money
* learning a skill
* completing a project
* improving general wellbeing

The Goal domain should therefore not become tightly coupled to any single subsystem such as Fitness or Tasks.

---

# 2. Product Vision

The central concept is:

> A Goal represents a desired outcome. Progress toward that outcome can be measured manually, through metrics, through related actions, or automatically from other Janus domains.

A Goal may have:

* a title
* a description
* a desired outcome
* a target
* a deadline
* measurable progress
* related tasks
* milestones
* contributing domains

Not every Goal needs all of these.

The design should support simple Goals without forcing unnecessary complexity.

---

# 3. Example Goal

## Reduce body fat percentage

This is a useful reference case because it spans multiple domains.

### Desired outcome

Reduce body fat percentage.

### Primary metric

Body fat percentage.

Example:

```text
Starting value: 23%
Current value: 20%
Target value: 15%
```

### Supporting metrics

Potentially:

* body weight
* waist circumference

### Contributing activities

Fitness:

* strength training
* running
* physical activity

Future domains:

* nutrition
* sleep
* recovery
* stress management

The Goal itself should not need to understand the implementation details of all these domains.

---

# 4. Core Design Principle

Goals should model **outcomes**, not merely actions.

For example:

Bad abstraction:

```text
Goal
 ├── Run
 ├── Eat healthy
 └── Go to gym
```

These are actions.

Better abstraction:

```text
Goal
│
├── Desired outcome:
│   Reduce body fat percentage
│
├── Primary metric:
│   Body fat %
│
├── Target:
│   15%
│
├── Supporting actions:
│   Strength training
│   Running
│   Nutrition habits
│
└── Supporting metrics:
    Weight
    Waist circumference
```

Tasks and workouts may contribute to a Goal, but they are not necessarily the Goal itself.

---

# 5. Questions to Investigate

Before implementing the Goal system, the existing repository architecture must be analyzed.

The following questions should be answered.

---

## 5.1 Current Goal architecture

Investigate:

* `src/janus/models/goal.py`
* Goal-related services
* Goal persistence
* `data/goals.md`
* Goal-related tests
* Attention Engine
* Daily Briefing
* Today CLI
* Weekly Review
* Task system

Determine:

1. Where is Goal currently defined?
2. What fields does the current Goal model contain?
3. How are Goals persisted?
4. How are Goals loaded?
5. Is the Goal model currently mutable?
6. Which services consume Goals?
7. How are Goals connected to Tasks?
8. How does Attention Engine reason about Goals?
9. How does Daily Briefing use Goals?
10. How does Weekly Review use Goals?
11. Which assumptions belong to the legacy Goal design?
12. Which parts of the existing code depend on the current Goal structure?
13. Are there duplicate models or duplicate domain concepts?
14. Is there already an implicit concept of progress elsewhere in the repository?

---

# 6. Conceptual Models to Compare

The discovery should compare several possible Goal models.

The objective is not to select the most abstract architecture.

The objective is to select the simplest architecture that supports meaningful future growth.

---

## Model A — Goal as task container

Example:

```text
Goal
│
├── title
└── related_tasks
```

Example:

```text
Goal: Prepare Japan trip

Tasks:
- Buy flights
- Book hotels
- Create itinerary
```

Advantages:

* simple
* already close to the current implementation
* easy to understand

Limitations:

* no measurable outcome
* progress is indirectly tied to task completion
* unsuitable for continuous metrics
* unsuitable for goals such as body composition

The analysis should determine whether this model should remain supported as one possible progress mechanism.

---

## Model B — Goal as KPI

Example:

```text
Goal: Reduce body fat

Metric:
Body fat percentage

Current:
23%

Target:
15%
```

Advantages:

* measurable
* simple progress calculation
* useful for fitness, finance and health

Limitations:

* not every goal has a single meaningful KPI
* may oversimplify complex outcomes

The analysis should determine whether a Goal should always have one primary metric.

---

## Model C — Goal as outcome

Example:

```text
Goal
│
├── Desired outcome
│
├── Primary metric
│
├── Supporting metrics
│
├── Related actions
│
├── Milestones
│
└── Deadline
```

Example:

```text
Goal:
Reduce body fat percentage

Primary metric:
Body fat %

Supporting metrics:
Weight
Waist circumference

Contributing activities:
Strength training
Running
Nutrition
```

This is currently the preferred conceptual direction, but it must be critically evaluated.

---

## Model D — Multiple progress mechanisms

A Goal may potentially support different ways of measuring progress.

Examples:

```text
Goal
│
├── Manual progress
├── Metric progress
├── Task completion progress
├── Milestone progress
└── Automatically derived progress
```

The discovery should determine whether these should be represented as:

* Goal types
* progress strategies
* metric providers
* separate entities
* simple optional fields

Avoid introducing a generic strategy framework unless the repository genuinely needs it.

---

# 7. Progress Model

Progress is the most important architectural question.

The Goal system should support different types of progress without forcing every Goal into the same model.

---

## 7.1 Manual progress

Example:

```text
Goal:
Save 10,000 PLN

Current:
4,500 PLN

Target:
10,000 PLN
```

Progress can be calculated directly.

---

## 7.2 Metric progress

Example:

```text
Goal:
Reduce body fat percentage

Start:
23%

Current:
20%

Target:
15%
```

Important consideration:

Not every metric progresses upward.

Examples:

```text
Increase to target

0 → 100
```

```text
Decrease to target

23% → 15%
```

The design should investigate whether the system needs to support:

* increasing targets
* decreasing targets
* threshold targets
* target ranges

Do not implement all possibilities unless they are justified by realistic use cases.

---

## 7.3 Task-based progress

Example:

```text
Goal:
Prepare Japan trip

Tasks:
7

Completed:
4
```

Possible progress:

```text
4 / 7
```

The discovery should determine whether task completion is:

* a primary Goal progress mechanism
* a supporting signal
* a legacy compatibility mechanism

---

## 7.4 Milestone progress

Example:

```text
Goal:
Run a marathon

Milestones:
- Run 5 km
- Run 10 km
- Run half marathon
- Run marathon
```

The analysis should determine whether milestones need to become first-class entities.

Potential concerns:

* persistence complexity
* CLI complexity
* interaction with tasks
* duplication between milestones and tasks

---

## 7.5 Automatically derived progress

Example:

```text
Goal:
Run 100 km during September

Progress source:
Running workouts

Current:
52.3 km

Target:
100 km
```

This raises architectural questions.

Should:

```text
Goal
    ↓
Workout Analytics
    ↓
Workout data
```

or:

```text
Goal
    ↓
Generic progress provider
    ↓
Workout domain
```

or another approach be used?

The recommendation should avoid introducing a plugin system prematurely.

---

# 8. Cross-Domain Architecture

Goals should eventually interact with multiple Janus domains.

Current domains include:

* Tasks
* Events
* Workouts
* Workout Analytics

Likely future domains include:

* Nutrition
* Body Metrics
* Sleep
* Recovery
* Health / Wellbeing

The conceptual relationship may look like:

```text
                    GOAL
                      │
          ┌───────────┼───────────┐
          │           │           │
          ▼           ▼           ▼
        Tasks      Workouts     Metrics
          │           │           │
          └───────────┼───────────┘
                      │
                      ▼
                   Progress
```

The discovery should answer:

1. Should Goal directly know about every domain?
2. Should external domains expose reusable metrics?
3. Should Goals store references to data sources?
4. Should progress be calculated dynamically?
5. Should progress snapshots be persisted?
6. How should future domains be added?
7. What is the smallest architecture that remains extensible?

---

# 9. Fitness Integration Case Studies

The architecture should be tested against realistic examples.

---

## Case Study A — Reduce body fat percentage

```text
Goal:
Reduce body fat percentage

Start:
23%

Current:
20%

Target:
15%
```

Potential supporting information:

```text
Supporting metrics:
- Weight
- Waist circumference

Contributing domains:
- Strength training
- Running
- Nutrition
- Sleep
```

The Goal should not require direct knowledge of workout implementation details.

---

## Case Study B — Run 100 km during September

```text
Goal:
Run 100 km during September

Current:
52.3 km

Target:
100 km

Data source:
Running workouts
```

The architecture should determine:

* where aggregation belongs
* whether Workout Analytics should expose reusable data
* whether Goal should call analytics services
* whether time windows belong to Goal configuration
* whether generic providers are necessary

---

## Case Study C — Complete a marathon

This Goal is more complex.

Possible interpretations:

* metric-based
* milestone-based
* task-based
* hybrid

The design should recommend the simplest useful representation.

---

# 10. CLI Product Design

The future Goal CLI should be designed around real user workflows.

Potential commands include:

```bash
janus goal list
janus goal show <name>
janus goal add ...
janus goal update ...
janus goal progress ...
janus goal complete ...
```

These commands are only examples.

The discovery should design the smallest useful MVP CLI.

Consider workflows such as:

### Creating a metric Goal

```bash
janus goal add "Reduce body fat"
```

### Recording a measurement

```bash
janus goal progress "Reduce body fat" 20
```

### Viewing progress

```bash
janus goal show "Reduce body fat"
```

### Listing active Goals

```bash
janus goal list
```

Avoid designing a large CLI with many commands before the domain model requires them.

---

# 11. Persistence Design

The current repository uses markdown-based persistence.

The discovery should investigate whether Goal data should remain in:

```text
data/goals.md
```

Questions:

1. Can the existing format represent metric goals?
2. Can it represent a target?
3. Can it represent progress?
4. Can it represent multiple metrics?
5. Can it represent deadlines?
6. Can it represent historical measurements?
7. Should measurements belong inside `goals.md`?
8. Should body measurements eventually become a separate domain?
9. Which data belongs to Goal versus a measurement history?

Prefer minimal evolution of the existing persistence architecture.

Do not redesign the entire data layer without a strong reason.

---

# 12. Attention Engine Integration

The existing Attention Engine should remain stable.

Future Goal functionality could eventually provide additional attention signals.

Potential examples:

* deadline approaching
* progress behind expected trajectory
* no progress for a long period
* metric moving in the wrong direction
* missing measurement updates
* goal has no active next action

These are future possibilities.

The current discovery should determine:

1. Which signals are realistic?
2. Which data model decisions would support them?
3. Which abstractions should be avoided?
4. Can the current `AttentionItem` remain generic?
5. How can richer Goals integrate without redesigning the Attention Engine?

Do not implement new attention signals during the first Goal milestone unless explicitly justified.

---

# 13. Migration and Compatibility

Existing Goals already exist in the repository.

The new design should consider backward compatibility.

Questions:

1. Can existing task-based Goals remain valid?
2. Can legacy Goals be represented in the new model?
3. Is backward-compatible parsing necessary?
4. Should legacy Goals automatically become task-progress Goals?
5. Should a migration script exist?
6. Can old and new Goal formats coexist temporarily?

The preferred migration approach should be:

* safe
* incremental
* easy to understand
* low risk

Avoid destructive migrations.

---

# 14. Architecture Principles

The recommended architecture should follow these principles.

## Prefer explicit models

Prefer:

```python
MetricGoal
```

or:

```python
Goal(
    progress_type="metric"
)
```

only after evaluating which option is simpler.

Do not introduce abstractions merely because they might support hypothetical future features.

---

## Avoid premature plugin systems

Do not introduce:

```text
GoalProgressProviderRegistry
```

or equivalent infrastructure unless the repository already has multiple concrete integrations that justify it.

Start with explicit integrations.

Generalize only when repetition appears.

---

## Preserve domain boundaries

Goal should not become a giant service that calculates:

* workout statistics
* nutrition statistics
* body metrics
* sleep metrics

Domain-specific services should remain responsible for their own calculations.

Goal should orchestrate or consume results where appropriate.

---

## Prefer incremental evolution

The first Goal implementation should solve one meaningful problem well.

Do not attempt to build:

* a generic life operating system
* a universal KPI framework
* a plugin architecture
* a dashboard system
* predictive trajectory analytics

unless a concrete requirement requires them.

---

# 15. Discovery Tasks

The architecture discovery should proceed through the following phases.

---

## Phase 1 — Repository archaeology

Inspect:

* models
* services
* integrations
* CLI
* tests
* persistence
* existing Goal usage

Produce an architecture map.

---

## Phase 2 — Domain analysis

Compare the Goal models described in this document.

Identify:

* strengths
* weaknesses
* compatibility
* implementation complexity

Recommend one direction.

---

## Phase 3 — Progress architecture

Define how progress should work for:

* manual goals
* metric goals
* task-based goals
* future automatically derived goals

Recommend the minimum viable model.

---

## Phase 4 — Persistence design

Determine:

* data ownership
* markdown format
* compatibility strategy
* measurement history strategy

---

## Phase 5 — CLI design

Define the smallest useful CLI.

Focus on:

* creating Goals
* viewing Goals
* updating progress

---

## Phase 6 — Integration analysis

Analyze interaction with:

* Tasks
* Workouts
* Workout Analytics
* Attention Engine
* future Nutrition
* future Health / Wellbeing

---

## Phase 7 — Migration analysis

Define how existing Goals transition to the new model.

---

## Phase 8 — Implementation roadmap

Produce concrete milestones.

Each milestone should include:

* purpose
* files to create
* files to modify
* API changes
* persistence changes
* tests
* risks

---

# 16. Required Final Deliverable

The architecture discovery should produce a document:

```text
docs/goal_system_design.md
```

The document should contain the following sections.

---

## 1. Executive Summary

Maximum 15 bullet points.

---

## 2. Current Goal Architecture

Include:

* existing model
* persistence
* services
* consumers
* dependencies

Include an architecture diagram.

---

## 3. Problems With the Current Model

Categorize findings:

```text
BLOCKER
SHOULD FIX
DESIGN LIMITATION
OPTIONAL
```

---

## 4. Recommended Goal Domain Model

Include:

* entities
* relationships
* responsibilities
* example Python dataclasses

---

## 5. Progress Architecture

Explain how progress works.

Include examples for:

* body fat goal
* running distance goal
* task-based goal

---

## 6. Persistence Recommendation

Include example data formats.

Explain ownership of:

* Goal definition
* target
* current progress
* historical measurements

---

## 7. CLI Design

Show example commands.

Show example output.

Recommend the MVP command set.

---

## 8. Cross-Domain Integration

Explain interaction with:

* Tasks
* Workouts
* Workout Analytics
* future Nutrition
* future Health / Wellbeing

---

## 9. Migration Strategy

Explain compatibility with existing Goals.

---

## 10. Phased Implementation Roadmap

Break implementation into milestones.

Each milestone should specify:

* objective
* files
* tests
* migration risk
* regression risk
* complexity

---

## 11. Recommended MVP

Be explicit.

Separate:

```text
BUILD NOW
```

from:

```text
BUILD LATER
```

The MVP should solve at least one meaningful real-world Goal use case.

---

## 12. File-Level Implementation Map

For every proposed file specify:

```text
CREATE
MODIFY
NO CHANGE
```

---

## 13. Risks

Include:

* overengineering risk
* coupling risk
* migration risk
* persistence risk
* CLI complexity risk

---

## 14. Final Recommendation

Provide one clear architecture recommendation.

Do not leave multiple alternatives unresolved.

---

# 17. Constraints

During architecture discovery:

* Do not implement the Goal system.
* Do not modify production code.
* Do not modify existing tests.
* Do not modify production data.
* Do not commit changes.
* Do not perform unrelated refactoring.

You may:

* inspect the entire repository
* inspect git history
* inspect tests
* run targeted tests
* run the full test suite
* trace imports
* search references
* inspect data formats

Temporary files may be created outside the repository if necessary.

---

# 18. Autonomous Decision-Making

The discovery agent should not stop when multiple design options exist.

When uncertain:

1. inspect the implementation
2. inspect usage sites
3. inspect tests
4. inspect git history
5. compare alternatives
6. make the most conservative justified recommendation

The agent should prefer:

```text
simple
↓
explicit
↓
extensible
```

over:

```text
generic
↓
abstract
↓
theoretically flexible
```

The final architecture should be detailed enough that a future implementation agent can execute the recommended MVP without repeating the discovery process.

