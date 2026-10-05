"""
Centralized evaluation thresholds and shared learning constants.

Import these instead of using magic numbers in handler logic so that all
evaluation pass/fail decisions stay in one place.
"""

# A teachback or quiz answer is accepted when the evaluation score is at or
# above this value (0–100 scale).
TEACHBACK_PASS_THRESHOLD: int = 60

# The Clarity Gate requires a higher bar: the student must demonstrate
# understanding across multiple concepts before the cluster review passes.
CLARITY_GATE_PASS_THRESHOLD: int = 70

# Short cluster reflection (between clusters in Zone 1 progression) — lighter than
# the final topic-wide Clarity Gate.
CLUSTER_CHECK_PASS_THRESHOLD: int = 55

# Cluster teachback (long answer after cluster quiz) — tiered response thresholds.
CLUSTER_TEACHBACK_EXCELLENT_THRESHOLD: int = 80
CLUSTER_TEACHBACK_PARTIAL_THRESHOLD: int = 50
CLUSTER_TEACHBACK_SOCRATIC_QUESTIONS: int = 2
CLUSTER_TEACHBACK_SUS_EXCELLENT_DELTA: float = 8.0
CLUSTER_TEACHBACK_SUS_PARTIAL_DELTA: float = 3.0
CLUSTER_TEACHBACK_SUS_WEAK_DELTA: float = -2.0

# Spaced-retrieval recall is graded generously — the goal is to prompt memory,
# not to grade rigorously.
RETRIEVAL_PASS_THRESHOLD: int = 50

# Micro-teaching: exit to the main quiz when the student's last answer scores at
# or above this (same bar as teachback — conceptual readiness, not perfection).
MICRO_TEACH_PASS_SCORE: int = TEACHBACK_PASS_THRESHOLD

# Absolute floor on answer length for micro-loop completion (reasoning is primary).
MICRO_TEACH_MIN_WORDS_FOR_COMPLETION: int = 4

# Safety cap on micro-teaching reply cycles (weak answers) before forcing quiz entry.
MICRO_TEACH_MAX_LOOPS: int = 12

# Stored in session.current_step_in_concept when micro-teaching is done and the
# next __action:quiz should run (must stay <= session field le=20).
MICRO_TEACH_STEP_READY_QUIZ: int = 19

# Zone 1: structured questions after each key concept's main VTSE explanation.
CONCEPT_QUESTIONS_PER_CONCEPT: int = 3

# Fixed concept-check slate: two MCQs then one fill-in-the-blank.
CONCEPT_CHECK_SLOT_TYPES: tuple[str, ...] = ("mcq", "mcq", "fill_in_blank")

# Zone 1 cluster-end quiz: two short descriptive answers then one MCQ.
CLUSTER_QUESTIONS_PER_CLUSTER: int = 3
CLUSTER_CHECK_SLOT_TYPES: tuple[str, ...] = ("descriptive", "descriptive", "mcq")
