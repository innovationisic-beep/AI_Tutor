"""Tests for LLM-generated correct-answer praise in concept questions."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.services.handlers.concept_question_orchestrator import (
    _generate_correct_feedback_on_board,
)


def _ctx() -> SimpleNamespace:
    return SimpleNamespace(topic_repository=AsyncMock())


@pytest.mark.asyncio
async def test_generate_correct_feedback_uses_llm_when_available() -> None:
    session = SimpleNamespace(
        current_concept="Living things",
        current_question="Name characteristics of living things.",
        topic_id="507f1f77bcf86cd799439011",
        organization_id="507f1f77bcf86cd799439099",
        student_id="507f1f77bcf86cd799439012",
    )
    llm_text = (
        "Nice — you named grow, breathe, and reproduce. "
        "Living things do all three, just as we covered on the board."
    )
    with patch(
        "app.services.handlers.concept_question_orchestrator._concept_check_board_rag_bundle",
        new_callable=AsyncMock,
        return_value=(AsyncMock(), "board context", None, SimpleNamespace()),
    ), patch(
        "app.services.handlers.concept_question_orchestrator.generate_tutor_rag_reply",
        new_callable=AsyncMock,
        return_value=llm_text,
    ):
        msg = await _generate_correct_feedback_on_board(
            ctx=_ctx(),
            session=session,
            session_id="507f1f77bcf86cd799439011",
            student_id="507f1f77bcf86cd799439012",
            topic=SimpleNamespace(),
            student_text="grow breathe and reproduce",
            reference="Living things grow, breathe, and reproduce.",
            question="Name characteristics of living things.",
            taught_ctx={
                "steps": [],
                "taught_points": ["Living things grow, breathe, and reproduce"],
            },
        )
    assert msg == llm_text
    assert "grow" in msg.lower()


@pytest.mark.asyncio
async def test_generate_correct_feedback_does_not_persist_internal_prompt() -> None:
    session = SimpleNamespace(
        current_concept="Living things",
        current_question="Name characteristics of living things.",
        topic_id="507f1f77bcf86cd799439011",
        organization_id="507f1f77bcf86cd799439099",
        student_id="507f1f77bcf86cd799439012",
    )
    mock_rag = AsyncMock(return_value="Great work on those traits.")
    with patch(
        "app.services.handlers.concept_question_orchestrator._concept_check_board_rag_bundle",
        new_callable=AsyncMock,
        return_value=(AsyncMock(), "board context", None, SimpleNamespace()),
    ), patch(
        "app.services.handlers.concept_question_orchestrator.generate_tutor_rag_reply",
        mock_rag,
    ):
        await _generate_correct_feedback_on_board(
            ctx=_ctx(),
            session=session,
            session_id="507f1f77bcf86cd799439011",
            student_id="507f1f77bcf86cd799439012",
            topic=SimpleNamespace(),
            student_text="grow breathe and reproduce",
            reference="Living things grow, breathe, and reproduce.",
            question="Name characteristics of living things.",
            taught_ctx={
                "steps": [],
                "taught_points": ["Living things grow, breathe, and reproduce"],
            },
        )
    mock_rag.assert_awaited_once()
    assert mock_rag.await_args.kwargs.get("persist_session_qa") is False


@pytest.mark.asyncio
async def test_generate_correct_feedback_falls_back_when_llm_empty() -> None:
    session = SimpleNamespace(
        current_concept="Living things",
        current_question="Tell one characteristic of living things.",
        topic_id="507f1f77bcf86cd799439011",
        organization_id="507f1f77bcf86cd799439099",
        student_id="507f1f77bcf86cd799439012",
    )
    with patch(
        "app.services.handlers.concept_question_orchestrator._concept_check_board_rag_bundle",
        new_callable=AsyncMock,
        return_value=(AsyncMock(), "board context", None, SimpleNamespace()),
    ), patch(
        "app.services.handlers.concept_question_orchestrator.generate_tutor_rag_reply",
        new_callable=AsyncMock,
        return_value="",
    ):
        msg = await _generate_correct_feedback_on_board(
            ctx=_ctx(),
            session=session,
            session_id="507f1f77bcf86cd799439011",
            student_id="507f1f77bcf86cd799439012",
            topic=SimpleNamespace(),
            student_text="grow",
            reference="They grow, breathe, and reproduce.",
            question="Tell one characteristic of living things.",
            taught_ctx={"steps": [], "taught_points": ["Living things grow over time"]},
        )
    assert "grow" in msg.lower()
    assert "answer key" not in msg.lower()
