"""Micro-teaching progression gates (Fix A monotonic step + Fix B mastery bypass)."""

from __future__ import annotations

import pytest

from app.core.constants import MICRO_TEACH_MAX_LOOPS
from app.services.handlers.explanation_handler import compute_micro_progression_gates


def test_fix_a_confirm_advances_step() -> None:
    """Confirm no longer freezes prev_rounds (was: next_cycle = prev on confirm)."""
    g0 = compute_micro_progression_gates(
        prev_rounds=0,
        mc_action="confirm",
        current_concept_mastered=False,
        meets=False,
        confusion_now=False,
    )
    assert g0["next_cycle"] == 1
    assert g0["progression_advanced"] is True

    g1 = compute_micro_progression_gates(
        prev_rounds=1,
        mc_action="confirm",
        current_concept_mastered=False,
        meets=False,
        confusion_now=False,
    )
    assert g1["next_cycle"] == 2
    assert g1["progression_advanced"] is True


def test_fix_b_mastery_bypass_min_rounds_lock() -> None:
    """Two confirms at round 0 → mastered → can exit without waiting for round 2."""
    g = compute_micro_progression_gates(
        prev_rounds=0,
        mc_action="confirm",
        current_concept_mastered=True,
        meets=False,
        confusion_now=False,
    )
    assert g["force_exit"] is True
    assert g["mastery_bypass"] is True
    assert g["min_rounds_lock_active"] is True


def test_readiness_exit_requires_deepening_round_without_mastery() -> None:
    """Meets + confirm at round 1 still needs had_deepening (round >= 2) unless mastered."""
    g = compute_micro_progression_gates(
        prev_rounds=1,
        mc_action="confirm",
        current_concept_mastered=False,
        meets=True,
        confusion_now=False,
    )
    assert g["force_exit"] is False
    assert g["had_deepening"] is False
    assert g["mastery_bypass"] is False


def test_readiness_exit_after_two_rounds() -> None:
    g = compute_micro_progression_gates(
        prev_rounds=2,
        mc_action="confirm",
        current_concept_mastered=False,
        meets=True,
        confusion_now=False,
    )
    assert g["force_exit"] is True
    assert g["next_cycle"] == 3


def test_probe_still_advances_progression() -> None:
    g = compute_micro_progression_gates(
        prev_rounds=3,
        mc_action="probe",
        current_concept_mastered=False,
        meets=False,
        confusion_now=True,
    )
    assert g["next_cycle"] == 4
    assert g["progression_advanced"] is True
    assert g["force_exit"] is False


def test_safety_max_reachable() -> None:
    """After enough replies, safety cap triggers exit even without mastery."""
    prev = MICRO_TEACH_MAX_LOOPS - 1
    g = compute_micro_progression_gates(
        prev_rounds=prev,
        mc_action="confirm",
        current_concept_mastered=False,
        meets=False,
        confusion_now=False,
    )
    assert g["safety_max"] is True
    assert g["force_exit"] is True
    assert g["next_cycle"] == MICRO_TEACH_MAX_LOOPS - 1


def test_confirm_heavy_path_reaches_exit_by_round_two_mastered() -> None:
    """Simulate two confirm rounds: round 0 not exit; round 1 mastered exits."""
    g0 = compute_micro_progression_gates(
        prev_rounds=0,
        mc_action="confirm",
        current_concept_mastered=False,
        meets=True,
        confusion_now=False,
    )
    assert g0["force_exit"] is False

    g1 = compute_micro_progression_gates(
        prev_rounds=1,
        mc_action="confirm",
        current_concept_mastered=True,
        meets=True,
        confusion_now=False,
    )
    assert g1["force_exit"] is True
    assert g1["mastery_bypass"] is True


def test_next_cycle_caps_below_max_loops() -> None:
    g = compute_micro_progression_gates(
        prev_rounds=100,
        mc_action="probe",
        current_concept_mastered=False,
        meets=False,
        confusion_now=False,
    )
    assert g["next_cycle"] == MICRO_TEACH_MAX_LOOPS - 1


def test_weak_student_probe_advances_step() -> None:
    """Probe path still monotonically advances (reinforcement preserved)."""
    g = compute_micro_progression_gates(
        prev_rounds=0,
        mc_action="probe",
        current_concept_mastered=False,
        meets=False,
        confusion_now=True,
    )
    assert g["next_cycle"] == 1
    assert g["force_exit"] is False


def test_concept_completion_path_after_three_rounds() -> None:
    """Readiness exit without mastery once guided + deepening rounds completed."""
    g = compute_micro_progression_gates(
        prev_rounds=2,
        mc_action="confirm",
        current_concept_mastered=False,
        meets=True,
        confusion_now=False,
    )
    assert g["force_exit"] is True
    assert g["next_cycle"] == 3
