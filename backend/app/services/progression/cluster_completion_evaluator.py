from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List, Optional

from beanie.odm.fields import PydanticObjectId

from app.models.learning.sessions import Session
from app.services.handlers.cluster_utils import derive_current_cluster_index, resolve_clusters
from app.services.progression.plan_session_cluster_registry import AssignedCluster


@dataclass
class ClusterGateStatus:
    teaching_complete: bool
    quiz_complete: bool
    teachback_complete: bool
    zone_gates_passed: bool

    @property
    def is_complete(self) -> bool:
        return (
            self.teaching_complete
            and self.quiz_complete
            and self.teachback_complete
            and self.zone_gates_passed
        )


class ClusterCompletionEvaluator:
    """
    A cluster is complete when all runtime gates have passed.

    Production signal: cluster teachback pass (implies teaching + quiz + teachback).
  Zone gates: clarity gate not blocking progression for assigned slice.
    """

    def evaluate_gates(
        self,
        session: Session,
        *,
        assigned: AssignedCluster,
    ) -> ClusterGateStatus:
        clusters = resolve_clusters(
            list(session.key_concepts or []),
            getattr(session, "concept_clusters", None),
        )
        if assigned.cluster_index >= len(clusters):
            return ClusterGateStatus(False, False, False, False)

        cluster_keys = clusters[assigned.cluster_index]
        if not cluster_keys:
            return ClusterGateStatus(False, False, False, False)

        kc = list(session.key_concepts or [])
        try:
            first_idx = kc.index(cluster_keys[0])
            last_idx = kc.index(cluster_keys[-1])
        except ValueError:
            first_idx = 0
            last_idx = len(kc) - 1

        concept_index = int(getattr(session, "current_concept_index", 0) or 0)
        teaching_complete = concept_index > last_idx

        learned = {
            str(c).strip().lower()
            for c in (getattr(session, "learned_concepts", None) or [])
            if c
        }
        if not teaching_complete:
            teaching_complete = all(
                str(k).strip().lower() in learned for k in cluster_keys
            )

        active_quiz = bool(getattr(session, "cluster_quiz_active", False))
        quiz_complete = teaching_complete and not active_quiz

        active_tb = bool(getattr(session, "cluster_teachback_active", False))
        teachback_complete = teaching_complete and not active_tb and not active_quiz

        clarity_active = bool(getattr(session, "cluster_check_pending", False)) or bool(
            getattr(session, "clarity_gate_active", False)
        )
        zone_gates_passed = not clarity_active

        return ClusterGateStatus(
            teaching_complete=teaching_complete,
            quiz_complete=quiz_complete,
            teachback_complete=teachback_complete,
            zone_gates_passed=zone_gates_passed,
        )

    def cluster_complete_from_event(
        self,
        *,
        event_type: str,
        completed_cluster_index: int,
        assigned: AssignedCluster,
    ) -> bool:
        """Event-driven completion (teachback_passed at cluster boundary)."""
        if event_type not in ("teachback_passed", "completed"):
            return False
        return assigned.cluster_index == completed_cluster_index

    def completed_cluster_index_before_advance(
        self, session: Session, *, previous_concept_index: int
    ) -> int:
        kc = list(session.key_concepts or [])
        clusters = resolve_clusters(kc, getattr(session, "concept_clusters", None))
        return derive_current_cluster_index(int(previous_concept_index or 0), clusters)
