"""Keep session concept strings and MongoDB concept ids aligned."""

from __future__ import annotations

from typing import Any

from beanie.odm.fields import PydanticObjectId


def session_concept_id_for_rag(session: Any) -> PydanticObjectId | None:
    """Primary concept id for RAG — explicit field, else index into key_concept_ids."""
    cid = getattr(session, "current_concept_id", None)
    if cid is not None:
        return cid
    idx = int(getattr(session, "current_concept_index", 0) or 0)
    return concept_id_at_index(session, idx)


def concept_id_at_index(session: Any, index: int) -> PydanticObjectId | None:
    ids = list(getattr(session, "key_concept_ids", None) or [])
    if 0 <= index < len(ids):
        return ids[index]
    return None


def sync_session_concept_fields(session: Any, *, index: int | None = None) -> None:
    """
    Align ``current_concept_index``, ``current_concept``, and ``current_concept_id``.

    Call after changing the concept index so string keys and Mongo ids stay paired.
    """
    idx = int(getattr(session, "current_concept_index", 0) or 0)
    if index is not None:
        idx = int(index)
        session.current_concept_index = idx

    kc = [str(c).strip() for c in (getattr(session, "key_concepts", None) or []) if str(c).strip()]
    if idx < len(kc):
        session.current_concept = kc[idx][:500]
    else:
        session.current_concept = None

    cid = concept_id_at_index(session, idx)
    session.current_concept_id = cid


def session_manifest_concept_ids(manifest: Any) -> list[PydanticObjectId]:
    raw = getattr(manifest, "concept_ids_ordered", None) or []
    return [cid for cid in raw if cid is not None]
