# Hermes / Janus Vision

## Purpose

Hermes is a persistent personal AI Chief of Staff designed to help manage projects, knowledge, research and personal operations.

Hermes should move beyond traditional conversational assistance.

Its role is to maintain context across domains, work autonomously on well-defined tasks, integrate information from multiple systems and transform fragmented information into structured knowledge and actionable insights.

The long-term objective is not to build another chatbot.

The objective is to build a personal operational system that can understand ongoing work, maintain useful context and help move important areas of life and work forward.

---

## Target Users

Hermes is built for a single primary user context: an individual professional who wants a dependable local assistant integrated with their own tools, data, and workflows.

That user typically values:

- working across projects, research, fitness, travel, and personal operations without fragmenting context,
- keeping data locally and under personal control where practical,
- deterministic foundations for important analysis and records,
- assistive autonomy for well-defined work rather than constant manual prompting,
- curated long-term knowledge that remains readable and navigable over time.

Hermes is not designed as a general-purpose consumer assistant for unrelated audiences. Its direction is shaped by the needs of one primary user and by the constraints of a tightly integrated personal system.

---

## Strategic Direction

Hermes is evolving toward a persistent personal Chief of Staff capable of working across multiple domains.

The development strategy is to build domain capabilities incrementally while maintaining:

- clear data ownership,
- deterministic foundations,
- useful integrations,
- curated long-term knowledge.

The system should become more useful as it accumulates context, domain knowledge, and reliable operational capabilities. Progress is measured less by conversational breadth and more by whether Hermes can responsibly carry work forward, keep commitments visible, and reduce friction in the areas that matter most to the user.

---

## Long-Term Direction

The desired system architecture is gradually moving toward:

```text
Multiple Information Sources
            │
            ▼
         Hermes
Agent / Reasoning / Orchestration
            │
            ▼
          Janus
Domain Logic / Models / Integrations
            │
     ┌──────┼──────┐
     ▼      ▼      ▼
 Operational  Structured  Curated
   Data         Data      Knowledge
                         │
                         ▼
                      Obsidian
```

In the long term, Hermes should feel less like a tool that is asked questions and more like a persistent layer that understands ongoing work and helps move it forward.

That direction includes:

- deeper awareness of tasks, commitments, and priorities,
- stronger domain capabilities in areas such as fitness, research, and personal operations,
- Obsidian as the curated long-term knowledge layer rather than a temporary note store,
- more reliable autonomous work with explicit checkpoints, verification, and recovery,
- interfaces and integrations tuned to how the user actually works.

The emphasis is on usefulness, continuity, and trust over time rather than on expanding into unrelated capabilities.

---

# System Model

The system consists of several complementary layers.

## Hermes

Hermes is the agent and orchestration layer.

Hermes is responsible for:

- interacting with the user,
- understanding goals and tasks,
- planning work,
- coordinating tools and integrations,
- performing autonomous work where appropriate,
- monitoring relevant information,
- maintaining situational awareness,
- reporting results,
- asking for decisions when human judgment is required.

Hermes should behave like a capable Chief of Staff rather than a passive question-answering system.

---

## Janus

Janus is the application and domain layer powering Hermes capabilities.

Janus is responsible for:

- domain models,
- business logic,
- persistence,
- integrations,
- deterministic analysis,
- structured data handling.

Hermes should use Janus capabilities rather than duplicating domain logic inside prompts whenever practical.

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
Agent / Orchestration / Reasoning
 │
 ▼
Janus
Application Logic / Models / Integrations / Data
```
