# PHASE PEDAGOGY-1 — QA Verification

## Scope

Session and cluster introduction cards appear **before** teaching. Zone 0, Zone 1, VTSE, Timeline, Clarity Gate, and progression logic are **not modified** — only a pre-teach intercept was added.

## 1. Database changes

| Entity | New fields |
|--------|------------|
| `ClassSessionPlan` | `session_study_points`, `session_learning_outcomes` (uses existing `title`, `description`) |
| `CurriculumCluster` | `description`, `study_points`, `learning_outcomes` (uses existing `title`) |
| `Session` (runtime) | `pedagogy_session_intro_done`, `pedagogy_cluster_intro_done_for` |

No migration required — missing fields default to empty / false.

## 2. API changes

- `PUT /classroom/plans/{id}` and `PATCH /admin/catalog/classroom/plans/{id}` accept `session_study_points`, `session_learning_outcomes`
- `PUT /curriculum/clusters/{id}` accepts `description`, `study_points`, `learning_outcomes`
- Runtime: `session_intro_card` and `cluster_intro_card` response types with `pedagogy_card` + `visual.type=pedagogy_intro`
- Actions: `__action:session_intro_done`, `__action:cluster_intro_done`

## 3. Admin UI

- `ClassroomPlanningPanel` (catalog scope): Session introduction editor on each plan
- `CurriculumBuilder`: Cluster description + bullet editors

## 4. Teacher UI

- Identical components — same `ClassroomPlanningPanel` + `CurriculumBuilder`
- Import/clone copies cluster pedagogy fields via `CurriculumCloneService`

## 5. Runtime flow

```
Session start → [Session Card?] → [Cluster Card?] → Zone 0 / Zone 1 / Zone 2+ entry → existing teaching
Cluster transition → [Cluster Card?] → existing teaching (no session card repeat)
```

Intercept location: `session_service._teacher_handle_conversation` **before** Zone 0 intercept.

## 6. TTS flow

- Narration built in `PedagogyIntroService._build_narration`
- Frontend: hidden `WordSyncedStreaming` speaks narration; card visible on whiteboard
- After TTS: auto `__action:session_intro_done` / `__action:cluster_intro_done`

## 7. Restore behavior

- `pedagogy_session_intro_done=true` → skip session card
- `pedagogy_cluster_intro_done_for >= current_cluster_index` → skip cluster card
- Board turns persist with `response_type` `session_intro_card` / `cluster_intro_card`
- Mid-intro resume replays card if flags not yet set

## 8. Files changed

### Backend
- `models/classroom/class_session_plan.py`
- `models/curriculum/curriculum_cluster.py`
- `models/learning/sessions.py`
- `api/schemas/classroom.py`, `curriculum_structure.py`
- `api/routes/classroom.py`, `admin_catalog_classroom.py`, `curriculum_structure.py`
- `services/classroom/class_session_plan_service.py`
- `services/curriculum/curriculum_cluster_service.py`, `curriculum_clone_service.py`
- `services/pedagogy/pedagogy_intro_service.py` (new)
- `services/session_service.py` (intercept + board persist only)
- `tests/pedagogy/test_pedagogy_intro_service.py` (new)

### Frontend
- `components/classroom/BulletListEditor.tsx`, `SessionIntroductionEditor.tsx` (new)
- `components/classroom/ClassroomPlanningPanel.tsx`
- `components/curriculum/CurriculumBuilder.tsx`
- `components/learning/PedagogyIntroCard.tsx` (new)
- `components/ai/AIWhiteboard.tsx`
- `hooks/useChat.ts`, `lib/api.ts`, `lib/tutorFlow.ts`, `lib/sessionRestore.ts`
- `lib/learning/zone0Chat.ts`, `lib/types.ts`, `lib/types/classroom.ts`
- `lib/api/classroom.ts`, `catalogClassroom.ts`, `curriculumStructure.ts`
- `app/(app)/learn/[topicId]/page.tsx`

## 9. Zone 0 / Zone 1 untouched verification

| Area | Status |
|------|--------|
| `zone0_handler.py` | **Not modified** |
| `explanation_handler.py` / VTSE | **Not modified** |
| `zone1_timeline_finalize.py` | **Not modified** |
| `ProductionTimelineRuntimeView` | **Not modified** |
| Cluster quiz / teachback handlers | **Not modified** |
| Clarity gate | **Not modified** |
| `plan_progress_coordinator.py` | **Not modified** |
| Zone 0 intercept block in `session_service.py` | **Not modified** (pedagogy intercept added **above** it) |

Run regression:

```bash
cd backend && pytest tests/integration/test_zone0_flow.py tests/progression/test_plan_zone_session_start.py tests/pedagogy/test_pedagogy_intro_service.py -q
```

Expected: all pass; Zone 0 phase transitions unchanged after intro completes.

## 10. HOTFIX (PEDAGOGY-1 audit)

### Root causes

| Bug | Root cause |
|-----|------------|
| 1–4 Prose / missing headings / merged bullets | `AskQuestionResponse` hard-coded `visual=None`, so frontend never received `pedagogy_card`; whiteboard fell back to visible narration `message` |
| 5 Cluster intro loop | `int(done_for or -1)` treated cluster index `0` as unset (`-1`), so `cluster_intro_done` never stuck; plus re-emit while `flow_state` was `pedagogy_cluster_intro` |
| 6 Zone 0 never starts | After `cluster_intro_done`, pedagogy set `session.flow_state=idle` but local `flow` in `_teacher_handle_conversation` stayed stale → Zone 0 intercept skipped |

### Fixes

- `sessions.py`: pass `visual` and `pedagogy_card` through API
- `pedagogy_intro_service.py`: strict wait states — while on intro screen only matching `*_done` action advances; headings `SESSION N` / `CLUSTER`
- `session_service.py`: refresh `flow` after pedagogy returns `None`
- `PedagogyIntroCard.tsx`: structured card only (TTS narration sr-only)
- `tutorFlow.ts`: preserve pedagogy flow on `noop` while waiting for TTS

### QA proof (manual)

**Zone 0 topic**

```
Session start → SESSION N card (bullets) → CLUSTER card (bullets) → Zone 0 anchor
```

**Zone 1 topic (Zone 0 skipped/done)**

```
Session start → SESSION N card → CLUSTER card → Zone 1 explanation
```

Verify: no repeated cluster blocks; no “Welcome to…” prose on whiteboard; Zone 0/1 behavior unchanged after intros complete.
