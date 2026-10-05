"""Semantic concept detection via sentence embeddings (lazy-loaded model)."""

from __future__ import annotations

import threading
from typing import Dict, List, Optional, Tuple

import numpy as np
from sklearn.metrics.pairwise import cosine_similarity

# SessionService uses this for updating current_concept vs keeping the previous value.
SIMILARITY_THRESHOLD = 0.5

_model = None
_model_lock = threading.Lock()

# (topic_id, tuple(concepts)) -> embedding matrix (n_concepts, dim)
_concept_matrix_cache: Dict[Tuple[str, Tuple[str, ...]], np.ndarray] = {}


def _get_model():
    global _model
    with _model_lock:
        if _model is None:
            from sentence_transformers import SentenceTransformer

            _model = SentenceTransformer("all-MiniLM-L6-v2")
        return _model


def get_embedding(text: str) -> List[float]:
    """Return a single L2-normalized embedding vector for the given text."""
    model = _get_model()
    vec = model.encode((text or "").strip(), normalize_embeddings=True)
    return np.asarray(vec).reshape(-1).tolist()


def find_best_concept_with_score(
    user_input: str,
    concepts: List[str],
    *,
    topic_id: Optional[str] = None,
) -> Tuple[Optional[str], float]:
    """
    Embed user_input and each concept; return the concept with highest cosine similarity
    and that score. Concepts list order is preserved; returned string is the original
    entry from that list (not normalized).
    """
    original: List[str] = []
    for c in concepts:
        s = str(c).strip()
        if s:
            original.append(s)
    if not original:
        return None, 0.0

    u_text = (user_input or "").strip()
    if not u_text:
        return None, 0.0

    model = _get_model()
    key = (topic_id or "", tuple(original))
    if key not in _concept_matrix_cache:
        mat = model.encode(original, normalize_embeddings=True)
        _concept_matrix_cache[key] = np.asarray(mat)
    mat = _concept_matrix_cache[key]

    u_emb = np.asarray(
        model.encode(u_text, normalize_embeddings=True)
    ).reshape(1, -1)
    sims = cosine_similarity(u_emb, mat)[0]
    idx = int(np.argmax(sims))
    return original[idx], float(sims[idx])


def find_best_concept(user_input: str, concepts: List[str]) -> Optional[str]:
    """Highest-similarity concept from the list, or None if concepts is empty."""
    c, _ = find_best_concept_with_score(user_input, concepts, topic_id=None)
    return c
