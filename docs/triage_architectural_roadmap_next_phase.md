# Triage architektoniczno-roadmapowy — kolejny etap rozwoju Janusa

**Task:** t_ea99cee2
**Data:** 2026-09-24
**Zakres:** Synthesis findings z 5 research-findings worktrees + discovery reads z t_80157ed1
**Metoda:** Cross-worktree aggregation + framework triagu z ciała tasku.

---

## 1. Executive Summary

1. **Janus ma już funkcjonalny, choć nie w pełni dojrzały cykl Goal → Task → Execution → Completion → Review.** Nie jest to „brak podstaw" — jest to system z prawdziwymi forced gates (ADR-004 Phases 1/3/4/5), obserwowalnymi lifecycle sygnałami (attention engine, goal audit, weekly review), i niemal kompletnym modelem domenowym (Goal, Task, Milestone, Project, EvidencePackage, ExecutionResultMessage). Główny brak to **formalny stan `under_review` na poziomie domeny** i **enforcement na poziomie Goal** (obecnie tylko task-level gates).

2. **ADR-004 jest kodowo kompletny, ale operacyjnie „dormant".** `janus_sync` plugin nie jest załadowany w obecnej konfiguracji Hermes. Oznacza to, że Phase 1 auto-sync i execution-feedback gate-block routing nie działają w produkcji — implementacja istnieje, ale nie jest aktywna. To najważniejszy single highest-impact operational gap.

3. **Agency-First Development Phase (`docs/janus-agency-first-development-phase.md`) jest referenced w roadmapie i w taskach, ale nie istnieje jako plik.** To powoduje, że roadmapowy „Agency-First Janus" sekcja jest odseparowana od dokumentacji, co podważa wiarygodność route'u.

4. **Dokumentacja zawiera realne stale/ambiguous sygnały:** roadmap items 9-12 oznaczone jako `[ ]` mimo że są wdrożone; dwa nakładające się pliki z consolidate'owanymi ADR-ami (`adr-consolidated-decisions.md` i `adr-003-004-005-consolidated-decisions.md`) zawierają stary status ADR-004 (pre-PR-189); roadmap items 11 i 15 są almost-duplicate; ADR-005 status polega na legacy migration sformułowaniu zamiast nowym „criteria met".

5. **Architektura Janus jest spójna pod kątem Agency-First:** Hermes trzyma agent-orchestration i interaction; Janus trzymi domenę, determinizm, persistence, i verificację. To właśnie jest „bounded context separation" — nie musi być wycinane, bo już działa. To, co trzeba zbudować, to wyższe warstwy **PersonalState, Policy/Approval, Agency-Aware Planning** — ale nie od razu. P0 powinno ustabilizować lifecycle enforcement i dokładnie zdefiniować to, co już działa.

6. **Nie ma potrzeby odświeżać ADR-001/ADR-002/ADR-003 w całości.** One są spójne z Agency-First. Potrzebny może być tylko ADR-004 update (status + runtime caveat) i ewentualnie nowy ADR dotyczący lifecycle review state i goal-level gates, jeśli decyzja o `under_review` zostanie wzięta.

7. **Nie ma potrzeby budować „Personal State Model" jako osobnej, abstrakcyjnej warstwy na start.** Obecny model (Goal, Task, Milestone, Project, RecentActivity, Attention) pokrywa się z tym, co potrzebne do Agency-First — dodaje się tylko observability gaps i goal-level review gates.

---

## 2. Current State — Co już mamy

### 2.1 Granica Janus ↔ Hermes (ADR-001)
- **Hermes:** agent runtime, kanban, dispatch, task lifecycle (todo/ready/running/review/done/blocked), review workflow, execution history, safety gates, repository integration, sdlc-review skill.
- **Janus:** domena. Models (`Goal`, `Task`, `Milestone`, `Project`, `AttentionItem`, `WeeklyReview`, `GoalReview`, `RecentActivityEntry`, `EvidencePackage`, `ExecutionResultMessage`, `JanusDomainMetadata`), services (`goals`, `tasks`, `milestones`, `projects`, `goal_progress`, `next_action`, `attention`, `daily_briefing`, `weekly_review`, `execution_feedback`, `strategic_summary`, `inbox`, `followup`, `observability`, `activity_ingest`, `verification`, `integration`, `curation`), integrations (`markdown_goals`, `markdown_tasks`, `google_calendar`, `obsidian_promoter`, `janus_sync`, `replenishment`).

Wszystko to jest spójne i nie konfliktuje z Agency-First.

### 2.2 Goal → Task → Execution → Completion → Review — co działa już
- Tasks mają `todo/in_progress/blocked` — ale **nie mają `under_review`**. Review istnieje jako Kanban phase (`kanban_request_review`), nie jako domenowy stan.
- Gdy task zichnie w Hermes jako done, Hermes może wywołać `dispatch_completion()` w Janus (execution_feedback service). Tam następuje routing do:
  - `update_goal_progress` (metric/task progress, evidence append do `recent_activity`)
  - `complete_janus_task` (chkbox flip w tasks.md, evidence metadata)
  - `update_milestone_status` (auto-complete, evidence)
  - `_ingest_research` / `_ingest_decision` (future / design-complete)
- `dispatch_completion()` przepuszcza task przez **ADR-004 Phase 5 gates** tylko jeśli task jest otwarty i live w repo; w przeciwnym razie jest idempotent re-evidence update.
- Gates: Phase 1 resync, Phase 3 deterministyczna weryfikacja (clean tree, tests, diff --check), Phase 4 integracja, Phase 5 gated completion.
- Goal integrity audit (`janus goal audit`) — read-only health checks, 4 issue types.
- Attention engine + daily briefing + weekly review — existing health signals (stalled, overdue, deadline soon, milestone slipped, goal inactive).
- Next action derivation (`janus goal next <title>`) — istnieje, zasada R1-R5, oparta na milestone sequence.

### 2.3 Repozytorium — struktura (z repository_inventory_findings.md)
- Python 3.11 CLI app, 94 pliki źródłowe, ~36.5k LOC.
- Warstwy: CLI → services → integrations → models.
- 84 pliki testów, ~28.4k LOC, ratio ~0.78.
- 33 service moduły (28 z dedicated tests), 25 domenowych modeli, 14 integrations, 2 pluginy (janus_sync, replenishment).
- Największe moduły: activity_ingest.py (1533 LOC), execution_feedback.py (1019 LOC), goals_cli.py (1552 LOC), strategic_summary.py (1701 LOC), tasks.py (1010 LOC), verification.py (2690 LOC).
- Luki: brak type checking/linting config, 5 services bez dedicated tests, kilka modułów >1000 LOC.

### 2.4 ADR-y — status (z adr_audit_report.md)
11 ADR/decision documents covering:
- ADR-001: Hermes/Janus system model — aktualny, aktywny
- ADR-002: Obsidian curated knowledge layer — aktualny, bez Obsidian write implementacji
- ADR-003: Canonical review topology (Model A) — fully implemented
- ADR-004: Safe sync-and-integrate workflow — kodowo kompletny, runtime dormancy
- ADR-005 + ADR-005-A1: Activity ingestion — resolved, `data_protection.py` deleted
- Poza ADR-001..005: milestone status lifecycle (S1), review probes (S2), vault versioning, consolidated decision records.

Kluczowe luki w ADR status signals:
- ADR-004 status: „Accepted with implementation caveats" — stale (pre-PR-189)
- ADR-005 status: references legacy incomplete migration — superseded
- Dwa consolidated ADR files: overlapping, unclear który jest authoritative

### 2.5 Test coverage — co jest chronione
- 84 test pliki, ~28.4k LOC.
- 28 z 33 services mają dedicated tests.
- Luki: obsidian_promoter.py (293 LOC, brak testu), followup.py (230 LOC), inbox.py (142 LOC), project_progress.py — bez dedicated testów.
- Brak mypy/pyright, ruff/flake8.
- Observability: 41 dedicated tests, 579 total passing.
- Execution feedback + gates: testy istnieją (test_execution_feedback.py, test_task_complete_gates.py, test_task_complete_janus_gates.py, test_janus_sync_plugin.py).

---

## 3. Gap Analysis względem Agency-First Development Phase

### 3.1 Already exists
- **Granica Hermes/Janus** — ADR-001, w pełni aktywna.
- **Task Execution i Completion gates** — ADR-004 Phase 5, w pełni zaimplementowane w kodzie (choć Phase 1 auto-sync dormancy).
- **Evidence model** — `EvidencePackage`, `ExecutionResultMessage`, `JanusDomainMetadata`, `attach_evidence()`, `propagate_state_updates()`. To jest już „evidence before inference" materializowane.
- **Verification** — `janus verify-contract` + verification pipeline (phases 1/2/3 + adversarial E2E).
- **Review workflow na poziomie Kanban** — `kanban_request_review`, review dispatch, `request_changes`, reviewer provenance. To jest „review" w tym sensie, że istnieje proces human-in-the-loop.
- **Goal health signals** — attention engine, weekly review, goal audit.
- **Deterministic goal next-action derivation** — `janus goal next`.
- **Obsidian curation principle** — ADR-002, flow Raw → Operational → Analysis → Curation → Obsidian.
- **Activity ingestion gateway** — ADR-005, `atomic_io` + `data_integrity` composition.

### 3.2 Partially exists
- **Review phase w domenie Janus.** Kanban ma review phase, ale Janus Task nie ma stanu `under_review`. To powoduje, że „execution done → awaiting review → review complete → completion accepted" nie ma domenowego enforcement. Obecnie review to tylko Kanban-level process, a nie Janus lifecycle state. To kluczowy gap.
- **Goal-level completion gates.** `complete_goal()` nie ma żadnych gate'ów — tylko status change. Task-level gates istnieją, ale Goal-level nie. To gap pod kątem „authoritative Goal state".
- **Metric advancement idempotency.** `update_goal_progress()` może nadpisać `current_value` bez guarda — task_id jest idempotentny w `recent_activity`, ale nie w metryce. To średni gap.
- **Personal State Model** — obecne modele (Goal, Task, Milestone, Project, RecentActivity, Attention, Event, Workout, DailyBriefing, WeeklyReview) są początkiem Personal State, ale nie ma spójnego, surrealnego „PersonalState" modelu, który agreguje te rzeczy w jeden authoritative view. Częściowo istnieje w `strategic_summary.py` (który próbuje to zrobić deterministycznie).
- **Policy / Approval (ALLOW/ASK/DENY).** Brak explicit modelu. Obecnie to jest „tricky" — nie ma formalnego policy engine. Co można zrobić: najpierw zdefiniować cooldown/gate-based approval (co jest już w ADR-004 gates), a potem ewentualnie rozszerzyć do explicit policy. Bez czegokolwiek speculative.

### 3.3 Missing
- **`under_review` state w Janus Task.**
- **Goal-level completion gates.**
- **Metric advancement idempotency guard.**
- **Tightened milestone auto-completion derivation** — obecnie dynamiczne `derive_milestone_tasks()` zależy od denormalizowanej `related_tasks` cache.
- **Pewne elementy z „janus-agency-first-development-phase.md" (którego nie ma)** — ale nie wiadomo, co dokładnie tam miało być. Należy najpierw zdefiniować, co to dokument miał reprezentować, i albo go stworzyć, albo niego usunąć z roadmapy.
- **Formalny Policy/Approval model.** Brak.

### 3.4 Should NOT be implemented (jeszcze / nie ma uzasadnienia)
- **Speculative Personal State Model jako osobna warstwa.** Obecny model jest początkiem — nie ma potrzeby wydzielać go jako osobnego modelu przed stabilizacją lifecycle enforcement.
- **Active writing do Obsidian bez stable Janus knowledge layer.** ADR-002 mówi, że Obsidian to curated layer. Zanim będzie Obsidian write, musi być stable Janus knowledge model — w obecnej fazie jest to premature.
- **Calendar write-back.** Product backlog jest „planned", nie ready.
- **Research knowledge pipeline.** Product backlog jest „planned", nie started.
- **Multi-agent orchestration.** To jest P3, a Agency-First fala to najpierw P0 + P1 (lifecycle enforcement, evidence, review state, goal gates).
- **Pre-mature execution_mode / support_mode abstractions** (USER / JANUS / COLLABORATIVE oraz EXPLAIN / COACH / SCAFFOLD / REVIEW / EXECUTE). Zanim są użyte w kodzie, nie mają jeszcze konkretnego problemu do rozwiązania. Można je zdefiniować jako **documentation decisions** dopiero wtedy, gdy będzie konkretny warstwa, która ich potrzebuje — np. task execution mode decyzyjny.

---

## 4. Target Architecture — Proponowany model domenowy

### 4.1 First-class concepts (część już istnieje, część częściowo)

| Concept | Obecny stan | Role w Agency-First |
|---------|-------------|---------------------|
| Goal | Istnieje (active/completed/inactive) | Authoritative high-level intent |
| Metric | Istnieje (metric_name/unit/start/current/target/direction) | Quantified outcome; progress computation |
| Task | Istnieje (todo/in_progress/blocked) | Atomic action unit; execution vehicle |
| Milestone | Istnieje (FSM, dynamic task membership) | Intermediate goal checkpoint |
| Project | Istnieje (auto-complete when tasks done) | Execution unit grouping |
| Plan | **Partial** — execution_planning.md, next_action derivation, milestone/project hierarchy design. Brak formalnego first-class Plan modelu. | Sequencing, next-action, execution planning |
| User Action | **Missing** jako first-class — obecnie user działa jako part of execution (task complete by user, or Hermes agent). User jest outside Janus (w Hermes). | Explicit user intent, approval, handoff from user to Janus execution |
| Execution | Istnieje (task execution, execution_feedback path, EvidencePackage, dispatch_completion) | Proof that work was done + effect |
| Evidence | Istnieje (EvidencePackage, ExecutionResultMessage, recent_activity, observability events). Brak formalnego „Evidence" modelu jako abstract — jest wydzielone w execution_feedback service. | Auditability, progress, verification |
| Verification | Istnieje (verify-contract, verification pipeline, goal audit) | Deterministic correctness check |
| Completion | Istnieje (task complete, goal complete) + gates (ADR-004) | Terminal state transition |
| Review | **Partial** — Kanban review phase, brak Janus Task `under_review` state. | Quality gate, human/agent approval |
| Decision | Istnieje w postaci ADR-ów (decision records), brak modelu „Decision" jako domenowy obiekt w Janus | Architectural/domain decisions, policy decisions |

### 4.2 Recommended first-class additions (minimal)

1. **`TaskState.under_review`** — między `in_progress` a completed. To zamknie lifecycle gap.
2. **`Goal-level completion gates`** — podobne do task-level gates, ale na poziomie Goal. Może być prostsze (np. require all milestones/states, require evidence, weryfikacja goal integrity).
3. **Dokumentacja jako „Plan" koncepcja** — aby nie powielać, można najpierw zdefiniować Plan jako **„ordered set of Milestones/Tasks/next-action sequences"**, bez nowego modelu, a jako uporządkowany widok na istniejące entity. Jeśli zaś Plan ma własną lifecycle, to wtedy można zastanowić się o Plan model.

### 4.3 Sources of truth

- **Goal:** dominujący dla intentu + metric. Jest źródłem prawdy dla „co chcemy osiągnąć".
- **Task:** źródło prawdy dla „co zostało zrobione / co trzeba zrobić".
- **Milestone:** checkpoints, ale bosą zależność do Goal (dynamiczne task membership).
- **Evidence:** execution_feedback service + recent_activity + observability events.
- **Verification:** verify-contract + gate pass.
- **Review:** Kanban review + potencjalny Janus `under_review` state.

### 4.4 Invariants — co powinno być chronione

- Goal w statusie `completed` nie może mieć otwartych tasków bez explicite reason (np. abandoned).
- Jeśli Goal ma metric, to przy każdym update wartość musi być spójna (idempotent guard).
- Milestone auto-completion powinno wymagać explicit task linkage bezpośredniego, nie tylko dynamicznego `derive_milestone_tasks()` ze starej `related_tasks` cache.
- Evidence para (task execution + goal update) powinna być przechowywana z trace_id / correlation_id — to już częściowo w observability structured events.
- Review nie może być omijany przez task completion — jeśli review jest wymagane, task nie może przejść do `done` bez przejścia przez `under_review` -> review -> complete.

### 4.5 Granice odpowiedzialności

- **Janus:** domena, modele, bussines logic, persistence, deterministic processing, gates, evidence, verification.
- **Hermes:** agent orchestration, kanban, task lifecycle (todo/ready/running/review/done/blocked), review workflow, dispatch, execution history. Hermes może wywoływać Janus services (execution_feedback), ale Janus nie woła Hermes.
- **User:** intent, approval w żaden sposób nie jest automatycznie „done" przez agenta bez explicite user confirmation, gdzie policy to wymaga.

---

## 5. ADR Plan

### 5.1 Kto z istniejących ADR-ów jest aktualny / nieaktualny

| ADR | Status | Agency-First komentarz |
|-----|--------|------------------------|
| ADR-001 (Hermes/Janus) | Aktualny, aktywny, fundament | OK |
| ADR-002 (Obsidian curated knowledge layer) | Aktualny, aktywny, ale bez implementacji Obsidian write. Vault versioning decision downstream. | OK, ale Obsidian write musi być deferred do stable Janus knowledge layer. |
| ADR-003 (Canonical review topology, Model A) | Aktualny, fully implemented. Model B rejected. ADR-003-S1 i S2 supplements. | OK. Ale brakuje Janus-domain `under_review` — czy to jest „rozszerzenie ADR-003" czy nowy ADR? |
| ADR-004 (Safe sync-and-integrate workflow) | Kodowo kompletny, ale runtime dormancy (janus_sync plugin not loaded). Status w consolidated ADR-y jest stale (pre-PR-189). | Update status + add runtime caveat. Ewentualnie nowy ADR o lifecycle review enforcement. |
| ADR-005 + ADR-005-A1 (Activity ingestion) | Resolved. `data_protection.py` deleted. Deferred SHA-256/flock/post-write verification to `t_1f9c2a7`. | OK. |
| Consolidated decision records (adr-consolidated-decisions.md, adr-003-004-005-consolidated-decisions.md) | Overlapping, stale ADR-004 status. Which is authoritative? | Potrzebne rozstrzygnięcie. |

### 5.2 ADR-y, które warto rozważyć (Proposed)

1. **ADR-NNN: Task Lifecycle Review State** — dodaj `under_review` do Task modelu, definiuj przejścia, wiąż z Kanban review. To jest naturalne rozszerzenie ADR-003. Jeśli zrobisz to jako ADR, to będzie „extension of ADR-003", a nie zamiennik.
2. **ADR-NNN: Goal-Level Completion Gates** — jeśli zdecydujesz się na goal-level gates, to warto mieć ADR, żeby zdefiniować co gate sprawdza, jakie warunki, jakie traces.
3. **ADR-004 Update (Status + Runtime Caveat)** — nie nowy ADR, ale update istniejącego ADR-004 statusu w consolidated dec recordach, aby odzwierciedzał kodowy stan (caveat: runtime plugin loading).
4. **Ewentualnie ADR-NNN: Minimal Policy / Approval Model** — jeśli zdecydujesz się, że user approval musi być formalny. Na razie warto odłożyć do momentu, gdy będziesz miał lifecycle enforcement stable.

### 5.3 ADR-y, których nie tworzymy
- Nie ma potrzeby tworzenia ADR-ów dla każdego małego featureu. ADR-y dla P0/P1 gapów, które są istotne architektonicznie.

---

## 6. Roadmap — proponowana P0 → P1 → P2 → P3

### 6.1 P0 — Konieczne fundamenty (stabilizacja lifecycle enforcement)

1. **Załaduj `janus_sync` plugin w Hermes config** lub dokumentuj gated completion jako opt-in. To jest najwyższy priorytet — bez tego ADR-004 nie jest w produkcji.
2. **Zaktualizuj roadmap items 9-12 z `[ ]` na `[x]`** — one są wdrożone.
3. **Zaktualizuj ADR status signals** (ADR-004, ADR-005, consolidated ADR files).
4. **Dodaj `Task.under_review` state** — minimalny, ale kluczowy lifecycle gap.
5. **Dodaj goal-level completion gates** (na poziomie `complete_goal()`).
6. **Zabezpiecz metric advancement idempotency** — guard przed double-counting.
7. **Tightened milestone auto-completion derivation** — explicit task linkage.

Each z tych może być osobnym PR-em.

### 6.2 P1 — Bezpośrednio potrzebne dla Agency-First

8. **Zdefiniuj formalny „Plan" jako domenowy koncept** (jeśli potrzebny) — może być uporządkowany widok, może być model. To zależy od tego, czy chcesz mieć „Plan" jako first-class entity.
9. **Rozszerz Personal State Model** — agreguj Istniejący model (Goal, Task, Milestone, Project, RecentActivity, Attention, Event, Workout, DailyBriefing, WeeklyReview) w jeden authoritative view. Może być tylko diale, a nie nowy model.
10. **Dodaj minimalny Policy/Approval model (ALLOW/ASK/DENY)** — jeśli potrzebny. Na razie może być prosty: co jest ALLOW (deterministiczne), co ASK (user confirmation), co DENY (blocked). To może być rozszerzenie existing gates.

### 6.3 P2 — Wartościowe rozszerzenia

11. **Execution mode / Support mode abstractions** — dopiero wtedy, gdy masz konkretne zastosowanie.
12. **Obsidian write integration** — dopiero po stabilnym Janus knowledge layer.
13. **Research knowledge pipeline** — dopiero po stabilnym modelu.
14. **Calendar-aware planning** — dopiero po calendar integration.

### 6.4 P3 — Późniejsze / eksperymentalne

15. Multi-agent orchestration.
16. Self-extending skills.
17. Connector protocol.
18. Personal finance domain.

---

## 7. Immediate Implementation Plan — zadania i PR-y

### Task 1: Load janus_sync plugin or document opt-in.
- **Scope:** albo dodać do config, albo dodać do dokumentacji.
- **Tests:** konfiguracja + ewentualny test plugin loading.
- **PR boundary:** Hermes config lub Janus doc.

### Task 2: Update roadmap items 9-12 + ADR status.
- **Scope:** wkleić w `docs/roadmap.md` i ADR files.
- **Tests:** brak, to jest dokumentacja.
- **PR boundary:** docs only.

### Task 3: Dodaj `Task.under_review` state + lifecycle.
- **Scope:** model, service, persistence, testy.
- **Tests:** unit + lifecycle E2E.
- **PR boundary:** `src/janus/models/task.py`, `src/janus/services/tasks.py`, `tests/`.

### Task 4: Dodaj goal-level completion gates.
- **Scope:** `complete_goal()` gates, evidence.
- **Tests:** unit + integration.
- **PR boundary:** `src/janus/services/goals.py`, `tests/`.

### Task 5: Metric advancement idempotency guard.
- **Scope:** `update_goal_progress()` guard.
- **Tests:** idempotency testy.
- **PR boundary:** `src/janus/services/goals.py`, `tests/`.

### Task 6: Tighten milestone auto-completion derivation — explicit task linkage.
- **Scope:** `derive_milestone_tasks()` improvement.
- **Tests:** derivation testy.
- **PR boundary:** `src/janus/services/next_action.py` lub `milestones.py`, `tests/`.

### Task 7: Stwórz lub usuń `docs/janus-agency-first-development-phase.md`.
- **Scope:** albo stwórz dokument, albo usuń referencję z roadmapy.
- **Tests:** brak.
- **PR boundary:** docs only.

---

## 8. Proposed `docs/roadmap.md` diff

```diff
 # Agency-First Janus

 See [Agency-First Development Phase](janus-agency-first-development-phase.md).

 Janus should optimize for increasing user capability and agency,
 not maximizing autonomous agent execution.

 Key phases:
 - [ ] Complete Goal → Task → Execution → Completion → Review
 - [ ] Evidence & Audit
 - [ ] Personal State Model
 - [ ] Agency-Aware Planning
 - [ ] Policy & Approval
 - [ ] Connector Protocol
 - [ ] Self-Extending Skills
 - [ ] Multi-Agent Orchestration
+
+## Agency-First Implementation Roadmap
+
+### P0 — Lifecycle enforcement foundations
+
+- [ ] Load janus_sync plugin in Hermes config or document gated completion as opt-in
+- [x] Update roadmap items 9-12 from [ ] to [x] (verified implemented)
+- [ ] Update ADR status signals (ADR-004, ADR-005, consolidated records)
+- [ ] Add `under_review` state to Janus Task model (lifecycle gap)
+- [ ] Add goal-level completion gates (authoritative Goal state)
+- [ ] Strengthen metric advancement idempotency (guard against double-counting)
+- [ ] Tighten milestone auto-completion derivation (explicit task linkage)
+
+### P1 — Agency-Aware extensions
+
+- [ ] Define formal Plan concept (if needed; first-class or ordered view)
+- [ ] Extend Personal State Model (aggregate existing entities into authoritative view)
+- [ ] Minimal Policy/Approval model (ALLOW/ASK/DENY)
+
+### P2 — Value extensions
+
+- [ ] Execution mode / support mode abstractions (when concrete use case exists)
+- [ ] Obsidian write integration (after stable Janus knowledge layer)
+- [ ] Research knowledge pipeline (after stable model)
+- [ ] Calendar-aware planning (after calendar integration)
+
+### P3 — Later / experimental
+
+- [ ] Multi-agent orchestration
+- [ ] Self-extending skills
+- [ ] Connector protocol
+- [ ] Personal finance domain
```

Te zmiany powinny być poprzedzone stworzeniem lub usunięciem `docs/janus-agency-first-development-phase.md`.

---

## 9. Risks / Open Questions

1. **Czy `janus-agency-first-development-phase.md` powinien istnieć i co zawiera?** Nie wiem. Trzeba to ustalić na start.
2. **Czy Policy/Approval model jest konieczny na tym etapie?** Nie jestem pewien — może być więc przyspieszyć. Proponuję odłożyć do momentu, gdy będziesz miał lifecycle enforcement.
3. **Czy `under_review` state powinien być w Janus Task, czy tylko w Kanban?** To jest decyzja architektoniczna — proponuję Janus Task, aby zamknąć lifecycle gap, ale to może być nadmierne.
4. **Czy goal-level completion gates są konieczne, czy task-level gates wystarczają?** To zależy od tego, jak silnie chcesz enforcement na poziomie Goal. Proponuję zrobić, bo to zamyka autoritet Goal state.
5. **Czy Execution mode / Support mode abstractions są potrzebne?** Nie do końca — może być premature. Proponuję zdefiniować je tylko wtedy, gdy będziesz miał konkretny problem.
6. **Który z consolidated ADR files jest authoritative?** `adr-consolidated-decisions.md` (211 lines, full) vs `adr-003-004-005-consolidated-decisions.md` (84 lines, summary). Trzeba to rozstrzygnąć — zostawić jeden, usunąć drugi lub zmerge'ować.

---

## 10. Task decomposition — zadania dla najbliższego etapu

Każdy z poniższych powinien być osobnym Kanban task-em z jasnym scope, acceptance criteria, i suggested PR boundary.

### Task A: Załaduj janus_sync plugin lub dokumentuj opt-in
- **Title:** Load janus_sync plugin in Hermes config or document ADR-004 as opt-in
- **Objective:** Ustawia ADR-004 compliance w produkcji (lub dokumentacja jako opt-in).
- **Scope:** Konfiguracja Hermes plugins.enabled, eventuell janus.pth update, dokumentacja runtime caveat.
- **Out of scope:** Zmiana plugin implementation.
- **Dependencies:** Brak.
- **Acceptance criteria:**
  - janus_sync jest w plugins.enabled, lub
  - dokumentacja wyraźnie mówi, że gated completion jest opt-in/dormant.
- **Tests:** Jeśli plugin loading, test konfiguracji + ewentualny smoke test.
- **Suggested PR boundary:** Hermes config + Janus doc update.

### Task B: Update roadmap items 9-12 + ADR status signals
- **Title:** Refresh stale roadmap and ADR status signals
- **Objective:** Usunąć stale/ambiguous sygnały z roadmapy i ADR files.
- **Scope:** `docs/roadmap.md` items 9-12 → `[x]`; ADR-004 status → „Accepted" (caveat: runtime plugin availability); ADR-005 status → „criteria met"; consolidated ADR files → jednoznaczny authoritative.
- **Out of scope:** Zmiana implements.
- **Dependencies:** Task A (jeśli chcemy czytelny ADR-004 status).
- **Acceptance criteria:**
  - roadmap items 9-12 są `[x]`.
  - ADR-004 status field odzwierciedla post-PR-189 state.
  - ADR-005 status field odzwierciedla ADR-005-A1 resolution.
  - Konsolidacja/usuwanie jednego z overlapping ADR files.
- **Tests:** Brak (dokumentacja).
- **Suggested PR boundary:** docs only.

### Task C: Dodaj `Task.under_review` state + lifecycle
- **Title:** Add `under_review` state to Janus Task model and lifecycle
- **Objective:** Zamknąć lifecycle gap — formalny review phase w domenie.
- **Scope:** `models/task.py` (dodaj `under_review` do ALLOWED_STATES), `services/tasks.py` (przejścia todo/in_progress → under_review → completed), persistence (`markdown_tasks.py`), testy.
- **Out of scope:** Zmiana Kanban review workflow (to jest osobny system).
- **Dependencies:** Task B (dokumentacja może wskazywać, że to jest w implementacji).
- **Acceptance criteria:**
  - Task ma stan `under_review`.
  - Przejścia: in_progress → under_review (np. po dispatch_completion wymaganego review), under_review → completed (po review accept).
  - Persistence zapisuje/odczytuje `under_review`.
  - Testy: unit + lifecycle E2E.
- **Tests:** `tests/test_tasks_under_review.py` (nowy) + ewentualne istniejące testy lifecycle.
- **Suggested PR boundary:** `src/janus/models/task.py`, `src/janus/services/tasks.py`, `src/janus/integrations/markdown_tasks.py`, `tests/`.

### Task D: Dodaj goal-level completion gates
- **Title:** Implement goal-level completion gates
- **Objective:** Uzupełnić task-level gates o goal-level enforcement.
- **Scope:** `services/goals.py` (`complete_goal()` z gates — np. weryfikacja goal integrity, weryfikacja że wszystkie milestones/zadania są spójne, evidence), `tests/`.
- **Out of scope:** Zmiana task-level gates (już istnieją).
- **Dependencies:** Task C (under_review state może być inputem do goal gates, jeśli goal oczekuje, że wszystkie tasks przechodzą przez review).
- **Acceptance criteria:**
  - `complete_goal()` uruchamia gates przed completion.
  - Gates mogą zawierać: goal integrity audit pro meso, weryfikacja że wszystkie related_tasks są handled (completed/blocked/in_review).
  - Fail-stop z reason codes.
- **Tests:** `tests/test_goal_complete_gates.py` (unit + integration).
- **Suggested PR boundary:** `src/janus/services/goals.py`, `tests/`.

### Task E: Metric advancement idempotency guard
- **Title:** Add idempotency guard to metric advancement in update_goal_progress
- **Objective:** Zapobiec double-counting przy re-completion tasku.
- **Scope:** `services/goals.py` (`update_goal_progress()` — guard: tylko update jeśli task_id nie jest jeszcze z tą samą wartością), `tests/`.
- **Out of scope:** Zmiana celów mechanizmu recent_activity (już idempotentny).
- **Dependencies:** Brak.
- **Acceptance criteria:**
  - Jeśli task_id jest już w recent_activity z tą samą wartością, nie nadpisuje current_value.
  - Jeśli task_id jest z inną wartością, to update (ewentualnie z logowaniem warningu).
- **Tests:** `tests/test_goal_metric_idempotency.py`.
- **Suggested PR boundary:** `src/janus/services/goals.py`, `tests/`.

### Task F: Tighten milestone auto-completion derivation
- **Title:** Require explicit task linkage for milestone auto-completion
- **Objective:** Zapobiec auto-completion milestoneu z denormalizowanej related_tasks cache.
- **Scope:** `services/next_action.py` lub `milestones.py` (`derive_milestone_tasks()` — explicit task linkage requirement), `tests/`.
- **Out of scope:** Zmiana milestone modelu (już istnieje).
- **Dependencies:** Task C (jeśli under_review wpływa na milestone derivation).
- **Acceptance criteria:**
  - `derive_milestone_tasks()` wymaga explicit task membership, nie tylko dynamicznego wywodzenia z related_tasks.
  - Milestone auto-completion sprawdza tylko te taski, które są explicite przypisane.
- **Tests:** `tests/test_milestone_derivation.py`.
- **Suggested PR boundary:** `src/janus/services/next_action.py` lub `milestones.py`, `tests/`.

### Task G: Stwórz lub usuń `docs/janus-agency-first-development-phase.md`
- **Title:** Create or remove missing janus-agency-first-development-phase.md reference
- **Objective:** Usunąć broken reference z roadmapy.
- **Scope:** Albo stwórz dokument (jeśli miałby zawierać Agency-First phases detail), albo usuń referncje z `docs/roadmap.md`.
- **Out of scope:** Implementacja phases (to jest priorytet P0).
- **Dependencies:** Brak.
- **Acceptance criteria:**
  - Reference w roadmapie nie prowadzi do broken linkiem, lub
  - Plik istnieje z zawartością.
- **Tests:** Brak.
- **Suggested PR boundary:** docs only.

---

## 11. Najważniejsze ograniczenia

### NIE:
- nie implementuj feature'ów,
- nie twórz kodu produkcyjnego,
- nie refaktoruj repo,
- nie twórz masy speculative abstractions,
- nie zakładaj, że większa autonomia agenta = lepszy Janus,
- nie dodawaj integracji tylko dlatego, że inne agenty je mają.

### TAK:
- analizuj istniejący kod,
- wykorzystuj istniejące ADR-y,
- wykorzystuj istniejące testy,
- identyfikuj rzeczywiste gaps,
- minimalizuj nowe abstrakcje,
- zachowaj obecny Goal → Task → Execution → Completion → Review loop,
- traktuj user agency jako nadrzędne kryterium architektoniczne,
- przygotuj implementację tak, aby można było ją wykonywać przez niezależne PR-y.

---

*End of triage.*
