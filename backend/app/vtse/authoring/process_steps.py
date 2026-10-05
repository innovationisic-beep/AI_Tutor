"""Deterministic process-step extraction for linear_process authoring (Phase A)."""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.vtse.authoring.comparison_rows import is_placeholder_text
from app.vtse.authoring.content_filters import (
    is_authoring_scaffold_header,
    is_practice_or_support_content,
    sanitize_process_production_text,
    strip_scaffold_prefix,
)
from app.cir.limits import CIR_V1_MAX_NODES
from app.vtse.authoring.process_step_content import (
    PROCESS_MAX_STEPS,
    is_generic_stage_label,
    is_prose_identity,
    split_process_step_content,
)
from app.vtse.authoring.semantic_extract import TraitDraft, _clip

_NUMBERED_STEP_RE = re.compile(r"^(\d+)[.)]\s+(.+)$")
_BULLET_RE = re.compile(r"^[\s]*(?:[-*•]|\d+[.)])\s+(.+)$", re.MULTILINE)
_STEP_SECTION_HEADER_RE = re.compile(r"^step\s*(\d+)\s*[—\-–:]\s*(.+)$", re.I)
_ANATOMICAL_HINT_RE = re.compile(
    r"\b(mouth|esophagus|oesophagus|stomach|small intestine|large intestine|"
    r"intestines|intestine|liver|pancreas|gallbladder|colon|rectum|anus|pharynx|"
    r"duodenum|jejunum|ileum|cecum|appendix)\b",
    re.I,
)


@dataclass(frozen=True)
class ProcessStepExtractionStats:
    filtered_placeholder_count: int = 0
    filtered_practice_nodes: int = 0
    process_step_count: int = 0
    process_scene_count: int = 0
    raw_line_count: int = 0


def _step_narration(identity: str, explanation: str, concept: str) -> str:
    body = sanitize_process_production_text(explanation, fallback=identity, max_len=400)
    if body.lower().startswith(identity.lower()):
        return _clip(body, 400)
    lead = identity.lower()
    return _clip(f"At this step — {lead} — {body[0].lower() + body[1:] if body else lead}.", 400)


def _append_step_line(current: list[str], line: str) -> None:
    cleaned = strip_scaffold_prefix(line.strip())
    if not cleaned:
        return
    if current:
        prev = current[-1]
        if not prev.endswith((".", "!", "?")):
            current[-1] = f"{prev} {cleaned}".strip()
            return
    current.append(cleaned)


def _is_process_overview_paragraph(text: str) -> bool:
    if len(text) < 72:
        return False
    low = text.lower()
    if re.match(r"^step\s*\d+", low):
        return False
    overview_markers = (
        " is the process",
        " is a process",
        " refers to ",
        " involves breaking",
        " involves the ",
        " is how ",
    )
    return any(marker in low for marker in overview_markers)


def _format_section_block(title: str, body_lines: list[str]) -> str:
    title = strip_scaffold_prefix(title.strip())
    body = " ".join(strip_scaffold_prefix(x) for x in body_lines if x.strip()).strip()
    if title and body:
        if ":" in title:
            return f"{title} {body}".strip()
        return f"{title}: {body}"
    return title or body


def _parse_process_sections(rag_context: str) -> tuple[list[str], ProcessStepExtractionStats]:
    """Parse ``Step N — Organ`` section headers with body lines as one teaching unit."""
    stats = ProcessStepExtractionStats()
    if not rag_context or not str(rag_context).strip():
        return [], stats

    sections: list[str] = []
    current_title: str | None = None
    current_body: list[str] = []
    skip_practice_block = False

    def flush_section() -> None:
        nonlocal current_title, current_body
        if current_title is None and not current_body:
            return
        block = _format_section_block(current_title or "", current_body)
        if block and not is_placeholder_text(block) and not is_practice_or_support_content(block):
            sections.append(block)
        current_title = None
        current_body = []

    for raw in str(rag_context).replace("\r", "").split("\n"):
        t = raw.strip()
        stats = ProcessStepExtractionStats(
            filtered_placeholder_count=stats.filtered_placeholder_count,
            filtered_practice_nodes=stats.filtered_practice_nodes,
            process_step_count=stats.process_step_count,
            process_scene_count=stats.process_scene_count,
            raw_line_count=stats.raw_line_count + (1 if t else 0),
        )

        if not t:
            skip_practice_block = False
            continue

        if is_authoring_scaffold_header(t):
            stats = ProcessStepExtractionStats(
                filtered_placeholder_count=stats.filtered_placeholder_count + 1,
                filtered_practice_nodes=stats.filtered_practice_nodes,
                process_step_count=stats.process_step_count,
                process_scene_count=stats.process_scene_count,
                raw_line_count=stats.raw_line_count,
            )
            skip_practice_block = is_practice_or_support_content(t)
            continue

        if skip_practice_block or is_practice_or_support_content(t):
            stats = ProcessStepExtractionStats(
                filtered_placeholder_count=stats.filtered_placeholder_count,
                filtered_practice_nodes=stats.filtered_practice_nodes + 1,
                process_step_count=stats.process_step_count,
                process_scene_count=stats.process_scene_count,
                raw_line_count=stats.raw_line_count,
            )
            continue

        if is_placeholder_text(t):
            stats = ProcessStepExtractionStats(
                filtered_placeholder_count=stats.filtered_placeholder_count + 1,
                filtered_practice_nodes=stats.filtered_practice_nodes,
                process_step_count=stats.process_step_count,
                process_scene_count=stats.process_scene_count,
                raw_line_count=stats.raw_line_count,
            )
            continue

        header = _STEP_SECTION_HEADER_RE.match(t)
        if header:
            flush_section()
            title_rest = strip_scaffold_prefix(header.group(2).strip())
            if ":" in title_rest:
                title_part, inline_body = title_rest.split(":", 1)
                current_title = title_part.strip()
                if inline_body.strip():
                    current_body.append(inline_body.strip())
            else:
                current_title = title_rest
            continue

        numbered = _NUMBERED_STEP_RE.match(t)
        if numbered:
            flush_section()
            sections.append(strip_scaffold_prefix(numbered.group(2).strip()))
            continue

        bullet = _BULLET_RE.match(t)
        if bullet:
            flush_section()
            sections.append(strip_scaffold_prefix(bullet.group(1).strip()))
            continue

        if current_title is not None:
            _append_step_line(current_body, t)
            continue

        if not sections and not current_title and _is_process_overview_paragraph(t):
            continue

        if len(t) >= 12 and not t.startswith("#"):
            flush_section()
            sections.append(strip_scaffold_prefix(t))

    flush_section()
    return sections, stats


def _parse_process_blocks(rag_context: str | None) -> tuple[list[str], ProcessStepExtractionStats]:
    """Legacy line-by-line parser (fallback when no section structure)."""
    stats = ProcessStepExtractionStats()
    if not rag_context or not str(rag_context).strip():
        return [], stats

    steps: list[str] = []
    skip_practice_block = False

    for raw in str(rag_context).replace("\r", "").split("\n"):
        t = raw.strip()
        stats = ProcessStepExtractionStats(
            filtered_placeholder_count=stats.filtered_placeholder_count,
            filtered_practice_nodes=stats.filtered_practice_nodes,
            process_step_count=stats.process_step_count,
            process_scene_count=stats.process_scene_count,
            raw_line_count=stats.raw_line_count + (1 if t else 0),
        )

        if not t:
            skip_practice_block = False
            continue

        if is_authoring_scaffold_header(t):
            stats = ProcessStepExtractionStats(
                filtered_placeholder_count=stats.filtered_placeholder_count + 1,
                filtered_practice_nodes=stats.filtered_practice_nodes,
                process_step_count=stats.process_step_count,
                process_scene_count=stats.process_scene_count,
                raw_line_count=stats.raw_line_count,
            )
            skip_practice_block = is_practice_or_support_content(t)
            continue

        if skip_practice_block or is_practice_or_support_content(t):
            stats = ProcessStepExtractionStats(
                filtered_placeholder_count=stats.filtered_placeholder_count,
                filtered_practice_nodes=stats.filtered_practice_nodes + 1,
                process_step_count=stats.process_step_count,
                process_scene_count=stats.process_scene_count,
                raw_line_count=stats.raw_line_count,
            )
            continue

        if is_placeholder_text(t):
            stats = ProcessStepExtractionStats(
                filtered_placeholder_count=stats.filtered_placeholder_count + 1,
                filtered_practice_nodes=stats.filtered_practice_nodes,
                process_step_count=stats.process_step_count,
                process_scene_count=stats.process_scene_count,
                raw_line_count=stats.raw_line_count,
            )
            continue

        numbered = _NUMBERED_STEP_RE.match(t)
        if numbered:
            steps.append(strip_scaffold_prefix(numbered.group(2).strip()))
            continue

        bullet = _BULLET_RE.match(t)
        if bullet:
            steps.append(strip_scaffold_prefix(bullet.group(1).strip()))
            continue

        if len(t) >= 12 and not t.startswith("#"):
            if steps:
                merged = f"{steps[-1]} {strip_scaffold_prefix(t)}".strip()
                steps[-1] = merged
            else:
                if not _is_process_overview_paragraph(t):
                    steps.append(strip_scaffold_prefix(t))

    return steps, stats


def _parse_process_raw_blocks(rag_context: str | None) -> tuple[list[str], ProcessStepExtractionStats]:
    if not rag_context or not str(rag_context).strip():
        return [], ProcessStepExtractionStats()

    sections, stats = _parse_process_sections(str(rag_context))
    if len(sections) >= 2:
        return sections, stats

    blocks, block_stats = _parse_process_blocks(rag_context)
    merged_stats = ProcessStepExtractionStats(
        filtered_placeholder_count=max(stats.filtered_placeholder_count, block_stats.filtered_placeholder_count),
        filtered_practice_nodes=max(stats.filtered_practice_nodes, block_stats.filtered_practice_nodes),
        process_step_count=block_stats.process_step_count,
        process_scene_count=block_stats.process_scene_count,
        raw_line_count=max(stats.raw_line_count, block_stats.raw_line_count),
    )
    return blocks or sections, merged_stats


def _normalize_stage_key(label: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (label or "").lower())


def _anatomical_key(text: str) -> str | None:
    match = _ANATOMICAL_HINT_RE.search(text or "")
    if not match:
        return None
    key = match.group(1).lower().replace(" ", "")
    if key == "oesophagus":
        return "esophagus"
    if key in {"intestines", "intestine"}:
        return "intestine"
    return key


def _stages_share_anatomy(left: TraitDraft, right: TraitDraft) -> bool:
    left_key = _anatomical_key(left.label) or _anatomical_key(left.summary or "")
    right_key = _anatomical_key(right.label) or _anatomical_key(right.summary or "")
    return left_key is not None and left_key == right_key


def _should_merge_process_steps(left: TraitDraft, right: TraitDraft) -> bool:
    left_key = _normalize_stage_key(left.label)
    right_key = _normalize_stage_key(right.label)
    if left_key and left_key == right_key:
        return True
    if _stages_share_anatomy(left, right):
        return True
    if left_key and len(left_key) >= 4 and left_key in _normalize_stage_key(right.summary or ""):
        return True
    if right_key and len(right_key) >= 4 and right_key in _normalize_stage_key(left.summary or ""):
        return True
    return False


def _pick_identity_label(left: str, right: str) -> str:
    left = (left or "").strip()
    right = (right or "").strip()
    if is_generic_stage_label(left) and not is_generic_stage_label(right):
        return right
    if is_generic_stage_label(right) and not is_generic_stage_label(left):
        return left
    if is_prose_identity(left) and not is_prose_identity(right):
        return right
    if is_prose_identity(right) and not is_prose_identity(left):
        return left
    if left and right:
        return left if len(left.split()) <= len(right.split()) else right
    return left or right


def coalesce_process_trait_steps(
    steps: tuple[TraitDraft, ...] | list[TraitDraft],
    *,
    concept: str,
) -> tuple[TraitDraft, ...]:
    """Merge fragmented RAG lines that describe the same anatomical stage."""
    merged: list[TraitDraft] = []
    for step in steps:
        _step_display, identity, explanation = split_process_step_content(
            step.summary or step.label or "",
            index=len(merged),
        )
        identity = _pick_identity_label(step.label or identity, identity)
        explanation = sanitize_process_production_text(
            step.summary or explanation,
            fallback=explanation,
            max_len=600,
        )
        if explanation.strip().lower() == identity.strip().lower():
            explanation = sanitize_process_production_text(
                step.narration or explanation,
                fallback=explanation,
                max_len=600,
            )
        candidate = TraitDraft(
            label=_clip(identity, 80),
            summary=_clip(explanation, 600),
            narration=sanitize_process_production_text(
                step.narration or _step_narration(identity, explanation, concept),
                fallback=_step_narration(identity, explanation, concept),
                max_len=400,
            ),
            kind="process",
        )

        if not merged:
            merged.append(candidate)
            continue

        if _should_merge_process_steps(merged[-1], candidate):
            prev = merged[-1]
            merged[-1] = TraitDraft(
                label=_clip(_pick_identity_label(prev.label, candidate.label), 80),
                summary=_clip(f"{prev.summary} {candidate.summary}".strip(), 600),
                narration=prev.narration or candidate.narration,
                kind="process",
            )
            continue

        if is_generic_stage_label(candidate.label) and not is_generic_stage_label(merged[-1].label):
            prev = merged[-1]
            merged[-1] = TraitDraft(
                label=prev.label,
                summary=_clip(f"{candidate.summary} {prev.summary}".strip(), 600),
                narration=prev.narration or candidate.narration,
                kind="process",
            )
            continue

        if is_generic_stage_label(merged[-1].label) and not is_generic_stage_label(candidate.label):
            prev = merged.pop()
            merged.append(
                TraitDraft(
                    label=candidate.label,
                    summary=_clip(f"{prev.summary} {candidate.summary}".strip(), 600),
                    narration=candidate.narration or prev.narration,
                    kind="process",
                ),
            )
            continue

        merged.append(candidate)

    return tuple(merged)


def extract_process_steps_from_rag(
    rag_context: str | None,
    concept: str,
    *,
    limit: int | None = None,
) -> tuple[tuple[TraitDraft, ...], ProcessStepExtractionStats]:
    """
    Build one coherent teaching unit per process step from RAG context.

    Filters placeholders, practice questions, and scaffold headers before node creation.
    """
    step_limit = limit if limit is not None else PROCESS_MAX_STEPS
    step_limit = min(step_limit, CIR_V1_MAX_NODES)
    raw_steps, stats = _parse_process_raw_blocks(rag_context)
    out: list[TraitDraft] = []

    for line in raw_steps:
        _step_display, identity, explanation = split_process_step_content(line, index=len(out))
        if is_prose_identity(identity):
            derived = split_process_step_content(explanation or line, index=len(out))[1]
            if not is_prose_identity(derived):
                identity = derived

        if not explanation or is_placeholder_text(explanation) or is_practice_or_support_content(explanation):
            stats = ProcessStepExtractionStats(
                filtered_placeholder_count=stats.filtered_placeholder_count + 1,
                filtered_practice_nodes=stats.filtered_practice_nodes,
                process_step_count=stats.process_step_count,
                process_scene_count=stats.process_scene_count,
                raw_line_count=stats.raw_line_count,
            )
            continue

        if is_placeholder_text(identity) or is_generic_stage_label(identity):
            if is_generic_stage_label(identity) and explanation:
                identity = split_process_step_content(explanation, index=len(out))[1]
            if is_placeholder_text(identity) or is_generic_stage_label(identity):
                stats = ProcessStepExtractionStats(
                    filtered_placeholder_count=stats.filtered_placeholder_count + 1,
                    filtered_practice_nodes=stats.filtered_practice_nodes,
                    process_step_count=stats.process_step_count,
                    process_scene_count=stats.process_scene_count,
                    raw_line_count=stats.raw_line_count,
                )
                continue

        narr = _step_narration(identity, explanation, concept)
        out.append(
            TraitDraft(
                label=_clip(identity, 80),
                summary=_clip(explanation, 600),
                narration=narr,
                kind="process",
            ),
        )
        if len(out) >= step_limit:
            break

    coalesced = coalesce_process_trait_steps(out, concept=concept)
    final_stats = ProcessStepExtractionStats(
        filtered_placeholder_count=stats.filtered_placeholder_count,
        filtered_practice_nodes=stats.filtered_practice_nodes,
        process_step_count=len(coalesced),
        process_scene_count=len(coalesced),
        raw_line_count=stats.raw_line_count,
    )
    return coalesced, final_stats


def filter_process_trait_steps(
    steps: tuple[TraitDraft, ...] | list[TraitDraft],
    *,
    concept: str,
) -> tuple[tuple[TraitDraft, ...], ProcessStepExtractionStats]:
    """Sanitize explicit/template process steps before plan build."""
    filtered: list[TraitDraft] = []
    placeholder_count = 0
    practice_count = 0

    for i, step in enumerate(steps):
        raw_label = (step.label or "").strip()
        raw_summary = (step.summary or step.narration or step.label or "").strip()

        if is_practice_or_support_content(raw_label) or is_practice_or_support_content(raw_summary):
            practice_count += 1
            continue

        combined = raw_summary or raw_label
        _step_display, identity, explanation = split_process_step_content(combined, index=i)
        if is_placeholder_text(identity) or is_placeholder_text(explanation):
            placeholder_count += 1
            continue

        narr = sanitize_process_production_text(
            step.narration or _step_narration(identity, explanation, concept),
            fallback=_step_narration(identity, explanation, concept),
            max_len=400,
        )
        filtered.append(
            TraitDraft(
                label=_clip(identity, 80),
                summary=_clip(explanation, 600),
                narration=narr,
                kind="process",
            ),
        )

    coalesced = coalesce_process_trait_steps(filtered, concept=concept)
    stats = ProcessStepExtractionStats(
        filtered_placeholder_count=placeholder_count,
        filtered_practice_nodes=practice_count,
        process_step_count=len(coalesced),
        process_scene_count=len(coalesced),
        raw_line_count=len(steps),
    )
    return coalesced, stats
