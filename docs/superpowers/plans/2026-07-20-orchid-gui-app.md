# Orchid GUI App Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A double-clickable `Orchid.app` that opens a small control window (port pickers, start/stop, status) around the existing `ChordEngine`, with settings remembered between launches.

**Architecture:** Three thin layers on the untouched engine: `settings.py` (JSON persistence), `gui.py` (tkinter window + mido callback-mode I/O), and a committed `Orchid.app` bundle whose shell script bootstraps the venv and launches `gui.py`. Spec: `docs/superpowers/specs/2026-07-20-orchid-gui-app-design.md`.

**Tech Stack:** Python 3.10+, tkinter (stdlib), existing `mido`/`python-rtmidi`, `pytest`.

## Global Constraints

- No new dependencies — `requirements.txt` is unchanged.
- All commands run from the repo root via `.venv/bin/python`.
- `settings.json` is git-ignored (it's per-machine state).
- Only the main tkinter thread touches widgets; mido's callback thread may send MIDI but must marshal UI updates through `root.after(0, ...)`.
- Stop/close always: close input port first, then send `engine.flush()` to the output, then close the output (spec: "Error handling summary").
- Channel is user-facing 1–16 in the GUI/settings; `ChordEngine` gets `channel - 1`. Base note valid range 0–116.
- CLI `orchid.py` behavior is unchanged.
- Commit after every task with the exact message given in the task.

---

### Task 1: Chord quality names on the engine

**Files:**
- Modify: `chords.py` (add `CHORD_NAMES` after `CHORD_MAP`; add property to `ChordEngine`)
- Test: `tests/test_chords.py`

**Interfaces:**
- Consumes: existing `ChordEngine`, `CHORD_MAP`, `_held_modifiers` (newest-last list).
- Produces: `CHORD_NAMES: dict[int, str]` and `ChordEngine.current_quality` property → `str | None`. Task 3's GUI reads `current_quality` after each processed message.

- [ ] **Step 1: Write the failing tests**

In `tests/test_chords.py`, change the import line to:

```python
from chords import CHORD_MAP, CHORD_NAMES, ChordEngine
```

and append:

```python
def test_every_chord_has_a_name():
    assert set(CHORD_NAMES) == set(CHORD_MAP)


def test_current_quality_tracks_held_modifiers():
    engine = ChordEngine()
    assert engine.current_quality is None
    engine.process(on(36))
    assert engine.current_quality == "major"
    engine.process(on(37))
    assert engine.current_quality == "minor"
    engine.process(off(37))
    assert engine.current_quality == "major"
    engine.process(off(36))
    assert engine.current_quality is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_chords.py -q`
Expected: collection ERROR — `ImportError: cannot import name 'CHORD_NAMES'`

- [ ] **Step 3: Implement**

In `chords.py`, directly after the `CHORD_MAP` dict add:

```python
# Display names for the qualities in CHORD_MAP, keyed by the same offsets.
CHORD_NAMES = {
    0: "major", 1: "minor", 2: "maj7", 3: "min7", 4: "dom7",
    5: "sus4", 6: "sus2", 7: "dim", 8: "aug", 9: "add9",
}
```

In `ChordEngine`, add after `process`:

```python
    @property
    def current_quality(self):
        """Name of the newest held modifier's quality, or None in passthrough."""
        if self._held_modifiers:
            return CHORD_NAMES.get(self._held_modifiers[-1])
        return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: 32 passed

- [ ] **Step 5: Commit**

```bash
git add chords.py tests/test_chords.py
git commit -m "feat: expose current chord quality name on engine"
```

---

### Task 2: Settings persistence

**Files:**
- Create: `settings.py`
- Test: `tests/test_settings.py`
- Modify: `.gitignore` (add `settings.json`)

**Interfaces:**
- Produces: `settings.DEFAULTS` (`{"in_port": "", "out_port": "", "base": 36, "channel": 1}`), `settings.load(path=SETTINGS_PATH) -> dict`, `settings.save(settings_dict, path=SETTINGS_PATH) -> None`, `settings.SETTINGS_PATH` (repo-local `settings.json`). Task 3 calls `load()`/`save()` with no path argument.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_settings.py`:

```python
import json

import settings


def test_load_missing_file_returns_defaults(tmp_path):
    assert settings.load(tmp_path / "nope.json") == settings.DEFAULTS


def test_load_corrupt_file_returns_defaults(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text("{not json")
    assert settings.load(path) == settings.DEFAULTS


def test_save_load_roundtrip(tmp_path):
    path = tmp_path / "settings.json"
    data = {"in_port": "KeyStep", "out_port": "USB MIDI", "base": 48, "channel": 3}
    settings.save(data, path)
    assert settings.load(path) == data


def test_load_ignores_unknown_keys_and_fills_missing(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"in_port": "KeyStep", "bogus": 1}))
    loaded = settings.load(path)
    assert loaded["in_port"] == "KeyStep"
    assert loaded["base"] == settings.DEFAULTS["base"]
    assert "bogus" not in loaded
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_settings.py -q`
Expected: collection ERROR — `ModuleNotFoundError: No module named 'settings'`

- [ ] **Step 3: Implement**

Create `settings.py`:

```python
"""Persisted GUI settings (port names, zone base, user-facing channel 1-16)."""

import json
from pathlib import Path

SETTINGS_PATH = Path(__file__).resolve().parent / "settings.json"
DEFAULTS = {"in_port": "", "out_port": "", "base": 36, "channel": 1}


def load(path=SETTINGS_PATH):
    """Defaults merged with whatever valid keys the file has; never raises."""
    try:
        data = json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return dict(DEFAULTS)
    merged = dict(DEFAULTS)
    if isinstance(data, dict):
        merged.update({k: data[k] for k in DEFAULTS if k in data})
    return merged


def save(values, path=SETTINGS_PATH):
    Path(path).write_text(json.dumps(values, indent=2))
```

Append `settings.json` to `.gitignore`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: 36 passed

- [ ] **Step 5: Commit**

```bash
git add settings.py tests/test_settings.py .gitignore
git commit -m "feat: settings persistence for the GUI"
```

---

### Task 3: The tkinter window

**Files:**
- Create: `gui.py`

**Interfaces:**
- Consumes: `ChordEngine(zone_base, channel).process(msg)/.flush()/.current_quality` (Task 1), `settings.load()/save()` (Task 2), `mido.get_input_names()/get_output_names()/open_input(name, callback=...)/open_output(name)`.
- Produces: `gui.main()` entry point (Task 4's app bundle runs `gui.py`); `OrchidApp` class.

- [ ] **Step 1: Implement**

(GUI code is verified by launching, not unit tests — the logic worth testing
already lives in `chords.py`/`settings.py`.) Create `gui.py`:

```python
"""Tkinter control window for the Orchid chord processor."""

import tkinter as tk
from tkinter import messagebox, ttk

import mido

import settings
from chords import ChordEngine


class OrchidApp:
    def __init__(self, root):
        self.root = root
        self.engine = None
        self.inport = None
        self.outport = None
        self._build()
        self._load_settings()

    def _build(self):
        self.root.title("Orchid")
        self.root.resizable(False, False)
        frame = ttk.Frame(self.root, padding=12)
        frame.grid(sticky="nsew")

        ttk.Label(frame, text="MIDI In").grid(row=0, column=0, sticky="w")
        self.in_box = ttk.Combobox(frame, state="readonly", width=32)
        self.in_box.grid(row=0, column=1, columnspan=2, pady=2)

        ttk.Label(frame, text="MIDI Out").grid(row=1, column=0, sticky="w")
        self.out_box = ttk.Combobox(frame, state="readonly", width=32)
        self.out_box.grid(row=1, column=1, columnspan=2, pady=2)

        ttk.Button(frame, text="Refresh", command=self.refresh_ports).grid(
            row=2, column=1, sticky="w", pady=2)

        ttk.Label(frame, text="Base note").grid(row=3, column=0, sticky="w")
        self.base_var = tk.StringVar()
        ttk.Entry(frame, textvariable=self.base_var, width=6).grid(
            row=3, column=1, sticky="w", pady=2)

        ttk.Label(frame, text="Channel").grid(row=4, column=0, sticky="w")
        self.channel_var = tk.StringVar()
        ttk.Entry(frame, textvariable=self.channel_var, width=6).grid(
            row=4, column=1, sticky="w", pady=2)

        self.toggle_btn = ttk.Button(frame, text="Start", command=self.toggle)
        self.toggle_btn.grid(row=5, column=0, columnspan=3, pady=(10, 4),
                             sticky="ew")

        self.status_var = tk.StringVar(value="stopped")
        ttk.Label(frame, textvariable=self.status_var).grid(
            row=6, column=0, columnspan=3)

        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def _load_settings(self):
        stored = settings.load()
        self.base_var.set(str(stored["base"]))
        self.channel_var.set(str(stored["channel"]))
        self.refresh_ports()
        if stored["in_port"] in self.in_box["values"]:
            self.in_box.set(stored["in_port"])
        if stored["out_port"] in self.out_box["values"]:
            self.out_box.set(stored["out_port"])

    def refresh_ports(self):
        self.in_box["values"] = mido.get_input_names()
        self.out_box["values"] = mido.get_output_names()

    def toggle(self):
        if self.inport is None:
            self.start()
        else:
            self.stop()

    def _validated(self):
        in_port, out_port = self.in_box.get(), self.out_box.get()
        if not in_port or not out_port:
            messagebox.showerror("Orchid", "Pick both a MIDI In and MIDI Out port.")
            return None
        try:
            base = int(self.base_var.get())
            channel = int(self.channel_var.get())
        except ValueError:
            messagebox.showerror("Orchid", "Base note and channel must be numbers.")
            return None
        if not 0 <= base <= 116:
            messagebox.showerror("Orchid", "Base note must be 0-116.")
            return None
        if not 1 <= channel <= 16:
            messagebox.showerror("Orchid", "Channel must be 1-16.")
            return None
        return {"in_port": in_port, "out_port": out_port,
                "base": base, "channel": channel}

    def start(self):
        config = self._validated()
        if config is None:
            return
        settings.save(config)
        self.engine = ChordEngine(zone_base=config["base"],
                                  channel=config["channel"] - 1)
        try:
            self.outport = mido.open_output(config["out_port"])
            self.inport = mido.open_input(config["in_port"],
                                          callback=self._on_message)
        except (OSError, ValueError) as exc:
            self._close_ports()
            messagebox.showerror("Orchid", f"Could not open MIDI ports:\n{exc}")
            return
        self.toggle_btn.config(text="Stop")
        self.status_var.set("running")

    def _on_message(self, msg):
        # mido's callback thread: send MIDI here, but only the main thread
        # may touch widgets.
        engine, outport = self.engine, self.outport
        if engine is None or outport is None:
            return
        for out in engine.process(msg):
            outport.send(out)
        quality = engine.current_quality
        text = f"running — {quality}" if quality else "running"
        self.root.after(0, self.status_var.set, text)

    def stop(self):
        self._close_ports()
        self.toggle_btn.config(text="Start")
        self.status_var.set("stopped")

    def _close_ports(self):
        inport, self.inport = self.inport, None
        if inport is not None:
            inport.close()
        engine, self.engine = self.engine, None
        outport, self.outport = self.outport, None
        if outport is not None:
            if engine is not None:
                for out in engine.flush():
                    outport.send(out)
            outport.close()

    def on_close(self):
        self._close_ports()
        self.root.destroy()


def main():
    root = tk.Tk()
    OrchidApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Import smoke test + full suite**

Run: `.venv/bin/python -c "import gui; print('gui imports ok')"`
Expected: `gui imports ok` (no window opens — mainloop only runs under `main()`)

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: 36 passed

- [ ] **Step 3: Launch the window briefly**

Run: `.venv/bin/python gui.py` (then close the window, or Ctrl+C)
Expected: an "Orchid" window with In/Out dropdowns (empty on a gear-less
machine), Refresh, Base note 36, Channel 1, Start button, "stopped" status.
Clicking Start with no ports shows the "Pick both..." error dialog. If the
shell is headless/sandboxed and tkinter cannot open a display, note it and
defer this check to the user's machine.

- [ ] **Step 4: Commit**

```bash
git add gui.py
git commit -m "feat: tkinter control window"
```

---

### Task 4: Orchid.app bundle + README

**Files:**
- Create: `Orchid.app/Contents/Info.plist`, `Orchid.app/Contents/MacOS/orchid` (executable)
- Modify: `README.md`

**Interfaces:**
- Consumes: `gui.py` entry point (Task 3), `requirements.txt`.
- Produces: double-clickable `Orchid.app` at repo root.

- [ ] **Step 1: Create the bundle**

`Orchid.app/Contents/Info.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key><string>Orchid</string>
    <key>CFBundleIdentifier</key><string>local.orchid</string>
    <key>CFBundleVersion</key><string>1.0</string>
    <key>CFBundlePackageType</key><string>APPL</string>
    <key>CFBundleExecutable</key><string>orchid</string>
</dict>
</plist>
```

`Orchid.app/Contents/MacOS/orchid`:

```bash
#!/bin/bash
# Orchid launcher: the repo root is the directory containing this .app bundle.
set -e
REPO="$(cd "$(dirname "$0")/../../.." && pwd)"
cd "$REPO"
if [ ! -x .venv/bin/python ]; then
    /usr/bin/env python3 -m venv .venv
    .venv/bin/python -m pip install -r requirements.txt
fi
exec .venv/bin/python gui.py
```

Then: `chmod +x Orchid.app/Contents/MacOS/orchid`

- [ ] **Step 2: Verify the launcher script logic**

Run: `Orchid.app/Contents/MacOS/orchid & sleep 3; kill %1`
Expected: no venv rebuild (it exists), the Orchid window appears and is killed
after 3s. On a headless shell, tkinter may fail to open a display — then
verify only that the script reaches Python (error comes from tkinter, not
bash), and defer the visual check to the user's machine.

- [ ] **Step 3: Update README**

In `README.md`, insert after the `## Setup` section:

```markdown
## App

Double-click `Orchid.app` to open the control window — pick your MIDI In/Out,
hit Start, play. Ports and settings are remembered between launches. On a new
machine the first launch builds the environment automatically (give it a
minute) — and since the app is unsigned, use right-click → Open the first
time if macOS complains.
```

- [ ] **Step 4: Full suite one more time**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: 36 passed

- [ ] **Step 5: Commit**

```bash
git add Orchid.app README.md
git commit -m "feat: double-clickable Orchid.app launcher"
```
