#!/bin/bash
# Copy the app's Python sources into the bundle and (re)sign it.
# Run after any change to gui.py, chords.py, settings.py, requirements.txt,
# or the launcher script.
set -e
cd "$(dirname "$0")"
RES=Orchid.app/Contents/Resources
mkdir -p "$RES"
cp gui.py chords.py settings.py requirements.txt "$RES/"
chmod +x Orchid.app/Contents/MacOS/orchid
ID="$(security find-identity -v -p codesigning 2>/dev/null \
      | awk -F'"' '/Developer ID Application/ {print $2; exit}')"
codesign --force --deep -s "${ID:--}" Orchid.app
echo "Built and signed Orchid.app${ID:+ ($ID)}"
