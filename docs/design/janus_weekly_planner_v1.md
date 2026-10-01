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

## 5. Deterministyczne sygnały

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

## 6. CLI

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

## 7. Evaluation

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

## 8. Error handling

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

## 9. Definition of Done

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

## 10. Poza zakresem V1

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

## 11. Kolejne wersje

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

## 12. Kompetencje rozwijane przez projekt

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
