"""
Zone 1 only: central pedagogy → Timeline V3 payload finalization.

Merges timelines into ``session.zone1_timeline_cache`` for incremental beats and
attaches ``instruction_timeline_v3`` on outgoing tutor dicts. Does not alter
governor, SUS, zones, or flow semantics.

Zone 1 full-timeline authoring (when VTSE flags on):

  Authored vtse_template → TeachingPlan → VTSECompiler → CIR
  → TimelinePlannerV3 → InstructionTimelineV3

On VTSE authoring failure: text-only response (no invented generic board).
"""

from __future__ import annotations

import copy
import logging
import os
import re
from dataclasses import dataclass
from typing import Any, Literal

from app.cir.compile_to_timeline_v3 import compile_cir_v1_to_timeline
from app.cir.validate import validate_cir_v1
from app.services.handlers.board_native_narration import (
    sanitize_annotation_for_timeline,
    sanitize_narration_for_timeline,
)
from app.services.timeline_planner_v3 import TimelinePlannerResult, TimelinePlannerV3

logger = logging.getLogger(__name__)

Zone1Policy = Literal["full", "incremental", "none"]
VTSE_AUTHORING_PLANNER_SOURCE = "timeline_v3_from_vtse_authoring_v1"
VTSE_AUTHORING_FAILED_SOURCE = "vtse_authoring_failed"


_TIMELINE_ID_RE = re.compile(r"^tlm_[A-Za-z0-9]+$")


def mint_full_rebuild_timeline_id(base: str) -> str:
    """Unique id for a full zone-1 rebuild so a prior attempt cannot match.

    The frontend contract is ``tlm_`` plus alphanumerics and a single underscore.
    The attempt nonce is appended to that tail, not as a second ``_`` segment.
    """
    import secrets

    nonce = secrets.token_hex(4)
    root = str(base or "").strip()
    if _TIMELINE_ID_RE.fullmatch(root):
        return f"{root}{nonce}"
    return f"tlm_{nonce}"


def _v3_debug_logs_enabled() -> bool:
    raw = str(os.getenv("V3_DEBUG_LOGS", "") or "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _vtse_authoring_runtime_log(event: str, **kwargs: object) -> None:
    parts = [f"[VTSE_ZONE1] {event}"]
    for k, v in sorted(kwargs.items()):
        if v is None or v == "":
            continue
        parts.append(f"{k}={v}")
    logger.info(" ".join(parts))


def _cir_validation_failure_log(
    raw: Any,
    *,
    phase: str,
    errors: tuple[str, ...],
) -> None:
    rep = "?"
    n_nodes = n_edges = n_beats = 0
    if isinstance(raw, dict):
        rep = str(raw.get("representation_type") or "?")
        n_nodes = len(raw.get("nodes") or [])
        n_edges = len(raw.get("edges") or [])
        n_beats = len(raw.get("beats") or [])
    first = (errors[0] if errors else "")[:400]
    logger.warning(
        "[CIR_VALIDATION_FAILURE] phase=%s representation=%s nodes=%d edges=%d beats=%d first_error=%s",
        phase,
        rep,
        n_nodes,
        n_edges,
        n_beats,
        first,
    )


def _annotate_planner_result(
    base: TimelinePlannerResult,
    *,
    fallback_used: bool = False,
    llm_skip_reason: str | None = None,
    planner_source: str | None = None,
    authoring_debug: dict[str, Any] | None = None,
) -> TimelinePlannerResult:
    src = planner_source or base.planner_source
    dbg = dict(base.cir_instruction_debug or {})
    dbg["planner_source"] = src
    if llm_skip_reason is not None:
        dbg["llm_skip_reason"] = llm_skip_reason
    if fallback_used:
        dbg["fallback_used"] = True
        dbg["emergency_fallback_used"] = True
    else:
        dbg.setdefault("fallback_used", False)
        dbg.setdefault("emergency_fallback_used", False)
    if authoring_debug:
        dbg.update(authoring_debug)
    return TimelinePlannerResult(
        timeline=base.timeline,
        planner_source=src,
        cir_instruction_debug=dbg,
    )


def _zone1_vtse_authoring_failed(
    *,
    fallback_reason: str,
) -> TimelinePlannerResult:
    """Controlled VTSE failure: no timeline / no invented board (text-only)."""
    _vtse_authoring_runtime_log(
        "authoring_failed",
        planner_source=VTSE_AUTHORING_FAILED_SOURCE,
        fallback_reason=fallback_reason,
        no_emergency_generic=True,
    )
    return TimelinePlannerResult(
        timeline={},
        planner_source=VTSE_AUTHORING_FAILED_SOURCE,
        cir_instruction_debug={
            "planner_source": VTSE_AUTHORING_FAILED_SOURCE,
            "llm_skip_reason": fallback_reason,
            "using_vtse_authoring": False,
            "emergency_fallback_used": False,
            "fallback_used": False,
            "timeline_attached": False,
        },
    )


def cluster_context_snapshot_for_cir(session: Any) -> str:
    """Current cluster concept keys only — never the full topic cluster list."""
    raw = getattr(session, "concept_clusters", None)
    if not raw or not isinstance(raw, list):
        return ""
    ci = int(getattr(session, "current_cluster_index", 0) or 0)
    if ci < 0 or ci >= len(raw):
        return ""
    cluster = raw[ci]
    if not isinstance(cluster, list):
        return ""
    keys = [str(c).strip() for c in cluster if c is not None and str(c).strip()]
    return ", ".join(keys)[:500]


def _vtse_scoped_teaching_objective(
    *,
    zone: int,
    concept: str,
    teaching_objective: str | None,
) -> str:
    cc = (concept or "").strip() or "this concept"
    scope = (
        f"Zone {zone} — teach ONLY the concept '{cc}'. "
        "Use ONLY the curriculum notes supplied below for this concept. "
        "Do NOT introduce traits, examples, or review from other concepts or prior clusters."
    )
    extra = (teaching_objective or "").strip()
    return f"{scope}\n{extra}" if extra else scope


@dataclass(frozen=True)
class VtseConceptIdentity:
    """Resolved concept labels for VTSE (session key vs board anchor vs RAG lookup keys)."""

    session_concept: str
    anchor_label: str
    rag_lookup_keys: tuple[str, ...]
    concept_id: Any | None = None


def _subject_from_question_concept(concept: str) -> str:
    """Turn question-form runtime keys into a board-friendly subject phrase."""
    raw = (concept or "").strip().rstrip("?").strip()
    if not raw:
        return concept
    low = raw.lower()
    prefixes = (
        "what are the ",
        "what are ",
        "what is the ",
        "what is ",
        "how do the ",
        "how do ",
        "how does the ",
        "how does ",
        "why do ",
        "why does ",
        "name the ",
        "name ",
        "list the ",
        "list ",
        "describe the ",
        "describe ",
        "define the ",
        "define ",
    )
    for prefix in prefixes:
        if low.startswith(prefix):
            subject = raw[len(prefix) :].strip()
            if subject:
                return subject
            break
    return raw


def _board_anchor_label(concept: str) -> str:
    from app.vtse.authoring.content_filters import is_question_text

    cc = (concept or "").strip()
    if not cc:
        return "Main concept"
    if is_question_text(cc):
        subject = _subject_from_question_concept(cc)
        return subject[:1].upper() + subject[1:] if subject else cc
    return cc


def _append_rag_lookup_key(keys: list[str], value: str | None) -> None:
    from app.services.curriculum.curriculum_validators import normalize_runtime_key

    raw = (value or "").strip()
    if not raw:
        return
    candidates: list[str] = [raw]
    try:
        candidates.append(normalize_runtime_key(raw))
    except ValueError:
        candidates.append(raw.lower())
    for candidate in candidates:
        if candidate and candidate not in keys:
            keys.append(candidate)


async def resolve_vtse_concept_identity(
    *,
    session: Any,
    concept: str,
) -> VtseConceptIdentity:
    """
    Map session runtime keys (often questions) to display anchor + note lookup keys.
    """
    from app.repositories.curriculum_concept_repository import CurriculumConceptRepository
    from app.services.curriculum.curriculum_validators import normalize_runtime_key
    from app.vtse.authoring.content_filters import is_question_text

    session_concept = (concept or getattr(session, "current_concept", None) or "").strip()
    topic_id = getattr(session, "topic_id", None)
    org_id = getattr(session, "organization_id", None)
    lookup_keys: list[str] = []
    from app.services.session_concept_tracking import session_concept_id_for_rag

    concept_id = session_concept_id_for_rag(session)
    anchor = _board_anchor_label(session_concept)

    if session_concept:
        _append_rag_lookup_key(lookup_keys, session_concept)

    key_norm = ""
    if session_concept:
        try:
            key_norm = normalize_runtime_key(session_concept)
        except ValueError:
            key_norm = session_concept.lower()

    if topic_id is not None and concept_id is None:
        try:
            concept_repo = CurriculumConceptRepository()
            for source in ("teacher", "catalog"):
                for row in await concept_repo.list_by_topic(
                    topic_id,
                    source,
                    organization_id=org_id if source == "teacher" else None,
                ):
                    row_key = ""
                    row_display = ""
                    try:
                        row_key = normalize_runtime_key(row.canonical_runtime_key)
                    except ValueError:
                        row_key = str(row.canonical_runtime_key or "").strip().lower()
                    try:
                        row_display = normalize_runtime_key(row.display_name)
                    except ValueError:
                        row_display = str(row.display_name or "").strip().lower()
                    if key_norm and key_norm not in (row_key, row_display):
                        continue
                    concept_id = row.id
                    anchor = (
                        row.display_name or row.canonical_runtime_key or session_concept
                    ).strip()
                    if is_question_text(anchor):
                        anchor = _board_anchor_label(anchor)
                    _append_rag_lookup_key(lookup_keys, row.canonical_runtime_key)
                    _append_rag_lookup_key(lookup_keys, row.display_name)
                    break
                if concept_id is not None:
                    break
        except Exception:  # noqa: BLE001 — curriculum DB may be unavailable in unit tests
            pass

    if is_question_text(session_concept):
        derived = _board_anchor_label(session_concept)
        if derived:
            anchor = derived
            _append_rag_lookup_key(lookup_keys, derived)

    if not lookup_keys and session_concept:
        lookup_keys.append(session_concept)

    return VtseConceptIdentity(
        session_concept=session_concept,
        anchor_label=anchor[:80] if anchor else "Main concept",
        rag_lookup_keys=tuple(lookup_keys),
        concept_id=concept_id,
    )


def _cir_already_vtse_authored(dumped: dict[str, Any]) -> bool:
    vtse = (dumped.get("metadata") or {}).get("vtse") or {}
    if not isinstance(vtse, dict):
        return False
    return str(vtse.get("compiler_path") or "") == "teaching_plan_to_cir_v1"


def _compile_validated_cir(
    *,
    planner: TimelinePlannerV3,
    dumped: dict[str, Any],
    session_id: str,
    topic_id_str: str | None,
    concept: str,
    from_llm: bool,
) -> TimelinePlannerResult:
    from app.vtse.pipeline import apply_vtse_shell_to_cir_dict, stamp_timeline_vtse_metadata

    cir_for_compile = dumped
    vtse_obs = None
    if not _cir_already_vtse_authored(dumped):
        cir_for_compile, vtse_obs = apply_vtse_shell_to_cir_dict(
            dumped,
            session_id=session_id,
            topic_id=topic_id_str or "",
            concept_id=concept,
        )

    compiled = compile_cir_v1_to_timeline(
        cir=cir_for_compile,
        session_id=session_id,
        topic_id=topic_id_str,
        concept=concept,
        planner=planner,
        from_llm=from_llm,
    )
    tl = compiled.timeline
    if not isinstance(tl, dict) or not tl.get("timeline_id") or not tl.get("beats"):
        raise ValueError("compiled CIR timeline missing timeline_id or beats")
    if vtse_obs:
        stamp_timeline_vtse_metadata(tl, vtse_obs)
    if vtse_obs and isinstance(compiled.cir_instruction_debug, dict):
        dbg = dict(compiled.cir_instruction_debug)
        dbg["vtse"] = vtse_obs
        return TimelinePlannerResult(
            timeline=tl,
            planner_source=compiled.planner_source,
            cir_instruction_debug=dbg,
        )
    return TimelinePlannerResult(
        timeline=tl,
        planner_source=compiled.planner_source,
        cir_instruction_debug=compiled.cir_instruction_debug,
    )


async def _zone1_full_timeline_via_vtse_async(
    *,
    planner: TimelinePlannerV3,
    session: Any | None = None,
    session_id: str,
    topic_id_str: str | None,
    topic_name: str,
    concept: str,
    question: str,
    rag_service: Any | None = None,
    cir_rag_context: str | None = None,
    teaching_objective: str | None = None,
    cluster_context: str | None = None,
    student_profile_dict: dict[str, Any] | None = None,
) -> TimelinePlannerResult:
    """
    Zone 1 full timeline via authored VTSE; on failure return text-only (no board).
    """
    _ = question or ""

    from app.vtse.authoring.zone1 import try_zone1_vtse_authoring

    vtse_cir_rag_context = cir_rag_context
    vtse_teaching_objective = teaching_objective
    vtse_cluster_context = cluster_context
    vtse_concept = concept
    vtse_template: dict[str, Any] | None = None
    vtse_visuals: dict[str, Any] | None = None
    vtse_visual_concept_id = ""
    row = None
    if session is not None:
        identity = await resolve_vtse_concept_identity(session=session, concept=concept)
        vtse_concept = identity.anchor_label
        vtse_cluster_context = cluster_context_snapshot_for_cir(session)
        vtse_teaching_objective = _vtse_scoped_teaching_objective(
            zone=int(getattr(session, "current_zone", 1) or 1),
            concept=vtse_concept,
            teaching_objective=teaching_objective,
        )
        if identity.concept_id is not None:
            try:
                from app.repositories.curriculum_concept_repository import (
                    CurriculumConceptRepository,
                )
                from app.services.curriculum.concept_vtse_context import (
                    format_vtse_template_as_rag_context,
                )

                row = await CurriculumConceptRepository().get_by_id(identity.concept_id)
                raw_tmpl = getattr(row, "vtse_template", None) if row is not None else None
                from app.services.vtse_visuals.authored import frozen_vtse_visuals

                vtse_visuals = frozen_vtse_visuals(
                    session,
                    getattr(row, "vtse_visuals", None) if row is not None else None,
                )
                vtse_visual_concept_id = str(identity.concept_id)
                if isinstance(raw_tmpl, dict):
                    vtse_template = dict(raw_tmpl)
                    vtse_cir_rag_context = format_vtse_template_as_rag_context(
                        vtse_template,
                        concept_label=vtse_concept,
                        story_hook=getattr(row, "story_hook", None) if row else None,
                    ) or vtse_cir_rag_context
            except Exception:  # noqa: BLE001
                vtse_template = None

    continuity_card = None
    if session is not None:
        try:
            from app.services.pedagogy.teacher_voice import build_continuity_card

            continuity_card = build_continuity_card(
                concept=row,
                session=session,
                current_stage="vtse",
                concept_name=vtse_concept,
            )
        except Exception:  # noqa: BLE001
            continuity_card = None

    authored = await try_zone1_vtse_authoring(
        planner=planner,
        session_id=session_id,
        topic_id_str=topic_id_str,
        topic_name=topic_name,
        concept=vtse_concept,
        rag_service=rag_service,
        cir_rag_context=vtse_cir_rag_context,
        teaching_objective=vtse_teaching_objective,
        cluster_context=vtse_cluster_context,
        student_profile_dict=student_profile_dict,
        vtse_template=vtse_template,
        vtse_visuals=vtse_visuals if isinstance(vtse_visuals, dict) else None,
        vtse_visual_concept_id=vtse_visual_concept_id,
        compile_validated_cir=_compile_validated_cir,
        continuity=continuity_card,
    )
    if authored is not None:
        vtse_meta = (authored.cir_instruction_debug or {}).get("vtse") or {}
        strategy_id = vtse_meta.get("strategy_id") or vtse_meta.get("selected_strategy")
        _vtse_authoring_runtime_log(
            "success",
            using_vtse_authoring=True,
            legacy_authoring_removed=True,
            emergency_fallback_used=False,
            compiler_path=vtse_meta.get("compiler_path") or "teaching_plan_authoring_to_cir_v1",
            strategy_id=strategy_id or "?",
            planner_source=VTSE_AUTHORING_PLANNER_SOURCE,
        )
        dbg = dict(authored.cir_instruction_debug or {})
        dbg.update(
            {
                "using_vtse_authoring": True,
                "legacy_authoring_removed": True,
                "legacy_cir_llm_used": False,
                "emergency_fallback_used": False,
            },
        )
        return TimelinePlannerResult(
            timeline=authored.timeline,
            planner_source=VTSE_AUTHORING_PLANNER_SOURCE,
            cir_instruction_debug=dbg,
        )
    _vtse_authoring_runtime_log(
        "authoring_failed",
        using_vtse_authoring=False,
        detail="vtse_returned_none",
        no_emergency_generic=True,
    )
    return _zone1_vtse_authoring_failed(fallback_reason="vtse_authoring_failed")


# Backward-compatible alias for imports/tests
_zone1_full_timeline_via_cir_or_plan_async = _zone1_full_timeline_via_vtse_async


def clear_zone1_board_for_cluster_change(session: Any) -> None:
    setattr(session, "zone1_timeline_cache", None)
    ci = int(getattr(session, "current_cluster_index", 0) or 0)
    setattr(session, "zone1_board_cluster_index", ci)


def _normalize_zone1_concept_key(concept: str | None) -> str:
    """Stable concept key for cache ownership checks (case/whitespace tolerant)."""
    raw = str(concept or "").strip()
    if not raw:
        return ""
    return " ".join(raw.lower().split())


def _zone1_concepts_match(left: str | None, right: str | None) -> bool:
    lk = _normalize_zone1_concept_key(left)
    rk = _normalize_zone1_concept_key(right)
    return bool(lk and rk and lk == rk)


def clear_zone1_board_for_concept_change(session: Any, *, concept: str) -> None:
    """Drop cached timeline when the active key concept changes."""
    cc = str(concept or "").strip() or None
    prev = str(getattr(session, "zone1_board_concept_id", None) or "").strip() or None
    if prev and cc and _zone1_concepts_match(prev, cc):
        return
    setattr(session, "zone1_timeline_cache", None)
    setattr(session, "zone1_board_concept_id", cc)


def reset_zone1_timeline_board(session: Any) -> None:
    setattr(session, "zone1_timeline_cache", None)
    setattr(session, "zone1_board_cluster_index", None)
    setattr(session, "zone1_board_concept_id", None)


def _cached_timeline_concept_id(cache: dict[str, Any] | None) -> str:
    if not isinstance(cache, dict):
        return ""
    return str(cache.get("concept_id") or "").strip()


def _concept_transition_detected(session: Any, concept: str, cache: dict[str, Any] | None) -> bool:
    cc_key = _normalize_zone1_concept_key(concept)
    if not cc_key:
        return False
    cached_from_timeline = _cached_timeline_concept_id(cache)
    if cached_from_timeline and not _zone1_concepts_match(cached_from_timeline, concept):
        return True
    board_concept = str(getattr(session, "zone1_board_concept_id", None) or "").strip()
    return bool(board_concept and not _zone1_concepts_match(board_concept, concept))


def _cache_usable_for_concept(cache: dict[str, Any] | None, concept: str) -> bool:
    if not isinstance(cache, dict) or not cache.get("beats"):
        return False
    cached_concept = _cached_timeline_concept_id(cache)
    if not cached_concept:
        return True
    return _zone1_concepts_match(cached_concept, concept)


def _stamp_zone1_finalize_observability(
    out: dict[str, Any],
    *,
    timeline_attached: bool,
    fallback_reason: str | None = None,
    zone1_policy: Zone1Policy | None = None,
    planner_source: str | None = None,
    vtse_pipeline_entered: bool = False,
    vtse_pipeline_completed: bool = False,
    timeline_compile_success: bool = False,
    timeline_payload_size: int = 0,
    instruction_timeline_v3_present: bool = False,
    extra_debug: dict[str, Any] | None = None,
) -> dict[str, Any]:
    dbg = dict(out.get("cir_instruction_debug") or {})
    dbg.update(
        {
            "timeline_attached": timeline_attached,
            "timeline_compile_success": timeline_compile_success,
            "timeline_payload_size": timeline_payload_size,
            "instruction_timeline_v3_present": instruction_timeline_v3_present,
            "vtse_pipeline_entered": vtse_pipeline_entered,
            "vtse_pipeline_completed": vtse_pipeline_completed,
            "fallback_reason": fallback_reason,
        },
    )
    if zone1_policy is not None:
        dbg["zone1_policy"] = zone1_policy
    if planner_source is not None:
        dbg["planner_source"] = planner_source
    if isinstance(extra_debug, dict):
        dbg.update(extra_debug)
    out["cir_instruction_debug"] = dbg
    return out


def _attach_recovered_zone1_timeline(
    session: Any,
    out: dict[str, Any],
    *,
    cache: dict[str, Any],
    policy: Zone1Policy,
    beat_kind: str,
    prior_beat_count: int,
    fallback_reason: str,
    forced_full_reason: str | None,
    concept_transition: bool,
) -> dict[str, Any]:
    merged = copy.deepcopy(cache)
    setattr(session, "zone1_timeline_cache", merged)
    setattr(session, "zone1_board_concept_id", str(_cached_timeline_concept_id(cache) or "").strip() or None)
    out["instruction_timeline_v3"] = merged
    src = str((out.get("planner_source") or "timeline_v3_cache_recovery"))
    timeline_meta: dict[str, Any] = {
        "planner_source": src,
        "zone1_policy": policy,
        "beat_kind": beat_kind,
        "board_native_language": True,
        "timeline_rebuild_scope": "cache_recovery",
        "concept_transition_detected": concept_transition,
        "forced_full_rebuild_reason": forced_full_reason,
        "timeline_cache_recovered": True,
    }
    out["timeline_metadata"] = timeline_meta
    out["planner_source"] = src
    out = _apply_board_native_instruction_payload(
        out, policy=policy, prior_beat_count=prior_beat_count
    )
    beats = len(merged.get("beats") or [])
    logger.warning(
        "[ZONE1_TIMELINE] cache_recovery beat_kind=%s policy=%s reason=%s timeline_id=%s beats=%d",
        beat_kind,
        policy,
        fallback_reason,
        str(merged.get("timeline_id") or ""),
        beats,
    )
    return _stamp_zone1_finalize_observability(
        out,
        timeline_attached=True,
        fallback_reason=fallback_reason,
        zone1_policy=policy,
        planner_source=src,
        vtse_pipeline_entered=True,
        vtse_pipeline_completed=False,
        timeline_compile_success=False,
        timeline_payload_size=beats,
        instruction_timeline_v3_present=True,
        extra_debug={
            "timeline_cache_recovered": True,
            "concept_transition_detected": concept_transition,
            "forced_full_rebuild_reason": forced_full_reason,
        },
    )


def _cluster_scope_ok(session: Any) -> bool:
    cached = getattr(session, "zone1_board_cluster_index", None)
    if cached is None:
        return True
    return int(cached) == int(getattr(session, "current_cluster_index", 0) or 0)


def _extract_node_entity_ids(timeline: dict[str, Any] | None) -> list[str]:
    if not isinstance(timeline, dict):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for beat in timeline.get("beats") or []:
        if not isinstance(beat, dict):
            continue
        for op in beat.get("operations") or []:
            if not isinstance(op, dict) or op.get("op_type") != "add_entity":
                continue
            payload = op.get("payload") or {}
            ent = payload.get("entity") if isinstance(payload, dict) else None
            if not isinstance(ent, dict):
                continue
            eid = ent.get("entity_id")
            if eid and str(eid) not in seen:
                seen.add(str(eid))
                out.append(str(eid))
    return out


def _apply_board_native_instruction_payload(
    out: dict[str, Any],
    *,
    policy: Zone1Policy,
    prior_beat_count: int,
) -> dict[str, Any]:
    if not isinstance(out.get("instruction_timeline_v3"), dict):
        return out
    meta = dict(out.get("timeline_metadata") or {})
    meta["instruction_display_mode"] = "board_only"
    if policy == "incremental" and prior_beat_count > 0:
        meta["playback_start_beat_index"] = prior_beat_count
    out["timeline_metadata"] = meta
    if str(out.get("message") or "").strip():
        out["message"] = ""
    return out


def merge_zone1_timeline_fragments(
    base: dict[str, Any] | None,
    fragment: dict[str, Any],
) -> dict[str, Any]:
    frag = copy.deepcopy(fragment)
    if not isinstance(frag, dict) or not frag.get("timeline_id"):
        return frag if isinstance(frag, dict) else {}
    if not isinstance(base, dict) or not base.get("beats"):
        return frag

    tid_b = str(base.get("timeline_id") or "")
    tid_f = str(frag.get("timeline_id") or "")
    if tid_b and tid_f and tid_b != tid_f:
        return frag

    merged = copy.deepcopy(base)
    base_beats = list(merged.get("beats") or [])
    seen = {str(b.get("beat_id")) for b in base_beats if isinstance(b, dict) and b.get("beat_id")}
    for b in frag.get("beats") or []:
        if not isinstance(b, dict):
            continue
        bid = str(b.get("beat_id") or "")
        if bid and bid not in seen:
            base_beats.append(copy.deepcopy(b))
            seen.add(bid)
    merged["beats"] = base_beats
    return merged


def decide_zone1_timeline_policy(
    *,
    beat_kind: str,
    session: Any,
    message: str,
    topic_name: str,
    concept: str,
    question: str,
    planner: TimelinePlannerV3,
    micro: dict[str, Any] | None,
) -> Zone1Policy:
    if int(getattr(session, "current_zone", 0) or 0) not in (1, 2):
        return "none"

    if beat_kind in {"quiz_light", "teachback_light"}:
        c = getattr(session, "zone1_timeline_cache", None)
        return "incremental" if isinstance(c, dict) and c.get("beats") else "none"

    cache = getattr(session, "zone1_timeline_cache", None)
    cc_norm = str(concept or "").strip()

    if _concept_transition_detected(session, concept, cache if isinstance(cache, dict) else None):
        return "full"

    if beat_kind == "opening":
        return "full"

    if not isinstance(cache, dict) or not cache.get("beats"):
        return "full"
    if not _cluster_scope_ok(session):
        return "full"

    msg = message or ""
    wc = len(msg.split())

    if beat_kind == "explain_turn":
        return "incremental" if wc < 38 else "full"

    if beat_kind == "micro_reply":
        cache = getattr(session, "zone1_timeline_cache", None)
        if isinstance(cache, dict) and cache.get("beats"):
            return "incremental"
        return "full"

    return "none"


async def finalize_zone1_tutor_payload(
    session: Any,
    out: dict[str, Any],
    *,
    beat_kind: str,
    topic_name: str,
    concept: str,
    question: str,
    planner: TimelinePlannerV3,
    micro: dict[str, Any] | None = None,
    rag_service: Any | None = None,
    cir_rag_context: str | None = None,
    teaching_objective: str | None = None,
    cluster_context: str | None = None,
    student_profile_dict: dict[str, Any] | None = None,
) -> dict[str, Any]:
    msg = str(out.get("message") or "")
    policy = decide_zone1_timeline_policy(
        beat_kind=beat_kind,
        session=session,
        message=msg,
        topic_name=topic_name,
        concept=concept,
        question=question,
        planner=planner,
        micro=micro,
    )
    if policy == "none":
        if _v3_debug_logs_enabled():
            logger.info("[V3_DEBUG] zone1_finalize policy=none beat_kind=%s", beat_kind)
        return _stamp_zone1_finalize_observability(
            out,
            timeline_attached=False,
            fallback_reason="zone1_policy_none",
            zone1_policy=policy,
            instruction_timeline_v3_present=isinstance(out.get("instruction_timeline_v3"), dict),
            extra_debug={"beat_kind": beat_kind},
        )

    session_id = str(getattr(session, "id", "") or "")
    topic_oid = getattr(session, "topic_id", None)
    topic_id_str = str(topic_oid) if topic_oid is not None else None

    if beat_kind == "opening":
        if not _cluster_scope_ok(session):
            clear_zone1_board_for_cluster_change(session)
        clear_zone1_board_for_concept_change(session, concept=concept)

    cache_raw = getattr(session, "zone1_timeline_cache", None)
    cache = copy.deepcopy(cache_raw) if isinstance(cache_raw, dict) else None
    recoverable_cache = (
        copy.deepcopy(cache_raw)
        if _cache_usable_for_concept(cache_raw if isinstance(cache_raw, dict) else None, concept)
        else None
    )
    prior_beat_count = len((cache or {}).get("beats") or []) if isinstance(cache, dict) else 0
    new_fragment: dict[str, Any] | None = None
    planner_source: str | None = None
    resolve_result: TimelinePlannerResult | None = None
    incremental_narration_meta: dict[str, Any] | None = None
    forced_full_reason: str | None = None
    concept_transition = _concept_transition_detected(
        session,
        concept,
        cache if isinstance(cache, dict) else None,
    )
    if concept_transition:
        cache = None
        recoverable_cache = None
        forced_full_reason = "concept_transition"
    elif policy == "full" and beat_kind == "opening":
        forced_full_reason = "concept_opening"

    vtse_pipeline_entered = True
    try:
        if policy == "full":
            prior_cc = str((cache or {}).get("concept_id") or "")
            if cache and prior_cc and not _zone1_concepts_match(prior_cc, concept):
                cache = None
                forced_full_reason = forced_full_reason or "concept_id_mismatch"
            resolve_result = await _zone1_full_timeline_via_vtse_async(
                planner=planner,
                session=session,
                session_id=session_id,
                topic_id_str=topic_id_str,
                topic_name=topic_name,
                concept=concept,
                question=question or msg[:2000],
                rag_service=rag_service,
                cir_rag_context=cir_rag_context,
                teaching_objective=teaching_objective,
                cluster_context=cluster_context,
                student_profile_dict=student_profile_dict,
            )
            new_fragment = resolve_result.timeline
            planner_source = resolve_result.planner_source
        else:
            if not isinstance(cache, dict) or not cache.get("beats"):
                resolve_result = await _zone1_full_timeline_via_vtse_async(
                    planner=planner,
                    session=session,
                    session_id=session_id,
                    topic_id_str=topic_id_str,
                    topic_name=topic_name,
                    concept=concept,
                    question=question or msg[:2000],
                    rag_service=rag_service,
                    cir_rag_context=cir_rag_context,
                    teaching_objective=teaching_objective,
                    cluster_context=cluster_context,
                    student_profile_dict=student_profile_dict,
                )
                new_fragment = resolve_result.timeline
                planner_source = resolve_result.planner_source
            else:
                nodes = _extract_node_entity_ids(cache)
                if not nodes:
                    resolve_result = await _zone1_full_timeline_via_vtse_async(
                        planner=planner,
                        session=session,
                        session_id=session_id,
                        topic_id_str=topic_id_str,
                        topic_name=topic_name,
                        concept=concept,
                        question=question or msg[:2000],
                        rag_service=rag_service,
                        cir_rag_context=cir_rag_context,
                        teaching_objective=teaching_objective,
                        cluster_context=cluster_context,
                        student_profile_dict=student_profile_dict,
                    )
                    new_fragment = resolve_result.timeline
                    planner_source = resolve_result.planner_source
                else:
                    md = micro or {}
                    prev_rounds = int(md.get("prev_rounds", 0) or 0)
                    focus = nodes[prev_rounds % len(nodes)]
                    mc_action = str(md.get("mc_action") or "")
                    if mc_action == "re_explain":
                        goal = "Recovery: re-ground the idea on the board"
                    elif mc_action == "probe":
                        goal = "Socratic probe — focus before the question"
                    elif md.get("force_exit"):
                        goal = "Micro-loop closure — highlight takeaway"
                    else:
                        goal = "Teaching exchange — connect to prior nodes"
                    beat_idx = len(cache.get("beats") or [])
                    narration, narr_meta = sanitize_narration_for_timeline(
                        msg,
                        fallback=goal,
                        max_len=800,
                        variation_seed=beat_idx,
                        narration_source="micro_llm_incremental",
                    )
                    ann, ann_meta = sanitize_annotation_for_timeline(
                        msg,
                        fallback=goal,
                        max_len=220,
                        variation_seed=beat_idx + 1,
                    )
                    incremental_narration_meta = {
                        **narr_meta,
                        "annotation_sanitized": ann_meta.get("narration_sanitized"),
                        "annotation_legacy_terms_removed": ann_meta.get(
                            "legacy_diagram_terms_removed"
                        ),
                    }
                    resolve_result = planner.plan_zone1_incremental(
                        prior_timeline=cache,
                        next_beat_index=len(cache.get("beats") or []),
                        goal=goal,
                        narration=narration,
                        focus_entity_id=focus,
                        annotation_text=ann,
                    )
                    new_fragment = resolve_result.timeline
                    planner_source = resolve_result.planner_source
    except Exception as exc:  # noqa: BLE001
        logger.exception("[V3_DEBUG] zone1_finalize planner_failed beat_kind=%s", beat_kind)
        if isinstance(recoverable_cache, dict) and recoverable_cache.get("beats"):
            return _attach_recovered_zone1_timeline(
                session,
                out,
                cache=recoverable_cache,
                policy=policy,
                beat_kind=beat_kind,
                prior_beat_count=prior_beat_count,
                fallback_reason="planner_exception",
                forced_full_reason=forced_full_reason,
                concept_transition=concept_transition,
            )
        return _stamp_zone1_finalize_observability(
            out,
            timeline_attached=False,
            fallback_reason="planner_exception",
            zone1_policy=policy,
            vtse_pipeline_entered=vtse_pipeline_entered,
            vtse_pipeline_completed=False,
            timeline_compile_success=False,
            instruction_timeline_v3_present=False,
            extra_debug={
                "beat_kind": beat_kind,
                "planner_error": str(exc)[:500],
                "concept_transition_detected": concept_transition,
                "forced_full_rebuild_reason": forced_full_reason,
            },
        )

    if not isinstance(new_fragment, dict) or not new_fragment.get("timeline_id"):
        if isinstance(recoverable_cache, dict) and recoverable_cache.get("beats"):
            return _attach_recovered_zone1_timeline(
                session,
                out,
                cache=recoverable_cache,
                policy=policy,
                beat_kind=beat_kind,
                prior_beat_count=prior_beat_count,
                fallback_reason="timeline_compile_missing",
                forced_full_reason=forced_full_reason,
                concept_transition=concept_transition,
            )
        logger.warning(
            "[ZONE1_TIMELINE] missing_timeline beat_kind=%s policy=%s concept=%s",
            beat_kind,
            policy,
            str(concept or "")[:120],
        )
        fail_dbg = dict((resolve_result.cir_instruction_debug if resolve_result else None) or {})
        if planner_source:
            fail_dbg.setdefault("planner_source", planner_source)
        fail_dbg.update(
            {
                "beat_kind": beat_kind,
                "concept_transition_detected": concept_transition,
                "forced_full_rebuild_reason": forced_full_reason,
            },
        )
        return _stamp_zone1_finalize_observability(
            out,
            timeline_attached=False,
            fallback_reason="timeline_compile_missing",
            zone1_policy=policy,
            planner_source=planner_source,
            vtse_pipeline_entered=vtse_pipeline_entered,
            vtse_pipeline_completed=False,
            timeline_compile_success=False,
            instruction_timeline_v3_present=False,
            extra_debug=fail_dbg,
        )

    merged = (
        merge_zone1_timeline_fragments(None, new_fragment)
        if policy == "full"
        else merge_zone1_timeline_fragments(cache, new_fragment)
    )
    if policy == "full" and isinstance(merged, dict):
        # Same-concept reteach reuses a stable hash id. A per-rebuild nonce
        # lets board-checkpoint and stage_done reject late prior-attempt writes.
        base = str(merged.get("timeline_id") or "tlm").strip() or "tlm"
        merged = {**merged, "timeline_id": mint_full_rebuild_timeline_id(base)}
    prev_tid = str((cache or {}).get("timeline_id") or "") if isinstance(cache, dict) else ""
    new_tid = str(merged.get("timeline_id") or "")
    if policy == "full" or (prev_tid and new_tid and prev_tid != new_tid):
        setattr(session, "zone1_last_completed_beat_index", None)
    setattr(session, "zone1_timeline_cache", merged)
    setattr(
        session,
        "zone1_board_cluster_index",
        int(getattr(session, "current_cluster_index", 0) or 0),
    )
    setattr(session, "zone1_board_concept_id", str(concept or "").strip() or None)
    out["instruction_timeline_v3"] = merged
    src = planner_source or "timeline_v3_native"
    beat_count = len(merged.get("beats") or [])
    timeline_meta: dict[str, Any] = {
        "planner_source": src,
        "zone1_policy": policy,
        "beat_kind": beat_kind,
        "board_native_language": True,
        "timeline_rebuild_scope": "full" if policy == "full" else "incremental",
        "concept_transition_detected": concept_transition,
        "forced_full_rebuild_reason": forced_full_reason,
    }
    if isinstance(incremental_narration_meta, dict):
        timeline_meta.update(incremental_narration_meta)
    out["timeline_metadata"] = timeline_meta
    out["planner_source"] = src
    out = _apply_board_native_instruction_payload(
        out, policy=policy, prior_beat_count=prior_beat_count
    )
    dbg = dict((resolve_result.cir_instruction_debug if resolve_result else None) or {})
    dbg.setdefault("planner_source", src)
    dbg["board_native_language"] = True
    dbg["timeline_rebuild_scope"] = timeline_meta.get("timeline_rebuild_scope")
    dbg["concept_transition_detected"] = concept_transition
    dbg["forced_full_rebuild_reason"] = forced_full_reason
    vtse_obs = dbg.get("vtse") if isinstance(dbg.get("vtse"), dict) else {}
    if isinstance(vtse_obs, dict):
        dbg["previous_strategy_id"] = vtse_obs.get("strategy_id")
    if isinstance(incremental_narration_meta, dict):
        dbg.update(incremental_narration_meta)
    out["cir_instruction_debug"] = dbg
    vtse_obs = dbg.get("vtse") if isinstance(dbg.get("vtse"), dict) else {}
    out = _stamp_zone1_finalize_observability(
        out,
        timeline_attached=True,
        zone1_policy=policy,
        planner_source=src,
        vtse_pipeline_entered=vtse_pipeline_entered,
        vtse_pipeline_completed=True,
        timeline_compile_success=True,
        timeline_payload_size=beat_count,
        instruction_timeline_v3_present=True,
        extra_debug={
            "strategy_id": vtse_obs.get("strategy_id") if isinstance(vtse_obs, dict) else None,
            "representation_type": vtse_obs.get("representation_type")
            if isinstance(vtse_obs, dict)
            else None,
            "concept_transition_detected": concept_transition,
            "forced_full_rebuild_reason": forced_full_reason,
            "beat_kind": beat_kind,
        },
    )
    if _v3_debug_logs_enabled():
        logger.info(
            "[V3_DEBUG] zone1_finalize policy=%s beat_kind=%s timeline_id=%s beats=%d "
            "timeline_attached=true instruction_timeline_v3_present=true",
            policy,
            beat_kind,
            str(merged.get("timeline_id", "")),
            beat_count,
        )
    return out
