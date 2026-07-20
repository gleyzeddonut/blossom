import mido
import pytest

from chords import ChordEngine


def on(note, velocity=100, channel=0):
    return mido.Message("note_on", note=note, velocity=velocity, channel=channel)


def off(note, channel=0):
    return mido.Message("note_off", note=note, velocity=0, channel=channel)


# Zone key offsets, per spec chord map: C=major, C#=minor, D=maj7, D#=min7,
# E=dom7, F=sus4, F#=sus2, G=dim, G#=aug, A=add9.
QUALITIES = {
    0: (0, 4, 7),
    1: (0, 3, 7),
    2: (0, 4, 7, 11),
    3: (0, 3, 7, 10),
    4: (0, 4, 7, 10),
    5: (0, 5, 7),
    6: (0, 2, 7),
    7: (0, 3, 6),
    8: (0, 4, 8),
    9: (0, 4, 7, 14),
}


@pytest.mark.parametrize("offset,intervals", QUALITIES.items())
def test_held_modifier_builds_chord(offset, intervals):
    engine = ChordEngine()
    engine.process(on(36 + offset))  # hold modifier key in the zone
    out = engine.process(on(60, velocity=90))
    assert out == [on(60 + i, velocity=90) for i in intervals]


def test_chord_uses_played_velocity():
    engine = ChordEngine()
    engine.process(on(36))
    out = engine.process(on(62, velocity=37))
    assert all(m.velocity == 37 for m in out)


def test_chord_sent_on_engine_channel():
    engine = ChordEngine(channel=3)
    engine.process(on(36))
    out = engine.process(on(60))
    assert out == [on(60, channel=3), on(64, channel=3), on(67, channel=3)]


def test_no_modifier_passes_single_note_through():
    engine = ChordEngine()
    assert engine.process(on(60, velocity=80)) == [on(60, velocity=80)]


def test_modifier_keys_are_consumed_silently():
    engine = ChordEngine()
    assert engine.process(on(36)) == []       # assigned modifier
    assert engine.process(on(46)) == []       # unassigned zone key (A#)
    assert engine.process(off(36)) == []
    assert engine.process(off(46)) == []


def test_most_recent_modifier_wins():
    engine = ChordEngine()
    engine.process(on(36))                    # major
    engine.process(on(37))                    # then minor
    assert engine.process(on(60)) == [on(60), on(63), on(67)]


def test_releasing_newest_modifier_falls_back():
    engine = ChordEngine()
    engine.process(on(36))                    # major
    engine.process(on(37))                    # minor on top
    engine.process(off(37))                   # release minor
    assert engine.process(on(60)) == [on(60), on(64), on(67)]


def test_releasing_all_modifiers_restores_passthrough():
    engine = ChordEngine()
    engine.process(on(36))
    engine.process(off(36))
    assert engine.process(on(60)) == [on(60)]
