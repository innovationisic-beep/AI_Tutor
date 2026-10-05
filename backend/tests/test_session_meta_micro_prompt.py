"""Session meta exposes learner-facing micro question during Zone 1 hold."""

from types import SimpleNamespace

from app.services.handlers.session_meta import build_teacher_session_meta


def test_meta_includes_micro_interaction_prompt_when_hold() -> None:
    session = SimpleNamespace(
        current_zone=1,
        current_step_in_concept=0,
        current_question=(
            "Living things need food. Can something grow but still not be alive?"
        ),
        explanation_mode="default",
        current_concept_index=0,
        total_concepts=3,
        key_concepts=["Digestion Process"],
        concept_clusters=None,
        current_cluster_index=0,
        student_questions_active=False,
        concept_questions_active=False,
        concept_question_index=0,
        concept_question_followup=False,
        concept_question_clarifying=False,
        sus_score=50.0,
        zone2_depth="medium",
        clarity_score=None,
    )
    meta = build_teacher_session_meta(session, topic=None)
    assert meta is not None
    assert meta["micro_quiz_hold"] == 1
    assert meta["micro_interaction_prompt"] == (
        "Can something grow but still not be alive?"
    )


def test_meta_omits_prompt_when_no_hold() -> None:
    session = SimpleNamespace(
        current_zone=1,
        current_step_in_concept=19,
        current_question="Old question?",
        explanation_mode="default",
        current_concept_index=0,
        total_concepts=3,
        key_concepts=["Digestion Process"],
        concept_clusters=None,
        current_cluster_index=0,
        student_questions_active=False,
        concept_questions_active=False,
        concept_question_index=0,
        concept_question_followup=False,
        concept_question_clarifying=False,
        sus_score=50.0,
        zone2_depth="medium",
        clarity_score=None,
    )
    meta = build_teacher_session_meta(session, topic=None)
    assert meta is not None
    assert meta["micro_quiz_hold"] == 0
    assert "micro_interaction_prompt" not in meta


def test_meta_concept_questions_emits_prompt_even_when_clarifying_hold_off() -> None:
    session = SimpleNamespace(
        current_zone=1,
        current_step_in_concept=0,
        current_question="What is photosynthesis?",
        explanation_mode="default",
        current_concept_index=0,
        total_concepts=3,
        key_concepts=["Photosynthesis"],
        concept_clusters=None,
        current_cluster_index=0,
        student_questions_active=False,
        concept_questions_active=True,
        concept_question_index=1,
        concept_question_followup=False,
        concept_question_clarifying=True,
        concept_question_pending_advance=False,
        current_concept_question_type="mcq",
        current_concept_question_options=["A", "B"],
        sus_score=50.0,
        zone2_depth="medium",
        clarity_score=None,
        concept_teaching_await_vtse_done=False,
        flow_checkpoint_pending=False,
        flow_state="concept_questions",
    )
    meta = build_teacher_session_meta(session, topic=None)
    assert meta is not None
    assert meta["concept_questions_active"] is True
    assert meta["micro_quiz_hold"] == 0
    assert meta["concept_question_clarifying"] is True
    assert meta["micro_interaction_prompt"] == "What is photosynthesis?"
    assert meta["current_question"] == "What is photosynthesis?"


def test_meta_concept_questions_hold() -> None:
    session = SimpleNamespace(
        current_zone=1,
        current_step_in_concept=0,
        current_question="What is photosynthesis?",
        explanation_mode="default",
        current_concept_index=0,
        total_concepts=3,
        key_concepts=["Photosynthesis"],
        concept_clusters=None,
        current_cluster_index=0,
        student_questions_active=False,
        concept_questions_active=True,
        concept_question_index=1,
        concept_question_followup=False,
        concept_question_clarifying=False,
        sus_score=50.0,
        zone2_depth="medium",
        clarity_score=None,
    )
    meta = build_teacher_session_meta(session, topic=None)
    assert meta is not None
    assert meta["micro_quiz_hold"] == 1
    assert meta["concept_questions_active"] is True
    assert meta["concept_question_index"] == 1
