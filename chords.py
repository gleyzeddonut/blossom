"""Pure chord logic for the Orchid-style MIDI processor. No MIDI I/O here."""

import re

import mido

# Bottom key of the modifier zone (C2 by default); the zone spans 12 keys.
ZONE_BASE = 36

# Zone offset (semitones above ZONE_BASE) -> chord intervals from the root.
CHORD_MAP = {
    0: (0, 4, 7),           # C  major
    1: (0, 4, 7, 11),       # C# maj7
    2: (0, 3, 7),           # D  minor
    3: (0, 3, 7, 10),       # D# min7
    4: (0, 4, 7, 10),       # E  dom7
    5: (0, 4, 7, 14),       # F  add9
    6: (0, 5, 7),           # F# sus4
    7: (0, 4, 7, 10, 21),   # G  13
    8: (0, 3, 6, 10),       # G# half-dim
    9: (0, 3, 6),           # A  dim
    10: (0, 4, 8),          # A# aug
}

# Display names for the qualities in CHORD_MAP, keyed by the same offsets.
CHORD_NAMES = {
    0: "major", 1: "maj7", 2: "minor", 3: "min7", 4: "dom7",
    5: "add9", 6: "sus4", 7: "13", 8: "halfdim", 9: "dim", 10: "aug",
}

# Every quality a chord key can be assigned to, in menu order.
QUALITY_INTERVALS = {
    "major": (0, 4, 7), "maj7": (0, 4, 7, 11), "maj9": (0, 4, 7, 11, 14),
    "6": (0, 4, 7, 9), "add9": (0, 4, 7, 14),
    "dom7": (0, 4, 7, 10), "9": (0, 4, 7, 10, 14), "13": (0, 4, 7, 10, 21),
    "sus2": (0, 2, 7), "sus4": (0, 5, 7),
    "minor": (0, 3, 7), "min7": (0, 3, 7, 10), "min9": (0, 3, 7, 10, 14),
    "min6": (0, 3, 7, 9), "minMaj7": (0, 3, 7, 11),
    "halfdim": (0, 3, 6, 10), "dim": (0, 3, 6), "dim7": (0, 3, 6, 9),
    "aug": (0, 4, 8),
}

# Pitch-class interval shapes (relative to a root) -> chord quality name.
# Used to identify whatever combination is actually sounding.
CHORD_SHAPES = {
    frozenset({0, 7}): "5",
    frozenset({0, 4, 7}): "major",
    frozenset({0, 3, 7}): "minor",
    frozenset({0, 3, 6}): "dim",
    frozenset({0, 4, 8}): "aug",
    frozenset({0, 5, 7}): "sus4",
    frozenset({0, 2, 7}): "sus2",
    frozenset({0, 4, 7, 11}): "maj7",
    frozenset({0, 3, 7, 10}): "min7",
    frozenset({0, 4, 7, 10}): "7",
    frozenset({0, 3, 6, 10}): "m7b5",
    frozenset({0, 3, 6, 9}): "dim7",
    frozenset({0, 3, 7, 11}): "minMaj7",
    frozenset({0, 4, 7, 9}): "6",
    frozenset({0, 3, 7, 9}): "min6",
    frozenset({0, 2, 4, 7}): "add9",
    frozenset({0, 2, 3, 7}): "min add9",
    frozenset({0, 2, 4, 7, 11}): "maj9",
    frozenset({0, 2, 3, 7, 10}): "min9",
    frozenset({0, 2, 4, 7, 10}): "9",
    frozenset({0, 4, 7, 9, 10}): "13",
    frozenset({0, 2, 4, 7, 9, 10}): "13",
    frozenset({0, 2, 4, 5, 7, 11}): "maj13",
}


# Scale-degree names for notes outside a chord's core tones.
_TENSION_NAMES = {1: "b9", 2: "9", 3: "#9", 5: "11", 6: "#11", 8: "b13", 9: "13"}


def _general_name(root, pcs):
    """Name any pitch-class set from a root: core quality plus tensions."""
    rel = {(pc - root) % 12 for pc in pcs}
    used = {0, 7}                         # root and fifth are never tensions
    third = None
    if 4 in rel:
        third = "maj"
        used.add(4)
    elif 3 in rel:
        third = "min"
        used.add(3)
    seventh = None
    if 10 in rel:
        seventh = "7"
        used.add(10)
    elif 11 in rel:
        seventh = "maj7"
        used.add(11)
    if third == "maj":
        quality = {"7": "7", "maj7": "maj7", None: "maj"}[seventh]
    elif third == "min":
        quality = {"7": "min7", "maj7": "minMaj7", None: "min"}[seventh]
    else:
        sus = ""
        if 5 in rel:
            sus = "sus4"
            used.add(5)
        elif 2 in rel:
            sus = "sus2"
            used.add(2)
        quality = (sus + (seventh or "")) or "maj"
    tensions = [_TENSION_NAMES[i] for i in sorted(rel - used)
                if i in _TENSION_NAMES]
    if tensions:
        quality = "%s(%s)" % (quality, ",".join(tensions))
    return "%s %s" % (NOTE_NAMES[root], quality)


def identify_chord(pitches):
    """Single name for whatever is sounding, e.g. 'C maj7' or
    'C maj(9,11,13)'. Exact shapes win; anything else gets named as the
    best root plus tensions. Never returns two chord names."""
    if not pitches:
        return None
    if len(pitches) == 1:
        return note_name(next(iter(pitches)))
    pcs = {p % 12 for p in pitches}
    bass = min(pitches) % 12
    if len(pcs) == 1:
        return NOTE_NAMES[bass]           # octaves of one pitch class
    order = [bass] + sorted(pcs - {bass})
    for root in order:
        shape = frozenset((pc - root) % 12 for pc in pcs)
        name = CHORD_SHAPES.get(shape)
        if name:
            return "%s %s" % (NOTE_NAMES[root], name)

    def plausibility(root):
        rel = {(pc - root) % 12 for pc in pcs}
        score = 3 if root == bass else 0
        if 3 in rel or 4 in rel:
            score += 2                    # has a third
        if 7 in rel:
            score += 1                    # has a fifth
        if 10 in rel or 11 in rel:
            score += 1                    # has a seventh
        return score - len(rel - {0, 3, 4, 7, 10, 11})   # fewer tensions

    return _general_name(max(order, key=plausibility), pcs)

# Major-scale pitch classes relative to the key root.
MAJOR_SCALE = {0, 2, 4, 5, 7, 9, 11}

# Chord intervals that are tensions (9ths, 11ths/sus4s, 13ths). In key mode
# these bend to the scale; core tones (3rd/5th/7th) stay as played.
_TENSION_INTERVALS = {2, 5, 9, 14, 17, 21}
_FOURTHS = {5, 17}                     # snap up (Lydian #11); others snap down

# Key mode: scale degree (semitones above the key root) -> diatonic triad.
# Non-scale notes fall back to single-note passthrough.
KEY_DEGREE_CHORDS = {
    0: (0, 4, 7),    # I   major
    2: (0, 3, 7),    # ii  minor
    4: (0, 3, 7),    # iii minor
    5: (0, 4, 7),    # IV  major
    7: (0, 4, 7),    # V   major
    9: (0, 3, 7),    # vi  minor
    11: (0, 3, 6),   # vii dim
}

# "1-3" shell voicings for plain seventh chords: the 5th drops, the 7th
# stays. Triads and richer chords are left untouched.
SHELL_VOICINGS = {
    (0, 4, 7, 11): (0, 4, 11),    # maj7
    (0, 3, 7, 10): (0, 3, 10),    # min7
    (0, 4, 7, 10): (0, 4, 10),    # dom7
    (0, 3, 7, 11): (0, 3, 11),    # minMaj7
}

# Tension-add qualities conform to the key: in key mode they build on the
# degree's diatonic chord instead of forcing the mapped quality. Explicit
# quality keys (major, min7, dim...) still override the key.
CONFORM_EXTENSIONS = {"add9": (14,), "6": (9,), "9": (14,), "13": (21,)}
_SEVENTH_BASED = {"9", "13"}           # these stack on the diatonic seventh

# The same degrees as diatonic seventh chords.
KEY_DEGREE_SEVENTHS = {
    0: (0, 4, 7, 11),    # I    maj7
    2: (0, 3, 7, 10),    # ii   min7
    4: (0, 3, 7, 10),    # iii  min7
    5: (0, 4, 7, 11),    # IV   maj7
    7: (0, 4, 7, 10),    # V    dom7
    9: (0, 3, 7, 10),    # vi   min7
    11: (0, 3, 6, 10),   # vii  half-dim
}

NOTE_NAMES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")
_ACCIDENTALS = {"": 0, "#": 1, "b": -1}
_NOTE_RE = re.compile(r"^([A-Ga-g])([#b]?)(-?\d+)$")


def note_name(n):
    """Scientific pitch name for a MIDI note number (60 -> 'C4')."""
    return "%s%d" % (NOTE_NAMES[n % 12], n // 12 - 1)


def parse_note(text):
    """MIDI number for 'C4' / 'Gb1' / '60' style input; None if invalid."""
    if text is None:
        return None
    text = str(text).strip()
    if re.fullmatch(r"\d+", text):
        num = int(text)
        return num if num <= 127 else None
    match = _NOTE_RE.match(text)
    if not match:
        return None
    letter, accidental, octave = match.groups()
    semitone = NOTE_NAMES.index(letter.upper())
    num = semitone + _ACCIDENTALS[accidental] + (int(octave) + 1) * 12
    return num if 0 <= num <= 127 else None


def _cascade(notes, steps):
    """Invert a sorted chord: each positive step moves the lowest note up an
    octave; each negative step moves the highest note down. Steps that would
    leave MIDI range are skipped."""
    notes = list(notes)
    for _ in range(max(steps, 0)):
        if notes[0] + 12 > 127:
            break
        notes = sorted(notes[1:] + [notes[0] + 12])
    for _ in range(max(-steps, 0)):
        if notes[-1] - 12 < 0:
            break
        notes = sorted([notes[-1] - 12] + notes[:-1])
    return notes


class ChordEngine:
    """Stateful message transformer: feed it mido messages, send what it returns."""

    def __init__(self, zone_base=ZONE_BASE, chord_map=None, channel=0,
                 key=None, spread=False, mono=False, offkey="bypass",
                 chord_names=None, voicing="1-3-5", voice_lead=True):
        self.zone_base = zone_base
        self.chord_map = CHORD_MAP if chord_map is None else chord_map
        self.chord_names = CHORD_NAMES if chord_names is None else chord_names
        self.channel = channel
        self.key = key      # pitch class 0-11 for key mode, or None
        self.offkey = offkey       # non-scale notes: "dom7"/"snap"/"bypass"
        self.voicing = voicing     # key-mode tones: "1-3"/"1-3-5"/"1-3-5-7"/"smart"
        self.voice_lead = voice_lead   # pick inversions near the last chord
        self.spread = spread       # drop-2 voicings when True
        self.mono = mono           # one chord at a time when True
        self.wheel_offset = 0      # extra inversion steps from the mod wheel
        self._held_modifiers = []  # zone offsets, oldest first; all combine
        self._active = {}   # root note -> list of pitches emitted for it
        self._counts = {}   # pitch -> number of active roots sounding it
        self._velocities = {}      # root note -> velocity it was played with
        self._last_voicing = None  # previous chord's voicing (pre-wheel)
        self._smart_seventh = False    # last smart chord carried a 7th

    def process(self, msg):
        """Return the list of messages to send for one incoming message."""
        if msg.type == "note_on" and msg.velocity == 0:
            msg = mido.Message("note_off", note=msg.note, velocity=0,
                               channel=msg.channel)
        if msg.type == "note_on":
            if self._in_zone(msg.note):
                offset = msg.note - self.zone_base
                if (offset in self.chord_map
                        and offset not in self._held_modifiers):
                    self._held_modifiers.append(offset)
                    return self._revoice_active(include_single=True)
                return []
            return self._press(msg.note, msg.velocity)
        if msg.type == "note_off":
            if self._in_zone(msg.note):
                offset = msg.note - self.zone_base
                if offset in self._held_modifiers:
                    self._held_modifiers.remove(offset)
                    return self._revoice_active(include_single=True)
                return []
            return self._release(msg.note)
        if msg.type == "control_change" and msg.control == 1:
            return self._set_wheel(msg.value)  # mod wheel drives voicing
        return [msg]

    @property
    def current_quality(self):
        """Combined name of all held modifiers ('maj7+add9'), or None."""
        if self._held_modifiers:
            return "+".join(self.chord_names.get(m, "?")
                            for m in self._held_modifiers)
        return None

    @property
    def sounding_notes(self):
        """Sorted pitches currently sounding at the output."""
        return sorted(self._counts)

    @property
    def held_zone_notes(self):
        """Zone keys (chord keys) currently held, as MIDI notes."""
        return sorted(self.zone_base + off for off in self._held_modifiers)

    @property
    def current_chord(self):
        """One name for what's actually sounding: C major over E minor reads
        'C maj7'; unmatched stacks read as root plus tensions."""
        if not self._counts:
            return ""
        return identify_chord(set(self._counts)) or ""

    def _in_zone(self, note):
        return self.zone_base <= note < self.zone_base + 12

    def _chord_for(self, root):
        """(actual_root, intervals) for a played key: held modifiers combine
        and override key mode; key mode supplies diatonic triads; non-scale
        notes follow the offkey setting; else passthrough."""
        if self._held_modifiers:
            degree = (root - self.key) % 12 if self.key is not None else None
            diatonic = degree in KEY_DEGREE_CHORDS
            combined = set()
            for offset in self._held_modifiers:
                name = self.chord_names.get(offset)
                if diatonic and name in CONFORM_EXTENSIONS:
                    base = (KEY_DEGREE_SEVENTHS if name in _SEVENTH_BASED
                            else KEY_DEGREE_CHORDS)[degree]
                    combined.update(base)
                    combined.update(CONFORM_EXTENSIONS[name])
                else:
                    combined.update(self.chord_map[offset])
            if self.voicing == "1-3":
                combined = set(SHELL_VOICINGS.get(tuple(sorted(combined)),
                                                  combined))
            if self.key is not None:
                combined = self._diatonic_tensions(root, combined)
            return root, sorted(combined)
        if self.key is not None:
            degree = (root - self.key) % 12
            if degree in KEY_DEGREE_CHORDS:
                return root, self._degree_chord(root, degree)
            # Non-diatonic. In a major key every chromatic note sits one
            # semitone above a scale note, so "the diatonic note below" is
            # always root - 1.
            dom7 = (0, 4, 10) if self.voicing == "1-3" else (0, 4, 7, 10)
            if self.offkey == "dom7":
                # tritone-sub dominant resolving down a half step
                return root, dom7
            if self.offkey == "V7":
                # functional dominant of the diatonic note below:
                # C# -> G7 (V of C), Bb -> E7 (V of A). Same pitch class a
                # tritone from the pressed key; voiced below when possible.
                dom = root - 6 if root - 6 >= 0 else root + 6
                return dom, dom7
            if self.offkey == "snap":
                return root - 1, self._degree_chord(root - 1,
                                                    (degree - 1) % 12)
            return root, (0,)
        return root, (0,)

    def _degree_chord(self, root, degree):
        """Intervals for a diatonic degree, shaped by the voicing setting."""
        triad = KEY_DEGREE_CHORDS[degree]
        seventh = KEY_DEGREE_SEVENTHS[degree]
        if self.voicing == "1-3":
            return triad[:2]
        if self.voicing == "1-5":
            return (triad[0], triad[2])    # power chord (b5 on vii)
        if self.voicing == "1-3-5-7":
            return seventh
        if self.voicing == "smart":
            # Triads by default; the 7th joins only when it feels earned:
            # either a tone from the previous chord is still ringing and
            # becomes the 7th (suspension logic), or the 7th version
            # voice-leads clearly better than the plain triad.
            if self._last_voicing is None:
                return triad

            def cost(intervals):
                notes = [root + i for i in intervals if root + i <= 127]
                best = min(
                    sum(min(abs(n - p) for p in self._last_voicing)
                        for n in _cascade(notes, k)) + abs(k)
                    for k in (0, -1, 1, -2, 2))
                return best / float(len(notes) or 1)

            dyad = triad[:2]
            shell = (0, seventh[1], seventh[-1])   # root, 3rd, 7th
            held_pcs = {p % 12 for p in self._last_voicing}
            seventh_held = (root + seventh[-1]) % 12 in held_pcs

            def score(intervals, bias, has_seventh):
                s = cost(intervals) + bias
                if has_seventh:
                    if seventh_held and not self._smart_seventh:
                        s -= 0.5           # a ringing tone becomes the 7th
                    if self._smart_seventh:
                        s += 0.5           # discourage back-to-back 7ths
                return s

            # triad is home base (bias 0, wins ties); sparser and richer
            # shapes need to earn their place through smoother movement
            options = [(score(triad, 0.0, False), 0, triad, False),
                       (score(dyad, 0.9, False), 1, dyad, False),
                       (score(shell, 0.35, True), 2, shell, True),
                       (score(seventh, 0.3, True), 3, seventh, True)]
            _, _, chosen, self._smart_seventh = min(options)
            return chosen
        return triad

    def _diatonic_tensions(self, root, intervals):
        """Bend tension intervals to the key's scale: a 9th on E in C major
        becomes b9 (F), a sus4 on F becomes #11 (B). Fourths snap up,
        seconds/sixths snap down. Core chord tones are left alone."""
        adjusted = set()
        for i in intervals:
            if (i in _TENSION_INTERVALS
                    and (root + i - self.key) % 12 not in MAJOR_SCALE):
                i += 1 if i in _FOURTHS else -1
            adjusted.add(i)
        return adjusted

    def _bass_avoid(self, chord_root, intervals):
        """Pitch classes that may not be the bass of this chord. Sevenths
        never sit in the bass; in strict 1-3-5-7 voicing the root is the
        only allowed bass, so every other tone is excluded."""
        if (not self._held_modifiers and self.key is not None
                and self.voicing == "1-3-5-7"):
            return frozenset((chord_root + i) % 12 for i in intervals
                             if i % 12 != 0)
        return frozenset((chord_root + i) % 12 for i in intervals
                         if i % 12 in (10, 11))

    def _voice(self, notes, avoid_bass=frozenset()):
        """Voice-lead a chord toward the previous one, then apply the wheel.

        Picks the inversion (within +/-2 cascade steps) whose notes move the
        least from the last chord's voicing, with a small penalty per step so
        voicings don't drift away from root position. Inversions that would
        put an avoided pitch class (the chord's 7th) in the bass are never
        chosen. Single notes pass through untouched."""
        if len(notes) < 2:
            return notes
        if self._last_voicing is not None and self.voice_lead:
            def cost(k):
                cand = _cascade(notes, k)
                move = sum(min(abs(n - p) for p in self._last_voicing)
                           for n in cand)
                # the 2x anchor keeps voicings near root position, so the
                # register stays where the mod wheel put it
                return move + 2 * abs(k)
            candidates = [k for k in (0, -1, 1, -2, 2)
                          if _cascade(notes, k)[0] % 12 not in avoid_bass]
            best = min(candidates or [0], key=cost)
            notes = _cascade(notes, best)
        self._last_voicing = list(notes)
        notes = _cascade(notes, self.wheel_offset)
        for _ in range(4):   # wheel landed the 7th in the bass: keep rolling
            if notes[0] % 12 not in avoid_bass or notes[0] + 12 > 127:
                break
            notes = _cascade(notes, 1)
        if self.spread and len(notes) >= 2 and notes[1] + 12 <= 127:
            # spread: second-from-bottom voice (usually the 3rd) goes up an
            # octave, leaving root and 5th to anchor the low end
            notes = [notes[0]] + notes[2:] + [notes[1] + 12]
        return sorted(set(notes))   # collapse octave collisions

    def _set_wheel(self, value):
        """CC1 0-127 -> 0..4 upward inversion steps; re-voices held chords."""
        offset = value * 5 // 128
        if offset == self.wheel_offset:
            return []
        self.wheel_offset = offset
        return self._revoice_active()

    def set_spread(self, spread):
        """Toggle drop-2 voicings; re-voices held chords."""
        spread = bool(spread)
        if spread == self.spread:
            return []
        self.spread = spread
        return self._revoice_active()

    def set_voice_lead(self, on):
        """Toggle voice leading. Turning it off re-voices held chords back
        to root position and forgets the leading context."""
        on = bool(on)
        if on == self.voice_lead:
            return []
        self.voice_lead = on
        if not on:
            self._last_voicing = None
            return self._revoice_active()
        return []

    def set_mono(self, mono):
        """Toggle one-chord-at-a-time; keeps only the newest held chord."""
        mono = bool(mono)
        if mono == self.mono:
            return []
        self.mono = mono
        out = []
        if mono and len(self._active) > 1:
            for root in list(self._active)[:-1]:   # newest was added last
                out.extend(self._release(root))
        return out

    def _revoice_active(self, include_single=False):
        out = []
        for root in list(self._active):
            if include_single or len(self._active[root]) > 1:
                out.extend(self._morph(root))
        return out

    def _morph(self, root):
        """Reshape one held root to the current settings, sending only the
        difference: common tones keep ringing rather than retriggering."""
        old = self._active.get(root)
        if old is None:
            return []
        velocity = self._velocities.get(root, 64)
        chord_root, intervals = self._chord_for(root)
        base = [chord_root + i for i in intervals
                if 0 <= chord_root + i <= 127]
        new = self._voice(base,
                          avoid_bass=self._bass_avoid(chord_root, intervals))
        self._active[root] = new
        out = []
        for note in old:
            if note not in new:
                remaining = self._counts.pop(note, 0) - 1
                if remaining > 0:
                    self._counts[note] = remaining
                else:
                    out.append(self._note_off(note))
        for note in new:
            if note not in old:
                self._counts[note] = self._counts.get(note, 0) + 1
                if self._counts[note] == 1:
                    out.append(self._note_on(note, velocity))
        return out

    def _press(self, root, velocity):
        out = []
        if self.mono:
            for other in list(self._active):
                if other != root:
                    out.extend(self._release(other))
        if root in self._active:
            out.extend(self._release(root))
        chord_root, intervals = self._chord_for(root)
        base = [chord_root + i for i in intervals
                if 0 <= chord_root + i <= 127]
        notes = self._voice(
            base, avoid_bass=self._bass_avoid(chord_root, intervals))
        self._active[root] = notes
        self._velocities[root] = velocity
        for note in notes:
            self._counts[note] = self._counts.get(note, 0) + 1
            if self._counts[note] == 1:
                out.append(self._note_on(note, velocity))
        return out

    def _release(self, root):
        out = []
        self._velocities.pop(root, None)
        notes = self._active.pop(root, None)
        if notes is None:
            # Untracked root (e.g. released by mono mode, or sounding before
            # we started). Forward the off as a safety unless that pitch is
            # being sustained as part of an active chord.
            return [] if root in self._counts else [self._note_off(root)]
        for note in notes:
            remaining = self._counts.pop(note, 0) - 1
            if remaining > 0:
                self._counts[note] = remaining
            else:
                out.append(self._note_off(note))
        return out

    def flush(self):
        """Note-offs for everything sounding; call before exit to avoid stuck notes."""
        out = [self._note_off(note) for note in sorted(self._counts)]
        self._active.clear()
        self._counts.clear()
        self._velocities.clear()
        self._last_voicing = None
        return out

    def _note_on(self, note, velocity):
        return mido.Message("note_on", note=note, velocity=velocity,
                            channel=self.channel)

    def _note_off(self, note):
        return mido.Message("note_off", note=note, velocity=0,
                            channel=self.channel)
