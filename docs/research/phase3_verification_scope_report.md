RESEARCH REPORT — t_27cf102a: Phase 3 Verification Pipeline Scope and Existing Capabilities
==============================================================================================

1) DEFINED SCOPE OF PHASE 3
--------------------------------------------------------------------------------

There is no standalone "Phase 3" document in the repository. The phrase
"repository verification" appears once, in docs/roadmap.md:110, under the
"Agent Reliability" focus area (lines 101-114):

  "Improve the reliability of autonomous work.
   Focus areas:
   - task checkpoints,
   - repository verification,
   - test execution,
   - recovery after interrupted work,
   - explicit uncertainty,
   - better queue and task management."

The parent task t_a665778c is titled "Close Verification Pipeline Phase 3".
It was decomposed by the auto-decomposer into three children:
  - t_27cf102a  (this research card)
  - t_b01ff44e  (todo, no body yet)
  - t_5dcad317  (todo, no body yet)

The root wakes when all children complete.

So the operational definition of Phase 3 is inferred from roadmap + decomposition:
the verification-pipeline phase whose scope is repository verification, test
execution, and related reliability work under the "Agent Reliability" roadmap item.

The exact sub-goals of t_b01ff44e and t_5dcad317 are still unknown — those
cards are todo with no body.


2) EXISTING VERIFICATION ARTIFACTS FOUND
--------------------------------------------------------------------------------

Test framework
  - pytest >=9.1.1 declared in pyproject.toml dev-dependencies.
  - No coverage config, no linting config, no pre-commit config found.

Test suite
  - 19 test files under tests/, all Python.
  - Coverage spans: models (Task, Goal, Workout), CLI handlers (task state,
    task progress, tasks_cli, workout_cli, goals_cli, weekly), integrations
    (Markdown goals, Markdown tasks, attention, Google Calendar, daily briefing,
    fitness), and domain logic.
  - tests/test_task_state_progress.py + tests/test_task_state_progress_cli.py
    cover the task state/progress feature, which aligns with the roadmap bullet
    "task checkpoints."

CI / automation
  - NO GitHub Actions workflow files exist (.yml/.yaml = 0 matches).
  - NO Makefile, justfile, or other verification script exists.
  - README + roadmap both say "uv run pytest" for tests, but nothing runs it
    automatically on push / PR / schedule.

Verification contract
  - No document or script defines what "repository verified" means for this
    project. The principles doc (docs/principles.md) says "run tests before
    reporting completion," but that is guidance, not a pipeline step.


3) MISSING PIECES NEEDED TO CLOSE THE PHASE
--------------------------------------------------------------------------------

a) CI pipeline — highest gap.
   No workflow file, no scheduled check, no gate that runs pytest against the
   current repo state on push or PR. The most natural reading of "repository
   verification" is automated test execution tied to repository changes. That
   does not exist yet.

b) Explicit verification contract.
   No doc/script stating: which command(s) constitute verification, what exit
   code means success, what artifacts are produced. Guidance exists in
   docs/principles.md; a defined pipeline step does not.

c) Remaining child work.
   t_b01ff44e and t_5dcad317 are todo with no body. Their content would refine
   the gap list. This report should not assume their scope.

d) Possible reuse.
   The existing task state/progress tests (task checkpoints) may already satisfy
   part of the roadmap's "task checkpoints" bullet. Whether they are wired into
   an automated verification step is the open question.


4) CAVEATS
--------------------------------------------------------------------------------
- "Phase 3" is not a separately documented phase with its own writeup. It is the
  verification-pipeline stage referenced by the parent card title and the roadmap
  bullet "repository verification."
- The test suite exists and is substantial. What is missing is the automation and
  the defined contract that ties those tests to a "repository verified" claim.
- No implementation was done on this card, per instructions.
