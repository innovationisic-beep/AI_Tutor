"""
Shared test helper utilities.

Keep this file import-free of app modules so it can be safely imported
anywhere in the test suite without triggering Beanie initialisation.
"""

from __future__ import annotations

from typing import Any

from beanie.odm.fields import PydanticObjectId


# Minimal valid authored VTSE template for classroom publish fixtures.
MINIMAL_VTSE_TEMPLATE: dict[str, Any] = {
    "strategy_id": "clustered_trait_list",
    "version": 1,
    "payload": {
        "steps": [
            {"label": "Trait A", "summary": "First teaching point."},
            {"label": "Trait B", "summary": "Second teaching point."},
            {"label": "Trait C", "summary": "Third teaching point."},
        ]
    },
}


# ─────────────────────────────────────────────────────────────────────────────
# Session snapshot helpers
# ─────────────────────────────────────────────────────────────────────────────

async def reload_session(session_id: PydanticObjectId):
    """Return a freshly loaded Session from mongomock (reflects latest saves)."""
    from app.models.learning.sessions import Session

    s = await Session.get(session_id)
    assert s is not None, f"Session {session_id} not found after reload"
    return s


def assert_session_fields(session: Any, **expected: Any) -> None:
    """
    Assert that a session (or any object) has the given field values.
    Raises AssertionError with a helpful message on first mismatch.
    """
    for field, want in expected.items():
        got = getattr(session, field, "<MISSING>")
        assert got == want, (
            f"session.{field}: expected {want!r}, got {got!r}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# HTTP response helpers
# ─────────────────────────────────────────────────────────────────────────────

def assert_response_ok(response: Any, *, expected_type: str | None = None) -> dict:
    """
    Assert the HTTP response is 200 and return the parsed JSON body.
    Optionally assert the `type` field in the body matches expected_type.
    """
    assert response.status_code == 200, (
        f"Expected 200, got {response.status_code}. Body: {response.text}"
    )
    body: dict = response.json()
    if expected_type is not None:
        got_type = body.get("type")
        assert got_type == expected_type, (
            f"Response type: expected {expected_type!r}, got {got_type!r}. "
            f"Full body: {body}"
        )
    return body


def ask_payload(session_id: str | PydanticObjectId, question: str) -> dict:
    """Build the JSON body for POST /sessions/ask."""
    return {"session_id": str(session_id), "question": question}


async def seed_pedagogy_layers_complete(session: Any) -> None:
    """
    Mark pedagogy intro / recall / cluster curiosity complete without HTTP.

    Leaves flow idle and zone0_phase at anchoring so Zone 0 can run next.
    Used when a test needs Zone 0 in isolation (e.g. skip before anchor emit).
    """
    session.pedagogy_session_intro_done = True
    session.pedagogy_session_recall_done = True
    session.pedagogy_cluster_intro_done_for = int(
        getattr(session, "current_cluster_index", 0) or 0
    )
    session.pedagogy_cluster_curiosity_done_for = int(
        getattr(session, "current_cluster_index", 0) or 0
    )
    session.flow_state = "idle"
    if not str(getattr(session, "zone0_phase", "") or "").strip():
        session.zone0_phase = "anchoring"
    await session.save()


async def advance_to_zone0_anchor(
    client: Any,
    session_id: str | PydanticObjectId,
    httpx_mock: Any,
    *,
    deepseek_url: str,
    deepseek_response_fn: Any,
    anchor_text: str = "Have you ever wondered how a plant makes its own food?",
) -> dict:
    """
    Walk personal-session bootstrap through cluster curiosity into Zone 0 anchor.

    Call counts (DeepSeek):
      1) cluster curiosity prompt
      2) cluster curiosity appreciation
      3) zone0_anchor narration  (same request as cluster_curiosity_done)

    Returns the zone0_anchor response body.
    """
    httpx_mock.add_response(
        url=deepseek_url,
        json=deepseek_response_fn(
            "Have you ever wondered how a plant makes its own food?"
        ),
    )
    assert_response_ok(
        await client.post("/sessions/ask", json=ask_payload(session_id, ".")),
        expected_type="cluster_curiosity_prompt",
    )

    httpx_mock.add_response(
        url=deepseek_url,
        json=deepseek_response_fn(
            "Sunlight on your garden plants is a lovely image — thanks for sharing that."
        ),
    )
    assert_response_ok(
        await client.post(
            "/sessions/ask",
            json=ask_payload(session_id, "I picture sunlight on my plants."),
        ),
        expected_type="cluster_curiosity_feedback",
    )

    # Completing curiosity returns None from pedagogy → Zone 0 emits anchor
    # in the same ask turn.
    httpx_mock.add_response(
        url=deepseek_url,
        json=deepseek_response_fn(anchor_text),
    )
    body = assert_response_ok(
        await client.post(
            "/sessions/ask",
            json=ask_payload(session_id, "__action:cluster_curiosity_done"),
        ),
        expected_type="zone0_anchor",
    )

    session = await reload_session(session_id)
    assert session.zone0_phase == "anchor_wait"
    assert int(session.current_zone or 0) == 0
    return body


async def advance_past_cluster_curiosity(
    client: Any,
    session_id: str | PydanticObjectId,
    httpx_mock: Any,
    *,
    deepseek_url: str,
    deepseek_response_fn: Any,
) -> None:
    """Compatibility alias: ends at zone0_anchor / anchor_wait."""
    await advance_to_zone0_anchor(
        client,
        session_id,
        httpx_mock,
        deepseek_url=deepseek_url,
        deepseek_response_fn=deepseek_response_fn,
    )


# ─────────────────────────────────────────────────────────────────────────────
# mongomock-motor index caveat guard
# ─────────────────────────────────────────────────────────────────────────────

MONGOMOCK_INDEX_WARNING = (
    "mongomock-motor does not enforce partial unique indexes. "
    "This test validates duplicate prevention via explicit logic, not DB constraints."
)
