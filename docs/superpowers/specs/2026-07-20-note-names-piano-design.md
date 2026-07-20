# Note-Name Base Field + Live Piano View — Design

**Date:** 2026-07-20
**Status:** Approved

## Purpose

Two GUI usability upgrades: (1) the base-note field speaks musician ("C2",
"F#1") instead of raw MIDI numbers; (2) a live piano-keyboard strip at the
bottom of the window lights up the notes currently sounding at the output —
play a chord, see its keys lit. (User chose the live keyboard over a
scrolling piano roll.)

## Note naming convention

Scientific pitch notation with middle C = C4 = MIDI 60 (so MIDI 36 = C2,
matching existing docs). Sharps preferred in output ("C#2"); input accepts
sharps, flats ("Db2"), lowercase, and plain integers ("36").

## Changes

### 1. `chords.py` — pure helpers (unit-tested)
- `note_name(n) -> str` — "C4" for 60, "C-1" for 0, "G8" for 127.
- `parse_note(text) -> int | None` — parses note names (regex
  `^[A-Ga-g][#b]?-?\d+$`) and plain integers; returns None for anything
  unparsable or outside 0–127.
- `ChordEngine.sounding_notes` property — sorted list of pitches currently
  sounding (keys of the existing refcount dict). Feeds the piano view.

### 2. `gui.py` — validation + display
- `validate_config` parses base via `parse_note`; error message becomes
  "Base note must be a note between C-1 and G#8 (like C2)." Range stays
  0–116 (12-key zone must fit in MIDI range). Channel unchanged.
- Settings still store base as an integer (no migration); the field displays
  `note_name(stored_base)` on launch.

### 3. `gui.py` — `PianoView(NSView)`
- Custom view, range C1–C7 (MIDI 24–96), drawn in `drawRect_`: white keys as
  a row of rects, black keys overlaid at 60% width/height, sounding notes
  filled with the system accent blue (white and black alike), thin gray
  outline, notes outside the range simply not shown.
- `set_sounding(notes)` (python_method) stores a set and calls
  `setNeedsDisplay_`; only ever invoked on the main thread.
- Wiring: the mido callback marshals one `_update_ui(status_text,
  sounding_notes)` call through `AppHelper.callAfter`; stop/close clears the
  view. Single passthrough notes light up too (they are refcounted like
  chord tones).
- Window grows to 420×330; existing controls shift up; piano strip occupies
  the bottom (20, 16, 380×88).

## Not changing
- Engine message processing, settings persistence format, launcher, CLI,
  bundle layout. No new dependencies.

## Testing
- Unit: `note_name`/`parse_note` (round trip, flats, lowercase, integers,
  garbage, out-of-range), `sounding_notes` lifecycle, `validate_config`
  accepting "C2"/"36" and rejecting bad/out-of-range names (existing
  numeric-range tests updated to the new error text).
- `import gui` smoke test + `./build_app.sh` + signature verify; visual
  check is the user's double-click (no venv rebuild needed — no new deps).
