"""
Board-native narration policy for Zone 1 Timeline V3 pedagogy.

Low-risk language layer only — does not change VTSE, planner, or runtime orchestration.
"""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

# ── LLM prompt blocks (injected into micro / visual teaching prompts) ─────────

BOARD_NATIVE_MICRO_VOICE_BLOCK = (
    "BOARD-NATIVE LANGUAGE (mandatory when teaching on the instructional board):\n"
    "- Refer to ideas on the board: 'on the board', 'this comparison', 'these connected ideas', "
    "'this step', 'this relationship', 'the highlighted part'.\n"
    "- NEVER say: diagram, chart, graph, illustration, picture, SVG, or 'above/below the chart'.\n"
    "- NEVER say: 'look at this diagram', 'observe the chart', 'as shown in the figure'.\n"
    "- Prefer: 'notice how these concepts connect', 'focus on this comparison', "
    "'observe how these ideas link', 'see how this part fits the whole'.\n"
    "- For comparisons: contrast traits or groups naturally ('one group… while another…').\n"
    "- For cycles/processes: use step language ('first… then… finally…').\n"
    "- For hierarchies: use levels or branches ('the main idea splits into…').\n"
    "- Keep spoken lines short, warm, and concrete — suitable for text-to-speech.\n\n"
)

BOARD_NATIVE_EXPLAIN_ZONE_SUFFIX = (
    " Use board-native language only (no diagrams, charts, or illustrations as metaphors)."
)


def pacing_visualize_instruction() -> str:
    """VISUALIZE pacing frame — board narration, not diagram narration."""
    return (
        "RESPONSE STYLE FOR THIS TURN — BOARD NARRATION:\n"
        "- Guide attention across the instructional board, as a teacher pointing to ideas already shown.\n"
        "- Narrate naturally: 'Notice how…', 'This part shows…', 'These ideas connect when…'.\n"
        "- Do NOT mention diagrams, charts, graphs, or illustrations.\n"
        "- Do NOT end with a Socratic question — a brief observational comment closes the turn.\n"
        "- Keep the tone like a teacher directing focus on relationships, not administering a test.\n\n"
    )


def visual_teaching_prompt_block(
    intent: dict[str, Any],
    *,
    pacing_is_visualize: bool = False,
) -> str:
    """
    Prompt block when a structured visual intent is attached (board-aligned wording).
    """
    layout = str(intent.get("type") or "").strip() or "relationship"
    d_data = intent.get("data")
    elements_block = (
        f"\nBoard elements to align with:\n{d_data}" if d_data is not None else ""
    )
    close_line = (
        "- Close with a brief observation (e.g., 'Notice how these parts connect.'), no question mark.\n"
        if pacing_is_visualize
        else "- End with one clear follow-up question.\n"
    )
    return (
        "\nBOARD-ALIGNED TEACHING MODE:\n\n"
        "- You are explaining while referring to what is on the instructional board.\n"
        '- Open by anchoring attention on the board (e.g., "Notice this comparison…", '
        '"Focus on how these ideas connect…").\n'
        "- Use natural pointers: 'here', 'this part', 'this side', 'these steps'.\n"
        "- Tie each sentence to the board elements — do not describe unrelated ideas.\n"
        "- Keep explanation concise and spoken-friendly.\n"
        f"{close_line}"
        "- Do NOT use the words diagram, chart, graph, illustration, or figure.\n\n"
        f"Layout style: {layout}"
        f"{elements_block}\n"
    )


# ── Sanitization (incremental timeline TTS / narration_segments) ─────────────

_LEGACY_PHRASE_REPLACEMENTS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\blook at this diagram\b", re.I), "notice how these ideas connect"),
    (re.compile(r"\blook at the diagram\b", re.I), "focus on this relationship on the board"),
    (re.compile(r"\bobserve the diagram\b", re.I), "notice this part of the lesson"),
    (re.compile(r"\bobserve this diagram\b", re.I), "notice how these concepts connect"),
    (re.compile(r"\bobserve the chart\b", re.I), "notice this comparison"),
    (re.compile(r"\bobserve this chart\b", re.I), "notice this comparison"),
    (re.compile(r"\bthe chart above\b", re.I), "on the board here"),
    (re.compile(r"\bthe diagram above\b", re.I), "on the board"),
    (re.compile(r"\bthis chart shows\b", re.I), "this comparison shows"),
    (re.compile(r"\bthis diagram shows\b", re.I), "the board shows"),
    (re.compile(r"\bas you can see in the (?:diagram|chart|graph|illustration)\b", re.I), "notice"),
    (re.compile(r"\bas you can see\b", re.I), "notice"),
    (re.compile(r"\bhere you can see\b", re.I), "here on the board"),
    (re.compile(r"\bin the (?:diagram|chart|graph|illustration) above\b", re.I), "on the board"),
    (re.compile(r"\bthe (?:diagram|chart|graph|illustration) (?:above|below)\b", re.I), "on the board"),
    (re.compile(r"\bvisual graph\b", re.I), "relationship"),
    (re.compile(r"\bthe graph above\b", re.I), "these connected ideas"),
    (re.compile(r"\bthis illustration\b", re.I), "this idea"),
    (re.compile(r"\bthe illustration\b", re.I), "the idea on the board"),
    (re.compile(r"\bpointing to a diagram\b", re.I), "guiding you on the board"),
    (re.compile(r"\bthe diagram\b", re.I), "the board"),
    (re.compile(r"\bthis diagram\b", re.I), "this view on the board"),
    (re.compile(r"\ba diagram\b", re.I), "the board layout"),
    (re.compile(r"\bthe chart\b", re.I), "this comparison"),
    (re.compile(r"\bthis chart\b", re.I), "this comparison"),
]

_DIAGRAM_TERM_PATTERN = re.compile(
    r"\b(?:diagram|chart|illustration|figure|svg)\b",
    re.I,
)

_TRANSITION_OPENERS = (
    "Consider this:",
    "Notice here:",
    "Think about this:",
    "One more angle:",
    "Building on that:",
    "Let's connect this:",
)

_REPETITIVE_TRANSITIONS: list[tuple[re.Pattern[str], int]] = [
    (re.compile(r"^Next consider\b", re.I | re.M), 0),
    (re.compile(r"^Now consider\b", re.I | re.M), 1),
    (re.compile(r"^Next, consider\b", re.I | re.M), 0),
    (re.compile(r"^Now, consider\b", re.I | re.M), 1),
    (re.compile(r"\bNext consider\b", re.I), 0),
    (re.compile(r"\bNow consider\b", re.I), 1),
]


def _count_diagram_terms(text: str) -> int:
    return len(_DIAGRAM_TERM_PATTERN.findall(text or ""))


def apply_transition_variation(text: str, *, variation_seed: int = 0) -> str:
    """Deterministically rotate repetitive transition openers."""
    if not text or not str(text).strip():
        return text
    out = str(text)
    seed = int(variation_seed) % max(1, len(_TRANSITION_OPENERS))
    for pattern, offset in _REPETITIVE_TRANSITIONS:
        idx = (seed + offset) % len(_TRANSITION_OPENERS)
        replacement = _TRANSITION_OPENERS[idx]
        out = pattern.sub(replacement, out, count=1)
    return out


def sanitize_narration_for_timeline(
    raw: str,
    *,
    fallback: str = "",
    max_len: int = 800,
    variation_seed: int = 0,
    narration_source: str = "micro_llm",
) -> tuple[str, dict[str, Any]]:
    """
    Prepare tutor prose for Timeline V3 ``narration_segments`` / TTS.

    Returns (sanitized_text, observability_metadata).
    """
    text = (raw or fallback or "").strip()
    if not text:
        text = (fallback or "").strip()

    before_terms = _count_diagram_terms(text)
    removed = 0
    for pattern, repl in _LEGACY_PHRASE_REPLACEMENTS:
        text, n = pattern.subn(repl, text)
        removed += n

    text = apply_transition_variation(text, variation_seed=variation_seed)

    after_terms = _count_diagram_terms(text)
    if after_terms > 0:
        text = _DIAGRAM_TERM_PATTERN.sub("the board", text)
        removed += after_terms

    text = re.sub(r"\s{2,}", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if max_len > 0 and len(text) > max_len:
        text = text[:max_len].rstrip()

    meta: dict[str, Any] = {
        "narration_sanitized": True,
        "board_native_language": True,
        "legacy_diagram_terms_removed": int(removed),
        "narration_source": narration_source,
        "diagram_terms_before": before_terms,
        "diagram_terms_after": _count_diagram_terms(text),
    }
    if removed > 0 or before_terms > 0:
        logger.info(
            "[BOARD_NATIVE_NARRATION] sanitized source=%s removed=%d terms_before=%d terms_after=%d len=%d",
            narration_source,
            removed,
            before_terms,
            meta["diagram_terms_after"],
            len(text),
        )
    return text, meta


def sanitize_annotation_for_timeline(
    raw: str,
    *,
    fallback: str = "",
    max_len: int = 220,
    variation_seed: int = 0,
) -> tuple[str, dict[str, Any]]:
    """Shorter sanitization pass for incremental annotation text."""
    text, meta = sanitize_narration_for_timeline(
        raw,
        fallback=fallback,
        max_len=max_len,
        variation_seed=variation_seed,
        narration_source="micro_llm_annotation",
    )
    return text, meta
