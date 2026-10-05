"""Shared CIR / Zone 1 pedagogical capacity limits."""

from __future__ import annotations

# CIR v1 compile contract — raised for rich comparison (headers + up to 10 row pairs).
CIR_V1_MAX_NODES = 24
CIR_V1_MAX_EDGES = 24

# Comparison authoring
COMPARISON_MAX_ROW_PAIRS = 10

# RAG deterministic ingest (comparison + general bullet extraction)
RAG_INGEST_LINE_LIMIT = 50
RAG_INGEST_LINE_MAX_CHARS = 500

# Layered comparison pedagogy: concise cards vs rich narration
ROW_CARD_DETAIL_MAX = 480
ROW_DETAIL_MAX = 600
ROW_NARRATION_MAX = 900
ROW_ANNOTATION_MAX = 220
