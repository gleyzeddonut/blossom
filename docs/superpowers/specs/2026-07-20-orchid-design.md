# Orchid-style Chord MIDI Processor — Design

**Date:** 2026-07-20
**Status:** Approved

## Purpose

A DIY software version of the Telepathic Instruments Orchid: hold a chord-quality
key and press a root note, and a full chord plays on an external synth. Runs on
the user's Mac between an existing MIDI keyboard and existing analog synths.
Total hardware cost: $0.

## Decisions made during brainstorming

- **Platform:** computer in the loop (macOS, CoreMIDI). A standalone Pi/Teensy
  port is a possible future step, not part of this design.
- **Chord-quality selection:** the bottom 12 keys of the MIDI keyboard act as
  modifier keys (left hand picks quality, right hand plays roots).
- **Output:** the full chord is sent on one MIDI channel to a polyphonic synth.
  A voice-per-channel split across mono synths is a future extension.
- **No modifier held:** incoming notes pass through unchanged (single-note
  melody playing works without a mode switch).
- **Implementation:** a single Python script using `mido` with the
  `python-rtmidi` backend. DAW chord tools (Logic Chord Trigger, Ableton Chord)
  were ruled out because they map fixed chords per key and cannot express the
  "hold modifier + root" conditional behavior. Max/Pd was ruled out as a
  heavier dependency with fiddlier state handling.

## Architecture

One script, `orchid.py`, with two layers:

1. **Pure chord logic** — a function taking (held modifiers, incoming note
   message, current state) and returning the outgoing note messages plus new
   state. No MIDI I/O; fully unit-testable.
2. **I/O shell** — opens MIDI input/output ports via `mido`, feeds incoming
   messages through the chord logic, sends the results, and handles startup
   (port selection) and shutdown (panic/note-offs).

## Behavior

### Port selection
On launch the script lists available CoreMIDI input and output ports. The user
picks each by name substring or number via CLI arguments; with no arguments,
the script prints the port list and exits with usage help.

### Modifier zone
- The lowest 12 keys of the controller form the modifier zone. The zone's base
  MIDI note is a constant at the top of the script (default 36 / C2 — adjust to
  the controller's actual bottom key).
- Modifier-zone note-ons and note-offs are consumed, never forwarded.
- Chord map (a dict at the top of the script, intervals in semitones from root):

  | Zone key | Quality | Intervals |
  |---|---|---|
  | C  | major | 0 4 7 |
  | C# | minor | 0 3 7 |
  | D  | maj7  | 0 4 7 11 |
  | D# | min7  | 0 3 7 10 |
  | E  | dom7  | 0 4 7 10 |
  | F  | sus4  | 0 5 7 |
  | F# | sus2  | 0 2 7 |
  | G  | dim   | 0 3 6 |
  | G# | aug   | 0 4 8 |
  | A  | add9  | 0 4 7 14 |
  | A#, B | unassigned (consumed, no effect) |

- If multiple modifiers are held, the most recently pressed wins. The script
  keeps held modifiers as an ordered structure so releasing the newest falls
  back to the previous one.

### Note handling
- **Note-on above the zone, modifier held:** emit the chord — root plus
  intervals — at the incoming velocity, on the configured output channel.
  Emitted notes above MIDI 127 are dropped (not wrapped).
- **Note-on above the zone, no modifier:** forward the note unchanged.
- **Note-off above the zone:** release exactly the notes that were emitted for
  that root when it was pressed, regardless of what modifiers are held now.
- **All other messages** (pitch bend, CCs, aftertouch, program change): forward
  unchanged.

### State and correctness
- Per active root key, the script records the exact set of notes it emitted.
- Sounding notes are **reference-counted**: a note-off is only sent when the
  last chord/note using that pitch releases it. Overlapping chords sharing a
  tone (C major and E minor both contain G) never cut each other off.
- Retriggering an already-held root re-sends note-ons without corrupting
  the counts (the previous emission for that root is released first).
- On exit (Ctrl+C or error), the script sends note-offs for every tracked
  sounding note before closing ports — no stuck notes on analog synths.

## Testing

- Unit tests (pytest) for the pure chord-logic layer: chord construction per
  quality, velocity passthrough, modifier press/release ordering, no-modifier
  passthrough, note-off matching after modifier release, reference counting of
  shared tones, range clamping at the top of MIDI range, panic/flush.
- Manual integration check: run against the IAC Driver bus or directly against
  the hardware MIDI interface and poly synth.

## Out of scope (future ideas, not in v1)

- Voice-per-channel chord splitting across monophonic synths
- Strum/arpeggio timing between chord tones
- Latching chord qualities
- Voicing options (inversions, spread, drop-2)
- Porting to Raspberry Pi for standalone use
