# Self-Contained Orchid.app — Design

**Date:** 2026-07-20
**Status:** Approved

## Purpose

Remove the need for any macOS privacy grant. The current app is a launcher
that reads code and a venv from the repo folder; when the repo sits in a
TCC-protected location (Documents/Desktop/Downloads) the app is silently
denied and cannot start. Signed apps get no prompt either (verified
empirically). A self-contained app only reads its own bundle and
`~/Library/Application Support` — neither is protected, so it runs from
anywhere with zero permissions.

## Changes

### 1. Bundle layout
- `Orchid.app/Contents/Resources/` holds copies of `gui.py`, `chords.py`,
  `settings.py`, `requirements.txt`, made by the build script. The directory
  is git-ignored (build artifact; sources of truth stay at repo root where
  the tests live).

### 2. Runtime state → Application Support
- venv: `~/Library/Application Support/Orchid/venv`, built by the launcher on
  first run (or rebuilt whenever `import tkinter, mido, rtmidi` fails in it —
  this also self-heals wrong-architecture and stale-requirements venvs).
- `settings.py` default path becomes
  `~/Library/Application Support/Orchid/settings.json`; `save()` creates
  parent directories. Load/save keep their injectable `path` parameter and
  never-raise behavior.

### 3. Launcher rewrite (`Orchid.app/Contents/MacOS/orchid`)
- Resolves `Resources/` relative to itself; never touches the repo.
- Probes venv health; on failure finds a tkinter-capable Python
  (`/usr/bin/python3`, then `python3` on PATH), rebuilds the venv in
  Application Support, installs `Resources/requirements.txt`, and verifies
  the imports before launching.
- Alerts (osascript) on: no tkinter Python (CLT hint), TCC denial (kept as
  defensive diagnostics), or a failed environment build. Log:
  `/tmp/orchid-launch.log`.
- `cd`s into `Resources/` and execs `venv/bin/python gui.py` so gui.py's
  sibling imports (`chords`, `settings`) resolve.

### 4. `build_app.sh` (repo root)
- Copies the four files into `Contents/Resources/`, ensures the launcher is
  executable, and codesigns the bundle: first "Developer ID Application"
  identity in the keychain if present, otherwise ad-hoc. Run after any code
  change to refresh the app.

### 5. README
- App section rewritten: app is standalone, runs from anywhere (including
  Documents), first launch builds its environment (~1 min), later launches
  are instant. Copying to another Mac = copy `Orchid.app` only (AirDrop /
  Finder copy preserves the signature; git clone requires running
  `./build_app.sh` once). Full Disk Access is not needed and can be revoked.

## Not changing
- `gui.py`, `chords.py`, `orchid.py` (CLI), tests, and the repo `.venv`
  dev workflow are untouched. `gui.py` finds `settings.py` by import, so the
  settings-location change is transparent to it.

## Testing
- Unit: `save()` creates missing parent directories (plus existing settings
  tests still pass — they inject `tmp_path`).
- Build: run `./build_app.sh`; verify Resources contents and
  `codesign --verify`.
- Launch logic: run the launcher with `HOME` pointed at a scratch dir —
  it must build a fresh venv there and reach "launching gui.py" in the log
  (the Tk window itself cannot render in the sandboxed shell; visual check
  is the user's double-click).
