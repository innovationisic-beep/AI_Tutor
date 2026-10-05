"""
Integration tests: Zone 0 state-machine after pedagogy layers.

Current personal-session order (authoritative):

    Pedagogy intro (often auto-skipped when empty)
    → cluster curiosity prompt / feedback / done
    → Zone 0 anchor → prereq → Zone 0 curiosity → ready → Zone 1

Zone 0 itself is unchanged once pedagogy is complete.
"""

import pytest
from httpx import AsyncClient

from tests.conftest import DEEPSEEK_URL, deepseek_response
from tests.helpers import (
    advance_to_zone0_anchor,
    ask_payload,
    assert_response_ok,
    reload_session,
    seed_pedagogy_layers_complete,
)


# ─────────────────────────────────────────────────────────────────────────────
# Pedagogy bootstrap (before Zone 0)
# ─────────────────────────────────────────────────────────────────────────────

class TestPedagogyBeforeZone0:
    async def test_bootstrap_returns_cluster_curiosity_prompt(
        self, client: AsyncClient, session, httpx_mock
    ):
        """Fresh personal session starts with cluster curiosity, not zone0_anchor."""
        httpx_mock.add_response(
            url=DEEPSEEK_URL,
            json=deepseek_response(
                "Have you ever wondered how a plant makes its own food?"
            ),
        )
        body = assert_response_ok(
            await client.post("/sessions/ask", json=ask_payload(session.id, ".")),
            expected_type="cluster_curiosity_prompt",
        )
        answer = body.get("answer") or body.get("message") or ""
        assert len(answer.strip()) > 0

        reloaded = await reload_session(session.id)
        assert reloaded.flow_state == "pedagogy_cluster_curiosity"
        assert reloaded.zone0_phase == "anchoring"
        assert reloaded.current_zone == 0


# ─────────────────────────────────────────────────────────────────────────────
# Phase 1: anchoring → anchor_wait (after pedagogy)
# ─────────────────────────────────────────────────────────────────────────────

class TestZone0Anchoring:
    async def test_zone0_anchor_runs_after_cluster_curiosity(
        self, client: AsyncClient, session, httpx_mock
    ):
        """Completing cluster curiosity emits type='zone0_anchor' in the same turn."""
        body = await advance_to_zone0_anchor(
            client,
            session.id,
            httpx_mock,
            deepseek_url=DEEPSEEK_URL,
            deepseek_response_fn=deepseek_response,
            anchor_text=(
                "Have you ever wondered how a plant makes its own food? "
                "Let's explore that today."
            ),
        )
        answer = body.get("answer") or body.get("message") or ""
        assert len(answer.strip()) > 0, "zone0_anchor must contain a non-empty message"

    async def test_zone0_phase_becomes_anchor_wait_after_anchor(
        self, client: AsyncClient, session, httpx_mock
    ):
        """After anchor delivery, session.zone0_phase must be 'anchor_wait'."""
        await advance_to_zone0_anchor(
            client,
            session.id,
            httpx_mock,
            deepseek_url=DEEPSEEK_URL,
            deepseek_response_fn=deepseek_response,
            anchor_text="Great anchor text here.",
        )
        reloaded = await reload_session(session.id)
        assert reloaded.zone0_phase == "anchor_wait"

    async def test_current_zone_still_0_after_anchor(
        self, client: AsyncClient, session, httpx_mock
    ):
        """Zone does not advance to 1 after just the anchor — it stays at 0."""
        await advance_to_zone0_anchor(
            client,
            session.id,
            httpx_mock,
            deepseek_url=DEEPSEEK_URL,
            deepseek_response_fn=deepseek_response,
            anchor_text="Anchor message.",
        )
        reloaded = await reload_session(session.id)
        assert reloaded.current_zone == 0

    async def test_flow_state_after_anchor(
        self, client: AsyncClient, session, httpx_mock
    ):
        """After the anchor, flow_state must still be 'idle' (waiting for chat)."""
        await advance_to_zone0_anchor(
            client,
            session.id,
            httpx_mock,
            deepseek_url=DEEPSEEK_URL,
            deepseek_response_fn=deepseek_response,
            anchor_text="Anchor message.",
        )
        reloaded = await reload_session(session.id)
        assert reloaded.flow_state == "idle"


# ─────────────────────────────────────────────────────────────────────────────
# Phase 2: zone0_next → curiosity question
# ─────────────────────────────────────────────────────────────────────────────

class TestZone0Prereq:
    @pytest.fixture
    async def anchored_session(self, client: AsyncClient, session, httpx_mock):
        """Advance through pedagogy + Zone 0 anchor → zone0_phase='anchor_wait'."""
        await advance_to_zone0_anchor(
            client,
            session.id,
            httpx_mock,
            deepseek_url=DEEPSEEK_URL,
            deepseek_response_fn=deepseek_response,
            anchor_text="Connecting to your prior knowledge...",
        )
        return session

    async def test_zone0_next_returns_zone0_curiosity_type(
        self, client: AsyncClient, anchored_session, httpx_mock
    ):
        """
        After anchor, '__action:zone0_next' returns type='zone0_curiosity'.
        With no prereqs, curiosity is returned in that same step.
        """
        httpx_mock.add_response(
            url=DEEPSEEK_URL,
            json=deepseek_response("Can you recall what chlorophyll does?"),
        )
        body = assert_response_ok(
            await client.post(
                "/sessions/ask",
                json=ask_payload(anchored_session.id, "__action:zone0_next"),
            ),
            expected_type="zone0_curiosity",
        )
        answer = body.get("answer") or body.get("message") or ""
        assert len(answer.strip()) > 0

    async def test_flow_state_is_zone0_curiosity_after_action(
        self, client: AsyncClient, anchored_session, httpx_mock
    ):
        """After __action:zone0_next, session.flow_state must be 'zone0_curiosity'."""
        httpx_mock.add_response(
            url=DEEPSEEK_URL,
            json=deepseek_response("Can you recall what chlorophyll does?"),
        )
        await client.post(
            "/sessions/ask",
            json=ask_payload(anchored_session.id, "__action:zone0_next"),
        )
        reloaded = await reload_session(anchored_session.id)
        assert reloaded.flow_state == "zone0_curiosity"

    async def test_zone0_phase_is_curiosity_wait_after_zone0_next(
        self, client: AsyncClient, anchored_session, httpx_mock
    ):
        """After __action:zone0_next, zone0_phase becomes 'curiosity_wait'."""
        httpx_mock.add_response(
            url=DEEPSEEK_URL,
            json=deepseek_response("Can you recall what chlorophyll does?"),
        )
        await client.post(
            "/sessions/ask",
            json=ask_payload(anchored_session.id, "__action:zone0_next"),
        )
        reloaded = await reload_session(anchored_session.id)
        assert reloaded.zone0_phase == "curiosity_wait"
        assert reloaded.zone0_prereq_done is True
        assert (reloaded.zone0_curiosity_question or "").strip() != ""

    async def test_substantive_chat_after_anchor_emits_mirror_then_q2(
        self, client: AsyncClient, anchored_session, httpx_mock
    ):
        """
        Substantive anchor reply → zone0_mirror (notes), then zone0_mirror_done → bare Q2.
        """
        httpx_mock.add_response(
            url=DEEPSEEK_URL,
            json=deepseek_response(
                '{"text": "Sunlight on your garden plants is a lovely image.",'
                ' "note": "Garden sunlight spark"}'
            ),
        )
        mirror_body = assert_response_ok(
            await client.post(
                "/sessions/ask",
                json=ask_payload(
                    anchored_session.id,
                    "I picture sunlight on my plants in the garden.",
                ),
            ),
            expected_type="zone0_mirror",
        )
        mirror_msg = (mirror_body.get("answer") or mirror_body.get("message") or "").strip()
        assert "sunlight" in mirror_msg.lower() or "garden" in mirror_msg.lower()
        assert mirror_body.get("writing_mode") == "notes"
        assert "?" not in mirror_msg or mirror_body.get("display_text") is not None
        reloaded = await reload_session(anchored_session.id)
        assert reloaded.zone0_phase == "curiosity_pending"

        httpx_mock.add_response(
            url=DEEPSEEK_URL,
            json=deepseek_response(
                "If plants make their own food, why do they still need water from the soil?"
            ),
        )
        q2_body = assert_response_ok(
            await client.post(
                "/sessions/ask",
                json=ask_payload(anchored_session.id, "__action:zone0_mirror_done"),
            ),
            expected_type="zone0_curiosity",
        )
        q2 = (q2_body.get("answer") or q2_body.get("message") or "").strip()
        assert "?" in q2
        assert not q2_body.get("buttons")
        assert q2_body.get("writing_mode") in (None, "legacy")
        reloaded2 = await reload_session(anchored_session.id)
        assert reloaded2.zone0_phase == "curiosity_wait"

        # Idempotent: second mirror_done does not emit another Q2.
        dup = await client.post(
            "/sessions/ask",
            json=ask_payload(anchored_session.id, "__action:zone0_mirror_done"),
        )
        assert dup.status_code == 200
        dup_body = dup.json()
        assert (dup_body.get("type") or "") in ("noop", None) or not (
            dup_body.get("message") or ""
        ).strip() or dup_body.get("type") == "noop"
        reloaded3 = await reload_session(anchored_session.id)
        assert reloaded3.zone0_phase == "curiosity_wait"

# ─────────────────────────────────────────────────────────────────────────────
# Phase 3: curiosity answer
# ─────────────────────────────────────────────────────────────────────────────

class TestZone0PrereqAnswer:
    @pytest.fixture
    async def prereq_session(self, client: AsyncClient, session, httpx_mock):
        """Advance to zone0_curiosity / curiosity_wait."""
        await advance_to_zone0_anchor(
            client,
            session.id,
            httpx_mock,
            deepseek_url=DEEPSEEK_URL,
            deepseek_response_fn=deepseek_response,
            anchor_text="Anchor text.",
        )
        httpx_mock.add_response(
            url=DEEPSEEK_URL,
            json=deepseek_response("What do plants need to make food?"),
        )
        await client.post(
            "/sessions/ask",
            json=ask_payload(session.id, "__action:zone0_next"),
        )
        return session

    async def test_curiosity_answer_returns_200(
        self, client: AsyncClient, prereq_session, httpx_mock
    ):
        """Answering curiosity returns zone0_curiosity with a ready button."""
        httpx_mock.add_response(
            url=DEEPSEEK_URL,
            json=deepseek_response(
                '{"text": "You named the key ingredients plants draw on.\\n\\n'
                'When you\'re ready to start, tap the button below.",'
                ' "note": "Ready when you are"}'
            ),
        )
        body = assert_response_ok(
            await client.post(
                "/sessions/ask",
                json=ask_payload(
                    prereq_session.id,
                    "Plants need sunlight, water, and carbon dioxide.",
                ),
            ),
            expected_type="zone0_curiosity",
        )
        answer = body.get("answer") or body.get("message") or ""
        assert "key ingredients" in answer
        assert body.get("writing_mode") == "notes"
        assert body.get("display_text") == "Ready when you are"
        assert answer != body.get("display_text")
        buttons = body.get("buttons") or []
        assert any(b.get("id") == "zone0_ready" for b in buttons)

    async def test_curiosity_answer_plain_text_stays_legacy(
        self, client: AsyncClient, prereq_session, httpx_mock
    ):
        """Invalid/plain LLM prose falls back to legacy (speech = display)."""
        httpx_mock.add_response(
            url=DEEPSEEK_URL,
            json=deepseek_response(
                "You named the key ingredients plants draw on.\n\n"
                "When you're ready to start, tap the button below."
            ),
        )
        body = assert_response_ok(
            await client.post(
                "/sessions/ask",
                json=ask_payload(
                    prereq_session.id,
                    "Sunlight and water matter a lot.",
                ),
            ),
            expected_type="zone0_curiosity",
        )
        assert body.get("writing_mode") in (None, "legacy")
        assert not body.get("display_text")
        answer = body.get("answer") or body.get("message") or ""
        assert "key ingredients" in answer

    async def test_anchor_question_stays_legacy_speech_equals_display(
        self, client: AsyncClient, session, httpx_mock
    ):
        """Structured Q1 never gets a shortened display_text note."""
        body = await advance_to_zone0_anchor(
            client,
            session.id,
            httpx_mock,
            deepseek_url=DEEPSEEK_URL,
            deepseek_response_fn=deepseek_response,
            anchor_text="What do you picture when you hear photosynthesis?",
        )
        assert body.get("type") == "zone0_anchor"
        msg = body.get("answer") or body.get("message") or ""
        assert "photosynthesis" in msg.lower()
        assert body.get("writing_mode") in (None, "legacy")
        assert body.get("display_text") in (None, "")

    async def test_zone0_prereq_done_after_answer(
        self, client: AsyncClient, prereq_session, httpx_mock
    ):
        """After answering the curiosity question, zone0_prereq_done stays True."""
        httpx_mock.add_response(
            url=DEEPSEEK_URL,
            json=deepseek_response(
                "Sunlight is a big piece of the puzzle.\n\n"
                "Tap below when you want to start the lesson."
            ),
        )
        await client.post(
            "/sessions/ask",
            json=ask_payload(
                prereq_session.id,
                "Sunlight, water, and CO2 are needed.",
            ),
        )
        reloaded = await reload_session(prereq_session.id)
        assert reloaded.zone0_prereq_done is True

    async def test_flow_state_stays_zone0_curiosity_after_q2_answer(
        self, client: AsyncClient, prereq_session, httpx_mock
    ):
        """After answering Q2, flow_state stays zone0_curiosity until ready."""
        httpx_mock.add_response(
            url=DEEPSEEK_URL,
            json=deepseek_response(
                "Starting from sunlight makes sense.\n\n"
                "Ready to begin? Use the button below when you like."
            ),
        )
        await client.post(
            "/sessions/ask",
            json=ask_payload(prereq_session.id, "I think plants need sunlight only."),
        )
        reloaded = await reload_session(prereq_session.id)
        assert reloaded.flow_state == "zone0_curiosity"
        assert reloaded.zone0_phase == "curiosity_ready"


# ─────────────────────────────────────────────────────────────────────────────
# Phase 4: ready → Zone 1
# ─────────────────────────────────────────────────────────────────────────────

class TestZone0CuriosityToZone1:
    @pytest.fixture
    async def curiosity_session(self, client: AsyncClient, session, httpx_mock):
        """Advance to zone0_curiosity / curiosity_wait (Q2 unanswered)."""
        await advance_to_zone0_anchor(
            client,
            session.id,
            httpx_mock,
            deepseek_url=DEEPSEEK_URL,
            deepseek_response_fn=deepseek_response,
            anchor_text="Anchor.",
        )
        httpx_mock.add_response(
            url=DEEPSEEK_URL, json=deepseek_response("What are you curious about?")
        )
        await client.post(
            "/sessions/ask", json=ask_payload(session.id, "__action:zone0_next")
        )
        return session

    async def test_curiosity_response_advances_to_zone1(
        self, client: AsyncClient, curiosity_session, httpx_mock
    ):
        """Q2 answer waits for ready; __action:zone0_ready moves to Zone 1."""
        httpx_mock.add_response(
            url=DEEPSEEK_URL,
            json=deepseek_response(
                "Leaves and light are a great thread to pull on.\n\n"
                "When you're ready, tap the button below to start."
            ),
        )
        await client.post(
            "/sessions/ask",
            json=ask_payload(
                curiosity_session.id,
                "I'm curious about how leaves capture light.",
            ),
        )
        mid = await reload_session(curiosity_session.id)
        assert mid.current_zone == 0
        assert mid.zone0_phase == "curiosity_ready"

        await client.post(
            "/sessions/ask",
            json=ask_payload(curiosity_session.id, "__action:zone0_ready"),
        )
        reloaded = await reload_session(curiosity_session.id)
        assert reloaded.current_zone == 1
        assert reloaded.zone0_phase == "done"

    async def test_flow_state_idle_after_zone1_entry(
        self, client: AsyncClient, curiosity_session, httpx_mock
    ):
        """After ready confirm completes Zone 0, flow_state returns to 'idle'."""
        httpx_mock.add_response(
            url=DEEPSEEK_URL,
            json=deepseek_response(
                "Enthusiasm helps.\n\n"
                "Tap the button below when you want to begin."
            ),
        )
        await client.post(
            "/sessions/ask",
            json=ask_payload(curiosity_session.id, "I want to learn everything!"),
        )
        await client.post(
            "/sessions/ask",
            json=ask_payload(curiosity_session.id, "__action:zone0_ready"),
        )
        reloaded = await reload_session(curiosity_session.id)
        assert reloaded.flow_state == "idle"

    async def test_skip_action_bypasses_zone0_when_pedagogy_is_done(
        self, client: AsyncClient, session
    ):
        """
        __action:skip during Zone 0 (after pedagogy is complete, before/at
        anchoring) jumps to Zone 1. No DeepSeek call — pure state-machine.

        Pedagogy is seeded complete so skip reaches the Zone 0 intercept
        (on a fresh personal session, the first ask would emit cluster curiosity).
        """
        await seed_pedagogy_layers_complete(session)
        session.zone0_phase = "anchoring"
        await session.save()

        resp = await client.post(
            "/sessions/ask",
            json=ask_payload(session.id, "__action:skip"),
        )
        assert resp.status_code == 200

        reloaded = await reload_session(session.id)
        assert reloaded.current_zone == 1
        assert reloaded.zone0_phase == "done"


# ─────────────────────────────────────────────────────────────────────────────
# Zone 0 regression: already-done sessions must not re-enter Zone 0
# ─────────────────────────────────────────────────────────────────────────────

class TestZone0NoReEntry:
    async def test_zone1_session_does_not_re_enter_zone0(
        self, client: AsyncClient, session
    ):
        """
        If a session is already at Zone 1 (zone0_phase='done'), any message
        must NOT return type='zone0_anchor'.
        """
        await seed_pedagogy_layers_complete(session)
        session.zone0_phase = "anchoring"
        await session.save()

        await client.post(
            "/sessions/ask",
            json=ask_payload(session.id, "__action:skip"),
        )

        resp = await client.post(
            "/sessions/ask", json=ask_payload(session.id, ".")
        )
        body = resp.json()
        response_type = body.get("type", "")
        assert response_type != "zone0_anchor", (
            f"Zone 1 session must not return zone0_anchor. Got type='{response_type}'"
        )
