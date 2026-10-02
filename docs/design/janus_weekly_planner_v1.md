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

### 4.1 Minimalne modele (P0)

`PlanningContext`, `WeeklyPlan`, `PlannedTask`, `Priority`, `PlanningRisk` — dokładnie tak, jak definiuje V1 spec §4.

### 4.2 Definicje typów

```python
# === models/planning.py (NOWE — proposed location) ===

from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Optional


class PriorityLevel(int, Enum):
    """1 = highest priority. Lower number = higher priority."""
    HIGH = 1
    MEDIUM = 2
    LOW = 3


@dataclass
class PlanningContext:
    """Aggregated input for the weekly planner. Ephemeral — constructed
    per planning cycle, not persisted."""
    goals: list["Goal"]                    # active goals from models/goal.py
    tasks: list["Task"]                    # open tasks from models/task.py
    events: list["Event"]                  # calendar events from models/event.py
    free_slots: list["TimeBlock"]          # from models/time_block.py
    overload_warning: Optional[str] = None  # deterministic signal
    # Deterministic signals (computed before LLM call):
    task_overdue: list[str] = field(default_factory=list)
    task_due_soon: list[str] = field(default_factory=list)
    goal_stalled: list[str] = field(default_factory=list)
    goal_behind_target: list[str] = field(default_factory=list)
    calendar_conflicts: list[str] = field(default_factory=list)


@dataclass
class Priority:
    """Goal priority ranking within the weekly plan."""
    goal_id: str
    reason: str
    priority: int                         # 1-based, lower = higher priority

    def __post_init__(self) -> None:
        if self.priority < 1:
            raise ValueError(f"Priority must be >= 1, got {self.priority}")


@dataclass
class PlannedTask:
    """A single task planned for a specific day. Ephemeral — lives
    only within a WeeklyPlan; not persisted in V1."""
    task_title: str                       # references Task.title (title-based identity)
    goal_title: str                       # references Goal.title
    priority: int                         # 1 = highest
    reason: str
    suggested_day: date                   # YYYY-MM-DD, within the WeeklyPlan week
    estimated_duration_minutes: Optional[int] = None  # V1 optional

    def __post_init__(self) -> None:
        if self.priority < 1:
            raise ValueError(f"PlannedTask priority must be >= 1, got {self.priority}")


@dataclass
class PlanningRisk:
    """Risk or conflict identified during planning."""
    description: str
    severity: str                         # "low" | "medium" | "high"

    def __post_init__(self) -> None:
        if self.severity not in ("low", "medium", "high"):
            raise ValueError(
                f"PlanningRisk.severity must be low/medium/high, got {self.severity!r}"
            )


@dataclass
class WeeklyPlan:
    """Output of the weekly planner. Ephemeral — generated each week,
    not persisted in V1."""
    week_start: date                      # Monday (ISO week start)
    week_summary: str
    priorities: list[Priority] = field(default_factory=list)
    planned_tasks: list[PlannedTask] = field(default_factory=list)
    risks: list[PlanningRisk] = field(default_factory=list)

    def __post_init__(self) -> None:
        # Validate all suggested_days fall within the plan week
        week_end = self.week_start + timedelta(days=6)
        for pt in self.planned_tasks:
            if not (self.week_start <= pt.suggested_day <= week_end):
                raise ValueError(
                    f"PlannedTask.suggested_day {pt.suggested_day} is outside "
                    f"the plan week [{self.week_start}, {week_end}]"
                )
```

### 4.3 Wzorce modeli (zgodne z istniejącym kodem)

| Wzorzec | Źródło | Zastosowanie |
|---------|--------|--------------|
| `dataclass` + `__post_init__` walidacji | `models/task.py`, `models/goal.py` | Wszystkie nowe modele |
| Tytuł-based tożsamość (brak UUID) | `Goal.title`, `Task.title` | `PlannedTask.task_title`, `PlannedTask.goal_title` |
| Listy `dict` dla uników cyklicznych | `Goal.milestones`, `Goal.projects` | Nie stosujemy — PlanningContext jest ephemeral |
| Enum-based stany | `ExecutionMode`, `SupportMode` | `PriorityLevel` enum |

---

## 5. Relacje i kardynalność

```text
PlanningContext                   WeeklyPlan
┌──────────────────┐              ┌──────────────────┐
│ goals: list[Goal]│              │ week_start: date  │
│ tasks: list[Task]│              │ week_summary: str │
│ events: list[Ev] │              │ priorities: list  │──┐
│ free_slots: list │              │ planned_tasks: list─┐ │
│ overload_warn:  │              │ risks: list[Risk] ───┘ │
│ + signals       │              └────────┬─────────┘    │
└──────────────────┘                       │              │
         │                                 │              │
         │ 1:N                             │ 1:N          │ 1:N
         ▼                                 ▼              ▼
     ┌─────────┐                    ┌────────────┐  ┌──────────────┐
     │  Goal   │                    │  Priority   │  │PlanningRisk  │
     └─────────┘                    └────────────┘  └──────────────┘
                                                │
         ┌──────────────┐                       │ 1:N
         │    Task      │                       ▼
         └──────────────┘              ┌──────────────────┐
              │                        │  PlannedTask     │
              │ 1:N                    └──────────────────┘
              ▼                       (task_title → Task.title)
         ┌──────────────┐           (goal_title  → Goal.title)
         │   Event      │           (suggested_day ∈ week)
         └──────────────┘

Kardynalność:
  - WeeklyPlan pokrywa dokładnie 1 tydzień (Mon–Sun)
  - PlannedTask należy do dokładnie 1 goal i odnosi się do 1 task
  - Priority odnosi się do dokładnie 1 goal
  - PlanningRisk jest niezależny (stand-alone)
  - PlanningContext → Goals/Tasks/Events: 1:N
```

---

## 6. Cykl życia (Lifecycle)

| Entity | Cykl | Trwanie |
|--------|------|---------|
| `PlanningContext` | Ephemeral — budowany cyklicznie (co briefing) | Nie przetrwałego |
| `WeeklyPlan` | Ephemeral — generowany co tydzień | Nie przetrwałego (V1) |
| `PlannedTask` | Ephemeral w ramach WeeklyPlan | Nie przetrwałego (V1) |
| `Priority` | Ephemeral w ramach WeeklyPlan | Nie przetrwałego (V1) |
| `PlanningRisk` | Ephemeral w ramach WeeklyPlan | Nie przetrwałego (V1) |

**Kluczowa zasada (z V1 spec §6, §9):** V1 planner NIE wykonuje żadnych side effects — generuje wyłącznie propozycję.

Niezgodność stanu nie jest możliwa, ponieważ modele nie są持久owane.

---

## 7. Punkty integracji z istniejącymi komponentami Janus

### 7.1 Źródła danych (wejście Context Builder)

| Źródło | Plik | Wzorzec |
|--------|------|---------|
| Goal persistence | `src/janus/integrations/markdown_goals.py` → `load_goals()` | `Goal` dataclass, path monkeypatchable |
| Task persistence | `src/janus/integrations/markdown_tasks.py` → `load_tasks()` | `Task` dataclass, path monkeypatchable |
| Calendar read | `src/janus/integrations/google_calendar.py` → `list_events()` | `Event` dataclass, `maxResults=10` — needs increase |
| Calendar connector | `src/janus/integrations/google_calendar_connector.py` | `Connector` ABC |
| Free/busy slots | `src/janus/services/freebusy.py` → `compute_free_slots()` | `TimeBlock` model |

### 7.2 Warstwa domenowa

| Element | Plik | Wzorzec |
|---------|------|---------|
| NextAction engine | `src/janus/domain/planning.py` | Dataclass + pure functions, domain depends only on models |
| Domain `__init__.py` | `src/janus/domain/__init__.py` | Public API exports |
| Layering constraint | `docs/decisions/001-hermes-janus-system-model.md` (ADR-001) | Domain may not import services |

### 7.3 Warstwa serwisowa

| Serwis | Plik | Zastosowanie |
|--------|------|--------------|
| Weekly review | `src/janus/services/weekly_review.py` | Reuse goal progress/health signals |
| Daily briefing | `src/janus/services/daily_briefing.py` | Attention items, free slots |
| Attention scoring | `src/janus/services/attention.py` | Deterministic scores (overdue=100, due_today=80, …) |
| Agency planning | `src/janus/services/agency_planning.py` | Agency-aware mode selection |
| Pipeline | `src/janus/services/pipeline.py` | Planner → Agency → Policy chain |
| Overload detection | `src/janus/services/overload.py` | Overload warnings for context |

### 7.4 CLI

| Istniejący | Plik | Wzorzec do naśladowania |
|-----------|------|------------------------|
| `janus weekly` | `src/janus/weekly.py` | Renderer pattern |
| `janus today` | `src/janus/daily_briefing.py` | Daily briefing flow |

**Nowa komenda:** `janus plan week` — renders `WeeklyPlan` (proposal only, no side effects).

### 7.5 Integrations

| Wzorzec | Plik |
|---------|------|
| `Connector` ABC | `src/janus/integrations/connector.py` |
| Registry | `src/janus/integrations/registry.py` |
| Atomic I/O | `src/janus/integrations/atomic_io.py` |
| Telegram delivery | `src/janus/integrations/telegram_weekly.py` |

---

## 8. Deterministyczne sygnały (przed LLM)

Przed wywołaniem LLM Janus powinien obliczyć:

- task overdue,
- task due soon,
- goal stalled,
- goal behind target,
- dostępność kalendarza,
- konflikty terminów,
- liczbę zadań konkurujących o ten sam okres.

Dzięki temu LLM otrzymuje gotowe sygnały zamiast samodzielnie rekonstruować je z surowych danych.

---

## 9. CLI

V1 powinna udostępniać komendę:

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

## 10. Evaluation

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

## 11. Error handling

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

## 12. Definition of Done

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

## 13. Poza zakresem V1

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

## 14. Kolejne wersje

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

## 15. Kompetencje rozwijane przez projekt

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

## 16. Otwarte pytania

1. **Początek tygodnia:** ISO standard (Monday) vs. preferencja użytkownika (Sunday w niektórych regionach). Spec nie precyzuje.
2. **Tożsamość task:** Title-based references są kruche przy zmianie tytułów. Istniejący wzorzec `Goal.related_tasks` ma to samo ograniczenie — V1 go nie rozwiązuje.
3. **Provider LLM:** V1 spec wymienia `LLMWeeklyPlanner` ale nie precyzuje interfejsu providera ani oczekiwanego schema structured output.
4. **Retry policy:** V1 spec §8 wspomina retry/error handling ale nie definiuje polityki retry ani fallbacku.
5. **Timezone:** Eventy kalendarzowe są timezone-aware; planner musi spójnie obsługiwać timezone dla `suggested_day`.
6. **Pojemność dzienna:** V1 spec nie definiuje ile zadań może być zaplanowanych na dzień ani jak wykrywać overload.
7. **Relacja z weekly review:** Czy planner ma zastąpić czy uzupełnić istniejący `weekly_review.py`? Spec nie precyzuje.

---

## 17. Następne kroki (minimalne)

1. **Stworzyć modele** (`src/janus/models/planning.py`): `PlanningContext`, `WeeklyPlan`, `PlannedTask`, `Priority`, `PlanningRisk` — zgodnie z §4.2, z `__post_init__` walidacją.
2. **Stworzyć interfejs** (`src/janus/domain/weekly_planner.py`): `WeeklyPlanner` Protocol + `LLMWeeklyPlanner` stub.
3. **Zbudować Context Builder** (`src/janus/services/`): agreguje Goals + Tasks + Calendar + deterministic signals.
4. **Dodać CLI** `janus plan week` (wzorzec `weekly.py`).
5. **Dodać testy** (`tests/test_weekly_planner.py`) z 10+ scenariuszami z V1 spec §7.
6. **Wyeliminować 7 otwartych pytań** z §16 przed rozpoczęciem implementacji — szczególnie week start day i LLM output schema.

---

## Roadmap tasks

### Phase 1 — Domain & context

#### WP-001 — Design Weekly Planner domain model
**Priority:** P0

Zaprojektować `PlanningContext`, `WeeklyPlan`, `PlannedTask`, `Priority` i `PlanningRisk`.

**Done when:**
- modele są niezależne od LLM,
- mają walidację,
- istnieją testy,
- nie zawierają logiki providera.

#### WP-002 — Build PlanningContext builder
**Priority:** P0
**Depends on:** WP-001

Zbudować komponent agregujący Goals, Tasks i Calendar do `PlanningContext`.

**Done when:**
- jeden komponent generuje kompletny context,
- obsługiwane są puste dane,
- obsługiwane są edge cases,
- istnieją testy.

---

### Phase 2 — Planner

#### WP-003 — Define WeeklyPlanner interface
**Priority:** P0
**Depends on:** WP-001

Wprowadzić abstrakcję `WeeklyPlanner` umożliwiającą wymianę implementacji.

**Done when:**
- istnieje protocol/interface,
- `LLMWeeklyPlanner` może być podstawioną implementacją,
- możliwe jest użycie mock/rule-based implementacji w testach.

#### WP-004 — Implement LLM weekly planner
**Priority:** P0
**Depends on:** WP-002, WP-003

Zaimplementować przepływ:

`PlanningContext → prompt → LLM → structured WeeklyPlan`

**Done when:**
- structured output jest walidowany,
- błędny output nie przechodzi dalej,
- istnieje retry/error handling,
- provider jest odseparowany od domeny.

---

### Phase 3 — CLI

#### WP-005 — Add `janus plan week`
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

### Phase 4 — Evaluation

#### WP-006 — Build weekly planner evaluation suite
**Priority:** P0
**Depends on:** WP-004

Zbudować minimum 10 scenariuszy testowych obejmujących m.in. overdue tasks, stalled goals, konflikty i brak dostępności.

**Done when:**
- scenariusze są reprodukowalne,
- testują właściwości odpowiedzi,
- można porównywać kolejne wersje planera/promptu.

#### WP-007 — Define planner quality metrics
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

### Phase 5 — Architecture & documentation

#### WP-008 — Write Weekly Planner ADR
**Priority:** P1
**Depends on:** WP-004

Udokumentować:

- granicę między kodem deterministycznym i LLM,
- domain model,
- context building,
- structured output,
- error handling,
- brak side effects w V1.

#### WP-009 — Document Weekly Planner
**Priority:** P1
**Depends on:** WP-005, WP-006, WP-008

Dodać dokumentację uruchomienia, architektury, przykładowego outputu i ograniczeń.

---

### Phase 6 — V1 completion

#### WP-010 — Harden Weekly Planner V1
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