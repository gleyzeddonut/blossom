# orchid

A DIY software take on the Telepathic Instruments Orchid: hold a chord-quality
key in your MIDI keyboard's bottom octave, play a root note, and the full chord
is sent to your synth.

## Setup

    python3 -m venv .venv
    .venv/bin/python -m pip install -r requirements.txt

## App

Double-click `Orchid.app` — it is fully self-contained and runs from
anywhere (Documents, /Applications, wherever). Pick your MIDI In/Out, hit
Start, play. The first launch on a machine builds the app's Python
environment in `~/Library/Application Support/Orchid` (give it a minute);
after that it opens instantly. Settings are remembered there too. No
privacy permissions are needed.

To put it on another Mac, copy just `Orchid.app` (AirDrop or Finder copy
keeps the code signature; after a plain `git clone`, run `./build_app.sh`
once to assemble and sign the app). After changing any of the Python
sources, run `./build_app.sh` to refresh the bundle.

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
