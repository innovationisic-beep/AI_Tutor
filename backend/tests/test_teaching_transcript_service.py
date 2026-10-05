"""Tests for transcript-grounded quiz question helpers."""

from app.cir.compile_to_timeline_v3 import compile_cir_v1_to_timeline
from app.services.handlers.concept_taught_context import (
    asked_quantity_in_question,
    effective_taught_item_count,
    extract_taught_steps_from_timeline,
    format_grading_context_block,
    question_count_matches_taught,
)
from app.services.handlers.teaching_transcript_service import (
    build_rule_based_pack_from_focus,
    extract_narrations_from_timeline,
    extract_quizable_items_from_timeline,
    extract_teaching_facts,
    fact_key,
    format_transcript_taught_block,
    merge_transcript_into_taught_context,
    pack_matches_focus_fact,
    pick_focus_fact,
    text_relates_to_fact,
)
from app.services.timeline_planner_v3 import TimelinePlannerV3
from app.vtse.authoring.semantic_extract import extract_authoring_semantics
from app.vtse.compiler.vtse_compiler import VTSECompiler
from app.vtse.strategies.clustered_trait_list import build_clustered_trait_list_plan_flat


def _living_things_timeline() -> dict:
    steps = [
        {
            "title": "Living Things",
            "annotation": "Living things share core life processes.",
            "narration": "Let us anchor the idea first.",
        },
        {
            "title": "Grow",
            "annotation": "Living things increase in size over time.",
            "narration": "They grow over time.",
        },
        {
            "title": "Breathe",
            "annotation": "Living things exchange gases for energy.",
            "narration": "They breathe.",
        },
        {
            "title": "Reproduce",
            "annotation": "Living things can make new organisms.",
            "narration": "They reproduce.",
        },
    ]
    semantic = extract_authoring_semantics(
        topic_name="Living Things",
        concept="life",
        trait_steps=steps,
        source="template_steps",
    )
    plan = build_clustered_trait_list_plan_flat(
        topic_label=semantic.topic_label,
        traits=semantic.traits,
    )
    cir = VTSECompiler().compile_to_cir_dict(plan).cir
    out = compile_cir_v1_to_timeline(
        cir=cir,
        session_id="s",
        topic_id="t",
        concept="life",
        planner=TimelinePlannerV3(),
    )
    return out.timeline


def test_hierarchy_quizable_items_exclude_root_anchor() -> None:
    timeline = _living_things_timeline()
    items = extract_quizable_items_from_timeline(timeline)
    assert items["representation"] == "hierarchy"
    assert items["topic_anchor"] == "Living Things"
    assert items["steps"] == ["Grow", "Breathe", "Reproduce"]
    assert len(items["teaching_facts"]) == 3
    assert all("Living Things" != f for f in items["teaching_facts"])
    assert any("grow" in f.lower() or "size" in f.lower() for f in items["teaching_facts"])
    assert effective_taught_item_count(
        {"teaching_facts": items["teaching_facts"], "step_count": len(items["teaching_facts"])}
    ) == 3


def test_extract_narrations_reads_narration_segments() -> None:
    timeline = _living_things_timeline()
    narrations = extract_narrations_from_timeline(timeline)
    assert len(narrations) == 4
    assert any("grow" in n.lower() for n in narrations)


def test_extract_taught_steps_from_hierarchy_timeline() -> None:
    timeline = _living_things_timeline()
    steps = extract_taught_steps_from_timeline(timeline)
    assert steps == ["Grow", "Breathe", "Reproduce"]
    assert "Living Things" not in steps


def test_format_transcript_taught_block_hierarchy_structure() -> None:
    timeline = _living_things_timeline()
    items = extract_quizable_items_from_timeline(timeline)
    ctx = merge_transcript_into_taught_context(
        {"steps": [], "step_count": 0},
        "",
        structured=items,
    )
    block = format_transcript_taught_block(ctx)
    assert "TOPIC ANCHOR" in block
    assert "exactly 3" in block
    assert "Grow" in block
    assert "not 4" in block.lower() or "not 4." in block


def test_question_count_rejects_four_characteristics_for_three_traits() -> None:
    timeline = _living_things_timeline()
    items = extract_quizable_items_from_timeline(timeline)
    taught = merge_transcript_into_taught_context(
        {"steps": [], "step_count": 0},
        "",
        structured=items,
    )
    bad = "What are the four characteristics of living things?"
    good = "What does reproduction mean for living things?"
    assert asked_quantity_in_question(bad) == 4
    assert question_count_matches_taught(bad, taught) is False
    assert question_count_matches_taught(good, taught) is True


def test_format_grading_context_block_hierarchy() -> None:
    timeline = _living_things_timeline()
    items = extract_quizable_items_from_timeline(timeline)
    ctx = merge_transcript_into_taught_context(
        {"steps": [], "step_count": 0},
        "",
        structured=items,
    )
    block = format_grading_context_block(ctx)
    assert "TOPIC ANCHOR" in block
    assert "CHARACTERISTICS TAUGHT" in block
    assert "Reproduce" in block


def test_extract_teaching_facts_from_transcript() -> None:
    transcript = (
        "Living things grow over time. "
        "They reproduce to make offspring. "
        "They respire to release energy from food."
    )
    facts = extract_teaching_facts(transcript)
    assert len(facts) == 3
    assert any("grow" in f.lower() for f in facts)
    assert any("reproduce" in f.lower() for f in facts)


def test_pick_focus_fact_rotates() -> None:
    ctx = {
        "teaching_facts": [
            "Living things grow over time.",
            "They reproduce to make offspring.",
            "They respire to release energy.",
        ]
    }
    f0, k0 = pick_focus_fact(ctx, used_fact_keys=[], question_index=0)
    f1, k1 = pick_focus_fact(ctx, used_fact_keys=[k0], question_index=1)
    assert f0 and f1
    assert k0 != k1


def test_question_count_rejects_four_key_points() -> None:
    taught = {
        "teaching_facts": ["a", "b", "c"],
        "step_count": 3,
    }
    bad = "Describe the four key points about living things."
    good = "What does reproduction mean?"
    assert asked_quantity_in_question(bad) == 4
    assert question_count_matches_taught(bad, taught) is False
    assert question_count_matches_taught(good, taught) is True


def test_pack_matches_focus_fact_rejects_broad_stem() -> None:
    focus = "Living things respire to release energy from food."
    pack = {
        "question": "What are the main ideas about living things?",
        "correct_answer": "growth and reproduction",
    }
    assert pack_matches_focus_fact(pack, focus) is False
    assert text_relates_to_fact("They respire to release energy", focus) is True


def test_pack_matches_focus_fact_rejects_drifted_correct_answer() -> None:
    from app.services.handlers.teaching_transcript_service import (
        text_strongly_grounded_in_fact,
    )

    focus = "Living things respire to release energy from food."
    drifted = {
        "question": "What do living things do with food?",
        "correct_answer": "They grow taller every year and make seeds.",
    }
    assert text_strongly_grounded_in_fact(
        "They respire to release energy from food.", focus
    )
    assert pack_matches_focus_fact(drifted, focus) is False
    grounded = {
        "question": "According to the lesson, why do living things respire?",
        "correct_answer": "To release energy from food.",
    }
    assert pack_matches_focus_fact(grounded, focus) is True


def test_pack_matches_taught_rejects_bank_off_board() -> None:
    from app.services.handlers.teaching_transcript_service import pack_matches_taught

    taught = {
        "teaching_facts": [
            "Living things grow over time.",
            "Living things reproduce to make offspring.",
        ],
        "step_count": 2,
    }
    bank_off_board = {
        "question": "Which statement about photosynthesis is correct?",
        "options": [
            "Plants make food using sunlight in chloroplasts.",
            "Rocks produce sugar from light.",
            "Animals photosynthesize at night.",
            "Water is never involved.",
        ],
        "correct_answer": "Plants make food using sunlight in chloroplasts.",
        "type": "mcq",
    }
    assert (
        pack_matches_taught(bank_off_board, taught, required_type="mcq") is False
    )
    bank_on_board = {
        "question": "According to the lesson, which statement about living things is correct?",
        "options": [
            "Living things grow over time.",
            "Living things never change size.",
            "Living things cannot reproduce.",
            "Only rocks are living.",
        ],
        "correct_answer": "Living things grow over time.",
        "type": "mcq",
    }
    assert pack_matches_taught(bank_on_board, taught, required_type="mcq") is True


def test_rule_based_fill_in_blanks_content_word_not_pronoun() -> None:
    from app.services.handlers.teaching_transcript_service import (
        build_rule_based_pack_from_focus,
    )

    focus = (
        "Because humans are living, they can move on their own "
        "and take care of themselves."
    )
    pack = build_rule_based_pack_from_focus(
        focus_fact=focus,
        archetype="term_blank",
        question_type="fill_in_blank",
        concept="Living things",
        index=2,
        taught_ctx={"teaching_facts": [focus]},
    )
    assert pack is not None
    assert pack["type"] == "fill_in_blank"
    assert "_____" in pack["question"]
    assert pack["correct_answer"].lower() != "themselves"
    assert pack["correct_answer"].lower() not in {"own", "things", "their"}


def test_rule_based_descriptive_from_focus() -> None:
    from app.services.handlers.teaching_transcript_service import (
        build_rule_based_pack_from_focus,
    )

    focus = "Living things grow over time."
    pack = build_rule_based_pack_from_focus(
        focus_fact=focus,
        archetype="explain_own_words",
        question_type="descriptive",
        concept="Living things",
        index=0,
        taught_ctx={},
    )
    assert pack is not None
    assert pack["type"] == "descriptive"
    assert focus in pack["correct_answer"]


def test_is_meta_instruction_text_filters_ui_and_zone0() -> None:
    from app.services.handlers.teaching_transcript_service import is_meta_instruction_text

    assert is_meta_instruction_text(
        "Follow along on the board — when you're ready, answer the question in chat."
    )
    assert is_meta_instruction_text(
        "According to the lesson, what is the purpose of warm-up questions about living things?"
    )
    assert is_meta_instruction_text(
        "When exploring living things, you should follow along on the whiteboard and answer in chat."
    )
    assert not is_meta_instruction_text(
        "Living things grow over time and reproduce to make offspring."
    )
    assert is_meta_instruction_text(
        "That captures the full idea we talked about today."
    )
    assert is_meta_instruction_text(
        "You've nailed the big idea right from the beginning."
    )


def test_is_meta_quiz_question_rejects_lesson_phrase_stem() -> None:
    from app.services.handlers.teaching_transcript_service import is_meta_quiz_question

    assert is_meta_quiz_question(
        "What does the lesson mean when it says 'That captures the full idea we talked about today'?"
    )
    assert is_meta_quiz_question(
        "What does the teacher mean when they say, 'You've nailed the big idea right from the beginning'?"
    )


def test_is_broad_quiz_stem_rejects_main_topic() -> None:
    from app.services.handlers.concept_taught_context import is_broad_quiz_stem

    assert is_broad_quiz_stem("What is the main topic of today's lesson?")


def test_format_transcript_taught_block_omits_session_meta() -> None:
    from app.services.handlers.teaching_transcript_service import (
        format_transcript_taught_block,
    )

    block = format_transcript_taught_block(
        {
            "teaching_transcript": "Living things grow over time.",
            "lesson_excerpt": "You've nailed the big idea right from the beginning.",
            "taught_points": ["warm-up chat line"],
        }
    )
    assert "Living things grow" in block
    assert "nailed the big idea" not in block
    assert "warm-up" not in block


def test_format_grading_context_block_includes_transcript() -> None:
    from app.services.handlers.concept_taught_context import format_grading_context_block

    ctx = {
        "teaching_transcript": "Living things grow over time. They reproduce to make offspring.",
        "teaching_facts": [
            "Living things grow over time.",
            "They reproduce to make offspring.",
        ],
        "step_count": 2,
    }
    block = format_grading_context_block(ctx)
    assert "FULL LESSON TAUGHT" in block
    assert "grow over time" in block
    assert "Facts taught (2)" in block


def test_extract_teaching_facts_skips_meta_ui_lines() -> None:
    transcript = (
        "Follow along on the board — when you're ready, answer the question in chat. "
        "Living things grow over time. "
        "They reproduce to make offspring."
    )
    facts = extract_teaching_facts(transcript)
    assert facts
    assert all("follow along" not in f.lower() for f in facts)
    assert any("grow" in f.lower() for f in facts)


def test_pack_matches_taught_rejects_meta_question() -> None:
    from app.services.handlers.teaching_transcript_service import pack_matches_taught

    taught = {
        "teaching_facts": ["Living things grow over time."],
        "step_count": 1,
    }
    pack = {
        "question": "What is the purpose of warm-up questions about living things?",
        "correct_answer": "They are not a test.",
        "options": [],
    }
    assert pack_matches_taught(pack, taught, required_type="descriptive") is False


def test_merge_transcript_sets_fact_count() -> None:
    transcript = (
        "Living things grow over time. "
        "They reproduce to make offspring. "
        "They respire to release energy."
    )
    ctx = merge_transcript_into_taught_context({"steps": [], "step_count": 0}, transcript)
    assert len(ctx["teaching_facts"]) >= 2
    assert ctx["step_count"] == len(ctx["teaching_facts"])
    assert fact_key(ctx["teaching_facts"][0])
