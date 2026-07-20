# Settings Window + Self-Update — Design

**Date:** 2026-07-20
**Status:** Approved

## Purpose

Cmd+, opens a Settings window showing the current version; the app checks a
public GitHub repo (`gleyzeddonut/orchid`, chosen by the user) for a newer
version and offers a one-click update.

## Versioning

- `VERSION` file at repo root (starts at `1.0.0`), copied into the bundle by
  `build_app.sh`. Bump it whenever a change should reach other machines.
- Published source of truth: `main` branch on GitHub; the app reads
  `https://raw.githubusercontent.com/gleyzeddonut/orchid/main/VERSION`.

## Components

### 1. `update.py` (new, bundled)
- `parse_version("1.2.3") -> (1,2,3)` (malformed → `(0,)`),
  `is_newer(candidate, current)` — tuple comparison; unit-tested.
- `local_version()` — reads `VERSION` next to the running code.
- `fetch_remote_version() -> str | None` — HTTPS GET with 10s timeout;
  None on any network error.
- `download_update(dest_dir=UPDATE_DIR)` — downloads all app files
  (`gui.py chords.py settings.py update.py requirements.txt VERSION`) from
  raw.githubusercontent; stages everything in memory first so a mid-download
  failure writes nothing. `UPDATE_DIR = ~/Library/Application
  Support/Orchid/app`.

### 2. GUI: menu + Settings window
- `main()` now installs a main menu (missing until now): app menu with
  "Settings…" (Cmd+,) targeting the controller and "Quit Orchid" (Cmd+Q).
- Settings window (320×150, titled/closable, `setReleasedWhenClosed_(False)`,
  lazily built): "Orchid version X.Y.Z" label, a status line, and an Update
  button (hidden by default).
- Opening Settings triggers an async check (background `threading.Thread`,
  results marshaled via `AppHelper.callAfter`): "Checking for updates…" →
  "You're up to date." / "Update available: X" (+ visible "Update to X"
  button) / "Could not check for updates (offline?)".
- Update button: downloads to `UPDATE_DIR`, then `pip install -r` the new
  requirements into the running venv (subprocess, non-fatal if it fails),
  then tells the user to quit and reopen. Errors surface in the status line.

### 3. Launcher
- After venv health check: run from `UPDATE_DIR` instead of
  `Contents/Resources` **iff** `UPDATE_DIR/VERSION` parses strictly newer
  than the bundle's (python one-liner comparison). An AirDropped newer bundle
  therefore beats a stale downloaded update automatically.

### 4. Publishing
- Create public repo `gleyzeddonut/orchid`, push `main`. Future flow: change
  code → bump `VERSION` → commit to main → push → `./build_app.sh` locally;
  other machines see "Update available".

## Error handling
- No network → friendly status, app fully usable.
- Partial download → nothing written (all-or-nothing staging).
- Malformed VERSION anywhere → treated as 0.0.0, never crashes.

## Testing
- Unit: parse_version/is_newer edge cases, local_version reads the repo's
  VERSION.
- Live: after push, curl the raw VERSION URL; import smoke test; visual
  check of menu/settings on the user's machine.
