"""Pure chord logic for the Orchid-style MIDI processor. No MIDI I/O here."""

import mido

# Bottom key of the modifier zone (C2 by default); the zone spans 12 keys.
ZONE_BASE = 36

# Zone offset (semitones above ZONE_BASE) -> chord intervals from the root.
CHORD_MAP = {
    0: (0, 4, 7),        # C  major
    1: (0, 3, 7),        # C# minor
    2: (0, 4, 7, 11),    # D  maj7
    3: (0, 3, 7, 10),    # D# min7
    4: (0, 4, 7, 10),    # E  dom7
    5: (0, 5, 7),        # F  sus4
    6: (0, 2, 7),        # F# sus2
    7: (0, 3, 6),        # G  dim
    8: (0, 4, 8),        # G# aug
    9: (0, 4, 7, 14),    # A  add9
}


class ChordEngine:
    """Stateful message transformer: feed it mido messages, send what it returns."""

    def __init__(self, zone_base=ZONE_BASE, chord_map=None, channel=0):
        self.zone_base = zone_base
        self.chord_map = CHORD_MAP if chord_map is None else chord_map
        self.channel = channel
        self._held_modifiers = []  # zone offsets, oldest first; last one wins
        self._active = {}   # root note -> list of pitches emitted for it
        self._counts = {}   # pitch -> number of active roots sounding it

    def process(self, msg):
        """Return the list of messages to send for one incoming message."""
        if msg.type == "note_on" and msg.velocity == 0:
            msg = mido.Message("note_off", note=msg.note, velocity=0,
                               channel=msg.channel)
        if msg.type == "note_on":
            if self._in_zone(msg.note):
                offset = msg.note - self.zone_base
                if offset in self.chord_map:
                    if offset in self._held_modifiers:
                        self._held_modifiers.remove(offset)
                    self._held_modifiers.append(offset)
                return []
            return self._press(msg.note, msg.velocity)
        if msg.type == "note_off":
            if self._in_zone(msg.note):
                offset = msg.note - self.zone_base
                if offset in self._held_modifiers:
                    self._held_modifiers.remove(offset)
                return []
            return self._release(msg.note)
        return [msg]

    def _in_zone(self, note):
        return self.zone_base <= note < self.zone_base + 12

    def _press(self, root, velocity):
        out = []
        if root in self._active:
            out.extend(self._release(root))
        if self._held_modifiers:
            intervals = self.chord_map[self._held_modifiers[-1]]
            notes = [root + i for i in intervals if root + i <= 127]
        else:
            notes = [root]
        self._active[root] = notes
        for note in notes:
            self._counts[note] = self._counts.get(note, 0) + 1
            if self._counts[note] == 1:
                out.append(self._note_on(note, velocity))
        return out

    def _release(self, root):
        out = []
        for note in self._active.pop(root, [root]):
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
        return out

    def _note_on(self, note, velocity):
        return mido.Message("note_on", note=note, velocity=velocity,
                            channel=self.channel)

    def _note_off(self, note):
        return mido.Message("note_off", note=note, velocity=0,
                            channel=self.channel)
