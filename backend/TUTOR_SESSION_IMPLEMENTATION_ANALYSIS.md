# AI Tutor — Deep implementation analysis (session flow, intent, RAG, orchestrator)

This document answers the nine-part audit with **full function source** (as of the repo), step-by-step behavior, and a **Problems found** section. File references: `app/services/session_service.py`, `app/services/rag_service.py`, `app/services/orchestrator_service.py`, `app/models/learning/sessions.py`, `app/core/dependencies.py`.

---

# PART 1 — Session flow (full implementation)

## 1.1 `SessionService.answer_tutor_question` — full code

```python
    async def answer_tutor_question(
        self,
        session_id: PydanticObjectId,
        student_id: PydanticObjectId,
        question: str,
    ) -> str | dict:
        """
        Answer a student question using RAG. Topic is resolved from the question
        when possible, otherwise the session's topic is used.
        """
        session = await self.session_repository.get_by_id(session_id)
        if session is None:
            raise ValueError("Session not found")
        if session.student_id != student_id:
            raise ValueError("Session does not belong to this student")
        if session.completion_status != "in_progress":
            raise ValueError("Session is not in progress")

        question = question.strip()
        if not question:
            raise ValueError("Question cannot be empty")
        is_question = "?" in question
        learning_state = getattr(session, "learning_state", "explaining")

        if getattr(session, "current_mode", "normal") == "quiz":
            user_answer = question.strip()
            if not session.current_question:
                session.current_mode = "normal"
                session.current_question = None
                await session.save()
                return {
                    "type": "feedback",
                    "message": "I could not find the pending quiz question. Let's continue.",
                    "correct": False,
                }
            result = await self.evaluate_student_answer(
                session_id=session.id,
                student_id=student_id,
                question=session.current_question,
                student_answer=user_answer,
            )
            session.current_mode = "normal"
            session.current_question = None
            session.learning_state = "checking_understanding"
            await session.save()
            mastery = await MasteryRepository().get_one(
                mastery_record_filter(
                    session.organization_id,
                    student_id,
                    session.topic_id,
                    normalize_concept(getattr(session, "current_concept", None)),
                )
            )
            mastery_score = float(mastery.mastery_score) if mastery is not None else 50.0
            decision = await OrchestratorService().decide_next_action(
                mastery_score=mastery_score,
                last_answer_correct=bool(result.get("correct")),
                has_recent_mistakes=not bool(result.get("correct")),
            )
            if decision["action"] == "QUIZ":
                suggestion_text = "Would you like to try another question?"
            elif decision["action"] == "EXPLAIN":
                suggestion_text = "Would you like me to explain this further?"
            else:
                suggestion_text = "What would you like to do next?"
            return {
                "type": "feedback",
                "message": f"{result['feedback']} {suggestion_text}".strip(),
                "correct": result["correct"],
                "suggestion": decision["action"],
                "suggested_difficulty": decision["difficulty"],
            }

        user_input = question.strip().lower()
        is_followup = any(
            word in user_input
            for word in [
                "this",
                "that",
                "it",
                "explain this",
                "explain that",
                "more detail",
            ]
        )
        if user_input in ["yes", "i understand", "ok", "got it"] and learning_state != "reviewing":
            quiz = await self.generate_quiz_question(
                session_id=session.id,
                student_id=student_id,
            )
            session.current_mode = "quiz"
            session.current_question = quiz["question"]
            session.learning_state = "quizzing"
            await session.save()
            return {
                "type": "quiz",
                "message": "Great! Let me check your understanding:",
                "question": quiz["question"],
            }
        wants_quiz = any(
            word in user_input
            for word in ["yes", "quiz", "question", "another", "test"]
        )
        wants_explanation = any(
            word in user_input
            for word in ["explain", "detail", "again", "don't understand"]
        )

        if wants_quiz and learning_state != "reviewing":
            quiz = await self.generate_quiz_question(
                session_id=session.id,
                student_id=student_id,
            )
            session.current_mode = "quiz"
            session.current_question = quiz["question"]
            session.learning_state = "quizzing"
            await session.save()
            return {
                "type": "quiz",
                "message": "Great! Here's another question:",
                "question": quiz["question"],
            }

        if wants_explanation:
            pass

        event_repository = EventRepository()
        await event_repository.create(
            {
                "organization_id": session.organization_id,
                "session_id": session_id,
                "student_id": student_id,
                "event_type": SessionEventType.QUESTION,
                "content": question[:4000] if len(question) > 4000 else question,
                "timestamp": datetime.utcnow(),
            }
        )

        topic_note_repository = TopicNoteRepository()
        video_subtitle_repository = VideoSubtitleRepository()
        topic_question_repository = TopicQuestionRepository()
        rag_service = RAGService(
            topic_note_repository,
            video_subtitle_repository,
            topic_question_repository,
            self.topic_repository,
        )

        student_profile = await StudentProfile.find_one(
            {"organization_id": session.organization_id, "user_id": session.student_id}
        )
        teaching_style = (
            student_profile.preferred_teaching_style
            if student_profile is not None
            else None
        )
        interests = student_profile.interests if student_profile is not None else []
        interest_category = interests[0] if interests else "general"
        difficulty_level = (
            student_profile.preferred_depth if student_profile is not None else None
        )

        if (
            is_followup
            and getattr(session, "last_answer", None)
            and learning_state in ["reviewing", "checking_understanding"]
        ):
            expanded_prompt = f"""
Explain the following question and its answer in more detail, step by step:

Question:
{session.last_question}

Answer:
{session.last_answer}

Explain clearly, step-by-step, as if teaching a beginner.
"""
            followup_answer = await rag_service.generate_prompt(
                question=expanded_prompt,
                context="",
                student_profile=student_profile.model_dump() if student_profile else None,
                topic_name=None,
            )
            session.last_question = question
            session.last_answer = followup_answer
            session.learning_state = "reviewing"
            await session.save()
            out_message = followup_answer
            if wants_explanation:
                out_message = (
                    self._random_explanation_ack() + "\n\n" + out_message
                )
            return {
                "type": "explanation",
                "message": out_message,
            }

        topic_id = session.topic_id
        detected_topic_id = await rag_service.detect_topic_from_query(
            question,
            session.organization_id,
        )
        if detected_topic_id:
            topic_id = detected_topic_id

        notes = await rag_service.get_topic_notes(
            topic_id=topic_id,
            organization_id=session.organization_id,
            teaching_style=teaching_style,
            interest_category=interest_category,
            difficulty_level=difficulty_level,
        )
        context = await rag_service.build_context(
            notes,
            topic_id=topic_id,
            organization_id=session.organization_id,
        )
        if not context or len(context.strip()) < 50:
            return {
                "answer": "I don't have enough information on this topic yet.",
            }

        topic_for_prompt = await self.topic_repository.get_by_id(topic_id)
        start_time = time.time()
        answer = await rag_service.generate_prompt(
            question=question,
            context=context,
            student_profile=student_profile.model_dump() if student_profile else None,
            topic_name=topic_for_prompt.topic_name if topic_for_prompt else None,
        )
        session.last_question = question
        session.last_answer = answer
        await session.save()
        orchestrator = OrchestratorService()
        mastery_repository = MasteryRepository()
        mastery = await mastery_repository.get_one(
            mastery_record_filter(
                session.organization_id,
                student_id,
                topic_id,
                normalize_concept(getattr(session, "current_concept", None)),
            )
        )
        mastery_score = mastery.mastery_score if mastery else 50
        events = await EventRepository().get_many(
            filters={
                "session_id": session.id,
            },
            limit=50,
        )
        interaction_count = len(
            [e for e in events if e.event_type == SessionEventType.QUESTION]
        )
        last_answer_correct = None
        for e in reversed(events):
            if e.event_type == SessionEventType.ANSWER:
                last_answer_correct = getattr(e, "is_correct", None)
                break
        has_recent_mistakes = any(
            getattr(e, "is_correct", False) is False
            for e in events
            if e.event_type == SessionEventType.ANSWER
        )
        decision = await orchestrator.decide_next_action(
            mastery_score=mastery_score,
            last_answer_correct=last_answer_correct,
            has_recent_mistakes=has_recent_mistakes,
        )
        if is_question:
            decision["action"] = "EXPLAIN"
        if decision["action"] == "QUIZ":
            if interaction_count < 2 or last_answer_correct is None:
                decision["action"] = "EXPLAIN"
        if learning_state == "reviewing" and decision["action"] == "QUIZ":
            decision["action"] = "EXPLAIN"
        print(f"[Orchestrator Decision]: {decision}")
        response_time_ms = int((time.time() - start_time) * 1000)

        await AIGenerationLog(
            organization_id=session.organization_id,
            student_id=student_id,
            topic_id=topic_id,
            session_id=session_id,
            model_used="deepseek-chat",
            task_type="qa",
            tokens_used=0,
            estimated_cost=0,
            response_time_ms=response_time_ms,
        ).insert()

        await event_repository.create(
            {
                "organization_id": session.organization_id,
                "session_id": session_id,
                "student_id": student_id,
                "event_type": SessionEventType.ANSWER,
                "content": (answer[:4000] if len(answer) > 4000 else answer),
                "timestamp": datetime.utcnow(),
            }
        )
        if decision["action"] == "QUIZ":
            quiz = await self.generate_quiz_question(
                session_id=session.id,
                student_id=student_id,
            )
            session.current_mode = "quiz"
            session.current_question = str(quiz["question"])
            session.learning_state = "quizzing"
            await session.save()
            return {
                "type": "quiz",
                "message": "Nice, I think you're getting it. Let me ask you something:",
                "question": quiz["question"],
                "difficulty": decision["difficulty"],
            }

        session.learning_state = "checking_understanding"
        await session.save()
        closing = (
            "\n\nDoes that make sense, or would you like to try a quick question?"
        )
        out_message = answer + closing
        if wants_explanation:
            out_message = self._random_explanation_ack() + "\n\n" + out_message
        return {
            "type": "explanation",
            "message": out_message,
        }
```

**Source:** `app/services/session_service.py` lines **865–1193**.

### Step-by-step: `answer_tutor_question`

| Step | What happens |
|------|----------------|
| Validation | Load session; reject wrong student or non–`in_progress`. Strip `question`; empty → `ValueError`. |
| **User input processing** | Original `question` kept for events/RAG; `user_input = question.strip().lower()` used only for keyword intent. `is_question = ("?" in question)` uses **original** string (case-sensitive `?` only). |
| **Intent (early)** | If `current_mode == "quiz"`: treat entire message as **quiz answer**, not intent detection. |
| **Quiz branch** | Calls `evaluate_student_answer` with `session.current_question`. Then sets `current_mode="normal"`, clears `current_question`, `learning_state="checking_understanding"`. **Orchestrator** called with mastery from **`session.topic_id`** and **`current_concept`**. Returns feedback + suggestion strings (no second quiz in same turn). |
| **Intent (affirmation)** | Exact list match: `user_input in ["yes", "i understand", "ok", "got it"]` and `learning_state != "reviewing"` → `generate_quiz_question`, set quiz mode/state, return. |
| **Intent (quiz keywords)** | Substring scan: `wants_quiz` if any of `yes`, `quiz`, `question`, `another`, `test` appears **anywhere** in `user_input`; blocked if `learning_state == "reviewing"`. |
| **Intent (explain)** | `wants_explanation` from substrings `explain`, `detail`, `again`, `don't understand`; **`if wants_explanation: pass` only** — no branch exit. |
| **QUESTION event** | Always logged before RAG path (except early returns). |
| **Follow-up branch** | If `is_followup` AND `last_answer` AND `learning_state in ["reviewing","checking_understanding"]`: **RAG** with empty context, expanded prompt from `last_question`/`last_answer`; sets `learning_state="reviewing"`; optional ack if `wants_explanation`. **No orchestrator.** |
| **Main RAG** | `detect_topic_from_query` may switch `topic_id`; `get_topic_notes` + `build_context`; if context &lt; 50 chars → early return string (no state save beyond what’s inside branch). **RAG** `generate_prompt` with student question. Updates `last_question`/`last_answer`. |
| **Orchestrator (main path)** | Loads mastery for **`topic_id` (may be detected)** and **`current_concept`**. Builds `last_answer_correct` / `has_recent_mistakes` from last 50 events (see Part 8 — often wrong). Calls `decide_next_action`, then **overrides** decision (`is_question` → EXPLAIN; QUIZ throttled; reviewing → no QUIZ). |
| **Logging** | `AIGenerationLog`; **ANSWER** event with tutor text (**`is_correct` not set**). |
| **QUIZ attach** | If final `decision["action"] == "QUIZ"`: `generate_quiz_question`, set `current_mode="quiz"`, `learning_state="quizzing"`, return combined message + new question. |
| **Else** | `learning_state="checking_understanding"`; append hard-coded closing question to answer; optional ack if `wants_explanation`. |

### Where `learning_state` is updated in this function

- After quiz answer path: → `"checking_understanding"`.
- Affirmation / keyword quiz: → `"quizzing"`.
- Follow-up RAG: → `"reviewing"`.
- Orchestrator QUIZ attach: → `"quizzing"`.
- Default explanation path: → `"checking_understanding"`.

### Where `current_mode` is updated

- Quiz answer path: `"normal"` (+ clear `current_question`).
- Missing `current_question` in quiz mode: `"normal"`.
- Enter quiz: `"quiz"` (affirmation, `wants_quiz`, or orchestrator QUIZ).

### Where `current_concept` is used

- Mastery lookup after quiz: `mastery_record_filter(..., normalize_concept(session.current_concept))`.
- Same in main-path mastery before orchestrator.
- **Not set anywhere in this function** (see Part 3 / Problems).

### Where orchestrator is called

1. After **`evaluate_student_answer`** in quiz mode (with `result["correct"]`-derived flags).
2. After main RAG answer, before attaching a quiz.

### Where RAG is called

1. Follow-up branch: `generate_prompt` with constructed `expanded_prompt`, `context=""`.
2. Main path: `detect_topic_from_query`, `get_topic_notes`, `build_context`, `generate_prompt`.

---

## 1.2 `SessionService.generate_quiz_question` — full code

```python
    async def generate_quiz_question(
        self,
        session_id: PydanticObjectId,
        student_id: PydanticObjectId,
        concept: str | None = None,
    ) -> dict:
        """
        Return a quiz question from the topic question bank when available,
        otherwise generate one via the AI tutor using RAG context.
        """
        session = await self.session_repository.get_by_id(session_id)
        if session is None:
            raise ValueError("Session not found")
        if session.student_id != student_id:
            raise ValueError("Session does not belong to this student")
        if session.completion_status != "in_progress":
            raise ValueError("Session is not in progress")

        session_concept = getattr(session, "current_concept", None)
        locked_concept = concept or session_concept
        strict_concept = bool(locked_concept)

        mastery_concept = (
            normalize_concept(locked_concept) if strict_concept else None
        )
        mastery = await MasteryRecord.find_one(
            mastery_record_filter(
                session.organization_id,
                student_id,
                session.topic_id,
                mastery_concept,
            )
        )
        mastery_score = mastery.mastery_score if mastery is not None else 50.0
        if mastery is not None and mastery.confidence_score < 0.3:
            difficulty = "easy"
        elif mastery_score < 35:
            difficulty = "easy"
        elif mastery_score < 75:
            difficulty = "medium"
        else:
            difficulty = "hard"

        if difficulty == "easy":
            difficulty_level_filter: int | dict = {"$in": [1, 2]}
        elif difficulty == "medium":
            difficulty_level_filter = 3
        else:
            difficulty_level_filter = {"$in": [4, 5]}

        event_repository = EventRepository()
        topic_question_repository = TopicQuestionRepository()
        base_filters = {
            "topic_id": session.topic_id,
            "organization_id": session.organization_id,
            "approved": True,
        }
        filters_with_diff = {
            **base_filters,
            "difficulty_level": difficulty_level_filter,
        }
        questions = await topic_question_repository.get_many(
            filters=filters_with_diff,
            limit=5,
        )
        if strict_concept:
            concept_lower = str(locked_concept).lower().strip()
            questions = [
                q
                for q in questions
                if concept_lower in (q.question_text or "").lower()
            ]

        if not questions and not strict_concept:
            questions = await topic_question_repository.get_many(
                filters=base_filters,
                limit=5,
            )

        asked_events = await event_repository.get_many(
            filters={
                "session_id": session_id,
                "event_type": SessionEventType.QUESTION,
            },
            limit=500,
        )
        asked_texts = {
            e.content.strip().lower()
            for e in asked_events
            if e.content
        }
        questions = [
            q
            for q in questions
            if q.question_text.strip().lower() not in asked_texts
        ]

        if questions:
            selected = random.choice(questions)
            await event_repository.create(
                {
                    "organization_id": session.organization_id,
                    "session_id": session_id,
                    "student_id": student_id,
                    "event_type": SessionEventType.QUESTION,
                    "content": selected.question_text[:4000],
                    "timestamp": datetime.utcnow(),
                }
            )
            return {
                "question": selected.question_text.strip(),
                "type": getattr(selected, "question_type", None) or "short_answer",
            }

        topic_note_repository = TopicNoteRepository()
        video_subtitle_repository = VideoSubtitleRepository()
        rag_service = RAGService(
            topic_note_repository,
            video_subtitle_repository,
            topic_question_repository,
            self.topic_repository,
        )

        student_profile = await StudentProfile.find_one(
            {"organization_id": session.organization_id, "user_id": session.student_id}
        )
        teaching_style = (
            student_profile.preferred_teaching_style
            if student_profile is not None
            else None
        )
        interests = student_profile.interests if student_profile is not None else []
        interest_category = interests[0] if interests else "general"
        difficulty_level = (
            student_profile.preferred_depth if student_profile is not None else None
        )

        notes = await rag_service.get_topic_notes(
            topic_id=session.topic_id,
            organization_id=session.organization_id,
            teaching_style=teaching_style,
            interest_category=interest_category,
            difficulty_level=difficulty_level,
        )
        context = await rag_service.build_context(
            notes,
            topic_id=session.topic_id,
            organization_id=session.organization_id,
        )

        if strict_concept:
            question_prompt = (
                f"Generate one short conceptual question specifically about {locked_concept}. "
                f"Keep difficulty at {difficulty} level. "
                f"Generate a question ONLY about {locked_concept}. "
                "Do NOT include other concepts like addition, comparison, or mixed problems. "
                "Do NOT switch topic. "
                "Do NOT include explanation."
            )
        else:
            question_prompt = (
                f"Generate one {difficulty} level conceptual question for this topic. "
                "Do NOT include explanation."
            )
        topic_for_quiz = await self.topic_repository.get_by_id(session.topic_id)
        ai_output = await rag_service.generate_prompt(
            question=question_prompt,
            context=context,
            student_profile=student_profile.model_dump() if student_profile else None,
            topic_name=topic_for_quiz.topic_name if topic_for_quiz else None,
        )
        ai_output = ai_output.strip()
        if ":" in ai_output:
            ai_output = ai_output.split(":", 1)[-1].strip()

        await event_repository.create(
            {
                "organization_id": session.organization_id,
                "session_id": session_id,
                "student_id": student_id,
                "event_type": SessionEventType.QUESTION,
                "content": ai_output[:4000],
                "timestamp": datetime.utcnow(),
            }
        )

        return {
            "question": ai_output,
            "type": "short_answer",
        }
```

**Source:** `app/services/session_service.py` lines **1195–1384**.

### Step-by-step: `generate_quiz_question`

| Concern | Behavior |
|---------|----------|
| **User input** | No user message; optional `concept` parameter + `session.current_concept`. |
| **Intent** | N/A. |
| **`learning_state` / `current_mode`** | **Not modified here** — callers set quiz mode. |
| **`current_concept`** | Used only if `concept` argument is `None`: `locked_concept = session.current_concept`. |
| **Orchestrator** | Not called. |
| **RAG** | If bank exhausted: `get_topic_notes`, `build_context`, `generate_prompt` with `question_prompt` only (not user chat). |
| **Difficulty** | From `MasteryRecord`: if `confidence_score < 0.3` → easy; else thresholds on `mastery_score` 35 / 75. **Note:** `confidence_score` is 0–100 in model; compared to `0.3` (almost always false unless score near zero). |
| **Duplicates** | Compare bank `question_text` to **QUESTION** event `content` (lowercase), last 500 QUESTION events. |
| **Concept filter** | If `strict_concept`: filter bank where concept substring in `question_text`. If none, falls through to AI or empty bank path. |

---

## 1.3 `SessionService.evaluate_student_answer` — full code

```python
    async def evaluate_student_answer(
        self,
        session_id: PydanticObjectId,
        student_id: PydanticObjectId,
        question: str,
        student_answer: str,
    ) -> dict:
        session = await self.session_repository.get_by_id(session_id)
        if session is None:
            raise ValueError("Session not found")
        if session.student_id != student_id:
            raise ValueError("Session does not belong to this student")
        if session.completion_status != "in_progress":
            raise ValueError("Session is not in progress")

        student_answer_stored = student_answer.strip()
        if not student_answer_stored:
            raise ValueError("Answer cannot be empty")

        event_repository = EventRepository()
        await event_repository.create(
            {
                "organization_id": session.organization_id,
                "session_id": session_id,
                "student_id": student_id,
                "event_type": SessionEventType.ANSWER,
                "content": student_answer_stored[:4000],
                "timestamp": datetime.utcnow(),
            }
        )

        student_answer_clean = student_answer.strip().lower()

        is_correct = False

        if len(student_answer_clean) <= 10:
            if student_answer_clean in question.lower():
                is_correct = True

        topic_note_repository = TopicNoteRepository()
        video_subtitle_repository = VideoSubtitleRepository()
        topic_question_repository = TopicQuestionRepository()
        rag_service = RAGService(
            topic_note_repository,
            video_subtitle_repository,
            topic_question_repository,
            self.topic_repository,
        )

        student_profile = await StudentProfile.find_one(
            {"organization_id": session.organization_id, "user_id": session.student_id}
        )

        topic = await self.topic_repository.get_by_id(session.topic_id)
        context = f"Topic: {topic.topic_name}" if topic else ""

        evaluation_prompt = f"""
You are an AI tutor.

Question:
{question}

Student Answer:
{student_answer_stored}

Evaluate:

1. Is the answer correct? (yes/no)
2. Give short feedback (1-2 lines)

Respond in JSON:
{{"correct": true/false, "feedback": "..."}}
"""

        ai_response = await rag_service.generate_prompt(
            question=evaluation_prompt,
            context=context,
            student_profile=student_profile.model_dump() if student_profile else None,
            topic_name=topic.topic_name if topic else None,
        )

        correct = is_correct
        feedback = "Good attempt, keep improving."
        t = ai_response.strip()
        if t.startswith("```"):
            rest = t.split("\n", 1)[-1] if "\n" in t else t[3:]
            t = rest.rsplit("```", 1)[0].strip()
        try:
            data = json.loads(t)
            correct = bool(data.get("correct", is_correct))
            fb = data.get("feedback")
            if fb is not None and str(fb).strip():
                feedback = str(fb).strip()
        except (json.JSONDecodeError, TypeError, ValueError):
            m = re.search(r"\{[\s\S]*\}", ai_response)
            if m:
                try:
                    data = json.loads(m.group(0))
                    correct = bool(data.get("correct", is_correct))
                    fb = data.get("feedback")
                    if fb is not None and str(fb).strip():
                        feedback = str(fb).strip()
                except (json.JSONDecodeError, TypeError, ValueError):
                    pass

        evaluation_score = 100.0 if correct else 0.0

        await TeachbackEvaluation(
            organization_id=session.organization_id,
            student_id=student_id,
            session_id=session_id,
            topic_id=session.topic_id,
            question_text=question.strip(),
            student_response=student_answer_stored,
            is_correct=correct,
            evaluation_score=evaluation_score,
            feedback=feedback,
            model_used="deepseek-chat",
            timestamp=datetime.utcnow(),
        ).insert()

        mastery_service = self.mastery_service
        if mastery_service is None:
            return {
                "correct": correct,
                "feedback": feedback,
            }
        try:
            mastery_record = await mastery_service.update_mastery(
                student_id=student_id,
                topic_id=session.topic_id,
                concept=normalize_concept(getattr(session, "current_concept", None)),
                is_correct=correct,
                organization_id=session.organization_id,
            )
        except Exception:
            mastery_record = None

        if correct:
            performance = "good"
        else:
            performance = "struggling"

        score = mastery_record.mastery_score if mastery_record else None
        await event_repository.create(
            {
                "organization_id": session.organization_id,
                "session_id": session_id,
                "student_id": student_id,
                "event_type": SessionEventType.PERFORMANCE,
                "content": json.dumps(
                    {
                        "performance": performance,
                        "score": score,
                    }
                )[:4000],
                "timestamp": datetime.utcnow(),
            }
        )

        return {
            "correct": correct,
            "feedback": feedback,
        }
```

**Source:** `app/services/session_service.py` lines **1386–1549**.

### Step-by-step: `evaluate_student_answer`

| Concern | Behavior |
|---------|----------|
| **User input** | `student_answer` stripped; empty → `ValueError`. |
| **Intent** | None. |
| **`learning_state` / `current_mode`** | Not updated here. |
| **`current_concept`** | Passed to `update_mastery(..., concept=normalize_concept(session.current_concept))`. |
| **Orchestrator** | Not called here. |
| **RAG** | `generate_prompt` with `evaluation_prompt` and minimal `context` (topic name only). |
| **Events** | **ANSWER** (no `is_correct`); **PERFORMANCE** with JSON in `content`. |

---

# PART 2 — Intent detection (all places)

## 2.1 Inside `answer_tutor_question`

**Mode gate (not keyword intent):**

```python
if getattr(session, "current_mode", "normal") == "quiz":
    # entire message treated as answer
```

**Affirmation (exact string match on full lowercased message):**

```python
user_input = question.strip().lower()
# ...
if user_input in ["yes", "i understand", "ok", "got it"] and learning_state != "reviewing":
```

**Quiz intent (substring anywhere in `user_input`):**

```python
wants_quiz = any(
    word in user_input
    for word in ["yes", "quiz", "question", "another", "test"]
)
# ...
if wants_quiz and learning_state != "reviewing":
```

**Explanation intent (substring):**

```python
wants_explanation = any(
    word in user_input
    for word in ["explain", "detail", "again", "don't understand"]
)
if wants_explanation:
    pass
```

**Follow-up intent (substring — false positives likely):**

```python
is_followup = any(
    word in user_input
    for word in [
        "this",
        "that",
        "it",
        "explain this",
        "explain that",
        "more detail",
    ]
)
```

**Punctuation “intent”:**

```python
is_question = "?" in question
# used later to force orchestrator to EXPLAIN
```

## 2.2 No other modules implement chat intent

`RAGService.detect_topic_from_query` is **topic routing**, not dialog intent: it matches `topic_name` or `key_concepts` substrings in the user text.

## 2.3 Trace: user says **"no explain me numerator"**

Assume `current_mode != "quiz"`, typical `learning_state` e.g. `checking_understanding`.

1. `user_input = "no explain me numerator"`.
2. **Affirmation list:** not matched (whole string must equal one of four literals).
3. **`wants_quiz`:** tests substrings `yes`, `quiz`, `question`, `another`, `test` inside the sentence → **false** (unless e.g. "test" appears).
4. **`wants_explanation`:** substring **`explain`** matches inside “expl**ain** …” → **true**.
5. `if wants_explanation: pass` → **no behavioral branch**; execution continues.
6. **`is_followup`:** e.g. `"it"` in string? **"numerator"** does not contain `"it"`; **`"this"`** no; **`"that"`** no; **`"explain this"`** no; **`"more detail"`** no — generally **false** unless a trigger substring appears (e.g. **`"it"`** matches inside many English words — see Problems).
7. A **QUESTION** event is recorded with full original text.
8. **Main RAG path** runs: user message including **"no"** is sent as the **Question:** line to DeepSeek via `generate_prompt` — there is **no special handling for negation** (“no”).
9. **`wants_explanation`** only affects the **final** explanation path by prepending `self._random_explanation_ack()` before the answer + closing — it does **not** skip RAG or force a pure “explain numerator” mode.

So: **"no" is ignored** as intent; **"explain"** only weakly biases formatting (ack) and does not change routing. The model may still answer about numerators, mixing frustration and explanation depending on the LLM.

---

# PART 3 — `learning_state` system

## 3.1 Model default

From `app/models/learning/sessions.py`:

```python
learning_state: str = Field(default="explaining")
```

**No enum constraint** — any string can be stored if set elsewhere.

## 3.2 All values **read** in `answer_tutor_question`

| Value | Where used |
|-------|------------|
| `explaining` | Default from `getattr(session, "learning_state", "explaining")` only when missing; not heavily branched. |
| `reviewing` | Blocks affirmation quiz and `wants_quiz` auto-quiz; allows follow-up branch when combined with `is_followup` and `last_answer`; orchestrator QUIZ overridden to EXPLAIN when `learning_state == "reviewing"`. |
| `checking_understanding` | With `last_answer` and `is_followup`, enters follow-up deep explanation; used in `learning_state in ["reviewing", "checking_understanding"]`. |
| `quizzing` | Set when entering quiz mode from this function; not read for branching inside the same function beyond what’s saved. |

## 3.3 Every **write** in `session_service.py` (from grep)

| Location | New value |
|----------|-----------|
| After quiz answer handling | `checking_understanding` |
| Affirmation → quiz | `quizzing` |
| `wants_quiz` → quiz | `quizzing` |
| Follow-up RAG success | `reviewing` |
| Orchestrator attaches quiz | `quizzing` |
| Explanation path (no attached quiz) | `checking_understanding` |

## 3.4 Not updated in

- `generate_quiz_question`
- `evaluate_student_answer`
- `start_session` (inherits default `"explaining"` from model)

## 3.5 Exact transition table (within `answer_tutor_question`)

| From (typical) | Condition | To |
|----------------|-----------|-----|
| any | Quiz mode answer completed | `checking_understanding` |
| ≠ `reviewing` | exact “yes” / “ok” / … | `quizzing` |
| ≠ `reviewing` | `wants_quiz` | `quizzing` |
| `reviewing` or `checking_understanding` | follow-up + `last_answer` + `is_followup` | `reviewing` |
| any | orchestrator QUIZ attach after main answer | `quizzing` |
| any | main answer, no QUIZ attach | `checking_understanding` |

---

# PART 4 — `current_mode` (“quiz” vs “normal”)

## 4.1 Sets to **`"quiz"`**

All in `answer_tutor_question`:

- After `generate_quiz_question` (affirmation path).
- After `generate_quiz_question` (`wants_quiz` path).
- After `generate_quiz_question` (orchestrator QUIZ decision path).

`generate_quiz_question` **does not** set mode.

## 4.2 Sets to **`"normal"`**

- Quiz branch when `current_question` missing (recovery).
- Quiz branch after successful `evaluate_student_answer` (before returning feedback).

Default on new session: `current_mode: str = Field(default="normal")` in `Session` model.

## 4.3 Triggers for quiz mode

1. User in **quiz mode** — next message graded as answer.
2. **Exact** short affirmation (not in `reviewing`).
3. **`wants_quiz`** substring match (not in `reviewing`).
4. Main tutor turn: orchestrator returns **QUIZ** after overrides, then second question generated.

## 4.4 Exiting quiz mode

- Submitting an answer through **`answer_tutor_question`** while in quiz mode (calls `evaluate_student_answer`, then sets `normal` and clears `current_question`).
- Or invalid state: `current_question` empty → reset to `normal`.

**Note:** Calling **`POST /sessions/evaluate-answer`** directly does **not** clear `current_mode` / `current_question` — can desync UI if client uses both paths.

---

# PART 5 — Orchestrator usage

## 5.1 Implementation

```python
class OrchestratorService:
    async def decide_next_action(
        self,
        mastery_score: float,
        last_answer_correct: bool | None = None,
        has_recent_mistakes: bool = False,
    ) -> dict:
        if mastery_score < 40:
            result = {
                "action": "EXPLAIN",
                "difficulty": "easy",
            }
        elif mastery_score < 70:
            if last_answer_correct is False:
                result = {
                    "action": "REVISE",
                    "difficulty": "easy",
                }
            else:
                result = {
                    "action": "QUIZ",
                    "difficulty": "medium",
                }
        else:
            result = {
                "action": "QUIZ",
                "difficulty": "hard",
            }

        action = result["action"]
        print(f"[Orchestrator] mastery={mastery_score}, action={action}")
        return result
```

**`has_recent_mistakes` is never read** — dead parameter.

## 5.2 Call site A — after quiz answer (`answer_tutor_question`)

```python
decision = await OrchestratorService().decide_next_action(
    mastery_score=mastery_score,
    last_answer_correct=bool(result.get("correct")),
    has_recent_mistakes=not bool(result.get("correct")),
)
```

## 5.3 Call site B — after main RAG explanation

```python
decision = await orchestrator.decide_next_action(
    mastery_score=mastery_score,
    last_answer_correct=last_answer_correct,
    has_recent_mistakes=has_recent_mistakes,
)
```

where `last_answer_correct` / `has_recent_mistakes` come from **SessionEvent** scan (ANSWER events).

## 5.4 Overrides after call (session logic, not orchestrator)

```python
if is_question:
    decision["action"] = "EXPLAIN"
if decision["action"] == "QUIZ":
    if interaction_count < 2 or last_answer_correct is None:
        decision["action"] = "EXPLAIN"
if learning_state == "reviewing" and decision["action"] == "QUIZ":
    decision["action"] = "EXPLAIN"
```

So: **yes, orchestrator is frequently overridden.**  
**REVISE** is never given distinct product behavior after main path — only quiz vs non-quiz matters for attaching a question.

---

# PART 6 — RAG + prompt (`RAGService.generate_prompt`)

## 6.1 Full function

```python
    async def generate_prompt(
        self,
        question: str,
        context: str,
        student_profile: dict | None = None,
        topic_name: str | None = None,
    ) -> str:
        style_instruction = ""
        interest_instruction = ""

        if student_profile:
            if "preferred_teaching_style" in student_profile and student_profile["preferred_teaching_style"]:
                style_instruction = (
                    f"Teach in a {student_profile['preferred_teaching_style']} style."
                )

            if "interests" in student_profile and student_profile["interests"]:
                interests = ", ".join(student_profile["interests"])
                interest_instruction = (
                    f"Use examples related to: {interests} when possible."
                )

        topic_line = (
            f"Topic: {topic_name}" if topic_name else "Topic: (not specified)"
        )
        prompt = f"""
You are an AI tutor.

{topic_line}

Use the following context as primary material for the topic above.

Context:
{context}

Question:
{question}

Student Preferences:
{style_instruction}
{interest_instruction}

Instructions:

* Explain clearly and simply
* Use examples if helpful
* If the question is directly related to the topic, you may use your general knowledge in addition to the context.

If the question is unrelated to the topic, politely refuse and guide the student back to the topic.

* Do not answer questions outside the topic.

* Adapt explanation based on student preferences
  """
        api_key = os.getenv("DEEPSEEK_API_KEY")
        if not api_key:
            raise ValueError("DEEPSEEK_API_KEY not set")

        url = "https://api.deepseek.com/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": "deepseek-chat",
            "messages": [
                {"role": "system", "content": "You are an AI tutor."},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.7,
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                response = await client.post(url, headers=headers, json=payload)
            except Exception:
                return "Sorry, the AI service is currently unavailable. Please try again."

        if response.status_code != 200:
            return "AI service error. Please try again later."

        try:
            data = response.json()
            return data["choices"][0]["message"]["content"]
        except Exception:
            return "AI response parsing failed. Please try again."
```

## 6.2 Does the prompt include…

| Signal | In `generate_prompt`? |
|--------|------------------------|
| **`learning_state`** | **No** |
| **Explicit student intent** (yes/no/quiz/explain flags) | **No** — only raw `question` text |
| **`last_answer`** | **No**, except indirectly: follow-up branch sets `question=expanded_prompt` which **embeds** `last_question` and `last_answer` inside the string |
| **Mistake / performance context** | **No** in main RAG; evaluation prompt is separate in `evaluate_student_answer` |

So the model is **not** told “student is in checking_understanding” or “student just refused a quiz”; only text + topic + context + preferences.

---

# PART 7 — Question generation logic

| Topic | Implementation detail |
|-------|-------------------------|
| **Bank vs AI** | Load up to 5 bank rows with difficulty filter; concept filter optionally; remove any whose text matches prior **QUESTION** event bodies (case-insensitive exact string); if any left, `random.choice`, log QUESTION event, return. Else RAG. |
| **Duplicates** | Exact match of full `question_text` to past QUESTION `content` only. AI-generated questions are **not** checked against semantic duplicates; only exact repeat if model outputs identical string. |
| **Difficulty** | Derived from mastery + broken confidence check (`< 0.3` vs 0–100 field). Maps to bank difficulty bands `{1,2}`, `3`, `{4,5}`. |
| **Concept** | `concept` arg or `session.current_concept`; if set, substring filter on bank questions; AI prompt names the concept explicitly. **No API in routes sets `current_concept` in this codebase** — field stays `None` unless set elsewhere. |

---

# PART 8 — Known issues (from code)

1. **Negation and compound intent ignored:** “no explain …” still hits `explain` substring for ack only; “no” never used.
2. **Substring intent false positives:** `yes` in `yesterday`; `it` in many words for `is_followup`; `question` in ordinary speech triggers quiz.
3. **`wants_explanation` is a no-op** before RAG (`pass`) — does not force explanation-only routing.
4. **Orchestrator inputs broken for event-based path:** `evaluate_student_answer` creates ANSWER events **without** `is_correct`; correctness is only in TeachbackEvaluation and PERFORMANCE JSON. Loop that sets `last_answer_correct` reads ANSWER events → usually **`None`**. `has_recent_mistakes` uses `getattr(e, "is_correct", False) is False` — **None** fails that test, so mistakes often **undetected**.
5. **`has_recent_mistakes` unused** inside `OrchestratorService` — planning ignores mistake signal entirely.
6. **Topic switch during session:** `detect_topic_from_query` can change `topic_id` for RAG and mastery lookup vs `session.topic_id` mismatch — quiz generation still uses **`session.topic_id`** always.
7. **`current_concept` never assigned** in services/routes found — concept-scoped mastery and quiz almost never activate.
8. **Confidence check bug:** `mastery.confidence_score < 0.3` almost never true if scores are 0–100.
9. **Mix explanation + quiz:** Orchestrator may append quiz **after** a long explanation in one turn (`type: "quiz"` with preface message and new question).
10. **`REVISE` not implemented** in UX — same as EXPLAIN for follow-up behavior.
11. **Dual evaluate paths:** Direct `/evaluate-answer` vs quiz-in-`/ask` — state fields may be inconsistent.
12. **`is_question` forces EXPLAIN** but user might have been asking for a quiz rhetorically.

---

# PART 9 — Error messages (where they come from)

## 9.1 `"Invalid authentication token"`

**File:** `app/core/dependencies.py`

```python
    payload = decode_access_token(token)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token",
        )

    user_id_str = payload.get("user_id")
    if not user_id_str:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token",
        )

    try:
        user_id = PydanticObjectId(user_id_str)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token",
        )
```

Also **401** with `"User not found"` if JWT valid but user id missing in DB.

## 9.2 `"MasteryService not initialized"`

**There is no user-facing string with this exact text** in the backend. Actual behavior when `self.mastery_service is None` in `evaluate_student_answer`:

```python
        if mastery_service is None:
            return {
                "correct": correct,
                "feedback": feedback,
            }
```

So mastery is **silently skipped** — no HTTP error, no message. The route docstring in `sessions.py` says `Expose evaluate_student_answer (requires MasteryService)` as documentation only.

## 9.3 Related runtime errors

| Source | Message / behavior |
|--------|---------------------|
| `RAGService.generate_prompt` | Raises `ValueError("DEEPSEEK_API_KEY not set")` if key missing (will bubble unless caught by caller). |
| `answer_tutor_question` early | Various `ValueError` strings: session not found, wrong student, not in progress, empty question. |
| HTTP layer | FastAPI converts unhandled exceptions to **500** unless handled. |

---

# Problems found (summary checklist)

- Intent is **naive substring / exact-list** logic; **no NLU**, no negation, strong **false positive** risk.
- **`learning_state`** is only partially wired; **`explaining`** is default but quickly replaced by **`checking_understanding`** without a clear “human” dialogue policy.
- **`OrchestratorService` ignores `has_recent_mistakes`**; **REVISE** has no dedicated handling.
- **Session events** don’t record **`is_correct`** on ANSWER rows → orchestrator’s **event-based** correctness is **wrong** in the main loop.
- **`generate_prompt`** omits **dialogue state**, **intent**, and **mistake context** — hurts human-like behavior.
- **`current_concept`** is effectively **unused** (read but never set in codebase grep).
- **Confidence vs mastery** threshold bug (`0.3` vs 0–100 scale).
- **Topic drift** possible between RAG topic and session topic for quizzes.
- **`/evaluate-answer`** vs quiz-in-**`/ask`** can **desync** `current_mode` / `current_question`.
- **401** text **"Invalid authentication token"** comes **only** from `get_current_user` JWT validation chain.

---

*End of analysis.*
