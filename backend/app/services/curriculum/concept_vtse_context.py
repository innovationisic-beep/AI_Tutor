"""Build RAG-style context strings from authored VTSE templates (not TopicNotes)."""

from __future__ import annotations

from typing import Any, Optional

from beanie.odm.fields import PydanticObjectId

from app.services.curriculum.concept_teaching_sequence import normalize_story_hook
from app.services.curriculum.concept_vtse_template import (
    ConceptVtseTemplate,
    normalize_vtse_template,
    vtse_template_strategy_label,
)


def format_vtse_template_as_rag_context(
    template: ConceptVtseTemplate | dict[str, Any] | None,
    *,
    concept_label: str = "",
    story_hook: Any = None,
) -> str:
    """
    Turn an authored VTSE template into a notes-like context string for LLM grounding.

    Returns empty string when template is missing/invalid.
    """
    try:
        tmpl = (
            template
            if isinstance(template, ConceptVtseTemplate)
            else normalize_vtse_template(template)
        )
    except Exception:  # noqa: BLE001
        tmpl = None
    if tmpl is None:
        return ""

    label = (concept_label or "").strip() or "Concept"
    strategy = vtse_template_strategy_label(tmpl.strategy_id) or tmpl.strategy_id
    lines: list[str] = [
        f"Concept: {label}",
        f"VTSE template: {strategy}",
        "Authored teaching outline (source of truth — expand in teacher language, do not invent new points):",
    ]

    payload = tmpl.payload or {}
    if tmpl.strategy_id == "comparison_contrast":
        left = str(payload.get("left_label") or "Left").strip()
        right = str(payload.get("right_label") or "Right").strip()
        lines.append(f"Comparison: {left} vs {right}")
        for i, row in enumerate(payload.get("rows") or [], start=1):
            if not isinstance(row, dict):
                continue
            dim = str(row.get("dimension") or f"Point {i}").strip()
            left_d = str(
                row.get("left_detail") or row.get("left") or ""
            ).strip()
            right_d = str(
                row.get("right_detail") or row.get("right") or ""
            ).strip()
            lines.append(f"{i}. [{dim}] {left}: {left_d}")
            lines.append(f"   {right}: {right_d}")
    else:
        steps = list(payload.get("steps") or [])
        for i, step in enumerate(steps, start=1):
            if isinstance(step, str):
                lines.append(f"{i}. {step.strip()}")
                continue
            if not isinstance(step, dict):
                continue
            title = str(step.get("label") or step.get("title") or f"Point {i}").strip()
            detail = str(
                step.get("summary") or step.get("annotation") or step.get("detail") or ""
            ).strip()
            if detail and detail != title:
                lines.append(f"{i}. {title} — {detail}")
            else:
                lines.append(f"{i}. {title}")

    hook = normalize_story_hook(story_hook)
    if hook is not None:
        lines.append("")
        lines.append("Story hook (optional narrative framing):")
        if hook.title.strip():
            lines.append(f"Title: {hook.title.strip()}")
        if hook.body.strip():
            lines.append(hook.body.strip())

    return "\n".join(lines).strip()


async def load_concept_vtse_rag_context(
    concept_id: PydanticObjectId | None,
    *,
    concept_label: str = "",
) -> str:
    """Load a curriculum concept and format its VTSE template as RAG context."""
    if concept_id is None:
        return ""
    try:
        from app.repositories.curriculum_concept_repository import (
            CurriculumConceptRepository,
        )

        row = await CurriculumConceptRepository().get_by_id(concept_id)
    except Exception:  # noqa: BLE001
        return ""
    if row is None:
        return ""
    label = concept_label or getattr(row, "display_name", None) or ""
    return format_vtse_template_as_rag_context(
        getattr(row, "vtse_template", None),
        concept_label=str(label),
        story_hook=getattr(row, "story_hook", None),
    )


def soft_normalize_vtse_template(raw: Any) -> Optional[ConceptVtseTemplate]:
    """Normalize without raising — for validation/listing paths."""
    try:
        return normalize_vtse_template(raw)
    except Exception:  # noqa: BLE001
        return None
