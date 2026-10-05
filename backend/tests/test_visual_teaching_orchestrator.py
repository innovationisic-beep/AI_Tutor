"""Orchestrator defer flags include visual_teaching."""

from types import SimpleNamespace

from app.services.pedagogy.concept_teaching_orchestrator import (
    ConceptTeachingOrchestrator,
)


def test_defer_when_vtse_timeline_must_play():
    orch = ConceptTeachingOrchestrator(concept_repo=SimpleNamespace())
    session = SimpleNamespace(
        concept_teaching_sequence_snapshot=["vtse"],
        concept_teaching_stage_index=0,
        concept_teaching_await_vtse_done=False,
        zone1_timeline_cache={
            "timeline_id": "tl-1",
            "beats": [{"index": 0}, {"index": 1}],
        },
    )
    assert orch.should_defer_concept_questions(session) is True


def test_mark_vtse_opening_awaits_playback_even_without_later_stage():
    orch = ConceptTeachingOrchestrator(concept_repo=SimpleNamespace())
    session = SimpleNamespace(
        concept_teaching_sequence_snapshot=["vtse", "visual_teaching"],
        concept_teaching_stage_index=0,
        concept_teaching_await_vtse_done=False,
        zone1_timeline_cache={
            "timeline_id": "tl-1",
            "beats": [{"index": 0}],
        },
    )
    assert orch.mark_vtse_opening_started(session) is True
    assert session.concept_teaching_await_vtse_done is True
    assert session.concept_teaching_stage_index == 0


def test_skip_empty_visual_teaching():
    orch = ConceptTeachingOrchestrator(concept_repo=SimpleNamespace())
    session = SimpleNamespace(
        concept_teaching_sequence_snapshot=["visual_teaching", "vtse"],
        concept_teaching_stage_index=0,
        concept_teaching_visual_teaching_snapshot=None,
    )
    assert orch._skip_non_executable_stages(session) == "vtse"
