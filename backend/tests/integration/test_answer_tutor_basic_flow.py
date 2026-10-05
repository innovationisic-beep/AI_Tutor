"""
Integration tests: basic ask → response flow via HTTP.

Current personal-session bootstrap:

    cluster curiosity (not persisted to chat)
    → zone0_anchor (also not persisted to chat — intentional)
    → later teaching turns may persist assistant rows

All tests mock DeepSeek via pytest-httpx.
"""

import pytest
from httpx import AsyncClient

from tests.conftest import DEEPSEEK_URL, deepseek_response
from tests.helpers import (
    advance_to_zone0_anchor,
    ask_payload,
    assert_response_ok,
    reload_session,
)


CURIOSITY_CONTENT = (
    "Have you ever wondered how a plant makes its own food? "
    "Let's explore that today?"
)
ANCHOR_CONTENT = (
    "Welcome to photosynthesis! Let's start by connecting what you already know "
    "about how plants get their energy. Think about a sunny day?"
)


# ─────────────────────────────────────────────────────────────────────────────
# Basic response structure
# ─────────────────────────────────────────────────────────────────────────────

class TestBasicAskFlow:
    async def test_bootstrap_dot_returns_200(
        self, client: AsyncClient, session, httpx_mock
    ):
        """POST /sessions/ask with '.' returns HTTP 200."""
        httpx_mock.add_response(
            url=DEEPSEEK_URL,
            json=deepseek_response(CURIOSITY_CONTENT),
        )
        resp = await client.post(
            "/sessions/ask",
            json=ask_payload(session.id, "."),
        )
        assert resp.status_code == 200

    async def test_bootstrap_returns_typed_dict(
        self, client: AsyncClient, session, httpx_mock
    ):
        """
        Bootstrap '.' on a fresh personal session returns cluster_curiosity_prompt
        (pedagogy layer before Zone 0).
        """
        httpx_mock.add_response(
            url=DEEPSEEK_URL,
            json=deepseek_response(CURIOSITY_CONTENT),
        )
        body = assert_response_ok(
            await client.post("/sessions/ask", json=ask_payload(session.id, ".")),
            expected_type="cluster_curiosity_prompt",
        )
        answer_text = body.get("answer") or body.get("message") or ""
        assert len(answer_text) > 0, "Expected non-empty curiosity message"

    async def test_response_has_required_fields(
        self, client: AsyncClient, session, httpx_mock
    ):
        """AskQuestionResponse must include 'answer'/'message' and 'type'."""
        httpx_mock.add_response(
            url=DEEPSEEK_URL,
            json=deepseek_response(CURIOSITY_CONTENT),
        )
        resp = await client.post("/sessions/ask", json=ask_payload(session.id, "."))
        body = resp.json()
        assert "answer" in body or "message" in body
        assert "type" in body

    async def test_dot_message_not_persisted(
        self, client: AsyncClient, session, httpx_mock
    ):
        """The bootstrap '.' message must NOT be saved as a user chat row."""
        httpx_mock.add_response(
            url=DEEPSEEK_URL,
            json=deepseek_response(CURIOSITY_CONTENT),
        )
        await client.post("/sessions/ask", json=ask_payload(session.id, "."))

        from app.models.learning.messages import SessionChatMessage

        user_msgs = await SessionChatMessage.find(
            {"session_id": session.id, "role": "user"}
        ).to_list()
        dot_msgs = [m for m in user_msgs if m.content.strip() == "."]
        assert dot_msgs == [], "The '.' bootstrap message must not be persisted"

    async def test_cluster_curiosity_assistant_not_persisted_to_chat(
        self, client: AsyncClient, session, httpx_mock
    ):
        """
        Pedagogy cluster-curiosity turns are intentionally excluded from
        session_chat_messages (same policy as zone0_anchor).
        """
        httpx_mock.add_response(
            url=DEEPSEEK_URL,
            json=deepseek_response(CURIOSITY_CONTENT),
        )
        await client.post("/sessions/ask", json=ask_payload(session.id, "."))

        from app.models.learning.messages import SessionChatMessage

        assistant_msgs = await SessionChatMessage.find(
            {"session_id": session.id, "role": "assistant"}
        ).to_list()
        assert assistant_msgs == [], (
            "cluster_curiosity_prompt must not be persisted as assistant chat"
        )

    async def test_zone0_anchor_reachable_after_curiosity(
        self, client: AsyncClient, session, httpx_mock
    ):
        """After pedagogy curiosity completes, Zone 0 anchor still runs."""
        body = await advance_to_zone0_anchor(
            client,
            session.id,
            httpx_mock,
            deepseek_url=DEEPSEEK_URL,
            deepseek_response_fn=deepseek_response,
            anchor_text=ANCHOR_CONTENT,
        )
        assert (body.get("answer") or body.get("message") or "").strip()

    async def test_real_question_is_persisted(
        self, client: AsyncClient, session, httpx_mock
    ):
        """
        A real typed question (not '.', not '__action:*') must be saved
        as a 'user' role message once Zone 0 is waiting for chat.
        """
        await advance_to_zone0_anchor(
            client,
            session.id,
            httpx_mock,
            deepseek_url=DEEPSEEK_URL,
            deepseek_response_fn=deepseek_response,
            anchor_text=ANCHOR_CONTENT,
        )
        # Real chat after anchor: mirror + Zone 0 curiosity (2 LLM calls).
        httpx_mock.add_response(
            url=DEEPSEEK_URL,
            json=deepseek_response("Good image — that helps frame your thinking."),
        )
        httpx_mock.add_response(
            url=DEEPSEEK_URL,
            json=deepseek_response("What do you think this process needs from the air?"),
        )
        real_question = "What is the light reaction exactly?"
        await client.post("/sessions/ask", json=ask_payload(session.id, real_question))

        from app.models.learning.messages import SessionChatMessage

        user_msgs = await SessionChatMessage.find(
            {"session_id": session.id, "role": "user"}
        ).to_list()
        contents = [m.content for m in user_msgs]
        assert real_question in contents, (
            f"Expected user message '{real_question}' in persisted messages. "
            f"Found: {contents}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Error handling
# ─────────────────────────────────────────────────────────────────────────────

class TestAskErrorHandling:
    async def test_unknown_session_id_returns_400(
        self, client: AsyncClient, db
    ):
        from beanie.odm.fields import PydanticObjectId

        fake_id = str(PydanticObjectId())
        resp = await client.post(
            "/sessions/ask",
            json={"session_id": fake_id, "question": "Hello"},
        )
        assert resp.status_code == 400

    async def test_empty_question_returns_422(
        self, client: AsyncClient, session
    ):
        resp = await client.post(
            "/sessions/ask",
            json={"session_id": str(session.id), "question": ""},
        )
        assert resp.status_code == 422

    async def test_action_message_not_persisted(
        self, client: AsyncClient, session, httpx_mock
    ):
        """__action:* messages must NOT appear as user chat rows."""
        await advance_to_zone0_anchor(
            client,
            session.id,
            httpx_mock,
            deepseek_url=DEEPSEEK_URL,
            deepseek_response_fn=deepseek_response,
            anchor_text=ANCHOR_CONTENT,
        )
        httpx_mock.add_response(
            url=DEEPSEEK_URL, json=deepseek_response("Prereq question?")
        )
        await client.post(
            "/sessions/ask",
            json=ask_payload(session.id, "__action:zone0_next"),
        )

        from app.models.learning.messages import SessionChatMessage

        user_msgs = await SessionChatMessage.find(
            {"session_id": session.id, "role": "user"}
        ).to_list()
        action_msgs = [m for m in user_msgs if m.content.startswith("__action:")]
        assert action_msgs == [], (
            "__action: messages must not be persisted as user messages"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Session state after ask
# ─────────────────────────────────────────────────────────────────────────────

class TestSessionStateAfterAsk:
    async def test_zone0_phase_advances_after_anchor(
        self, client: AsyncClient, session, httpx_mock
    ):
        """After zone0_anchor, zone0_phase advances to 'anchor_wait'."""
        await advance_to_zone0_anchor(
            client,
            session.id,
            httpx_mock,
            deepseek_url=DEEPSEEK_URL,
            deepseek_response_fn=deepseek_response,
            anchor_text=ANCHOR_CONTENT,
        )
        reloaded = await reload_session(session.id)
        assert reloaded.zone0_phase == "anchor_wait", (
            f"Expected zone0_phase='anchor_wait' after anchor, got '{reloaded.zone0_phase}'"
        )

    async def test_session_still_in_progress_after_single_ask(
        self, client: AsyncClient, session, httpx_mock
    ):
        """A single ask must not complete or abandon the session."""
        httpx_mock.add_response(
            url=DEEPSEEK_URL,
            json=deepseek_response(CURIOSITY_CONTENT),
        )
        await client.post("/sessions/ask", json=ask_payload(session.id, "."))
        reloaded = await reload_session(session.id)
        assert reloaded.completion_status == "in_progress"
