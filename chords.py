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

    def process(self, msg):
        """Return the list of messages to send for one incoming message."""
        if msg.type == "note_on":
            if self._in_zone(msg.note):
                offset = msg.note - self.zone_base
                if offset in self.chord_map:
                    if offset in self._held_modifiers:
                        self._held_modifiers.remove(offset)
                    self._held_modifiers.append(offset)
                return []
            return self._press(msg.note, msg.velocity)
        return []

    def _in_zone(self, note):
        return self.zone_base <= note < self.zone_base + 12

    def _press(self, root, velocity):
        intervals = self.chord_map[self._held_modifiers[-1]]
        return [
            mido.Message("note_on", note=root + i, velocity=velocity,
                         channel=self.channel)
            for i in intervals
        ]
