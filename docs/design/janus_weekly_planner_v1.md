# Janus Weekly Planner — V1

## 1. Cel projektu

Zbudować w Janusie pierwszy produkcyjnie myślący komponent AI, który potrafi na podstawie rzeczywistych danych użytkownika wygenerować realistyczny plan kolejnego tygodnia.

V1 odpowiada na jedno pytanie:

> Czy Janus potrafi wiarygodnie zaplanować tydzień na podstawie aktywnych celów, zadań i kalendarza?

W V1 planner **nie wykonuje żadnych zmian**. Generuje wyłącznie propozycję planu.

---

## 2. Zakres V1

### Input

Planner otrzymuje:

- aktywne cele,
- zadania,
- kalendarz,
- opcjonalnie podstawowe informacje o ostatniej aktywności, jeśli są już dostępne bez istotnego rozszerzania scope'u.

Minimalny V1:

```text
Goals + Tasks + Calendar
```

### Output

Planner generuje ustrukturyzowany `WeeklyPlan` zawierający:

- podsumowanie tygodnia,
- priorytety,
- zaplanowane zadania,
- uzasadnienie priorytetów,
- sugerowany dzień realizacji,
- ryzyka i konflikty.

Przykładowa struktura:

```json
{
  "week_summary": "...",
  "priorities": [
    {
      "goal_id": "career",
      "reason": "...",
      "priority": 1
    }
  ],
  "planned_tasks": [
    {
      "task_id": "task-123",
      "goal_id": "career",
      "priority": 1,
      "reason": "...",
      "suggested_day": "2026-10-05"
    }
  ],
  "risks": [
    {
      "description": "...",
      "severity": "medium"
    }
  ]
}
```

---

## 3. Architektura

```text
             ┌─────────────┐
             │    Goals    │
             └──────┬──────┘
                    │
             ┌──────▼──────┐
             │    Tasks    │
             └──────┬──────┘
                    │
             ┌──────▼──────┐
             │   Calendar  │
             └──────┬──────┘
                    │
                    ▼
            ┌─────────────────┐
            │ Context Builder │
            └────────┬────────┘
                     │
                     ▼
            ┌─────────────────┐
            │   LLM Planner   │
            └────────┬────────┘
                     │
                     ▼
            ┌─────────────────┐
            │  WeeklyPlan     │
            │   validation    │
            └────────┬────────┘
                     │
                     ▼
                CLI / output
```

### Kluczowa zasada architektoniczna

LLM nie powinien bezpośrednio czytać plików ani wykonywać logiki biznesowej.

Janus powinien przygotować ustrukturyzowany kontekst:

```text
Domain data
    ↓
Context Builder
    ↓
PlanningContext
    ↓
LLM
    ↓
structured WeeklyPlan
    ↓
validation
```

Logika deterministyczna pozostaje w kodzie. LLM odpowiada przede wszystkim za:

- priorytetyzację,
- reasoning,
- planowanie,
- wykrywanie konfliktów,
- uzasadnianie decyzji.

---

## 4. Domain model

Planner powinien mieć własny model domenowy, niezależny od konkretnego providera LLM.

Minimalne modele:

- `PlanningContext`
- `WeeklyPlan`
- `PlannedTask`
- `Priority`
- `PlanningRisk`

Interfejs planera:

```python
class WeeklyPlanner(Protocol):
    def plan(
        self,
        context: PlanningContext,
    ) -> WeeklyPlan:
        ...
```

Pierwsza implementacja:

```text
LLMWeeklyPlanner
```

Docelowo architektura powinna umożliwiać również:

```text
RuleBasedPlanner
MockPlanner
```

bez zmiany reszty aplikacji.

---

## 5. WeeklyPlanner interface (WP-003)

**Work package:** WP-003 — Define WeeklyPlanner interface
**Priority:** P0
**Depends on:** WP-001 (domain model — parent task `t_4aa88c63`), WP-002 (PlanningContext builder — parent task `t_dec30769`)
**Roadmap context:** Phase 2 — Planner (see `docs/roadmap.md` WP-003)

### 5.1 Purpose and scope

The WeeklyPlanner interface is the abstraction that defines how Janus generates a weekly plan from a given PlanningContext. It is the second stage of the planning pipeline, consuming the output of the PlanningContext builder (WP-002) and producing a structured WeeklyPlan.

The interface is designed to be implementation-agnostic. The V1 implementation will be `LLMWeeklyPlanner`, which uses an LLM to reason over the PlanningContext and produce a WeeklyPlan. The interface must also support alternative implementations (e.g., `RuleBasedPlanner`, `MockPlanner`) for testing and future use cases, without requiring changes to the rest of the application.

This design is P0-scoped and covers V1 only. It references the domain model defined in WP-001 (parent task `t_4aa88c63`, Alternative A — minimal model with 5 entities: `PlanningContext`, `WeeklyPlan`, `PlannedTask`, `Priority`, `PlanningRisk`) and the PlanningContext builder defined in WP-002 (parent task `t_dec30769`).

### 5.2 Interface contract

The WeeklyPlanner interface is defined as a Protocol (structural type) with a single method:

```text
WeeklyPlanner (Protocol)
  └── plan(context: PlanningContext) -> WeeklyPlan
```

**Contract:**
- The planner receives a fully-constructed PlanningContext (produced by the PlanningContext builder from WP-002).
- The planner returns a WeeklyPlan (defined in WP-001 domain model).
- The planner must not modify the input PlanningContext.
- The planner must not perform any I/O operations (no file reads, no network calls, no LLM API calls) outside of its implementation boundary. The LLM call is encapsulated within the LLMWeeklyPlanner implementation.
- The planner must be deterministic in its interface contract: given the same PlanningContext, it should produce a semantically equivalent WeeklyPlan (though LLM-based implementations may have non-deterministic output).

### 5.3 Method signatures

#### 5.3.1 plan()

```text
plan(context: PlanningContext) -> WeeklyPlan
```

**Parameters:**
- `context`: A PlanningContext instance containing all loaded data and computed signals for the planning week. This is the output of the PlanningContextBuilder (WP-002).

**Returns:**
- A WeeklyPlan instance containing:
  - `week_summary`: A text summary of the week
  - `priorities`: An ordered list of Priority objects (goal_id, reason, priority rank)
  - `planned_tasks`: A list of PlannedTask objects (task_id, goal_id, priority, reason, suggested_day)
  - `risks`: A list of PlanningRisk objects (description, severity)

**Preconditions:**
- The PlanningContext is valid (produced by PlanningContextBuilder.build())
- The PlanningContext contains at minimum: week metadata, goal signals, task signals, calendar signals

**Postconditions:**
- The returned WeeklyPlan is structurally valid (passes validation)
- All task_id and goal_id references in the WeeklyPlan correspond to entities in the PlanningContext
- The WeeklyPlan does not introduce new tasks or goals not present in the PlanningContext

### 5.4 State management and lifecycle

The WeeklyPlanner is **stateless** across invocations. Each call to `plan()` is independent:
- The planner does not maintain internal state between calls
- The planner does not cache previous plans
- The planner does not learn from previous plans (in V1)

**Lifecycle:**
1. The planner is instantiated (constructor may accept configuration, e.g., LLM model, prompt template)
2. The planner receives a PlanningContext via `plan()`
3. The planner processes the context and produces a WeeklyPlan
4. The WeeklyPlan is returned to the caller
5. The planner instance can be discarded or reused for the next call

**Resource management:**
- The LLMWeeklyPlanner implementation manages the LLM client lifecycle (connection, API calls)
- The planner must release any resources (e.g., LLM client connections) when no longer needed
- In V1, the planner is invoked once per `janus plan week` command and then discarded

### 5.5 Interaction patterns

#### 5.5.1 Interaction with PlanningContext builder (WP-002, parent task t_dec30769)

The WeeklyPlanner consumes the output of the PlanningContextBuilder:

```text
PlanningContextBuilder.build() → PlanningContext → WeeklyPlanner.plan() → WeeklyPlan
```

The PlanningContextBuilder (WP-002) is responsible for:
- Loading raw domain data (goals, tasks, calendar)
- Computing deterministic signals (overdue, due soon, stalled, conflicts)
- Assembling the PlanningContext

The WeeklyPlanner (WP-003) is responsible for:
- Receiving the PlanningContext
- Reasoning over the context (via LLM or rules)
- Producing a WeeklyPlan

The two components are decoupled: the planner does not know how the PlanningContext was built, and the builder does not know how the plan is generated.

#### 5.5.2 Interaction with LLM (WP-004)

The LLMWeeklyPlanner implementation (WP-004) will:
1. Serialize the PlanningContext into a prompt
2. Send the prompt to the LLM
3. Parse the LLM's structured output into a WeeklyPlan
4. Validate the WeeklyPlan

The interface defined in this document does not specify how the LLM is invoked — that is the responsibility of the WP-004 implementation.

#### 5.5.3 Interaction with CLI (WP-005)

The `janus plan week` command will:
1. Invoke the PlanningContextBuilder to produce a PlanningContext
2. Pass the PlanningContext to the WeeklyPlanner
3. Display the resulting WeeklyPlan

The CLI does not interact with the planner directly — it goes through the interface.

#### 5.5.4 Roadmap replenishment (#replenish)

This work package was created by the roadmap replenishment system (`#replenish`) after the completion of WP-002 (parent task `t_dec30769`). The replenishment system pulled WP-003 from the roadmap (`docs/roadmap.md`) and created this task. The interface defined here is the contract that the WP-004 implementation must satisfy.

### 5.6 Error handling and edge cases

The WeeklyPlanner must handle the following error cases:

**Invalid PlanningContext:**
- Empty PlanningContext (no goals, no tasks, no calendar) → the planner should still produce a valid (possibly empty) WeeklyPlan
- Malformed PlanningContext (missing required fields) → the planner should raise a ValidationError

**LLM output errors (for LLMWeeklyPlanner):**
- Invalid structured output (malformed JSON, missing required fields) → the planner should raise a PlanGenerationError
- LLM returns references to non-existent tasks/goals → the planner should raise a ValidationError
- LLM returns an empty plan → the planner should raise a PlanGenerationError (or return an empty plan, depending on the use case)

**Provider errors:**
- LLM API timeout → the planner should raise a ProviderError (with retry logic in WP-004)
- LLM API rate limit → the planner should raise a ProviderError (with retry logic in WP-004)
- LLM API authentication failure → the planner should raise a ProviderError

**Edge cases:**
- All goals completed → the planner should produce a minimal plan (no priorities, no planned tasks)
- No open tasks → the planner should produce a plan with no planned tasks
- Conflicting deadlines → the planner should flag the conflict in the risks section
- Too many tasks for one week → the planner should prioritize and flag the overload in the risks section

### 5.7 Dependencies and integration points

**Domain model (WP-001):**
- PlanningContext (input)
- WeeklyPlan (output)
- PlannedTask, Priority, PlanningRisk (output components)

**PlanningContext builder (WP-002, parent task t_dec30769):**
- Produces the PlanningContext that the planner consumes

**LLM provider (WP-004):**
- The LLMWeeklyPlanner implementation depends on an LLM provider
- The provider is abstracted behind an interface (not specified in this document)

**Validation (WP-004):**
- The WeeklyPlan must be validated before being returned
- Validation rules are defined in the domain model (WP-001)

**CLI (WP-005):**
- The `janus plan week` command invokes the planner
- The CLI displays the WeeklyPlan

### 5.8 Design constraints

1. **Implementation-agnostic:** The interface must not depend on any specific LLM provider, prompt format, or output format.
2. **Single responsibility:** The planner only generates plans. It does not load data, compute signals, or persist results.
3. **Stateless:** The planner does not maintain state between invocations.
4. **Side-effect-free:** The planner does not modify the input PlanningContext or any external state.
5. **Replaceable:** The interface must allow swapping implementations (LLMWeeklyPlanner, RuleBasedPlanner, MockPlanner) without changing the rest of the application.
6. **Synchronous:** The `plan()` method is synchronous (returns a WeeklyPlan, not a Future or coroutine). Async support may be added in V2 if needed.

### 5.9 Testing strategy

**Unit tests:**
- Interface conformance: verify that LLMWeeklyPlanner, RuleBasedPlanner, and MockPlanner all conform to the WeeklyPlanner protocol
- Input validation: verify that the planner handles invalid PlanningContext gracefully
- Output validation: verify that the planner returns a valid WeeklyPlan

**Integration tests:**
- End-to-end: PlanningContextBuilder → WeeklyPlanner → WeeklyPlan
- LLM integration: verify that LLMWeeklyPlanner correctly invokes the LLM and parses the output
- Error handling: verify that the planner handles LLM errors, timeouts, and invalid output

**Test data:**
- Use synthetic PlanningContext instances (not real data)
- Cover the 10 evaluation scenarios from §8 (Evaluation)

### 5.10 Design decisions and trade-offs

**Decision 1: Protocol (structural type) over ABC**
The WeeklyPlanner is defined as a Protocol (structural type) rather than an abstract base class. This allows any class with a `plan()` method to conform to the interface, without requiring explicit inheritance. This is more flexible and Pythonic.

**Decision 2: Single method interface**
The interface has a single method (`plan()`). This keeps the interface simple and focused. Additional methods (e.g., `validate()`, `explain()`) can be added in V2 if needed.

**Decision 3: Synchronous interface**
The `plan()` method is synchronous. This simplifies the interface and is sufficient for V1 (the planner is invoked once per CLI command). Async support can be added in V2 if needed.

**Decision 4: Stateless planner**
The planner does not maintain state between invocations. This simplifies the implementation and makes it easier to test. State management (e.g., caching, learning) can be added in V2.

### 5.11 Relationship to other work packages

- **WP-001 (domain model):** Defines the PlanningContext, WeeklyPlan, PlannedTask, Priority, and PlanningRisk entities. This document specifies how these entities are used by the planner.
- **WP-002 (PlanningContext builder, parent task t_dec30769):** Produces the PlanningContext that the planner consumes. The quality of the builder's output directly affects the quality of the planner's output.
- **WP-004 (LLM weekly planner):** Implements the LLMWeeklyPlanner. This document defines the interface that the implementation must conform to.
- **WP-005 (CLI):** The `janus plan week` command invokes the planner and displays the result.
- **WP-006 (evaluation):** The evaluation scenarios will test the planner's output as part of the end-to-end planning pipeline.

### 5.12 Open questions for WP-004

These questions are not resolved in this document; they are deferred to the relevant work packages:

1. **Prompt format:** How should the PlanningContext be serialized for the LLM prompt? (JSON, markdown, natural language?)
2. **LLM model selection:** Which LLM model should be used for V1? What are the cost and latency constraints?
3. **Output format:** What structured output format should the LLM produce? (JSON schema, function calling, structured output?)
4. **Retry strategy:** How many retries should be attempted on LLM failure? What backoff strategy should be used?
5. **Validation rules:** What are the exact validation rules for the WeeklyPlan? (e.g., must all planned tasks exist in the PlanningContext? Must priorities be unique?)

---

## 6. Deterministic signals

Przed wywołaniem LLM Janus powinien obliczyć przynajmniej:

- task overdue,
- task due soon,
- goal stalled,
- goal behind target,
- dostępność kalendarza,
- konflikty terminów,
- liczbę zadań konkurujących o ten sam okres.

Dzięki temu LLM otrzymuje gotowe sygnały zamiast samodzielnie rekonstruować je z surowych danych.

---

## 7. CLI

V1 powinna udostępniać komendę w rodzaju:

```bash
uv run janus plan week
```

Przykładowy output:

```text
JANUS WEEKLY PLAN
5–11 Oct 2026

TOP PRIORITIES

1. Career
   Prepare AI/Agent Engineering development plan

2. Janus
   Complete autonomous planning V1

3. Health
   2 strength sessions

RISKS

⚠ Career goal has no completed actions...
⚠ Multiple tasks compete for the same time...

PLANNED TASKS

Monday
  ...

Tuesday
  ...
```

Na tym etapie CLI nie powinno powodować side effects.

---

## 8. Evaluation

Evaluation jest kluczowym elementem projektu.

Nie należy wymagać identycznego tekstu odpowiedzi LLM. Należy sprawdzać właściwości planu.

Minimalny zestaw scenariuszy:

1. Jeden pilny task.
2. Wiele overdue tasks.
3. Stalled goal.
4. Brak dostępności w kalendarzu.
5. Konflikt deadline'ów.
6. Zbyt wiele zadań na jeden tydzień.
7. Pusta lista zadań.
8. Cel bez powiązanych zadań.
9. Cel już ukończony.
10. Kilka celów o podobnym priorytecie.

Przykład właściwości:

> Overdue task musi zostać uwzględniony albo explicite odrzucony z uzasadnieniem.

Evaluation powinno umożliwiać porównywanie kolejnych wersji promptu i logiki planera.

---

## 9. Error handling

Planner powinien obsługiwać:

- invalid structured output,
- brakujące dane,
- błędy providera LLM,
- timeout,
- retry,
- niepoprawne identyfikatory zadań/celów,
- niemożliwe lub sprzeczne rekomendacje.

Nie wolno zakładać, że output LLM jest poprawny tylko dlatego, że model został poproszony o JSON.

---

## 10. Definition of Done

Projekt V1 jest zakończony, gdy:

- [ ] `janus plan week` działa end-to-end.
- [ ] Planner pobiera Goals.
- [ ] Planner pobiera Tasks.
- [ ] Planner pobiera Calendar.
- [ ] Istnieje `PlanningContext`.
- [ ] Istnieje niezależny interfejs `WeeklyPlanner`.
- [ ] Istnieje `LLMWeeklyPlanner`.
- [ ] LLM generuje structured output.
- [ ] `WeeklyPlan` jest walidowany.
- [ ] Invalid output jest obsługiwany.
- [ ] Istnieją testy jednostkowe.
- [ ] Istnieje zestaw evaluation scenarios.
- [ ] Planner nie wykonuje side effects.
- [ ] Istnieje ADR opisujący architekturę.
- [ ] Istnieje dokumentacja.
- [ ] Istnieje przykładowy output.
- [ ] Można uruchomić cały flow jedną komendą.

---

## 11. Poza zakresem V1

Nie implementować w V1:

- multi-agent system,
- LangGraph ani innego frameworka tylko dlatego, że jest agentowy,
- MCP,
- vector database,
- RAG,
- autonomous execution,
- Telegram approval,
- long-term memory,
- web search,
- UI,
- Kubernetes,
- dodatkowej infrastruktury cloudowej.

Te elementy mogą być rozważone dopiero po potwierdzeniu wartości V1.

---

## 12. Kolejne wersje

### V2 — Human-in-the-loop

```text
WeeklyPlan
    ↓
Proposed actions
    ↓
User approval
    ↓
Execution
```

Planner może proponować:

- utworzenie taska,
- zmianę priorytetu,
- zmianę deadline'u,
- utworzenie wydarzenia w kalendarzu.

Akcje destrukcyjne lub zewnętrzne wymagają approval.

### V3 — Autonomous execution

```text
Observe
   ↓
Plan
   ↓
Approve / policy
   ↓
Execute
   ↓
Observe result
   ↓
Review
```

### V4 — Feedback loop

Po tygodniu Janus analizuje:

- planned actions,
- completed actions,
- postponed actions,
- ignored actions,
- goal progress,
- prediction accuracy,
- koszt LLM,
- liczbę wymaganych approval.

Następnie wykorzystuje wynik w kolejnym planowaniu.

---

## 13. Kompetencje rozwijane przez projekt

Projekt ma być praktycznym ćwiczeniem w:

- AI/agent architecture,
- LLM structured output,
- tool-oriented architecture,
- planning,
- evaluation,
- human-in-the-loop,
- reliability,
- error handling,
- observability,
- API/domain design,
- testing,
- architecture decisions,
- technical documentation.

Docelowo projekt ma rozwijać profil:

```text
Senior Software Engineer
        ↓
AI / Agent Systems Engineer
        ↓
Staff-level system design
        ↓
AI Systems Architect
```

---

# Roadmap tasks

## Phase 1 — Domain & context

### WP-001 — Design Weekly Planner domain model
**Priority:** P0

Zaprojektować `PlanningContext`, `WeeklyPlan`, `PlannedTask`, `Priority` i `PlanningRisk`.

**Done when:**
- modele są niezależne od LLM,
- mają walidację,
- istnieją testy,
- nie zawierają logiki providera.

### WP-002 — Build PlanningContext builder
**Priority:** P0  
**Depends on:** WP-001

Zbudować komponent agregujący Goals, Tasks i Calendar do `PlanningContext`.

**Done when:**
- jeden komponent generuje kompletny context,
- obsługiwane są puste dane,
- obsługiwane są edge cases,
- istnieją testy.

---

## Phase 2 — Planner

### WP-003 — Define WeeklyPlanner interface
**Priority:** P0  
**Depends on:** WP-001

Wprowadzić abstrakcję `WeeklyPlanner` umożliwiającą wymianę implementacji.

**Done when:**
- istnieje protocol/interface,
- `LLMWeeklyPlanner` może być podstawioną implementacją,
- możliwe jest użycie mock/rule-based implementacji w testach.

### WP-004 — Implement LLM weekly planner
**Priority:** P0  
**Depends on:** WP-002, WP-003

Zaimplementować przepływ:

`PlanningContext → prompt → LLM → structured WeeklyPlan`.

**Done when:**
- structured output jest walidowany,
- błędny output nie przechodzi dalej,
- istnieje retry/error handling,
- provider jest odseparowany od domeny.

---

## Phase 3 — CLI

### WP-005 — Add `janus plan week`
**Priority:** P1  
**Depends on:** WP-004

Dodać CLI generujące tygodniowy plan.

**Done when:**
- komenda działa end-to-end,
- pokazuje priorytety,
- pokazuje planned tasks,
- pokazuje risks,
- nie wykonuje side effects.

---

## Phase 4 — Evaluation

### WP-006 — Build weekly planner evaluation suite
**Priority:** P0  
**Depends on:** WP-004

Zbudować minimum 10 scenariuszy testowych obejmujących m.in. overdue tasks, stalled goals, konflikty i brak dostępności.

**Done when:**
- scenariusze są reprodukowalne,
- testują właściwości odpowiedzi,
- można porównywać kolejne wersje planera/promptu.

### WP-007 — Define planner quality metrics
**Priority:** P1  
**Depends on:** WP-006

Zdefiniować metryki jakości planowania.

Minimum:

- task coverage,
- overdue-task handling,
- deadline awareness,
- calendar conflict rate,
- plan validity,
- number of unsupported recommendations.

---

## Phase 5 — Architecture & documentation

### WP-008 — Write Weekly Planner ADR
**Priority:** P1  
**Depends on:** WP-004

Udokumentować:

- granicę między kodem deterministycznym i LLM,
- domain model,
- context building,
- structured output,
- error handling,
- brak side effects w V1.

### WP-009 — Document Weekly Planner
**Priority:** P1  
**Depends on:** WP-005, WP-006, WP-008

Dodać dokumentację uruchomienia, architektury, przykładowego outputu i ograniczeń.

---

## Phase 6 — V1 completion

### WP-010 — Harden Weekly Planner V1
**Priority:** P1  
**Depends on:** WP-007, WP-009

Przegląd całości i usunięcie problemów przed uznaniem V1 za zakończone.

**Done when:**
- wszystkie DoD spełnione,
- testy przechodzą,
- evaluation suite działa,
- dokumentacja jest aktualna,
- flow można uruchomić jedną komendą.

---

## V2 backlog

Po ukończeniu V1:

- `WP-011` — Design action proposal model
- `WP-012` — Add human approval workflow
- `WP-013` — Add task mutation tools
- `WP-014` — Add calendar mutation tools
- `WP-015` — Add execution policy
- `WP-016` — Add execution result tracking
- `WP-017` — Add weekly review loop
- `WP-018` — Add planner feedback/evaluation loop
