"""Dimension-aligned comparison row authoring for VTSE comparison_contrast."""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.cir.limits import (
    COMPARISON_MAX_ROW_PAIRS,
    RAG_INGEST_LINE_LIMIT,
    ROW_ANNOTATION_MAX,
    ROW_CARD_DETAIL_MAX,
    ROW_DETAIL_MAX,
    ROW_NARRATION_MAX,
)
from app.vtse.authoring.content_filters import is_placeholder_text, strip_placeholder_markers
from app.vtse.authoring.semantic_extract import (
    AuthoringSemanticDraft,
    TraitDraft,
    _clip,
    _lines_from_rag,
)

_CONTRAST_SPLIT = re.compile(
    r"\s+(?:while|whereas|but|unlike|;\s*|\s+vs\.?\s+)",
    re.IGNORECASE,
)
_DIMENSION_KEYWORDS: tuple[tuple[str, str], ...] = (
    ("emotion", "Emotions"),
    ("feel", "Emotions"),
    ("energy", "Energy"),
    ("food", "Energy"),
    ("power", "Energy"),
    ("electric", "Energy"),
    ("fuel", "Energy"),
    ("grow", "Growth"),
    ("growth", "Growth"),
    ("develop", "Growth"),
    ("reproduc", "Reproduction"),
    ("offspring", "Reproduction"),
    ("learn", "Learning"),
    ("think", "Thinking"),
    ("intelligen", "Intelligence"),
    ("move", "Movement"),
    ("motion", "Movement"),
    ("biolog", "Biology"),
    ("living", "Biology"),
    ("surviv", "Survival"),
    ("need", "Needs"),
    ("machine", "Nature"),
    ("program", "Programming"),
)


@dataclass(frozen=True)
class ComparisonRow:
    """One pedagogical comparison dimension with paired left/right semantics."""

    dimension: str
    left_title: str
    left_detail: str
    right_title: str
    right_detail: str
    left_card: str = ""
    right_card: str = ""
    pair_narration_text: str = ""

    def left_card_detail(self) -> str:
        return _clip(self.left_card or self.left_detail, ROW_CARD_DETAIL_MAX)

    def right_card_detail(self) -> str:
        return _clip(self.right_card or self.right_detail, ROW_CARD_DETAIL_MAX)

    def pair_narration(self, left_label: str, right_label: str) -> str:
        if self.pair_narration_text.strip():
            return _clip(self.pair_narration_text.strip(), ROW_NARRATION_MAX)
        return _clip(
            teacher_pair_narration(
                dimension=self.dimension,
                left_label=left_label,
                right_label=right_label,
                left_detail=self.left_detail,
                right_detail=self.right_detail,
            ),
            ROW_NARRATION_MAX,
        )

    def left_narration(self, left_label: str, right_label: str) -> str:
        return _clip(
            teacher_pair_narration(
                dimension=self.dimension,
                left_label=left_label,
                right_label=right_label,
                left_detail=self.left_detail,
                right_detail=self.right_detail,
                focus="left",
            ),
            ROW_NARRATION_MAX,
        )

    def right_narration(self, left_label: str, right_label: str) -> str:
        return _clip(
            teacher_pair_narration(
                dimension=self.dimension,
                left_label=left_label,
                right_label=right_label,
                left_detail=self.left_detail,
                right_detail=self.right_detail,
                focus="right",
            ),
            ROW_NARRATION_MAX,
        )

    def left_annotation(self) -> str:
        return _clip(f"{self.dimension}: {self.left_card_detail()}", ROW_ANNOTATION_MAX)

    def right_annotation(self) -> str:
        return _clip(f"{self.dimension}: {self.right_card_detail()}", ROW_ANNOTATION_MAX)


@dataclass(frozen=True)
class ComparisonRowBuildStats:
    comparison_dimension_count: int
    paired_rows_generated: int
    orphan_rows_detected: int
    placeholder_filtered: int
    narration_mode: str = "comparison_teacher_expanded"
    orphan_row_count: int = 0
    repaired_row_count: int = 0
    skipped_incomplete_rows: int = 0
    invalid_dimension_pairs: int = 0
    rag_context_chars_used: int = 0
    rag_lines_ingested: int = 0
    comparison_rows_generated: int = 0
    rows_rendered: int = 0
    rows_clipped_by_budget: int = 0
    narration_detail_level: str = "deterministic_expanded"
    semantic_compression_ratio: float = 0.0
    dropped_context_sections: int = 0


def _row_side_complete(text: str | None) -> bool:
    return bool(text and not is_placeholder_text(text) and len(text.strip()) >= 3)


def is_complete_comparison_row(row: ComparisonRow) -> bool:
    return (
        _row_side_complete(row.left_detail)
        and _row_side_complete(row.right_detail)
        and bool(row.dimension.strip())
        and not is_placeholder_text(row.dimension)
    )


def _matches_side_label(text: str, left_label: str, right_label: str) -> bool:
    raw = (text or "").strip().lower()
    if not raw:
        return False
    for label in (left_label, right_label):
        tokens = _side_tokens(label)
        if not tokens:
            if label.strip().lower() == raw:
                return True
            continue
        if raw in tokens or all(tok == raw for tok in tokens if len(tokens) == 1):
            return True
        if len(raw.split()) <= 2 and all(t in raw for t in tokens):
            return True
    return False


def _infer_dimension_from_content(text: str, *, fallback: str) -> str:
    lower = (text or "").lower()
    for needle, title in _DIMENSION_KEYWORDS:
        if needle in lower:
            return title
    return _clip(fallback, 40)


def _dimension_from_text(
    text: str,
    *,
    fallback: str,
    left_label: str = "",
    right_label: str = "",
) -> str:
    cleaned = sanitize_production_text(text, fallback=fallback)
    if ":" in cleaned:
        head = cleaned.split(":", 1)[0].strip()
        if (
            2 <= len(head) <= 40
            and not _matches_side_label(head, left_label, right_label)
            and not is_placeholder_text(head)
        ):
            return _clip(head, 40)
    inferred = _infer_dimension_from_content(cleaned, fallback=fallback)
    if not _matches_side_label(inferred, left_label, right_label):
        return inferred
    return _clip(
        fallback if not _matches_side_label(fallback, left_label, right_label) else "Compare",
        40,
    )


def _strip_side_prefix(text: str, left_label: str, right_label: str) -> str:
    cleaned = sanitize_production_text(text, fallback=text or "")
    for label in (left_label, right_label):
        side = (label or "").strip()
        if not side:
            continue
        pattern = re.compile(rf"^{re.escape(side)}\s*[:—\-.,;]\s*", re.IGNORECASE)
        cleaned = pattern.sub("", cleaned).strip()
    return cleaned


def _exclusive_side(detail: str, left_label: str, right_label: str) -> str | None:
    left_hit, right_hit = _line_side_hits(detail, left_label, right_label)
    if left_hit and not right_hit:
        return "left"
    if right_hit and not left_hit:
        return "right"
    return None


def _normalize_comparison_row(
    row: ComparisonRow,
    *,
    left_label: str,
    right_label: str,
) -> ComparisonRow | None:
    """Strip subject prefixes, swap inverted sides, reject same-side-only rows."""
    ld = _strip_side_prefix(row.left_detail, left_label, right_label)
    rd = _strip_side_prefix(row.right_detail, left_label, right_label)
    lt, rt = row.left_title, row.right_title

    ls = _exclusive_side(ld, left_label, right_label)
    rs = _exclusive_side(rd, left_label, right_label)

    left_card = row.left_card
    right_card = row.right_card
    pair_narration = row.pair_narration_text
    if ls == "right" and rs == "left":
        ld, rd = rd, ld
        lt, rt = rt, lt
        left_card, right_card = right_card, left_card
        ls, rs = rs, ls
    elif ls == "right" or rs == "left":
        return None
    elif ls == rs and ls in ("left", "right"):
        return None

    dim = row.dimension.strip()
    if not dim or _matches_side_label(dim, left_label, right_label) or is_placeholder_text(dim):
        dim = _dimension_from_text(
            f"{ld} {rd}",
            fallback=_infer_dimension_from_content(f"{ld} {rd}", fallback="Compare"),
            left_label=left_label,
            right_label=right_label,
        )

    return ComparisonRow(
        dimension=dim,
        left_title=_concise_title(ld, left_label, fallback=lt),
        right_title=_concise_title(rd, right_label, fallback=rt),
        left_detail=ld,
        right_detail=rd,
        left_card=left_card,
        right_card=right_card,
        pair_narration_text=pair_narration,
    )


def validate_comparison_rows(
    rows: list[ComparisonRow],
    *,
    left_label: str = "",
    right_label: str = "",
) -> tuple[tuple[ComparisonRow, ...], ComparisonRowBuildStats]:
    """Reject incomplete/orphan rows; only complete pedagogical pairs survive."""
    complete: list[ComparisonRow] = []
    skipped_incomplete = 0
    invalid_dimension = 0
    orphan_row_count = 0

    for row in rows:
        normalized = (
            _normalize_comparison_row(row, left_label=left_label, right_label=right_label)
            if left_label and right_label
            else row
        )
        if normalized is None:
            skipped_incomplete += 1
            orphan_row_count += 1
            continue
        row = normalized

        left_ok = _row_side_complete(row.left_detail)
        right_ok = _row_side_complete(row.right_detail)
        dim_ok = bool(row.dimension.strip()) and not is_placeholder_text(row.dimension)
        if _matches_side_label(row.dimension, left_label, right_label):
            dim_ok = False

        if not left_ok or not right_ok:
            skipped_incomplete += 1
            if left_ok != right_ok:
                orphan_row_count += 1
            continue
        if not dim_ok:
            invalid_dimension += 1
            skipped_incomplete += 1
            continue
        complete.append(row)

    stats = ComparisonRowBuildStats(
        comparison_dimension_count=len(complete),
        paired_rows_generated=len(complete),
        orphan_rows_detected=orphan_row_count,
        placeholder_filtered=0,
        orphan_row_count=orphan_row_count,
        repaired_row_count=0,
        skipped_incomplete_rows=skipped_incomplete,
        invalid_dimension_pairs=invalid_dimension,
    )
    return tuple(complete), stats


def _side_phrase(detail: str, side_label: str) -> str:
    text = sanitize_production_text(detail, fallback=detail or side_label)
    side = (side_label or "").strip()
    if side and text.lower().startswith(side.lower()):
        text = text[len(side) :].strip(" :—-.,;")
    if not text:
        return side_label
    if side and not text.lower().startswith(side.lower()):
        return f"{side} {text[0].lower()}{text[1:]}" if text else side
    return text


def teacher_pair_narration(
    *,
    dimension: str,
    left_label: str,
    right_label: str,
    left_detail: str,
    right_detail: str,
    focus: str = "pair",
) -> str:
    """Teacher-style spoken contrast — richer than summary cards, grounded in row detail."""
    dim = dimension.strip()
    left = _side_phrase(left_detail, left_label)
    right = _side_phrase(right_detail, right_label)
    left = left.rstrip(".")
    right = right.rstrip(".")
    dim_clause = f" on {dim.lower()}" if dim and dim.lower() not in ("compare", "comparison") else ""
    if focus == "left":
        return f"When we compare {left_label} and {right_label}{dim_clause}, {left}."
    if focus == "right":
        return f"For {right_label}{dim_clause}, {right}."
    return (
        f"When we compare {left_label} and {right_label}{dim_clause}, "
        f"{left}. In contrast, {right}."
    )


def structured_row_narration(
    *,
    dimension: str,
    left_label: str,
    right_label: str,
    left_detail: str,
    right_detail: str,
    focus: str = "pair",
) -> str:
    """Comparison-aware spoken line — not raw node label reads."""
    _ = left_label, right_label
    dim = dimension.strip()
    left = left_detail.strip().rstrip(".")
    right = right_detail.strip().rstrip(".")
    if focus == "left":
        return f"On {dim}, {left}."
    if focus == "right":
        return f"For {dim}, {right}."
    return f"On {dim}, {left}, while {right.lower()}."


def sanitize_production_text(text: str | None, *, fallback: str) -> str:
    cleaned = (text or "").strip()
    if is_placeholder_text(cleaned):
        return fallback
    cleaned = strip_placeholder_markers(cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned)
    return _clip(cleaned or fallback, ROW_DETAIL_MAX)


def _concise_title(detail: str, side_label: str, *, fallback: str, max_words: int = 4) -> str:
    text = sanitize_production_text(detail, fallback=fallback)
    side = (side_label or "").strip()
    if side and text.lower().startswith(side.lower()):
        text = text[len(side) :].strip(" :—-.,;")
    if ":" in text and len(text.split(":", 1)[0].split()) <= max_words:
        return _clip(text.split(":", 1)[0].strip(), 32)
    words = text.split()
    if len(words) <= max_words:
        return _clip(text, 32)
    return _clip(" ".join(words[:max_words]), 32)


def _trait_to_side_parts(trait: TraitDraft, side_label: str) -> tuple[str, str]:
    detail = sanitize_production_text(
        trait.summary or trait.narration or trait.label,
        fallback=trait.label,
    )
    title = _concise_title(detail, side_label, fallback=_clip(trait.label, 32))
    if is_placeholder_text(trait.label):
        title = title or _clip(detail.split()[0] if detail.split() else side_label, 32)
    else:
        short_label = _clip(trait.label, 32)
        if len(short_label.split()) <= 4 and not is_placeholder_text(short_label):
            title = short_label
    return title, detail


def _row_from_trait_pair(
    left_trait: TraitDraft,
    right_trait: TraitDraft,
    *,
    left_label: str,
    right_label: str,
    dimension_hint: str | None = None,
) -> ComparisonRow | None:
    lt, ld = _trait_to_side_parts(left_trait, left_label)
    rt, rd = _trait_to_side_parts(right_trait, right_label)
    if is_placeholder_text(ld) and is_placeholder_text(rd):
        return None
    dim = dimension_hint or _dimension_from_text(
        left_trait.label if len(left_trait.label.split()) <= 4 else left_trait.summary,
        fallback=lt,
        left_label=left_label,
        right_label=right_label,
    )
    row = ComparisonRow(
        dimension=dim,
        left_title=lt,
        left_detail=ld,
        right_title=rt,
        right_detail=rd,
    )
    return _normalize_comparison_row(row, left_label=left_label, right_label=right_label)


def _parse_contrast_line(
    line: str,
    *,
    left_label: str,
    right_label: str,
) -> ComparisonRow | None:
    cleaned = sanitize_production_text(line, fallback="")
    if not cleaned:
        return None
    parts = _CONTRAST_SPLIT.split(cleaned, maxsplit=1)
    if len(parts) != 2:
        return None
    a, b = parts[0].strip(), parts[1].strip()
    left_hit_a, right_hit_a = _line_side_hits(a, left_label, right_label)
    left_hit_b, right_hit_b = _line_side_hits(b, left_label, right_label)

    if left_hit_a and not right_hit_a and right_hit_b and not left_hit_b:
        left_part, right_part = a, b
    elif left_hit_b and not right_hit_b and right_hit_a and not left_hit_a:
        left_part, right_part = b, a
    elif left_hit_a and not right_hit_a and not left_hit_b and not right_hit_b:
        left_part, right_part = a, b
    elif right_hit_b and not left_hit_b and not left_hit_a and not right_hit_a:
        left_part, right_part = a, b
    else:
        return None

    dim = _dimension_from_text(
        left_part,
        fallback=_dimension_from_text(
            cleaned,
            fallback="Compare",
            left_label=left_label,
            right_label=right_label,
        ),
        left_label=left_label,
        right_label=right_label,
    )
    lt = _concise_title(left_part, left_label, fallback=dim)
    rt = _concise_title(right_part, right_label, fallback=dim)
    row = ComparisonRow(
        dimension=dim,
        left_title=lt,
        left_detail=sanitize_production_text(left_part, fallback=lt),
        right_title=rt,
        right_detail=sanitize_production_text(right_part, fallback=rt),
    )
    return _normalize_comparison_row(row, left_label=left_label, right_label=right_label)


def default_dimension_rows(left_label: str, right_label: str, concept: str) -> tuple[ComparisonRow, ...]:
    _ = concept
    return (
        ComparisonRow(
            dimension="Growth",
            left_title="Can grow",
            left_detail=f"{left_label} can grow and develop over time.",
            right_title="No growth",
            right_detail=f"{right_label} does not grow on its own.",
        ),
        ComparisonRow(
            dimension="Energy",
            left_title="Needs food",
            left_detail=f"{left_label} needs food or water for energy.",
            right_title="Needs power",
            right_detail=f"{right_label} needs electricity or fuel.",
        ),
        ComparisonRow(
            dimension="Reproduction",
            left_title="Reproduces",
            left_detail=f"{left_label} can produce offspring.",
            right_title="No offspring",
            right_detail=f"{right_label} does not reproduce biologically.",
        ),
    )


def _side_tokens(label: str) -> set[str]:
    stop = {"the", "a", "an", "vs", "versus", "and", "or", "of"}
    return {t for t in re.split(r"[\W_]+", label.lower()) if len(t) >= 3 and t not in stop}


def _line_side_hits(line: str, left_label: str, right_label: str) -> tuple[bool, bool]:
    lower = line.lower()
    left_tokens = _side_tokens(left_label)
    right_tokens = _side_tokens(right_label)
    left_hit = any(tok in lower for tok in left_tokens) if left_tokens else left_label.lower() in lower
    right_hit = any(tok in lower for tok in right_tokens) if right_tokens else right_label.lower() in lower
    return left_hit, right_hit


def _bucket_lines_by_side(
    lines: list[str],
    *,
    left_label: str,
    right_label: str,
) -> tuple[list[str], list[str]]:
    left_lines: list[str] = []
    right_lines: list[str] = []

    for line in lines:
        if is_placeholder_text(line):
            continue
        left_hit, right_hit = _line_side_hits(line, left_label, right_label)
        if left_hit and not right_hit:
            left_lines.append(line)
        elif right_hit and not left_hit:
            right_lines.append(line)

    return left_lines, right_lines


def _rows_from_side_buckets(
    left_lines: list[str],
    right_lines: list[str],
    *,
    left_label: str,
    right_label: str,
    max_rows: int,
) -> list[ComparisonRow]:
    rows: list[ComparisonRow] = []
    pair_count = min(len(left_lines), len(right_lines), max_rows)
    for i in range(pair_count):
        left_part = left_lines[i]
        right_part = right_lines[i]
        dim = _dimension_from_text(
            left_part,
            fallback=_dimension_from_text(
                right_part,
                fallback="Compare",
                left_label=left_label,
                right_label=right_label,
            ),
            left_label=left_label,
            right_label=right_label,
        )
        lt = _concise_title(left_part, left_label, fallback=dim)
        rt = _concise_title(right_part, right_label, fallback=dim)
        row = ComparisonRow(
            dimension=dim,
            left_title=lt,
            left_detail=sanitize_production_text(left_part, fallback=lt),
            right_title=rt,
            right_detail=sanitize_production_text(right_part, fallback=rt),
        )
        normalized = _normalize_comparison_row(row, left_label=left_label, right_label=right_label)
        if normalized:
            rows.append(normalized)
    return rows


def _bucket_traits_by_side(
    traits: tuple[TraitDraft, ...],
    *,
    left_label: str,
    right_label: str,
) -> tuple[list[TraitDraft], list[TraitDraft]]:
    left_traits: list[TraitDraft] = []
    right_traits: list[TraitDraft] = []
    for trait in traits:
        text = trait.summary or trait.label or trait.narration or ""
        if is_placeholder_text(text):
            continue
        left_hit, right_hit = _line_side_hits(text, left_label, right_label)
        if left_hit and not right_hit:
            left_traits.append(trait)
        elif right_hit and not left_hit:
            right_traits.append(trait)
    return left_traits, right_traits


def comparison_rows_from_llm_json(
    payload: dict,
    *,
    left_label: str,
    right_label: str,
) -> tuple[ComparisonRow, ...]:
    """Parse optional LLM comparison draft; validate/normalize each row."""
    rows: list[ComparisonRow] = []
    for item in payload.get("rows") or []:
        if not isinstance(item, dict):
            continue
        dim = str(item.get("dimension") or "").strip()
        ld = str(item.get("left_detail") or item.get("left_summary") or "").strip()
        rd = str(item.get("right_detail") or item.get("right_summary") or "").strip()
        if not ld and not rd:
            continue
        row = ComparisonRow(
            dimension=dim or "Compare",
            left_title=str(item.get("left_title") or dim or "Left")[:32],
            left_detail=ld,
            right_title=str(item.get("right_title") or dim or "Right")[:32],
            right_detail=rd,
            left_card=str(item.get("left_card") or "")[:ROW_CARD_DETAIL_MAX],
            right_card=str(item.get("right_card") or "")[:ROW_CARD_DETAIL_MAX],
            pair_narration_text=str(item.get("pair_narration") or "")[:ROW_NARRATION_MAX],
        )
        normalized = _normalize_comparison_row(row, left_label=left_label, right_label=right_label)
        if normalized:
            rows.append(normalized)
    return tuple(rows)


def merge_comparison_row_sources(
    *,
    deterministic_rows: tuple[ComparisonRow, ...],
    llm_rows: tuple[ComparisonRow, ...],
    left_label: str,
    right_label: str,
    max_rows: int,
    fill_from_deterministic: bool = True,
) -> tuple[tuple[ComparisonRow, ...], str]:
    """Prefer validated LLM/authored rows; optionally fill gaps from deterministic extract.

    Authored VTSE templates pass ``fill_from_deterministic=False`` so the teach
    path keeps the exact authored row count (RAG often re-ingests the same
    outline and would append near-duplicates under different dimension keys).
    """
    _ = left_label, right_label
    if not llm_rows:
        return deterministic_rows[:max_rows], "deterministic_expanded"

    # Authored lock: preserve exact order/count — do not collapse on dimension
    # (normalize can rewrite short labels to the same fallback "Compare").
    if not fill_from_deterministic:
        return tuple(llm_rows[:max_rows]), "llm_primary"

    merged: list[ComparisonRow] = []
    seen: set[str] = set()
    for row in llm_rows:
        if len(merged) >= max_rows:
            break
        key = row.dimension.strip().lower()
        if key in seen:
            continue
        merged.append(row)
        seen.add(key)
    for row in deterministic_rows:
        if len(merged) >= max_rows:
            break
        key = row.dimension.strip().lower()
        if key in seen:
            continue
        merged.append(row)
        seen.add(key)
    level = "llm_hybrid" if deterministic_rows else "llm_primary"
    return tuple(merged), level


def _count_rag_source_lines(rag_context: str | None) -> int:
    if not rag_context:
        return 0
    count = 0
    for raw in str(rag_context).replace("\r", "").split("\n"):
        t = raw.strip()
        if len(t) >= 10 and not t.startswith("#"):
            count += 1
    return count


def _finalize_comparison_stats(
    *,
    rows: tuple[ComparisonRow, ...],
    integrity: ComparisonRowBuildStats,
    rag_context: str | None,
    rag_lines_ingested: int,
    placeholder_filtered: int,
    orphan_rows: int,
    narration_detail_level: str,
    rows_before_budget: int,
    rows_rendered: int,
) -> ComparisonRowBuildStats:
    rag_chars = len((rag_context or "").strip())
    detail_chars = sum(len(r.left_detail) + len(r.right_detail) for r in rows)
    source_lines = _count_rag_source_lines(rag_context)
    compression = round(detail_chars / max(1, rag_chars), 4) if rag_chars else 0.0
    return ComparisonRowBuildStats(
        comparison_dimension_count=len(rows),
        paired_rows_generated=len(rows),
        orphan_rows_detected=orphan_rows + integrity.orphan_row_count,
        placeholder_filtered=placeholder_filtered,
        narration_mode="comparison_teacher_expanded",
        orphan_row_count=integrity.orphan_row_count,
        repaired_row_count=integrity.repaired_row_count,
        skipped_incomplete_rows=integrity.skipped_incomplete_rows,
        invalid_dimension_pairs=integrity.invalid_dimension_pairs,
        rag_context_chars_used=rag_chars,
        rag_lines_ingested=rag_lines_ingested,
        comparison_rows_generated=rows_before_budget,
        rows_rendered=rows_rendered,
        rows_clipped_by_budget=max(0, rows_before_budget - rows_rendered),
        narration_detail_level=narration_detail_level,
        semantic_compression_ratio=compression,
        dropped_context_sections=max(0, source_lines - rag_lines_ingested),
    )


def build_comparison_rows(
    *,
    left_label: str,
    right_label: str,
    concept: str,
    draft: AuthoringSemanticDraft,
    rag_context: str | None,
    max_rows: int = COMPARISON_MAX_ROW_PAIRS,
    llm_rows: tuple[ComparisonRow, ...] | None = None,
) -> tuple[tuple[ComparisonRow, ...], ComparisonRowBuildStats]:
    rows: list[ComparisonRow] = []
    placeholder_filtered = 0
    orphan_rows = 0
    rag_lines = _lines_from_rag(rag_context, limit=RAG_INGEST_LINE_LIMIT)
    rag_lines_ingested = len(rag_lines)

    for line in rag_lines:
        if is_placeholder_text(line):
            placeholder_filtered += 1
            continue
        parsed = _parse_contrast_line(line, left_label=left_label, right_label=right_label)
        if parsed:
            rows.append(parsed)

    if len(rows) < 2:
        left_lines, right_lines = _bucket_lines_by_side(
            rag_lines,
            left_label=left_label,
            right_label=right_label,
        )
        if left_lines and right_lines:
            rows.extend(
                _rows_from_side_buckets(
                    left_lines,
                    right_lines,
                    left_label=left_label,
                    right_label=right_label,
                    max_rows=max_rows,
                ),
            )

    if len(rows) < 2 and len(draft.traits) >= 2:
        left_traits, right_traits = _bucket_traits_by_side(
            draft.traits,
            left_label=left_label,
            right_label=right_label,
        )
        if left_traits and right_traits:
            for row in _rows_from_side_buckets(
                [t.summary or t.label for t in left_traits],
                [t.summary or t.label for t in right_traits],
                left_label=left_label,
                right_label=right_label,
                max_rows=max_rows,
            ):
                rows.append(row)
            orphan_rows += abs(len(left_traits) - len(right_traits))

    if len(rows) < 2 and len(draft.traits) >= 2:
        mid = (len(draft.traits) + 1) // 2
        left_traits = draft.traits[:mid]
        right_traits = draft.traits[mid:]
        pair_count = min(len(left_traits), len(right_traits), max_rows)
        rows = []
        for i in range(pair_count):
            row = _row_from_trait_pair(
                left_traits[i],
                right_traits[i],
                left_label=left_label,
                right_label=right_label,
            )
            if row:
                rows.append(row)
            else:
                placeholder_filtered += 1
        orphan_rows += abs(len(left_traits) - len(right_traits))

    rows = rows[:max_rows]
    if len(rows) < 2:
        rows = list(default_dimension_rows(left_label, right_label, concept))

    validated, integrity = validate_comparison_rows(
        rows,
        left_label=left_label,
        right_label=right_label,
    )
    if len(validated) >= 2:
        rows = list(validated)
    elif len(validated) == 1:
        rows = list(validated) + list(default_dimension_rows(left_label, right_label, concept))[: max_rows - 1]
        integrity = ComparisonRowBuildStats(
            comparison_dimension_count=len(rows),
            paired_rows_generated=len(rows),
            orphan_rows_detected=integrity.orphan_row_count,
            placeholder_filtered=placeholder_filtered,
            orphan_row_count=integrity.orphan_row_count,
            repaired_row_count=len(rows) - len(validated),
            skipped_incomplete_rows=integrity.skipped_incomplete_rows,
            invalid_dimension_pairs=integrity.invalid_dimension_pairs,
            narration_detail_level="deterministic_expanded",
        )
    else:
        rows = list(default_dimension_rows(left_label, right_label, concept))[:max_rows]
        integrity = ComparisonRowBuildStats(
            comparison_dimension_count=len(rows),
            paired_rows_generated=len(rows),
            orphan_rows_detected=orphan_rows + integrity.orphan_row_count,
            placeholder_filtered=placeholder_filtered,
            orphan_row_count=orphan_rows + integrity.orphan_row_count,
            repaired_row_count=len(rows),
            skipped_incomplete_rows=integrity.skipped_incomplete_rows,
            invalid_dimension_pairs=integrity.invalid_dimension_pairs,
            narration_detail_level="deterministic_fallback",
        )

    det_rows = tuple(rows[:max_rows])
    narration_level = integrity.narration_detail_level or "deterministic_expanded"
    if llm_rows:
        # Authored/LLM comparison drafts are authoritative — do not pad with
        # RAG/deterministic extracts (common failure: outline also used as
        # rag_context → duplicate point under a different dimension key).
        det_rows, narration_level = merge_comparison_row_sources(
            deterministic_rows=det_rows,
            llm_rows=llm_rows,
            left_label=left_label,
            right_label=right_label,
            max_rows=max_rows,
            fill_from_deterministic=False,
        )

    rows_before_budget = len(det_rows)
    from app.cir.limits import CIR_V1_MAX_NODES

    max_renderable = min(max_rows, (CIR_V1_MAX_NODES - 2) // 2)
    final_rows = det_rows
    rows_rendered = min(len(final_rows), max_renderable)

    stats = _finalize_comparison_stats(
        rows=final_rows,
        integrity=integrity,
        rag_context=rag_context,
        rag_lines_ingested=rag_lines_ingested,
        placeholder_filtered=placeholder_filtered,
        orphan_rows=orphan_rows,
        narration_detail_level=narration_level,
        rows_before_budget=rows_before_budget,
        rows_rendered=rows_rendered,
    )
    return final_rows, stats


def rows_to_trait_drafts(rows: tuple[ComparisonRow, ...]) -> tuple[tuple[TraitDraft, ...], tuple[TraitDraft, ...]]:
    """Legacy provenance mirrors for tests and debug."""
    left: list[TraitDraft] = []
    right: list[TraitDraft] = []
    for row in rows:
        left.append(
            TraitDraft(
                label=row.left_title,
                summary=row.left_card_detail(),
                narration=row.left_detail,
            ),
        )
        right.append(
            TraitDraft(
                label=row.right_title,
                summary=row.right_card_detail(),
                narration=row.right_detail,
            ),
        )
    return tuple(left), tuple(right)
