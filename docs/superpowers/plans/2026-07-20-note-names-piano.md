# Note Names + Piano View Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Base-note field in note names (C2, F#1) and a live piano-keyboard strip lighting up sounding notes.

**Architecture:** Per spec `docs/superpowers/specs/2026-07-20-note-names-piano-design.md`. Pure helpers in `chords.py`, validation change + `PianoView(NSView)` in `gui.py`.

**Tech Stack:** unchanged (no new dependencies).

## Global Constraints

- Middle C = C4 = MIDI 60. Settings keep storing base as an integer.
- UI updates from the mido callback thread only via `AppHelper.callAfter`.
- PyObjC: any non-selector method on an NSObject subclass gets `@objc.python_method`.
- Run `./build_app.sh` after code changes.
- Commit after each task with the exact message given.

---

### Task 1: note_name / parse_note / sounding_notes

**Files:**
- Modify: `chords.py`
- Test: `tests/test_chords.py`

**Interfaces:**
- Produces: `note_name(n: int) -> str`; `parse_note(text) -> int | None`;
  `ChordEngine.sounding_notes -> list[int]` (sorted). Task 2/3 consume all three.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_chords.py`; add `note_name`, `parse_note` to the chords import)

```python
@pytest.mark.parametrize("num,name", [
    (60, "C4"), (36, "C2"), (0, "C-1"), (127, "G8"), (61, "C#4"), (95, "B6"),
])
def test_note_name(num, name):
    assert note_name(num) == name


@pytest.mark.parametrize("text,num", [
    ("C4", 60), ("c2", 36), ("F#1", 42), ("Gb1", 42), ("C-1", 0), ("G8", 127),
    ("36", 36), ("0", 0),
])
def test_parse_note_accepts_names_and_integers(text, num):
    assert parse_note(text) == num


@pytest.mark.parametrize("text", ["", "H2", "C", "4C", "C#", "G9", "C10", "-1", "128", "C##2", None])
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
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_chords.py -q`
Expected: collection ERROR — cannot import `note_name`.

- [ ] **Step 3: Implement** (in `chords.py`, after `CHORD_NAMES`; `import re` at top)

```python
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
    semitone = NOTE_NAMES.index(letter.upper()) if letter.upper() in NOTE_NAMES \
        else {"D": 2, "E": 4, "G": 7, "A": 9, "B": 11}[letter.upper()]
    num = semitone + _ACCIDENTALS[accidental] + (int(octave) + 1) * 12
    return num if 0 <= num <= 127 else None
```

Note: every natural letter (C D E F G A B) appears in `NOTE_NAMES`, so the
`.index()` branch always hits; keep it simple:

```python
    semitone = NOTE_NAMES.index(letter.upper())
```

(drop the dict fallback entirely). And in `ChordEngine`, after
`current_quality`:

```python
    @property
    def sounding_notes(self):
        """Sorted pitches currently sounding at the output."""
        return sorted(self._counts)
```

- [ ] **Step 4: Run full suite**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: 47 + 25 new = 72 passed

- [ ] **Step 5: Commit**

```bash
git add chords.py tests/test_chords.py
git commit -m "feat: note-name helpers and sounding_notes on engine"
```

---

### Task 2: validate_config takes note names

**Files:**
- Modify: `gui.py` (validate_config + settings display), `tests/test_gui.py`

**Interfaces:**
- Consumes: `parse_note`, `note_name` from Task 1.
- Produces: `validate_config` accepting "C2"/"F#1"/"36" for base.

- [ ] **Step 1: Update/extend tests**

In `tests/test_gui.py`: existing base tests change — replace
`test_non_numeric_fields_rejected` and `test_base_out_of_range_rejected` with:

```python
def test_note_name_base_accepted():
    config, err = validate_config("a", "b", "C2", "1")
    assert err is None and config["base"] == 36


def test_bad_base_rejected():
    config, err = validate_config("a", "b", "H7", "1")
    assert config is None and "C-1" in err


@pytest.mark.parametrize("base", ["G9", "117", "C-2"])
def test_base_out_of_range_rejected(base):
    config, err = validate_config("a", "b", base, "1")
    assert config is None and "C-1" in err


def test_non_numeric_channel_rejected():
    config, err = validate_config("a", "b", "C2", "x")
    assert config is None and "Channel" in err
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_gui.py -q`
Expected: new tests FAIL (validate_config rejects "C2").

- [ ] **Step 3: Implement**

In `gui.py`: import `note_name, parse_note` from chords; replace the middle of
`validate_config`:

```python
def validate_config(in_port, out_port, base_text, channel_text):
    """Return (config, None) if inputs are usable, else (None, error message)."""
    if not in_port or not out_port:
        return None, "Pick both a MIDI In and MIDI Out port."
    base = parse_note(base_text)
    if base is None or not 0 <= base <= 116:
        return None, "Base note must be a note between C-1 and G#8 (like C2)."
    try:
        channel = int(str(channel_text))
    except ValueError:
        return None, "Channel must be a number 1-16."
    if not 1 <= channel <= 16:
        return None, "Channel must be a number 1-16."
    return {"in_port": in_port, "out_port": out_port,
            "base": base, "channel": channel}, None
```

In `_load_settings`, display the name:

```python
        self.base_field.setStringValue_(note_name(stored["base"]))
```

- [ ] **Step 4: Run full suite**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: 74 passed (72 + 4 new − 2 replaced)

- [ ] **Step 5: Commit**

```bash
git add gui.py tests/test_gui.py
git commit -m "feat: base note field speaks note names"
```

---

### Task 3: PianoView + layout

**Files:**
- Modify: `gui.py`

**Interfaces:**
- Consumes: `ChordEngine.sounding_notes` (Task 1).
- Produces: `PianoView(NSView)` with `set_sounding(iterable)`.

- [ ] **Step 1: Add PianoView** (in `gui.py`, after `_label`; extend AppKit imports with `NSBezierPath, NSColor, NSView`)

```python
PIANO_LOW, PIANO_HIGH = 24, 96          # C1 .. C7
_WHITE_PCS = {0, 2, 4, 5, 7, 9, 11}     # pitch classes drawn as white keys


class PianoView(NSView):
    def initWithFrame_(self, frame):
        self = objc.super(PianoView, self).initWithFrame_(frame)
        if self is None:
            return None
        self.sounding = set()
        return self

    @objc.python_method
    def set_sounding(self, notes):
        self.sounding = {n for n in notes if PIANO_LOW <= n <= PIANO_HIGH}
        self.setNeedsDisplay_(True)

    def drawRect_(self, rect):
        bounds = self.bounds()
        width, height = bounds.size.width, bounds.size.height
        NSColor.grayColor().set()
        NSBezierPath.fillRect_(bounds)
        whites = [n for n in range(PIANO_LOW, PIANO_HIGH + 1)
                  if n % 12 in _WHITE_PCS]
        key_w = width / len(whites)
        white_x = {}
        x = 0.0
        for n in whites:
            white_x[n] = x
            if n in self.sounding:
                NSColor.systemBlueColor().set()
            else:
                NSColor.whiteColor().set()
            NSBezierPath.fillRect_(NSMakeRect(x + 0.5, 0.5, key_w - 1, height - 1))
            x += key_w
        black_w, black_h = key_w * 0.6, height * 0.6
        for n in range(PIANO_LOW, PIANO_HIGH + 1):
            if n % 12 in _WHITE_PCS:
                continue
            bx = white_x[n - 1] + key_w - black_w / 2
            if n in self.sounding:
                NSColor.systemBlueColor().set()
            else:
                NSColor.blackColor().set()
            NSBezierPath.fillRect_(NSMakeRect(bx, height - black_h, black_w, black_h))
```

- [ ] **Step 2: Grow the window and add the view**

In `_build_window`: window rect becomes `NSMakeRect(0, 0, 420, 330)`; controls
move up (new frames):
- MIDI In label (20, 288, 76, 20), in_pop (100, 284, 300, 26)
- MIDI Out label (20, 254, 76, 20), out_pop (100, 250, 300, 26)
- Refresh (96, 216, 100, 28)
- Base label (20, 186, 76, 20), base_field (100, 182, 60, 24)
- Channel label (185, 186, 64, 20), channel_field (250, 182, 60, 24)
- toggle (20, 142, 380, 32)
- status (20, 116, 380, 20)
- piano (new, before `setDelegate_`):

```python
        self.piano = PianoView.alloc().initWithFrame_(NSMakeRect(20, 16, 380, 88))
        content.addSubview_(self.piano)
```

- [ ] **Step 3: Wire updates**

Replace the end of `_on_message` and add `_update_ui`:

```python
        quality = engine.current_quality
        text = "running — %s" % quality if quality else "running"
        AppHelper.callAfter(self._update_ui, text, engine.sounding_notes)

    @objc.python_method
    def _update_ui(self, text, notes):
        self.status.setStringValue_(text)
        self.piano.set_sounding(notes)
```

In `_stop`, after `setStringValue_("stopped")`: `self.piano.set_sounding([])`.

- [ ] **Step 4: Smoke test, rebuild, full suite**

Run: `.venv/bin/python -c "import gui; print('ok')"`
Expected: `ok`

Run: `.venv/bin/python -m pytest tests/ -q && ./build_app.sh && codesign --verify --deep --strict Orchid.app && echo done`
Expected: 74 passed, built+signed, `done`.

- [ ] **Step 5: Commit**

```bash
git add gui.py
git commit -m "feat: live piano view showing sounding notes"
```
