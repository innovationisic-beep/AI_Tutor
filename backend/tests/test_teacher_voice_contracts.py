"""Prompt contracts for one continuous teacher voice. No live DeepSeek calls."""

from __future__ import annotations

import inspect
import json

from app.services.pedagogy.teacher_voice import (
    TEACHER_SPEAKING_CONTRACT,
    build_continuity_card,
    coarse_position_hint,
    phrase_has_internal_name,
    zone0_close_paragraph,
)
from app.services.story_hook.planner import _FOLLOW_UP_SYSTEM, _PLANNER_SYSTEM, build_planner_prompt
from app.services.visual_teaching.authored import (
    ConceptVisualTeaching,
    VisualTeachingConnection,
    VisualTeachingImage,
    VisualTeachingRegion,
)
from app.services.visual_teaching.planner import (
    _PLANNER_SYSTEM as VT_SYSTEM,
    build_visual_teaching_user_payload,
)
from app.vtse.authoring import authored_expand
from app.vtse.authoring.semantic_extract import extract_authoring_semantics

CONCEPT = "Humans vs Robots"


class _Concept:
    def __init__(self, strategy: str = "comparison_contrast"):
        self.display_name = CONCEPT
        self.story_hook = {
            "title": "A smile that is not a feeling",
            "body": "A robot can copy a smile.",
            "teacher_intent": "Notice whether a smile is a feeling.",
        }
        self.visual_teaching = {
            "images": [
                {
                    "teaching_purpose": "See that both faces can smile.",
                    "asset_key": "faces",
                }
            ]
        }
        self.vtse_template = {"strategy_id": strategy, "payload": {}}
        self.teaching_sequence = ["story_hook", "vtse", "visual_teaching"]
        self.teaching_sequence_mode = "manual"
        self.study_points = []
        self.learning_outcomes = []


def _card(
    stage: str | None,
    strategy: str = "comparison_contrast",
    thread: str = "",
    sequence: list[str] | None = None,
) -> dict:
    concept = _Concept(strategy)
    concept.teaching_sequence = sequence or ["story_hook", "vtse", "visual_teaching"]
    session = type("S", (), {})()
    session.story_hook_qa = [{"answer": thread}] if thread else []
    session.zone0_student_thread = ""
    session.concept_teaching_sequence_snapshot = list(concept.teaching_sequence)
    session.concept_teaching_story_hook_snapshot = concept.story_hook
    session.concept_teaching_visual_teaching_snapshot = concept.visual_teaching
    return build_continuity_card(
        concept=concept,
        session=session,
        current_stage=stage,
        concept_name=CONCEPT,
        include_student_thread=stage is not None,
    )


def test_focus_cards_use_student_phrases():
    cases = {
        "zone0_story": _card(None, sequence=["story_hook", "vtse"]),
        "zone0_vtse": _card(None, strategy="linear_process", sequence=["vtse"]),
        "hook_to_vt": _card("story_hook", sequence=["story_hook", "visual_teaching"]),
        "hook_to_vtse": _card("story_hook", sequence=["story_hook", "vtse"]),
        "vt_to_vtse": _card(
            "visual_teaching", sequence=["story_hook", "visual_teaching", "vtse"]
        ),
        "vtse_to_vt": _card("vtse", sequence=["vtse", "visual_teaching"]),
    }
    # Zone 0 with comparison sequence leads into the story, not a stage id.
    assert "the steps of" in cases["zone0_vtse"]["next_focus"]
    assert cases["zone0_story"]["next_focus"].startswith("a short story")
    assert cases["hook_to_vt"]["next_focus"] == "See that both faces can smile."
    assert "side-by-side comparison" in cases["hook_to_vtse"]["next_focus"]
    assert cases["vtse_to_vt"]["next_focus"] == "See that both faces can smile."
    assert cases["vt_to_vtse"]["previous_focus"].startswith("a short story")
    for card in cases.values():
        blob = " ".join(card.values())
        assert not phrase_has_internal_name(blob)
        for token in ("story_hook", "visual_teaching", "vtse"):
            assert token not in blob


def test_zone0_close_points_at_next_focus_and_the_button():
    text = zone0_close_paragraph("a short story about Humans vs Robots")
    assert "a short story about Humans vs Robots" in text
    assert "button" in text
    assert "story_hook" not in text
    assert zone0_close_paragraph("").startswith("Paragraph 2:")


def test_story_hook_prompt_carries_finish_bridge_and_spoken_only_rule():
    card = _card("story_hook", thread="I think only people feel a smile.")
    prompt = build_planner_prompt(
        concept_label=CONCEPT,
        seed="A robot can copy a smile.",
        title="A smile that is not a feeling",
        teacher_intent="Notice the feeling.",
        outline="Humans feel. Robots display.",
        visuals=[],
        continuity=card,
    )
    assert "side-by-side comparison" in prompt
    assert "I think only people feel a smile." in prompt
    assert "spoken only" in _PLANNER_SYSTEM.lower() or "spoken only" in TEACHER_SPEAKING_CONTRACT.lower()
    assert "bridges stay in" in _PLANNER_SYSTEM
    assert "story_hook" not in prompt
    assert "return to the story" in _FOLLOW_UP_SYSTEM


def test_visual_payload_omits_geometry_and_unhinted_sides():
    pkg = ConceptVisualTeaching(
        images=[
            VisualTeachingImage(
                id="1",
                asset_key="faces",
                storage_key="faces.jpg",
                teaching_purpose="See that both faces can smile.",
                annotations_status="confirmed",
                regions=[
                    VisualTeachingRegion(
                        region_id="human_face",
                        label="Human face",
                        teaching_purpose="A smile that can come from a feeling.",
                        shape="rect",
                        geometry={"x": 0.05, "y": 0.4, "w": 0.2, "h": 0.2},
                    ),
                    VisualTeachingRegion(
                        region_id="robot_face",
                        label="Robot face",
                        teaching_purpose="A smile a program can display.",
                        shape="rect",
                        geometry={},
                    ),
                ],
                connections=[
                    VisualTeachingConnection(
                        connection_id="feeling_to_smile",
                        from_anchor="a",
                        to_anchor="b",
                        label="Feeling to smile",
                        teaching_purpose="A feeling can lead to the smile.",
                    )
                ],
            )
        ]
    )
    hinted = coarse_position_hint(
        shape="rect", geometry={"x": 0.05, "y": 0.4, "w": 0.2, "h": 0.2}
    )
    assert hinted == "left"
    assert coarse_position_hint(shape="rect", geometry={}) is None

    card = _card("visual_teaching")
    payload = build_visual_teaching_user_payload(
        pkg=pkg,
        vtse_template={"strategy_id": "comparison_contrast", "payload": {}},
        concept_name=CONCEPT,
        continuity=card,
    )
    raw = json.dumps(payload)
    assert "feeling_to_smile" in raw
    assert '"geometry"' not in raw
    assert '"x"' not in raw
    assert '"y"' not in raw
    assert '"w"' not in raw
    assert '"h"' not in raw
    robot = payload["teaching_images"][0]["regions"][1]
    assert "position_hint" not in robot
    robot_raw = json.dumps(robot)
    for word in ("left", "right", "above"):
        assert word not in robot_raw
    assert "position_hint" in VT_SYSTEM
    assert "highlighted part" in VT_SYSTEM
    assert "next_focus" in raw
    assert "story_hook" not in raw


def test_vtse_expand_is_direct_and_keeps_speech_off_the_board():
    source = inspect.getsource(authored_expand)
    assert "generate_prompt" not in source
    assert "Have you ever wondered" not in source
    assert "VTSE_STRUCTURED" not in source
    assert "_ask_expand" in source
    assert "llm_call" in source
    assert "pair_narration is spoken only" in source
    assert "Do not copy narration into explanation_text" in source
    assert "Do not copy pair_narration into cards" in source
    assert "why this step follows the previous" in source
    assert "loop returns" in source
    assert "toward the next outline point" in source


def test_hierarchy_opening_replaces_fallback_sentence():
    draft = extract_authoring_semantics(
        topic_name="Living things",
        concept=CONCEPT,
        trait_steps=[
            {"title": "Feelings", "annotation": "People feel things inside.", "narration": "People feel."},
            {"title": "Power", "annotation": "People need food.", "narration": "People eat."},
            {"title": "Choice", "annotation": "People choose.", "narration": "People choose."},
        ],
        opening_narration="Both faces can smile, and only one of those smiles starts inside.",
    )
    assert draft.anchor_narration.startswith("Both faces can smile")
    fallback = extract_authoring_semantics(
        topic_name="Living things",
        concept=CONCEPT,
        trait_steps=[
            {"title": "Feelings", "annotation": "People feel things inside.", "narration": "People feel."},
            {"title": "Power", "annotation": "People need food.", "narration": "People eat."},
            {"title": "Choice", "annotation": "People choose.", "narration": "People choose."},
        ],
    )
    assert fallback.anchor_narration.startswith("Let us anchor the idea first")


def test_neighbor_continuity_cases_are_in_the_expand_prompts():
    """Golden cases 7-9: comparison, process, and hierarchy neighbor rules."""
    source = inspect.getsource(authored_expand)
    assert "moving toward that next row" in source
    assert "why this step follows the previous outline step" in source
    assert "toward the next outline point" in source
    assert TEACHER_SPEAKING_CONTRACT.splitlines()[0] in source or "TEACHER_SPEAKING_CONTRACT" in source


ATRIUM_BOARD = "Right atrium receives deoxygenated blood returning from the body."
ATRIUM_SPEECH = (
    "Start with the right atrium. An atrium is an upper chamber of the heart. "
    "The blood arriving here has already given much of its oxygen to the body, "
    "which is why it is called deoxygenated. From this chamber the blood moves "
    "on to the next chamber."
)


def test_speech_guard_rejects_a_read_aloud_and_keeps_shared_terms():
    from app.vtse.authoring.authored_expand import narration_board_error, speech_reads_board

    assert speech_reads_board(ATRIUM_BOARD, ATRIUM_BOARD)
    assert narration_board_error(ATRIUM_BOARD, ATRIUM_BOARD) == "speech_reads_board"
    synonym = "Right atrium gets deoxygenated blood returning from the body."
    assert speech_reads_board(synonym, ATRIUM_BOARD)
    living = "Humans are living organisms."
    assert speech_reads_board("Humans are organisms that are alive.", living)
    rich_living = (
        "Let's start with the human side. When we call humans living organisms, we mean "
        "their bodies naturally carry out the processes needed for life. We grow, use energy, "
        "and reproduce. That is very different from a robot, which may move but does not "
        "carry out biological life processes."
    )
    assert speech_reads_board(
        rich_living,
        "Humans are living organisms that grow and reproduce.",
    ) is False
    assert narration_board_error("", ATRIUM_BOARD) == "empty_narration"
    assert speech_reads_board(ATRIUM_SPEECH, ATRIUM_BOARD) is False
    assert narration_board_error(ATRIUM_SPEECH, ATRIUM_BOARD) is None
    card = "Humans smile because a feeling starts inside."
    assert narration_board_error(card, card) == "speech_reads_board"


def test_expand_prompts_keep_board_depth_and_ask_speech_to_teach():
    source = inspect.getsource(authored_expand)
    lowered = source.lower()
    assert "one sentence" not in lowered
    assert "several useful sentences" in source
    assert "two visible columns" in source
    assert "both sides" in lowered
    assert "distinction" in lowered
    assert "why it matters" in lowered
    assert "moving toward that next row" in source
    assert "why this step leads to the next" in source
    assert "loop returns" in source
    assert "child belongs to the parent" in source
    assert "why the trait matters" in source
    assert "spoken only" in lowered
    assert "previous_error" in source
    assert "explanation.split" not in source
    assert 'f"Next, {label}."' not in source


def test_board_and_speech_stay_distinct_for_every_template():
    from app.vtse.authoring.authored_expand import prepend_spoken_opening, speech_reads_board
    from app.vtse.authoring.comparison_rows import ComparisonRow
    from app.vtse.authoring.semantic_extract import TraitDraft
    from app.vtse.authoring.semantic_shape import ComparisonSidesDraft
    from app.vtse.strategies.clustered_trait_list import build_clustered_trait_list_plan_flat
    from app.vtse.strategies.comparison_contrast import build_comparison_contrast_plan
    from app.vtse.strategies.cycle_process import build_cycle_process_plan
    from app.vtse.strategies.linear_process import build_linear_process_plan

    opening = "Both faces can smile, and only one of those smiles starts inside."
    left_card = (
        "A human smile begins as a feeling inside the body. "
        "The face then shows that feeling to other people."
    )
    right_card = (
        "A robot smile is a programmed face movement. "
        "No feeling has to start inside the machine."
    )
    pair = (
        "This row is about where a smile begins. On the human side a feeling starts "
        "inside and the face follows it. On the robot side the face can move because "
        "a program told it to, which is why the same look is not the same event. "
        "The next row asks what each one needs in order to keep going."
    )
    sides = ComparisonSidesDraft(
        left_label="Humans",
        right_label="Robots",
        opening_narration=opening,
        rows=(
            ComparisonRow(
                dimension="Emotions",
                left_title="Inner feeling",
                left_detail=left_card,
                right_title="Programmed look",
                right_detail=right_card,
                left_card=left_card,
                right_card=right_card,
                pair_narration_text=pair,
            ),
        ),
    )
    comparison = build_comparison_contrast_plan(
        topic_label="Humans vs Robots",
        sides=sides,
        concept_id="compare",
    )
    left_header = next(b for b in comparison.beats if b.metadata.get("comparison_side") == "left_col")
    right_header = next(b for b in comparison.beats if b.metadata.get("comparison_side") == "right_col")
    left_row = next(b for b in comparison.beats if b.metadata.get("comparison_side") == "left")
    right_row = next(b for b in comparison.beats if b.metadata.get("comparison_side") == "right")
    assert left_header.narration_text.startswith("Both faces can smile")
    assert right_header.narration_text == "Robots"
    assert right_row.narration_text == "\u200b"
    assert "feeling" in (comparison.semantic_graph.nodes[2].summary or "")
    assert speech_reads_board(left_row.narration_text or "", left_card) is False

    child_board = (
        "Feelings begin inside a person before the face changes. "
        "That inner start is what makes the smile a human one."
    )
    child_speech = (
        "This child belongs to the parent idea of a living response. "
        "A feeling is something that starts inside before anyone else can see it. "
        "Next we look at what the body needs in order to keep that response going."
    )
    hierarchy = extract_authoring_semantics(
        topic_name="Living things",
        concept="Living response",
        trait_steps=[
            {"title": "Feelings", "annotation": child_board, "narration": child_speech},
            {"title": "Energy", "annotation": "The body needs fuel to keep responding.", "narration": "Energy keeps the response going."},
            {"title": "Choice", "annotation": "A person can choose the next action.", "narration": "Choice is how the person directs the response."},
        ],
        opening_narration=opening,
    )
    assert hierarchy.anchor_narration.startswith("Both faces can smile")
    assert "feeling" in hierarchy.traits[0].summary.lower() or "Feelings" in hierarchy.traits[0].summary
    assert speech_reads_board(hierarchy.traits[0].narration, hierarchy.traits[0].summary) is False
    assert "belongs to the parent" in hierarchy.traits[0].narration

    cluster_board = "A smile can copy the shape of a feeling without containing one."
    cluster_speech = prepend_spoken_opening(
        "This trait matters because the copied shape can fool the eye, and it fits beside the next trait about what powers the copy.",
        opening,
    )
    traits = (
        TraitDraft("Smile", cluster_board, cluster_speech),
        TraitDraft("Power", "A robot draws power from electricity.", "Electricity is why the copy can keep running after the first look."),
        TraitDraft("Program", "A program decides which face to show.", "The program is how this trait fits the set: nothing inside has to feel it."),
    )
    cluster = build_clustered_trait_list_plan_flat(topic_label="Signals", traits=traits, concept_id="cluster")
    assert cluster.beats[0].narration_text.startswith(opening)
    assert cluster_board in (cluster.semantic_graph.nodes[0].summary or "")
    assert speech_reads_board(cluster.beats[0].narration_text or "", cluster_board) is False

    steps = (
        TraitDraft("Right atrium", ATRIUM_BOARD, ATRIUM_SPEECH),
        TraitDraft("Right ventricle", "The right ventricle pumps that blood toward the lungs.", "The ventricle is the pumping chamber, which is why the blood can leave for the lungs."),
        TraitDraft("Lungs", "The lungs add oxygen to the blood.", "Oxygen enters here, which is why the blood is no longer called deoxygenated."),
    )
    linear = build_linear_process_plan(topic_label="Heart", steps=steps, concept_id="heart")
    assert ATRIUM_BOARD in (linear.beats[0].annotation_text or linear.semantic_graph.nodes[0].summary or "")
    assert speech_reads_board(linear.beats[0].narration_text or "", ATRIUM_BOARD) is False
    assert "atrium" in (linear.beats[0].narration_text or "").lower()

    cycle_last = (
        "Evaporation lifts water into the air, which is why the cycle returns to the first stage "
        "and condensation can begin again."
    )
    cycle_steps = (
        TraitDraft("Evaporation", "Heat turns liquid water into vapor.", "Heat gives the water enough energy to leave the surface and become vapor."),
        TraitDraft("Condensation", "Cooling turns vapor back into droplets.", "Cooling pulls the vapor together, which is why clouds can form."),
        TraitDraft("Return", "Droplets fall and the water is liquid again.", cycle_last),
    )
    cycle = build_cycle_process_plan(topic_label="Water cycle", steps=cycle_steps, concept_id="water")
    assert "vapor" in (cycle.semantic_graph.nodes[0].summary or "").lower()
    assert "returns to the first stage" in (cycle.beats[-1].narration_text or "")
    assert speech_reads_board(cycle.beats[-1].narration_text or "", cycle_steps[-1].summary) is False


def test_comparison_json_keeps_pair_narration_through_normalization():
    """The production parser used to drop pair_narration and then read the cards."""
    from app.vtse.authoring.comparison_rows import comparison_rows_from_llm_json
    from app.vtse.authoring.semantic_extract import AuthoringSemanticDraft
    from app.vtse.authoring.semantic_shape import _build_comparison_sides
    from app.vtse.strategies.comparison_contrast import build_comparison_contrast_plan

    left_card = (
        "Humans are living organisms. They grow, reproduce, respond to their surroundings, "
        "and carry out essential life processes. Their bodies perform these processes naturally "
        "to keep them alive."
    )
    right_card = (
        "Robots are non-living machines created by humans. They may move or respond, but they "
        "do not grow, reproduce, or perform biological life processes. Their actions depend on "
        "programming and power."
    )
    pair = (
        "This first row is about what it means to be alive. On the human side, a living organism "
        "is a body that carries out the processes needed for life: we grow, use energy, and can "
        "reproduce. A robot can move, but that movement follows its design, so motion alone does "
        "not make it alive. Keep that distinction, because the next row looks at emotions."
    )
    opening = (
        "On the left we are looking at humans, and on the right at robots. "
        "Let's begin with the first difference."
    )
    payload = {
        "opening_narration": opening,
        "left_label": "Humans",
        "right_label": "Robots",
        "rows": [
            {
                "dimension": "Living",
                "left_title": "Living organism",
                "right_title": "Machine",
                "left_detail": left_card,
                "right_detail": right_card,
                "left_card": left_card,
                "right_card": right_card,
                "pair_narration": pair,
            }
        ],
    }
    parsed = comparison_rows_from_llm_json(payload, left_label="Humans", right_label="Robots")
    assert len(parsed) == 1
    assert parsed[0].pair_narration_text == pair
    assert parsed[0].left_card == left_card
    assert parsed[0].right_card == right_card

    draft = AuthoringSemanticDraft(
        topic_label="Humans vs Robots",
        concept_label="Humans vs Robots",
        anchor_label="Humans vs Robots",
        anchor_summary="",
        anchor_narration="",
        traits=(),
        source="test",
    )
    sides = _build_comparison_sides(
        topic_name="Humans vs Robots",
        concept="Humans vs Robots",
        draft=draft,
        rag_context=None,
        comparison_llm_json=payload,
    )
    assert sides.opening_narration == opening
    assert sides.rows[0].pair_narration_text == pair
    assert left_card in sides.rows[0].left_card_detail()
    assert right_card in sides.rows[0].right_card_detail()

    plan = build_comparison_contrast_plan(
        topic_label="Humans vs Robots",
        sides=sides,
        concept_id="compare",
    )
    left_header = next(b for b in plan.beats if b.metadata.get("comparison_side") == "left_col")
    right_header = next(b for b in plan.beats if b.metadata.get("comparison_side") == "right_col")
    left_row = next(b for b in plan.beats if b.metadata.get("comparison_side") == "left")
    right_row = next(b for b in plan.beats if b.metadata.get("comparison_side") == "right")
    assert left_header.narration_text == opening
    assert right_header.narration_text == "Robots"
    assert left_row.narration_text == pair
    assert right_row.narration_text == "\u200b"
    assert "When we compare" not in (left_row.narration_text or "")
    assert "In contrast" not in (left_row.narration_text or "")
    assert "life processes" in (plan.semantic_graph.nodes[2].summary or "")
    assert "programming and power" in (plan.semantic_graph.nodes[3].summary or "")
