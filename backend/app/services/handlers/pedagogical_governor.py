"""
Pedagogical Governor — Zone 1 pacing decision engine.

=======================================================================
WHY THIS MODULE EXISTS
=======================================================================

The AI tutor's Zone 1 (foundational) teaching currently forces a question
into every response through four independent enforcement layers:

  L1  Prompt mandate   — every LLM prompt instructs "ask exactly ONE question"
  L2  Post-processor   — _enforce_explain_then_one_question() restructures output
  L3  Engagement guard — _micro_ensure_engagement_closer() appends a question
  L4  Visual mandate   — _visual_prompt_block() adds "end with one follow-up question"

This produces an interrogation cadence:  [short explanation] → [question]
on every single turn, making the tutor feel like a question machine rather
than a teacher building understanding progressively.

The governor provides a SINGLE AUTHORITATIVE PACING DECISION that all four
layers can defer to.  When the governor says "DELIVER", L2 and L3 stand
down.  When it says "QUESTION", they activate as before.

=======================================================================
WHY QUESTIONING MUST BE CONDITIONAL
=======================================================================

Zone 1 foundational teaching requires explanation-first pacing:

  "A student cannot reflect on what they have not yet been told."

The first interaction with a new concept must be a DELIVERY beat — the
teacher states what the concept is, where it appears in real life, and
what its key components are.  Only after the student has received a
conceptual model is questioning pedagogically appropriate.

Forcing a question before any delivery has occurred is a zone-category
error: it treats Zone 1 (foundational) students like Zone 4 (reflective)
students.

The pacing sequence for a well-taught Zone 1 concept should be:

  Beat 0  DELIVER    — concept introduction, real-world anchor
  Beat 1  REINFORCE  — mechanism / example / component detail
  Beat 2  REFLECT    — ONE soft reflective question (first question)
  Beat 3+ QUESTION   — full Socratic exchange
  Exit    CLOSE      — wrap-up, handoff to Q&A / cluster quiz

=======================================================================
WHY VISUALS MUST BE GATED
=======================================================================

Visuals are reinforcement tools, not introduction tools.  A diagram shown
before any explanation has been delivered requires the student to decode
the diagram without context.  This produces cognitive load, not insight.

Visual eligibility in Zone 1 requires at least one prior delivery beat
so the diagram anchors to an already-established conceptual frame.

=======================================================================
THIS FILE IS INFRASTRUCTURE ONLY (Step G1)
=======================================================================

This module is INERT at creation time.  It is not imported or called
from anywhere in the codebase.  Subsequent implementation steps (G2–G5)
will wire it into explanation_handler.py without changing any existing
behavior outside that file.

The module is a pure-function library:
  - No database access
  - No session writes
  - No async
  - No imports from session_service or explanation_handler
  - Fully deterministic given the same inputs
  - Safe to unit-test in isolation
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


# ─────────────────────────────────────────────────────────────────────────────
# PacingMode
# ─────────────────────────────────────────────────────────────────────────────


class PacingMode(str, Enum):
    """
    Authoritative pacing decision for a single tutor turn.

    Each mode controls:
      - whether the LLM prompt is allowed to request a question
      - whether L2 (_enforce_explain_then_one_question) activates
      - whether L3 (_micro_ensure_engagement_closer) activates
      - whether a visual diagram is eligible for this turn
      - whether the student is expected to reply with a substantive answer

    Modes are ordered from most content-heavy to most interactive:
      DELIVER → REINFORCE → VISUALIZE → REFLECT → QUESTION → CLOSE
    """

    DELIVER = "deliver"
    """
    Pure content delivery.  No question of any kind.

    Use for:
      - The opening beat of every new concept (beat 0)
      - Re-grounding when student confusion is high
      - Introducing a new semantic aspect after a close/reset

    L2 active:  NO
    L3 active:  NO
    Visual:     NO (concept not yet grounded)
    Student reply required:  NO (soft continue cue only)
    """

    REINFORCE = "reinforce"
    """
    Deepening/reinforcement without interrogation.

    Use for:
      - The second beat of a concept (beat 1)
      - Providing a concrete example or analogy
      - Connecting to prior cluster knowledge
      - After a high-SUS student demonstrates they need depth, not breadth

    L2 active:  NO
    L3 active:  NO
    Visual:     NO (still in grounding phase)
    Student reply required:  NO (soft continue cue only)
    """

    VISUALIZE = "visualize"
    """
    Visual-accompanied delivery beat.  Still no Socratic question.

    Use for:
      - Beat 2+ when a visual is available and concept is grounded
      - Showing a diagram that illustrates what was just explained
      - Reinforcing a process or comparison through structured visuals

    L2 active:  NO
    L3 active:  NO
    Visual:     YES (eligible from beat 2+ when grounding exists)
    Student reply required:  NO (soft continue cue only)
    """

    REFLECT = "reflect"
    """
    First reflective question after grounding is established.

    The question must be retrospective ("Based on what I just explained,
    what do you think...") rather than prior-knowledge probing
    ("What do you already know about X?").

    Use for:
      - The first question turn (only after >= 2 delivery beats)
      - Transitioning from delivery phase to exchange phase
      - Soft entry into Socratic exchange for low-SUS students

    L2 active:  YES (single soft question only)
    L3 active:  YES
    Visual:     YES (if available and beat index permits)
    Student reply required:  YES
    """

    QUESTION = "question"
    """
    Full Socratic exchange.  Current default behavior for all turns.

    Use for:
      - All turns from beat 3 onward (after grounding + first reflection)
      - Standard probe/re-explain/connection/deepening branches
      - Any turn where the student is in an active exchange loop

    L2 active:  YES
    L3 active:  YES
    Visual:     YES
    Student reply required:  YES
    """

    CLOSE = "close"
    """
    Concept handoff / wrap-up.  No question.

    Use for:
      - The force_exit path (micro-loop closure)
      - Concept mastery confirmation
      - Transition to Q&A phase or cluster quiz

    L2 active:  NO
    L3 active:  NO
    Visual:     NO
    Student reply required:  NO (Q&A invitation added separately by caller)
    """


# ─────────────────────────────────────────────────────────────────────────────
# Confusion level constants
# ─────────────────────────────────────────────────────────────────────────────

CONFUSION_LOW = "low"
CONFUSION_MEDIUM = "medium"
CONFUSION_HIGH = "high"


# ─────────────────────────────────────────────────────────────────────────────
# GovernorConfig
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class GovernorConfig:
    """
    Per-zone, per-subject configuration for the Pedagogical Governor.

    Frozen dataclass so all configs are immutable after construction.
    A default zone-1 config is provided as ``ZONE_1_DEFAULT``.

    Future subject-specific or zone-specific configs can be injected
    without changing any governor logic.

    Attributes:
        min_delivery_beats_before_reflect:
            Minimum number of DELIVER/REINFORCE/VISUALIZE beats that must
            occur before the governor is allowed to return REFLECT or
            QUESTION.  Controls the foundational grounding window.

        min_delivery_beats_before_visual:
            Minimum delivery beats required before a visual is eligible.
            Set to 0 for zones that allow immediate visual introduction.

        high_sus_delivery_beats:
            For students with sus_score > sus_high_threshold, use this
            (shorter) delivery window before questioning.

        sus_high_threshold:
            SUS score above which the student is treated as high-confidence.

        sus_low_threshold:
            SUS score below which the student is treated as struggling.

        max_consecutive_questions:
            After this many consecutive QUESTION-mode turns, the governor
            recommends a REINFORCE beat to re-anchor the concept.
            Set to 0 to disable.

        zone:
            The zone this config applies to.  Currently only zone 1 uses
            the governor; zones 2–4 will follow in future steps.
    """

    min_delivery_beats_before_reflect: int = 2
    min_delivery_beats_before_visual: int = 1
    high_sus_delivery_beats: int = 1
    sus_high_threshold: float = 70.0
    sus_low_threshold: float = 40.0
    max_consecutive_questions: int = 4
    zone: int = 1


# Canonical config instances.  Step G4 will use ZONE_1_DEFAULT as the default.
ZONE_1_DEFAULT = GovernorConfig(
    min_delivery_beats_before_reflect=2,
    min_delivery_beats_before_visual=1,
    high_sus_delivery_beats=1,
    sus_high_threshold=70.0,
    sus_low_threshold=40.0,
    max_consecutive_questions=4,
    zone=1,
)

# Zones 2–4 do not gate delivery beats; they go straight to QUESTION.
ZONE_2_DEFAULT = GovernorConfig(
    min_delivery_beats_before_reflect=0,
    min_delivery_beats_before_visual=0,
    high_sus_delivery_beats=0,
    max_consecutive_questions=0,
    zone=2,
)

ZONE_3_DEFAULT = GovernorConfig(
    min_delivery_beats_before_reflect=0,
    min_delivery_beats_before_visual=0,
    high_sus_delivery_beats=0,
    max_consecutive_questions=0,
    zone=3,
)

ZONE_4_DEFAULT = GovernorConfig(
    min_delivery_beats_before_reflect=0,
    min_delivery_beats_before_visual=0,
    high_sus_delivery_beats=0,
    max_consecutive_questions=0,
    zone=4,
)

_ZONE_CONFIGS: dict[int, GovernorConfig] = {
    1: ZONE_1_DEFAULT,
    2: ZONE_2_DEFAULT,
    3: ZONE_3_DEFAULT,
    4: ZONE_4_DEFAULT,
}


def zone_uses_vtse_engine(zone: int) -> bool:
    """Zones 1–2 share the Zone 1 VTSE teaching pipeline."""
    return int(zone) in (1, 2)


def get_config_for_zone(zone: int) -> GovernorConfig:
    """
    Return the canonical GovernorConfig for a given zone number.

    Returns ZONE_1_DEFAULT for any unrecognized zone to ensure safe fallback.
    Future subject-specific overrides can be injected here without changing
    any other governor logic.
    """
    if zone_uses_vtse_engine(zone):
        return ZONE_1_DEFAULT
    return _ZONE_CONFIGS.get(zone, ZONE_1_DEFAULT)


# ─────────────────────────────────────────────────────────────────────────────
# Confusion level inference
# ─────────────────────────────────────────────────────────────────────────────


def infer_confusion_level(
    *,
    low_confidence: bool = False,
    incorrect_idea: bool = False,
    incomplete_understanding: bool = False,
    score: int = 50,
) -> str:
    """
    Convert micro-teaching confusion signals to a canonical confusion level.

    Returns one of CONFUSION_LOW, CONFUSION_MEDIUM, or CONFUSION_HIGH.

    This function accepts the same confusion signals already computed by
    _micro_confusion_signals() in explanation_handler.py so the governor
    does not re-derive them.

    Args:
        low_confidence:          True when student answer is short/hedged + low score.
        incorrect_idea:          True when evaluator flags the answer as wrong.
        incomplete_understanding:True when evaluator reports missing points.
        score:                   Evaluator score (0–100).

    Returns:
        CONFUSION_HIGH   — multiple confusion signals or very low score
        CONFUSION_MEDIUM — single confusion signal or moderate score
        CONFUSION_LOW    — no confusion signals and adequate score
    """
    signal_count = sum([low_confidence, incorrect_idea, incomplete_understanding])
    if signal_count >= 2 or score < 35:
        return CONFUSION_HIGH
    if signal_count == 1 or score < 55:
        return CONFUSION_MEDIUM
    return CONFUSION_LOW


# ─────────────────────────────────────────────────────────────────────────────
# Core pacing decision
# ─────────────────────────────────────────────────────────────────────────────


def decide_pacing_mode(
    *,
    concept_beat_index: int,
    concept_delivery_beats: int,
    sus_score: float,
    confusion_level: str,
    force_exit: bool,
    is_opening: bool,
    prev_pacing_mode: Optional[PacingMode] = None,
    consecutive_question_turns: int = 0,
    zone: int = 1,
    config: Optional[GovernorConfig] = None,
) -> PacingMode:
    """
    Return the authoritative PacingMode for the next tutor turn.

    This is the central decision function of the Pedagogical Governor.
    It is the ONLY place in the codebase that decides whether questioning
    is appropriate for a given turn.

    All post-processors (L2, L3), prompt builders, and visual eligibility
    checks should defer to the return value of this function.

    Args:
        concept_beat_index:
            How many turns have occurred for the current concept so far.
            Corresponds to session.current_step_in_concept.
            0 = first turn (opening), 1 = second turn, etc.

        concept_delivery_beats:
            How many DELIVER/REINFORCE/VISUALIZE beats have occurred for
            the current concept WITHOUT a question being asked.
            Corresponds to session.concept_delivery_beats (new field, G2).
            0 on first turn; increments on each non-questioning beat.

        sus_score:
            Student Understanding Signal (0–100).  Higher = more confident.
            session.sus_score.

        confusion_level:
            Canonical confusion string from infer_confusion_level().
            One of: CONFUSION_LOW, CONFUSION_MEDIUM, CONFUSION_HIGH.

        force_exit:
            True when the micro-loop exit conditions have been met
            (student demonstrated mastery, safety cap reached, etc.).
            When True, always returns CLOSE regardless of other inputs.

        is_opening:
            True when this is the very first turn for a new concept
            (i.e., teacher_micro_teaching_opening was just called).
            When True, always returns DELIVER regardless of other inputs.

        prev_pacing_mode:
            The pacing mode of the immediately preceding turn.
            Used to detect transitions and avoid repeated same-mode turns
            where pedagogically inappropriate.

        consecutive_question_turns:
            How many consecutive QUESTION-mode turns have occurred.
            When this reaches config.max_consecutive_questions, the
            governor recommends a REINFORCE beat to re-anchor the concept.

        zone:
            Current learning zone (1–4).  Zones 2–4 bypass delivery gating
            and default to QUESTION to preserve existing behavior.

        config:
            Optional GovernorConfig override.  When None, the canonical
            config for the given zone is used.

    Returns:
        A PacingMode value.  The caller must respect this decision.

    Decision tree (Zone 1, SUS=MEDIUM, no confusion):

        force_exit=True                    → CLOSE
        is_opening=True                    → DELIVER
        in-flight session guard            → QUESTION  (see note below)
        confusion_level == HIGH            → DELIVER   (re-ground confused student)
        delivery_beats < min:
            delivery_beats == 0            → DELIVER
            delivery_beats >= 1            → REINFORCE (example/analogy beat)
        delivery_beats == min
          AND prev == REINFORCE            → VISUALIZE (diagram narration beat)
        delivery_beats >= min
          AND prev in (VISUALIZE, DELIVER,
                       None)               → REFLECT   (first soft question)
        consecutive_q >= max               → REINFORCE (periodic re-anchor)
        default                            → QUESTION  (standard Socratic exchange)

    Full intended pacing arc (SUS=MEDIUM):
        Beat 0  DELIVER    — concept introduction, real-world anchor
        Beat 1  REINFORCE  — example / analogy / component connection
        Beat 2  VISUALIZE  — diagram narration, no question
        Beat 3  REFLECT    — ONE soft retrospective question
        Beat 4+ QUESTION   — full Socratic exchange
        Exit    CLOSE      — wrap-up, handoff to Q&A / cluster quiz

    High-SUS fast-track (sus_score > sus_high_threshold):
        min_beats = 1, so the window collapses to:
        Beat 0  DELIVER → Beat 1  REFLECT → Beat 2+ QUESTION
        (REINFORCE and VISUALIZE are skipped for confident students)

    In-flight session guard:
        If concept_delivery_beats == 0 AND concept_beat_index > 2, the session
        is probably mid-concept from before the governor was introduced.
        Return QUESTION to match the pre-governor behavior for these sessions.
    """
    cfg = config or get_config_for_zone(zone)

    # ── Absolute priority: CLOSE ─────────────────────────────────────────────
    if force_exit:
        return PacingMode.CLOSE

    # ── Zones 3–4: bypass delivery gating entirely ───────────────────────────
    # Zones 3–4 have their own pedagogical model (challenge, reflection).
    # Zones 1–2 share the VTSE delivery governor.
    if zone >= 3:
        return PacingMode.QUESTION

    # ── Opening beat: always DELIVER ────────────────────────────────────────
    # The student has just arrived at this concept.  Nothing has been explained
    # yet.  There is nothing to question.
    # NOTE: is_opening=True only when teacher_micro_teaching_opening is called.
    # The first student *reply* (beat_idx=0, is_opening=False) is intentionally
    # NOT covered here — it falls through to the delivery window where it
    # correctly receives REINFORCE (delivery_beats==1).
    if is_opening:
        return PacingMode.DELIVER

    # ── In-flight session guard ──────────────────────────────────────────────
    # Sessions that were created before the governor was introduced will have
    # concept_delivery_beats == 0 even if they are mid-concept (beat 3+).
    # Return QUESTION for those sessions to avoid unexpectedly switching them
    # to a delivery-mode cadence mid-conversation.
    if concept_delivery_beats == 0 and concept_beat_index > 2:
        return PacingMode.QUESTION

    # ── High-confusion: re-ground regardless of beat position ───────────────
    # A student who is confused needs more explanation, not more questioning.
    # Return DELIVER to trigger a re-grounding prompt from a different angle.
    if confusion_level == CONFUSION_HIGH:
        return PacingMode.DELIVER

    # ── Effective delivery window ────────────────────────────────────────────
    # Determine how many delivery beats are required before questioning.
    # High-SUS students have a shorter window (they need less scaffolding).
    sus_high = cfg.sus_high_threshold
    min_beats = (
        cfg.high_sus_delivery_beats
        if sus_score > sus_high
        else cfg.min_delivery_beats_before_reflect
    )

    # ── Still in delivery window ─────────────────────────────────────────────
    if concept_delivery_beats < min_beats:
        # After the first DELIVER beat, switch to REINFORCE so the second
        # delivery beat provides a concrete example / analogy / connection.
        # Using concept_delivery_beats (not concept_beat_index) is correct here:
        # it measures how many *content* beats have landed, independent of how
        # many student-turn round trips have occurred.
        if concept_delivery_beats >= 1:
            return PacingMode.REINFORCE
        return PacingMode.DELIVER

    # ── VISUALIZE: diagram narration beat ───────────────────────────────────
    # When the delivery window has just closed (delivery_beats == min_beats)
    # AND the preceding beat was a REINFORCE, insert one VISUALIZE beat so
    # the teacher shows/narrates a diagram before asking the first question.
    # This produces the full arc: DELIVER → REINFORCE → VISUALIZE → REFLECT.
    #
    # Using == min_beats (not >=) intentionally limits VISUALIZE to the
    # initial delivery-window transition only.  Periodic REINFORCE re-anchors
    # (which occur after many QUESTION turns when delivery_beats > min_beats)
    # do NOT re-trigger a VISUALIZE beat — they go back to QUESTION directly.
    if concept_delivery_beats == min_beats and prev_pacing_mode == PacingMode.REINFORCE:
        return PacingMode.VISUALIZE

    # ── First question: REFLECT (soft) ───────────────────────────────────────
    # The student has received enough grounding.  The first question must be
    # retrospective and soft, not a prior-knowledge probe.
    #
    # Allowed previous modes:
    #   VISUALIZE — primary path after the diagram narration beat
    #   DELIVER   — fallback if REINFORCE/VISUALIZE were bypassed (e.g. high-SUS
    #               fast-track, or a confusion-driven re-ground mid-concept)
    #   None      — in-flight guard for legacy sessions that predate the governor
    if concept_delivery_beats >= min_beats and prev_pacing_mode in (
        PacingMode.VISUALIZE,
        PacingMode.DELIVER,
        None,
    ):
        return PacingMode.REFLECT

    # ── Periodic re-anchor ───────────────────────────────────────────────────
    # After several consecutive QUESTION turns, insert a REINFORCE beat to
    # prevent the exchange from drifting too far from the concept's core idea.
    if (
        cfg.max_consecutive_questions > 0
        and consecutive_question_turns >= cfg.max_consecutive_questions
    ):
        return PacingMode.REINFORCE

    # ── Standard Socratic exchange ───────────────────────────────────────────
    return PacingMode.QUESTION


# ─────────────────────────────────────────────────────────────────────────────
# Visual eligibility
# ─────────────────────────────────────────────────────────────────────────────


def visual_eligible(
    *,
    concept_delivery_beats: int,
    pacing_mode: PacingMode,
    zone: int = 1,
    config: Optional[GovernorConfig] = None,
) -> bool:
    """
    True when a visual diagram is pedagogically appropriate for this turn.

    Visuals in Zone 1 require a minimum number of prior delivery beats so
    the diagram anchors to an already-established conceptual frame rather
    than requiring the student to decode it cold.

    Mode eligibility (Zone 1):
      VISUALIZE — YES (primary visual beat; this is its entire purpose)
      REFLECT   — YES (visual can accompany the first soft question)
      QUESTION  — YES (visual can support the Socratic exchange)
      DELIVER   — NO  (concept not yet grounded; diagram adds cognitive load)
      REINFORCE — NO  (still in grounding phase; not yet the visual beat)
      CLOSE     — NO  (concept wrapping up; a new diagram would distract)

    Zones 2–4 have no visual gating (different pedagogical model).

    Args:
        concept_delivery_beats:
            How many delivery beats have occurred for the current concept.

        pacing_mode:
            The mode decided for this turn by decide_pacing_mode().

        zone:
            Current learning zone.

        config:
            Optional GovernorConfig override.

    Returns:
        True if a visual is eligible, False otherwise.
    """
    # Zones 3–4: no visual delivery gating
    if zone >= 3:
        return True

    cfg = config or get_config_for_zone(zone)

    # DELIVER, REINFORCE, and CLOSE modes: no visual.
    # DELIVER:   concept not yet grounded — diagram adds cognitive load without context.
    # REINFORCE: still in grounding phase — not yet the visual narration beat.
    # CLOSE:     concept wrapping up — a new diagram would distract from handoff.
    # VISUALIZE is intentionally NOT in this set — it is the primary visual beat.
    if pacing_mode in (PacingMode.DELIVER, PacingMode.REINFORCE, PacingMode.CLOSE):
        return False

    # Require minimum delivery beats before visual (default: 1).
    # VISUALIZE is only reached when delivery_beats == min_beats (>= 1 by config),
    # so this check is always satisfied when pacing_mode == VISUALIZE.
    if concept_delivery_beats < cfg.min_delivery_beats_before_visual:
        return False

    return True


def should_allow_visual(
    *,
    concept_beat_index: int,
    pacing_mode: PacingMode,
    zone: int = 1,
    config: Optional[GovernorConfig] = None,
) -> bool:
    """
    Convenience alias using concept_beat_index instead of concept_delivery_beats.

    Use this in contexts where concept_delivery_beats is not yet tracked
    (e.g., before Step G2 adds the session field).  Uses concept_beat_index
    as a conservative proxy for delivery beats (same value or lower).

    Args:
        concept_beat_index:
            session.current_step_in_concept — used as proxy for delivery beats.

        pacing_mode:
            The mode decided for this turn.

        zone:
            Current learning zone.

        config:
            Optional GovernorConfig override.

    Returns:
        True if a visual is eligible, False otherwise.
    """
    return visual_eligible(
        concept_delivery_beats=concept_beat_index,
        pacing_mode=pacing_mode,
        zone=zone,
        config=config,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Question enforcement gating
# ─────────────────────────────────────────────────────────────────────────────


def should_force_question(pacing_mode: PacingMode) -> bool:
    """
    True when L2 (_enforce_explain_then_one_question) should activate.

    L2 restructures a response to guarantee it contains exactly one question.
    This is only appropriate when the pacing mode explicitly calls for
    student interaction (REFLECT or QUESTION).

    Step G4 will replace the unconditional call to
    _enforce_explain_then_one_question() with:

        if should_force_question(pacing_mode):
            answer = _enforce_explain_then_one_question(answer, ...)

    Args:
        pacing_mode: The mode decided by decide_pacing_mode() for this turn.

    Returns:
        True for REFLECT and QUESTION modes only.
        False for DELIVER, REINFORCE, VISUALIZE, and CLOSE.
    """
    return pacing_mode in (PacingMode.REFLECT, PacingMode.QUESTION)


def should_force_engagement_closer(pacing_mode: PacingMode) -> bool:
    """
    True when L3 (_micro_ensure_engagement_closer) should activate.

    L3 appends a question or engagement phrase if none is detected.
    Like L2, it is only appropriate when student interaction is expected.

    Step G4 will replace the unconditional call to
    _micro_ensure_engagement_closer() with:

        if should_force_engagement_closer(pacing_mode):
            answer = _micro_ensure_engagement_closer(answer)
        else:
            answer = _apply_soft_continue_cue(answer, pacing_mode)

    Args:
        pacing_mode: The mode decided by decide_pacing_mode() for this turn.

    Returns:
        True for REFLECT and QUESTION modes only.
        False for DELIVER, REINFORCE, VISUALIZE, and CLOSE.
    """
    return pacing_mode in (PacingMode.REFLECT, PacingMode.QUESTION)


# ─────────────────────────────────────────────────────────────────────────────
# Soft continue cue
# ─────────────────────────────────────────────────────────────────────────────

# Closing phrases for DELIVER/REINFORCE/VISUALIZE beats.
# These end the response naturally without interrogating the student.
# The caller rotates through these to avoid repetition.
_SOFT_CONTINUE_CUES: tuple[str, ...] = (
    "Let that settle — we'll build on it in the next step.",
    "Take a moment with that idea before we continue.",
    "That's the core of it — we'll connect it to the next piece shortly.",
    "Keep that in mind as we go deeper.",
    "Hold onto that image — it'll connect to what comes next.",
)

_SOFT_CONTINUE_CUE_DEFAULT = "Let that settle — we'll build on it in the next step."


def get_soft_continue_cue(turn_index: int = 0) -> str:
    """
    Return a non-interrogative closing cue for DELIVER/REINFORCE turns.

    Rotates through a small set of natural phrases to avoid repetition
    across consecutive delivery beats.

    Args:
        turn_index: Any integer (e.g., concept_beat_index).  Used to select
                    a phrase via modulo; the specific phrase is not important.

    Returns:
        A single sentence ending in a period, suitable for appending to a
        delivery-mode response that must not contain a question.
    """
    if not _SOFT_CONTINUE_CUES:
        return _SOFT_CONTINUE_CUE_DEFAULT
    idx = abs(int(turn_index)) % len(_SOFT_CONTINUE_CUES)
    return _SOFT_CONTINUE_CUES[idx]


# ─────────────────────────────────────────────────────────────────────────────
# Delivery beat counter helper
# ─────────────────────────────────────────────────────────────────────────────


def next_delivery_beat_count(
    current_delivery_beats: int,
    pacing_mode: PacingMode,
) -> int:
    """
    Return the updated concept_delivery_beats counter after a turn.

    DELIVER, REINFORCE, and VISUALIZE beats increment the counter.
    REFLECT, QUESTION, and CLOSE beats do NOT increment it — they are
    interactive beats, not delivery beats.

    Step G4 will call this to compute the new value to persist in
    session.concept_delivery_beats at the end of each micro-teaching turn.

    Args:
        current_delivery_beats: session.concept_delivery_beats before this turn.
        pacing_mode:            The pacing mode used for this turn.

    Returns:
        Updated delivery beat count.
    """
    if pacing_mode in (PacingMode.DELIVER, PacingMode.REINFORCE, PacingMode.VISUALIZE):
        return current_delivery_beats + 1
    return current_delivery_beats


# ─────────────────────────────────────────────────────────────────────────────
# Zone classification utilities
# ─────────────────────────────────────────────────────────────────────────────


def is_questioning_mode(pacing_mode: PacingMode) -> bool:
    """True when the mode expects a substantive student reply."""
    return pacing_mode in (PacingMode.REFLECT, PacingMode.QUESTION)


def is_delivery_mode(pacing_mode: PacingMode) -> bool:
    """True when the mode delivers content without interrogation."""
    return pacing_mode in (
        PacingMode.DELIVER,
        PacingMode.REINFORCE,
        PacingMode.VISUALIZE,
    )


def is_terminal_mode(pacing_mode: PacingMode) -> bool:
    """True when the mode closes the current concept (no more teaching beats)."""
    return pacing_mode == PacingMode.CLOSE


def pacing_mode_label(pacing_mode: PacingMode) -> str:
    """
    Human-readable label for logging and debugging.

    Returns a concise string suitable for log lines without exposing
    internal enum details to non-governor callers.
    """
    labels: dict[PacingMode, str] = {
        PacingMode.DELIVER: "DELIVER (explanation-only)",
        PacingMode.REINFORCE: "REINFORCE (example/connection, no question)",
        PacingMode.VISUALIZE: "VISUALIZE (diagram + narration, no question)",
        PacingMode.REFLECT: "REFLECT (first soft question after grounding)",
        PacingMode.QUESTION: "QUESTION (full Socratic exchange)",
        PacingMode.CLOSE: "CLOSE (handoff, no question)",
    }
    return labels.get(pacing_mode, str(pacing_mode))
