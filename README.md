# orchid

A DIY software take on the Telepathic Instruments Orchid: hold a chord-quality
key in your MIDI keyboard's bottom octave, play a root note, and the full chord
is sent to your synth.

## Setup

    python3 -m venv .venv
    .venv/bin/python -m pip install -r requirements.txt

## App

**Where to keep this folder:** anywhere *except* Documents, Desktop, or
Downloads (and their iCloud equivalents). macOS privacy protection blocks
unsigned apps from reading those folders, so the app cannot start there —
your home folder (e.g. `~/orchid`) works great. The launcher will tell you
if this is the problem. (Alternative: add Orchid.app to Full Disk Access in
System Settings → Privacy & Security.)

Double-click `Orchid.app` to open the control window — pick your MIDI In/Out,
hit Start, play. Ports and settings are remembered between launches. On a new
machine the first launch builds the environment automatically (give it a
minute) — and since the app is unsigned, use right-click → Open the first
time if macOS complains.

## Run (CLI)

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
