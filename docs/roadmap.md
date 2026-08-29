# Hermes / Janus Roadmap

This document describes strategic direction.

Implementation status must be verified against the repository and should not be inferred solely from this roadmap.

---

# Product Direction

Hermes is evolving toward a persistent personal Chief of Staff capable of working across multiple domains.

The development strategy is to build domain capabilities incrementally while maintaining:

- clear data ownership,
- deterministic foundations,
- useful integrations,
- curated long-term knowledge.

---

# Current Focus Areas

## 1. Personal Operations

Direction:

- task awareness,
- calendar integration,
- daily briefings,
- attention management,
- prioritization.

Goal:

Create a useful operational layer that helps maintain awareness of commitments and priorities.

---

## 2. Fitness MVP

Direction:

Build a structured fitness domain supporting:

- strength workouts,
- running workouts,
- persistent workout history,
- historical queries,
- deterministic analysis,
- progress tracking,
- Obsidian integration.

Future evolution:

- Telegram workout input,
- screenshot-based input,
- activity imports,
- richer progress analysis,
- periodic reviews.

---

## 3. Obsidian Knowledge Layer

Direction:

Establish Obsidian as a curated long-term knowledge system.

Focus areas:

- structured exports,
- domain-specific notes,
- links between related knowledge,
- durable summaries,
- decisions,
- historical records.

The goal is not to mirror every operational workspace into Obsidian.

---

## 4. Research and Investing

Direction:

Support long-running research workflows.

Potential capabilities:

- company workspaces,
- research history,
- investment thesis tracking,
- catalysts,
- risks,
- monitoring,
- curated investment knowledge.

---

## 5. Agent Reliability

Direction:

Improve the reliability of autonomous work.

Focus areas:

- task checkpoints,
- repository verification,
- test execution,
- recovery after interrupted work,
- explicit uncertainty,
- better queue and task management.

The objective is to make long-running autonomous work predictable and reviewable.

---

# Future Domains

The following domains are strategically relevant but should be introduced only when they provide clear value.

## Travel

Potential capabilities:

- destination research,
- planning,
- itineraries,
- logistics,
- monitoring.

---

## Personal Knowledge

Potential capabilities:

- structured note generation,
- automatic linking,
- knowledge summaries,
- periodic reviews,
- decision history.

---

## Monitoring

Potential capabilities:

- research monitoring,
- company monitoring,
- important news,
- project changes,
- relevant personal signals.

Monitoring should prioritize relevance over notification volume.

---

# Long-Term Direction

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
