"""Auto teaching-stage order: prompt contract, fallback, freeze, clone, reteach."""

from __future__ import annotations

import asyncio
import inspect
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from beanie.odm.fields import PydanticObjectId
from fastapi import HTTPException

from app.api.schemas.curriculum_structure import concept_to_out
from app.services.curriculum.concept_teaching_sequence import (
    auto_order_is_stale,
    normalize_teaching_sequence_mode,
    select_frozen_teaching_sequence,
    teaching_sequence_auto_fingerprint,
)
from app.services.curriculum.curriculum_clone_service import CurriculumCloneService
from app.services.curriculum.curriculum_concept_service import CurriculumConceptService
from app.services.curriculum.curriculum_publish_service import CurriculumPublishService
from app.services.curriculum.curriculum_validation_service import CurriculumValidationService
from app.services.curriculum.topic_context_service import TopicContext
from app.services.handlers.cluster_teachback_orchestrator import (
    handle_cluster_teachback_reteach,
)
from app.services.pedagogy.concept_teaching_orchestrator import ConceptTeachingOrchestrator
from app.services.pedagogy.stage_order_planner import (
    _SYSTEM,
    build_stage_order_prompt,
    resolve_auto_teaching_order,
)
from tests.curriculum.test_teaching_sequence_permutations import (
    _complete,
    _enter,
    _patches,
    _session,
)

_VTSE = {
    "strategy_id": "comparison_contrast",
    "version": 1,
    "payload": {
        "left_label": "Open",
        "right_label": "Closed",
        "notes": "A very long internal note that must not be copied into the prompt.",
        "name": "Compare pores",
        "rows": [
            {"dimension": "Day", "left": "Open pore", "right": "Closed pore"},
            {"dimension": "Night", "left": "Mostly shut", "right": "Shut"},
        ],
    },
}

_MANUAL = ["vtse", "story_hook", "visual_teaching"]
_SORTED = ["story_hook", "visual_teaching", "vtse"]


def _concept(**overrides) -> SimpleNamespace:
    base = dict(
        id="concept-1",
        display_name="Stomata",
        study_points=["Pores on leaves", "x" * 200],
        learning_outcomes=["Explain gas exchange"],
        teaching_sequence=list(_MANUAL),
        teaching_sequence_mode="auto",
        teaching_sequence_auto=[],
        teaching_sequence_auto_fingerprint="",
        teaching_sequence_auto_reason="",
        teaching_sequence_auto_status="",
        story_hook={
            "title": "A locked door",
            "body": "The leaf was shut until morning.",
            "teacher_intent": "Make them curious about pores " + ("y" * 220),
            "visuals": [],
        },
        visual_teaching={
            "images": [
                {
                    "asset_key": "leaf",
                    "storage_key": "leaf.png",
                    "title": "Stoma",
                    "teaching_purpose": "Show the pore opening " + ("z" * 140),
                }
            ]
        },
        vtse_template=dict(_VTSE),
    )
    base.update(overrides)
    return SimpleNamespace(**base)


class _Script:
    def __init__(self, replies: list) -> None:
        self.replies = list(replies)
        self.prompts: list[tuple[str, str]] = []

    async def __call__(self, user: str, *, system_content: str) -> str | None:
        self.prompts.append((user, system_content))
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


def _ok_reverse(user: str) -> str:
    raw = user.split("\n\nprevious_error:", 1)[0]
    stages = json.loads(raw)["available_stages"]
    return json.dumps(
        {"stages": list(reversed(stages)), "reason": "Practice after the picture."}
    )


class _Repo:
    def __init__(self, concept) -> None:
        self.concept = concept
        self.calls = 0

    async def get_by_id(self, _concept_id):
        self.calls += 1
        return self.concept


def _blank_session():
    session = _session(["vtse"])
    session.concept_teaching_sequence_snapshot = []
    session.concept_teaching_for_index = -1
    session.concept_teaching_sequence_source = None
    session.key_concept_ids = ["concept-1"]
    session.current_concept_index = 0
    return session


def test_missing_mode_is_manual_and_unknown_mode_is_rejected():
    assert normalize_teaching_sequence_mode(None) == "manual"
    assert normalize_teaching_sequence_mode("  ") == "manual"
    assert normalize_teaching_sequence_mode("AUTO") == "auto"
    with pytest.raises(HTTPException) as raised:
        normalize_teaching_sequence_mode("smart")
    assert raised.value.status_code == 400
    assert raised.value.detail["code"] == "INVALID_TEACHING_SEQUENCE_MODE"


def test_client_cannot_write_auto_list_through_concept_service():
    update = inspect.signature(CurriculumConceptService.update).parameters
    create = inspect.signature(CurriculumConceptService.create).parameters
    assert "teaching_sequence_mode" in update
    assert "teaching_sequence_mode" in create
    assert "teaching_sequence_auto" not in update
    assert "teaching_sequence_auto" not in create


def test_prompt_uses_context_and_hides_manual_order():
    concept = _concept()
    prompt = build_stage_order_prompt(concept, ["vtse", "story_hook", "visual_teaching"])
    body = json.loads(prompt)
    assert body["available_stages"] == _SORTED
    assert [card["stage"] for card in body["stage_cards"]] == _SORTED
    assert body["study_points"][0] == "Pores on leaves"
    assert len(body["study_points"][1]) == 160
    assert body["study_points"][1].endswith("…")
    assert body["learning_outcomes"] == ["Explain gas exchange"]
    assert "curious about pores" in body["stage_cards"][0]["teacher_intent"]
    assert len(body["stage_cards"][0]["teacher_intent"]) == 200
    assert "pore opening" in body["stage_cards"][1]["images"][0]["teaching_purpose"]
    assert len(body["stage_cards"][1]["images"][0]["teaching_purpose"]) == 120
    assert body["stage_cards"][2]["strategy_id"] == "comparison_contrast"
    assert "Open pore" not in prompt
    assert "very long internal note" not in prompt
    assert json.dumps(_MANUAL) not in prompt
    assert "manual" not in prompt.lower()
    assert "fallback" not in prompt.lower()
    assert "current order" not in prompt.lower()
    assert "manual" not in _SYSTEM.lower()
    assert "fallback" not in _SYSTEM.lower()
    assert set(body) == {
        "concept_name",
        "study_points",
        "learning_outcomes",
        "available_stages",
        "stage_cards",
    }


def test_fingerprint_ignores_manual_arrow_order():
    left = _concept()
    right = _concept(teaching_sequence=["visual_teaching", "story_hook", "vtse"])
    assert teaching_sequence_auto_fingerprint(left) == teaching_sequence_auto_fingerprint(
        right
    )
    right.study_points = ["A different point"]
    assert teaching_sequence_auto_fingerprint(left) != teaching_sequence_auto_fingerprint(
        right
    )


@pytest.mark.asyncio
async def test_auto_resolution_permutations_retry_and_fallback():
    concept = _concept()
    manual_before = list(concept.teaching_sequence)
    script = _Script([])

    async def _caller(user: str, *, system_content: str) -> str:
        script.prompts.append((user, system_content))
        return _ok_reverse(user)

    status = await resolve_auto_teaching_order(concept, llm=_caller)
    assert status == "resolved"
    assert concept.teaching_sequence_auto == ["vtse", "visual_teaching", "story_hook"]
    assert concept.teaching_sequence == manual_before
    assert concept.teaching_sequence_auto_status == "resolved"
    assert concept.teaching_sequence_auto_reason == "Practice after the picture."
    assert "alphabetical order" in script.prompts[0][1]

    again = _Script([])
    status = await resolve_auto_teaching_order(concept, llm=again)
    assert status == "resolved"
    assert again.prompts == []

    two = _concept(teaching_sequence=["story_hook", "vtse"])
    two.visual_teaching = {"images": []}
    seen: list[str] = []

    async def _two(user: str, *, system_content: str) -> str:
        seen.append(user)
        return _ok_reverse(user)

    assert await resolve_auto_teaching_order(two, llm=_two) == "resolved"
    assert two.teaching_sequence_auto == ["vtse", "story_hook"]
    assert len(seen) == 1

    one = _concept(teaching_sequence=["vtse"], story_hook=None, visual_teaching=None)
    assert await resolve_auto_teaching_order(one, llm=_Script([AssertionError("no")])) == "resolved"
    assert one.teaching_sequence_auto == ["vtse"]

    empty = _concept(
        teaching_sequence=["story_hook"],
        story_hook={"title": "", "body": "", "teacher_intent": ""},
        visual_teaching=None,
        vtse_template=None,
    )
    assert await resolve_auto_teaching_order(empty, llm=_Script([AssertionError("no")])) == "resolved"
    assert empty.teaching_sequence_auto == ["vtse"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "replies",
    [
        ["not-json", "still-not-json"],
        [None, ""],
        [TimeoutError("slow")],
        [RuntimeError("down")],
        [json.dumps({"stages": ["vtse", "vtse", "story_hook"], "reason": "dup"})] * 2,
        [json.dumps({"stages": ["story_hook", "vtse"], "reason": "missing"})] * 2,
        [json.dumps({"stages": ["story_hook", "quiz", "vtse"], "reason": "extra"})] * 2,
        [json.dumps({"stages": ["story_hook", "media", "vtse"], "reason": "media"})] * 2,
    ],
)
async def test_invalid_model_output_falls_back_to_manual_effective(replies):
    concept = _concept()
    script = _Script(replies)
    status = await resolve_auto_teaching_order(concept, llm=script)
    assert status == "fallback"
    assert concept.teaching_sequence_auto == _MANUAL
    assert concept.teaching_sequence_auto_status == "fallback"
    assert concept.teaching_sequence_auto_reason == ""
    assert concept.teaching_sequence == _MANUAL
    assert 1 <= len(script.prompts) <= 2


@pytest.mark.asyncio
async def test_validation_retry_can_recover_and_long_reason_is_clipped():
    concept = _concept()
    bad = json.dumps({"stages": ["media"], "reason": "no"})
    good = json.dumps({"stages": _SORTED, "reason": "r" * 400})
    script = _Script([bad, good])
    assert await resolve_auto_teaching_order(concept, llm=script) == "resolved"
    assert concept.teaching_sequence_auto == _SORTED
    assert len(concept.teaching_sequence_auto_reason) == 240
    assert "previous_error" in script.prompts[1][0]


@pytest.mark.asyncio
async def test_fallback_fingerprint_is_not_replanned_until_regenerate():
    concept = _concept()
    script = _Script([TimeoutError("slow")])
    assert await resolve_auto_teaching_order(concept, llm=script) == "fallback"
    held = _Script([AssertionError("should not call")])
    assert await resolve_auto_teaching_order(concept, llm=held) == "fallback"
    assert held.prompts == []
    again = _Script([json.dumps({"stages": _SORTED, "reason": "now"})])
    assert await resolve_auto_teaching_order(concept, regenerate=True, llm=again) == "resolved"


def test_select_frozen_manual_auto_and_stale():
    manual = _concept(teaching_sequence_mode="manual")
    seq, source = select_frozen_teaching_sequence(manual)
    assert source == "manual"
    assert seq == _MANUAL

    missing = _concept(teaching_sequence_mode=None, teaching_sequence=[])
    seq, source = select_frozen_teaching_sequence(missing)
    assert source == "manual"
    assert seq == ["vtse"]

    auto = _concept()
    auto.teaching_sequence_auto = ["story_hook", "vtse", "visual_teaching"]
    auto.teaching_sequence_auto_status = "resolved"
    auto.teaching_sequence_auto_fingerprint = teaching_sequence_auto_fingerprint(auto)
    seq, source = select_frozen_teaching_sequence(auto)
    assert source == "auto"
    assert seq == ["story_hook", "vtse", "visual_teaching"]

    stale = _concept()
    stale.teaching_sequence_auto = ["story_hook", "vtse", "visual_teaching"]
    stale.teaching_sequence_auto_status = "resolved"
    stale.teaching_sequence_auto_fingerprint = "old"
    seq, source = select_frozen_teaching_sequence(stale)
    assert source == "auto_fallback"
    assert seq == _MANUAL
    assert auto_order_is_stale(stale) is True
    assert auto_order_is_stale(auto) is False
    assert auto_order_is_stale(manual) is False


@pytest.mark.asyncio
async def test_snapshot_freeze_is_read_only_and_stable():
    manual = _concept(teaching_sequence_mode=None, teaching_sequence=[])
    repo = _Repo(manual)
    orch = ConceptTeachingOrchestrator(concept_repo=repo)
    session = _blank_session()
    with patch(
        "app.services.pedagogy.stage_order_planner.llm_call",
        side_effect=AssertionError("student path must not call the planner"),
    ):
        frozen = await orch.ensure_sequence_snapshot(session)
    assert frozen == ["vtse"]
    assert session.concept_teaching_sequence_source == "manual"

    authored = _concept(
        teaching_sequence_mode="manual",
        teaching_sequence=["visual_teaching", "story_hook", "vtse"],
    )
    repo.concept = authored
    session = _blank_session()
    frozen = await orch.ensure_sequence_snapshot(session)
    assert frozen == ["visual_teaching", "story_hook", "vtse"]
    assert session.concept_teaching_sequence_source == "manual"

    auto = _concept()
    auto.teaching_sequence_auto = ["story_hook", "vtse", "visual_teaching"]
    auto.teaching_sequence_auto_status = "resolved"
    auto.teaching_sequence_auto_fingerprint = teaching_sequence_auto_fingerprint(auto)
    repo.concept = auto
    repo.calls = 0
    session = _blank_session()
    first, second = await asyncio.gather(
        orch.ensure_sequence_snapshot(session),
        orch.ensure_sequence_snapshot(session),
    )
    assert first == second == ["story_hook", "vtse", "visual_teaching"]
    assert session.concept_teaching_sequence_source == "auto"
    assert session.concept_teaching_sequence_snapshot == first

    calls_after = repo.calls
    auto.teaching_sequence_auto = ["vtse", "story_hook", "visual_teaching"]
    auto.study_points = ["edited after freeze"]
    restored = await orch.ensure_sequence_snapshot(session)
    assert restored == ["story_hook", "vtse", "visual_teaching"]
    assert repo.calls == calls_after

    fresh = _blank_session()
    auto.teaching_sequence_auto_status = "fallback"
    auto.teaching_sequence_auto_fingerprint = teaching_sequence_auto_fingerprint(auto)
    frozen = await orch.ensure_sequence_snapshot(fresh)
    assert frozen == _MANUAL
    assert fresh.concept_teaching_sequence_source == "auto_fallback"

    newer = _blank_session()
    auto.study_points = ["Pores on leaves", "x" * 200]
    auto.teaching_sequence_auto = ["visual_teaching", "story_hook", "vtse"]
    auto.teaching_sequence_auto_status = "resolved"
    auto.teaching_sequence_auto_fingerprint = teaching_sequence_auto_fingerprint(auto)
    frozen = await orch.ensure_sequence_snapshot(newer)
    assert frozen == ["visual_teaching", "story_hook", "vtse"]
    assert newer.concept_teaching_sequence_source == "auto"


@pytest.mark.asyncio
async def test_concept_check_waits_for_non_vtse_last_auto_order():
    order = ["story_hook", "vtse", "visual_teaching"]
    concept = _concept()
    concept.teaching_sequence_auto = list(order)
    concept.teaching_sequence_auto_status = "resolved"
    concept.teaching_sequence_auto_fingerprint = teaching_sequence_auto_fingerprint(concept)
    orch = ConceptTeachingOrchestrator(concept_repo=_Repo(concept))
    session = _blank_session()
    frozen = await orch.ensure_sequence_snapshot(session)
    assert frozen == order
    assert session.concept_teaching_sequence_source == "auto"
    assert frozen != _MANUAL

    patches = _patches(orch)
    for item in patches:
        item.start()
    try:
        await _enter(orch, session, order[0])
        for index, stage in enumerate(order):
            assert session.concept_questions_active is False
            result = await _complete(orch, session, stage)
            if index < len(order) - 1:
                assert session.concept_questions_active is False
                nxt = order[index + 1]
                if nxt == "vtse":
                    session.flow_state = "explaining"
                    session.concept_vtse_opening_status = "ready"
                    session.concept_vtse_opening_for_index = 0
                    session.concept_teaching_await_vtse_done = True
                    session.zone1_last_completed_beat_index = 1
            else:
                assert result["type"] == "concept_question"
                assert session.concept_questions_active is True
        assert await orch.ensure_sequence_snapshot(session) == order
    finally:
        for item in reversed(patches):
            item.stop()


@pytest.mark.asyncio
async def test_reteach_does_not_replace_the_frozen_order():
    session = _session(["story_hook", "vtse", "visual_teaching"])
    session.concept_teaching_stage_index = 1
    session.concept_teaching_sequence_source = "auto"
    session.cluster_teachback_phase = "reteach_pending"
    session.teachback_concepts = ["cell"]
    session.asked_missing_concepts = []
    session.cluster_teachback_socratic_turn = 0
    before = list(session.concept_teaching_sequence_snapshot)
    with (
        patch(
            "app.services.handlers.cluster_teachback_orchestrator._run_simplified_vtse_reteach",
            new=AsyncMock(return_value={"type": "explanation"}),
        ),
        patch(
            "app.services.handlers.cluster_teachback_orchestrator.generate_cluster_teachback_question",
            new=AsyncMock(return_value="Try again"),
        ),
    ):
        await handle_cluster_teachback_reteach(
            SimpleNamespace(),
            session,
            PydanticObjectId(),
            PydanticObjectId(),
            SimpleNamespace(),
            AsyncMock(),
        )
    assert session.concept_teaching_sequence_snapshot == before
    assert session.concept_teaching_stage_index == 1
    assert session.concept_teaching_sequence_source == "auto"


@pytest.mark.asyncio
async def test_clone_copies_auto_fields_without_calling_the_planner():
    zone_id = PydanticObjectId()
    cluster_id = PydanticObjectId()
    concept = _concept()
    concept.id = PydanticObjectId()
    concept.curriculum_zone_id = zone_id
    concept.curriculum_cluster_id = cluster_id
    concept.slug = "stomata"
    concept.canonical_runtime_key = "stomata"
    concept.sort_order = 0
    concept.difficulty_level = "core"
    concept.estimated_learning_minutes = 8
    concept.legacy_concept_key = None
    concept.published_revision = 0
    concept.status = "draft"
    concept.teaching_sequence_auto = ["story_hook", "visual_teaching", "vtse"]
    concept.teaching_sequence_auto_fingerprint = "fp"
    concept.teaching_sequence_auto_reason = "Picture first"
    concept.teaching_sequence_auto_status = "resolved"
    original = list(concept.teaching_sequence)

    class _Store:
        def __init__(self) -> None:
            self.payloads = []

        async def create(self, payload):
            self.payloads.append(payload)
            return SimpleNamespace(id=PydanticObjectId())

    zones = _Store()
    clusters = _Store()
    concepts = _Store()
    service = CurriculumCloneService(
        zone_repo=zones, cluster_repo=clusters, concept_repo=concepts
    )
    zone = SimpleNamespace(
        id=zone_id,
        zone_number=1,
        title="Core",
        description="",
        purpose="",
        allows_vtse=True,
        is_system_zone=False,
        sort_order=1,
        status="draft",
    )
    cluster = SimpleNamespace(
        id=cluster_id,
        curriculum_zone_id=zone_id,
        cluster_number=1,
        title="Leaves",
        description="",
        study_points=[],
        learning_outcomes=[],
        sort_order=0,
        estimated_learning_minutes=8,
        status="draft",
    )
    with patch(
        "app.services.pedagogy.stage_order_planner.llm_call",
        side_effect=AssertionError("clone must not call the planner"),
    ):
        result = await service._write_cloned_tree(
            result=SimpleNamespace(
                zones_copied=0,
                clusters_copied=0,
                concepts_copied=0,
                notes_copied=0,
                questions_copied=0,
                zone_id_map={},
                cluster_id_map={},
                concept_id_map={},
            ),
            source_zones=[zone],
            source_clusters=[cluster],
            source_concepts=[concept],
            story_hooks={},
            vt_pkgs={},
            source_topic_id=PydanticObjectId(),
            target_topic_id=PydanticObjectId(),
            target_topic_source="catalog",
            target_organization_id=None,
            copy_content=False,
            note_grade="General",
            note_board="general",
        )
    copied = concepts.payloads[0]
    assert copied["teaching_sequence"] == original
    assert concept.teaching_sequence == original
    assert copied["teaching_sequence_mode"] == "auto"
    assert copied["teaching_sequence_auto"] == ["story_hook", "visual_teaching", "vtse"]
    assert copied["teaching_sequence_auto_fingerprint"] == "fp"
    assert copied["teaching_sequence_auto_reason"] == "Picture first"
    assert copied["teaching_sequence_auto_status"] == "resolved"
    assert result.concepts_copied == 1


def _ctx() -> TopicContext:
    return TopicContext(
        topic_id=PydanticObjectId(),
        topic_source="catalog",
        organization_id=None,
        topic_name="Leaves",
        curriculum_schema_version="v2",
        curriculum_revision=0,
        curriculum_published_at=None,
        supports_class_sessions=False,
        is_catalog=True,
    )


@pytest.mark.asyncio
async def test_publish_reuses_resolved_order_and_warns_on_failure():
    resolved = _concept()
    resolved.teaching_sequence_auto = _SORTED
    resolved.teaching_sequence_auto_status = "resolved"
    resolved.teaching_sequence_auto_fingerprint = teaching_sequence_auto_fingerprint(resolved)
    resolved.save = AsyncMock()
    manual = _concept(teaching_sequence_mode="manual")
    manual.save = AsyncMock()

    class _List:
        async def list_by_topic(self, *_args, **_kwargs):
            return [manual, resolved]

    calls = {"n": 0}

    async def _boom(*_args, **_kwargs):
        calls["n"] += 1
        raise AssertionError("matching fingerprint must not call the model")

    service = CurriculumPublishService(concept_repo=_List())
    with patch("app.services.pedagogy.stage_order_planner.llm_call", side_effect=_boom):
        await service._refresh_auto_teaching_orders(_ctx())
    assert calls["n"] == 0
    assert manual.save.await_count == 0
    assert resolved.save.await_count == 1

    failing = _concept()
    failing.save = AsyncMock()

    class _FailList:
        async def list_by_topic(self, *_args, **_kwargs):
            return [failing]

    service = CurriculumPublishService(concept_repo=_FailList())
    with patch(
        "app.services.pedagogy.stage_order_planner.resolve_auto_teaching_order",
        side_effect=RuntimeError("timeout"),
    ):
        await service._refresh_auto_teaching_orders(_ctx())
    assert failing.teaching_sequence_auto_status == "fallback"
    assert failing.teaching_sequence_auto_reason == ""
    assert failing.save.await_count == 1


@pytest.mark.asyncio
async def test_publish_validation_warns_without_blocking_ready():
    template = dict(_VTSE)

    class _Tree:
        async def get_tree(self, _ctx):
            return {
                "zones": [
                    {
                        "zone_number": 1,
                        "clusters": [
                            {
                                "cluster_number": 1,
                                "title": "Leaves",
                                "concepts": [
                                    {
                                        "display_name": "Fallback",
                                        "slug": "fallback",
                                        "vtse_template": template,
                                        "teaching_sequence": ["vtse"],
                                        "teaching_sequence_mode": "auto",
                                        "teaching_sequence_auto_status": "fallback",
                                    },
                                    {
                                        "display_name": "Ready",
                                        "slug": "ready",
                                        "vtse_template": template,
                                        "teaching_sequence": ["vtse"],
                                        "teaching_sequence_mode": "auto",
                                        "teaching_sequence_auto_status": "resolved",
                                    },
                                    {
                                        "display_name": "Manual",
                                        "slug": "manual",
                                        "vtse_template": template,
                                        "teaching_sequence": ["vtse"],
                                        "teaching_sequence_mode": "manual",
                                    },
                                ],
                            }
                        ],
                    }
                ]
            }

    result = await CurriculumValidationService(tree_service=_Tree()).validate(_ctx())
    assert result.ready_to_publish is True
    codes = [issue.code for issue in result.warnings]
    assert codes.count("TEACHING_SEQUENCE_AUTO_FALLBACK") == 1


def test_concept_out_exposes_auto_fields_and_stale_flag():
    concept = _concept()
    concept.curriculum_zone_id = "zone"
    concept.curriculum_cluster_id = "cluster"
    concept.slug = "stomata"
    concept.canonical_runtime_key = "stomata"
    concept.sort_order = 0
    concept.difficulty_level = "core"
    concept.estimated_learning_minutes = 8
    concept.status = "draft"
    concept.published_revision = 0
    concept.teaching_sequence_auto = ["story_hook", "vtse", "visual_teaching"]
    concept.teaching_sequence_auto_status = "resolved"
    concept.teaching_sequence_auto_reason = "Hook first"
    concept.teaching_sequence_auto_fingerprint = "stale"
    out = concept_to_out(concept)
    assert out.teaching_sequence_mode == "auto"
    assert out.teaching_sequence_auto == ["story_hook", "vtse", "visual_teaching"]
    assert out.teaching_sequence_auto_reason == "Hook first"
    assert out.teaching_sequence_auto_status == "resolved"
    assert out.teaching_sequence_auto_stale is True
    assert not hasattr(out, "teaching_sequence_auto_fingerprint")
