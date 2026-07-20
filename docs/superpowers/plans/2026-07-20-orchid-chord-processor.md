# Orchid-Style Chord MIDI Processor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A Python script that sits between a MIDI keyboard and a poly synth: hold a chord-quality key in the keyboard's bottom octave, press a root note, and the full chord is sent to the synth.

**Architecture:** Two layers in two files. `chords.py` holds a pure, fully unit-tested `ChordEngine` class — MIDI messages in, MIDI messages out, no I/O. `orchid.py` is a thin CLI shell that opens CoreMIDI ports via mido, pumps messages through the engine, and flushes note-offs on exit. Spec: `docs/superpowers/specs/2026-07-20-orchid-design.md`.

**Tech Stack:** Python 3.10+, `mido` with the `python-rtmidi` backend (runtime), `pytest` (tests only).

## Global Constraints

- Runtime dependencies: `mido` and `python-rtmidi` only. Test dependency: `pytest` only.
- Flat layout: `chords.py` and `orchid.py` at repo root, tests in `tests/`.
- All work happens in the project venv: create with `python3 -m venv .venv`, invoke tools as `.venv/bin/python -m pytest ...` (never rely on an activated shell).
- The engine never mutates incoming messages' meaning: non-note messages pass through unchanged.
- Emitted chord notes above MIDI 127 are dropped, not wrapped (spec: "Note handling").
- Note-ons are emitted only when a pitch goes from 0 → 1 active users; note-offs only on 1 → 0 (reference counting, spec: "State and correctness").
- Default modifier zone base is MIDI 36 (C2); zone spans exactly 12 keys.
- Engine works in 0-based MIDI channels (mido convention); the CLI accepts 1–16 and subtracts 1.
- Commit after every task with the exact message given in the task.

## Test Helpers (used verbatim in every test below)

The top of `tests/test_chords.py` defines these once (Task 1 creates them):

```python
import mido
import pytest

from chords import ChordEngine


def on(note, velocity=100, channel=0):
    return mido.Message("note_on", note=note, velocity=velocity, channel=channel)


def off(note, channel=0):
    return mido.Message("note_off", note=note, velocity=0, channel=channel)
```

`mido.Message` objects compare by value, so tests assert directly against expected message lists. Constructing messages needs no MIDI ports or hardware.

---

### Task 1: Project setup + chord construction

**Files:**
- Create: `requirements.txt`, `.gitignore`, `chords.py`, `tests/test_chords.py`

**Interfaces:**
- Produces: `ChordEngine(zone_base=36, chord_map=None, channel=0)` with method `process(msg: mido.Message) -> list[mido.Message]`; module constants `ZONE_BASE = 36` and `CHORD_MAP: dict[int, tuple[int, ...]]` (zone offset → intervals). Later tasks extend `process` and add `flush()`.

- [ ] **Step 1: Create environment files and venv**

`requirements.txt`:
```
mido
python-rtmidi
pytest
```

`.gitignore`:
```
.venv/
__pycache__/
.pytest_cache/
```

Run:
```bash
cd /Users/dangleyzer/Documents/CLAUDE/orchid
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```
Expected: pip installs mido, python-rtmidi, pytest without errors.

- [ ] **Step 2: Write the failing tests**

Create `tests/test_chords.py` with the helpers from "Test Helpers" above, then:

```python
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
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_chords.py -v`
Expected: FAIL/ERROR with `ModuleNotFoundError: No module named 'chords'`

- [ ] **Step 4: Write the implementation**

Create `chords.py`:

```python
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
```

(`_press` is deliberately minimal — no-modifier passthrough, note tracking, and clamping arrive in Tasks 2–4.)

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_chords.py -v`
Expected: all 12 tests PASS

- [ ] **Step 6: Commit**

```bash
git add requirements.txt .gitignore chords.py tests/test_chords.py
git commit -m "feat: chord construction from held modifier keys"
```

---

### Task 2: Passthrough and modifier press/release ordering

**Files:**
- Modify: `chords.py`
- Test: `tests/test_chords.py`

**Interfaces:**
- Consumes: `ChordEngine.process`, `_press`, `_held_modifiers` from Task 1.
- Produces: `process` handles `note_off` in the zone (modifier release) and no-modifier note-ons (single-note passthrough). Behavior later tasks rely on: most-recent modifier wins; releasing it falls back to the previous one.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_chords.py`)

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_chords.py -v`
Expected: the five new tests FAIL (`IndexError` from `_held_modifiers[-1]` on passthrough; zone note_off returns `[]` only after implementation — `test_modifier_keys_are_consumed_silently` fails because `note_off` currently returns `[]` for everything, so it may pass; the passthrough and fallback tests fail).

- [ ] **Step 3: Implement**

In `chords.py`, replace `process`'s `note_on` branch ending and add a `note_off` branch — the whole method becomes:

```python
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
        if msg.type == "note_off":
            if self._in_zone(msg.note):
                offset = msg.note - self.zone_base
                if offset in self._held_modifiers:
                    self._held_modifiers.remove(offset)
                return []
            return []
        return []
```

and replace `_press` with:

```python
    def _press(self, root, velocity):
        if self._held_modifiers:
            intervals = self.chord_map[self._held_modifiers[-1]]
            notes = [root + i for i in intervals]
        else:
            notes = [root]
        return [
            mido.Message("note_on", note=note, velocity=velocity,
                         channel=self.channel)
            for note in notes
        ]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_chords.py -v`
Expected: all 17 tests PASS

- [ ] **Step 5: Commit**

```bash
git add chords.py tests/test_chords.py
git commit -m "feat: single-note passthrough and modifier ordering"
```

---

### Task 3: Note tracking, reference counting, note-off matching, flush

**Files:**
- Modify: `chords.py`
- Test: `tests/test_chords.py`

**Interfaces:**
- Consumes: `process`/`_press` from Task 2.
- Produces: `_release(root) -> list[mido.Message]`; `flush() -> list[mido.Message]`; internal state `_active: dict[int, list[int]]` (root → emitted notes) and `_counts: dict[int, int]` (pitch → active users). The 0→1 / 1→0 emission rule established here is relied on by Task 4's clamping tests.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_chords.py`)

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_chords.py -v`
Expected: the six new tests FAIL (no `_active`/`_counts`/`flush`; note_offs return `[]`).

- [ ] **Step 3: Implement**

In `chords.py`, add to `__init__` (after the `_held_modifiers` line):

```python
        self._active = {}   # root note -> list of pitches emitted for it
        self._counts = {}   # pitch -> number of active roots sounding it
```

Replace `process` with:

```python
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
        return []
```

Replace `_press` and add `_release`, `_note_on`, `_note_off`, `flush`:

```python
    def _press(self, root, velocity):
        out = []
        if root in self._active:
            out.extend(self._release(root))
        if self._held_modifiers:
            intervals = self.chord_map[self._held_modifiers[-1]]
            notes = [root + i for i in intervals]
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
```

(`self._active.pop(root, [root])` makes an untracked note-off fall through to forwarding a plain note-off for that pitch.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_chords.py -v`
Expected: all 23 tests PASS

- [ ] **Step 5: Commit**

```bash
git add chords.py tests/test_chords.py
git commit -m "feat: note tracking, shared-tone refcounting, and flush"
```

---

### Task 4: Range clamping and non-note passthrough

**Files:**
- Modify: `chords.py`
- Test: `tests/test_chords.py`

**Interfaces:**
- Consumes: `_press` from Task 3.
- Produces: final `ChordEngine` behavior — chord tones above 127 dropped; pitchwheel/CC/aftertouch/program change forwarded unchanged. `orchid.py` (Task 5) treats `process`/`flush` as the complete engine API.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_chords.py`)

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_chords.py -v`
Expected: both new tests FAIL (`ValueError` or out-of-range note from mido for note 134; non-note messages currently return `[]`).

- [ ] **Step 3: Implement**

In `chords.py` `_press`, change the interval expansion line:

```python
            notes = [root + i for i in intervals if root + i <= 127]
```

In `process`, change the final `return []` (the fall-through after the `note_off` branch) to:

```python
        return [msg]
```

- [ ] **Step 4: Run full suite to verify everything passes**

Run: `.venv/bin/python -m pytest tests/ -v`
Expected: all 25 tests PASS

- [ ] **Step 5: Commit**

```bash
git add chords.py tests/test_chords.py
git commit -m "feat: clamp out-of-range chord tones, forward non-note messages"
```

---

### Task 5: CLI shell, manual hardware test, README

**Files:**
- Create: `orchid.py`, `README.md`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `ChordEngine(zone_base, channel).process(msg)` and `.flush()` from Tasks 1–4; `ZONE_BASE` constant.
- Produces: `pick_port(names: list[str], wanted: str) -> str` (raises `SystemExit` on no/ambiguous match); `python orchid.py` CLI entry point.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_cli.py`:

```python
import pytest

from orchid import pick_port

PORTS = ["IAC Driver Bus 1", "Arturia KeyStep 32", "USB MIDI Interface"]


def test_pick_port_by_index():
    assert pick_port(PORTS, "1") == "Arturia KeyStep 32"


def test_pick_port_by_name_substring_case_insensitive():
    assert pick_port(PORTS, "keystep") == "Arturia KeyStep 32"


def test_pick_port_no_match_exits():
    with pytest.raises(SystemExit):
        pick_port(PORTS, "moog")


def test_pick_port_ambiguous_match_exits():
    with pytest.raises(SystemExit):
        pick_port(PORTS, "i")  # matches all three


def test_pick_port_index_out_of_range_exits():
    with pytest.raises(SystemExit):
        pick_port(PORTS, "9")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_cli.py -v`
Expected: FAIL/ERROR with `ModuleNotFoundError: No module named 'orchid'`

- [ ] **Step 3: Implement**

Create `orchid.py`:

```python
#!/usr/bin/env python3
"""Orchid-style chord processor: hold a modifier key, play a root, get a chord."""

import argparse

import mido

from chords import ChordEngine, ZONE_BASE


def pick_port(names, wanted):
    """Resolve a port by numeric index or case-insensitive name substring."""
    if wanted.isdigit():
        index = int(wanted)
        if 0 <= index < len(names):
            return names[index]
        raise SystemExit(f"port index {wanted} out of range (0-{len(names) - 1})")
    matches = [n for n in names if wanted.lower() in n.lower()]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise SystemExit(f"no port matching {wanted!r}")
    raise SystemExit(f"{wanted!r} matches several ports: {matches}")


def list_ports():
    print("Inputs:")
    for i, name in enumerate(mido.get_input_names()):
        print(f"  {i}: {name}")
    print("Outputs:")
    for i, name in enumerate(mido.get_output_names()):
        print(f"  {i}: {name}")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--in", dest="in_port",
                        help="input port (number or name substring)")
    parser.add_argument("--out", dest="out_port",
                        help="output port (number or name substring)")
    parser.add_argument("--base", type=int, default=ZONE_BASE,
                        help="lowest note of the modifier zone (default %(default)s)")
    parser.add_argument("--channel", type=int, default=1, choices=range(1, 17),
                        metavar="1-16", help="output MIDI channel (default %(default)s)")
    args = parser.parse_args(argv)

    if not args.in_port or not args.out_port:
        list_ports()
        parser.exit(message="\nRun again with --in and --out.\n")

    in_name = pick_port(mido.get_input_names(), args.in_port)
    out_name = pick_port(mido.get_output_names(), args.out_port)
    engine = ChordEngine(zone_base=args.base, channel=args.channel - 1)

    with mido.open_input(in_name) as inport, mido.open_output(out_name) as outport:
        print(f"orchid: {in_name} -> {out_name} (Ctrl+C to quit)")
        try:
            for msg in inport:
                for out in engine.process(msg):
                    outport.send(out)
        except KeyboardInterrupt:
            pass
        finally:
            for out in engine.flush():
                outport.send(out)
            print("\nbye")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run the full suite**

Run: `.venv/bin/python -m pytest tests/ -v`
Expected: all 30 tests PASS

- [ ] **Step 5: Smoke-test port listing**

Run: `.venv/bin/python orchid.py`
Expected: prints `Inputs:` / `Outputs:` lists of the Mac's CoreMIDI ports (contents depend on connected gear; IAC bus appears if enabled in Audio MIDI Setup) and exits with the "Run again with --in and --out." message. No traceback.

- [ ] **Step 6: Write README**

Create `README.md`:

```markdown
# orchid

A DIY software take on the Telepathic Instruments Orchid: hold a chord-quality
key in your MIDI keyboard's bottom octave, play a root note, and the full chord
is sent to your synth.

## Setup

    python3 -m venv .venv
    .venv/bin/python -m pip install -r requirements.txt

## Run

    .venv/bin/python orchid.py                  # list MIDI ports
    .venv/bin/python orchid.py --in keystep --out "usb midi"

Options: `--base N` sets the lowest note of the 12-key modifier zone
(default 36 = C2 — set this to your keyboard's bottom key); `--channel 1-16`
sets the output channel (default 1).

## Modifier keys (bottom octave, relative to --base)

| Key | Chord | Key | Chord |
|-----|-------|-----|-------|
| C   | major | F#  | sus2  |
| C#  | minor | G   | dim   |
| D   | maj7  | G#  | aug   |
| D#  | min7  | A   | add9  |
| E   | dom7  | A#,B | (unassigned) |

No modifier held = notes pass through unchanged. Ctrl+C sends note-offs for
everything before exiting. Chord map lives in `CHORD_MAP` in `chords.py` —
edit to taste.
```

- [ ] **Step 7: Commit**

```bash
git add orchid.py tests/test_cli.py README.md
git commit -m "feat: CLI shell with port selection, plus README"
```

- [ ] **Step 8: Manual integration test (with the user / their hardware)**

1. Connect the MIDI keyboard and interface, run `.venv/bin/python orchid.py` to find port names.
2. Run with `--in <keyboard> --out <interface>` (and `--base` set to the keyboard's true bottom key if it isn't 36).
3. Verify: bare notes play single notes; holding bottom-octave C + a root plays a major chord; switching modifiers mid-hold works; releasing keys leaves no stuck notes; Ctrl+C silences everything.

This step needs the user at the hardware — report readiness and hand off rather than simulating it.
