---
name: janus-task-add-nl
description: >
  Use when adding a task to Janus from natural language.
version: 0.1.0
author: Hermes agent (personal skill)
license: MIT
---

# Janus — Natural Language Task Add

## When to Use

Use this skill when the user wants to add a task to Janus using natural language
— for example:

- "Add buy running shoes before Friday"
- "Remind me to book a dentist appointment tomorrow"
- "Dodaj zadanie kupić buty do biegania przed piątkiem"

The skill interprets the request, extracts the task title, resolves relative dates,
decides on priority, and calls the existing Janus CLI. It never edits `data/tasks.md`
directly.

**When NOT to use:** when the user gives an exact task title and exact date/priority
and just wants the command run — in that case call `janus task add` directly without
the interpretation layer.

**Responsibility split:**
- Hermes: understand intent, extract title, resolve relative dates, decide priority, call CLI.
- Janus: validation, persistence, write to `data/tasks.md`.

**Never:** edit `data/tasks.md` directly. Always go through the CLI.

## CLI to call

```bash
cd /home/dan11hermes/workspaces/janus && \
uv run janus task add "TASK TITLE" [--due YYYY-MM-DD] [--priority N]
```

## Step 1 — Extract task title

Convert the request into a concise actionable title. Strip framing language:

- "I need to remember to buy running shoes" → "Buy running shoes"
- "Muszę umówić dentystę" → "Book dentist appointment"
- "Remind me to prepare my training plan this weekend" → "Prepare training plan"
- "Dodaj zadanie kupić buty do biegania przed piątkiem" → "Kupić buty do biegania"

Rules:
- Keep one clear imperative sentence.
- Prefer the user's own wording when it is already a clean title.
- Do not invent details not in the request.

## Step 2 — Resolve dates

Use the current date as the reference point. Resolve common expressions:

- "tomorrow" → today + 1 day
- "today" → today (rare; clarify if genuinely today)
- "day after tomorrow" → today + 2 days
- "this weekend" → Saturday of the upcoming weekend (next Saturday from today). If today is Saturday or Sunday, ask the user which weekend they mean.
- "next weekend" → Saturday of the weekend after the upcoming one.
- "by Friday" / "before Friday" / "until Friday" → the upcoming Friday (if today is Friday or later, take next Friday).
- "this Friday" → upcoming Friday in the current week.
- "next Monday" → Monday of next week.
- "in 3 days" / "in a week" → today + N days.
- YYYY-MM-DD literal → use directly.

For Polish weekday names, map:
- poniedziałek → Monday
- wtorek → Tuesday
- środa → Wednesday
- czwartek → Thursday
- piątek → Friday
- sobota → Saturday
- niedziela → Sunday

If the expression is genuinely ambiguous and the ambiguity could materially affect the task (e.g. "this weekend" when today is Friday, or "next week" without a day), ask the user for clarification instead of guessing.

## Step 3 — Decide priority

Default priority is 1. Only assign higher priority when there is a clear, explicit reason.

- priority 2 → important or time-sensitive task (explicit "important", "urgent but not critical", near deadline, appointment-like).
- priority 3 → urgent / critical / explicitly high priority ("urgent", "ASAP", "critical", "as soon as possible", health/finance deadlines).

Do not invent priority 2 or 3 from a bare relative date alone unless the date itself strongly implies urgency (e.g. "today" + something time-sensitive). When in doubt, keep priority 1.

## Step 4 — Build the command

Construct:

```
cd /home/dan11hermes/workspaces/janus && \
uv run janus task add "TASK TITLE" [--due YYYY-MM-DD] [--priority N]
```

Include `--due` only when a date was resolved.
Include `--priority` only when priority > 1.

## Step 5 — Execute and report

Run the command. On success, report briefly:

"Added task: <title> [-- due <date>] [-- priority <N>]"

On failure, report the error from Janus and do not retry indefinitely.

## Edge cases

- Empty or whitespace-only title → ask the user for a clearer request.
- No task title detectable → ask the user to clarify.
- Multiple possible dates → ask which one, do not guess when it matters.
- User provides an absolute date in a non-ISO format → normalize to YYYY-MM-DD if possible; otherwise ask.
- User says something already exists as a task → do not duplicate without asking.

## Examples

Request: "Add buy running shoes before Friday"
→ title: "Buy running shoes", due: upcoming Friday, priority: 2 if Friday is urgent, else 1.

Request: "Remind me to book a dentist appointment tomorrow"
→ title: "Book dentist appointment", due: tomorrow, priority: 2 (appointment-like).

Request: "I need to prepare my training plan this weekend"
→ title: "Prepare training plan", due: Saturday of upcoming weekend, priority: 1 (unless context says otherwise).

Request: "Dodaj zadanie kupić buty do biegania przed piątkiem"
→ title: "Kupić buty do biegania", due: upcoming Friday, priority: 1 unless context says otherwise.
