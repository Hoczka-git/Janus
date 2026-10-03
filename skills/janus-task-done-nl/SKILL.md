---
name: janus-task-done-nl
description: >
  Mark a Janus task completed from natural language.
version: 0.1.0
author: Hermes agent (personal skill)
license: MIT
---

# Janus — Natural Language Task Complete

## When to Use

Use this skill when the user wants to mark a Janus task as done using natural language — for example:

- "Zrób na to zadanie"
- "Oznacz Rozpocząć implementację Janusz jako ukończone"
- "Completed buy running shoes"
- "Zrobione — posprzątać łazienkę"

The skill interprets the request, identifies the task by its title, and calls the existing Janus CLI. It never edits `data/tasks.md` directly.

**When NOT to use:** when the user gives the exact task title and just wants the command run — in that case call `janus task complete` directly without the interpretation layer.

**Responsibility split:**
- Hermes: understand intent, match task title, call CLI.
- Janus: validation, persistence, write to `data/tasks.md`.

**Never:** edit `data/tasks.md` directly. Always go through the CLI.

## CLI to call

```bash
cd /home/dan11hermes/workspaces/janus && \
uv run janus task complete "TASK TITLE"
```

## Step 1 — Extract task title

Convert the request into the exact task title as it appears in Janus.

Rules:
- Match the task title verbatim if the user provides it (e.g. "Rozpocząć implementację Janusz").
- If the user gives a natural-language confirmation ("zrobione", "około to", "done"), scan `data/tasks.md` for the most recently added or most recently mentioned open task and confirm with the user before completing.
- Keep the title exactly as Janus stores it — do not rephrase.

## Step 2 — Locate the task

Two cases:

**Explicit title provided.** Use it directly. Do not search — run the CLI with that title.

**Implicit / ambiguous.** When the user says something like "zrób na to" without naming the task:
1. Read the current open tasks from `data/tasks.md`.
2. If exactly one open task exists, use it.
3. If multiple open tasks exist, ask the user which one they mean — do not guess.
4. If the user recently mentioned a specific task in this conversation, prefer that one but still confirm if ambiguity remains.

## Step 3 — Execute and report

Run:

```bash
cd /home/dan11hermes/workspaces/janus && \
uv run janus task complete "TASK TITLE"
```

On success, report briefly:

"Completed task: <title>"

On failure (not found, multiple matches), report the error from Janus and do not retry indefinitely. If Janus reports multiple open matches, list the candidate titles and ask the user to pick one.

## Edge cases

- Title not found in open tasks → ask the user whether the task exists under a different title or was already completed.
- Multiple open tasks with similar titles → list candidates, ask for disambiguation.
- Task already completed (`[x]`) → report that it is already marked completed; do not touch the file.
- Empty or whitespace-only request → ask the user for the task title.
- User says something that does not correspond to any known task → ask for clarification; do not create a task under completion intent.

## Examples

Request: "Zrób na to zadanie — Rozpocząć implementację Janusz"
→ title: "Rozpocząć implementację Janusz", run `janus task complete "Rozpocząć implementację Janusz"`.

Request: "Oznacz Spacer jako zrobione"
→ title: "Spacer", run `janus task complete "Spacer"`.

Request: "Zrobione"
→ inspect open tasks; if only one, confirm and complete; if multiple, ask which one.

Request: "Completed buy running shoes"
→ title: "Buy running shoes", run `janus task complete "Buy running shoes"`.
