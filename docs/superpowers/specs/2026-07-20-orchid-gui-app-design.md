# Orchid GUI App — Design

**Date:** 2026-07-20
**Status:** Approved

## Purpose

Make the existing chord processor launchable by double-clicking an app icon —
no terminal commands. A small window handles port selection, start/stop, and
status; settings persist between launches.

## Decisions made during brainstorming

- **App style:** a small control window (tkinter — ships with Python, no new
  dependencies), not a headless auto-launcher or a menu-bar app.
- **Packaging:** a plain `Orchid.app` bundle committed to the repo (an .app is
  just a folder with `Info.plist` + an executable script). It travels with the
  repo to the studio computer and bootstraps itself there. py2app/PyInstaller
  (per-machine rebuilds, heavy tooling) and Automator/Platypus (external tool,
  logic hidden outside git) were ruled out.
- The CLI `orchid.py` keeps working unchanged.

## Components

### 1. `chords.py` — one small addition
- `CHORD_NAMES: dict[int, str]` mapping zone offsets to quality names
  ("major", "minor", "maj7", "min7", "dom7", "sus4", "sus2", "dim", "aug",
  "add9"), kept alongside `CHORD_MAP`.
- `ChordEngine.current_quality` property: the name of the newest held
  modifier's quality, or `None` when no modifier is held (passthrough).
- No other engine changes.

### 2. `settings.py` — persisted GUI settings
- Stores `settings.json` next to the code (git-ignored).
- Keys and defaults: `in_port: ""`, `out_port: ""`, `base: 36`, `channel: 1`
  (channel is user-facing 1–16).
- `load()` returns defaults merged with whatever valid keys the file has;
  a missing or corrupt file yields pure defaults (never raises).
- `save(settings)` writes pretty-printed JSON.

### 3. `gui.py` — the window
- tkinter window titled "Orchid":
  - **MIDI In** and **MIDI Out** dropdowns (read-only comboboxes) listing
    current ports, plus a **Refresh** button that re-scans.
  - **Base note** and **Channel** entry fields (integers; channel 1–16).
  - **Start/Stop** toggle button.
  - **Status line**: "stopped" / "running" and, while running with a modifier
    held, the active quality (e.g. "running — min7").
- On launch: load settings; pre-select saved ports if currently present.
- **Start:** validate selections (both ports chosen, base 0–116 so the 12-key zone stays in MIDI range, channel
  1–16 — invalid input shows an error dialog and stays stopped), save
  settings, open the output port, then open the input port in mido callback
  mode with a fresh `ChordEngine(zone_base, channel-1)`.
- **Callback path (runs on mido's thread):** each incoming message goes
  through `engine.process()`, results are sent to the output port, and the
  status label is updated via `root.after(0, ...)` (tkinter is not
  thread-safe; only the main thread touches widgets).
- **Stop:** close the input port first (no more callbacks), send
  `engine.flush()` note-offs to the output, close the output. Same
  no-stuck-notes guarantee as the CLI.
- **Window close:** stop (if running), then destroy.
- Port-open failures show an error dialog and return to stopped state.

### 4. `Orchid.app/` — committed launcher bundle
- `Contents/Info.plist`: minimal plist (name Orchid, executable `orchid`).
- `Contents/MacOS/orchid`: executable bash script that:
  1. Resolves the repo root as the bundle's parent directory.
  2. If `.venv/bin/python` is missing, creates the venv and installs
     `requirements.txt` (first launch on a new machine).
  3. `exec`s `.venv/bin/python gui.py`.
- Git preserves the executable bit, so the bundle works after clone/copy.
- README notes: first open on a new machine may require right-click → Open
  (unsigned app, Gatekeeper), and the bundled script assumes `python3` with
  tkinter is available (true for python.org and Apple CLT Python).

## Error handling summary
- Corrupt/missing settings → defaults, no crash.
- No ports selected / invalid base or channel → dialog, stays stopped.
- Port open failure → dialog, stays stopped.
- Stop/close always flushes note-offs before releasing the output port.

## Testing
- Unit tests: `CHORD_NAMES` coverage of every `CHORD_MAP` key,
  `current_quality` (none held, held, fallback after release), settings
  roundtrip / missing file / corrupt file / unknown-key filtering.
- GUI: `import gui` smoke test (no mainloop); real window verified by
  launching. Port dropdowns will be empty on the dev machine (no gear) —
  full check happens on the studio computer.

## Out of scope
- Menu bar mode, standalone signed/packaged .app, editing the chord map from
  the GUI, MIDI activity meters.
