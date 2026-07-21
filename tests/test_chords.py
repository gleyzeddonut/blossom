import mido
import pytest

from chords import CHORD_MAP, CHORD_NAMES, ChordEngine, note_name, parse_note


def on(note, velocity=100, channel=0):
    return mido.Message("note_on", note=note, velocity=velocity, channel=channel)


def off(note, channel=0):
    return mido.Message("note_off", note=note, velocity=0, channel=channel)


def cc(control, value, channel=0):
    return mido.Message("control_change", control=control, value=value,
                        channel=channel)


# Zone key offsets: C=major, C#=maj7, D=minor, D#=min7, E=dom7, F=add9,
# F#=sus4, G=13, G#=half-dim, A=dim, A#=aug.
QUALITIES = {
    0: (0, 4, 7),
    1: (0, 4, 7, 11),
    2: (0, 3, 7),
    3: (0, 3, 7, 10),
    4: (0, 4, 7, 10),
    5: (0, 4, 7, 14),
    6: (0, 5, 7),
    7: (0, 4, 7, 10, 21),
    8: (0, 3, 6, 10),
    9: (0, 3, 6),
    10: (0, 4, 8),
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
    assert engine.process(on(47)) == []       # unassigned zone key (B)
    assert engine.process(off(36)) == []
    assert engine.process(off(47)) == []


def test_held_modifiers_combine():
    engine = ChordEngine()
    engine.process(on(37))                    # maj7
    engine.process(on(41))                    # + add9
    # union of (0,4,7,11) and (0,4,7,14) -> maj7add9
    assert engine.process(on(60)) == [on(60), on(64), on(67), on(71), on(74)]


def test_releasing_one_modifier_keeps_the_other():
    engine = ChordEngine()
    engine.process(on(36))                    # major
    engine.process(on(38))                    # + minor
    engine.process(off(38))                   # release minor
    assert engine.process(on(60)) == [on(60), on(64), on(67)]


def test_releasing_all_modifiers_restores_passthrough():
    engine = ChordEngine()
    engine.process(on(36))
    engine.process(off(36))
    assert engine.process(on(60)) == [on(60)]


def test_releasing_modifier_collapses_held_chord():
    engine = ChordEngine()
    engine.process(on(36))                    # major
    engine.process(on(60))                    # C major sounding
    out = engine.process(off(36))             # modifier released while held
    assert out == [off(64), off(67)]          # chord thins to the bare note
    assert engine.process(off(60)) == [off(60)]


def test_shared_tones_are_reference_counted():
    engine = ChordEngine()
    engine.process(on(36))                    # major, held throughout
    engine.process(on(60))                    # C major: 60 64 67
    out = engine.process(on(64))              # E major, voice-led to 59 64 68
    assert out == [on(59), on(68)]            # 64 is shared, not retriggered
    out = engine.process(off(60))
    assert out == [off(60), off(67)]          # 64 still owned by the E chord
    out = engine.process(off(64))
    assert out == [off(59), off(64), off(68)]


def test_retrigger_held_root_releases_previous_emission_first():
    engine = ChordEngine()
    engine.process(on(36))                    # major
    engine.process(on(60))                    # C major
    out = engine.process(on(60))              # retrigger same root
    assert out == [off(60), off(64), off(67), on(60), on(64), on(67)]
    assert engine.process(off(60)) == [off(60), off(64), off(67)]


def test_untracked_note_off_is_forwarded():
    engine = ChordEngine()
    assert engine.process(off(72)) == [off(72)]


def test_stray_note_off_cannot_kill_a_sustained_chord_tone():
    engine = ChordEngine()
    engine.process(on(36))                    # major
    engine.process(on(60))                    # C major: 60 64 67
    # A stray off for 64 (never pressed as a root) must not cut the chord
    # tone or corrupt its reference count.
    assert engine.process(off(64)) == []
    assert engine.sounding_notes == [60, 64, 67]
    assert engine.process(off(60)) == [off(60), off(64), off(67)]


def test_mono_release_of_stolen_root_is_harmless():
    engine = ChordEngine(mono=True)
    engine.process(on(36))
    engine.process(on(60))                    # C chord
    engine.process(on(72))                    # steals; C released
    engine.process(off(60))                   # off for the stolen root
    assert engine.sounding_notes != []        # newest chord untouched
    engine.process(off(72))
    assert engine.sounding_notes == []


def test_velocity_zero_note_on_is_a_note_off():
    engine = ChordEngine()
    engine.process(on(36))
    engine.process(on(60))
    out = engine.process(on(60, velocity=0))
    assert out == [off(60), off(64), off(67)]


def test_flush_releases_everything_and_resets():
    engine = ChordEngine()
    engine.process(on(36))
    engine.process(on(60))                    # 60 64 67
    engine.process(on(72))                    # voice-led near it: 64 67 72
    assert engine.flush() == [off(60), off(64), off(67), off(72)]
    assert engine.flush() == []


def test_chord_tones_above_127_are_dropped():
    engine = ChordEngine()
    engine.process(on(36 + 5))                # add9: 0 4 7 14
    out = engine.process(on(120))             # 134 is out of range
    assert out == [on(120), on(124), on(127)]
    assert engine.process(off(120)) == [off(120), off(124), off(127)]


def test_non_note_messages_pass_through_unchanged():
    engine = ChordEngine()
    bend = mido.Message("pitchwheel", pitch=2000, channel=0)
    volume = cc(7, 64)                        # CC1 is consumed; others pass
    touch = mido.Message("aftertouch", value=50, channel=0)
    prog = mido.Message("program_change", program=5, channel=0)
    for msg in (bend, volume, touch, prog):
        assert engine.process(msg) == [msg]


def test_every_chord_has_a_name():
    assert set(CHORD_NAMES) == set(CHORD_MAP)


def test_quality_intervals_cover_the_default_map():
    from chords import QUALITY_INTERVALS
    for offset, name in CHORD_NAMES.items():
        assert QUALITY_INTERVALS[name] == CHORD_MAP[offset]


def test_custom_chord_map_with_duplicates():
    from chords import QUALITY_INTERVALS
    cmap = {0: QUALITY_INTERVALS["min9"], 1: QUALITY_INTERVALS["min9"]}
    names = {0: "min9", 1: "min9"}
    engine = ChordEngine(chord_map=cmap, chord_names=names)
    engine.process(on(37))                    # second min9 slot
    assert engine.current_quality == "min9"
    assert engine.process(on(60)) == [on(60), on(63), on(67), on(70), on(74)]
    engine.process(off(60))
    assert engine.process(on(38)) == []       # unassigned slot is consumed


def test_current_quality_tracks_held_modifiers():
    engine = ChordEngine()
    assert engine.current_quality is None
    engine.process(on(36))
    assert engine.current_quality == "major"
    engine.process(on(37))
    assert engine.current_quality == "major+maj7"
    engine.process(off(36))
    assert engine.current_quality == "maj7"
    engine.process(off(37))
    assert engine.current_quality is None


def test_key_mode_plays_diatonic_chords():
    engine = ChordEngine(key=0)               # key of C
    assert engine.process(on(60)) == [on(60), on(64), on(67)]   # I  major
    engine.process(off(60))
    assert engine.process(on(62)) == [on(62), on(65), on(69)]   # ii minor
    engine.process(off(62))
    # vii dim, voice-led down near the ii voicing
    assert engine.process(on(71)) == [on(62), on(65), on(71)]
    engine.process(off(71))


def test_voice_leading_minimizes_movement():
    engine = ChordEngine()
    engine.process(on(36))                    # major
    engine.process(on(60))                    # C: 60 64 67
    engine.process(off(60))
    out = engine.process(on(65))              # F voiced near C -> F/C
    assert out == [on(60), on(65), on(69)]


def test_first_chord_uses_root_position():
    engine = ChordEngine()
    engine.process(on(36))
    assert engine.process(on(60)) == [on(60), on(64), on(67)]


def test_mod_wheel_shifts_voicing_upward():
    engine = ChordEngine()
    assert engine.process(cc(1, 127)) == []   # consumed, nothing sounding
    engine.process(on(36))
    # offset 4: four cascade inversions above root position
    assert engine.process(on(60)) == [on(76), on(79), on(84)]


def test_mod_wheel_revoices_held_chords():
    engine = ChordEngine()
    engine.process(on(36))
    engine.process(on(60))                    # 60 64 67
    out = engine.process(cc(1, 127))
    assert out == [off(60), off(64), off(67), on(76), on(79), on(84)]
    out = engine.process(cc(1, 0))            # wheel back down -> original
    assert out == [off(76), off(79), off(84), on(60), on(64), on(67)]


def test_mod_wheel_ignores_single_notes():
    engine = ChordEngine()
    engine.process(on(60))                    # passthrough single note
    assert engine.process(cc(1, 127)) == []   # nothing to re-voice
    assert engine.process(off(60)) == [off(60)]


def test_spread_lifts_second_highest_voice():
    engine = ChordEngine(spread=True)
    engine.process(on(36))                    # major
    # closed (60, 64, 67) -> lift 64 an octave -> (60, 67, 76)
    assert engine.process(on(60)) == [on(60), on(67), on(76)]


def test_spread_on_dyad_voicing():
    engine = ChordEngine(key=0, voicing="1-3", spread=True)
    # 1-3 dyad (60, 64): the third lifts an octave -> open tenth
    assert engine.process(on(60)) == [on(60), on(76)]


def test_spread_on_four_note_chord():
    engine = ChordEngine(spread=True)
    engine.process(on(37))                    # maj7
    # closed (60, 64, 67, 71) -> the 3rd (64) lifts -> (60, 67, 71, 76)
    assert engine.process(on(60)) == [on(60), on(67), on(71), on(76)]


def test_set_spread_morphs_held_chords_keeping_common_tones():
    engine = ChordEngine()
    engine.process(on(36))
    engine.process(on(60))                    # closed 60 64 67
    out = engine.set_spread(True)             # -> 60 67 76; 60 and 67 ring on
    assert out == [off(64), on(76)]
    out = engine.set_spread(False)
    assert out == [off(76), on(64)]


def test_set_spread_noop_when_unchanged():
    engine = ChordEngine(spread=True)
    assert engine.set_spread(True) == []


def test_current_chord_identifies_modifier_combos():
    engine = ChordEngine()
    assert engine.current_chord == ""
    engine.process(on(37))                    # maj7
    engine.process(on(41))                    # + add9
    engine.process(on(60))
    assert engine.current_chord == "C maj9"   # 1 3 5 7 9 is a maj9
    engine.process(off(60))
    assert engine.current_chord == ""


def test_current_chord_shows_key_mode_and_single_notes():
    engine = ChordEngine(key=0)
    engine.process(on(62))
    assert engine.current_chord == "D minor"
    engine.process(off(62))
    engine.process(on(61))                    # non-scale passthrough
    assert engine.current_chord == "C#4"
    engine.process(off(61))


def test_current_chord_identifies_stacked_roots():
    engine = ChordEngine(key=0)
    engine.process(on(60))                    # C major: C E G
    engine.process(on(64))                    # E minor: E G B stacked on top
    assert engine.current_chord == "C maj7"   # C E G B is one chord


def test_identify_chord_shapes():
    from chords import identify_chord
    assert identify_chord({60, 64, 67, 71}) == "C maj7"
    assert identify_chord({62, 65, 69, 72}) == "D min7"
    assert identify_chord({60, 64, 67, 70}) == "C 7"
    assert identify_chord({60, 63, 66, 69}) == "C dim7"
    assert identify_chord({55, 60, 64}) == "C major"      # inversion, G bass
    assert identify_chord({60, 72}) == "C"                # octaves
    assert identify_chord({60}) == "C4"


def test_identify_chord_names_anything_as_root_plus_tensions():
    from chords import identify_chord
    # C major + D minor: C D E F G A -> C with 9, 11, 13
    assert identify_chord({60, 62, 64, 65, 67, 69}) == "C maj(9,11,13)"
    # Hendrix chord: E7#9
    assert identify_chord({52, 56, 62, 67}) == "E 7(#9)"
    # even a tone cluster gets one name, never two chords
    assert identify_chord({60, 61, 62}) == "C sus2(b9)"


def test_changing_modifier_reshapes_held_chord():
    engine = ChordEngine()
    engine.process(on(36))                    # major
    engine.process(on(60))                    # 60 64 67
    out = engine.process(on(37))              # add maj7 while chord is held
    assert out == [on(71)]                    # B joins on top (never in bass)
    out = engine.process(off(37))             # let go of maj7
    assert out == [off(71)]                   # back to plain major


def test_pressing_modifier_blooms_held_single_note():
    engine = ChordEngine()
    engine.process(on(60))                    # bare passthrough note
    out = engine.process(on(36))              # hold major afterwards
    assert out == [on(64), on(67)]            # note blooms into the chord
    out = engine.process(off(36))
    assert out == [off(64), off(67)]          # collapses back to the note
    assert engine.sounding_notes == [60]


def test_mono_new_root_releases_previous_chord():
    engine = ChordEngine(mono=True)
    engine.process(on(36))                    # major
    engine.process(on(60))                    # C: 60 64 67
    out = engine.process(on(65))              # F takes over, voice-led F/C
    assert out == [off(60), off(64), off(67), on(60), on(65), on(69)]
    assert engine.sounding_notes == [60, 65, 69]


def test_mono_note_off_still_releases():
    engine = ChordEngine(mono=True)
    engine.process(on(36))
    engine.process(on(60))
    assert engine.process(off(60)) == [off(60), off(64), off(67)]
    assert engine.sounding_notes == []


def test_set_mono_keeps_only_newest_chord():
    engine = ChordEngine()
    engine.process(on(36))
    engine.process(on(60))                    # C: 60 64 67
    engine.process(on(72))                    # led near it: 64 67 72
    out = engine.set_mono(True)               # C released, C5 chord stays
    assert out == [off(60)]                   # 64 67 shared, only 60 stops
    assert engine.sounding_notes == [64, 67, 72]
    assert engine.set_mono(True) == []        # no-op when unchanged


def test_current_chord_never_shows_two_chords():
    engine = ChordEngine(key=0)
    engine.process(on(60))                    # C major
    engine.process(on(62))                    # D minor stacked on top
    assert engine.current_chord == "C maj(9,11,13)"


def test_key_mode_passes_non_scale_notes_through():
    engine = ChordEngine(key=0)               # key of C
    assert engine.process(on(61)) == [on(61)]  # C# not in C major
    assert engine.process(off(61)) == [off(61)]


def test_offkey_dom7_plays_tritone_sub_dominant():
    engine = ChordEngine(key=0, offkey="dom7")
    # C# in C major: dominant 7th on the pressed key, resolving down to C
    assert engine.process(on(61)) == [on(61), on(65), on(68), on(71)]
    assert engine.process(off(61)) == [off(61), off(65), off(68), off(71)]
    # diatonic notes unaffected
    assert engine.process(on(60)) == [on(60), on(64), on(67)]


def test_offkey_V7_plays_functional_dominant_of_note_below():
    engine = ChordEngine(key=0, offkey="V7")
    # C#4 -> G7 (V of C), voiced below the pressed key
    assert engine.process(on(61)) == [on(55), on(59), on(62), on(65)]
    assert engine.process(off(61)) == [off(55), off(59), off(62), off(65)]
    # Bb4 -> E7 (V of A); fresh engine so voice leading doesn't relocate it
    engine2 = ChordEngine(key=0, offkey="V7")
    assert engine2.process(on(70)) == [on(64), on(68), on(71), on(74)]
    engine2.process(off(70))


def test_offkey_snap_plays_the_diatonic_neighbor_below():
    engine = ChordEngine(key=0, offkey="snap")
    assert engine.process(on(61)) == [on(60), on(64), on(67)]   # C# -> C major
    assert engine.process(off(61)) == [off(60), off(64), off(67)]
    engine.process(on(66))                    # F# -> F major, voice-led F/C
    assert engine.sounding_notes == [60, 65, 69]
    engine.process(off(66))


def test_offkey_snap_shares_tones_with_the_real_degree():
    engine = ChordEngine(key=0, offkey="snap")
    engine.process(on(60))                    # C major
    assert engine.process(on(61)) == []       # C# snaps to the same chord
    assert engine.process(off(60)) == []      # still owned by the C# press
    assert engine.process(off(61)) == [off(60), off(64), off(67)]


def test_offkey_modifier_still_overrides():
    engine = ChordEngine(key=0, offkey="snap")
    engine.process(on(38))                    # minor modifier held
    assert engine.process(on(61)) == [on(61), on(64), on(68)]   # C# minor


def test_key_mode_flattens_out_of_scale_ninths():
    engine = ChordEngine(key=0)               # C major
    engine.process(on(41))                    # add9 modifier (F key)
    # add9 on E builds on the diatonic E minor; the 9th bends to b9 (F)
    assert engine.process(on(64)) == [on(64), on(67), on(71), on(77)]
    engine.process(off(64))
    engine.process(off(41))


def test_key_mode_raises_out_of_scale_fourths():
    engine = ChordEngine(key=0)               # C major
    engine.process(on(42))                    # sus4 modifier (F# key)
    # sus4 on F: the 4th would be Bb, out of key -> #11 (B natural)
    assert engine.process(on(65)) == [on(65), on(71), on(72)]
    engine.process(off(65))
    engine.process(off(42))


def test_key_mode_flattens_out_of_scale_thirteenths():
    engine = ChordEngine(key=0)               # C major
    engine.process(on(43))                    # 13 modifier (G key)
    # 13 on E builds on the diatonic Em7; the 13th bends to b13 (C)
    assert engine.process(on(64)) == [on(64), on(67), on(71), on(74), on(84)]
    engine.process(off(64))


def test_conforming_keys_follow_the_degree_quality():
    engine = ChordEngine(key=0)
    engine.process(on(41))                    # add9
    # on C (major degree): C major + D
    assert engine.process(on(60)) == [on(60), on(64), on(67), on(74)]
    engine.process(off(60))
    engine.process(off(41))
    engine2 = ChordEngine(key=0)
    engine2.process(on(43))                   # 13 on G: diatonic G7 + 13 (E)
    assert engine2.process(on(67)) == [on(67), on(71), on(74), on(77), on(88)]


def test_explicit_quality_keys_still_override_key():
    engine = ChordEngine(key=0)
    engine.process(on(36))                    # explicit major
    assert engine.process(on(64)) == [on(64), on(68), on(71)]   # E major
    engine.process(off(64))
    engine.process(off(36))
    engine.process(on(37))                    # explicit maj7 on D
    assert engine.process(on(62)) == [on(62), on(66), on(69), on(73)]


def test_conforming_keys_fall_back_off_scale():
    engine = ChordEngine(key=0)
    engine.process(on(41))                    # add9 on C#: no diatonic base,
    out = engine.process(on(61))              # literal add9 applies (bent 9)
    assert [m.note for m in out] == [61, 65, 68, 74]


def test_tensions_untouched_without_key_or_when_in_scale():
    engine = ChordEngine()                    # no key: leave tensions alone
    engine.process(on(41))                    # add9
    assert engine.process(on(64)) == [on(64), on(68), on(71), on(78)]
    engine2 = ChordEngine(key=0)
    engine2.process(on(41))                   # add9 on C: D is in scale
    assert engine2.process(on(60)) == [on(60), on(64), on(67), on(74)]


def test_voicing_sevenths_plays_diatonic_seventh_chords():
    engine = ChordEngine(key=0, voicing="1-3-5-7")
    assert engine.process(on(60)) == [on(60), on(64), on(67), on(71)]  # Cmaj7
    engine.process(off(60))
    engine2 = ChordEngine(key=0, voicing="1-3-5-7")
    assert engine2.process(on(62)) == [on(62), on(65), on(69), on(72)]  # Dm7
    engine3 = ChordEngine(key=0, voicing="1-3-5-7")
    assert engine3.process(on(67)) == [on(67), on(71), on(74), on(77)]  # G7


def test_voicing_power_chord_plays_root_and_fifth():
    engine = ChordEngine(key=0, voicing="1-5")
    assert engine.process(on(60)) == [on(60), on(67)]
    engine.process(off(60))
    assert engine.process(on(62)) == [on(62), on(69)]
    engine.process(off(62))
    engine2 = ChordEngine(key=0, voicing="1-5")
    assert engine2.process(on(71)) == [on(71), on(77)]   # vii keeps its b5


def test_voicing_dyad_plays_root_and_third():
    engine = ChordEngine(key=0, voicing="1-3")
    assert engine.process(on(60)) == [on(60), on(64)]
    engine.process(off(60))
    assert engine.process(on(62)) == [on(62), on(65)]   # minor third for ii


def test_voicing_smart_picks_by_voice_leading():
    engine = ChordEngine(key=0, voicing="smart")
    # no context yet: plain triad
    assert engine.process(on(60)) == [on(60), on(64), on(67)]
    engine.process(off(60))
    # next chord may be triad or seventh, but always diatonic to the degree
    out = engine.process(on(65))
    pcs = {m.note % 12 for m in out}
    assert pcs <= {5, 9, 0, 4}                # F maj7 tones at most
    assert len(out) in (3, 4)


def test_strict_sevenths_keep_the_root_in_the_bass():
    engine = ChordEngine(key=0, voicing="1-3-5-7")
    engine.process(on(60))                    # Cmaj7: 60 64 67 71
    engine.process(off(60))
    # In 1-3-5-7 mode the root is always the bass: no F/C inversions.
    assert engine.process(on(65)) == [on(65), on(69), on(72), on(76)]


def test_strict_sevenths_wheel_rolls_whole_octaves():
    engine = ChordEngine(key=0, voicing="1-3-5-7")
    engine.process(cc(1, 32))                 # one inversion step requested
    # the bass must stay on the root, so the wheel lands a full octave up
    assert engine.process(on(60)) == [on(72), on(76), on(79), on(83)]


def test_seventh_never_lands_in_the_bass_via_voice_leading():
    engine = ChordEngine(key=0, voicing="smart")
    engine.process(on(36 + 1))                # maj7 modifier for context
    engine.process(on(60))                    # Cmaj7
    engine.process(off(60))
    engine.process(off(36 + 1))
    out = engine.process(on(65))              # F led near it (smart voicing)
    notes = sorted(m.note for m in out)
    assert notes[0] % 12 != 4                 # E never in the bass


def test_seventh_never_lands_in_the_bass_via_wheel():
    engine = ChordEngine()
    engine.process(on(37))                    # maj7 modifier
    engine.process(cc(1, 80))                 # wheel: 3 inversion steps
    # step 3 of Cmaj7 would be B-C-E-G; it rolls one further to C on top
    assert engine.process(on(60)) == [on(72), on(76), on(79), on(83)]
    engine = ChordEngine(voice_lead=False)
    engine.process(on(36))                    # major
    engine.process(on(60))                    # C: 60 64 67
    engine.process(off(60))
    # with leading off, F stays in root position instead of F/C
    assert engine.process(on(65)) == [on(65), on(69), on(72)]


def test_voice_lead_toggles_live():
    engine = ChordEngine()
    engine.process(on(36))
    engine.process(on(60))
    engine.process(off(60))
    engine.voice_lead = False
    assert engine.process(on(65)) == [on(65), on(69), on(72)]
    engine.process(off(65))
    engine.voice_lead = True
    # led near the previous F (65 69 72): C comes out as C/E, not root position
    assert engine.process(on(60)) == [on(64), on(67), on(72)]


def test_disabling_voice_lead_resets_held_chords_to_root_position():
    engine = ChordEngine()
    engine.process(on(36))                    # major
    engine.process(on(60))                    # C: 60 64 67
    engine.process(off(60))
    engine.process(on(65))                    # F voice-led to F/C: 60 65 69
    out = engine.set_voice_lead(False)        # morphs back to root position
    assert out == [off(60), on(72)]
    assert engine.sounding_notes == [65, 69, 72]
    assert engine.set_voice_lead(False) == [] # no-op when unchanged


def test_voice_leading_register_stays_anchored_over_time():
    engine = ChordEngine(key=0)
    basses = []
    for _ in range(12):                       # C Am F G, three times around
        for root in (60, 69, 65, 67):
            out = engine.process(mido.Message("note_on", note=root,
                                              velocity=100))
            ons = [m.note for m in out if m.type == "note_on"]
            if ons:
                basses.append(min(min(ons), root))
            engine.process(mido.Message("note_off", note=root, velocity=0))
    # the lowest sounded pitch never sinks more than an octave under the
    # played roots, and never climbs above them: no register drift
    assert min(basses) >= 60 - 12
    assert max(basses) <= 69


def test_voicing_does_not_touch_modifier_triads():
    engine = ChordEngine(key=0, voicing="1-3")
    engine.process(on(36))                    # major modifier held
    assert engine.process(on(60)) == [on(60), on(64), on(67)]


def test_shell_voicing_drops_fifth_from_seventh_chords():
    engine = ChordEngine(voicing="1-3")
    engine.process(on(37))                    # maj7 key
    assert engine.process(on(60)) == [on(60), on(64), on(71)]
    engine.process(off(60))
    engine.process(off(37))
    engine.process(on(39))                    # min7 key
    assert engine.process(on(60)) == [on(60), on(63), on(70)]
    engine3 = ChordEngine(voicing="1-3")
    engine3.process(on(43))                   # 13 key: richer, stays whole
    assert engine3.process(on(60)) == [on(60), on(64), on(67), on(70), on(81)]


def test_shell_voicing_applies_to_offkey_dominants():
    engine = ChordEngine(key=0, voicing="1-3", offkey="dom7")
    assert engine.process(on(61)) == [on(61), on(65), on(71)]   # C#7 shell
    engine2 = ChordEngine(key=0, voicing="1-3", offkey="V7")
    assert engine2.process(on(61)) == [on(55), on(59), on(65)]  # G7 shell


def test_offkey_dominants_keep_fifth_in_triad_voicing():
    engine = ChordEngine(key=0, voicing="1-3-5", offkey="dom7")
    assert engine.process(on(61)) == [on(61), on(65), on(68), on(71)]


def test_modifier_overrides_key_mode():
    engine = ChordEngine(key=0)               # key of C
    engine.process(on(38))                    # hold minor modifier
    assert engine.process(on(60)) == [on(60), on(63), on(67)]   # C minor
    engine.process(off(60))
    engine.process(off(38))                   # release -> key mode again
    assert engine.process(on(60)) == [on(60), on(64), on(67)]   # C major


@pytest.mark.parametrize("num,name", [
    (60, "C4"), (36, "C2"), (0, "C-1"), (127, "G9"), (61, "C#4"), (95, "B6"),
])
def test_note_name(num, name):
    assert note_name(num) == name


@pytest.mark.parametrize("text,num", [
    ("C4", 60), ("c2", 36), ("F#1", 30), ("Gb1", 30), ("C-1", 0), ("G9", 127),
    ("36", 36), ("0", 0),
])
def test_parse_note_accepts_names_and_integers(text, num):
    assert parse_note(text) == num


@pytest.mark.parametrize("text", ["", "H2", "C", "4C", "C#", "A9", "C10", "-1", "128", "C##2", None])
def test_parse_note_rejects_garbage_and_out_of_range(text):
    assert parse_note(text) is None


def test_sounding_notes_tracks_output():
    engine = ChordEngine()
    assert engine.sounding_notes == []
    engine.process(on(36))
    engine.process(on(60))
    assert engine.sounding_notes == [60, 64, 67]
    engine.process(off(60))
    assert engine.sounding_notes == []
