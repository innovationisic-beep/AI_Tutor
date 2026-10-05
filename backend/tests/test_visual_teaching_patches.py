"""Unit tests for VisualState field-replace patch semantics."""

from app.services.visual_teaching.plan_schema import (
    VisualState,
    apply_visual_state_patch,
    empty_visual_state,
    materialize_beat_states,
    VisualTeachingBeat,
    SemanticAnchorEvent,
)


def test_omit_preserves():
    base = VisualState(highlights=["a"], pointer="a", dim_others=True)
    out = apply_visual_state_patch(base, {"pointer": "b"})
    assert out.highlights == ["a"]
    assert out.pointer == "b"
    assert out.dim_others is True


def test_empty_list_clears_highlights():
    base = VisualState(highlights=["a", "b"])
    out = apply_visual_state_patch(base, {"highlights": []})
    assert out.highlights == []


def test_null_clears_pointer_and_zoom():
    base = VisualState(pointer="a", zoom={"region_id": "a"})
    out = apply_visual_state_patch(base, {"pointer": None, "zoom": None})
    assert out.pointer is None
    assert out.zoom is None


def test_arrows_empty_clears():
    base = VisualState(arrows=["c1"])
    out = apply_visual_state_patch(base, {"arrows": []})
    assert out.arrows == []


def test_arrows_patch_preserves_highlights_when_omitted():
    base = VisualState(highlights=["right_atrium"], arrows=["old"])
    out = apply_visual_state_patch(base, {"arrows": ["body_to_right_atrium"]})
    assert out.highlights == ["right_atrium"]
    assert out.arrows == ["body_to_right_atrium"]


def test_materialize_beat_states():
    beat = VisualTeachingBeat(
        id="b1",
        visual_state=VisualState(highlights=["a"]),
        speak="Hello. World.",
        sentence_events=[
            SemanticAnchorEvent(
                sentence_index=0,
                patch={"highlights": ["b"]},
            ),
            SemanticAnchorEvent(
                sentence_index=1,
                patch={"pointer": "b"},
            ),
        ],
    )
    snaps = materialize_beat_states(beat)
    assert snaps[-1].highlights == ["a"]
    assert snaps[0].highlights == ["b"]
    assert snaps[1].pointer == "b"
    assert snaps[1].highlights == ["b"]
