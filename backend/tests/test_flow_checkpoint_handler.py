"""Tests for flow checkpoint runtime handler helpers."""

from __future__ import annotations

import pytest

from app.services.handlers.flow_checkpoint_handler import (
    parse_flow_checkpoint_pause_labels,
)


def test_parse_flow_checkpoint_pause_labels_json_suffix() -> None:
    raw = '__action:flow_checkpoint_pause|["Mouth", "Esophagus"]'
    assert parse_flow_checkpoint_pause_labels(raw) == ["Mouth", "Esophagus"]


def test_parse_flow_checkpoint_pause_labels_empty_when_missing() -> None:
    assert parse_flow_checkpoint_pause_labels("__action:flow_checkpoint_pause") == []
