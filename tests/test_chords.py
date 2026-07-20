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


def test_note_off_releases_chord_even_after_modifier_released():
    engine = ChordEngine()
    engine.process(on(36))                    # major
    engine.process(on(60))                    # C major sounding
    engine.process(off(36))                   # let go of modifier first
    out = engine.process(off(60))
    assert out == [off(60), off(64), off(67)]


def test_shared_tones_are_reference_counted():
    engine = ChordEngine()
    engine.process(on(36))                    # major
    engine.process(on(60))                    # C major: 60 64 67
    engine.process(on(37))                    # minor (newest wins)
    out = engine.process(on(64))              # E minor: 64 67 71 — 64,67 already on
    assert out == [on(71)]                    # only the new pitch is note-on'd
    out = engine.process(off(60))             # release C major
    assert out == [off(60)]                   # 64 and 67 still owned by E minor
    out = engine.process(off(64))
    assert out == [off(64), off(67), off(71)]


def test_retrigger_held_root_releases_previous_emission_first():
    engine = ChordEngine()
    engine.process(on(36))                    # major
    engine.process(on(60))                    # C major
    engine.process(on(37))                    # switch to minor
    out = engine.process(on(60))              # retrigger same root
    assert out == [off(60), off(64), off(67), on(60), on(63), on(67)]
    assert engine.process(off(60)) == [off(60), off(63), off(67)]


def test_untracked_note_off_is_forwarded():
    engine = ChordEngine()
    assert engine.process(off(72)) == [off(72)]


def test_velocity_zero_note_on_is_a_note_off():
    engine = ChordEngine()
    engine.process(on(36))
    engine.process(on(60))
    out = engine.process(on(60, velocity=0))
    assert out == [off(60), off(64), off(67)]


def test_flush_releases_everything_and_resets():
    engine = ChordEngine()
    engine.process(on(36))
    engine.process(on(60))
    engine.process(on(72))
    assert engine.flush() == [off(60), off(64), off(67), off(72), off(76), off(79)]
    assert engine.flush() == []


def test_chord_tones_above_127_are_dropped():
    engine = ChordEngine()
    engine.process(on(36 + 9))                # add9: 0 4 7 14
    out = engine.process(on(120))             # 134 is out of range
    assert out == [on(120), on(124), on(127)]
    assert engine.process(off(120)) == [off(120), off(124), off(127)]


def test_non_note_messages_pass_through_unchanged():
    engine = ChordEngine()
    bend = mido.Message("pitchwheel", pitch=2000, channel=0)
    cc = mido.Message("control_change", control=1, value=64, channel=0)
    touch = mido.Message("aftertouch", value=50, channel=0)
    prog = mido.Message("program_change", program=5, channel=0)
    for msg in (bend, cc, touch, prog):
        assert engine.process(msg) == [msg]
