"""
Concept cluster utilities — pure, stateless helpers.

Clusters are an optional GROUPING LAYER over key_concepts.  They are never a
replacement for key_concepts; the flat concept sequence remains canonical.

Phase 1 contract:
  * resolve_clusters  — returns the cluster structure (list of lists) from a
                        session snapshot or auto-derives it when absent.
  * derive_current_cluster_index — maps a flat concept index to a cluster index.

Neither function modifies session state.  Both are deterministic given the same
inputs, making them safe to call freely in read paths.
"""

from __future__ import annotations

import math
from typing import Optional


# ── Cluster auto-derivation parameters ───────────────────────────────────────
_MIN_CHUNK = 3
_MAX_CHUNK = 5
_TARGET_CHUNK = 4  # preferred cluster size when auto-generating


def resolve_clusters(
    key_concepts: list[str],
    concept_clusters: Optional[list[list[str]]] = None,
) -> list[list[str]]:
    """
    Return the cluster structure for a concept list.

    Priority:
      1. If ``concept_clusters`` is provided and non-empty, use it as-is.
         Assumes the caller has already validated that the clusters cover the
         same concepts as ``key_concepts`` (no enforcement here — Phase 1 is
         purely additive).
      2. Otherwise, auto-group ``key_concepts`` into chunks of ``_TARGET_CHUNK``
         (3–5 concepts each), preserving order.

    Args:
        key_concepts:     The canonical flat concept list from the session/topic.
        concept_clusters: Optional explicit cluster snapshot (from session or topic).

    Returns:
        A list of clusters, each cluster being a non-empty list of concept strings.
        Returns ``[[]]`` (a single empty cluster) only when ``key_concepts`` is
        empty — callers should guard against an empty concept list before calling.
    """
    # Use explicit clusters when they exist and are non-empty.
    if concept_clusters:
        # Filter out any empty inner lists for robustness.
        valid = [c for c in concept_clusters if c]
        if valid:
            return valid

    # Auto-derive: chunk key_concepts into groups of _TARGET_CHUNK.
    kc = [c for c in key_concepts if c]  # drop empty strings
    if not kc:
        return []

    n = len(kc)
    if n <= _MAX_CHUNK:
        # Fits in a single cluster.
        return [kc]

    # Compute number of clusters such that each has _MIN_CHUNK ≤ size ≤ _MAX_CHUNK.
    num_clusters = math.ceil(n / _TARGET_CHUNK)
    # Distribute concepts as evenly as possible.
    base_size, remainder = divmod(n, num_clusters)
    clusters: list[list[str]] = []
    idx = 0
    for i in range(num_clusters):
        size = base_size + (1 if i < remainder else 0)
        clusters.append(kc[idx : idx + size])
        idx += size
    return clusters


def derive_current_cluster_index(
    current_concept_index: int,
    clusters: list[list[str]],
) -> int:
    """
    Map a flat concept index to its enclosing cluster index.

    Iterates through clusters accumulating concept counts until it reaches
    the cluster that contains ``current_concept_index``.

    Args:
        current_concept_index: Zero-based index into the flat key_concepts list.
        clusters:              The resolved cluster structure (from resolve_clusters).

    Returns:
        Zero-based cluster index.  Returns 0 for an empty cluster list or a
        non-positive concept index.  Clamps to the last cluster if the concept
        index exceeds the total number of concepts.
    """
    if not clusters or current_concept_index <= 0:
        return 0

    cumulative = 0
    for cluster_idx, cluster in enumerate(clusters):
        cumulative += len(cluster)
        if current_concept_index < cumulative:
            return cluster_idx

    # concept_index exceeds total concepts — clamp to last cluster.
    return len(clusters) - 1


def flat_index_is_first_in_its_cluster(
    flat_index: int,
    clusters: list[list[str]],
) -> bool:
    """
    True when ``flat_index`` is the first concept inside its cluster (start of a cluster).
    Index 0 is always first in the first cluster.
    """
    if flat_index <= 0:
        return True
    if not clusters:
        return True
    acc = 0
    for cl in clusters:
        if not cl:
            continue
        start = acc
        acc += len(cl)
        if start <= flat_index < acc:
            return flat_index == start
    return True


def flat_index_is_last_in_its_cluster(
    flat_index: int,
    clusters: list[list[str]],
) -> bool:
    """
    True when ``flat_index`` points to the last concept inside its cluster
    (not necessarily the last concept in the topic).
    """
    if not clusters or flat_index < 0:
        return False
    acc = 0
    for cl in clusters:
        if not cl:
            continue
        acc += len(cl)
        if flat_index < acc:
            return flat_index == acc - 1
    return False


def sync_current_cluster_index(
    *,
    key_concepts: list[str],
    concept_clusters: Optional[list[list[str]]],
    current_concept_index: int,
) -> int:
    """Return cluster index for the current flat concept index (0-based)."""
    clusters = resolve_clusters(key_concepts, concept_clusters)
    if not clusters:
        return 0
    return derive_current_cluster_index(int(current_concept_index or 0), clusters)
