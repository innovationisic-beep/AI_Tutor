"""Visual Teaching planner must use the same DeepSeek URL/key as Story Hook."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.config import Settings
from app.services.visual_teaching.planner import _call_deepseek


@pytest.mark.asyncio
async def test_visual_teaching_planner_uses_settings_deepseek_api_url(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    posted: dict = {}

    class _Resp:
        status_code = 200
        text = ""

        def json(self):
            return {"choices": [{"message": {"content": '{"ok":true}'}}]}

        def raise_for_status(self):
            return None

    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, url, headers=None, json=None):
            posted["url"] = url
            posted["headers"] = headers
            posted["json"] = json
            return _Resp()

    with patch("app.services.visual_teaching.planner.httpx.AsyncClient", _Client):
        out = await _call_deepseek(system="sys", user="usr", cfg=Settings())

    assert out == '{"ok":true}'
    assert posted["url"] == Settings.DEEPSEEK_API_URL
    assert "/v1/chat/completions" in posted["url"]
    assert posted["headers"]["Authorization"] == "Bearer test-key"
    assert posted["json"]["model"] == Settings.DEEPSEEK_MODEL


@pytest.mark.asyncio
async def test_visual_teaching_planner_requires_api_key(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    from app.services.visual_teaching.validate import VisualTeachingPlanError

    with pytest.raises(VisualTeachingPlanError, match="DEEPSEEK_API_KEY"):
        await _call_deepseek(system="sys", user="usr", cfg=Settings())
