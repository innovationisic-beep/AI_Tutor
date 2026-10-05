# QA: Photosynthesis V2 Final

Manual verification for structured curriculum (v2) end-to-end.  
Use these exact topic names for traceability.

| Role | Topic name |
|------|------------|
| Admin (catalog) | **Photosynthesis V2 Final** |
| Teacher (org copy) | **Photosynthesis Teacher V2 Final** |

---

## Prerequisites

- Backend and frontend running
- Admin account
- Teacher account (institution org with at least one class/subject)
- Independent or institution student account for launch tests

---

## 1. Admin — Create structured curriculum

1. Log in as **admin** → `/admin/curriculum`
2. Select subject → **New topic** → name: `Photosynthesis V2 Final`
3. Open **Structured curriculum** (builder) for the topic
4. Add Zone 0 (curiosity) if required, Zone 1 clusters/concepts
5. Add **structured notes** and **structured questions** on at least one concept
6. **Publish** curriculum
7. Confirm readiness: v2, published, class sessions enabled

**Expected:** Legacy Concepts/Notes/Questions tabs are **hidden** for this v2 topic. Only Learning Flow + workflow nav (Curriculum / Session planning) visible.

---

## 2. Admin — Session planning (independent students)

1. From builder → **Session planning**
2. Create **Session 1** with Zone 1 Cluster A coverage
3. Create **Session 2** with next cluster; **Session 3** with Zone 2 cluster if applicable
4. Validate and **publish** each plan

**Expected:** Plans appear in student session picker for catalog topic.

---

## 3. Teacher — Import or create topic

**Option A — Import**

1. Teacher → workspace → **Import curriculum** for class/subject
2. Confirm **Photosynthesis Teacher V2 Final** (or import Photosynthesis V2 Final)
3. Verify structured tree copied (zones/clusters/concepts), not flat key_concepts only

**Option B — Manual**

1. Create teacher topic `Photosynthesis Teacher V2 Final`
2. Open **Structured curriculum** → build tree → publish

**Expected:** Workspace hides Concepts/Notes/Questions tabs for v2. Workflow nav shows Curriculum + Session planning.

---

## 4. Teacher — Classroom session planning

1. Workspace → select topic → **Session planning**
2. Create Session 1 / 2 / 3 with cluster coverage (match admin pattern)
3. Publish plans → schedule instance → enroll class (institution)

---

## 5. Student — Launch session

**Independent (catalog)**

1. Browse to catalog topic **Photosynthesis V2 Final**
2. **Choose a session** (Session 1/2/3) if plans exist
3. Start learning

**Institution (classroom)**

1. Student → **Classroom sessions** → launch enrolled instance

**Expected:** Session uses manifest slice (not full stale key_concepts). No silent fallback error for v2 published topics.

---

## 6. Verify RAG

1. During session, ask a question tied to current concept content
2. Confirm answer uses notes for the **active concept string** (runtime unchanged)

**Expected:** RAG behavior unchanged; content from structured notes linked by `canonical_runtime_key`.

---

## 7. Verify Zone 1

1. Progress through Zone 1 teaching beats
2. Confirm whiteboard / timeline / VTSE paths unchanged
3. Confirm concept progression follows session manifest order

**Expected:** Zone 1 runtime unchanged from pre–UI-finalization behavior.

---

## Checklist summary

| Step | Area | Pass |
|------|------|------|
| 1 | Admin structured curriculum + publish | ☐ |
| 2 | Admin session plans (catalog) | ☐ |
| 3 | Teacher v2 topic + import/build | ☐ |
| 4 | Teacher classroom plans | ☐ |
| 5 | Student launch (catalog + classroom) | ☐ |
| 6 | RAG | ☐ |
| 7 | Zone 1 runtime | ☐ |

---

## UI regression (v2)

| Surface | v2 topic | v1 topic |
|---------|----------|----------|
| Teacher workspace | No Concepts/Notes/Questions tabs | Legacy tabs visible |
| Teacher `/teacher/topic` | Redirect/banner to structured builder | Legacy concepts editable |
| Admin curriculum panel | No legacy authoring tabs | Legacy tabs visible |
| Admin topic modal | No key concepts editor when v2 | Key concepts on create/edit v1 |

Backend legacy APIs and models remain available; only UI is hidden.
