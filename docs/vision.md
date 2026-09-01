# Hermes / Janus Vision

## Purpose

Hermes and Janus together form a persistent personal operational system designed to help manage projects, knowledge, research, personal operations and long-term goals.

The system should move beyond traditional conversational assistance.

Its role is to maintain useful context across domains, work autonomously on well-defined tasks, preserve structured history and transform fragmented information into actionable knowledge, insights and decisions.

The long-term objective is not to build another chatbot.

The objective is to build a personal operational system that can understand ongoing work and personal state, maintain useful context over time, help move important areas of life and work forward, and improve its usefulness as structured history accumulates.

---

# System Model

The system consists of complementary layers with clearly separated responsibilities.

## Hermes

Hermes is the agent execution, orchestration and interaction layer.

Hermes is responsible for:

- interacting with the user,
- understanding goals and requests,
- planning work,
- coordinating tools and integrations,
- performing autonomous work where appropriate,
- managing agent execution,
- dispatching work to specialized agent profiles,
- managing workspaces and execution runs,
- coordinating implementation and review workflows,
- monitoring relevant information,
- maintaining situational awareness,
- reporting results,
- asking for decisions when human judgment is required.

Hermes should behave like a capable Chief of Staff rather than a passive question-answering system.

Hermes owns the execution workflow.

Where Hermes already provides infrastructure, Janus should integrate with it rather than duplicate it.

Examples include:

- agent orchestration,
- Kanban task execution,
- agent assignment,
- execution runs,
- workspaces and worktrees,
- implementation and review workflows,
- task dependencies,
- dispatching and retries.

---

## Janus

Janus is the persistent application, domain and personal state layer.

Janus is responsible for:

- domain models,
- business logic,
- persistence,
- structured personal data,
- historical records,
- deterministic analysis,
- domain-specific integrations,
- goal and task state,
- workout and activity data,
- daily reports,
- reflections,
- health and wellbeing events,
- weekly and long-term reviews,
- analytics and pattern detection.

Janus should preserve structured state that remains useful independently of any individual conversation or agent run.

Hermes should use Janus capabilities rather than duplicating domain logic inside prompts whenever practical.

Janus owns the durable representation of what is known, what happened and how important areas are progressing.

---

# Responsibility Boundary

The core architectural principle is:

> Hermes executes and orchestrates. Janus stores, models, analyzes and evaluates persistent state.

Conceptually:

```text
User
 │
 ├── Telegram
 ├── ChatGPT
 └── Future interfaces
 │
 ▼
Hermes
Interaction / Agents / Orchestration / Execution
 │
 │ actions, requests, observations
 ▼
Janus
Domain Models / Business Logic / Persistent State
 │
 ▼
Structured History
 │
 ▼
Analysis / Patterns / Insights
