# Native Cocoa GUI — Design

**Date:** 2026-07-20
**Status:** Approved

## Purpose

Replace the tkinter window with a native macOS (Cocoa) window via PyObjC.
Apple's system Python ships Tk 8.5 (deprecated, 2007-era), which renders a
blank window on current macOS — the fourth tkinter failure this project has
hit (missing `_tkinter` in Homebrew Python, ancient system Tk, architecture
quirks, blank rendering). PyObjC installs from wheels like any pip package,
so the app stays fully self-contained, and the window becomes a real native
macOS window.

## Changes

### 1. `requirements.txt`
- Add `pyobjc-framework-Cocoa` (pulls `pyobjc-core`). No other deps change.

### 2. `gui.py` — full rewrite, same feature set
- Same controls as before: MIDI In / MIDI Out popup buttons, Refresh button,
  Base note and Channel text fields, Start/Stop toggle button, status line
  showing "stopped" / "running" / "running — <quality>".
- Same behavior contract as the tkinter version: settings loaded on launch
  and saved on Start; saved ports pre-selected when present; validation
  errors via NSAlert (both ports chosen, base 0–116, channel 1–16); port-open
  failure alerts and stays stopped; Stop and window-close close the input
  port first, flush note-offs to the output, close the output; closing the
  window quits the app.
- Structure: a pure function `validate_config(in_port, out_port, base_text,
  channel_text) -> (config_dict | None, error_message | None)` holds the
  validation logic and is unit-tested; an `OrchidController(NSObject)` class
  builds the window (fixed-size ~400×240, titled/closable/miniaturizable),
  wires target/action handlers, and owns engine + ports.
- Threading: mido's callback thread sends MIDI directly; UI updates go
  through `PyObjCTools.AppHelper.callAfter` (main-thread marshaling).
  Event loop via `AppHelper.runEventLoop()`; window close stops ports then
  `AppHelper.stopEventLoop()`.

### 3. Launcher (`Orchid.app/Contents/MacOS/orchid`)
- Health check becomes `import mido, rtmidi, AppKit` (tkinter gone). An
  existing tkinter-era venv fails this check and self-rebuilds with the new
  requirements — no user action needed.
- Python discovery no longer probes for tkinter — any working `python3`
  qualifies (`/usr/bin/python3` first, then PATH). "Operation not permitted"
  detection retained as defensive diagnostics. Alert text drops the tkinter
  mention.

### 4. Docs
- README Setup note unchanged; App section already describes the standalone
  behavior. `build_app.sh` unchanged (copies the same four files).

## Not changing
- `chords.py`, `settings.py`, `orchid.py` (CLI), all existing tests,
  `build_app.sh`, bundle layout.

## Testing
- Unit: `validate_config` (valid config passthrough + each rejection).
- `import gui` smoke test (AppKit imports headless; window creation cannot
  render in the sandboxed shell — visual check is the user's double-click).
- Full suite green; `./build_app.sh` re-run and signature verified.
