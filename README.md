# Janus

**Personal Chief of Staff for proactive personal life and work management.**

Janus is the persistent state, planning, and decision-support layer for the [Hermes](https://github.com/NousResearch/hermes-agent) personal agent system.

Hermes is responsible for **execution**.

Janus is responsible for **knowing what matters, why it matters, what should happen next, and whether it actually happened**.

Janus keeps structured personal state in local files and exposes deterministic CLI workflows for goals, tasks, workouts, reviews, calendars, research, decisions, and execution feedback.

---

## Why Janus?

A normal task manager answers:

> What tasks do I have?

Janus tries to answer a larger question:

> **Given my goals, commitments, current state, recent activity, and unfinished work — what deserves my attention now, what should happen next, and what evidence do I have that I am making progress?**

The core loop is:

```text
                    ┌─────────────┐
                    │    Goals    │
                    └──────┬──────┘
                           │
                           ▼
                 ┌──────────────────┐
                 │ Projects / Plans │
                 └────────┬─────────┘
                          │
                          ▼
                    ┌───────────┐
                    │   Tasks   │
                    └─────┬─────┘
                          │
                          ▼
                 ┌─────────────────┐
                 │    Execution    │
                 │     Hermes      │
                 └────────┬────────┘
                          │
                          ▼
                    ┌───────────┐
                    │  Evidence │
                    └─────┬─────┘
                          │
                          ▼
                ┌───────────────────┐
                │ Completion /      │
                │ Review            │
                └─────────┬─────────┘
                          │
                          ▼
                 ┌─────────────────┐
                 │ Strategic State │
                 └────────┬────────┘
                          │
                          └──────► Next actions
```

This creates a closed loop:

**Goal → Task → Execution → Evidence → Completion → Review → Updated state → Next action**

---

# What Janus manages

## Goals

Long-term outcomes with:

* measurable metrics
* current and target values
* deadlines
* direction of change
* related tasks
* completion state

Example:

```text
Goal: Complete autumn endurance challenge

Metric: Training preparation sessions
Target: 12 sessions
Direction: increase

Related tasks:
- Prepare training plan
- Buy running shoes
```

Goals provide context for tasks rather than being isolated lists of aspirations.

---

## Tasks

Tasks are the executable layer.

Each task can have:

* priority
* due date
* state
* progress
* relationship to a goal
* execution/evidence information

Example:

```text
- [ ] Prepare AI/agent engineering development plan
  due: 2026-09-15
  priority: 2
```

The task lifecycle is explicit:

```text
todo
  │
  ▼
in_progress
  │
  ├──────► blocked
  │
  ▼
completed
```

Completion is represented by the `[x]` checkbox. `state: done` is intentionally not used as a second source of truth.

---

## Daily briefing

The daily briefing combines several sources of state:

```bash
uv run janus today
```

It can include:

* upcoming Google Calendar events
* open tasks
* active goals
* attention items
* deterministic attention ranking
* a suggested focus item

Typical usage:

```text
JANUS — TODAY

SCHEDULE
- 09:00 — Daily standup
- 18:00 — Training

REQUIRES ATTENTION
1. Prepare training plan [FOCUS]
2. Review open project task
3. Follow up on decision

SUGGESTED FOCUS
1. Prepare training plan
```

The important distinction is that Janus does not simply dump everything that exists.

It tries to reduce the state to:

> **What requires attention now?**

---

# Typical Janus workflow

A normal day can look like this:

### 1. Start with the state

```bash
uv run janus today
```

Review:

* calendar
* attention items
* active goals
* suggested focus

### 2. Add or update work

```bash
uv run janus task add "Review architecture proposal" --priority 2
```

Move work forward:

```bash
uv run janus task state "Review architecture proposal" --state in_progress
```

Update progress:

```bash
uv run janus task progress "Review architecture proposal" --pct 70
```

Complete it:

```bash
uv run janus task complete "Review architecture proposal"
```

### 3. Execute

Tasks that require agent execution can be handed to Hermes.

The separation is intentional:

```text
Janus
  └── decides / tracks / evaluates

Hermes
  └── executes / interacts with tools / produces evidence
```

### 4. Review the result

Execution should produce evidence:

* changed files
* tests
* command output
* research artifacts
* decisions
* implementation results
* external actions

Evidence can then be used to update Janus state.

### 5. Review the system

```bash
uv run janus weekly
```

The weekly review summarizes:

* completed tasks
* remaining work
* tasks needing attention
* goal progress
* suggested next steps

---

# Goals in practice

List goals:

```bash
uv run janus goal list
```

Inspect a goal:

```bash
uv run janus goal show "Complete autumn endurance challenge"
```

Create a measurable goal:

```bash
uv run janus goal add \
  "Complete autumn endurance challenge" \
  --metric "Training preparation sessions" \
  --unit "sessions" \
  --start 0 \
  --current 0 \
  --target 12 \
  --direction increase
```

Update progress:

```bash
uv run janus goal update \
  "Complete autumn endurance challenge" \
  --current 4
```

Connect a task to a goal:

```bash
uv run janus goal add \
  "Improve AI/agent engineering capability" \
  --related-task "Prepare AI/agent engineering development plan"
```

The goal/task relationship allows Janus to distinguish:

```text
I have completed a task
```

from:

```text
I am actually making progress toward something important
```

Those are not always the same thing.

---

# Example: professional development

One of the workflows Janus is designed for is turning an ambiguous development objective into concrete work.

For example:

```text
Goal
└── Improve AI / agent engineering capability
    │
    ├── Identify key competencies
    │   ├── AI / LLM systems
    │   ├── agent systems
    │   ├── architecture
    │   ├── distributed systems
    │   ├── cloud
    │   └── reliability
    │
    ├── Build development plan
    │
    ├── Execute selected projects
    │
    └── Collect evidence
        ├── shipped implementation
        ├── design decisions
        ├── tests
        ├── research
        └── reviews
```

This is more useful than keeping a single task such as:

```text
Learn AI agents
```

because Janus can track the chain from intention to evidence.

---

# Example: engineering work

Janus can also manage software-engineering work performed through Hermes.

A typical workflow:

```text
Goal
└── Improve Janus execution reliability
        │
        ▼
Task
└── Implement safe sync-and-integrate workflow
        │
        ▼
Research
└── Investigate existing repository state
        │
        ▼
Decision
└── ADR-004
        │
        ▼
Execution
└── Hermes implements the change
        │
        ▼
Evidence
├── changed source files
├── tests
├── verification output
└── review
        │
        ▼
Completion
        │
        ▼
Strategic review
```

This is the pattern behind workflows such as:

* ADR-003 — review topology
* ADR-004 — safe sync-and-integrate workflow
* ADR-005 — activity data ingestion

The important part is not the ADR itself.

The important part is that a decision becomes **executable work**, and the result becomes **evidence-backed state**.

---

# Research → decision → action

Janus is also designed to prevent research from becoming an endpoint.

The intended flow is:

```text
Question
   │
   ▼
Research
   │
   ▼
Findings
   │
   ▼
Decision
   │
   ▼
Action
   │
   ▼
Evidence
   │
   ▼
Updated state
```

For example:

```text
Question:
How should Janus synchronize work with Hermes?

        ↓

Research:
Inspect repository, existing implementation,
tests and previous decisions.

        ↓

Finding:
Existing synchronization logic is fragmented.

        ↓

Decision:
Use the workflow described by ADR-004.

        ↓

Action:
Implement and verify the integration.

        ↓

Evidence:
Tests + repository state + verification results.

        ↓

State:
Decision implemented.
Follow-up work closed or generated explicitly.
```

This keeps research connected to execution.

---

# Workouts and activity

Janus can also track structured training data.

Add a strength workout:

```bash
uv run janus workout add \
  --type strength \
  --exercise "Back Squat" \
  --sets "5x80kg@8,5x80kg@8.5"
```

Add a run:

```bash
uv run janus workout add \
  --type running \
  --distance 8.74 \
  --duration 69.77 \
  --hr 151 \
  --elevation 69.4
```

View recent workouts:

```bash
uv run janus workout show
```

View a period:

```bash
uv run janus workout show \
  --from 2026-09-01 \
  --to 2026-09-30
```

View exercise progression:

```bash
uv run janus workout show --exercise "Back Squat"
```

Analytics:

```bash
uv run janus workout summary
```

or:

```bash
uv run janus workout summary --running
```

```bash
uv run janus workout summary --exercise "Back Squat"
```

The purpose is not to create another fitness tracker.

The purpose is to make activity another source of structured evidence for goals and reviews.

---

# Telegram

Janus can deliver the same operational views to Telegram.

Daily briefing:

```bash
uv run janus telegram
```

Weekly review:

```bash
uv run janus telegram-weekly
```

This makes Telegram a lightweight interface while Janus remains the persistent state layer.

---

# Google Calendar

Calendar integration is read-only.

Configure calendars in:

```text
config/config.toml
```

Example:

```toml
[google_calendar]

[[google_calendar.calendars]]
id = "JOB_CALENDAR_ID"
name = "Job"

[[google_calendar.calendars]]
id = "PERSONAL_CALENDAR_ID"
name = "Personal"
```

Then:

```bash
uv run janus today
```

On the first run, Janus performs the OAuth flow and stores the generated token locally.

Calendar events become context for the daily briefing rather than another task database.

---

# Data model

Janus deliberately keeps its persistent state simple.

```text
data/
├── tasks.md
├── goals.md
├── workouts.md
├── inbox.md
├── followups.md
└── research.md
```

The `data/` directory is created at runtime and is gitignored — the repository
tracks no runtime state, only the format conventions and the code that
reads/writes it.

The current core data files contain:

| File              | Purpose                                              |
| ------------------ | ---------------------------------------------------- |
| `data/tasks.md`    | Open and completed tasks                             |
| `data/goals.md`    | Long-term goals, metrics and related tasks           |
| `data/workouts.md` | Strength and running activity                        |
| `data/inbox.md`    | Inbox items pending triage                           |
| `data/followups.md`| Follow-up items linked to decisions or actions       |
| `data/research.md` | Research findings, artifacts and knowledge summaries |

The data is human-readable and can be inspected directly without Janus.

Example task:

```markdown
- [ ] Review architecture proposal | due: 2026-09-20 | priority: 2 | state: in_progress | progress: 70
```

Example goal:

```markdown
## Goal: Improve AI / agent engineering capability

Description: Build measurable capability through projects and evidence.
Status: active
Deadline: 2026-12-31
Metric: Completed evidence-backed projects
Unit: projects
Start: 0
Current: 1
Target: 4
Direction: increase

Related tasks:
- Prepare AI/agent engineering development plan
```

This file-backed approach makes the system:

* inspectable
* debuggable
* portable
* easy to version
* resilient to changes in the CLI

---

# Verification

The repository is verified by running the full test suite:

```bash
uv run pytest tests/
```

Exit code 0 means all checks pass. See `docs/verification.md` for the
verification contract, success criteria, CI configuration, and the
pre-completion checklist enforced before reporting a task complete.

The `src/janus/verification.py` module additionally provides a
contract-based verification pipeline (`ContractVerifier`) that can check:

```python
from janus.verification import ContractVerifier
verifier = ContractVerifier.load("contract.yaml")
verifier.verify(Path("."))
```

* required files
* immutable files
* modified-file scope
* untracked files
* required/forbidden AST symbols
* verification commands

This is particularly useful when Janus delegates implementation work to an agent.

Instead of trusting:

```text
"Implementation complete."
```

the system can verify repository state against an explicit contract.

See:

* `docs/verification.md`
* `docs/examples/contract_phase1.yaml`

---

# Architecture

At a high level:

```text
                    ┌───────────────────┐
                    │      Telegram     │
                    └─────────┬─────────┘
                              │
                              ▼
┌──────────────┐       ┌───────────────┐
│ Google       │──────►│     Janus     │
│ Calendar     │       │               │
└──────────────┘       │  State        │
                       │  Goals        │
                       │  Tasks        │
                       │  Reviews       │
                       │  Research      │
                       │  Decisions     │
                       │  Evidence      │
                       └───────┬───────┘
                               │
                               │ execution
                               ▼
                       ┌───────────────┐
                       │    Hermes     │
                       │               │
                       │ agent runtime │
                       │ tools         │
                       │ execution     │
                       └───────┬───────┘
                               │
                               │ results / evidence
                               ▼
                       ┌───────────────┐
                       │     Janus     │
                       │ updated state │
                       └───────────────┘
```

### Janus

Owns:

* persistent state
* domain models
* goals
* tasks
* planning
* deterministic analysis
* reviews
* decisions
* evidence
* strategic state

### Hermes

Owns:

* agent execution
* tool use
* repository interaction
* external actions
* long-running execution
* execution feedback

The boundary is intentional.

**Janus decides what should happen and records what happened. Hermes performs the work.**

---

# Installation

## Requirements

* Python 3.11+
* [`uv`](https://docs.astral.sh/uv/)

Optional integrations:

* Google Calendar OAuth credentials
* Telegram bot token and chat ID

Install dependencies:

```bash
uv sync
```

Run Janus:

```bash
uv run janus
```

With no arguments Janus prints usage and available commands. Use
`janus <command>` with no subcommand for usage on that command group
(e.g. `janus task`, `janus goal`, `janus inbox`).

---

# Development

Run the test suite:

```bash
uv run pytest tests/ -v
```

The project uses `pytest` for automated testing.

Source layout:

```text
src/janus/
├── __init__.py            # CLI entry point (janus)
├── _log.py
├── logging_config.py
├── today.py               # daily briefing
├── weekly.py              # weekly review
├── telegram_weekly_cli.py
├── tasks_cli.py
├── workout_cli.py
├── goals_cli.py
├── inbox_cli.py
├── followup_cli.py
├── research_cli.py
├── decision_cli.py
├── status_cli.py
├── strategic_cli.py
├── git_sync.py            # safe sync-and-integrate (ADR-004)
├── integration.py
├── verification.py
├── integrations/
├── models/
└── services/

data/
config/
docs/
scripts/
tests/
```

### CLI commands

Janus exposes a flat command tree. Each group supports a `--help`-style usage
summary when invoked with no subcommand.

```text
janus today                 Daily briefing
janus telegram              Send daily briefing to Telegram
janus telegram-weekly       Send weekly review to Telegram
janus task add|list|state|progress|complete
janus workout add|show|summary
janus goal list|show|add|update|complete|milestone|project|next|health|audit|skills|set-skill
janus weekly                Weekly review
janus status                Strategic status summary
janus inbox list|pending|triage
janus followup list|add|show|update|complete|convert-to-task
janus research add|show|list|link|promote-finding
janus decision propose|link-finding|link-goal|list|show
```

The `models/` layer contains domain concepts such as:

* `Task`
* `Goal`
* `Milestone`
* `Project`
* `Workout`
* `Event`
* `AttentionItem`
* `DailyBriefing`
* `WeeklyReview`
* `Source`
* `Finding`
* `ResearchArtifact`
* `KnowledgeSummary`
* `Decision`
* `FollowUp`
* `MetricSnapshot`
* `RecommendedAction`
* `GoalSignal`
* `GoalHealthAssessment`
* `GoalIntegrityReport`

The `services/` layer contains domain logic for:

* briefing (daily / weekly)
* goals (progress, health, integrity audit, skill tracking)
* tasks (parsing, persistence, completion, placement, overload)
* workouts (analytics, progression)
* projects (hierarchy, progress)
* milestones
* planning (next-action derivation, milestone task inference)
* research / knowledge pipeline (findings, artifacts, knowledge summaries)
* decisions and follow-ups
* attention (ranking, recommendations)
* evidence propagation / execution feedback
* measurement collection and log
* activity data ingestion (calendar free/busy, replenishment)
* git sync (ADR-004 sync primitive)

---

# Security and local configuration

The following files contain local credentials or configuration and should not be committed:

```text
credentials.json
token.json
config/config.toml
```

Google Calendar access uses the read-only calendar scope.

Telegram credentials are stored locally in `config/config.toml`.

---

# Design principles

## 1. State before automation

Janus should know the current state before deciding what to do.

## 2. Goals provide context

A task without context is just work.

A task connected to a meaningful goal can be evaluated in terms of progress.

## 3. Execution must produce evidence

"Done" should ideally be backed by something observable:

```text
code
tests
documents
measurements
decisions
external results
```

## 4. Human-readable persistence

The canonical state should remain understandable without the application.

## 5. Deterministic analysis where possible

If a result can be derived deterministically from stored state, Janus should not require an LLM to produce it.

## 6. Separate planning from execution

Janus and Hermes have different responsibilities.

```text
Janus  → What / Why / What next?
Hermes → How / Execute
Janus  → What happened?
```

## 7. Close the loop

The system should not stop at:

```text
task created
```

or even:

```text
task executed
```

The useful endpoint is:

```text
goal
 → task
 → execution
 → evidence
 → completion
 → review
 → updated strategic state
 → next action
```

---

# Roadmap philosophy

Janus started as a small CLI for personal goals and tasks.

The system is evolving toward a **personal operating system with an agent execution layer**.

The direction is:

```text
Task manager
     ↓
Goal manager
     ↓
Personal operating system
     ↓
Chief of Staff
     ↓
Goal-directed agent system
```

The defining property is not the number of commands.

It is the closed feedback loop between:

**intent → planning → execution → evidence → review → action.**

---

# Contribution guidelines

Janus is an active personal-infrastructure project. To contribute:

1. **Verify the repository** — run `uv run pytest tests/` from the repository
   root and confirm a green exit code before opening a change. See
   `docs/verification.md` for the full verification contract.
2. **Use the safe sync-and-integrate workflow** (ADR-004). Branches are kept
   linear and fast-forward-friendly via rebase. See
   `docs/design/sync_integration_workflow_design.md`.
3. **Keep state human-readable** — persistent data files use plain Markdown so
   they remain inspectable without Janus. Follow the existing file-backed
   format conventions under `src/janus/integrations/`.
4. **Close the loop** — implementation should produce evidence (tests, changed
   files, verification output) that feeds back into strategic state.
5. **Do not commit local credentials.** The following must remain untracked:
   `credentials.json`, `token.json`, `config/config.toml`, and any `.env*` file
   (except `.env.example`).

Design decisions are recorded as ADRs in `docs/decisions/` and design
specifications in `docs/design/`. New work that touches architecture should
reference or update the relevant document.

---

# License

The Janus source repository does not currently ship a `LICENSE` file. Until an
explicit license is added, treat the project as **all-rights-reserved** and do
not copy, redistribute, or build on it without the author's permission.

The underlying [Hermes agent system](https://github.com/NousResearch/hermes-agent)
and its dependencies carry their own licenses.
